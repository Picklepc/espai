"""
ESPAI Matter Bridge — process manager and HTTP client.

Spawns hub/matter/bridge.mjs as a child Node.js process and communicates
with it via a local HTTP API on ESPAI_MATTER_PORT (default 5580).

All public functions are safe to call even when Node.js is not installed
or when ESPAI_MATTER_AUTOSTART is not set — they no-op gracefully.
"""

import json
import logging
import os
import re
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

from .config import PROJECTS_DIR

log = logging.getLogger(__name__)

_PORT       = int(os.environ.get("ESPAI_MATTER_PORT", "5580"))
_HUB_PORT   = int(os.environ.get("ESPAI_PORT",        "7888"))
_BRIDGE_DIR = Path(__file__).parent.parent / "matter"
_BASE_URL   = f"http://127.0.0.1:{_PORT}"

_proc:   subprocess.Popen | None = None
_lock    = threading.Lock()
_running = False


# ── Internal helpers ──────────────────────────────────────────────────────────

def _call(method: str, path: str, body=None, timeout: int = 5):
    url  = _BASE_URL + path
    data = json.dumps(body).encode() if body is not None else None
    req  = urllib.request.Request(url, data=data, method=method,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Matter bridge unreachable: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Matter bridge error: {e}") from e


def _update_state_bg(device_id: str, state_dict: dict) -> None:
    """Fire-and-forget: update device state without blocking caller."""
    def _run():
        try:
            _call("PUT", f"/devices/{device_id}/state", state_dict)
        except Exception as e:
            log.debug("matter_bridge.update_state %s: %s", device_id, e)
    threading.Thread(target=_run, daemon=True, name="matter-state-push").start()


# ── Public API ────────────────────────────────────────────────────────────────

def start() -> bool:
    """
    Start the bridge process.  No-ops if already running or if Node.js is
    not installed.  Returns True if the bridge came up successfully.
    """
    global _proc, _running
    with _lock:
        if _running:
            return True

        bridge_script = _BRIDGE_DIR / "bridge.mjs"
        if not bridge_script.exists():
            log.warning("Matter bridge: bridge.mjs not found at %s", bridge_script)
            return False

        # Resolve node executable
        node = _find_node()
        if not node:
            log.info("Matter bridge: Node.js not found — Matter disabled")
            return False

        # Ensure npm deps are installed
        _ensure_deps()

        env = {**os.environ,
               "ESPAI_MATTER_PORT":  str(_PORT),
               "ESPAI_HUB_PORT":     str(_HUB_PORT),
               "ESPAI_MATTER_STORAGE": str(_BRIDGE_DIR / "data" / "matter-storage")}

        try:
            _proc = subprocess.Popen(
                [node, str(bridge_script)],
                cwd=str(_BRIDGE_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            log.error("Matter bridge: failed to start process: %s", e)
            return False

        # Wait for "READY" line (15 s timeout)
        import time
        deadline = time.time() + 15
        ready = False
        while time.time() < deadline:
            if _proc.poll() is not None:
                log.error("Matter bridge: process exited early (code %d)", _proc.returncode)
                break
            line = _proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            log.debug("[matter] %s", line.rstrip())
            if "READY" in line:
                ready = True
                break

        if not ready:
            log.error("Matter bridge: did not become ready within 15 s")
            try:
                _proc.kill()
            except Exception:
                pass
            _proc = None
            return False

        # Drain stdout in background
        threading.Thread(target=_drain_log, args=(_proc,), daemon=True,
                         name="matter-log").start()

        _running = True
        log.info("Matter bridge started on port %d", _PORT)
        return True


def stop() -> None:
    global _proc, _running
    with _lock:
        if not _running or _proc is None:
            _running = False
            return
        try:
            _call("POST", "/shutdown")
        except Exception:
            pass
        import time
        deadline = time.time() + 5
        while time.time() < deadline and _proc.poll() is None:
            time.sleep(0.1)
        if _proc.poll() is None:
            _proc.kill()
        _proc = None
        _running = False
        log.info("Matter bridge stopped")


def is_running() -> bool:
    global _running, _proc
    if not _running:
        return False
    if _proc is not None and _proc.poll() is not None:
        # Process died unexpectedly
        _running = False
        _proc = None
        return False
    return True


def get_status() -> dict:
    if not is_running():
        return {"enabled": False, "running": False, "commissioned": False, "endpoints": []}
    try:
        status = _call("GET", "/status")
        status["enabled"] = True
        return status
    except Exception as e:
        log.warning("matter get_status: %s", e)
        return {"enabled": True, "running": False, "commissioned": False, "endpoints": [], "error": str(e)}


def get_qrcode() -> dict | None:
    if not is_running():
        return None
    try:
        return _call("GET", "/qrcode")
    except Exception as e:
        log.warning("matter get_qrcode: %s", e)
        return None


def register_device(device_id: str, name: str, device_type: str,
                    initial_state: dict | None = None) -> dict:
    return _call("POST", "/devices", {
        "id": device_id, "name": name,
        "device_type": device_type,
        "state": initial_state or {},
    })


def update_state(device_id: str, state_dict: dict) -> None:
    """Non-blocking state push — called from push_data hot path."""
    if is_running():
        _update_state_bg(device_id, state_dict)


def remove_device(device_id: str) -> bool:
    try:
        result = _call("DELETE", f"/devices/{device_id}")
        return result.get("removed", False)
    except Exception as e:
        log.warning("matter remove_device %s: %s", device_id, e)
        return False


def _safe_endpoint_id(project_id: str, device_id: str) -> str:
    """URL-safe endpoint ID for per-device Matter endpoints."""
    return f"{project_id}_{re.sub(r'[^a-zA-Z0-9_-]', '_', device_id)}"


def _linked_device_ids(project_id: str) -> list[str]:
    """Return the list of device IDs linked to a project."""
    try:
        from .db import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT devices FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        return json.loads(row["devices"] or "[]") if row else []
    except Exception:
        return []


def sync_project(project_id: str) -> None:
    """Read project matter config and register/remove its endpoint(s)."""
    cfg = _read_matter_cfg(project_id)
    if not cfg:
        return

    if cfg.get("matter_enabled"):
        name  = cfg.get("matter_label") or project_id
        dtype = cfg.get("matter_device_type", "on_off_plug")

        if cfg.get("matter_endpoint_per_device"):
            # One endpoint per linked device node
            device_ids = _linked_device_ids(project_id)
            for did in device_ids:
                eid    = _safe_endpoint_id(project_id, did)
                ep_name = f"{name} — {did}"
                try:
                    register_device(eid, ep_name, dtype)
                except Exception as e:
                    log.warning("matter sync_project %s device %s: %s", project_id, did, e)
            # Remove the single-project endpoint if it exists (migration)
            try:
                remove_device(project_id)
            except Exception:
                pass
        else:
            # Single endpoint per project (default)
            try:
                result = register_device(project_id, name, dtype)
                if result.get("created") or result.get("updated"):
                    cfg["matter_endpoint_id"] = result.get("endpoint_id")
                    _write_matter_cfg(project_id, cfg)
            except Exception as e:
                log.warning("matter sync_project %s: %s", project_id, e)
    else:
        # Remove single-project endpoint
        try:
            remove_device(project_id)
        except Exception:
            pass
        # Also remove any per-device endpoints that may exist
        for did in _linked_device_ids(project_id):
            try:
                remove_device(_safe_endpoint_id(project_id, did))
            except Exception:
                pass


def sync_all_projects() -> None:
    """Re-register all matter-enabled projects with the bridge."""
    if not PROJECTS_DIR.exists():
        return
    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        cfg = _read_matter_cfg(proj_dir.name)
        if cfg and cfg.get("matter_enabled"):
            sync_project(proj_dir.name)


# ── Config helpers ────────────────────────────────────────────────────────────

_MATTER_DEFAULTS = {
    "matter_enabled":              False,
    "matter_device_type":          "on_off_plug",
    "matter_label":                "",
    "matter_state_map":            {},
    "matter_command_actions":      {},
    "matter_endpoint_id":          None,
    "matter_endpoint_per_device":  False,
}
_MATTER_KEYS = set(_MATTER_DEFAULTS)


def _read_matter_cfg(project_id: str) -> dict | None:
    cfg_file = PROJECTS_DIR / project_id / ".ESPAI-project.json"
    if not cfg_file.exists():
        return None
    try:
        full = json.loads(cfg_file.read_text(encoding="utf-8"))
        result = {**_MATTER_DEFAULTS}
        for k in _MATTER_KEYS:
            if k in full:
                result[k] = full[k]
        return result
    except Exception:
        return None


def _write_matter_cfg(project_id: str, matter_cfg: dict) -> None:
    cfg_file = PROJECTS_DIR / project_id / ".ESPAI-project.json"
    try:
        full = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
        for k in _MATTER_KEYS:
            if k in matter_cfg:
                full[k] = matter_cfg[k]
        cfg_file.write_text(json.dumps(full, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("matter _write_matter_cfg %s: %s", project_id, e)


# ── Process helpers ───────────────────────────────────────────────────────────

def _find_node() -> str | None:
    import shutil
    for candidate in ("node", "node.exe", "nodejs"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _ensure_deps() -> None:
    node_modules = _BRIDGE_DIR / "node_modules"
    pkg_json     = _BRIDGE_DIR / "package.json"
    if node_modules.exists() or not pkg_json.exists():
        return
    npm = _find_npm()
    if not npm:
        return
    log.info("Matter bridge: running npm install…")
    try:
        subprocess.run([npm, "install", "--omit=dev"],
                       cwd=str(_BRIDGE_DIR), check=True,
                       timeout=120, capture_output=True)
        log.info("Matter bridge: npm install complete")
    except Exception as e:
        log.warning("Matter bridge: npm install failed: %s", e)


def _find_npm() -> str | None:
    import shutil
    return shutil.which("npm") or shutil.which("npm.cmd")


def _drain_log(proc: subprocess.Popen) -> None:
    try:
        for line in proc.stdout:
            log.debug("[matter] %s", line.rstrip())
    except Exception:
        pass
