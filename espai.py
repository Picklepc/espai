#!/usr/bin/env python3
"""
ESPAI — ESPAI Hub command-line interface

Commands:
  ESPAI init           Create workspace directories, verify config
  ESPAI doctor         Check installed dependencies
  ESPAI serve          Start the hub server
  ESPAI install-deps   Install Python dependencies (explicit opt-in)

Usage:
  python ESPAI.py <command> [options]
"""
import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# When running as a PyInstaller bundle, ROOT is next to the .exe.
# Two-directory model (mirrors hub/backend/config.py):
#
#   INSTALL_DIR  — exe + bundled read-only assets.  Overwritten on update.
#   USER_DIR     — all mutable user data (projects, DB, content packs, .env).
#                  NEVER touched by the installer; survives updates/reinstalls.
#
# In source / dev mode both collapse to the repo root.
if getattr(sys, "frozen", False):
    ROOT        = Path(sys.executable).parent          # install dir
    INSTALL_DIR = ROOT
    USER_DIR    = Path.home() / "Documents" / "ESPAI"
else:
    ROOT        = Path(__file__).parent                # repo root
    INSTALL_DIR = ROOT
    USER_DIR    = ROOT

REQUIRED_DIRS = [
    "data",
    "projects",
    "firmware-catalog",
]

# Source-mode helpers (not used in frozen builds)
HUB_REQUIREMENTS = INSTALL_DIR / "hub" / "backend" / "requirements.txt"
HUB_MODULE       = "hub.backend.main:app"

# Prefer the project venv if it exists — avoids global Python conflicts
_VENV_PYTHON = INSTALL_DIR / ".venv" / "Scripts" / "python.exe"   # Windows
if not _VENV_PYTHON.exists():
    _VENV_PYTHON = INSTALL_DIR / ".venv" / "bin" / "python"        # Linux/macOS
VENV_PYTHON = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable


# ── Helpers ───────────────────────────────────────────────────────────────────

def ok(msg):  print(f"  \033[92m✓\033[0m  {msg}")
def warn(msg): print(f"  \033[93m!\033[0m  {msg}")
def err(msg):  print(f"  \033[91m✗\033[0m  {msg}")
def info(msg): print(f"     {msg}")


def check_cmd(name, *args, label=None):
    label = label or name
    found = shutil.which(name)
    if found:
        try:
            result = subprocess.run(
                [name, *args], capture_output=True, text=True, timeout=5
            )
            version = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "?"
            ok(f"{label}: {version}")
        except Exception:
            ok(f"{label}: found at {found}")
    else:
        warn(f"{label}: not found")
    return found


def check_python_pkg(pkg, import_name=None):
    import_name = import_name or pkg
    try:
        __import__(import_name)
        ok(f"Python package: {pkg}")
        return True
    except ImportError:
        warn(f"Python package: {pkg} — not installed (run: ESPAI install-deps)")
        return False


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_init(args):
    print("\nESPAI init\n")
    info(f"Data directory: {USER_DIR}")
    print()
    created = []
    for d in REQUIRED_DIRS:
        path = USER_DIR / d
        if not path.exists():
            path.mkdir(parents=True)
            (path / ".gitkeep").touch()
            created.append(d)
            ok(f"Created {USER_DIR / d}")
        else:
            ok(f"{d}/ already exists")

    config_env = USER_DIR / ".env"
    if not config_env.exists():
        config_env.write_text(
            "# ESPAI Hub configuration\n"
            "ESPAI_HOST=0.0.0.0\n"
            "ESPAI_PORT=7888\n"
            "ESPAI_DEBUG=0\n",
            encoding="utf-8",
        )
        ok(f"Created .env at {config_env}")
    else:
        ok(".env already exists")

    print()
    if created:
        info(f"Created: {', '.join(created)}")
    info("Run 'python espai.py doctor' to verify dependencies.")
    info("Run 'python espai.py serve' to start the hub.")
    print()


