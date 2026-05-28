#!/usr/bin/env python3
"""
ESPAI Fake Node Simulator

Mimics the HTTP API of a real ESP32 node so you can develop and test the hub
without any physical hardware.

Usage:
    python fake_node.py                          # default port 8001
    python fake_node.py --port 8002 --id my-id  # custom port / ID
    python fake_node.py --hub http://localhost:7888 --checkin-interval 10

The simulator will:
  - Serve all node API endpoints (manifest, status, checkin, reboot, ota)
  - Optionally POST periodic checkins to the hub (--hub flag)
  - Increment uptime and randomise sensor-like values over time

Multiple instances can run simultaneously on different ports to simulate a fleet.
"""
import argparse
import hashlib
import json
import random
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

# ── State ─────────────────────────────────────────────────────────────────────

_start_time  = time.monotonic()
_paired      = False
_reboot_flag = False
_ota_log: list[dict] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uptime() -> int:
    return int(time.monotonic() - _start_time)


# ── Node identity ─────────────────────────────────────────────────────────────

def _make_node_id(seed: str) -> str:
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"node-{h[:12]}"


# ── Request handler ───────────────────────────────────────────────────────────

class FakeNodeHandler(BaseHTTPRequestHandler):
    node_id: str = "node-000000000000"
    node_name: str = "fake-node"
    board: str = "esp32dev"
    fw_version: str = "0.1.0"

    def log_message(self, fmt, *args):
        # Suppress default noisy access log; we print our own
        pass

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    # ── GET ────────────────────────────────────────────────────────────────────

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/api/manifest":
            self._send_json(200, {
                "schema":     "ESPAI.device.v1",
                "id":         self.node_id,
                "name":       self.node_name,
                "board":      self.board,
                "fw_version": self.fw_version,
                "paired":     _paired,
                "capabilities": {
                    "ota":    True,
                    "sleep":  True,
                    "camera": False,
                    "ble":    False,
                    "gpio":   [2, 4, 5, 13, 14],
                },
            })

        elif path == "/api/status":
            self._send_json(200, {
                "id":        self.node_id,
                "uptime_s":  _uptime(),
                "heap_free": random.randint(180_000, 240_000),
                "wifi_rssi": random.randint(-75, -40),
                "ip":        _my_ip(),
                "ap_mode":   False,
                "paired":    _paired,
                "temp_c":    round(random.uniform(28.0, 35.0), 1),
            })

        else:
            self._send_json(404, {"error": "Not found"})

    # ── POST ───────────────────────────────────────────────────────────────────

    def do_POST(self):
        global _paired, _reboot_flag
        path = self.path.split("?")[0]
        body = self._read_body()

        if path == "/api/checkin":
            self._send_json(200, {"status": "ok", "id": self.node_id})

        elif path == "/api/reboot":
            print(f"[{self.node_name}] Reboot requested — simulating restart")
            self._send_json(200, {"status": "rebooting"})
            _reboot_flag = True

        elif path == "/ota/update":
            size = len(body)
            entry = {"timestamp": _now(), "size_bytes": size, "status": "accepted"}
            _ota_log.append(entry)
            print(f"[{self.node_name}] OTA binary received: {size} bytes")
            self._send_json(200, {"status": "accepted", "size_bytes": size})

        elif path == "/api/pair":
            try:
                data = json.loads(body)
                if data.get("confirm"):
                    _paired = True
                    print(f"[{self.node_name}] Paired!")
            except Exception:
                pass
            self._send_json(200, {"status": "ok", "paired": _paired})

        else:
            self._send_json(404, {"error": "Not found"})


# ── Hub checkin loop ──────────────────────────────────────────────────────────

def _my_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _checkin_loop(hub_url: str, handler_cls: type, interval: int) -> None:
    """POST /api/devices/checkin to the hub periodically."""
    endpoint = hub_url.rstrip("/") + "/api/devices/checkin"
    ip = _my_ip()

    while True:
        payload = {
            "id":         handler_cls.node_id,
            "name":       handler_cls.node_name,
            "board":      handler_cls.board,
            "fw_version": handler_cls.fw_version,
            "ip":         ip,
            "capabilities": {
                "ota":  True,
                "sleep": True,
            },
        }
        body = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                if data.get("paired") and not _paired:
                    print(f"[{handler_cls.node_name}] Hub reports: paired")
        except urllib.error.URLError as e:
            print(f"[{handler_cls.node_name}] Hub checkin failed: {e.reason}")
        except Exception as e:
            print(f"[{handler_cls.node_name}] Hub checkin error: {e}")

        time.sleep(interval)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ESPAI fake ESP32 node simulator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--port",     type=int,  default=8001,  help="HTTP port to listen on")
    parser.add_argument("--id",       default=None,             help="Node ID seed (default: auto from port)")
    parser.add_argument("--name",     default=None,             help="Node name (default: fake-node-<port>)")
    parser.add_argument("--board",    default="esp32dev",       help="Board ID")
    parser.add_argument("--fw",       default="0.1.0",          help="Firmware version string")
    parser.add_argument("--hub",      default=None,             help="Hub URL for periodic checkins (e.g. http://localhost:7888)")
    parser.add_argument("--checkin-interval", type=int, default=15, help="Seconds between hub checkins")
    args = parser.parse_args()

    node_id   = _make_node_id(args.id or f"fake-node-port-{args.port}")
    node_name = args.name or f"fake-node-{args.port}"

    # Build a handler class with node identity baked in (HTTPServer reuses one class)
    handler = type("Handler", (FakeNodeHandler,), {
        "node_id":    node_id,
        "node_name":  node_name,
        "board":      args.board,
        "fw_version": args.fw,
    })

    server = HTTPServer(("0.0.0.0", args.port), handler)

    print(f"\nESPAI fake node '{node_name}'")
    print(f"  ID      : {node_id}")
    print(f"  Board   : {args.board}  fw {args.fw}")
    print(f"  API     : http://localhost:{args.port}/api/manifest")
    if args.hub:
        print(f"  Hub     : {args.hub}  (checkin every {args.checkin_interval}s)")
    print()

    if args.hub:
        t = threading.Thread(
            target=_checkin_loop,
            args=(args.hub, handler, args.checkin_interval),
            daemon=True,
            name="checkin-loop",
        )
        t.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping fake node.")
        server.shutdown()


if __name__ == "__main__":
    main()
