#!/usr/bin/env python3
"""
ESPAI Fake GPIO Simulator

Mimics a GPIO controller node — 8 digital pins + 2 analog inputs.

Usage:
    python fake_gpio.py                              # port 8012
    python fake_gpio.py --port 8013 --id my-gpio
    python fake_gpio.py --hub http://localhost:7888 --checkin-interval 10

Endpoints:
    GET  /api/manifest         — device identity
    GET  /api/status           — uptime, heap, GPIO summary
    GET  /api/gpio             — all pin states
    POST /api/gpio/<pin>       — body: {"value": 0|1} or {"pwm": 0-255}
    GET  /api/adc              — analog input readings
    POST /api/checkin          — hub checkin
    POST /api/reboot           — simulated reboot (resets pins)
"""
import argparse
import hashlib
import json
import random
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

_start_time = time.monotonic()
_paired     = False

# 8 digital output pins (0 or 1), 2 analog inputs (0-4095 on 12-bit ADC)
_pins  = [0] * 8          # GPIO 0–7
_pwm   = [0] * 8          # PWM value 0-255 per pin
_adc_pins = [0, 1]        # ADC-capable pins


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uptime() -> int:
    return int(time.monotonic() - _start_time)


def _make_node_id(seed: str) -> str:
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"gpio-{h[:12]}"


def _adc_reading(pin: int) -> int:
    """Simulated ADC — slow sine wave + noise."""
    t = time.monotonic()
    base = 2048 + 1800 * (0.5 + 0.5 * __import__("math").sin(t / 10.0 + pin))
    return int(base + random.uniform(-30, 30))


# ── HTTP handler ───────────────────────────────────────────────────────────────

class GPIOHandler(BaseHTTPRequestHandler):
    node_id:   str = "gpio-000000000000"
    node_name: str = "fake-gpio"
    port:      int = 8012

    def log_message(self, fmt, *args):
        pass

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
                "board":      "gpio-ctrl-v1",
                "fw_version": "0.1.0",
                "capabilities": {"gpio": True, "adc": True, "ota": False},
            })
        elif self.path == "/api/status":
            self._send_json(200, {
                "id":       self.node_id,
                "uptime_s": _uptime(),
                "heap_free": random.randint(100000, 160000),
                "ip":       "127.0.0.1",
                "gpio": {
                    "digital": {f"D{i}": _pins[i] for i in range(8)},
                    "pwm":     {f"D{i}": _pwm[i]  for i in range(8) if _pwm[i]},
                },
            })
        elif self.path == "/api/gpio":
            self._send_json(200, {
                "pins": [
                    {"pin": i, "label": f"D{i}", "value": _pins[i], "pwm": _pwm[i]}
                    for i in range(8)
                ],
            })
        elif self.path == "/api/adc":
            self._send_json(200, {
                "readings": [
                    {"pin": p, "label": f"A{p}", "raw": _adc_reading(p),
                     "voltage": round(_adc_reading(p) * 3.3 / 4095, 3)}
                    for p in _adc_pins
                ],
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            body = {}

        path = self.path.rstrip("/")

        if path.startswith("/api/gpio/"):
            pin_str = path.split("/")[-1]
            try:
                pin = int(pin_str)
            except ValueError:
                self._send_json(400, {"error": "invalid pin"})
                return
            if not (0 <= pin < 8):
                self._send_json(400, {"error": f"pin {pin} out of range (0-7)"})
                return
            if "pwm" in body:
                _pwm[pin] = max(0, min(255, int(body["pwm"])))
                _pins[pin] = 1 if _pwm[pin] > 0 else 0
            else:
                _pins[pin] = 1 if body.get("value", 0) else 0
                _pwm[pin]  = 0
            self._send_json(200, {"pin": pin, "value": _pins[pin], "pwm": _pwm[pin]})

        elif path == "/api/checkin":
            self._send_json(200, {"status": "ok", "paired": _paired})

        elif path == "/api/reboot":
            for i in range(8):
                _pins[i] = 0
                _pwm[i]  = 0
            self._send_json(200, {"status": "rebooting"})

        else:
            self._send_json(404, {"error": "not found"})


# ── Hub checkin loop ───────────────────────────────────────────────────────────

def _checkin_loop(hub: str, node_id: str, node_name: str, port: int, interval: int) -> None:
    time.sleep(2)
    while True:
        try:
            payload = json.dumps({
                "id":         node_id,
                "name":       node_name,
                "board":      "gpio-ctrl-v1",
                "fw_version": "0.1.0",
                "ip":         f"127.0.0.1:{port}",
                "capabilities": {"gpio": True, "adc": True},
            }).encode()
            req = urllib.request.Request(
                f"{hub}/api/devices/checkin",
                data=payload, method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                global _paired
                _paired = data.get("paired", False)
            high = sum(_pins)
            print(f"[GPIO] checked in — {high}/8 pins HIGH", flush=True)
        except Exception as exc:
            print(f"[GPIO] checkin failed: {exc}", flush=True)
        time.sleep(interval)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="ESPAI Fake GPIO Simulator")
    ap.add_argument("--port", type=int, default=8012)
    ap.add_argument("--id",   default=None)
    ap.add_argument("--name", default="fake-gpio")
    ap.add_argument("--hub",  default=None)
    ap.add_argument("--checkin-interval", type=int, default=10)
    args = ap.parse_args()

    node_id = args.id or _make_node_id(f"gpio:{args.port}")

    GPIOHandler.node_id   = node_id
    GPIOHandler.node_name = args.name
    GPIOHandler.port      = args.port

    if args.hub:
        t = threading.Thread(
            target=_checkin_loop,
            args=(args.hub, node_id, args.name, args.port, args.checkin_interval),
            daemon=True,
        )
        t.start()

    server = HTTPServer(("0.0.0.0", args.port), GPIOHandler)
    print(f"ESPAI Fake GPIO  id={node_id}  port={args.port}", flush=True)
    print(f"  GET  http://localhost:{args.port}/api/manifest", flush=True)
    print(f"  GET  http://localhost:{args.port}/api/gpio", flush=True)
    print(f"  POST http://localhost:{args.port}/api/gpio/<0-7>  body: {{\"value\":1}}", flush=True)
    print(f"  GET  http://localhost:{args.port}/api/adc", flush=True)
    if args.hub:
        print(f"  Checking in to {args.hub} every {args.checkin_interval}s", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[GPIO] stopped", flush=True)


if __name__ == "__main__":
    main()
