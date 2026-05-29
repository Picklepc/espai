#!/usr/bin/env python3
"""
ESPAI Windows Tray App

Manages the hub as a silent background process and exposes a system tray
icon for start / stop / restart, opening the dashboard, tailing logs in a
new console window, and toggling start-at-login.

Usage (source):   python espai.py tray [--port 7888]
Usage (bundled):  espai.exe            (auto-starts tray when no command given)
"""
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Mirrors espai.py / config.py two-directory model.
if getattr(sys, "frozen", False):
    ROOT     = Path(sys.executable).parent          # install dir
    USER_DIR = Path.home() / "Documents" / "ESPAI"
else:
    ROOT     = Path(__file__).parent.parent.parent  # repo root
    USER_DIR = ROOT

LOG_FILE = USER_DIR / "data" / "espai-hub.log"

_hub_proc: subprocess.Popen | None = None
_hub_lock = threading.Lock()
_log_handle = None


# ── Icon ──────────────────────────────────────────────────────────────────────

def _make_icon(size: int = 64, running: bool = True):
    """Render the ESPAI teal-diamond / gold-star badge. Gray when stopped."""
    from PIL import Image, ImageDraw
    import math

    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    r = size * 0.36

    # Pentagon: top 3/4 is a diamond, bottom 1/4 terminates in a flat edge.
    pts = [
        (cx,              cy - r),
        (cx + r,          cy),
        (cx + r * 0.50,   cy + r * 0.70),
        (cx - r * 0.50,   cy + r * 0.70),
        (cx - r,          cy),
    ]
    draw.polygon(pts, fill=(26, 175, 196, 230) if running else (90, 90, 95, 180))
    s = 0.82
    inner = [(cx + (x - cx) * s, cy + (y - cy) * s) for x, y in pts]
    draw.polygon(inner, fill=(8, 12, 16, 240))

    star_r, star_w = size * 0.15, size * 0.04
    star_pts = []
    for i in range(8):
        angle = math.radians(i * 45 - 90)
        rad   = star_r if i % 2 == 0 else star_w
        star_pts.append((cx + rad * math.cos(angle), cy + rad * math.sin(angle)))
    draw.polygon(star_pts, fill=(240, 168, 32, 255) if running else (140, 110, 25, 180))

    return img


# ── Hub process management ─────────────────────────────────────────────────────

def _hub_running() -> bool:
    with _hub_lock:
        return _hub_proc is not None and _hub_proc.poll() is None


def _start_hub(port: int) -> bool:
    global _hub_proc, _log_handle
    with _hub_lock:
        if _hub_proc is not None and _hub_proc.poll() is None:
            return False

        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _log_handle = open(LOG_FILE, "a", encoding="utf-8", errors="replace", buffering=1)

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        if getattr(sys, "frozen", False):
            # Frozen: re-invoke the same exe with the "serve" subcommand.
            cmd = [str(sys.executable), "serve", "--port", str(port)]
        else:
            venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
            if not venv_py.exists():
                venv_py = ROOT / ".venv" / "bin" / "python"
            python = str(venv_py) if venv_py.exists() else sys.executable
            cmd = [python, str(ROOT / "espai.py"), "serve", "--port", str(port)]

        _hub_proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=_log_handle,
            stderr=_log_handle,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return True


def _stop_hub() -> bool:
    global _hub_proc, _log_handle
    with _hub_lock:
        if _hub_proc is None or _hub_proc.poll() is not None:
            return False
        _hub_proc.terminate()
        try:
            _hub_proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _hub_proc.kill()
        _hub_proc = None
        if _log_handle:
            try:
                _log_handle.close()
            except Exception:
                pass
            _log_handle = None
        return True


# ── Autostart (Windows registry) ──────────────────────────────────────────────

def _autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_READ,
        )
        try:
            winreg.QueryValueEx(key, "ESPAI")
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def _set_autostart(enable: bool):
    if sys.platform != "win32":
        return
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        if enable:
            winreg.SetValueEx(key, "ESPAI", 0, winreg.REG_SZ, f'"{sys.executable}"')
        else:
            try:
                winreg.DeleteValue(key, "ESPAI")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass


# ── Logs window ───────────────────────────────────────────────────────────────

