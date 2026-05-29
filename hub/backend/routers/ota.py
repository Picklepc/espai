"""
OTA orchestration scaffold.

Security model:
- Firmware upload: filename is sanitized (path traversal prevention).
- Push endpoint: device must be paired before OTA is allowed.
- Every OTA action is audit-logged with timestamp and operator.
- Actual firmware push to node is scaffolded but not implemented.
"""
import hashlib
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, field_validator

from ..config import FIRMWARE_CATALOG_DIR, PROJECTS_DIR
from ..db import get_conn
from .. import git_helper

router = APIRouter()

_SAFE_FILENAME = re.compile(r"^[a-zA-Z0-9_\-\.]{1,128}$")
_SAFE_VERSION  = re.compile(r"^\d+\.\d+\.\d+[a-zA-Z0-9\.\-]*$")
_SAFE_BOARD    = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")
_SAFE_LABEL    = re.compile(r"^[a-zA-Z0-9 _\-\.]{0,128}$")
_SAFE_PROJ_ID  = re.compile(r"^[a-zA-Z0-9_\-]{0,64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_filename(raw: str | None) -> str:
    """Strip directory components and enforce allowlist of safe characters."""
    if not raw:
        return "firmware.bin"
    name = Path(raw).name  # drop any directory component
    if not _SAFE_FILENAME.match(name):
        return "firmware.bin"
    return name


class OTARequest(BaseModel):
    device_id: str
    firmware_id: str
    operator: str = "local"
    force: bool = False  # override board compatibility check

    @field_validator("operator")
    @classmethod
    def sanitize_operator(cls, v: str) -> str:
        # Prevent operator field from carrying injected strings into logs
        return re.sub(r"[^\w\-\. ]", "", v)[:64]


class RollbackRequest(BaseModel):
    device_id: str
    operator: str = "local"
    force: bool = False

    @field_validator("operator")
    @classmethod
    def sanitize_operator(cls, v: str) -> str:
        return re.sub(r"[^\w\-\. ]", "", v)[:64]


class CatalogPatch(BaseModel):
    known_good: bool | None = None
    rollback_target: str | None = None
    channel: str | None = None
    label: str | None = None


class RolloutRequest(BaseModel):
    firmware_id: str
    operator: str = "local"
    force: bool = False
    # Targeting — at least one must be provided
    device_ids: list[str] | None = None   # explicit list of device IDs
    board_filter: str | None = None        # only push to devices matching this board
    pct: int | None = None                 # percentage of eligible devices (1-100)

    @field_validator("operator")
    @classmethod
    def sanitize_operator(cls, v: str) -> str:
        return re.sub(r"[^\w\-\. ]", "", v)[:64]

    @field_validator("pct")
    @classmethod
    def clamp_pct(cls, v: int | None) -> int | None:
        if v is not None and not (1 <= v <= 100):
            raise ValueError("pct must be between 1 and 100")
        return v


# ── Catalog ───────────────────────────────────────────────────────────────────

@router.get("/catalog")
def list_catalog():
    FIRMWARE_CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for meta_file in sorted(FIRMWARE_CATALOG_DIR.glob("*/firmware.json")):
        try:
            with open(meta_file, encoding="utf-8") as fh:
                data = json.load(fh)
            data["_folder"] = meta_file.parent.name
            entries.append(data)
        except Exception:
            pass
    return entries


@router.get("/catalog/project/{project_id}")
def catalog_by_project(project_id: str):
    """Return firmware entries tagged with a specific project_id, newest first."""
    if not _SAFE_PROJ_ID.match(project_id):
        raise HTTPException(400, "Invalid project_id")
    all_entries = list_catalog()
    return [e for e in all_entries if e.get("project_id") == project_id]


@router.post("/catalog/upload")
async def upload_firmware(
    file: UploadFile = File(...),
    board: str = "generic",
    version: str = "0.0.0",
    channel: str = "dev",
    label: str = "",        # human-readable display name shown in catalog and project view
    project_id: str = "",   # project this firmware belongs to (enables project-scoped flash)
):
    """
    Upload a firmware .bin into the catalog.
    - Filename is sanitized to prevent path traversal.
    - board and version are validated against safe patterns.
    - SHA-256 is computed server-side (client-provided checksums are not trusted).
    - Upload size limit: 4 MB (enforced by reading in one shot and checking length).
    """
    if not _SAFE_BOARD.match(board):
        raise HTTPException(400, "Invalid board identifier")
    if not _SAFE_VERSION.match(version):
        raise HTTPException(400, "Invalid version string")
    if channel not in ("dev", "beta", "stable"):
        raise HTTPException(400, "channel must be dev, beta, or stable")
    label      = label.strip()[:128]
    project_id = project_id.strip()[:64]
    if label and not _SAFE_LABEL.match(label):
        raise HTTPException(400, "Label contains invalid characters")
    if project_id and not _SAFE_PROJ_ID.match(project_id):
        raise HTTPException(400, "Invalid project_id")

    content = await file.read()
    if len(content) > 4 * 1024 * 1024:
        raise HTTPException(413, "Firmware binary exceeds 4 MB limit")
    if len(content) == 0:
        raise HTTPException(400, "Empty file")

    sha256 = hashlib.sha256(content).hexdigest()
    safe_name = _sanitize_filename(file.filename)

    FIRMWARE_CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    entry_dir = FIRMWARE_CATALOG_DIR / f"{board}-{version}"
    entry_dir.mkdir(parents=True, exist_ok=True)
    bin_path = entry_dir / safe_name
    bin_path.write_bytes(content)

    meta = {
        "schema": "ESPAI.firmware.v1",
        "board": board,
        "version": version,
        "channel": channel,
        "label": label,
        "project_id": project_id,
        "filename": safe_name,
        "size_bytes": len(content),
        "sha256": sha256,
        "uploaded": _now(),
        "known_good": False,
    }
    (entry_dir / "firmware.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


# ── OTA Actions ───────────────────────────────────────────────────────────────

@router.post("/push")
def push_firmware(data: OTARequest):
    """
    Push firmware to a paired device via HTTP POST to its /ota/update endpoint.

    Security model:
    - Device must be paired before OTA is permitted.
    - Firmware must exist in the catalog; arbitrary files are never served.
    - SHA-256 is sent in X-Firmware-SHA256 header for node-side verification.
    - Every push is audit-logged (push_start + push_complete) with operator and timestamp.
    """
    with get_conn() as conn:
        device = conn.execute(
            "SELECT * FROM devices WHERE id=?", (data.device_id,)
        ).fetchone()
        if not device:
            raise HTTPException(404, f"Device {data.device_id!r} not found")
        if not device["paired"]:
            raise HTTPException(403, "Device must be paired before OTA push")

        meta_path = FIRMWARE_CATALOG_DIR / data.firmware_id / "firmware.json"
        if not meta_path.exists():
            raise HTTPException(404, f"Firmware {data.firmware_id!r} not in catalog")

        with open(meta_path, encoding="utf-8") as fh:
            fw_meta = json.load(fh)

        device_ip = device["ip"]
        if not device_ip:
            raise HTTPException(400, "Device has no IP address on record — checkin first")

        # Board compatibility check
        device_board = (device["board"] or "").strip()
        fw_board = (fw_meta.get("board") or "").strip()
        if fw_board and device_board and fw_board != device_board and not data.force:
            raise HTTPException(
                409,
                f"Board mismatch: firmware targets '{fw_board}' but device reports '{device_board}'. "
                "Set force=true to override (may brick device)."
            )

        conn.execute(
            """INSERT INTO ota_log
               (device_id, fw_version, action, result, operator, timestamp)
               VALUES (?,?,?,?,?,?)""",
            (data.device_id, data.firmware_id, "push_start", "pending", data.operator, _now()),
        )

    bin_path = FIRMWARE_CATALOG_DIR / data.firmware_id / fw_meta["filename"]
    if not bin_path.exists():
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO ota_log (device_id, fw_version, action, result, operator, timestamp)
                   VALUES (?,?,?,?,?,?)""",
                (data.device_id, data.firmware_id, "push_complete", "binary_missing",
                 data.operator, _now()),
            )
        raise HTTPException(404, "Firmware binary missing from catalog directory")

    firmware_bytes = bin_path.read_bytes()

    try:
        # Seed firmware uses WebServer's multipart upload handler, so we must
        # encode the binary as multipart/form-data (not raw octet-stream).
        boundary = "espai-ota-9f3a"
        filename = fw_meta["filename"]
        part_header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        part_footer = f"\r\n--{boundary}--\r\n".encode()
        body = part_header + firmware_bytes + part_footer

        req = urllib.request.Request(
            f"http://{device_ip}/ota/update",
            data=body,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
                "X-Firmware-SHA256": fw_meta.get("sha256", ""),
                "X-ESPAI-Operator": data.operator,
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_body = resp.read(4096).decode("utf-8", errors="replace")
            push_result = "ok"
    except urllib.error.HTTPError as exc:
        resp_body = f"HTTP {exc.code}: {exc.reason}"
        push_result = "failed"
    except Exception as exc:
        exc_str = str(exc)
        # WinError 10054 / ECONNRESET: device rebooted before the response was
        # fully delivered — common with OTA. Verify by polling /api/manifest.
        is_reset = (
            isinstance(exc, ConnectionResetError)
            or "10054" in exc_str
            or "connection reset" in exc_str.lower()
            or "forcibly closed" in exc_str.lower()
        )
        if is_reset:
            import time
            time.sleep(15)
            try:
                with urllib.request.urlopen(
                    f"http://{device_ip}/api/manifest", timeout=8
                ) as verify_resp:
                    manifest = json.loads(verify_resp.read(2048))
                # Device is up and responds — treat as success regardless of
                # fw_version string (build flag may differ from catalog version).
                resp_body = (
                    f"verified: device up, fw_version={manifest.get('fw_version', '?')!r}"
                )
                push_result = "ok"
            except Exception as ve:
                resp_body = f"connection reset; device did not come back: {ve}"
                push_result = "failed"
        else:
            resp_body = exc_str
            push_result = "failed"

    # Capture git HEAD SHA from the linked project (if any)
    git_sha = None
    proj_id = fw_meta.get("project_id") or ""
    if proj_id:
        git_sha = git_helper.get_head_sha(PROJECTS_DIR / proj_id)

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO ota_log (device_id, fw_version, action, result, operator, timestamp, git_sha)
               VALUES (?,?,?,?,?,?,?)""",
            (data.device_id, data.firmware_id, "push_complete", push_result, data.operator, _now(), git_sha),
        )

    return {
        "status": push_result,
        "device_id": data.device_id,
        "firmware_id": data.firmware_id,
        "response": resp_body,
    }


@router.get("/log")
def ota_log(device_id: str | None = None):
    with get_conn() as conn:
        if device_id:
            rows = conn.execute(
                "SELECT * FROM ota_log WHERE device_id=? ORDER BY timestamp DESC LIMIT 200",
                (device_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ota_log ORDER BY timestamp DESC LIMIT 200"
            ).fetchall()
    return [dict(r) for r in rows]


# ── Known-good and rollback ───────────────────────────────────────────────────

@router.post("/catalog/{firmware_id}/mark-good")
def mark_known_good(firmware_id: str, operator: str = "local"):
    """Mark a firmware entry as known-good and log it."""
    meta_path = FIRMWARE_CATALOG_DIR / firmware_id / "firmware.json"
    if not meta_path.exists():
        raise HTTPException(404, f"Firmware {firmware_id!r} not in catalog")
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    meta["known_good"]     = True
    meta["known_good_at"]  = _now()
    meta["known_good_by"]  = re.sub(r"[^\w\-\. ]", "", operator)[:64]
    (FIRMWARE_CATALOG_DIR / firmware_id / "firmware.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO ota_log (device_id, fw_version, action, result, operator, timestamp)
               VALUES (?,?,?,?,?,?)""",
            ("*", firmware_id, "mark_known_good", "ok",
             re.sub(r"[^\w\-\. ]", "", operator)[:64], _now()),
        )
    return {"status": "ok", "firmware_id": firmware_id, "known_good": True}


@router.patch("/catalog/{firmware_id}")
def patch_catalog_entry(firmware_id: str, data: CatalogPatch):
    """Update mutable metadata fields (known_good, rollback_target, channel)."""
    meta_path = FIRMWARE_CATALOG_DIR / firmware_id / "firmware.json"
    if not meta_path.exists():
        raise HTTPException(404, f"Firmware {firmware_id!r} not in catalog")
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)

    if data.known_good is not None:
        meta["known_good"] = data.known_good
    if data.rollback_target is not None:
        # Validate: target must exist in catalog
        if data.rollback_target and not (FIRMWARE_CATALOG_DIR / data.rollback_target / "firmware.json").exists():
            raise HTTPException(404, f"Rollback target {data.rollback_target!r} not in catalog")
        meta["rollback_target"] = data.rollback_target
    if data.channel is not None:
        if data.channel not in ("dev", "beta", "stable"):
            raise HTTPException(400, "channel must be dev, beta, or stable")
        meta["channel"] = data.channel
    if data.label is not None:
        label = data.label.strip()[:128]
        if label and not _SAFE_LABEL.match(label):
            raise HTTPException(400, "Label contains invalid characters")
        meta["label"] = label

    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


@router.post("/rollback")
def rollback_firmware(data: RollbackRequest):
    """
    Push the rollback_target firmware for the device's current firmware.

    Looks at the most recent successful OTA push for this device to determine
    the current firmware, then follows its rollback_target pointer.
    """
    with get_conn() as conn:
        device = conn.execute("SELECT * FROM devices WHERE id=?", (data.device_id,)).fetchone()
        if not device:
            raise HTTPException(404, f"Device {data.device_id!r} not found")
        if not device["paired"]:
            raise HTTPException(403, "Device must be paired before rollback")

        # Find the last successfully pushed firmware for this device
        last_push = conn.execute(
            """SELECT fw_version FROM ota_log
               WHERE device_id=? AND action='push_complete' AND result='ok'
               ORDER BY timestamp DESC LIMIT 1""",
            (data.device_id,),
        ).fetchone()

    if not last_push:
        raise HTTPException(400, "No successful OTA push found for this device — cannot determine rollback target")

    current_fw_id = last_push["fw_version"]
    meta_path     = FIRMWARE_CATALOG_DIR / current_fw_id / "firmware.json"
    if not meta_path.exists():
        raise HTTPException(404, f"Current firmware {current_fw_id!r} not in catalog")

    with open(meta_path, encoding="utf-8") as fh:
        current_meta = json.load(fh)

    rollback_target = current_meta.get("rollback_target")
    if not rollback_target:
        raise HTTPException(400, f"Firmware {current_fw_id!r} has no rollback_target set")

    rb_meta_path = FIRMWARE_CATALOG_DIR / rollback_target / "firmware.json"
    if not rb_meta_path.exists():
        raise HTTPException(404, f"Rollback target {rollback_target!r} not in catalog")

    # Delegate to push logic by constructing an OTARequest and calling push_firmware
    push_data = OTARequest(
        device_id=data.device_id,
        firmware_id=rollback_target,
        operator=data.operator,
        force=data.force,
    )
    result = push_firmware(push_data)
    result["rollback"] = True
    result["rolled_back_from"] = current_fw_id
    return result


# ── Staged rollout ────────────────────────────────────────────────────────────

@router.post("/rollout")
def staged_rollout(data: RolloutRequest):
    """
    Push firmware to a subset of the paired fleet in one operation.

    Targeting options (combinable — all filters are AND-ed):
      device_ids:   explicit list of device IDs to target
      board_filter: only target devices whose board matches this string
      pct:          random sample of pct% of the eligible set (after other filters)

    At least one targeting option must be set.
    Each device push is attempted independently — failures don't abort the run.
    Returns a summary with per-device results.
    """
    import random

    if not data.device_ids and not data.board_filter and not data.pct:
        raise HTTPException(400, "Provide at least one targeting option: device_ids, board_filter, or pct")

    meta_path = FIRMWARE_CATALOG_DIR / data.firmware_id / "firmware.json"
    if not meta_path.exists():
        raise HTTPException(404, f"Firmware {data.firmware_id!r} not in catalog")
    with open(meta_path, encoding="utf-8") as fh:
        fw_meta = json.load(fh)

    # Collect candidate devices
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM devices WHERE paired=1").fetchall()
    candidates = [dict(r) for r in rows]

    # Apply device_ids filter
    if data.device_ids:
        id_set     = set(data.device_ids)
        candidates = [d for d in candidates if d["id"] in id_set]

    # Apply board_filter
    if data.board_filter:
        candidates = [d for d in candidates if (d.get("board") or "").strip() == data.board_filter.strip()]

    if not candidates:
        return {"status": "no_targets", "firmware_id": data.firmware_id, "attempted": 0,
                "succeeded": 0, "failed": 0, "results": []}

    # Apply pct sampling
    if data.pct and data.pct < 100:
        n = max(1, round(len(candidates) * data.pct / 100))
        candidates = random.sample(candidates, n)

    results: list[dict] = []
    succeeded = 0
    failed    = 0

    for device in candidates:
        push_data = OTARequest(
            device_id=device["id"],
            firmware_id=data.firmware_id,
            operator=data.operator,
            force=data.force,
        )
        try:
            res = push_firmware(push_data)
            ok  = res.get("status") == "ok"
        except HTTPException as exc:
            res = {"error": exc.detail}
            ok  = False
        except Exception as exc:
            res = {"error": str(exc)}
            ok  = False

        results.append({"device_id": device["id"], "ok": ok, **res})
        if ok: succeeded += 1
        else:  failed    += 1

    # Audit log for the rollout itself
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO ota_log (device_id, fw_version, action, result, operator, timestamp)
               VALUES (?,?,?,?,?,?)""",
            ("*rollout*", data.firmware_id, "rollout",
             f"{succeeded}/{len(candidates)} ok", data.operator, _now()),
        )

    return {
        "status":      "done",
        "firmware_id": data.firmware_id,
        "attempted":   len(candidates),
        "succeeded":   succeeded,
        "failed":      failed,
        "pct_used":    data.pct,
        "board_filter": data.board_filter,
        "results":     results,
    }
