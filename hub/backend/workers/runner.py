"""
ESPAI Worker Runner

Handles two worker execution modes:

  Job mode (mode: job, default)
    Polls the jobs table and executes queued workers as short-lived subprocesses.
    One job runs at a time. Lifecycle: queued → running → done | failed.

  Service mode (mode: service)
    Long-running supervised processes started at hub startup.
    Auto-restarted on crash with exponential backoff (max 5 restarts, then
    stays in 'crashed' state until manually restarted).
    Lifecycle: starting → running → stopped | crashed | restarting.

Workers receive context via environment variables:
  ESPAI_JOB_ID   — job ID (job mode only)
  ESPAI_INPUTS   — JSON-encoded inputs dict (job mode only)

On success, job-mode entrypoints should print a single JSON object to stdout.
Service-mode entrypoints run indefinitely; stderr is captured for status display.
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

from ..config import POLICIES_DIR, PROJECTS_DIR, WORKERS_DIR
from ..db import get_conn
from ..registry.loader import scan_folder
from ..rules.engine import evaluate_rules
from .permissions import build_sandbox_env, check_permissions, process_flags

log = logging.getLogger(__name__)

POLL_INTERVAL_S      = 5
MAX_CONCURRENT       = 1
MAX_SERVICE_RESTARTS = 5
SERVICE_BASE_DELAY_S = 5   # initial restart delay; doubles each attempt, caps at 60 s

_running_count = 0
_lock          = threading.Lock()

# ── Service tracker ───────────────────────────────────────────────────────────
# { worker_name: { status, restarts, pid, proc, last_error, _stop_requested } }
_service_tracker: dict[str, dict] = {}
_service_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_policy() -> dict:
    try:
        import yaml
        for p in sorted(POLICIES_DIR.glob("*.yaml")):
            with open(p, encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
    except Exception:
        pass
    return {}



def _fail_job(job_id: str, error: str) -> None:
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', error=?, finished=? WHERE id=?",
                (error[:2000], _now(), job_id),
            )
    except Exception as e:
        log.error("Failed to mark job %s as failed: %s", job_id, e)


# ── Worker resolution ─────────────────────────────────────────────────────────

def _resolve_worker(worker_name: str, project_id: str | None) -> dict | None:
    """
    Find a worker definition, preferring a project-scoped copy over the global one.

    Resolution order:
      1. projects/{project_id}/workers/{worker_name}/worker.yaml  (project-local)
      2. workers/{worker_name}/worker.yaml                         (global template)

    This lets users copy a global worker into their project folder and modify it
    freely without affecting other projects that use the same global worker.
    """
    if project_id:
        proj_worker_dir = PROJECTS_DIR / project_id / "workers" / worker_name
        if (proj_worker_dir / "worker.yaml").exists():
            local = scan_folder(proj_worker_dir, "worker")
            match = next(
                (w for w in local if w.get("name") == worker_name or w.get("_folder") == worker_name),
                None,
            )
            if match:
                log.debug("Using project-scoped worker %r for project %s", worker_name, project_id)
                return match

    global_workers = scan_folder(WORKERS_DIR, "worker")
    return next(
        (w for w in global_workers if w.get("name") == worker_name or w.get("_folder") == worker_name),
        None,
    )


# ── Job mode ──────────────────────────────────────────────────────────────────

def _run_job(job_id: str, worker_name: str, inputs: dict) -> None:
    global _running_count
    policy = _load_policy()

    project_id = inputs.get("project_id") if isinstance(inputs, dict) else None
    worker = _resolve_worker(worker_name, project_id)
    if not worker:
        _fail_job(job_id, f"Worker {worker_name!r} not found in registry")
        return

    violations = check_permissions(worker, policy)
    if violations:
        _fail_job(job_id, "Permission denied: " + "; ".join(violations))
        log.warning("Job %s blocked by policy (%s): %s", job_id, worker_name, violations)
        return

    worker_dir     = Path(worker["_path"])
    entrypoint     = worker_dir / worker.get("entrypoint", "main.py")
    if not entrypoint.exists():
        _fail_job(job_id, f"Entrypoint not found: {entrypoint}")
        return

    max_runtime = int(policy.get("workers", {}).get("max_runtime_seconds", 300))

    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET status='running', started=? WHERE id=?",
                (_now(), job_id),
            )
    except Exception as e:
        log.error("Failed to mark job %s as running: %s", job_id, e)
        return

    base_env = {**os.environ, "ESPAI_JOB_ID": job_id, "ESPAI_INPUTS": json.dumps(inputs)}
    env      = build_sandbox_env(worker, policy, base_env)
    pflags   = process_flags(worker)

    log.info("Job %s launching %r", job_id, worker_name)

    try:
        result = subprocess.run(
            [sys.executable, str(entrypoint)],
            capture_output=True, text=True,
            timeout=max_runtime, env=env, cwd=str(worker_dir),
            **pflags,
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
    _publish_worker_events(worker_name, job_id, outputs)


def _publish_worker_events(worker_name: str, job_id: str, outputs: dict) -> None:
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
        log.info("Job %s published %d event(s) from %r", job_id, published, worker_name)


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
                        if _running_count >= MAX_CONCURRENT:
                            break
                        _running_count += 1
                    t = threading.Thread(
                        target=_run_job, args=(job_id, worker_name, inputs),
                        daemon=True, name=f"worker-{job_id[:8]}",
                    )
                    t.start()
        except Exception as e:
            log.error("Runner poll error: %s", e)
        time.sleep(POLL_INTERVAL_S)


def start_runner() -> threading.Thread:
    t = threading.Thread(target=_poll_loop, daemon=True, name="ESPAI-worker-runner")
    t.start()
    return t


# ── Service mode ──────────────────────────────────────────────────────────────

def _supervise_service(
    worker_name: str,
    worker_dir: Path,
    entrypoint: Path,
    env: dict,
    pflags: dict,
) -> None:
    """Supervisor loop: starts the service process and restarts it on crash."""
    restarts = 0
    delay    = SERVICE_BASE_DELAY_S

    while True:
        with _service_lock:
            if _service_tracker.get(worker_name, {}).get("_stop_requested"):
                _service_tracker[worker_name]["status"] = "stopped"
                _service_tracker[worker_name]["proc"]   = None
                _service_tracker[worker_name]["pid"]    = None
                log.info("Service %r stopped", worker_name)
                return
            if restarts > MAX_SERVICE_RESTARTS:
                _service_tracker[worker_name]["status"] = "crashed"
                log.error("Service %r exceeded max restarts — giving up", worker_name)
                return
            _service_tracker[worker_name]["status"]   = "running"
            _service_tracker[worker_name]["restarts"] = restarts

        log.info("Service %r starting (attempt %d)", worker_name, restarts + 1)
        try:
            proc = subprocess.Popen(
                [sys.executable, str(entrypoint)],
                env=env, cwd=str(worker_dir),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, **pflags,
            )
            with _service_lock:
                _service_tracker[worker_name]["proc"] = proc
                _service_tracker[worker_name]["pid"]  = proc.pid

            _, stderr = proc.communicate()  # blocks until process exits

        except Exception as exc:
            stderr = str(exc)
            with _service_lock:
                _service_tracker[worker_name]["last_error"] = stderr

        with _service_lock:
            stopped = _service_tracker.get(worker_name, {}).get("_stop_requested")
            _service_tracker[worker_name]["proc"] = None
            _service_tracker[worker_name]["pid"]  = None
            _service_tracker[worker_name]["last_error"] = (stderr or "").strip()[-500:]

        if stopped:
            with _service_lock:
                _service_tracker[worker_name]["status"] = "stopped"
            log.info("Service %r stopped", worker_name)
            return

        log.warning("Service %r exited, restarting in %ds", worker_name, delay)
        with _service_lock:
            _service_tracker[worker_name]["status"] = "restarting"
        time.sleep(delay)
        delay    = min(delay * 2, 60)
        restarts += 1


def _launch_service(worker_name: str, worker: dict) -> bool:
    """Start the supervisor thread for a single service worker."""
    policy     = _load_policy()
    worker_dir = Path(worker["_path"])
    entrypoint = worker_dir / worker.get("entrypoint", "main.py")
    if not entrypoint.exists():
        log.warning("Service %r entrypoint not found: %s", worker_name, entrypoint)
        return False
    env    = build_sandbox_env(worker, policy, {**os.environ})
    pflags = process_flags(worker)
    with _service_lock:
        _service_tracker[worker_name] = {
            "status": "starting", "restarts": 0,
            "pid": None, "proc": None,
            "last_error": None, "_stop_requested": False,
        }
    t = threading.Thread(
        target=_supervise_service,
        args=(worker_name, worker_dir, entrypoint, env, pflags),
        daemon=True, name=f"service-{worker_name}",
    )
    t.start()
    log.info("Service %r supervisor started", worker_name)
    return True


def start_services() -> None:
    """Start all service-mode workers. Called from hub lifespan on startup."""
    policy  = _load_policy()
    workers = scan_folder(WORKERS_DIR, "worker")
    for worker in workers:
        if worker.get("mode") != "service":
            continue
        wname = worker.get("name") or worker.get("_folder")
        if not wname:
            continue
        _launch_service(wname, worker)


# ── Service control API (called by workers router) ────────────────────────────

def get_service_status() -> dict[str, dict]:
    """Return a snapshot of all tracked service worker states."""
    with _service_lock:
        return {
            name: {k: v for k, v in info.items() if k not in ("proc", "_stop_requested")}
            for name, info in _service_tracker.items()
        }


def service_start(worker_name: str) -> tuple[bool, str]:
    """Start a stopped or crashed service worker."""
    with _service_lock:
        existing = _service_tracker.get(worker_name, {})
        if existing.get("status") in ("running", "starting", "restarting"):
            return True, "already running"

    policy  = _load_policy()
    workers = scan_folder(WORKERS_DIR, "worker")
    worker  = next(
        (w for w in workers if w.get("name") == worker_name or w.get("_folder") == worker_name),
        None,
    )
    if not worker or worker.get("mode") != "service":
        return False, "not a service worker"
    ok = _launch_service(worker_name, worker)
    return ok, "started" if ok else "entrypoint not found"


def service_stop(worker_name: str) -> tuple[bool, str]:
    """Stop a running service worker (will not auto-restart)."""
    with _service_lock:
        if worker_name not in _service_tracker:
            return False, "not tracked"
        _service_tracker[worker_name]["_stop_requested"] = True
        proc = _service_tracker[worker_name].get("proc")
    if proc:
        try:
            proc.terminate()
        except (ProcessLookupError, OSError):
            pass
    return True, "stop requested"


def service_restart(worker_name: str) -> tuple[bool, str]:
    """Restart a service worker by killing it; supervisor will re-launch."""
    with _service_lock:
        if worker_name not in _service_tracker:
            # Not running yet — just start it
            pass
        else:
            _service_tracker[worker_name]["_stop_requested"] = False
            _service_tracker[worker_name]["restarts"]        = 0
            proc = _service_tracker[worker_name].get("proc")
            if proc:
                try:
                    proc.terminate()
                except (ProcessLookupError, OSError):
                    pass
                return True, "restart requested"

    # Not currently tracked — start fresh
    ok, msg = service_start(worker_name)
    return ok, msg
