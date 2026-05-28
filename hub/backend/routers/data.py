"""
ESPAI Hub — Project Data Store

ESP32 devices push time-series readings here; web apps read them back.
This decouples the web app lifetime from the device lifetime — dashboards
work 24/7 even when the ESP32 is asleep or on a low-power duty cycle.

Push endpoint (called by ESP32 firmware):
    POST /api/projects/{project_id}/data
    Headers:  X-Device-ID: node-abc123   (optional, defaults to device IP)
    Body:     {"temperature": 23.5, "humidity": 65, "battery_pct": 87}

Pull endpoints (called by hub-hosted web apps):
    GET  /api/projects/{project_id}/data/latest          → last reading
    GET  /api/projects/{project_id}/data?limit=200       → history (newest first)
    GET  /api/projects/{project_id}/data?key=temperature → single-key history
    DELETE /api/projects/{project_id}/data               → clear history
"""

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query

from ..db import get_conn

router = APIRouter()

# Keep at most this many rows per project (oldest pruned on each push)
_MAX_ROWS_PER_PROJECT = 10_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Push ─────────────────────────────────────────────────────────────────────

@router.post("/{project_id}/data", status_code=201)
async def push_data(project_id: str, request: Request):
    """
    Accept a JSON payload from an ESP32 device and store it.

    The device identifies itself via the optional X-Device-ID header.
    If omitted, the client IP is used as the device identifier.

    The payload is stored verbatim — any flat JSON object is valid.
    The hub also upserts a 'latest' cache entry for instant dashboard loads.
    """
    with get_conn() as conn:
        proj = conn.execute(
            "SELECT id FROM projects WHERE id=?", (project_id,)
        ).fetchone()
    if not proj:
        raise HTTPException(404, f"Project {project_id!r} not found")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Body must be a JSON object")
    if not isinstance(body, dict):
        raise HTTPException(400, "Payload must be a JSON object (key:value pairs)")

    device_id = (
        request.headers.get("X-Device-ID")
        or request.headers.get("x-device-id")
        or request.client.host
        or ""
    )
    payload_str = json.dumps(body)
    now = _now()

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO project_data (project_id, device_id, payload, timestamp) VALUES (?,?,?,?)",
            (project_id, device_id, payload_str, now),
        )
        # Upsert latest cache
        conn.execute(
            """INSERT INTO project_data_cache (project_id, device_id, payload, timestamp)
               VALUES (?,?,?,?)
               ON CONFLICT(project_id, device_id) DO UPDATE SET
                 payload=excluded.payload, timestamp=excluded.timestamp""",
            (project_id, device_id, payload_str, now),
        )
        # Prune oldest rows if over limit
        count = conn.execute(
            "SELECT COUNT(*) FROM project_data WHERE project_id=?", (project_id,)
        ).fetchone()[0]
        if count > _MAX_ROWS_PER_PROJECT:
            conn.execute(
                """DELETE FROM project_data WHERE id IN (
                     SELECT id FROM project_data WHERE project_id=?
                     ORDER BY timestamp ASC LIMIT ?
                   )""",
                (project_id, count - _MAX_ROWS_PER_PROJECT),
            )

    return {"stored": True, "project_id": project_id, "device_id": device_id, "timestamp": now}


# ── Latest ────────────────────────────────────────────────────────────────────

@router.get("/{project_id}/data/latest")
def get_latest(project_id: str):
    """
    Return the most recent reading for every device linked to this project.
    Web apps call this on load for an instant result — no history scan needed.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT device_id, payload, timestamp FROM project_data_cache WHERE project_id=?",
            (project_id,),
        ).fetchall()

    if not rows:
        return {"project_id": project_id, "devices": [], "note": "No data pushed yet"}

    devices = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except Exception:
            payload = {"_raw": row["payload"]}
        devices.append({
            "device_id":  row["device_id"],
            "payload":    payload,
            "timestamp":  row["timestamp"],
        })
    return {"project_id": project_id, "devices": devices}


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/{project_id}/data")
def get_history(
    project_id: str,
    device_id:  Optional[str] = None,
    key:        Optional[str] = None,
    limit:      int = Query(default=200, le=10_000),
    since:      Optional[str] = None,   # ISO timestamp
):
    """
    Return historical readings for a project, newest first.

    Filters:
      device_id — restrict to one device
      key       — extract only a single field from the payload (e.g. "temperature")
      limit     — max rows (default 200, max 10 000)
      since     — only rows after this ISO timestamp
    """
    sql = "SELECT device_id, payload, timestamp FROM project_data WHERE project_id=?"
    params: list = [project_id]
    if device_id:
        sql += " AND device_id=?"; params.append(device_id)
    if since:
        sql += " AND timestamp > ?"; params.append(since)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    results = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except Exception:
            payload = {"_raw": row["payload"]}
        entry = {"device_id": row["device_id"], "timestamp": row["timestamp"]}
        if key:
            entry["value"] = payload.get(key)
        else:
            entry["payload"] = payload
        results.append(entry)

    return {"project_id": project_id, "count": len(results), "rows": results}


# ── Clear ─────────────────────────────────────────────────────────────────────

@router.delete("/{project_id}/data")
def clear_data(project_id: str):
    """Delete all stored readings for a project (irreversible)."""
    with get_conn() as conn:
        conn.execute("DELETE FROM project_data       WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM project_data_cache WHERE project_id=?", (project_id,))
    return {"cleared": True, "project_id": project_id}
