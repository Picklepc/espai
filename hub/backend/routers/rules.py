"""
ESPAI Rules Router — CRUD for event-triggered automation rules.

Rules live in the `rules` DB table and are evaluated by the rules engine
every time an event is published to POST /api/events/publish.

Supported action types:
  log_event   { }                           — writes a log line
  run_worker  { "worker_name": "my-worker" } — queues a job
  webhook     { "url": "http://..." }        — HTTP POST to a URL
"""
import json
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_conn

router = APIRouter()

_VALID_ACTION_TYPES = {"log_event", "run_worker", "webhook"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    d = dict(row)
    if d.get("action_config"):
        try:
            d["action_config"] = json.loads(d["action_config"])
        except Exception:
            pass
    d["enabled"] = bool(d.get("enabled", 1))
    return d


class RuleCreate(BaseModel):
    name: str
    event_type: str
    source_filter: str | None = None
    action_type: str
    action_config: dict = {}
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    source_filter: str | None = None
    action_config: dict | None = None


@router.get("/")
def list_rules():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM rules ORDER BY created DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/{rule_id}")
def get_rule(rule_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Rule {rule_id!r} not found")
    return _row_to_dict(row)


@router.post("/")
def create_rule(data: RuleCreate):
    if data.action_type not in _VALID_ACTION_TYPES:
        raise HTTPException(400, f"action_type must be one of: {', '.join(sorted(_VALID_ACTION_TYPES))}")
    if not data.name.strip():
        raise HTTPException(400, "name must not be empty")
    if not data.event_type.strip():
        raise HTTPException(400, "event_type must not be empty")

    rule_id = secrets.token_hex(6)
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO rules (id, name, enabled, event_type, source_filter, action_type, action_config, created)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                rule_id, data.name.strip(), int(data.enabled),
                data.event_type.strip(), data.source_filter or None,
                data.action_type, json.dumps(data.action_config), now,
            ),
        )
    return {"id": rule_id, "name": data.name, "created": now}


@router.patch("/{rule_id}")
def update_rule(rule_id: str, data: RuleUpdate):
    updates, vals = [], []
    if data.name is not None:
        updates.append("name=?"); vals.append(data.name.strip())
    if data.enabled is not None:
        updates.append("enabled=?"); vals.append(int(data.enabled))
    if data.source_filter is not None:
        updates.append("source_filter=?"); vals.append(data.source_filter or None)
    if data.action_config is not None:
        updates.append("action_config=?"); vals.append(json.dumps(data.action_config))
    if not updates:
        return {"status": "no-op"}
    vals.append(rule_id)
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM rules WHERE id=?", (rule_id,)).fetchone():
            raise HTTPException(404, f"Rule {rule_id!r} not found")
        conn.execute(f"UPDATE rules SET {', '.join(updates)} WHERE id=?", vals)
    return {"status": "updated"}


@router.delete("/{rule_id}")
def delete_rule(rule_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
    return {"status": "deleted"}
