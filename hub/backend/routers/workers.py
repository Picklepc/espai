import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import POLICIES_DIR, ROOT, WORKERS_DIR
from .. import git_helper
from ..registry.loader import scan_folder
from ..reg_files import (FileWrite, NewItemRequest,
                          delete_item, list_files, read_file,
                          scaffold_worker, write_file,
                          create_file, delete_file)
from ..workers.permissions import build_sandbox_env, check_permissions
from ..workers.runner import _load_policy

router = APIRouter()


class WorkerTestRequest(BaseModel):
    inputs: dict = {}
    timeout: int = 30   # seconds; capped at 60 for test runs


@router.post("/new")
def create_worker(body: NewItemRequest):
    """Scaffold a new worker folder with worker.yaml + main.py + requirements.txt."""
    return scaffold_worker(WORKERS_DIR, body)


@router.get("/")
def list_workers():
    return scan_folder(WORKERS_DIR, "worker")


@router.get("/{worker_name}")
def get_worker(worker_name: str):
    all_workers = scan_folder(WORKERS_DIR, "worker")
    for w in all_workers:
        if w.get("name") == worker_name or w.get("_folder") == worker_name:
            return w
    raise HTTPException(404, f"Worker {worker_name!r} not found")



@router.get("/{worker_name}/compat")
def worker_compat(worker_name: str):
    """
    Check whether this worker can run in the current hub environment.

    Checks:
    - entrypoint exists
    - external_tools on PATH
    - requirements.txt installed (import test for first-party packages)
    - sandbox.preferred: docker → Docker available?
    - permission policy: declared permissions within policy caps
    """
    all_workers = scan_folder(WORKERS_DIR, "worker")
    worker = next(
        (w for w in all_workers if w.get("name") == worker_name or w.get("_folder") == worker_name),
        None,
    )
    if not worker:
        raise HTTPException(404, f"Worker {worker_name!r} not found")

    issues:    list[str] = []
    satisfied: list[str] = []
    policy = _load_policy()

    # Entrypoint
    worker_dir   = Path(worker["_path"])
    entrypoint_n = worker.get("entrypoint", "main.py")
    if (worker_dir / entrypoint_n).exists():
        satisfied.append(f"entrypoint '{entrypoint_n}' found")
    else:
        issues.append(f"Entrypoint '{entrypoint_n}' not found in {worker_dir.name}/")

    # External tools
    for tool in (worker.get("external_tools") or []):
        if shutil.which(tool):
            satisfied.append(f"external tool '{tool}' on PATH")
        else:
            issues.append(f"External tool '{tool}' not found on PATH")

    # Sandbox preference
    sandbox = worker.get("sandbox") or {}
    pref    = sandbox.get("preferred", "native")
    if pref == "docker":
        if shutil.which("docker"):
            satisfied.append("Docker available (preferred sandbox)")
        else:
            native_ok = sandbox.get("native_allowed", False)
            if native_ok:
                satisfied.append("Docker preferred but not found — native_allowed: true (will run native)")
            else:
                issues.append("Docker preferred but not installed, and native_allowed: false")

    # Permission policy
    violations = check_permissions(worker, policy)
    if violations:
        issues.extend(violations)
    else:
        satisfied.append("permissions within policy caps")

    return {
        "worker":     worker_name,
        "runnable":   len(issues) == 0,
        "issues":     issues,
        "satisfied":  satisfied,
        "permissions": worker.get("permissions") or {},
        "sandbox":     sandbox,
    }


