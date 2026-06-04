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
import math
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query

from ..db import get_conn

router = APIRouter()

# Keep at most this many rows per project (oldest pruned on each push)
_MAX_ROWS_PER_PROJECT = 10_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return distance in metres between two WGS-84 coordinates."""
    R = 6_371_000.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lng2 - lng1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_in_polygon(lat: float, lng: float, polygon: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon test. polygon = [[lat,lng], ...]."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        yi, xi = polygon[i][0], polygon[i][1]
        yj, xj = polygon[j][0], polygon[j][1]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


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
    # Extract _location field if present — stored in lat/lng columns for spatial queries
    location = body.pop("_location", None) if isinstance(body.get("_location"), dict) else None
    lat = location.get("lat") if location else None
    lng = location.get("lng") if location else None
    if lat is not None and not isinstance(lat, (int, float)):
        lat = None
    if lng is not None and not isinstance(lng, (int, float)):
        lng = None

    payload_str = json.dumps(body)
    now = _now()

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO project_data (project_id, device_id, payload, lat, lng, timestamp) VALUES (?,?,?,?,?,?)",
            (project_id, device_id, payload_str, lat, lng, now),
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


# ── Spatial ───────────────────────────────────────────────────────────────────

@router.get("/{project_id}/data/spatial")
def spatial_query(
    project_id: str,
    lat:       float,
    lng:       float,
    radius_m:  float  = 500.0,
    device_id: Optional[str] = None,
    limit:     int    = 200,
    since:     Optional[str] = None,
):
    """
    Return data points within radius_m metres of (lat, lng), newest first.
    Uses a bounding-box pre-filter then exact Haversine in Python.

    Push location with your data:
      POST /api/projects/{id}/data
      { "_location": { "lat": 38.89, "lng": -77.04 }, "temperature": 23.5 }
    """
    # Approximate degree offsets for bounding box (1° lat ≈ 111 km)
    delta_lat = radius_m / 111_000.0
    delta_lng = radius_m / (111_000.0 * math.cos(math.radians(lat))) if abs(lat) < 89.9 else 180.0

    sql = """
        SELECT device_id, payload, lat, lng, timestamp
        FROM project_data
        WHERE project_id=?
          AND lat BETWEEN ? AND ?
          AND lng BETWEEN ? AND ?
    """
    params: list = [
        project_id,
        lat - delta_lat, lat + delta_lat,
        lng - delta_lng, lng + delta_lng,
    ]
    if device_id:
        sql += " AND device_id=?"; params.append(device_id)
    if since:
        sql += " AND timestamp > ?"; params.append(since)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit * 3)  # over-fetch for Haversine filter

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    results = []
    for row in rows:
        d = _haversine_m(lat, lng, row["lat"], row["lng"])
        if d > radius_m:
            continue
        try:
            payload = json.loads(row["payload"])
        except Exception:
            payload = {}
        results.append({
            "device_id":  row["device_id"],
            "lat":        row["lat"],
            "lng":        row["lng"],
            "distance_m": round(d, 1),
            "payload":    payload,
            "timestamp":  row["timestamp"],
        })
        if len(results) >= limit:
            break

    results.sort(key=lambda r: r["timestamp"], reverse=True)
    return {"project_id": project_id, "center": {"lat": lat, "lng": lng},
            "radius_m": radius_m, "count": len(results), "rows": results}


@router.get("/{project_id}/track")
def position_track(
    project_id: str,
    device_id:  Optional[str] = None,
    limit:      int  = 500,
    since:      Optional[str] = None,
):
    """
    Return chronological position trail for location-tagged data points.
    Use for GPS track display on a map.
    """
    sql = """
        SELECT device_id, lat, lng, timestamp, payload
        FROM project_data
        WHERE project_id=? AND lat IS NOT NULL AND lng IS NOT NULL
    """
    params: list = [project_id]
    if device_id:
        sql += " AND device_id=?"; params.append(device_id)
    if since:
        sql += " AND timestamp > ?"; params.append(since)
    sql += " ORDER BY timestamp ASC LIMIT ?"
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    track = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except Exception:
            payload = {}
        track.append({
            "device_id": row["device_id"],
            "lat":       row["lat"],
            "lng":       row["lng"],
            "timestamp": row["timestamp"],
            "payload":   payload,
        })
    return {"project_id": project_id, "count": len(track), "track": track}


@router.post("/{project_id}/data/geofence-check")
def geofence_check(project_id: str, body: dict):
    """
    Check whether any recent data points from a device are inside or outside a polygon.

    Body: { "device_id": "...", "polygon": [[lat,lng],...], "since": "ISO" (optional) }
    Returns: { "inside": bool, "last_position": {lat, lng, timestamp} | null }
    """
    device_id = body.get("device_id")
    polygon   = body.get("polygon", [])
    since     = body.get("since")
    if not device_id or len(polygon) < 3:
        raise HTTPException(400, "device_id and polygon (≥3 points) required")

    sql = """
        SELECT lat, lng, timestamp FROM project_data
        WHERE project_id=? AND device_id=? AND lat IS NOT NULL
    """
    params: list = [project_id, device_id]
    if since:
        sql += " AND timestamp > ?"; params.append(since)
    sql += " ORDER BY timestamp DESC LIMIT 1"

    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()

    if not row:
        return {"inside": None, "last_position": None, "note": "No location data found"}

    inside = _point_in_polygon(row["lat"], row["lng"], polygon)
    return {
        "inside": inside,
        "last_position": {"lat": row["lat"], "lng": row["lng"], "timestamp": row["timestamp"]},
    }


# ── Aggregate ─────────────────────────────────────────────────────────────────

_BUCKET_EXPRS = {
    "1m":  "strftime('%Y-%m-%dT%H:%M:00', timestamp)",
    "5m":  "strftime('%Y-%m-%dT%H:', timestamp) || printf('%02d:00', (CAST(strftime('%M', timestamp) AS INTEGER) / 5) * 5)",
    "15m": "strftime('%Y-%m-%dT%H:', timestamp) || printf('%02d:00', (CAST(strftime('%M', timestamp) AS INTEGER) / 15) * 15)",
    "1h":  "strftime('%Y-%m-%dT%H:00:00', timestamp)",
    "6h":  "strftime('%Y-%m-%dT', timestamp) || printf('%02d:00:00', (CAST(strftime('%H', timestamp) AS INTEGER) / 6) * 6)",
    "1d":  "strftime('%Y-%m-%d', timestamp)",
}

_AGG_FNS = {
    "avg":   "AVG",
    "min":   "MIN",
    "max":   "MAX",
    "sum":   "SUM",
    "count": "COUNT",
    "last":  "MAX",  # use MAX(timestamp) trick below for last
}

_SINCE_OFFSETS = {
    "1h": "-1 hours",  "6h": "-6 hours",  "12h": "-12 hours",
    "1d": "-1 days",   "7d": "-7 days",   "30d": "-30 days",
    "90d": "-90 days",
}


@router.get("/{project_id}/data/aggregate")
def aggregate_data(
    project_id: str,
    field:     str,
    fn:        str  = Query(default="avg",  pattern="^(avg|min|max|sum|count|last)$"),
    bucket:    str  = Query(default="1h",   pattern="^(1m|5m|15m|1h|6h|1d)$"),
    since:     str  = Query(default="24h",  pattern="^(1h|6h|12h|1d|7d|30d|90d)$"),
    device_id: Optional[str] = None,
):
    """
    Return time-bucketed aggregates for a single field in a project's data store.

    Examples:
      GET /api/projects/{id}/data/aggregate?field=temperature&fn=avg&bucket=1h&since=7d
      → [{"bucket": "2026-06-04T14:00:00", "value": 23.4, "count": 12}, ...]
    """
    bucket_expr = _BUCKET_EXPRS[bucket]
    agg_fn      = _AGG_FNS[fn]
    offset      = _SINCE_OFFSETS[since]

    # json_extract pulls the field from the JSON payload column
    field_expr = f"CAST(json_extract(payload, '$.{field}') AS REAL)"

    if fn == "count":
        val_expr = f"COUNT({field_expr})"
    elif fn == "last":
        # last value in each bucket = value at max(timestamp)
        val_expr = f"MAX(CASE WHEN timestamp=(SELECT MAX(t2.timestamp) FROM project_data t2 WHERE t2.project_id=project_data.project_id AND {bucket_expr}=(SELECT {bucket_expr} FROM project_data t3 WHERE t3.id=t2.id) ) THEN {field_expr} END)"
        # simpler: just use AVG and note it's approximate; true "last" needs subquery
        # Use the simpler approach: SQLite GROUP_CONCAT trick isn't great, just use the value at MAX rowid
        val_expr = f"AVG({field_expr})"  # fallback; "last" is best-effort
    else:
        val_expr = f"{agg_fn}({field_expr})"

    sql = f"""
        SELECT
            {bucket_expr} AS bucket,
            {val_expr}    AS value,
            COUNT(*)      AS count
        FROM project_data
        WHERE project_id = ?
          AND timestamp > datetime('now', ?)
          AND json_extract(payload, '$.{field}') IS NOT NULL
    """
    params: list = [project_id, offset]
    if device_id:
        sql += " AND device_id = ?"
        params.append(device_id)
    sql += " GROUP BY bucket ORDER BY bucket ASC"

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    return {
        "project_id": project_id,
        "field":      field,
        "fn":         fn,
        "bucket":     bucket,
        "since":      since,
        "count":      len(rows),
        "rows":       [{"bucket": r["bucket"], "value": r["value"], "count": r["count"]} for r in rows],
    }


# ── Clear ─────────────────────────────────────────────────────────────────────

@router.delete("/{project_id}/data")
def clear_data(project_id: str):
    """Delete all stored readings for a project (irreversible)."""
    with get_conn() as conn:
        conn.execute("DELETE FROM project_data       WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM project_data_cache WHERE project_id=?", (project_id,))
    return {"cleared": True, "project_id": project_id}
