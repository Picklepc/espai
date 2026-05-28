#!/usr/bin/env python3
"""
ESPAI Fake BMS Simulator

Mimics a Battery Management System node for hub development without hardware.

Usage:
    python fake_bms.py                              # port 8011
    python fake_bms.py --port 8012 --id my-bms
    python fake_bms.py --hub http://localhost:7888 --checkin-interval 15

Simulated data:
  - 4-cell LiFePO4 pack, 12 V nominal
  - Slow discharge cycle (discharges over ~10 min, then switches to charging)
  - Realistic cell-level voltages with small random variance
  - Temperature follows load (rises while discharging, cools while charging)
"""
import argparse
import hashlib
import json
import math
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

_start_time = time.monotonic()
_paired     = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uptime() -> int:
    return int(time.monotonic() - _start_time)


def _make_node_id(seed: str) -> str:
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"bms-{h[:12]}"


# ── BMS simulation ─────────────────────────────────────────────────────────────

CYCLE_SECONDS = 600  # full discharge-charge cycle time


def _bms_state() -> dict:
    """Return simulated BMS readings based on elapsed time."""
    t = _uptime()
    phase = (t % CYCLE_SECONDS) / CYCLE_SECONDS      # 0.0 → 1.0
    charging = phase >= 0.5

    if not charging:
        soc = 100.0 - (phase / 0.5) * 100.0          # 100 % → 0 %
    else:
        soc = ((phase - 0.5) / 0.5) * 100.0          # 0 % → 100 %

    # LiFePO4 voltage curve (simplified): 2.5 V–3.6 V per cell × 4 cells
    cell_v_base = 2.5 + (soc / 100.0) * 1.1
    cells = [round(cell_v_base + random.uniform(-0.005, 0.005), 4) for _ in range(4)]
    pack_voltage = round(sum(cells), 3)

    # Current: negative when discharging, positive when charging
    current = round((random.uniform(0.8, 1.2) if charging else -random.uniform(0.8, 1.2)), 3)

    # Temperature peaks at end of discharge / rises slightly during fast charge
    base_temp = 25.0
    temp_delta = 12.0 * math.sin(phase * math.pi)     # peaks mid-cycle
    temperature = round(base_temp + temp_delta + random.uniform(-0.3, 0.3), 2)

    return {
        "soc_pct":     round(soc, 1),
        "pack_voltage": pack_voltage,
        "current_a":   current,
        "temperature_c": temperature,
        "charging":    charging,
        "cell_voltages": cells,
        "cell_min_v":  min(cells),
        "cell_max_v":  max(cells),
        "cell_delta_v": round(max(cells) - min(cells), 4),
        "cycles":      t // CYCLE_SECONDS,
    }


# ── HTTP handler ───────────────────────────────────────────────────────────────

class BMSHandler(BaseHTTPRequestHandler):
    node_id:   str = "bms-000000000000"
    node_name: str = "fake-bms"
    port:      int = 8011

    def log_message(self, fmt, *args):
        pass  # suppress access logs

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/manifest":
            self._send_json(200, {
                "schema":     "ESPAI.device.v1",
                "id":         self.node_id,
                "name":       self.node_name,
                "board":      "bms-lifepo4-v1",
                "fw_version": "0.1.0",
                "capabilities": {
                    "battery":  True,
                    "ota":      False,
                    "gpio":     False,
                },
            })
        elif self.path == "/api/status":
            bms = _bms_state()
            self._send_json(200, {
                "id":          self.node_id,
                "uptime_s":    _uptime(),
                "heap_free":   random.randint(120000, 180000),
                "ip":          f"127.0.0.1",
                "battery":     bms,
            })
        elif self.path == "/api/bms/data":
            self._send_json(200, _bms_state())
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        if self.path == "/api/checkin":
            self._send_json(200, {"status": "ok", "paired": _paired})
        elif self.path == "/api/reboot":
            self._send_json(200, {"status": "rebooting"})
        else:
            self._send_json(404, {"error": "not found"})


# ── Hub checkin loop ───────────────────────────────────────────────────────────

def _checkin_loop(hub: str, node_id: str, node_name: str, port: int, interval: int) -> None:
    time.sleep(2)  # brief startup delay
    while True:
        try:
            bms = _bms_state()
            payload = json.dumps({
                "id":         node_id,
                "name":       node_name,
                "board":      "bms-lifepo4-v1",
                "fw_version": "0.1.0",
                "ip":         f"127.0.0.1:{port}",
                "capabilities": {"battery": True},
                "battery":    bms,
            }).encode()
            req = urllib.request.Request(
                f"{hub}/api/devices/checkin",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                global _paired
                _paired = data.get("paired", False)
            print(f"[BMS] checked in — SoC {bms['soc_pct']:.1f}% {'charging' if bms['charging'] else 'discharging'}", flush=True)
        except Exception as exc:
            print(f"[BMS] checkin failed: {exc}", flush=True)
        time.sleep(interval)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="ESPAI Fake BMS Simulator")
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--id",   default=None, help="Override node ID")
    ap.add_argument("--name", default="fake-bms")
    ap.add_argument("--hub",  default=None, help="Hub URL for auto-checkin, e.g. http://localhost:7888")
    ap.add_argument("--checkin-interval", type=int, default=15)
    args = ap.parse_args()

    node_id = args.id or _make_node_id(f"bms:{args.port}")

    BMSHandler.node_id   = node_id
    BMSHandler.node_name = args.name
    BMSHandler.port      = args.port

    if args.hub:
        t = threading.Thread(
            target=_checkin_loop,
            args=(args.hub, node_id, args.name, args.port, args.checkin_interval),
            daemon=True,
        )
        t.start()

    server = HTTPServer(("0.0.0.0", args.port), BMSHandler)
    print(f"ESPAI Fake BMS  id={node_id}  port={args.port}", flush=True)
    print(f"  GET  http://localhost:{args.port}/api/manifest", flush=True)
    print(f"  GET  http://localhost:{args.port}/api/status", flush=True)
    print(f"  GET  http://localhost:{args.port}/api/bms/data", flush=True)
    if args.hub:
        print(f"  Checking in to {args.hub} every {args.checkin_interval}s", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[BMS] stopped", flush=True)


if __name__ == "__main__":
    main()
