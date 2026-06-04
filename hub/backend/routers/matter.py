"""
ESPAI Matter Bridge router — /api/matter/...

Provides bridge control, commissioning QR code, and the command webhook
that the Node.js bridge calls when Matter sends a command to a device.
"""

import logging

from fastapi import APIRouter, HTTPException

from .. import matter_bridge, ws_broker
from ..rules.engine import fire_event

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/status")
def matter_status():
    """Bridge status, commissioned state, and registered endpoint list."""
    return matter_bridge.get_status()


@router.get("/qrcode")
def matter_qrcode():
    """QR code SVG + pairing codes for Matter commissioning."""
    qr = matter_bridge.get_qrcode()
    if qr is None:
        raise HTTPException(404, "Bridge not running or QR not available")
    return qr


@router.post("/bridge/start")
def matter_bridge_start():
    """Start the Matter bridge process."""
    ok = matter_bridge.start()
    if ok:
        matter_bridge.sync_all_projects()
    return {"started": ok, **matter_bridge.get_status()}


@router.post("/bridge/stop")
def matter_bridge_stop():
    """Stop the Matter bridge process."""
    matter_bridge.stop()
    return {"stopped": True}


@router.post("/sync")
def matter_sync():
    """Re-register all matter-enabled projects with the running bridge."""
    if not matter_bridge.is_running():
        raise HTTPException(503, "Bridge not running")
    matter_bridge.sync_all_projects()
    return {"synced": True, **matter_bridge.get_status()}


@router.post("/command")
async def matter_command(body: dict):
    """
    Webhook called by the bridge when Matter sends a command to a device.
    Body: { device_id, command, args }
    Routes to the project's matter_command_actions config.
    """
    device_id = body.get("device_id", "")
    command   = body.get("command", "")
    args      = body.get("args", {})

    if not device_id or not command:
        raise HTTPException(400, "device_id and command required")

    # Read command actions for this project
    cfg = matter_bridge._read_matter_cfg(device_id)
    action = None
    if cfg:
        action = cfg.get("matter_command_actions", {}).get(command)

    if action:
        atype = action.get("type")
        if atype == "event":
            event_type = action.get("event_type", f"matter.{command}")
            await fire_event(event_type, {"device_id": device_id, "command": command, **args})
        elif atype == "device_api":
            _call_device_api(device_id, action.get("endpoint", ""), command, args)
        else:
            log.warning("matter command: unknown action type %s", atype)
    else:
        # Default: fire a generic matter.command event
        event_type = f"matter.{command}"
        await fire_event(event_type, {"device_id": device_id, "command": command, **args})

    # Broadcast over WebSocket so the dashboard can react in real time
    ws_broker.publish({"type": "matter.command",
                       "device_id": device_id,
                       "command": command,
                       "args": args})

    return {"routed": True, "device_id": device_id, "command": command}


def _call_device_api(project_id: str, endpoint: str, command: str, args: dict) -> None:
    """Best-effort call to a device HTTP endpoint based on a command action."""
    import json as _json
    import urllib.request
    from ..db import get_conn
    from ..config import PROJECTS_DIR

    if not endpoint:
        return
    try:
        with get_conn() as conn:
            proj = conn.execute(
                "SELECT devices FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        if not proj:
            return
        dev_ids = _json.loads(proj["devices"] or "[]")
        for did in dev_ids:
            with get_conn() as conn:
                dev = conn.execute("SELECT ip FROM devices WHERE id=?", (did,)).fetchone()
            if dev and dev["ip"]:
                url = f"http://{dev['ip']}{endpoint}"
                req = urllib.request.Request(url, method="POST",
                                             data=_json.dumps(args).encode(),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5):
                    pass
                return
    except Exception as e:
        log.warning("matter _call_device_api %s %s: %s", project_id, endpoint, e)