def cmd_doctor(args):
    print("\nESPAI doctor\n")

    # Python
    v = sys.version_info
    if v >= (3, 11):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        warn(f"Python {v.major}.{v.minor}.{v.micro} — 3.11+ recommended")

    print()
    print("  Hub dependencies:")
    check_python_pkg("fastapi")
    check_python_pkg("uvicorn")
    check_python_pkg("yaml", "yaml")

    print()
    print("  Optional hub dependencies:")
    check_python_pkg("zeroconf")
    check_python_pkg("aiohttp")

    print()
    print("  External tools:")
    pio_found = check_cmd("pio", "--version", label="PlatformIO CLI")
    if not pio_found:
        # PlatformIO can also be installed as a Python package
        pio_pkg = check_python_pkg("platformio", "platformio")
        if not pio_pkg:
            info("Install PlatformIO: pip install platformio  (required for firmware builds)")
    check_cmd("git",        "--version", label="Git")
    check_cmd("docker",     "--version", label="Docker")
    check_cmd("ffmpeg",     "-version",  label="FFmpeg")
    check_cmd("code",       "--version", label="VSCode")
    check_cmd("node",       "--version", label="Node.js")

    print()
    print("  Terminal:")
    if sys.platform == "win32":
        has_term = check_python_pkg("pywinpty", "winpty")
        if not has_term:
            info("Install: pip install pywinpty  (requires Windows 10 1903+)")
    else:
        has_term = check_python_pkg("ptyprocess")
        if not has_term:
            info("Install: pip install ptyprocess")

    print()
    print("  Agent Bench adapters:")
    agent_bench_enabled = os.environ.get("ESPAI_AGENT_BENCH", "").lower() in ("1", "true", "yes")
    if agent_bench_enabled:
        ok("Agent Bench: enabled")
    else:
        warn("Agent Bench: disabled  (set ESPAI_AGENT_BENCH=true in .env to enable)")
    check_cmd("claude",     "--version", label="Claude Code CLI")
    check_cmd("codex",      "--version", label="Codex CLI")

    print()
    print("  Workspace:")
    info(f"Data dir: {USER_DIR}")
    for d in REQUIRED_DIRS:
        path = USER_DIR / d
        if path.exists():
            ok(f"{d}/")
        else:
            warn(f"{d}/ — missing (run: ESPAI init)")
    print()


def _first_run_scaffold():
    """
    On first launch of a frozen build, populate USER_DIR (~/Documents/ESPAI)
    with workspace dirs, default content packs, and a default .env.
    Subsequent launches (and updates) skip this entirely — the sentinel guards it.
    Content packs are copied from INSTALL_DIR so user customisations are never
    overwritten by an update.
    """
    sentinel = USER_DIR / "data" / ".espai-initialized"
    if sentinel.exists():
        return

    # Workspace dirs in USER_DIR
    for d in REQUIRED_DIRS:
        (USER_DIR / d).mkdir(parents=True, exist_ok=True)

    # Copy starter content packs from the install dir into USER_DIR.
    # _MEIPASS exists for onefile builds; one-dir builds use INSTALL_DIR directly.
    bundle = Path(getattr(sys, "_MEIPASS", str(INSTALL_DIR)))
    content_dirs = ["recipes", "workers", "cards", "design", "agents",
                    "policies", "schemas", "agent-bench"]
    copied = []
    for d in content_dirs:
        src = bundle / d
        dst = USER_DIR / d
        if src.exists() and not dst.exists():
            shutil.copytree(str(src), str(dst))
            copied.append(d)

    # Default .env in USER_DIR
    env_file = USER_DIR / ".env"
    if not env_file.exists():
        env_file.write_text(
            "# ESPAI Hub configuration\n"
            "ESPAI_HOST=0.0.0.0\n"
            "ESPAI_PORT=7888\n"
            "ESPAI_DEBUG=0\n",
            encoding="utf-8",
        )

    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()

    if copied:
        print(f"\n  ✦ First run — installed content packs: {', '.join(copied)}")
    print(f"  ✦ ESPAI data directory: {USER_DIR}")


def _open_browser_delayed(url: str, delay: float = 2.0):
    """Open the dashboard in the default browser after a short startup delay."""
    import webbrowser
    time.sleep(delay)
    webbrowser.open(url)


