"""
ESPAI WebSocket broker — realtime fan-out hub.

Every event published via POST /api/events/publish is broadcast to all connected
WebSocket clients instantly, replacing the 2-second SSE polling loop.

The WebSocket endpoint lives at /api/ws (wired in main.py).

Thread safety: broadcast_event_sync() is safe to call from worker threads or the
rules engine. It schedules the async broadcast on the uvicorn event loop that was
captured at startup via set_loop().
"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import WebSocket

log = logging.getLogger(__name__)

_loop: Optional[asyncio.AbstractEventLoop] = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Capture the running asyncio loop so sync threads can schedule broadcasts."""
    global _loop
    _loop = loop


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        log.debug("ws: client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        log.debug("ws: client disconnected (%d total)", len(self._connections))

    @property
    def count(self) -> int:
        return len(self._connections)

    async def broadcast(self, message: dict) -> None:
        if not self._connections:
            return
        data = json.dumps(message)
        dead: set[WebSocket] = set()
        for ws in list(self._connections):
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._connections.discard(ws)
        if dead:
            log.debug("ws: pruned %d dead connection(s)", len(dead))


manager = ConnectionManager()


def broadcast_event_sync(event: dict) -> None:
    """
    Schedule an event broadcast from any thread.
    No-op if the event loop isn't captured yet or isn't running.
    """
    if _loop is None or not _loop.is_running():
        return
    try:
        asyncio.run_coroutine_threadsafe(manager.broadcast(event), _loop)
    except Exception as exc:
        log.debug("ws: broadcast_event_sync failed: %s", exc)
