import json
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from ..db import get_conn

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobSubmit(BaseModel):
    worker_name: str
    inputs: dict = {}

    @field_validator("worker_name")
    @classmethod
    def validate_worker_name(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-zA-Z0-9_\-]{1,64}$", v):
            raise ValueError("worker_name must be alphanumeric/dash/underscore, max 64 chars")
        return v


class JobCancel(BaseModel):
    reason: str | None = None


def _deserialize_job(row) -> dict:
    d = dict(row)
    for field in ("inputs", "outputs"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                pass
    return d


@router.get("/")
def list_jobs(status: str | None = None, limit: int = 50):
    if limit > 500:
        limit = 500
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY created DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,)
            ).fetchall()
    return [_deserialize_job(r) for r in rows]


@router.get("/{job_id}")
def get_job(job_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Job {job_id!r} not found")
    return _deserialize_job(row)


@router.post("/submit")
def submit_job(data: JobSubmit):
    """Queue a job for a named worker. The runner picks it up within its poll interval."""
    job_id = secrets.token_hex(8)
    now = _now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, worker_name, status, inputs, created) VALUES (?,?,?,?,?)",
            (job_id, data.worker_name, "queued", json.dumps(data.inputs), now),
        )
    return {"id": job_id, "status": "queued", "worker_name": data.worker_name}


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, data: JobCancel = JobCancel()):
    with get_conn() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Job {job_id!r} not found")
        if row["status"] not in ("queued", "running"):
            raise HTTPException(400, f"Cannot cancel job with status {row['status']!r}")
        conn.execute(
            "UPDATE jobs SET status='cancelled', error=?, finished=? WHERE id=?",
            (data.reason or "cancelled by user", _now(), job_id),
        )
    return {"status": "cancelled", "id": job_id}


@router.delete("/completed")
def purge_completed():
    """Remove all terminal jobs (done / failed / cancelled)."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM jobs WHERE status IN ('done','failed','cancelled')"
        )
    return {"status": "purged"}
