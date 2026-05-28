"""
ESPAI Hub — Admin endpoints: backup and restore.

GET  /api/admin/backup          — JSON snapshot of all DB tables + config
POST /api/admin/restore         — Restore devices, projects, and rules from a backup
GET  /api/admin/backup/download — Same as /backup but as a downloadable .json file

Restore is intentionally selective:
  - Restores: devices, projects, rules (persistent configuration)
  - Skips: events, ota_log, jobs, pairing_tokens (operational / append-only data)
  - Uses INSERT OR REPLACE so existing rows are overwritten.

The backup includes a `_meta` block with timestamp, version, and table manifest
so future versions can detect schema mismatches before attempting a restore.
"""

import json
import re
from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..config import ACTIVE_THEME
from ..db import get_conn

router = APIRouter()

_RESTORABLE_TABLES = ["devices", "projects", "rules"]
_BACKUP_TABLES     = ["devices", "projects", "rules", "ota_log", "events", "jobs"]

_HUB_VERSION = "0.1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump_table(conn, table: str) -> list[dict]:
    try:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        return [dict(r) for r in rows]
    except Exception:
        return []


def _build_backup() -> dict:
    with get_conn() as conn:
        tables = {t: _dump_table(conn, t) for t in _BACKUP_TABLES}

    return {
        "_meta": {
            "schema":    "ESPAI.backup.v1",
            "version":   _HUB_VERSION,
            "timestamp": _now(),
            "tables":    {t: len(rows) for t, rows in tables.items()},
            "active_theme": ACTIVE_THEME,
        },
        **tables,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/backup")
def get_backup():
    """Return a full JSON backup of all hub data."""
    return _build_backup()


@router.get("/backup/download")
def download_backup():
    """Return the backup as a downloadable .json file."""
    payload = json.dumps(_build_backup(), indent=2).encode("utf-8")
    ts      = datetime.now().strftime("%Y%m%d-%H%M%S")
    fname   = f"espai-backup-{ts}.json"
    return StreamingResponse(
        BytesIO(payload),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/restore")
async def restore_backup(request: Request):
    """
    Restore devices, projects, and rules from a backup JSON body.

    - Only the restorable tables (devices, projects, rules) are touched.
    - Existing rows with the same primary key are replaced.
    - Events, jobs, ota_log, and pairing_tokens are left unchanged.
    - Returns a summary of rows restored per table.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Request body must be valid JSON")

    meta = body.get("_meta", {})
    schema = meta.get("schema", "")
    if schema and schema != "ESPAI.backup.v1":
        raise HTTPException(422, f"Unrecognised backup schema: {schema!r}")

    # Column allowlists guard against injection via crafted backup keys
    _ALLOWED_COLS: dict[str, set[str]] = {
        "devices":  {"id","ip","name","board","fw_version","paired","last_seen","capabilities","meta"},
        "projects": {"id","name","description","devices","created","meta"},
        "rules":    {"id","name","enabled","event_type","source_filter","action_type","action_config","created","last_triggered"},
    }

    summary: dict[str, int] = {}
    with get_conn() as conn:
        for table in _RESTORABLE_TABLES:
            rows = body.get(table, [])
            if not isinstance(rows, list):
                continue
            allowed = _ALLOWED_COLS[table]
            count   = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                clean = {k: v for k, v in row.items() if k in allowed}
                if not clean:
                    continue
                cols  = ", ".join(clean.keys())
                phlds = ", ".join("?" * len(clean))
                vals  = list(clean.values())
                conn.execute(
                    f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({phlds})",  # noqa: S608
                    vals,
                )
                count += 1
            summary[table] = count

    return {
        "status":    "restored",
        "timestamp": _now(),
        "restored":  summary,
        "skipped":   [t for t in _BACKUP_TABLES if t not in _RESTORABLE_TABLES],
    }


@router.get("/status")
def admin_status():
    """Return row counts for all tables — useful for monitoring."""
    with get_conn() as conn:
        counts = {}
        for table in _BACKUP_TABLES:
            try:
                counts[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"  # noqa: S608
                ).fetchone()[0]
            except Exception:
                counts[table] = -1
    return {"table_counts": counts, "timestamp": _now()}