def _open_logs():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        LOG_FILE.write_text(
            "No hub logs yet. Start the hub to begin logging.\n",
            encoding="utf-8",
        )
    if sys.platform == "win32":
        # Open a new PowerShell console that tails the log file live.
        subprocess.Popen(
            [
                "powershell", "-NoExit", "-Command",
                (
                    f"$Host.UI.RawUI.WindowTitle = 'ESPAI Hub Logs'; "
                    f"Write-Host 'ESPAI Hub Log  —  {LOG_FILE}' -ForegroundColor Cyan; "
                    f"Write-Host ''; "
                    f"Get-Content -Path '{LOG_FILE}' -Wait -Tail 200"
                ),
            ],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    else:
        for term in ["x-terminal-emulator", "gnome-terminal", "konsole", "xterm"]:
            try:
                subprocess.Popen([term, "-e", f"tail -f '{LOG_FILE}'"])
                return
            except FileNotFoundError:
                continue


# ── Tray ──────────────────────────────────────────────────────────────────────

def _run_tray(port: int):
    try:
        import pystray
    except ImportError:
        print("pystray not installed.  Run:  pip install pystray Pillow")
        sys.exit(1)

    _icons = {
        True:  _make_icon(64, running=True),
        False: _make_icon(64, running=False),
    }

    def _tooltip() -> str:
        if _hub_running():
            return f"ESPAI Hub  ·  Running on :{port}"
        return "ESPAI Hub  ·  Stopped"

    def _refresh(ic):
        ic.icon  = _icons[_hub_running()]
        ic.title = _tooltip()

    # ── Menu actions ──────────────────────────────────────────────────────────

    def on_open(ic, _item):
        webbrowser.open(f"http://localhost:{port}/")

    def on_start(ic, _item):
        if _start_hub(port):
            time.sleep(1.5)
            _refresh(ic)
            ic.notify("ESPAI Hub started", f"http://localhost:{port}/")
        else:
            ic.notify("Hub is already running", "ESPAI")

    def on_stop(ic, _item):
        if _stop_hub():
            _refresh(ic)
            ic.notify("ESPAI Hub stopped", "ESPAI")
        else:
            ic.notify("Hub is not running", "ESPAI")

    def on_restart(ic, _item):
        was_running = _hub_running()
        _stop_hub()
        time.sleep(1)
        _start_hub(port)
        time.sleep(1.5)
        _refresh(ic)
        if was_running:
            ic.notify("ESPAI Hub restarted", f"http://localhost:{port}/")

    def on_logs(_ic, _item):
        _open_logs()

    def on_autostart_toggle(_ic, _item):
        _set_autostart(not _autostart_enabled())

    def on_exit(ic, _item):
        _stop_hub()
        ic.stop()

    # ── Dynamic state predicates for menu items ───────────────────────────────
    # pystray calls these on each menu open to decide enabled / checked state.

    def _is_running(_item):   return _hub_running()
    def _is_stopped(_item):   return not _hub_running()
    def _autostart_on(_item): return _autostart_enabled()

    menu = pystray.Menu(
        pystray.MenuItem("Open Dashboard",   on_open,              default=True),
        pystray.MenuItem("Open Logs",        on_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start Hub",        on_start,             enabled=_is_stopped),
        pystray.MenuItem("Stop Hub",         on_stop,              enabled=_is_running),
        pystray.MenuItem("Restart Hub",      on_restart,           enabled=_is_running),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start at Login",   on_autostart_toggle,  checked=_autostart_on),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit",             on_exit),
    )

    icon = pystray.Icon("ESPAI", _icons[False], _tooltip(), menu)

    def _auto_start_then_refresh():
        _start_hub(port)
        time.sleep(2)
        _refresh(icon)

    threading.Thread(target=_auto_start_then_refresh, daemon=True).start()

    # Poll every 3 s and update icon/tooltip when hub process state changes.
    def _monitor():
        prev = None
        while True:
            time.sleep(3)
            cur = _hub_running()
            if cur != prev:
                _refresh(icon)
                prev = cur

    threading.Thread(target=_monitor, daemon=True).start()

    icon.run()


def main(port: int = 7888):
    _run_tray(port)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=7888)
    args = p.parse_args()
    main(port=args.port)
