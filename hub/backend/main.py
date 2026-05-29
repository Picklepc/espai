"""
ESPAI Hub — FastAPI entry point.

Run from repo root:
    uvicorn hub.backend.main:app --host 0.0.0.0 --port 7888 --reload

Or via the CLI:
    python ESPAI.py serve
"""
import asyncio
import json
import logging
import os
import re
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import DEBUG, PORT
from .config import PROJECTS_DIR
from .db import get_conn, init_db
from . import __version__ as HUB_VERSION
from .discovery.mdns import mdns_manager
from . import mqtt_publisher, theme_scheduler, ws_broker
from .routers import admin, agent_bench, cards, data, design, devices, events, jobs, ota, packages, projects, recipes, rules, services, terminal, workers
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


_startup_time = datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    # Reset tasks/runs left in "running" state by a previous unclean shutdown
    with get_conn() as conn:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE agent_tasks SET status='draft', updated=? WHERE status='running'", (now,))
        conn.execute("UPDATE agent_runs  SET status='failed', finished=? WHERE status='running'", (now,))
    start_runner()
    mdns_manager.start(hub_port=PORT, on_node_found=_on_mdns_node_found)
    mdns_manager.register_all_projects()   # advertise {slug}.local for each project
    mqtt_publisher.init()
    theme_scheduler.start()
    ws_broker.set_loop(asyncio.get_event_loop())
    yield
    # Shutdown
    mdns_manager.stop()
    mqtt_publisher.shutdown()


app = FastAPI(
    title="ESPAI Hub",
    version=HUB_VERSION,
    description="Local-first ESP32 fleet and edge-processing platform",
    lifespan=lifespan,
    # Only expose docs in debug mode — there is no authentication on these endpoints
    docs_url="/docs" if DEBUG else None,
    redoc_url=None,
)

# CORS: ESPAI is local-first — allow all LAN origins.
# No cookie auth, no credentials. API keys / auth are NOT in scope for v0.1
# (hub is assumed to run on a private LAN). Revisit before any cloud exposure.
_cors_origins = os.environ.get("ESPAI_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Firmware-SHA256", "X-ESPAI-Operator"],
)

# ── API routers ───────────────────────────────────────────────────────────────

