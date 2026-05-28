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
from pathlib import Path

ROOT = Path(__file__).parent

REQUIRED_DIRS = [
    "data",
    "projects",
    "firmware-catalog",
]

HUB_REQUIREMENTS = ROOT / "hub" / "backend" / "requirements.txt"
HUB_MODULE       = "hub.backend.main:app"

# Prefer the project venv if it exists — avoids global Python conflicts
_VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"   # Windows
if not _VENV_PYTHON.exists():
    _VENV_PYTHON = ROOT / ".venv" / "bin" / "python"        # Linux/macOS
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
    created = []
    for d in REQUIRED_DIRS:
        path = ROOT / d
        if not path.exists():
            path.mkdir(parents=True)
            gitkeep = path / ".gitkeep"
            gitkeep.touch()
            created.append(str(path.relative_to(ROOT)))
            ok(f"Created {d}/")
        else:
            ok(f"{d}/ already exists")

    config_env = ROOT / ".env"
    if not config_env.exists():
        config_env.write_text(
            "# ESPAI Hub configuration\n"
            "ESPAI_HOST=0.0.0.0\n"
            "ESPAI_PORT=7888\n"
            "ESPAI_DEBUG=0\n",
            encoding="utf-8",
        )
        ok("Created .env (edit to customize)")
    else:
        ok(".env already exists")

    print()
    if created:
        info(f"Created: {', '.join(created)}")
    info("Run 'python ESPAI.py doctor' to verify dependencies.")
    info("Run 'python ESPAI.py serve' to start the hub.")
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
    check_cmd("pio",        "--version", label="PlatformIO")
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
    for d in REQUIRED_DIRS:
        path = ROOT / d
        if path.exists():
            ok(f"{d}/")
        else:
            warn(f"{d}/ — missing (run: ESPAI init)")
    print()


def cmd_serve(args):
    host = args.host or os.environ.get("ESPAI_HOST", "0.0.0.0")
    port = args.port or int(os.environ.get("ESPAI_PORT", "7888"))
    reload = args.reload

    # Load .env if present
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    print(f"\n  ESPAI Hub starting on http://{host}:{port}\n")
    print(f"  Dashboard : http://localhost:{port}/")
    print(f"  API docs  : http://localhost:{port}/docs")
    print(f"  Status    : http://localhost:{port}/api/status")
    if VENV_PYTHON != sys.executable:
        print(f"  Python    : {VENV_PYTHON} (venv)")
    print()

    # If a venv exists and we're not already in it, re-launch using its Python.
    # Use subprocess.run (not os.execv) — execv splits on spaces in the path
    # on Windows, breaking paths like "C:\Users\Roto Router\...".
    if VENV_PYTHON != sys.executable:
        cmd = (
            [VENV_PYTHON, __file__, "serve", "--host", host, "--port", str(port)]
            + (["--reload"] if reload else [])
        )
        result = subprocess.run(cmd, cwd=str(ROOT))
        sys.exit(result.returncode)

    try:
        import uvicorn
    except ImportError:
        err("uvicorn not installed. Run: python ESPAI.py install-deps")
        sys.exit(1)

    # Run from repo root so hub.backend.main:app resolves correctly
    os.chdir(ROOT)
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

    venv_dir = ROOT / ".venv"
    if not venv_dir.exists():
        print("  Creating .venv …")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

    pip = str(venv_dir / "Scripts" / "pip.exe") if (venv_dir / "Scripts").exists() \
          else str(venv_dir / "bin" / "pip")

    print(f"  Running: {pip} install -r {HUB_REQUIREMENTS}\n")
    result = subprocess.run(
        [pip, "install", "-r", str(HUB_REQUIREMENTS)],
        cwd=ROOT,
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
    parser = argparse.ArgumentParser(
        prog="ESPAI",
        description="ESPAI Hub CLI — local-first ESP32 platform",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialize workspace directories")

    sub.add_parser("doctor", help="Check dependencies and workspace")

    serve_p = sub.add_parser("serve", help="Start the hub server")
    serve_p.add_argument("--host", default=None, help="Bind host (default: 0.0.0.0)")
    serve_p.add_argument("--port", default=None, type=int, help="Bind port (default: 7888)")
    serve_p.add_argument("--reload", action="store_true", help="Enable hot-reload (dev)")

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
