"""
ESPAI Hub — FastAPI entry point.

Run from repo root:
    uvicorn hub.backend.main:app --host 0.0.0.0 --port 7888 --reload

Or via the CLI:
    python ESPAI.py serve
"""
import asyncio
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import DEBUG, PORT
from .db import get_conn, init_db
from .discovery.mdns import mdns_manager
from . import mqtt_publisher, theme_scheduler, ws_broker
from .routers import admin, cards, design, devices, events, jobs, ota, projects, recipes, rules, workers
from .workers.runner import start_runner

log = logging.getLogger(__name__)

_SAFE_NODE_ID = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def _on_mdns_node_found(node: dict) -> None:
    """Upsert a node discovered via mDNS into the devices table, preserving paired state."""
    props = node.get("properties", {})
    raw_id = props.get("id", "")
    if not _SAFE_NODE_ID.match(raw_id):
        ip = node.get("ip") or ""
        raw_id = "mdns-" + ip.replace(".", "-")
        if not _SAFE_NODE_ID.match(raw_id):
            log.warning("mDNS: skipping node with unresolvable ID: %s", node)
            return
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_conn() as conn:
            existing = conn.execute(
                "SELECT paired FROM devices WHERE id=?", (raw_id,)
            ).fetchone()
            paired = int(existing["paired"]) if existing else 0
            conn.execute(
                """INSERT INTO devices (id, ip, name, board, fw_version, paired, last_seen)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     ip=excluded.ip, name=excluded.name, board=excluded.board,
                     fw_version=excluded.fw_version, last_seen=excluded.last_seen""",
                (
                    raw_id,
                    node.get("ip"),
                    props.get("name"),
                    props.get("board"),
                    props.get("version"),
                    paired,
                    now,
                ),
            )
        log.info("mDNS: registered node %s at %s", raw_id, node.get("ip"))
    except Exception:
        log.exception("mDNS: error upserting node %s", raw_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    start_runner()
    mdns_manager.start(hub_port=PORT, on_node_found=_on_mdns_node_found)
    mqtt_publisher.init()
    theme_scheduler.start()
    ws_broker.set_loop(asyncio.get_event_loop())
    yield
    # Shutdown
    mdns_manager.stop()
    mqtt_publisher.shutdown()


app = FastAPI(
    title="ESPAI Hub",
    description="Local-first ESP32 fleet and edge-processing platform",
    version="0.1.0",
    lifespan=lifespan,
    # Only expose docs in debug mode — there is no authentication on these endpoints
    docs_url="/docs" if DEBUG else "/docs",
    redoc_url=None,
)

# CORS: ESPAI is local-first. Allow all origins so the dashboard can be opened
# from any LAN host (e.g., phone browser pointing to the hub's LAN IP).
# Credentials are never sent — this is not a cookie-auth API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)

# ── API routers ───────────────────────────────────────────────────────────────

app.include_router(devices.router,  prefix="/api/devices",  tags=["devices"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(recipes.router,  prefix="/api/recipes",  tags=["recipes"])
app.include_router(workers.router,  prefix="/api/workers",  tags=["workers"])
app.include_router(cards.router,    prefix="/api/cards",    tags=["cards"])
app.include_router(design.router,   prefix="/api/design",   tags=["design"])
app.include_router(ota.router,      prefix="/api/ota",      tags=["ota"])
app.include_router(jobs.router,     prefix="/api/jobs",     tags=["jobs"])
app.include_router(events.router,   prefix="/api/events",   tags=["events"])
app.include_router(rules.router,    prefix="/api/rules",    tags=["rules"])
app.include_router(admin.router,    prefix="/api/admin",    tags=["admin"])


@app.websocket("/api/ws")
async def ws_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time event fan-out to dashboard and tooling clients."""
    await ws_broker.manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep connection alive; client messages ignored
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        ws_broker.manager.disconnect(websocket)


@app.get("/api/status", tags=["meta"])
def hub_status():
    return {"status": "ok", "service": "ESPAI Hub", "version": "0.1.0"}


@app.get("/api/meta", tags=["meta"])
def hub_meta():
    """
    Service discovery endpoint for IDE extensions, dashboards, and agents.
    Returns capabilities, schema versions, and endpoint prefixes so clients
    can discover what this hub supports without hardcoding assumptions.
    """
    import os
    try:
        import paho.mqtt.client  # noqa: F401
        mqtt_installed = True
    except ImportError:
        mqtt_installed = False

    return {
        "schema":         "ESPAI.hub.v1",
        "service":        "espai-hub",
        "version":        "0.1.0",
        "port":           PORT,
        "capabilities": [
            "devices", "pairing", "discovery", "scan",
            "projects", "project-theme-overrides",
            "recipes", "recipe-validation", "recipe-export", "recipe-compat", "recipe-overlays",
            "workers", "worker-test", "worker-compat", "worker-permissions",
            "cards",
            "ota", "ota-catalog", "ota-push", "ota-known-good", "ota-rollback",
            "jobs", "job-queue",
            "events", "events-sse", "events-ws",
            "rules", "rules-engine", "rules-theme-change",
            "design", "design-tokens", "design-themes",
            "mqtt" if (mqtt_installed and os.environ.get("ESPAI_MQTT_HOST")) else None,
            "admin-backup", "admin-restore",
        ],
        "endpoints": {
            "status":     "/api/status",
            "meta":       "/api/meta",
            "devices":    "/api/devices/",
            "projects":   "/api/projects/",
            "recipes":    "/api/recipes/",
            "workers":    "/api/workers/",
            "cards":      "/api/cards/",
            "ota":        "/api/ota/catalog",
            "jobs":       "/api/jobs/",
            "events":     "/api/events/",
            "events_sse": "/api/events/stream",
            "events_ws":  "/api/ws",
            "rules":      "/api/rules/",
            "design":     "/api/design/tokens",
            "backup":     "/api/admin/backup",
            "docs":       "/docs",
        },
        "schemas": {
            "device":   "ESPAI.device.v1",
            "project":  "ESPAI.project.v1",
            "recipe":   "ESPAI.recipe.v1",
            "worker":   "ESPAI.worker.v1",
            "firmware": "ESPAI.firmware.v1",
            "policy":   "ESPAI.policy.v1",
            "backup":   "ESPAI.backup.v1",
        },
    }


# ── Frontend static files ─────────────────────────────────────────────────────
# Mounted LAST so /api/* routes always take precedence.

_frontend = Path(__file__).parent.parent / "frontend"
if _frontend.exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")
