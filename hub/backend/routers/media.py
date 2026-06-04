"""
Project Media Store — binary file upload and retrieval for ESP32 projects.

Devices POST images, audio clips, or any binary payload to the hub.
Files are stored in MEDIA_DIR/{project_id}/ and catalogued in project_media.
Hub-side workers receive file_id references and fetch content for processing.
"""

import json
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..config import MEDIA_DIR, PROJECTS_DIR
from ..db import get_conn

router = APIRouter()

_QUOTA_MB    = int(os.environ.get("ESPAI_MEDIA_MAX_MB", "2048"))
_MAX_BYTES   = _QUOTA_MB * 1024 * 1024
_SINGLE_MAX  = 50 * 1024 * 1024  # 50 MB per file hard cap


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_media_dir(project_id: str) -> Path:
    d = MEDIA_DIR / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _project_quota_used(project_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(size_bytes),0) FROM project_media WHERE project_id=?",
            (project_id,),
        ).fetchone()
    return row[0] if row else 0


# ── Upload ─────────────────────────────────────────────────────────────────────

@router.post("/{project_id}/media", status_code=201)
async def upload_media(
    project_id: str,
    file: UploadFile = File(...),
    device_id: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),        # comma-separated
    metadata: Optional[str] = Form(None),    # JSON string
):
    """
    Upload a binary file (image, audio, etc.) for a project.
    Called by ESP32 devices via HTTP multipart/form-data POST.
    Returns file_id usable in worker inputs.
    """
    proj_dir = PROJECTS_DIR / project_id
    if not proj_dir.exists():
        raise HTTPException(404, f"Project {project_id!r} not found")

    # Read file content
    content = await file.read()
    size    = len(content)

    if size > _SINGLE_MAX:
        raise HTTPException(413, f"File too large ({size // (1024*1024)} MB — max 50 MB per file)")

    used = _project_quota_used(project_id)
    if used + size > _MAX_BYTES:
        raise HTTPException(
            507,
            f"Project media quota exceeded ({used // (1024*1024)} MB used of {_QUOTA_MB} MB). "
            "Delete old media files or increase ESPAI_MEDIA_MAX_MB.",
        )

    # Determine content type and extension
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    ext          = Path(file.filename or "upload").suffix or mimetypes.guess_extension(content_type) or ".bin"
    file_id      = str(uuid.uuid4())
    stored_name  = f"{file_id}{ext}"

    media_dir = _project_media_dir(project_id)
    dest      = media_dir / stored_name
    dest.write_bytes(content)

    # Parse metadata
    extra = {}
    if metadata:
        try:
            extra = json.loads(metadata)
        except Exception:
            pass
    if device_id:
        extra["device_id"] = device_id
    if tags:
        extra["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

    now = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO project_media
               (id, project_id, filename, content_type, size_bytes, file_path, created, metadata)
               VALUES (?,?,?,?,?,?,?,?)""",
            (file_id, project_id, file.filename or stored_name,
             content_type, size, stored_name, now, json.dumps(extra)),
        )

    return {
        "file_id":      file_id,
        "filename":     file.filename or stored_name,
        "content_type": content_type,
        "size_bytes":   size,
        "url":          f"/api/projects/{project_id}/media/{file_id}",
        "created":      now,
    }


# ── List ───────────────────────────────────────────────────────────────────────

@router.get("/{project_id}/media")
def list_media(project_id: str, content_type: Optional[str] = None, limit: int = 100):
    """List media files for a project, newest first."""
    with get_conn() as conn:
        if content_type:
            rows = conn.execute(
                "SELECT * FROM project_media WHERE project_id=? AND content_type LIKE ? ORDER BY created DESC LIMIT ?",
                (project_id, f"{content_type}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM project_media WHERE project_id=? ORDER BY created DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        item["url"] = f"/api/projects/{project_id}/media/{r['id']}"
        try:
            item["metadata"] = json.loads(r["metadata"] or "{}")
        except Exception:
            item["metadata"] = {}
        items.append(item)
    return {"files": items, "count": len(items)}


# ── Serve ──────────────────────────────────────────────────────────────────────

@router.get("/{project_id}/media/{file_id}")
def serve_media(project_id: str, file_id: str):
    """Serve the raw file — used by frontend gallery and workers."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM project_media WHERE id=? AND project_id=?",
            (file_id, project_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Media file not found")
    path = _project_media_dir(project_id) / row["file_path"]
    if not path.exists():
        raise HTTPException(404, "File missing from storage")
    return FileResponse(
        str(path),
        media_type=row["content_type"] or "application/octet-stream",
        filename=row["filename"],
    )


# ── Delete ─────────────────────────────────────────────────────────────────────

@router.delete("/{project_id}/media/{file_id}")
def delete_media(project_id: str, file_id: str):
    """Delete a media file from storage and DB."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM project_media WHERE id=? AND project_id=?",
            (file_id, project_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Media file not found")
    path = _project_media_dir(project_id) / row["file_path"]
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
    with get_conn() as conn:
        conn.execute("DELETE FROM project_media WHERE id=?", (file_id,))
    return {"deleted": file_id}


# ── Quota info ─────────────────────────────────────────────────────────────────

@router.get("/{project_id}/media/quota")
def media_quota(project_id: str):
    """Return current media usage and quota for a project."""
    used = _project_quota_used(project_id)
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM project_media WHERE project_id=?", (project_id,)
        ).fetchone()[0]
    return {
        "used_bytes":    used,
        "used_mb":       round(used / (1024 * 1024), 2),
        "quota_mb":      _QUOTA_MB,
        "quota_bytes":   _MAX_BYTES,
        "percent_used":  round(used / _MAX_BYTES * 100, 1) if _MAX_BYTES else 0,
        "file_count":    count,
    }