app.include_router(devices.router,  prefix="/api/devices",  tags=["devices"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(recipes.router,  prefix="/api/recipes",  tags=["recipes"])
app.include_router(workers.router,  prefix="/api/workers",  tags=["workers"])
app.include_router(packages.router, prefix="/api/packages", tags=["packages"])
app.include_router(cards.router,    prefix="/api/cards",    tags=["cards"])
app.include_router(design.router,   prefix="/api/design",   tags=["design"])
app.include_router(ota.router,      prefix="/api/ota",      tags=["ota"])
app.include_router(jobs.router,     prefix="/api/jobs",     tags=["jobs"])
app.include_router(events.router,   prefix="/api/events",   tags=["events"])
app.include_router(rules.router,    prefix="/api/rules",    tags=["rules"])
app.include_router(admin.router,       prefix="/api/admin",        tags=["admin"])
app.include_router(agent_bench.router, prefix="/api/agent-bench",  tags=["agent-bench"])
app.include_router(services.router,    prefix="/api/services",      tags=["services"])
app.include_router(terminal.router,    prefix="/api/terminal",     tags=["terminal"])
app.include_router(data.router,        prefix="/api/projects",     tags=["project-data"])


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
    with get_conn() as conn:
        device_count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    uptime = (datetime.now(timezone.utc) - _startup_time).total_seconds()
    return {
        "status":       "ok",
        "service":      "ESPAI Hub",
        "version":      HUB_VERSION,
        "uptime":       round(uptime, 1),
        "device_count": device_count,
    }


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


# ── Project web apps ─────────────────────────────────────────────────────────
# Serve each project's web/ directory at /app/{project_id}/
# Must be registered BEFORE the catch-all frontend StaticFiles mount.

_SAFE_PID = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def _resolve_project_web_dir(identifier: str) -> Path | None:
    """
    Find a project's web/ directory by project_id OR by slug (node_name).
    Slug = project name lowercased, spaces→dashes, non-word chars stripped.
    E.g. "Jingle Bells" → "jingle-bells"
    """
    import re as _re

    def _slug(name: str) -> str:
        return _re.sub(r"[^\w\s-]", "", name).strip().lower().replace(" ", "-")[:40]

    # Try direct project_id first
    direct = PROJECTS_DIR / identifier / "web"
    if direct.exists():
        return direct

    # Fall back to slug lookup across all projects
    with get_conn() as conn:
        rows = conn.execute("SELECT id, name FROM projects").fetchall()
    for row in rows:
        if _slug(row["name"]) == identifier:
            p = PROJECTS_DIR / row["id"] / "web"
            if p.exists():
                return p
    return None


@app.get("/app/{identifier}", include_in_schema=False)
@app.get("/app/{identifier}/{path:path}", include_in_schema=False)
async def serve_project_app(identifier: str, path: str = ""):
    web_dir = _resolve_project_web_dir(identifier)
    if web_dir is None:
        return Response(
            f"No web app found for '{identifier}'. "
            "Add a web/index.html to the project folder.",
            status_code=404,
        )
    target = (web_dir / path) if path else (web_dir / "index.html")
    if not target.is_file():
        target = web_dir / "index.html"   # SPA fallback
    if not target.is_file():
        return Response("No index.html in project web/", status_code=404)
    try:
        target.resolve().relative_to(web_dir.resolve())
    except ValueError:
        return Response("Access denied", status_code=403)
    return FileResponse(target)


def _device_offline_page(project_id: str) -> Response:
    """
    Serve a context-aware 'device unavailable' page.
    Distinguishes between 'actively unreachable' and 'sleeping/low-power'
    based on when the device last checked in with the hub.
    """
    from datetime import datetime, timezone, timedelta

    with get_conn() as conn:
        proj = conn.execute(
            "SELECT name, slug, devices FROM projects WHERE id=?", (project_id,)
        ).fetchone()
    name = proj["name"] if proj else project_id
    slug = proj["slug"] if proj else project_id

    # Look up last-seen for the linked device
    last_seen_str = None
    last_seen_ago = None
    sleeping = False
    if proj:
        dev_ids = json.loads(proj["devices"] or "[]")
        if dev_ids:
            with get_conn() as conn:
                dev = conn.execute(
                    "SELECT last_seen FROM devices WHERE id=?", (dev_ids[0],)
                ).fetchone()
            if dev and dev["last_seen"]:
                last_seen_str = dev["last_seen"]
                try:
                    ls = datetime.fromisoformat(last_seen_str)
                    ago = datetime.now(timezone.utc) - ls
                    if ago < timedelta(minutes=5):
                        last_seen_ago = "just now"
                    elif ago < timedelta(hours=1):
                        last_seen_ago = f"{int(ago.total_seconds() // 60)} min ago"
                    elif ago < timedelta(days=1):
                        last_seen_ago = f"{int(ago.total_seconds() // 3600)} hr ago"
                    else:
                        last_seen_ago = f"{ago.days} day(s) ago"
                    # >5 min but was recently active = likely sleeping/low-power
                    sleeping = ago > timedelta(minutes=5)
                except Exception:
                    pass

    icon  = "💤" if sleeping else "📡"
    badge_color = "#1a2a3a" if sleeping else "#3a1a1a"
    badge_border = "#2a4a6a" if sleeping else "#7a2a2a"
    badge_text_color = "#80c0f0" if sleeping else "#f08080"
    badge_label = "Device sleeping / low-power" if sleeping else "Device unreachable"
    last_seen_html = (
        f'<p style="color:#555;font-size:.8rem">Last seen: {last_seen_ago}</p>'
        if last_seen_ago else ""
    )
    guidance = (
        """<p>This device checks in periodically — it is likely sleeping to save power.
        The page will retry automatically. You can also try the device URL directly.</p>"""
        if sleeping else
        """<div class="steps">
          <div>1. Check that the ESP32 is powered on</div>
          <div>2. Confirm it is on the same WiFi network</div>
          <div>3. If WiFi failed it starts a <strong>ESPAI-xxxxxx</strong> fallback AP</div>
          <div>4. Try <a href="http://{slug}.local/" style="color:#f0a820">{slug}.local</a> directly</div>
        </div>""".format(slug=slug)
    )
    hub_app = f"/app/{slug}/" if (PROJECTS_DIR / project_id / "web" / "index.html").exists() else None
    hub_link = (
        f'<a href="{hub_app}" style="color:#f0a820;font-size:.9rem">← Hub-hosted app</a>'
        if hub_app else ""
    )
    auto_retry = '<meta http-equiv="refresh" content="30">' if sleeping else ""

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  {auto_retry}
  <title>{name} — {badge_label}</title>
  <style>
    body{{font-family:system-ui,sans-serif;background:#0d0d0d;color:#e8e8e8;
         min-height:100vh;display:flex;flex-direction:column;align-items:center;
         justify-content:center;gap:16px;padding:24px;text-align:center}}
    h1{{font-size:1.6rem;font-weight:700;margin:0}}
    .badge{{display:inline-block;padding:4px 14px;border-radius:20px;font-size:.85rem;
            background:{badge_color};color:{badge_text_color};border:1px solid {badge_border}}}
    p,.steps{{color:#888;max-width:440px;line-height:1.7;font-size:.9rem}}
    .steps{{text-align:left;color:#aaa;font-size:.875rem;line-height:2.2}}
    button{{padding:10px 24px;background:#222;color:#e8e8e8;border:1px solid #444;
            border-radius:7px;font-size:.9rem;cursor:pointer;margin-top:4px}}
    button:hover{{background:#333}}
  </style>
</head><body>
  <div style="font-size:2.8rem">{icon}</div>
  <h1>{name}</h1>
  <span class="badge">{badge_label}</span>
  {last_seen_html}
  {guidance}
  {hub_link}
  <button onclick="location.reload()">↻ Retry now</button>
</body></html>"""
    return Response(html, status_code=503, media_type="text/html")


@app.api_route(
    "/proxy/{project_id}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    include_in_schema=False,
)
async def proxy_device(project_id: str, path: str, request: Request):
    """
    Proxy requests to the device linked to a project.
    The web app uses /proxy/{project_id}/api/... so it never needs to know
    the device IP — the hub handles discovery and forwarding.
    """
    if not _SAFE_PID.match(project_id):
        return Response("Invalid project ID", status_code=400)

    # Resolve device IP from project's linked devices
    device_ip = None
    with get_conn() as conn:
        proj_row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if proj_row:
            dev_ids = json.loads(proj_row["devices"] or "[]")
            for did in dev_ids:
                dev = conn.execute("SELECT ip FROM devices WHERE id=?", (did,)).fetchone()
                if dev and dev["ip"]:
                    device_ip = dev["ip"]
                    break

    if not device_ip:
        if "text/html" in request.headers.get("accept", ""):
            return _device_offline_page(project_id)
        return Response(
            '{"error":"No online device linked to this project"}',
            status_code=503,
            media_type="application/json",
        )

    # Forward the request
    qs = str(request.url.query)
    target_url = f"http://{device_ip}/{path}" + (f"?{qs}" if qs else "")
    try:
        body = await request.body()
        req = urllib.request.Request(
            target_url,
            data=body or None,
            method=request.method,
        )
        for h, v in request.headers.items():
            if h.lower() not in ("host", "content-length"):
                req.add_header(h, v)
        with urllib.request.urlopen(req, timeout=8) as resp:
            content = resp.read()
            ct = resp.headers.get("Content-Type", "application/octet-stream")
            return Response(content, status_code=resp.status, media_type=ct)
    except urllib.error.HTTPError as e:
        if "text/html" in request.headers.get("accept", "") and e.code >= 500:
            return _device_offline_page(project_id)
        return Response(e.read(), status_code=e.code)
    except Exception as exc:
        if "text/html" in request.headers.get("accept", ""):
            return _device_offline_page(project_id)
        return Response(
            json.dumps({"error": str(exc)}),
            status_code=502,
            media_type="application/json",
        )


# ── Frontend static files ─────────────────────────────────────────────────────
# Mounted LAST so /api/* and /app/* routes always take precedence.

_frontend = Path(__file__).parent.parent / "frontend"
if _frontend.exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")
