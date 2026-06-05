import concurrent.futures
import json
import re
import secrets
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from ..db import get_conn

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Input models ──────────────────────────────────────────────────────────────

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


# ── NVS config blocklist (M29) ────────────────────────────────────────────────
# These keys are platform-managed and must never be accessible via the config API.
_CONFIG_BLOCKLIST = frozenset(["sta_ssid", "sta_pass", "sleep_s", "awake_s", "awake_w"])

def _is_blocked_config_key(key: str) -> bool:
    return key in _CONFIG_BLOCKLIST or key.lower().startswith("espai_")


class DeviceCheckin(BaseModel):
    id: str
    name: str | None = None
    board: str | None = None
    fw_version: str | None = None
    capabilities: dict | None = None
    ip: str | None = None
    sleep_interval_s: int | None = None   # node reports its configured sleep interval; 0 = awake-always
    awake_window_s:   int | None = None   # node reports how long it stays awake before sleeping
    config: list[dict] | None = None      # firmware's registered config schema from /api/manifest

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not _SAFE_ID.match(v):
            raise ValueError("Device ID must be alphanumeric/dash/underscore, max 64 chars")
        return v


class ManualDevice(BaseModel):
    ip: str
    name: str | None = None

    @field_validator("ip")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        # Loose check: allow IPv4, IPv6, and hostnames but reject control chars
        if len(v) > 255 or any(c in v for c in ("\n", "\r", "\x00")):
            raise ValueError("Invalid IP/hostname")
        return v


