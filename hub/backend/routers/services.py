"""
Local Network Service Registry

Discovers, persists, and manages all local web services — ESPAI projects, Tasmota,
Jellyfin, OpenWRT, Proxmox, Home Assistant, and anything else hosting HTTP/S on
the LAN. Services survive page reloads via SQLite persistence.

Discover endpoint probes port 80 + common alternate ports across the subnet.
Manual add accepts hostname/IP + port and auto-fetches metadata (title, favicon).
"""

import concurrent.futures
import re
import socket
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from ..db import get_conn

router = APIRouter()

# Ports probed during a full discover scan (port 80 is always probed)
_DISCOVER_PORTS = [80, 8080, 8096, 8123, 3000, 9000, 8888]

_TITLE_RE  = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_ICON_RE   = re.compile(r'<link[^>]+rel=["\'](?:shortcut )?icon["\'][^>]*href=["\']([^"\']+)["\']', re.IGNORECASE)
_SAFE_HOST = re.compile(r"^[a-zA-Z0-9._\-]{1,255}$")


# ── Service-type + category detection ────────────────────────────────────────

# (type_key, category, emoji, title_fragments, server_fragments)
_SIGNATURES = [
    ("tasmota",    "smart-home", "💡", ["tasmota"],                       ["tasmota"]),
    ("esphome",    "smart-home", "⚡", ["esphome"],                       ["esphome"]),
    ("homeassist", "smart-home", "🏠", ["home assistant", "homeassistant"], []),
    ("openwrt",    "network",    "🌐", ["openwrt", "luci"],               ["openwrt"]),
    ("pihole",     "network",    "🛡️", ["pi-hole", "pi hole", "pihole"],   ["pi-hole"]),
    ("proxmox",    "network",    "🖥️", ["proxmox"],                       ["proxmox"]),
    ("jellyfin",   "media",      "🎬", ["jellyfin"],                      ["jellyfin"]),
    ("plex",       "media",      "🟡", ["plex"],                          ["plex"]),
    ("emby",       "media",      "🟢", ["emby"],                          ["emby"]),
    ("kodi",       "media",      "🎵", ["kodi"],                          []),
    ("navidrome",  "media",      "🎵", ["navidrome"],                     []),
    ("grafana",    "tools",      "📊", ["grafana"],                       ["grafana"]),
    ("portainer",  "tools",      "🐳", ["portainer"],                     []),
    ("gitea",      "tools",      "🦎", ["gitea"],                         ["gitea"]),
    ("nextcloud",  "tools",      "☁️",  ["nextcloud"],                    ["nextcloud"]),
    ("synology",   "tools",      "💾", ["synology", "dsm"],              ["synology"]),
    ("espai",      "projects",   "📡", [],                                []),
]

_SVC_COLORS = {
    "tasmota":    "#e07828",
    "esphome":    "#00bcd4",
    "homeassist": "#18bcf2",
    "openwrt":    "#2ecc71",
    "pihole":     "#e74c3c",
    "proxmox":    "#e67e22",
    "jellyfin":   "#8e44ad",
    "plex":       "#e5a00d",
    "emby":       "#52b54b",
    "kodi":       "#17b2e8",
    "navidrome":  "#f47225",
    "grafana":    "#f46800",
    "portainer":  "#13bef9",
    "gitea":      "#609926",
    "nextcloud":  "#0082c9",
    "synology":   "#b5b5b5",
    "espai":      "#1aafc4",
    "unknown":    "#546e7a",
}

_CATEGORY_ORDER = ["projects", "smart-home", "media", "network", "tools", "other"]
_CATEGORY_LABELS = {
    "projects":   "Projects",
    "smart-home": "Smart Home",
    "media":      "Media",
    "network":    "Network",
    "tools":      "Tools",
    "other":      "Other",
}


def _detect(title: str, server: str, is_espai: bool) -> tuple[str, str, str, str]:
    """Returns (type_key, category, emoji, hex_color)."""
    if is_espai:
        return "espai", "projects", "📡", _SVC_COLORS["espai"]
    tl = (title or "").lower()
    sl = (server or "").lower()
    for type_key, category, emoji, tfrags, sfrags in _SIGNATURES:
        if any(f in tl for f in tfrags) or any(f in sl for f in sfrags):
            return type_key, category, emoji, _SVC_COLORS.get(type_key, _SVC_COLORS["unknown"])
    return "unknown", "other", "🌐", _SVC_COLORS["unknown"]