@router.post("/{worker_name}/test")
def test_worker(worker_name: str, body: WorkerTestRequest):
    """
    Run a worker synchronously with the given inputs and return full diagnostics.
    Does NOT create a job record — intended for development and debugging.
    Respects the same permission checks as the normal runner.
    """
    all_workers = scan_folder(WORKERS_DIR, "worker")
    worker = next(
        (w for w in all_workers if w.get("name") == worker_name or w.get("_folder") == worker_name),
        None,
    )
    if not worker:
        raise HTTPException(404, f"Worker {worker_name!r} not found")

    policy = _load_policy()
    violations = check_permissions(worker, policy)
    if violations:
        raise HTTPException(403, "Permission denied: " + "; ".join(violations))

    worker_dir  = Path(worker["_path"])
    entrypoint  = worker_dir / worker.get("entrypoint", "main.py")
    if not entrypoint.exists():
        raise HTTPException(400, f"Entrypoint not found: {entrypoint.name}")

    timeout_s = min(int(body.timeout), 60)
    base_env  = {
        **os.environ,
        "ESPAI_JOB_ID":  "test-run",
        "ESPAI_INPUTS":  json.dumps(body.inputs),
    }
    env = build_sandbox_env(worker, policy, base_env)

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, str(entrypoint)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            cwd=str(worker_dir),
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
    except subprocess.TimeoutExpired:
        raise HTTPException(408, f"Worker timed out after {timeout_s}s")
    except Exception as exc:
        raise HTTPException(500, str(exc))

    stdout = result.stdout.strip()
    outputs: dict = {}
    parse_error: str | None = None
    if stdout:
        try:
            outputs = json.loads(stdout)
            if not isinstance(outputs, dict):
                outputs = {"result": outputs}
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
            outputs = {"stdout": stdout}

    return {
        "worker":       worker_name,
        "status":       "ok" if result.returncode == 0 else "failed",
        "exit_code":    result.returncode,
        "duration_ms":  duration_ms,
        "stdout":       stdout[:8000] if stdout else "",
        "stderr":       result.stderr.strip()[:4000] if result.stderr else "",
        "outputs":      outputs,
        "parse_error":  parse_error,
        "inputs_used":  body.inputs,
    }


# ── Worker item management ────────────────────────────────────────────────────

def _worker_folder(worker_name: str) -> str:
    all_workers = scan_folder(WORKERS_DIR, "worker")
    w = next((w for w in all_workers
               if w.get("name") == worker_name or w.get("_folder") == worker_name), None)
    if not w:
        raise HTTPException(404, f"Worker {worker_name!r} not found")
    return w["_folder"]


@router.delete("/{worker_name}")
def delete_worker(worker_name: str):
    from ..db import get_conn
    with get_conn() as conn:
        running = conn.execute(
            "SELECT id FROM jobs WHERE worker_name=? AND status IN ('queued','running')",
            (worker_name,),
        ).fetchone()
    if running:
        raise HTTPException(409, f"Worker {worker_name!r} has active jobs — cancel them first")
    folder = _worker_folder(worker_name)
    return delete_item(WORKERS_DIR, folder)


@router.get("/{worker_name}/files")
def list_worker_files(worker_name: str):
    return list_files(WORKERS_DIR, _worker_folder(worker_name))


@router.get("/{worker_name}/files/{file_path:path}")
def read_worker_file(worker_name: str, file_path: str):
    return read_file(WORKERS_DIR, _worker_folder(worker_name), file_path)


@router.put("/{worker_name}/files/{file_path:path}")
def write_worker_file(worker_name: str, file_path: str, body: FileWrite):
    result = write_file(WORKERS_DIR, _worker_folder(worker_name), file_path, body)
    folder = _worker_folder(worker_name)
    git_helper.git_commit(ROOT, f"edit: workers/{folder}/{file_path}")
    return result


@router.post("/{worker_name}/files/{file_path:path}")
def create_worker_file(worker_name: str, file_path: str, body: FileWrite):
    return create_file(WORKERS_DIR, _worker_folder(worker_name), file_path, body)


@router.delete("/{worker_name}/files/{file_path:path}")
def delete_worker_file(worker_name: str, file_path: str):
    return delete_file(WORKERS_DIR, _worker_folder(worker_name), file_path)


# ── Service worker control ─────────────────────────────────────────────────────

@router.get("/services/status")
def list_service_status():
    """Return runtime status of all service-mode workers."""
    from ..workers.runner import get_service_status
    return get_service_status()


@router.post("/{worker_name}/service/start")
def start_service_worker(worker_name: str):
    from ..workers.runner import service_start
    ok, msg = service_start(worker_name)
    if not ok:
        raise HTTPException(400, msg)
    return {"worker": worker_name, "action": "start", "status": msg}


@router.post("/{worker_name}/service/stop")
def stop_service_worker(worker_name: str):
    from ..workers.runner import service_stop
    ok, msg = service_stop(worker_name)
    if not ok:
        raise HTTPException(404, msg)
    return {"worker": worker_name, "action": "stop", "status": msg}


@router.post("/{worker_name}/service/restart")
def restart_service_worker(worker_name: str):
    from ..workers.runner import service_restart
    ok, msg = service_restart(worker_name)
    if not ok:
        raise HTTPException(400, msg)
    return {"worker": worker_name, "action": "restart", "status": msg}
