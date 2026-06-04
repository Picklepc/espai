"""
ESPAI Matter Bridge router — /api/matter/...

Provides bridge control, commissioning QR code, and the command webhook
that the Node.js bridge calls when Matter sends a command to a device.
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from .. import matter_bridge, ws_broker
from ..db import get_conn
from ..rules.engine import evaluate_rules

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
def matter_command(body: dict):
    """
    Webhook called by the bridge when Matter sends a command to a device.
    Body: { device_id, command, args }
    Routes to the project's matter_command_actions config.
    """
    device_id = body.get("device_id", "")
    command   = body.get("command", "")
    args      = body.get("args", {}) or {}

    if not device_id or not command:
        raise HTTPException(400, "device_id and command required")

    # Read command actions for this project
    cfg    = matter_bridge._read_matter_cfg(device_id)
    action = cfg.get("matter_command_actions", {}).get(command) if cfg else None

    if action:
        atype = action.get("type")
        if atype == "event":
            _fire_matter_event(
                action.get("event_type", f"matter.{command}"),
                {"device_id": device_id, "command": command, **args},
            )
        elif atype == "device_api":
            _call_device_api(device_id, action.get("endpoint", ""), args)
        else:
            log.warning("matter command: unknown action type %r", atype)
    else:
        # Default: fire a generic matter.<command> event
        _fire_matter_event(
            f"matter.{command}",
            {"device_id": device_id, "command": command, **args},
        )

    # Broadcast over WebSocket so the dashboard can react in real time
    ws_broker.broadcast_event_sync({
        "type":      "matter.command",
        "device_id": device_id,
        "command":   command,
        "args":      args,
    })

    return {"routed": True, "device_id": device_id, "command": command}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fire_matter_event(event_type: str, payload: dict) -> None:
    """Persist a Matter command as an event and evaluate rules against it."""
    now = datetime.now(timezone.utc).isoformat()
    ev  = {
        "source":     "matter",
        "event_type": event_type,
        "payload":    payload,
        "timestamp":  now,
    }
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO events (source, event_type, payload, timestamp) VALUES (?,?,?,?)",
                (ev["source"], event_type, json.dumps(payload), now),
            )
    except Exception:
        log.warning("matter: failed to persist event %s", event_type)
    evaluate_rules(ev)


def _call_device_api(project_id: str, endpoint: str, args: dict) -> None:
    """Best-effort POST to a device HTTP endpoint based on a command action."""
    import urllib.request

    if not endpoint:
        return
    try:
        with get_conn() as conn:
            proj = conn.execute(
                "SELECT devices FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        if not proj:
            return
        dev_ids = json.loads(proj["devices"] or "[]")
        for did in dev_ids:
            with get_conn() as conn:
                dev = conn.execute("SELECT ip FROM devices WHERE id=?", (did,)).fetchone()
            if dev and dev["ip"]:
                url = f"http://{dev['ip']}{endpoint}"
                req = urllib.request.Request(
                    url, method="POST",
                    data=json.dumps(args).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5):
                    pass
                return
    except Exception as e:
        log.warning("matter _call_device_api %s %s: %s", project_id, endpoint, e)
