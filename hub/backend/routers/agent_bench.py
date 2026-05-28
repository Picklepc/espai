"""
Agent Bench — optional AI-assisted development feature.

All endpoints return 503 when ESPAI_AGENT_BENCH != "true".

Security model (enforced here, not delegated to the agent):
- Blocked paths are never writable by any adapter
- OTA to non-dev devices is rejected
- All adapter actions are logged in agent_runs
- Workers created by agents start quarantined
"""

import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from ..config import ROOT, AGENTS_DIR, AGENT_BENCH_DIR
from ..db import get_conn

router = APIRouter()

# ── Constants ─────────────────────────────────────────────────────────────────

_BLOCKED_PATH_PATTERNS = [
    ".env", "secrets/", ".private.yaml", ".private.json",
    "local.yaml", "secrets.yaml", "data/", "backups/",
    "captures/private/", "firmware/seed/secrets.ini",
]

_KNOWN_ADAPTERS = {
    "manual": {
        "name": "manual",
        "display_name": "Manual (Copy/Paste)",
        "description": "Copy the generated prompt to your agent, paste results back.",
        "cli_command": None,
        "requires_install": False,
    },
    "codex-cli": {
        "name": "codex-cli",
        "display_name": "OpenAI Codex CLI",
        "description": "Runs via local codex CLI tool.",
        "cli_command": "codex",
        "requires_install": True,
        "install_hint": "npm install -g @openai/codex",
    },
    "claude-code-cli": {
        "name": "claude-code-cli",
        "display_name": "Claude Code CLI",
        "description": "Runs via local claude CLI tool.",
        "cli_command": "claude",
        "requires_install": True,
        "install_hint": "npm install -g @anthropic-ai/claude-code",
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_enabled() -> bool:
    return os.environ.get("ESPAI_AGENT_BENCH", "").lower() in ("1", "true", "yes")


def _require_enabled():
    if not _is_enabled():
        raise HTTPException(
            503,
            "Agent Bench is disabled. Set ESPAI_AGENT_BENCH=true in .env and restart the hub.",
        )


def _is_blocked(path: str) -> bool:
    p = path.lstrip("/").replace("\\", "/")
    for pattern in _BLOCKED_PATH_PATTERNS:
        if pattern.endswith("/"):
            if p.startswith(pattern) or ("/" + pattern) in p:
                return True
        else:
            if p.endswith(pattern) or pattern in p:
                return True
    return False


def _detect_tool(cmd: str, version_flag: str = "--version") -> dict:
    found = shutil.which(cmd)
    if not found:
        return {"found": False, "path": None, "version": None}
    try:
        result = subprocess.run(
            [cmd, version_flag], capture_output=True, text=True, timeout=5
        )
        output = (result.stdout or result.stderr or "").strip().splitlines()
        version = output[0] if output else "?"
        return {"found": True, "path": found, "version": version}
    except Exception:
        return {"found": True, "path": found, "version": "?"}


def _snapshot_paths(allowed_paths: list[str]) -> dict[str, str | None]:
    """Capture current file contents for all files under allowed paths."""
    snapshot: dict[str, str | None] = {}
    for rel_path in allowed_paths:
        base = ROOT / rel_path.lstrip("/")
        if base.is_file():
            try:
                snapshot[rel_path] = base.read_text(encoding="utf-8", errors="replace")
            except Exception:
                snapshot[rel_path] = None
        elif base.is_dir():
            for f in base.rglob("*"):
                if f.is_file():
                    key = str(f.relative_to(ROOT)).replace("\\", "/")
                    try:
                        snapshot[key] = f.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        snapshot[key] = None
    return snapshot


def _compute_diffs(before: dict, after: dict) -> list[dict]:
    all_keys = set(before) | set(after)
    diffs = []
    for key in sorted(all_keys):
        a = (before.get(key) or "").splitlines(keepends=True)
        b = (after.get(key) or "").splitlines(keepends=True)
        if a == b:
            continue
        patch = "".join(unified_diff(a, b, fromfile=f"a/{key}", tofile=f"b/{key}"))
        status = "added" if key not in before else ("removed" if key not in after else "modified")
        diffs.append({"path": key, "status": status, "diff": patch})
    return diffs


def _build_prompt(task: dict, project: dict | None) -> str:
    adapter_dir = AGENTS_DIR / "adapters"
    system_path = adapter_dir / "claude-code" / "prompts" / "system.md"
    system = system_path.read_text(encoding="utf-8") if system_path.exists() else ""

    allowed = json.loads(task.get("allowed_paths") or "[]")
    criteria = json.loads(task.get("acceptance_criteria") or "[]")

    criteria_text = "\n".join(f"- [ ] {c}" for c in criteria) if criteria else "- (none specified)"
    paths_text = "\n".join(f"- `{p}`" for p in allowed) if allowed else "- (all allowed paths for this template)"

    prompt = f"""{system}

---

## Task: {task['title']}

**Project:** {project['name'] if project else '(no project)'}
**Template:** {task.get('template', 'custom')}

### Description

{task['description']}

### Allowed paths (read + write)

{paths_text}

### Acceptance criteria

{criteria_text}
"""
    if task.get("context"):
        prompt += f"\n### Context\n\n{task['context']}\n"

    prompt += "\n---\n\nBegin. Make the changes, then summarize every file modified and why.\n"
    return prompt


# ── Pydantic models ───────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    description: str
    template: str = "custom"
    project_id: Optional[str] = None
    acceptance_criteria: list[str] = []
    allowed_paths: list[str] = []
    context: Optional[str] = None
    lane: str = "dev"
    adapter_id: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title cannot be empty")
        return v.strip()[:200]

    @field_validator("lane")
    @classmethod
    def valid_lane(cls, v: str) -> str:
        if v not in ("dev", "stable", "production"):
            raise ValueError("lane must be dev, stable, or production")
        return v

    @field_validator("allowed_paths")
    @classmethod
    def no_blocked_paths(cls, paths: list[str]) -> list[str]:
        for p in paths:
            if _is_blocked(p):
                raise ValueError(f"Path '{p}' is blocked by agent policy")
        return paths


class MessageCreate(BaseModel):
    role: str = "user"
    content: str

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in ("user", "agent", "system"):
            raise ValueError("role must be user, agent, or system")
        return v


class RunCreate(BaseModel):
    adapter_id: str = "manual"


class ReviewCreate(BaseModel):
    decision: str
    notes: Optional[str] = None

    @field_validator("decision")
    @classmethod
    def valid_decision(cls, v: str) -> str:
        if v not in ("approved", "rejected", "needs_changes"):
            raise ValueError("decision must be approved, rejected, or needs_changes")
        return v


class ConfigUpdate(BaseModel):
    enabled: bool = False
    allow_dev_device_deploy: bool = False
    require_human_review: bool = True
    allowed_adapters: list[str] = ["manual"]


# ── Config endpoints ──────────────────────────────────────────────────────────

@router.get("/config")
def get_config():
    enabled = _is_enabled()
    allow_dev = os.environ.get("ESPAI_AGENT_ALLOW_DEV_DEPLOY", "false").lower() == "true"
    require_review = os.environ.get("ESPAI_AGENT_REQUIRE_REVIEW", "true").lower() != "false"
    allowed = os.environ.get("ESPAI_AGENT_ADAPTERS", "manual").split(",")
    return {
        "enabled": enabled,
        "allow_dev_device_deploy": allow_dev,
        "require_human_review": require_review,
        "allowed_adapters": [a.strip() for a in allowed],
        "available_adapters": list(_KNOWN_ADAPTERS.keys()),
    }


@router.post("/config")
def update_config(data: ConfigUpdate):
    """Write config back to .env (simple key=value update)."""
    env_path = ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    updates = {
        "ESPAI_AGENT_BENCH": "true" if data.enabled else "false",
        "ESPAI_AGENT_ALLOW_DEV_DEPLOY": "true" if data.allow_dev_device_deploy else "false",
        "ESPAI_AGENT_REQUIRE_REVIEW": "true" if data.require_human_review else "false",
        "ESPAI_AGENT_ADAPTERS": ",".join(data.allowed_adapters),
    }

    new_lines = []
    seen = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)

    for key, val in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Apply to current process so subsequent calls reflect the change
    for key, val in updates.items():
        os.environ[key] = val

    return {"status": "ok", "note": "Restart the hub for changes to fully take effect."}


# ── Doctor endpoint ───────────────────────────────────────────────────────────

@router.get("/doctor")
def agent_doctor():
    tools = {
        "python":    _detect_tool("python",    "--version"),
        "git":       _detect_tool("git",       "--version"),
        "pio":       _detect_tool("pio",       "--version"),
        "docker":    _detect_tool("docker",    "--version"),
        "codex":     _detect_tool("codex",     "--version"),
        "claude":    _detect_tool("claude",    "--version"),
        "node":      _detect_tool("node",      "--version"),
    }
    adapters_ready = {
        "manual":          True,
        "codex-cli":       tools["codex"]["found"],
        "claude-code-cli": tools["claude"]["found"],
    }
    return {
        "tools": tools,
        "adapters_ready": adapters_ready,
        "agent_bench_enabled": _is_enabled(),
    }


# ── Adapter endpoints ─────────────────────────────────────────────────────────

@router.get("/adapters")
def list_adapters():
    _require_enabled()
    result = []
    for key, meta in _KNOWN_ADAPTERS.items():
        info = dict(meta)
        if meta.get("cli_command"):
            detected = _detect_tool(meta["cli_command"])
            info["installed"] = detected["found"]
            info["detected_version"] = detected.get("version")
        else:
            info["installed"] = True
            info["detected_version"] = None
        result.append(info)
    return result


@router.post("/adapters/{adapter_name}/test")
def test_adapter(adapter_name: str):
    _require_enabled()
    if adapter_name not in _KNOWN_ADAPTERS:
        raise HTTPException(404, f"Unknown adapter: {adapter_name!r}")
    meta = _KNOWN_ADAPTERS[adapter_name]
    if adapter_name == "manual":
        return {"ok": True, "message": "Manual adapter is always available."}
    cmd = meta.get("cli_command")
    if not cmd:
        return {"ok": False, "message": "No CLI command defined."}
    detected = _detect_tool(cmd)
    if detected["found"]:
        return {"ok": True, "message": f"{cmd} found: {detected['version']}"}
    return {
        "ok": False,
        "message": f"{cmd} not found on PATH.",
        "install_hint": meta.get("install_hint", ""),
    }


# ── Task endpoints ────────────────────────────────────────────────────────────

@router.get("/tasks")
def list_tasks(project_id: Optional[str] = None, status: Optional[str] = None):
    _require_enabled()
    with get_conn() as conn:
        if project_id and status:
            rows = conn.execute(
                "SELECT * FROM agent_tasks WHERE project_id=? AND status=? ORDER BY created DESC",
                (project_id, status),
            ).fetchall()
        elif project_id:
            rows = conn.execute(
                "SELECT * FROM agent_tasks WHERE project_id=? ORDER BY created DESC",
                (project_id,),
            ).fetchall()
        elif status:
            rows = conn.execute(
                "SELECT * FROM agent_tasks WHERE status=? ORDER BY created DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_tasks ORDER BY created DESC LIMIT 100"
            ).fetchall()
    return [dict(r) for r in rows]


@router.post("/tasks")
def create_task(data: TaskCreate):
    _require_enabled()
    if data.lane != "dev":
        raise HTTPException(400, "Agent Bench MVP only supports dev lane tasks.")
    task_id = str(uuid.uuid4())
    now = _now()

    # Default allowed_paths from template if not specified
    allowed = data.allowed_paths
    if not allowed:
        templates_dir = AGENT_BENCH_DIR / "task-templates"
        tmpl_path = templates_dir / f"{data.template}.yaml"
        if tmpl_path.exists():
            try:
                import yaml
                tmpl = yaml.safe_load(tmpl_path.read_text(encoding="utf-8"))
                allowed = tmpl.get("default_allowed_paths", [])
            except Exception:
                pass

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO agent_tasks
               (id, project_id, title, description, template, status,
                allowed_paths, acceptance_criteria, context, lane, adapter_id, created, updated)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id,
                data.project_id,
                data.title,
                data.description,
                data.template,
                "draft",
                json.dumps(allowed),
                json.dumps(data.acceptance_criteria),
                data.context,
                data.lane,
                data.adapter_id,
                now,
                now,
            ),
        )
    return {"id": task_id, "status": "draft", "created": now}


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    _require_enabled()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agent_tasks WHERE id=?", (task_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"Task {task_id!r} not found")
    task = dict(row)
    # Attach latest run summary
    with get_conn() as conn:
        run = conn.execute(
            "SELECT * FROM agent_runs WHERE task_id=? ORDER BY started DESC LIMIT 1",
            (task_id,),
        ).fetchone()
    task["latest_run"] = dict(run) if run else None
    return task


