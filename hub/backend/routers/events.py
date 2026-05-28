"""
Local event bus.

Events are persisted in SQLite and surfaced via:
  GET /api/events/         — poll for recent events
  GET /api/events/stream   — Server-Sent Events stream (long-poll, 2 s tick)
  POST /api/events/publish — emit a new event

The SSE stream adds a Cache-Control: no-cache header and follows the
EventSource protocol so browsers can subscribe with just:
  new EventSource('/api/events/stream?since_id=0')
"""
import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..db import get_conn
from .. import mqtt_publisher, ws_broker
from ..rules.engine import evaluate_rules

router = APIRouter()

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # disable nginx buffering for SSE
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deserialize(row) -> dict:
    d = dict(row)
    if d.get("payload"):
        try:
            d["payload"] = json.loads(d["payload"])
        except Exception:
            pass
    return d


class EventPublish(BaseModel):
    source: str
    event_type: str
    payload: dict = {}


@router.get("/")
def list_events(
    limit: int = 100,
    source: str | None = None,
    event_type: str | None = None,
):
    if limit > 1000:
        limit = 1000
    clauses, vals = [], []
    if source:
        clauses.append("source=?"); vals.append(source)
    if event_type:
        clauses.append("event_type=?"); vals.append(event_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    vals.append(limit)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM events {where} ORDER BY id DESC LIMIT ?", vals
        ).fetchall()
    return [_deserialize(r) for r in rows]


@router.post("/publish")
def publish_event(data: EventPublish):
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO events (source, event_type, payload, timestamp) VALUES (?,?,?,?)",
            (data.source, data.event_type, json.dumps(data.payload), now),
        )
        event_id = cur.lastrowid
    ev = {
        "id": event_id,
        "source": data.source,
        "event_type": data.event_type,
        "payload": data.payload,
        "timestamp": now,
    }
    # Evaluate rules after the event is committed
    evaluate_rules(ev)
    # Forward to MQTT broker if configured
    mqtt_publisher.publish_event(data.source, data.event_type, data.payload)
    # Broadcast to WebSocket clients in real time
    ws_broker.broadcast_event_sync(ev)
    return {"status": "published"}


@router.get("/stream")
async def event_stream(since_id: int = 0):
    """
    SSE stream. Client tracks last received event ID and reconnects with it.
    The stream never ends — the client disconnects when it's done.
    """
    async def generator():
        last_id = since_id
        # Send a comment to confirm connection immediately
        yield ": connected\n\n"
        while True:
            try:
                with get_conn() as conn:
                    rows = conn.execute(
                        "SELECT * FROM events WHERE id > ? ORDER BY id ASC LIMIT 50",
                        (last_id,),
                    ).fetchall()
                for row in rows:
                    d = _deserialize(row)
                    last_id = d["id"]
                    yield f"id: {last_id}\ndata: {json.dumps(d)}\n\n"
            except Exception:
                pass
            await asyncio.sleep(2)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
