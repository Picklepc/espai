"""
Device Command Queue — hub → device bidirectional channel.

Devices poll GET /api/devices/{id}/commands/pending every 1-5 s to receive
commands queued by the hub, rules engine, or operator.

Lifecycle:  pending → delivered (on poll) → acked (device confirms execution)
            pending → expired  (TTL exceeded — background TTL sweeper)
            pending → cancelled (explicit DELETE)
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_conn

router = APIRouter()

_BUILT_IN_TYPES = {"reboot", "set_config", "run_ota_check", "user_action"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Pydantic models ───────────────────────────────────────────────────────────

class CommandCreate(BaseModel):
    command_type: str = "user_action"
    payload: dict = {}
    ttl_seconds: int = 300

class CommandAck(BaseModel):
    result: Optional[dict] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{device_id}/commands", status_code=201)
def enqueue_command(device_id: str, data: CommandCreate):
    """Hub or rules engine enqueues a command for a device."""
    cmd_id = str(uuid.uuid4())
    now    = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO device_commands
               (id, device_id, command_type, payload, status, created, ttl_seconds)
               VALUES (?,?,?,?,?,?,?)""",
            (cmd_id, device_id, data.command_type,
             json.dumps(data.payload), "pending", now, max(10, data.ttl_seconds)),
        )
    return {"id": cmd_id, "device_id": device_id, "command_type": data.command_type, "status": "pending"}


@router.get("/{device_id}/commands/pending")
def poll_pending(device_id: str):
    """
    Device polls this endpoint. Returns all pending commands and marks them delivered.
    Typically called every 1-5 seconds by the device firmware.
    """
    now = _now()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM device_commands
               WHERE device_id=? AND status='pending'
               ORDER BY created ASC""",
            (device_id,),
        ).fetchall()
        cmds = [dict(r) for r in rows]
        if cmds:
            ids = [r["id"] for r in cmds]
            conn.execute(
                f"UPDATE device_commands SET status='delivered', delivered_at=? WHERE id IN ({','.join('?'*len(ids))})",
                [now] + ids,
            )
    return {"commands": cmds}


@router.post("/{device_id}/commands/{cmd_id}/ack")
def ack_command(device_id: str, cmd_id: str, data: CommandAck):
    """Device confirms it has executed a command."""
    now = _now()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM device_commands WHERE id=? AND device_id=?",
            (cmd_id, device_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, f"Command {cmd_id!r} not found for device {device_id!r}")
        conn.execute(
            "UPDATE device_commands SET status='acked', acked_at=? WHERE id=?",
            (now, cmd_id),
        )
    return {"id": cmd_id, "status": "acked"}


@router.get("/{device_id}/commands")
def list_commands(device_id: str, status: Optional[str] = None, limit: int = 50):
    """Hub view — command history for a device."""
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM device_commands WHERE device_id=? AND status=? ORDER BY created DESC LIMIT ?",
                (device_id, status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM device_commands WHERE device_id=? ORDER BY created DESC LIMIT ?",
                (device_id, limit),
            ).fetchall()
    return [dict(r) for r in rows]


@router.delete("/{device_id}/commands/{cmd_id}")
def cancel_command(device_id: str, cmd_id: str):
    """Cancel a pending command before the device picks it up."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM device_commands WHERE id=? AND device_id=?",
            (cmd_id, device_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Command not found")
        if row["status"] != "pending":
            raise HTTPException(400, f"Cannot cancel a command with status={row['status']!r}")
        conn.execute(
            "UPDATE device_commands SET status='cancelled' WHERE id=?", (cmd_id,)
        )
    return {"id": cmd_id, "status": "cancelled"}


# ── Background TTL sweeper (called from main.py lifespan) ─────────────────────

def expire_stale_commands() -> int:
    """
    Mark commands as expired when created + ttl_seconds < now.
    Returns the number of commands expired.
    Called periodically (every 60 s) from a background thread.
    """
    now = _now()
    with get_conn() as conn:
        result = conn.execute(
            """UPDATE device_commands
               SET status='expired'
               WHERE status='pending'
                 AND datetime(created, '+' || ttl_seconds || ' seconds') < datetime(?)""",
            (now,),
        )
        return result.rowcount