# ── HTTP probing helpers ──────────────────────────────────────────────────────

def _resolve_host(host: str) -> str:
    """Resolve a hostname to an IP (best-effort; returns host unchanged on failure)."""
    try:
        return socket.gethostbyname(host)
    except Exception:
        return host


def _probe_url(url: str, timeout: float = 1.5) -> dict | None:
    """
    Probe a single URL. Returns dict with title/server/favicon_url/is_espai,
    or None if unreachable.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ESPAI-Hub/0.1 LocalNetworkScanner"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct   = resp.headers.get("Content-Type", "")
            srv  = resp.headers.get("Server", "")
            body = resp.read(4096).decode("utf-8", errors="replace")

            # ESPAI check
            if "/api/manifest" in url:
                import json as _json
                try:
                    data = _json.loads(body)
                    if isinstance(data, dict) and data.get("schema") == "ESPAI.device.v1":
                        return {"is_espai": True, "title": data.get("name", ""), "server": srv, "favicon_url": None}
                except Exception:
                    pass
                return None

            title_m = _TITLE_RE.search(body)
            title   = title_m.group(1).strip()[:128] if title_m else ""
            icon_m  = _ICON_RE.search(body)
            # Build absolute favicon URL
            base = url.rstrip("/")
            if icon_m:
                icon_path = icon_m.group(1)
                favicon = icon_path if icon_path.startswith("http") else f"{base}{icon_path if icon_path.startswith('/') else '/' + icon_path}"
            else:
                favicon = f"{base}/favicon.ico"

            return {"is_espai": False, "title": title, "server": srv, "favicon_url": favicon}
    except Exception:
        return None


def _probe_host_port(host: str, port: int, protocol: str = "http") -> dict | None:
    """
    Full probe for one (host, port): try ESPAI manifest first, then root URL.
    Returns metadata dict or None.
    """
    base = f"{protocol}://{host}:{port}"
    # ESPAI check (short timeout — if it's not ESPAI this will fail fast)
    espai = _probe_url(f"{base}/api/manifest", timeout=0.8)
    if espai and espai.get("is_espai"):
        return espai

    # Generic HTTP page
    result = _probe_url(f"{base}/", timeout=1.5)
    return result


# ── Pydantic models ───────────────────────────────────────────────────────────

class ServiceAdd(BaseModel):
    host:     str
    port:     int  = 80
    protocol: str  = "http"
    label:    Optional[str] = None
    category: Optional[str] = None   # override auto-detected category

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not _SAFE_HOST.match(v):
            raise ValueError("Invalid host — use an IP address or simple hostname")
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("Port must be 1-65535")
        return v

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        if v not in ("http", "https"):
            raise ValueError("protocol must be http or https")
        return v


class ServicePatch(BaseModel):
    label:      Optional[str]  = None
    category:   Optional[str]  = None
    pinned:     Optional[bool] = None
    hidden:     Optional[bool] = None
    project_id: Optional[str]  = None   # link to an ESPai project; set to "" to unlink


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["pinned"]    = bool(d.get("pinned"))
    d["hidden"]    = bool(d.get("hidden"))
    d["is_espai"]  = bool(d.get("is_espai"))
    d["reachable"] = bool(d.get("reachable", 1))
    d["color"]     = _SVC_COLORS.get(d.get("service_type", "unknown"), _SVC_COLORS["unknown"])
    d["category_label"] = _CATEGORY_LABELS.get(d.get("category", "other"), "Other")
    return d


# ── Service health polling ────────────────────────────────────────────────────

_HEALTH_INTERVAL_S = 60
_health_thread: threading.Thread | None = None


def _ping_service(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return True if the host:port is reachable (TCP connect)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _health_poll_loop() -> None:
    """Background thread — pings all pinned services every 60 s."""
    import time
    while True:
        time.sleep(_HEALTH_INTERVAL_S)
        try:
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT id, host, port FROM local_services WHERE pinned=1 AND hidden=0"
                ).fetchall()
            for row in rows:
                reachable = _ping_service(row["host"], row["port"])
                now = datetime.now(timezone.utc).isoformat()
                with get_conn() as conn:
                    if reachable:
                        conn.execute(
                            "UPDATE local_services SET reachable=1, last_seen=? WHERE id=?",
                            (now, row["id"]),
                        )
                    else:
                        conn.execute(
                            "UPDATE local_services SET reachable=0 WHERE id=?",
                            (row["id"],),
                        )
        except Exception:
            pass


def start_health_poller() -> None:
    """Called from hub lifespan — starts the background health polling thread once."""
    global _health_thread
    if _health_thread and _health_thread.is_alive():
        return
    _health_thread = threading.Thread(
        target=_health_poll_loop, daemon=True, name="svc-health-poller"
    )
    _health_thread.start()


def _upsert_service(conn, host: str, port: int, protocol: str, meta: dict, project_id: str | None = None) -> None:
    """Insert or update a service row. Preserves user-set label, pinned, hidden."""
    now = _now()
    is_espai = int(meta.get("is_espai", False))
    title    = (meta.get("title") or "")[:128]
    server   = (meta.get("server") or "")[:128]
    favicon  = meta.get("favicon_url") or ""
    svc_type, category, _emoji, _color = _detect(title, server, bool(is_espai))

    conn.execute("""
        INSERT INTO local_services
            (host, port, protocol, title, server, favicon_url, service_type, category,
             is_espai, project_id, pinned, hidden, discovered_at, last_seen)
        VALUES (?,?,?,?,?,?,?,?,?,?,0,0,?,?)
        ON CONFLICT(host, port) DO UPDATE SET
            title        = excluded.title,
            server       = excluded.server,
            favicon_url  = excluded.favicon_url,
            service_type = excluded.service_type,
            category     = CASE WHEN local_services.category != 'other' AND excluded.category = 'other'
                                 THEN local_services.category ELSE excluded.category END,
            is_espai     = excluded.is_espai,
            project_id   = COALESCE(excluded.project_id, local_services.project_id),
            last_seen    = excluded.last_seen
    """, (host, port, protocol, title, server, favicon, svc_type, category,
          is_espai, project_id, now, now))


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/")
def list_services():
    """Return all non-hidden services, grouped by category, pinned items first."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM local_services
            WHERE hidden = 0
            ORDER BY pinned DESC, category ASC, COALESCE(label, title, host) ASC
        """).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/categories")
def list_categories():
    """Return the ordered list of categories with their display labels."""
    return [{"key": k, "label": _CATEGORY_LABELS[k]} for k in _CATEGORY_ORDER]


@router.post("/discover")
def discover_services(subnet: str | None = None):
    """
    Scan the local subnet for HTTP services on port 80 and common alternate ports.
    Results are upserted into local_services (user labels/pinned state preserved).

    This is a blocking scan — it takes 10-20 s for a full subnet.
    The frontend shows a spinner and should not call this on every page load.
    """
    if subnet is None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
            except Exception:
                local_ip = "127.0.0.1"
        subnet = ".".join(local_ip.split(".")[:3])

    if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$", subnet):
        raise HTTPException(400, "Invalid subnet format")

    # Build (ip, port) probe list
    ips = [f"{subnet}.{i}" for i in range(1, 255)]
    tasks: list[tuple[str, int]] = []
    for ip in ips:
        tasks.append((ip, 80))        # always probe port 80
        for port in _DISCOVER_PORTS:
            if port != 80:
                tasks.append((ip, port))

    found_results: list[tuple[str, int, dict]] = []

    def _probe_task(args: tuple[str, int]) -> tuple[str, int, dict] | None:
        host, port = args
        meta = _probe_host_port(host, port)
        if meta:
            return (host, port, meta)
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=128) as pool:
        for result in pool.map(_probe_task, tasks):
            if result:
                found_results.append(result)

    # Resolve ESPAI project associations from devices table
    espai_project_map: dict[str, str] = {}  # ip → project_id
    with get_conn() as conn:
        dev_rows = conn.execute("SELECT ip, id FROM devices").fetchall()
        ip_to_dev = {r["ip"]: r["id"] for r in dev_rows if r["ip"]}
        proj_rows = conn.execute("SELECT id, devices FROM projects").fetchall()
        import json as _json
        for pr in proj_rows:
            try:
                dev_ids = _json.loads(pr["devices"] or "[]")
                for did in dev_ids:
                    # Find the IP for this device ID
                    for dip, diid in ip_to_dev.items():
                        if diid == did:
                            espai_project_map[dip] = pr["id"]
            except Exception:
                pass

    # Upsert all results in one transaction
    with get_conn() as conn:
        for host, port, meta in found_results:
            proj_id = espai_project_map.get(host) if meta.get("is_espai") else None
            _upsert_service(conn, host, port, "http", meta, proj_id)

    return {"found": len(found_results), "subnet": subnet}


@router.post("/")
def add_service(data: ServiceAdd):
    """
    Manually add a service by hostname/IP + port.
    The hub probes the service immediately to fetch title, server header, and
    favicon URL. The service is saved even if the probe fails (marked unknown).
    """
    now  = _now()
    meta = _probe_host_port(data.host, data.port, data.protocol) or {}

    svc_type, category, _emoji, _color = _detect(
        meta.get("title", ""), meta.get("server", ""), bool(meta.get("is_espai"))
    )
    # User-supplied category overrides detection
    if data.category and data.category in _CATEGORY_LABELS:
        category = data.category

    favicon = meta.get("favicon_url") or f"{data.protocol}://{data.host}:{data.port}/favicon.ico"

    with get_conn() as conn:
        conn.execute("""
            INSERT INTO local_services
                (host, port, protocol, label, title, server, favicon_url, service_type, category,
                 is_espai, pinned, hidden, discovered_at, last_seen)
            VALUES (?,?,?,?,?,?,?,?,?,0,0,0,?,?)
            ON CONFLICT(host, port) DO UPDATE SET
                label        = COALESCE(excluded.label, local_services.label),
                title        = excluded.title,
                server       = excluded.server,
                favicon_url  = excluded.favicon_url,
                service_type = excluded.service_type,
                category     = excluded.category,
                last_seen    = excluded.last_seen
        """, (
            data.host, data.port, data.protocol,
            data.label or None,
            (meta.get("title") or "")[:128],
            (meta.get("server") or "")[:128],
            favicon, svc_type, category, now, now,
        ))
        row = conn.execute(
            "SELECT * FROM local_services WHERE host=? AND port=?", (data.host, data.port)
        ).fetchone()

    return _row_to_dict(row)


@router.patch("/{svc_id}")
def update_service(svc_id: int, data: ServicePatch):
    """Update user-controlled fields: label, category, pinned, hidden, project_id."""
    allowed = {"label", "category", "pinned", "hidden", "project_id"}
    raw = data.model_dump()
    # Allow explicit empty-string project_id to unlink
    updates = {k: v for k, v in raw.items()
               if k in allowed and (v is not None or k == "project_id") and raw.get(k) is not None}
    # Normalise: empty string → NULL for project_id
    if "project_id" in updates and updates["project_id"] == "":
        updates["project_id"] = None
    if not updates:
        raise HTTPException(400, "Nothing to update")
    if "category" in updates and updates["category"] not in _CATEGORY_LABELS:
        raise HTTPException(400, f"category must be one of: {', '.join(_CATEGORY_LABELS)}")
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with get_conn() as conn:
        result = conn.execute(
            f"UPDATE local_services SET {set_clause} WHERE id=?",
            (*updates.values(), svc_id),
        )
        if result.rowcount == 0:
            raise HTTPException(404, f"Service {svc_id} not found")
    return {"status": "ok", "id": svc_id}


@router.delete("/{svc_id}")
def delete_service(svc_id: int):
    """Permanently remove a service entry."""
    with get_conn() as conn:
        conn.execute("DELETE FROM local_services WHERE id=?", (svc_id,))
    return {"status": "deleted", "id": svc_id}