def cmd_serve(args):
    host = args.host or os.environ.get("ESPAI_HOST", "0.0.0.0")
    port = args.port or int(os.environ.get("ESPAI_PORT", "7888"))
    reload    = getattr(args, "reload",    False)
    open_browser = getattr(args, "open", False) or getattr(sys, "frozen", False)

    # Load .env from user data dir (~/Documents/ESPAI in frozen builds)
    env_file = USER_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    # First-run data scaffold (frozen / bundled installs only)
    if getattr(sys, "frozen", False):
        _first_run_scaffold()

    dashboard_url = f"http://localhost:{port}/"
    print(f"\n  ESPAI Hub  v{'(dev)' if not getattr(sys, 'frozen', False) else 'bundled'}\n")
    print(f"  Dashboard  {dashboard_url}")
    print(f"  Data dir   {USER_DIR}")
    if VENV_PYTHON != sys.executable:
        print(f"  Python     {VENV_PYTHON} (venv)")
    print()

    # Re-launch under venv Python if needed (source installs only)
    if not getattr(sys, "frozen", False) and VENV_PYTHON != sys.executable:
        cmd = (
            [VENV_PYTHON, __file__, "serve", "--host", host, "--port", str(port)]
            + (["--reload"] if reload else [])
            + (["--open"] if open_browser else [])
        )
        result = subprocess.run(cmd, cwd=str(INSTALL_DIR))
        sys.exit(result.returncode)

    try:
        import uvicorn
    except ImportError:
        err("uvicorn not installed. Run: python ESPAI.py install-deps")
        sys.exit(1)

    # Open browser in a background thread so it doesn't block uvicorn startup
    if open_browser:
        t = threading.Thread(target=_open_browser_delayed, args=(dashboard_url,), daemon=True)
        t.start()

    os.chdir(INSTALL_DIR)
    uvicorn.run(
        HUB_MODULE,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


def cmd_tray(args):
    port = args.port or int(os.environ.get("ESPAI_PORT", "7888"))
    try:
        from hub.tray.tray import main as tray_main
        tray_main(port=port)
    except ImportError as exc:
        err(f"Tray dependencies missing: {exc}")
        info("Install with:  pip install pystray Pillow")
        sys.exit(1)


def cmd_install_deps(args):
    print("\nESPAI install-deps\n")
    print("  This will install hub/backend/requirements.txt into the project venv.")

    if not HUB_REQUIREMENTS.exists():
        err(f"Requirements file not found: {HUB_REQUIREMENTS}")
        sys.exit(1)

    venv_dir = INSTALL_DIR / ".venv"
    if not venv_dir.exists():
        print("  Creating .venv …")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

    pip = str(venv_dir / "Scripts" / "pip.exe") if (venv_dir / "Scripts").exists() \
          else str(venv_dir / "bin" / "pip")

    print(f"  Running: {pip} install -r {HUB_REQUIREMENTS}\n")
    result = subprocess.run(
        [pip, "install", "-r", str(HUB_REQUIREMENTS)],
        cwd=INSTALL_DIR,
    )
    if result.returncode == 0:
        print()
        ok("Dependencies installed into .venv")
        info("Run 'python ESPAI.py serve' to start the hub.")
    else:
        err("pip install failed (see above).")
        sys.exit(result.returncode)


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    # Frozen exe with no arguments: auto-start tray so double-clicking the
    # installed exe silently brings up the hub with a tray icon.
    if getattr(sys, "frozen", False) and len(sys.argv) == 1:
        if getattr(sys, "frozen", False):
            _first_run_scaffold()
        cmd_tray(argparse.Namespace(port=None))
        return

    parser = argparse.ArgumentParser(
        prog="ESPAI",
        description="ESPAI Hub CLI — local-first ESP32 platform",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialize workspace directories")

    sub.add_parser("doctor", help="Check dependencies and workspace")

    serve_p = sub.add_parser("serve", help="Start the hub server")
    serve_p.add_argument("--host",   default=None, help="Bind host (default: 0.0.0.0)")
    serve_p.add_argument("--port",   default=None, type=int, help="Bind port (default: 7888)")
    serve_p.add_argument("--reload", action="store_true", help="Enable hot-reload (dev)")
    serve_p.add_argument("--open",   action="store_true", help="Open dashboard in browser after startup (always on for bundled exe)")

    sub.add_parser("install-deps", help="Install Python dependencies")

    tray_p = sub.add_parser("tray", help="Start hub with Windows system tray icon (requires pystray + Pillow)")
    tray_p.add_argument("--port", default=None, type=int, help="Hub port (default: 7888)")

    args = parser.parse_args()

    dispatch = {
        "init":         cmd_init,
        "doctor":       cmd_doctor,
        "serve":        cmd_serve,
        "install-deps": cmd_install_deps,
        "tray":         cmd_tray,
    }

    if args.command not in dispatch:
        parser.print_help()
        sys.exit(0)

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
