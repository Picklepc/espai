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


class DeviceCheckin(BaseModel):
    id: str
    name: str | None = None
    board: str | None = None
    fw_version: str | None = None
    capabilities: dict | None = None
    ip: str | None = None

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
            """INSERT INTO devices (id, ip, name, board, fw_version, paired, last_seen, capabilities)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 ip=excluded.ip,
                 name=excluded.name,
                 board=excluded.board,
                 fw_version=excluded.fw_version,
                 last_seen=excluded.last_seen,
                 capabilities=excluded.capabilities""",
            (
                data.id,
                data.ip,
                data.name,
                data.board,
                data.fw_version,
                paired,
                now,
                json.dumps(data.capabilities or {}),
            ),
        )
    return {"status": "ok", "paired": bool(paired)}


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