@router.get("/tasks/{task_id}/prompt")
def get_task_prompt(task_id: str):
    _require_enabled()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agent_tasks WHERE id=?", (task_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"Task {task_id!r} not found")
    task = dict(row)
    project = None
    if task.get("project_id"):
        with get_conn() as conn:
            p = conn.execute(
                "SELECT * FROM projects WHERE id=?", (task["project_id"],)
            ).fetchone()
        project = dict(p) if p else None
    return {"prompt": _build_prompt(task, project)}


@router.post("/tasks/{task_id}/message")
def add_message(task_id: str, data: MessageCreate):
    _require_enabled()
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT id FROM agent_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(404, f"Task {task_id!r} not found")
        msg_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO agent_task_messages (id, task_id, role, content, timestamp) VALUES (?,?,?,?,?)",
            (msg_id, task_id, data.role, data.content, _now()),
        )
    return {"id": msg_id, "task_id": task_id}


@router.get("/tasks/{task_id}/messages")
def get_messages(task_id: str):
    _require_enabled()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_task_messages WHERE task_id=? ORDER BY timestamp ASC",
            (task_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/tasks/{task_id}/diff")
def get_diff(task_id: str, run_id: Optional[str] = None):
    _require_enabled()
    with get_conn() as conn:
        if run_id:
            run = conn.execute(
                "SELECT * FROM agent_runs WHERE id=? AND task_id=?", (run_id, task_id)
            ).fetchone()
        else:
            run = conn.execute(
                "SELECT * FROM agent_runs WHERE task_id=? ORDER BY started DESC LIMIT 1",
                (task_id,),
            ).fetchone()
    if not run:
        return {"diffs": [], "run_id": None}
    run = dict(run)
    before = json.loads(run.get("snapshot_before") or "{}")
    after = json.loads(run.get("snapshot_after") or "{}")
    return {"diffs": _compute_diffs(before, after), "run_id": run["id"]}


@router.get("/tasks/{task_id}/artifacts")
def get_artifacts(task_id: str):
    _require_enabled()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_artifacts WHERE task_id=? ORDER BY created DESC",
            (task_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/tasks/{task_id}/run")
def run_task(task_id: str, data: RunCreate):
    """
    Start an agent run for a task.

    - manual adapter: captures snapshot, generates prompt, waits for human to paste result
    - CLI adapters: spawns subprocess in background thread, streams output to task messages
    """
    _require_enabled()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agent_tasks WHERE id=?", (task_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"Task {task_id!r} not found")
    task = dict(row)

    if task["status"] not in ("draft", "needs_changes"):
        raise HTTPException(400, f"Task is {task['status']} — only draft or needs_changes tasks can be run")

    adapter = data.adapter_id
    if adapter not in _KNOWN_ADAPTERS:
        raise HTTPException(400, f"Unknown adapter: {adapter!r}")

    # Snapshot current file state
    allowed = json.loads(task.get("allowed_paths") or "[]")
    snapshot_before = _snapshot_paths(allowed)

    run_id = str(uuid.uuid4())
    now = _now()

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO agent_runs
               (id, task_id, adapter_id, status, started, snapshot_before)
               VALUES (?,?,?,?,?,?)""",
            (run_id, task_id, adapter, "running", now, json.dumps(snapshot_before)),
        )
        conn.execute(
            "UPDATE agent_tasks SET status='running', updated=? WHERE id=?",
            (now, task_id),
        )

    # Generate prompt
    project = None
    if task.get("project_id"):
        with get_conn() as conn:
            p = conn.execute(
                "SELECT * FROM projects WHERE id=?", (task["project_id"],)
            ).fetchone()
        project = dict(p) if p else None
    prompt = _build_prompt(task, project)

    if adapter == "manual":
        # Manual: store prompt as system message, mark waiting for human
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO agent_task_messages (id, task_id, role, content, timestamp) VALUES (?,?,?,?,?)",
                (str(uuid.uuid4()), task_id, "system", prompt, _now()),
            )
            conn.execute(
                "UPDATE agent_runs SET status='awaiting_input' WHERE id=?", (run_id,)
            )
            conn.execute(
                "UPDATE agent_tasks SET status='awaiting_review', updated=? WHERE id=?",
                (_now(), task_id),
            )
        return {
            "run_id": run_id,
            "adapter": "manual",
            "status": "awaiting_input",
            "prompt": prompt,
            "message": "Copy the prompt to your agent, then paste the response as a message.",
        }

    # CLI adapters — run in background thread
    meta = _KNOWN_ADAPTERS[adapter]
    cli_cmd = meta.get("cli_command")
    if not shutil.which(cli_cmd):
        with get_conn() as conn:
            conn.execute(
                "UPDATE agent_runs SET status='failed', finished=?, log=? WHERE id=?",
                (_now(), f"{cli_cmd} not found on PATH", run_id),
            )
            conn.execute(
                "UPDATE agent_tasks SET status='draft', updated=? WHERE id=?",
                (_now(), task_id),
            )
        raise HTTPException(
            400,
            f"{cli_cmd} not found. Install with: {meta.get('install_hint', '')}",
        )

    def _run_cli():
        try:
            if adapter == "claude-code-cli":
                args = [cli_cmd, "--print", "--dangerously-skip-permissions"]
                proc = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=str(ROOT),
                )
                stdout, stderr = proc.communicate(input=prompt, timeout=300)
            elif adapter == "codex-cli":
                args = [cli_cmd, "exec", "--json", "-"]
                proc = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=str(ROOT),
                )
                stdout, stderr = proc.communicate(input=prompt, timeout=300)
            else:
                stdout, stderr = "", "Unknown adapter"
                proc = type("P", (), {"returncode": 1})()

            output = stdout or stderr or "(no output)"
            snapshot_after = _snapshot_paths(allowed)
            finished = _now()

            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO agent_task_messages (id, task_id, role, content, timestamp) VALUES (?,?,?,?,?)",
                    (str(uuid.uuid4()), task_id, "agent", output, finished),
                )
                conn.execute(
                    """UPDATE agent_runs
                       SET status=?, finished=?, exit_code=?, snapshot_after=?, log=?
                       WHERE id=?""",
                    (
                        "completed" if proc.returncode == 0 else "failed",
                        finished,
                        proc.returncode,
                        json.dumps(snapshot_after),
                        stderr[:4096] if stderr else None,
                        run_id,
                    ),
                )
                conn.execute(
                    "UPDATE agent_tasks SET status='awaiting_review', updated=? WHERE id=?",
                    (finished, task_id),
                )
        except subprocess.TimeoutExpired:
            proc.kill()
            with get_conn() as conn:
                conn.execute(
                    "UPDATE agent_runs SET status='failed', finished=?, log=? WHERE id=?",
                    (_now(), "Timed out after 300s", run_id),
                )
                conn.execute(
                    "UPDATE agent_tasks SET status='draft', updated=? WHERE id=?",
                    (_now(), task_id),
                )
        except Exception as exc:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE agent_runs SET status='failed', finished=?, log=? WHERE id=?",
                    (_now(), str(exc)[:2048], run_id),
                )
                conn.execute(
                    "UPDATE agent_tasks SET status='draft', updated=? WHERE id=?",
                    (_now(), task_id),
                )

    thread = threading.Thread(target=_run_cli, daemon=True)
    thread.start()

    return {
        "run_id": run_id,
        "adapter": adapter,
        "status": "running",
        "message": f"Agent run started in background. Poll GET /tasks/{task_id} for status.",
    }


@router.post("/tasks/{task_id}/review")
def submit_review(task_id: str, data: ReviewCreate):
    _require_enabled()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agent_tasks WHERE id=?", (task_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"Task {task_id!r} not found")
    task = dict(row)
    if task["status"] not in ("awaiting_review", "needs_changes"):
        raise HTTPException(400, f"Task is {task['status']} — nothing to review yet")

    review_id = str(uuid.uuid4())
    now = _now()
    new_status = {
        "approved":      "approved",
        "rejected":      "rejected",
        "needs_changes": "needs_changes",
    }[data.decision]

    with get_conn() as conn:
        # Get latest run
        run = conn.execute(
            "SELECT id FROM agent_runs WHERE task_id=? ORDER BY started DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        run_id = run["id"] if run else None

        conn.execute(
            "INSERT INTO agent_reviews (id, task_id, run_id, decision, notes, created) VALUES (?,?,?,?,?,?)",
            (review_id, task_id, run_id, data.decision, data.notes, now),
        )
        conn.execute(
            "UPDATE agent_tasks SET status=?, updated=? WHERE id=?",
            (new_status, now, task_id),
        )
    return {"review_id": review_id, "task_id": task_id, "decision": data.decision, "status": new_status}


# ── Run endpoints ─────────────────────────────────────────────────────────────

@router.get("/runs")
def list_runs(task_id: Optional[str] = None):
    _require_enabled()
    with get_conn() as conn:
        if task_id:
            rows = conn.execute(
                "SELECT id, task_id, adapter_id, status, started, finished, exit_code FROM agent_runs WHERE task_id=? ORDER BY started DESC",
                (task_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, task_id, adapter_id, status, started, finished, exit_code FROM agent_runs ORDER BY started DESC LIMIT 50"
            ).fetchall()
    return [dict(r) for r in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    _require_enabled()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Run {run_id!r} not found")
    return dict(row)
