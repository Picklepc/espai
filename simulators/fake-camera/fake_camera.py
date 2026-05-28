#!/usr/bin/env python3
"""
ESPAI Fake Camera Simulator

Mimics an ESP32-CAM node with MJPEG stream for hub development without hardware.

Usage:
    python fake_camera.py                              # port 8021
    python fake_camera.py --port 8022 --id my-cam
    python fake_camera.py --hub http://localhost:7888 --checkin-interval 15

Optional dependency for animated frames:
    pip install Pillow

Without Pillow the stream still works but serves a static placeholder frame.
"""

import argparse
import hashlib
import io
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

try:
    from PIL import Image, ImageDraw
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# ── State ──────────────────────────────────────────────────────────────────────

_start_time   = time.monotonic()
_paired       = False
_frame_count  = 0
_motion_count = 0
_fps_target   = 10
_resolution   = (320, 240)
_last_motion  = 0.0

_config_lock  = threading.Lock()

# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uptime() -> int:
    return int(time.monotonic() - _start_time)


def _make_node_id(seed: str) -> str:
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"cam-{h[:12]}"


def _my_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ── Frame generation ───────────────────────────────────────────────────────────

# Minimal 1×1 gray JFIF, used when Pillow is absent
_PLACEHOLDER_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000"
    "ffdb004300080606070605080707070909080a0c"
    "140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20"
    "242e2720222c231c1c2837292c30313434341f27"
    "393d38323c2e333432ffc0000b08000100010101"
    "11ffc4001f0000010501010101010100000000000"
    "00000010203040506070809ffda00080101000003"
    "f07fffd9"
)


def _build_placeholder() -> bytes:
    """Return the embedded placeholder JPEG bytes."""
    return _PLACEHOLDER_JPEG


