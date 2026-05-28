"""
ESPAI Worker Runner

Polls the jobs table and executes queued worker jobs as subprocesses.
One job runs at a time per runner thread (simple but safe for local use).

Job lifecycle:
  queued → running → done | failed | cancelled

Workers must:
  - Have a valid worker.yaml in their folder
  - Not be in quarantined state (checked against policy)
  - Have an entrypoint script that exists

The worker entrypoint receives job context via environment variables:
  ESPAI_JOB_ID    — job ID string
  ESPAI_INPUTS    — JSON-encoded inputs dict

On success the entrypoint should print a single JSON object to stdout.
Stderr is captured and stored as the error field on failure.
"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import POLICIES_DIR, WORKERS_DIR
from ..db import get_conn
from ..registry.loader import scan_folder
from ..rules.engine import evaluate_rules
from .permissions import build_sandbox_env, check_permissions, process_flags

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 5   # seconds between job queue polls
MAX_CONCURRENT  = 1   # jobs running simultaneously (increase carefully)

_running_count = 0
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_policy() -> dict:
    """Load the first policy file found; fall back to safe defaults."""
    try:
        import yaml
        for p in sorted(POLICIES_DIR.glob("*.yaml")):
            with open(p, encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
    except Exception:
        pass
    return {}


def _worker_is_quarantined(worker: dict, policy: dict) -> bool:
    """
    Workers imported from outside the repo start quarantined until reviewed.
    The quarantine flag can be set in worker.yaml:
      quarantine: true
    Or enforced by the policy's imported_default_state.
    """
    if worker.get("quarantine"):
        return True
    # Policy default: all imported workers start quarantined
    # A worker is considered "local" if it has trusted: true in its yaml
    if not worker.get("trusted") and not worker.get("local", True):
        if policy.get("workers", {}).get("imported_default_state") == "quarantined":
            return True
    return False


def _fail_job(job_id: str, error: str) -> None:
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', error=?, finished=? WHERE id=?",
                (error[:2000], _now(), job_id),
            )
    except Exception as e:
        log.error("Failed to mark job %s as failed: %s", job_id, e)


def _run_job(job_id: str, worker_name: str, inputs: dict) -> None:
    global _running_count
    policy = _load_policy()

    # Find the worker definition
    workers = scan_folder(WORKERS_DIR, "worker")
    worker = next(
        (w for w in workers if w.get("name") == worker_name or w.get("_folder") == worker_name),
        None,
    )
    if not worker:
        _fail_job(job_id, f"Worker {worker_name!r} not found in registry")
        return

    if _worker_is_quarantined(worker, policy):
        _fail_job(job_id, f"Worker {worker_name!r} is quarantined — review and set trusted: true in worker.yaml")
        return

    # Permission gate — check declared permissions against active policy
    violations = check_permissions(worker, policy)
    if violations:
        _fail_job(job_id, "Permission denied: " + "; ".join(violations))
        log.warning("Job %s blocked by policy (%s): %s", job_id, worker_name, violations)
        return

    worker_dir = Path(worker["_path"])
    entrypoint_name = worker.get("entrypoint", "main.py")
    entrypoint = worker_dir / entrypoint_name
    if not entrypoint.exists():
        _fail_job(job_id, f"Entrypoint not found: {entrypoint}")
        return

    max_runtime = int(policy.get("workers", {}).get("max_runtime_seconds", 300))

    # Mark running
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET status='running', started=? WHERE id=?",
                (_now(), job_id),
            )
    except Exception as e:
        log.error("Failed to mark job %s as running: %s", job_id, e)
        return

    # Build sanitized env — strips secrets unless worker has explicit permission
    base_env = {**os.environ, "ESPAI_JOB_ID": job_id, "ESPAI_INPUTS": json.dumps(inputs)}
    env = build_sandbox_env(worker, policy, base_env)
    proc_flags = process_flags(worker)

    log.info(
        "Job %s launching worker %r (net=%s secrets=%s fs=%s)",
        job_id, worker_name,
        (worker.get("permissions") or {}).get("network", "none"),
        (worker.get("permissions") or {}).get("secrets", "none"),
        (worker.get("permissions") or {}).get("filesystem", "none"),
    )

    try:
        result = subprocess.run(
            [sys.executable, str(entrypoint)],
            capture_output=True,
            text=True,
            timeout=max_runtime,
            env=env,
            cwd=str(worker_dir),
            **proc_flags,
        )
    except subprocess.TimeoutExpired:
        _fail_job(job_id, f"Timed out after {max_runtime}s")
        return
    except Exception as e:
        _fail_job(job_id, str(e))
        return
    finally:
        with _lock:
            _running_count -= 1

    if result.returncode != 0:
        error = (result.stderr or f"Exit code {result.returncode}").strip()
        _fail_job(job_id, error[:2000])
        log.warning("Job %s failed: %s", job_id, error[:200])
        return

    # Parse stdout as JSON outputs; fall back to raw string
    outputs: dict = {}
    stdout = result.stdout.strip()
    if stdout:
        try:
            outputs = json.loads(stdout)
            if not isinstance(outputs, dict):
                outputs = {"result": outputs}
        except json.JSONDecodeError:
            outputs = {"stdout": stdout}

    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET status='done', outputs=?, finished=? WHERE id=?",
                (json.dumps(outputs), _now(), job_id),
            )
    except Exception as e:
        log.error("Failed to mark job %s as done: %s", job_id, e)
        return

    log.info("Job %s done (%s)", job_id, worker_name)

    # Publish any events the worker emitted in its output dict
    _publish_worker_events(worker_name, job_id, outputs)


def _publish_worker_events(worker_name: str, job_id: str, outputs: dict) -> None:
    """
    If the worker's output contains an 'events' list, publish each entry
    to the event bus and evaluate rules — closing the worker→rules loop.

    Expected shape:
        {"events": [{"type": "motion_detected", "data": {...}}, ...]}
    """
    raw = outputs.get("events")
    if not isinstance(raw, list) or not raw:
        return

    source = f"worker:{worker_name}"
    now    = _now()
    published = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        event_type = str(item.get("type") or item.get("event_type") or "worker_event")
        payload    = item.get("data") or item.get("payload") or {}
        try:
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO events (source, event_type, payload, timestamp) VALUES (?,?,?,?)",
                    (source, event_type, json.dumps(payload), now),
                )
            evaluate_rules({"source": source, "event_type": event_type, "payload": payload, "timestamp": now})
            published += 1
        except Exception as e:
            log.warning("Failed to publish worker event %r: %s", event_type, e)

    if published:
        log.info("Job %s published %d event(s) from worker %r", job_id, published, worker_name)


def _poll_loop() -> None:
    global _running_count
    log.info("Worker runner started (poll interval %ds)", POLL_INTERVAL_S)
    while True:
        try:
            with _lock:
                slots = MAX_CONCURRENT - _running_count

            if slots > 0:
                with get_conn() as conn:
                    rows = conn.execute(
                        "SELECT id, worker_name, inputs FROM jobs "
                        "WHERE status='queued' ORDER BY created ASC LIMIT ?",
                        (slots,),
                    ).fetchall()

                for row in rows:
                    job_id      = row["id"]
                    worker_name = row["worker_name"]
                    inputs      = json.loads(row["inputs"] or "{}")

                    with _lock:
                        # Re-check slot (another thread might have filled it)
                        if _running_count >= MAX_CONCURRENT:
                            break
                        _running_count += 1

                    t = threading.Thread(
                        target=_run_job,
                        args=(job_id, worker_name, inputs),
                        daemon=True,
                        name=f"worker-{job_id[:8]}",
                    )
                    t.start()

        except Exception as e:
            log.error("Runner poll error: %s", e)

        time.sleep(POLL_INTERVAL_S)


def start_runner() -> threading.Thread:
    t = threading.Thread(target=_poll_loop, daemon=True, name="ESPAI-worker-runner")
    t.start()
    return t
