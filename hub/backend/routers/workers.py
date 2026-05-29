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

from ..config import POLICIES_DIR, WORKERS_DIR
from ..registry.loader import scan_folder
from ..workers.permissions import build_sandbox_env, check_permissions
from ..workers.runner import _load_policy

router = APIRouter()


class WorkerTestRequest(BaseModel):
    inputs: dict = {}
    timeout: int = 30   # seconds; capped at 60 for test runs


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


@router.patch("/{worker_name}/quarantine")
def set_worker_quarantine(worker_name: str, quarantine: bool = True):
    """
    Set the quarantine flag in a worker's YAML manifest.
    Pass quarantine=false to lift quarantine after reviewing agent-generated code.
    """
    if not re.match(r"^[a-zA-Z0-9_\-]{1,64}$", worker_name):
        raise HTTPException(400, "Invalid worker name")
    all_workers = scan_folder(WORKERS_DIR, "worker")
    worker = next(
        (w for w in all_workers if w.get("name") == worker_name or w.get("_folder") == worker_name),
        None,
    )
    if not worker:
        raise HTTPException(404, f"Worker {worker_name!r} not found")

    folder = worker.get("_folder", worker_name)
    yaml_path = WORKERS_DIR / folder / "worker.yaml"
    if not yaml_path.exists():
        raise HTTPException(404, f"worker.yaml not found for {worker_name!r}")

    import yaml as _yaml
    try:
        with open(yaml_path, encoding="utf-8") as fh:
            data = _yaml.safe_load(fh) or {}
    except Exception as exc:
        raise HTTPException(500, f"Failed to read worker.yaml: {exc}")

    data["quarantine"] = quarantine
    if not quarantine:
        data["trusted"] = True

    try:
        with open(yaml_path, "w", encoding="utf-8") as fh:
            _yaml.dump(data, fh, default_flow_style=False, allow_unicode=True)
    except Exception as exc:
        raise HTTPException(500, f"Failed to write worker.yaml: {exc}")

    return {"worker": worker_name, "quarantine": quarantine, "trusted": not quarantine}


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
    - quarantine state
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

    # Quarantine
    if worker.get("quarantine"):
        issues.append("Worker is quarantined — set trusted: true in worker.yaml to enable")
    else:
        satisfied.append("not quarantined")

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

    if worker.get("quarantine"):
        raise HTTPException(403, f"Worker {worker_name!r} is quarantined — set trusted: true to test")

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