def _render_frame(w: int, h: int, frame_n: int) -> bytes:
    """Generate a synthetic MJPEG frame using Pillow."""
    img = Image.new("RGB", (w, h), color=(8, 12, 16))       # ESPAI dark bg
    draw = ImageDraw.Draw(img)

    # Grid lines — retro CRT feel
    grid_color = (0, 40, 55)
    step_x = max(w // 10, 1)
    step_y = max(h // 8, 1)
    for x in range(0, w, step_x):
        draw.line([(x, 0), (x, h)], fill=grid_color)
    for y in range(0, h, step_y):
        draw.line([(0, y), (w, y)], fill=grid_color)

    # Scanline overlay (every other row slightly darker)
    for y in range(0, h, 2):
        draw.line([(0, y), (w, y)], fill=(0, 0, 0, 80))

    # Simulated "motion blob" — random bright spot
    motion_active = (time.monotonic() - _last_motion) < 1.5
    if motion_active:
        bx = random.randint(w // 4, 3 * w // 4)
        by = random.randint(h // 4, 3 * h // 4)
        r  = random.randint(8, 20)
        draw.ellipse([(bx - r, by - r), (bx + r, by + r)], fill=(224, 120, 40, 180))
        draw.rectangle([(2, 2), (80, 14)], fill=(224, 120, 40))
        draw.text((4, 2), "MOTION", fill=(8, 12, 16))

    # Noise pixels
    for _ in range(40):
        px = random.randint(0, w - 1)
        py = random.randint(0, h - 1)
        v  = random.randint(20, 80)
        draw.point((px, py), fill=(0, v, v + 10))

    # Corner HUD
    ts = datetime.now().strftime("%H:%M:%S")
    draw.text((4, h - 22), f"ESPAI-CAM  {w}x{h}", fill=(26, 175, 196))
    draw.text((4, h - 12), f"F:{frame_n:06d}  {ts}", fill=(26, 175, 196))

    # Center diamond logo accent (tiny)
    cx, cy = w // 2, h // 2
    half = 6
    diamond = [(cx, cy - half), (cx + half, cy), (cx, cy + half), (cx - half, cy)]
    draw.polygon(diamond, outline=(240, 168, 32))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def _get_frame() -> bytes:
    global _frame_count
    with _config_lock:
        w, h = _resolution
    _frame_count += 1
    if _HAS_PIL:
        return _render_frame(w, h, _frame_count)
    return _build_placeholder()


# ── HTTP handler ───────────────────────────────────────────────────────────────

class FakeCameraHandler(BaseHTTPRequestHandler):
    node_id:   str = "cam-000000000000"
    node_name: str = "fake-camera"
    board:     str = "esp32-cam"
    fw_version: str = "0.1.0"
    hub_url:   str = ""
    port:      int = 8021

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""

    # ── GET ────────────────────────────────────────────────────────────────────

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/api/manifest":
            with _config_lock:
                w, h = _resolution
            self._send_json(200, {
                "schema":      "ESPAI.device.v1",
                "id":          self.node_id,
                "name":        self.node_name,
                "board":       self.board,
                "fw_version":  self.fw_version,
                "ip":          _my_ip(),
                "port":        self.port,
                "paired":      _paired,
                "capabilities": {
                    "camera":    True,
                    "ota":       True,
                    "mjpeg":     True,
                    "snapshot":  True,
                    "gpio":      [],
                    "sleep":     False,
                    "ble":       False,
                },
            })

        elif path == "/api/status":
            self._send_json(200, {
                "id":          self.node_id,
                "uptime_s":    _uptime(),
                "heap_free":   random.randint(160_000, 220_000),
                "wifi_rssi":   random.randint(-72, -38),
                "ip":          _my_ip(),
                "paired":      _paired,
                "temp_c":      round(random.uniform(38.0, 48.0), 1),
            })

        elif path == "/api/camera/info":
            with _config_lock:
                w, h = _resolution
                fps  = _fps_target
            self._send_json(200, {
                "resolution":   f"{w}x{h}",
                "width":        w,
                "height":       h,
                "fps":          fps,
                "format":       "MJPEG",
                "frame_count":  _frame_count,
                "motion_count": _motion_count,
                "has_pil":      _HAS_PIL,
                "stream_url":   f"http://{_my_ip()}:{self.port}/camera/stream",
                "snapshot_url": f"http://{_my_ip()}:{self.port}/api/camera/snapshot",
            })

        elif path == "/api/camera/snapshot":
            frame = _get_frame()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(frame)

        elif path == "/camera/stream":
            self._serve_mjpeg()

        else:
            self._send_json(404, {"error": "Not found"})

    # ── POST ───────────────────────────────────────────────────────────────────

    def do_POST(self):
        global _paired
        path = self.path.split("?")[0]
        body = self._read_body()

        if path == "/api/checkin":
            self._send_json(200, {"status": "ok", "id": self.node_id})

        elif path == "/api/reboot":
            print(f"[{self.node_name}] Reboot requested — simulating restart")
            self._send_json(200, {"status": "rebooting"})

        elif path == "/api/pair":
            try:
                d = json.loads(body)
                if d.get("token"):
                    _paired = True
                    self._send_json(200, {"status": "paired", "id": self.node_id})
                else:
                    self._send_json(400, {"error": "token required"})
            except Exception:
                self._send_json(400, {"error": "bad json"})

        elif path == "/api/camera/config":
            global _fps_target
            try:
                d = json.loads(body)
                with _config_lock:
                    if "fps" in d:
                        _fps_target = max(1, min(30, int(d["fps"])))
                    if "resolution" in d:
                        res_map = {
                            "320x240": (320, 240),
                            "640x480": (640, 480),
                            "160x120": (160, 120),
                        }
                        new_res = res_map.get(d["resolution"])
                        if new_res:
                            _resolution = new_res
                self._send_json(200, {"status": "ok"})
            except Exception:
                self._send_json(400, {"error": "bad config"})

        elif path == "/ota/update":
            size = len(body)
            print(f"[{self.node_name}] OTA binary received: {size} bytes (simulated)")
            self._send_json(200, {"status": "accepted", "size_bytes": size})

        else:
            self._send_json(404, {"error": "Not found"})

    # ── MJPEG stream ───────────────────────────────────────────────────────────

    def _serve_mjpeg(self):
        boundary = b"espai_frame"
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace;boundary={boundary.decode()}")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Connection", "close")
        self.end_headers()

        with _config_lock:
            fps = _fps_target
        frame_delay = 1.0 / max(fps, 1)

        try:
            while True:
                frame = _get_frame()
                header = (
                    b"--" + boundary + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                )
                self.wfile.write(header + frame + b"\r\n")
                self.wfile.flush()
                time.sleep(frame_delay)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client disconnected


# ── Hub checkin ────────────────────────────────────────────────────────────────

def _checkin(hub_url: str, node_id: str, node_name: str, port: int) -> None:
    with _config_lock:
        w, h = _resolution
        fps  = _fps_target
    payload = json.dumps({
        "id":         node_id,
        "name":       node_name,
        "board":      "esp32-cam",
        "fw_version": "0.1.0",
        "ip":         _my_ip(),
        "port":       port,
        "capabilities": {
            "camera":   True,
            "ota":      True,
            "mjpeg":    True,
            "snapshot": True,
            "resolution": f"{w}x{h}",
            "fps":      fps,
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{hub_url}/api/devices/checkin",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
        print(f"[{node_name}] Checked in to hub: {hub_url}")
    except urllib.error.URLError as e:
        print(f"[{node_name}] Hub checkin failed: {e.reason}", file=sys.stderr)


def _motion_loop(hub_url: str, node_id: str, node_name: str) -> None:
    """Simulate random motion events and publish them to the hub."""
    global _motion_count, _last_motion
    while True:
        time.sleep(random.uniform(8, 25))
        _motion_count += 1
        _last_motion = time.monotonic()
        print(f"[{node_name}] Motion detected (event #{_motion_count})")
        if hub_url:
            payload = json.dumps({
                "device_id": node_id,
                "type":      "motion_detected",
                "data":      {"count": _motion_count, "frame": _frame_count},
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{hub_url}/api/events/publish",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=3):
                    pass
            except Exception:
                pass


def _checkin_loop(hub_url: str, node_id: str, node_name: str, port: int, interval: int) -> None:
    while True:
        time.sleep(interval)
        _checkin(hub_url, node_id, node_name, port)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ESPAI Fake Camera Simulator")
    parser.add_argument("--port",             type=int, default=8021)
    parser.add_argument("--id",               type=str, default="")
    parser.add_argument("--hub",              type=str, default="http://localhost:7888")
    parser.add_argument("--checkin-interval", type=int, default=30)
    parser.add_argument("--fps",              type=int, default=10)
    parser.add_argument("--resolution",       type=str, default="320x240",
                        choices=["160x120", "320x240", "640x480"])
    parser.add_argument("--no-hub",           action="store_true",
                        help="Disable hub checkin (run standalone)")
    args = parser.parse_args()

    seed    = args.id or f"fake-camera:{args.port}"
    node_id = _make_node_id(seed)
    name    = args.id or f"fake-camera-{args.port}"

    global _fps_target, _resolution
    _fps_target = args.fps
    _resolution = tuple(int(x) for x in args.resolution.split("x"))  # type: ignore[assignment]

    FakeCameraHandler.node_id   = node_id
    FakeCameraHandler.node_name = name
    FakeCameraHandler.hub_url   = args.hub
    FakeCameraHandler.port      = args.port

    hub_url = "" if args.no_hub else args.hub

    print(f"[{name}] ESPAI Fake Camera Simulator")
    print(f"[{name}] Node ID : {node_id}")
    print(f"[{name}] Address : http://{_my_ip()}:{args.port}")
    print(f"[{name}] Stream  : http://{_my_ip()}:{args.port}/camera/stream")
    print(f"[{name}] Snapshot: http://{_my_ip()}:{args.port}/api/camera/snapshot")
    print(f"[{name}] Pillow  : {'yes (animated frames)' if _HAS_PIL else 'no  (static placeholder — pip install Pillow)'}")
    if hub_url:
        print(f"[{name}] Hub     : {hub_url}")

    if hub_url:
        _checkin(hub_url, node_id, name, args.port)
        threading.Thread(
            target=_checkin_loop,
            args=(hub_url, node_id, name, args.port, args.checkin_interval),
            daemon=True,
        ).start()
        threading.Thread(
            target=_motion_loop,
            args=(hub_url, node_id, name),
            daemon=True,
        ).start()

    server = HTTPServer(("0.0.0.0", args.port), FakeCameraHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n[{name}] Stopped.")


if __name__ == "__main__":
    main()