class PairingConfirm(BaseModel):
    token: str
    device_id: str

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        if not re.match(r"^[0-9a-f]{1,64}$", v):
            raise ValueError("Invalid token format")
        return v


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    d = dict(row)
    for field in ("capabilities", "meta"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                pass
    return d


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/")
def list_devices():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM devices ORDER BY last_seen DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/{device_id}")
def get_device(device_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Device {device_id!r} not found")
    return _row_to_dict(row)


@router.get("/{device_id}/projects")
def device_projects(device_id: str):
    """List all projects this device is enrolled in, including its role in each."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT pn.project_id, pn.role, pn.label, pn.node_index,
                      p.name, p.slug, p.description
               FROM project_nodes pn
               JOIN projects p ON p.id = pn.project_id
               WHERE pn.device_id = ?
               ORDER BY p.name""",
            (device_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/checkin")
def checkin(data: DeviceCheckin):
    """Called by nodes on boot and periodically. Upserts device record."""
    now = _now()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT paired FROM devices WHERE id=?", (data.id,)
        ).fetchone()
        # Preserve paired state — nodes cannot un-pair themselves via checkin
        paired = int(existing["paired"]) if existing else 0
        conn.execute(
            """INSERT INTO devices
                 (id, ip, name, board, fw_version, paired, last_seen, capabilities,
                  sleep_interval_s, awake_window_s)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 ip=excluded.ip,
                 name=excluded.name,
                 board=excluded.board,
                 fw_version=excluded.fw_version,
                 last_seen=excluded.last_seen,
                 capabilities=excluded.capabilities,
                 sleep_interval_s=COALESCE(excluded.sleep_interval_s, devices.sleep_interval_s),
                 awake_window_s=COALESCE(excluded.awake_window_s, devices.awake_window_s)""",
            (
                data.id, data.ip, data.name, data.board, data.fw_version,
                paired, now, json.dumps(data.capabilities or {}),
                data.sleep_interval_s, data.awake_window_s,
            ),
        )
        row = conn.execute(
            "SELECT sleep_interval_s, awake_window_s FROM devices WHERE id=?", (data.id,)
        ).fetchone()
    # Upsert config schema from manifest and auto-push any matching secrets
    if data.config:
        _upsert_config_schema(data.id, data.config, now)

    return {
        "status": "ok",
        "paired": bool(paired),
        "sleep_interval_s": row["sleep_interval_s"] if row else None,
        "awake_window_s":   (row["awake_window_s"] or 5) if row else 5,
    }


@router.post("/manual")
def add_manual(data: ManualDevice):
    """Add a device by IP without waiting for mDNS or checkin."""
    device_id = f"manual-{secrets.token_hex(4)}"
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO devices (id, ip, name, paired, last_seen)
               VALUES (?,?,?,0,?)""",
            (device_id, data.ip, data.name, now),
        )
    return {"id": device_id, "ip": data.ip, "name": data.name}


@router.post("/pair/initiate/{device_id}")
def initiate_pairing(device_id: str):
    """Generate a short-lived one-time pairing token for this device."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=5)
    token = secrets.token_hex(8)
    with get_conn() as conn:
        # Invalidate any previous unused tokens for this device
        conn.execute(
            "UPDATE pairing_tokens SET used=1 WHERE device_id=? AND used=0",
            (device_id,),
        )
        conn.execute(
            """INSERT INTO pairing_tokens (token, device_id, created, expires, used)
               VALUES (?,?,?,?,0)""",
            (token, device_id, now.isoformat(), expires.isoformat()),
        )
    return {"token": token, "device_id": device_id, "expires": expires.isoformat()}


@router.post("/pair/confirm")
def confirm_pairing(data: PairingConfirm):
    """Confirm pairing using a valid, unexpired, unused token."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM pairing_tokens WHERE token=? AND device_id=? AND used=0",
            (data.token, data.device_id),
        ).fetchone()
        if not row:
            raise HTTPException(400, "Invalid or already-used pairing token")

        expires = datetime.fromisoformat(row["expires"])
        if datetime.now(timezone.utc) > expires:
            # Mark it used so it can't be retried
            conn.execute("UPDATE pairing_tokens SET used=1 WHERE token=?", (data.token,))
            raise HTTPException(400, "Pairing token expired")

        conn.execute("UPDATE pairing_tokens SET used=1 WHERE token=?", (data.token,))
        conn.execute("UPDATE devices SET paired=1 WHERE id=?", (data.device_id,))

    return {"status": "paired", "device_id": data.device_id}


class DevicePatch(BaseModel):
    sleep_interval_s: int | None = None   # 0 = awake-always; positive = deep-sleep interval in seconds
    awake_window_s:   int | None = None   # seconds node stays awake after boot before sleeping


@router.patch("/{device_id}")
def patch_device(device_id: str, data: DevicePatch):
    """Update hub-side per-device settings. Sent back to the node on next checkin."""
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with get_conn() as conn:
        result = conn.execute(
            f"UPDATE devices SET {set_clause} WHERE id=?",
            (*updates.values(), device_id),
        )
        if result.rowcount == 0:
            raise HTTPException(404, f"Device {device_id!r} not found")
    return {"status": "ok", "id": device_id, **updates}


@router.delete("/{device_id}")
def delete_device(device_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM devices WHERE id=?", (device_id,))
        conn.execute("DELETE FROM pairing_tokens WHERE device_id=?", (device_id,))
    return {"status": "deleted"}


@router.post("/scan")
def scan_lan(subnet: str | None = None):
    """Probe the local subnet for ESPAI nodes on port 80. Auto-detects subnet if not given."""
    if subnet is None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
            except Exception:
                local_ip = "127.0.0.1"
        subnet = ".".join(local_ip.split(".")[:3])

    if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$", subnet):
        raise HTTPException(400, "Invalid subnet format (expect x.x.x, e.g. 192.168.1)")

    def _probe(n: int) -> dict | None:
        ip = f"{subnet}.{n}"
        try:
            req = urllib.request.Request(
                f"http://{ip}/api/manifest",
                headers={"User-Agent": "ESPAI-Hub/0.1"},
            )
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                data = json.loads(resp.read(8192))
                if isinstance(data, dict) and data.get("schema") == "ESPAI.device.v1":
                    return {"ip": ip, "manifest": data}
        except Exception:
            pass
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        results = list(pool.map(_probe, range(1, 255)))

    found = [r for r in results if r is not None]
    now = _now()
    registered = []
    for node in found:
        m = node["manifest"]
        raw_id = m.get("id", "")
        if not _SAFE_ID.match(raw_id):
            raw_id = "scan-" + node["ip"].replace(".", "-")
        if not _SAFE_ID.match(raw_id):
            continue
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
                (raw_id, node["ip"], m.get("name"), m.get("board"), m.get("fw_version"), paired, now),
            )
        registered.append(raw_id)

    return {
        "subnet": subnet,
        "probed": 254,
        "found": len(found),
        "registered": registered,
        "devices": [{**r["manifest"], "ip": r["ip"]} for r in found],
    }


@router.post("/browse")
def browse_lan(subnet: str | None = None):
    """
    Scan the subnet for ANY HTTP device on port 80 — not just ESPAI nodes.
    Returns ESPAI devices (is_espai=True) and generic HTTP devices (Tasmota,
    ESPHome, routers, cameras, etc.). Non-ESPAI devices are never auto-registered.
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

    _title_re = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

    def _probe_all(n: int) -> dict | None:
        ip = f"{subnet}.{n}"
        # Try ESPAI manifest first
        try:
            req = urllib.request.Request(f"http://{ip}/api/manifest",
                                         headers={"User-Agent": "ESPAI-Hub/0.1"})
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                data = json.loads(resp.read(4096))
                if isinstance(data, dict) and data.get("schema") == "ESPAI.device.v1":
                    return {"ip": ip, "is_espai": True, "title": data.get("name", ip),
                            "manifest": data}
        except Exception:
            pass
        # Fall back to any HTTP response on port 80
        try:
            req = urllib.request.Request(f"http://{ip}/",
                                         headers={"User-Agent": "ESPAI-Hub/0.1"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                ct   = resp.headers.get("Content-Type", "")
                body = resp.read(2048).decode("utf-8", errors="replace")
                m = _title_re.search(body)
                title = m.group(1).strip()[:64] if m else ip
                server = resp.headers.get("Server", "")
                return {"ip": ip, "is_espai": False, "title": title,
                        "content_type": ct, "server": server}
        except Exception:
            pass
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        results = list(pool.map(_probe_all, range(1, 255)))

    return {
        "subnet": subnet,
        "found": [r for r in results if r is not None],
    }


# ── Device NVS config (M29) ───────────────────────────────────────────────────

def _upsert_config_schema(device_id: str, config: list[dict], now: str) -> None:
    """Upsert config schema from checkin manifest; auto-push matching secrets."""
    from ..config import ROOT
    with get_conn() as conn:
        for entry in config:
            key = entry.get("key", "")
            if not key or _is_blocked_config_key(key):
                continue
            conn.execute(
                """INSERT INTO device_config_schema
                   (device_id, key, type, default_val, description, secret)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(device_id, key) DO UPDATE SET
                     type=excluded.type, default_val=excluded.default_val,
                     description=excluded.description, secret=excluded.secret""",
                (device_id, key,
                 entry.get("type", "string"),
                 entry.get("default", ""),
                 entry.get("description", ""),
                 1 if entry.get("secret") else 0),
            )

    # Auto-push secrets from secrets/{device_id}/
    secrets_dir = ROOT / "secrets" / device_id
    if not secrets_dir.exists():
        return
    with get_conn() as conn:
        secret_keys = [
            r["key"] for r in conn.execute(
                "SELECT key FROM device_config_schema WHERE device_id=? AND secret=1",
                (device_id,)
            ).fetchall()
        ]
    for key in secret_keys:
        secret_file = secrets_dir / key
        if secret_file.is_file():
            try:
                value = secret_file.read_text(encoding="utf-8").strip()
                if not value:
                    continue
                cmd_id = secrets.token_hex(8)
                with get_conn() as conn:
                    conn.execute(
                        "INSERT INTO device_commands"
                        " (id, device_id, command_type, payload, status, created, ttl_seconds)"
                        " VALUES (?,?,?,?,?,?,?)",
                        (cmd_id, device_id, "set_config",
                         json.dumps({"key": key, "value": value}),
                         "pending", now, 300),
                    )
                    # Record that secret was pushed (no value stored)
                    conn.execute(
                        """INSERT INTO device_config
                           (device_id, key, value, secret_set_at, updated)
                           VALUES (?,NULL,?,?)
                           ON CONFLICT(device_id, key) DO UPDATE SET
                             secret_set_at=excluded.secret_set_at,
                             updated=excluded.updated""",
                        (device_id, key, now, now),
                    )
            except Exception:
                pass


@router.get("/{device_id}/config/schema")
def get_device_config_schema(device_id: str):
    """Return config keys declared by this device's firmware."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM device_config_schema WHERE device_id=? ORDER BY key",
            (device_id,)
        ).fetchall()
    return {"device_id": device_id, "schema": [dict(r) for r in rows]}


@router.get("/{device_id}/config")
def get_device_config(device_id: str):
    """
    Return current operational config values.
    Proxies to the device's GET /api/config when reachable; falls back to
    the cached DB mirror. Secret key values are never returned.
    """
    with get_conn() as conn:
        dev = conn.execute(
            "SELECT ip FROM devices WHERE id=?", (device_id,)
        ).fetchone()
    if not dev:
        raise HTTPException(404, f"Device {device_id!r} not found")

    offline = True
    values: dict = {}

    if dev["ip"]:
        try:
            req = urllib.request.Request(
                f"http://{dev['ip']}/api/config", headers={}
            )
            with urllib.request.urlopen(req, timeout=3) as r:
                values = json.loads(r.read())
                offline = False
                # Cache operational values in DB
                now = _now()
                with get_conn() as conn:
                    for k, v in values.items():
                        if not _is_blocked_config_key(k):
                            conn.execute(
                                """INSERT INTO device_config
                                   (device_id, key, value, updated)
                                   VALUES (?,?,?,?)
                                   ON CONFLICT(device_id, key) DO UPDATE SET
                                     value=excluded.value, updated=excluded.updated""",
                                (device_id, k, str(v), now),
                            )
        except Exception:
            pass

    if offline:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT key, value, secret_set_at FROM device_config WHERE device_id=?",
                (device_id,)
            ).fetchall()
        # Return operational cached values; secrets show set status only
        for r in rows:
            if r["value"] is not None:
                values[r["key"]] = r["value"]

    return {"device_id": device_id, "values": values, "offline": offline}


@router.put("/{device_id}/config")
def set_device_config_key(device_id: str, body: dict):
    """Write a single config key via the command channel."""
    key   = body.get("key", "").strip()
    value = str(body.get("value", ""))
    if not key:
        raise HTTPException(400, "key required")
    if _is_blocked_config_key(key):
        raise HTTPException(403, f"Key {key!r} is platform-managed — use provision firmware for WiFi credentials")

    with get_conn() as conn:
        if not conn.execute("SELECT id FROM devices WHERE id=?", (device_id,)).fetchone():
            raise HTTPException(404, f"Device {device_id!r} not found")
        schema_row = conn.execute(
            "SELECT secret FROM device_config_schema WHERE device_id=? AND key=?",
            (device_id, key)
        ).fetchone()
    is_secret = bool(schema_row and schema_row["secret"])

    now    = _now()
    cmd_id = secrets.token_hex(8)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO device_commands"
            " (id, device_id, command_type, payload, status, created, ttl_seconds)"
            " VALUES (?,?,?,?,?,?,?)",
            (cmd_id, device_id, "set_config",
             json.dumps({"key": key, "value": value}), "pending", now, 300),
        )
        if is_secret:
            conn.execute(
                """INSERT INTO device_config
                   (device_id, key, value, secret_set_at, updated)
                   VALUES (?,NULL,?,?)
                   ON CONFLICT(device_id, key) DO UPDATE SET
                     secret_set_at=excluded.secret_set_at, updated=excluded.updated""",
                (device_id, key, now, now),
            )
        else:
            conn.execute(
                """INSERT INTO device_config (device_id, key, value, updated)
                   VALUES (?,?,?,?)
                   ON CONFLICT(device_id, key) DO UPDATE SET
                     value=excluded.value, updated=excluded.updated""",
                (device_id, key, value, now),
            )
    return {"queued": True, "cmd_id": cmd_id, "key": key, "secret": is_secret}


@router.put("/{device_id}/config/bulk")
def bulk_set_device_config(device_id: str, body: dict):
    """Write multiple config keys at once via the command channel."""
    if not isinstance(body, dict) or not body:
        raise HTTPException(400, "Body must be a non-empty JSON object {key: value}")
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM devices WHERE id=?", (device_id,)).fetchone():
            raise HTTPException(404, f"Device {device_id!r} not found")

    now     = _now()
    queued  = []
    blocked = []
    for key, value in body.items():
        if _is_blocked_config_key(key):
            blocked.append(key)
            continue
        with get_conn() as conn:
            schema_row = conn.execute(
                "SELECT secret FROM device_config_schema WHERE device_id=? AND key=?",
                (device_id, key)
            ).fetchone()
        is_secret = bool(schema_row and schema_row["secret"])
        cmd_id = secrets.token_hex(8)
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO device_commands"
                " (id, device_id, command_type, payload, status, created, ttl_seconds)"
                " VALUES (?,?,?,?,?,?,?)",
                (cmd_id, device_id, "set_config",
                 json.dumps({"key": key, "value": str(value)}), "pending", now, 300),
            )
            if is_secret:
                conn.execute(
                    """INSERT INTO device_config
                       (device_id, key, value, secret_set_at, updated)
                       VALUES (?,NULL,?,?)
                       ON CONFLICT(device_id, key) DO UPDATE SET
                         secret_set_at=excluded.secret_set_at, updated=excluded.updated""",
                    (device_id, key, now, now),
                )
            else:
                conn.execute(
                    """INSERT INTO device_config (device_id, key, value, updated)
                       VALUES (?,?,?,?)
                       ON CONFLICT(device_id, key) DO UPDATE SET
                         value=excluded.value, updated=excluded.updated""",
                    (device_id, key, str(value), now),
                )
        queued.append(key)

    return {"queued": queued, "blocked": blocked}
