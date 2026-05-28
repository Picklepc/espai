#!/usr/bin/env python3
"""
ESPAI Windows Tray App

Runs the hub as a managed background process and provides a system tray
icon for starting, stopping, and opening the dashboard.

Requirements:
    pip install pystray Pillow

Usage:
    python espai.py tray
    python espai.py tray --port 7888
"""

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # repo root

_hub_proc: subprocess.Popen | None = None
_hub_lock = threading.Lock()


# ── Icon generation ────────────────────────────────────────────────────────────

def _make_icon(size: int = 64):
    """Draw the ESPAI rounded-diamond badge as a PIL Image for the tray."""
    from PIL import Image, ImageDraw
    import math

    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2
    r = size * 0.36           # half-diagonal of the square
    corner = size * 0.18      # rx approximation via polygon rounding

    # Rotate a square 45° to make a diamond
    # Use a polygon for the diamond shape
    pts = [
        (cx,          cy - r),   # top
        (cx + r,      cy),       # right
        (cx,          cy + r),   # bottom
        (cx - r,      cy),       # left
    ]
    # Outer teal diamond
    draw.polygon(pts, fill=(26, 175, 196, 230))
    # Inner dark fill (slightly smaller)
    s = 0.82
    inner = [(cx + (x - cx) * s, cy + (y - cy) * s) for x, y in pts]
    draw.polygon(inner, fill=(8, 12, 16, 240))

    # Gold 4-pointed star in the center
    star_r = size * 0.15
    star_w = size * 0.04
    star_pts = []
    for i in range(8):
        angle = math.radians(i * 45 - 90)
        rad   = star_r if i % 2 == 0 else star_w
        star_pts.append((cx + rad * math.cos(angle), cy + rad * math.sin(angle)))
    draw.polygon(star_pts, fill=(240, 168, 32, 255))

    return img


# ── Hub process management ─────────────────────────────────────────────────────

def _hub_running() -> bool:
    with _hub_lock:
        return _hub_proc is not None and _hub_proc.poll() is None


def _start_hub(port: int) -> bool:
    global _hub_proc
    with _hub_lock:
        if _hub_proc is not None and _hub_proc.poll() is None:
            return False  # already running
        venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
        python = str(venv_python) if venv_python.exists() else sys.executable
        _hub_proc = subprocess.Popen(
            [python, str(ROOT / "espai.py"), "serve", "--port", str(port)],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return True


def _stop_hub() -> bool:
    global _hub_proc
    with _hub_lock:
        if _hub_proc is None or _hub_proc.poll() is not None:
            return False
        _hub_proc.terminate()
        try:
            _hub_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _hub_proc.kill()
        _hub_proc = None
        return True


def _hub_status_text() -> str:
    if _hub_running():
        return "Hub: Running"
    return "Hub: Stopped"


# ── Tray menu ──────────────────────────────────────────────────────────────────

def _run_tray(port: int):
    try:
        import pystray
    except ImportError:
        print("pystray not installed. Run:  pip install pystray Pillow")
        sys.exit(1)

    icon_image = _make_icon(64)

    def on_open(_icon, _item):
        webbrowser.open(f"http://localhost:{port}/")

    def on_start(_icon, _item):
        if _start_hub(port):
            _icon.notify("ESPAI Hub started", f"http://localhost:{port}/")
        else:
            _icon.notify("Hub already running")

    def on_stop(_icon, _item):
        if _stop_hub():
            _icon.notify("ESPAI Hub stopped")
        else:
            _icon.notify("Hub is not running")

    def on_exit(_icon, _item):
        _stop_hub()
        _icon.stop()

    def _status_label(item) -> str:
        return _hub_status_text()

    menu = pystray.Menu(
        pystray.MenuItem("Open Dashboard",  on_open,  default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(_status_label, None, enabled=False),
        pystray.MenuItem("Start Hub",  on_start),
        pystray.MenuItem("Stop Hub",   on_stop),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", on_exit),
    )

    icon = pystray.Icon("ESPAI", icon_image, "ESPAI Hub", menu)

    # Auto-start hub when tray launches
    threading.Thread(target=lambda: _start_hub(port), daemon=True).start()

    print(f"ESPAI tray started — hub at http://localhost:{port}/")
    print("Right-click the tray icon to control the hub.")
    icon.run()


def main(port: int = 7888):
    _run_tray(port)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=7888)
    args = p.parse_args()
    main(port=args.port)
