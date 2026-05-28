"""
Agent Bench — optional AI-assisted development feature.

All endpoints return 503 when ESPAI_AGENT_BENCH != "true".

Security model (enforced here, not delegated to the agent):
- Blocked paths are never writable by any adapter
- OTA to non-dev devices is rejected
- All adapter actions are logged in agent_runs
- Workers created by agents start quarantined
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
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
    # Secrets and private data — always blocked
    ".env", "secrets/", ".private.yaml", ".private.json",
    "local.yaml", "secrets.yaml", "data/", "backups/",
    "captures/private/", "firmware/seed/secrets.ini",
    # ESPai platform code — agents work *on* projects, not *on* the hub itself
    # (hub-feature tasks that legitimately need hub access must list paths explicitly)
    "firmware/seed/",      # seed template protected — projects get their own copy
    "firmware/provision/", # provision firmware protected
]

# Per-template default acceptance criteria (used when user doesn't specify any)
_TEMPLATE_DEFAULT_CRITERIA: dict[str, list[str]] = {
    "firmware-feature": [
        "Firmware compiles without errors (pio run)",
        "No existing functionality regressed",
    ],
    "hub-feature": [
        "Hub starts without errors after changes",
        "New API endpoint returns expected response",
        "All existing endpoints still respond correctly",
    ],
    "port-to-hub": [
        "Firmware compiles without errors",
        "Hub receives device events within 5 seconds of trigger",
        "ESP32 falls back to its local web server when hub is unreachable (10s timeout)",
        "No existing hub functionality regressed",
    ],
    "recipe-feature": [
        "Recipe YAML validates without errors",
        "Recipe pipeline processes test data correctly",
    ],
    "bug-fix": [
        "The reported issue no longer occurs",
        "No regressions introduced by the fix",
    ],
}

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

# ── Tool metadata (install hints shown in Doctor) ─────────────────────────────

_TOOL_HINTS: dict[str, str] = {
    "python": "https://www.python.org/downloads/",
    "git":    "https://git-scm.com/  — or install GitHub Desktop",
    "pio":    "py -3.11 -m pip install platformio --user",
    "docker": "https://docs.docker.com/desktop/install/windows/",
    "codex":  "npm install -g @openai/codex",
    "claude": "npm install -g @anthropic-ai/claude-code",
    "node":   "https://nodejs.org/",
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


def _extra_tool_dirs() -> list[str]:
    """
    Directories to search in addition to PATH.

    The hub server process may inherit a stripped PATH (especially when launched
    from a GUI or venv). This covers the most common Windows install locations
    for the tools we care about.
    """
    home    = Path.home()
    appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    local   = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    dirs: list[str] = []

    # npm global installs  (claude, codex, node-based tools)
    dirs.append(str(appdata / "npm"))

    # Python user Scripts — pip install --user puts exes here
    for pyver in ("Python313", "Python312", "Python311", "Python310", "Python39"):
        dirs.append(str(appdata / "Python" / pyver / "Scripts"))

    # GitHub Desktop bundled git — pick the newest app-x.y.z folder
    gh_pattern = str(local / "GitHubDesktop" / "app-*" / "resources" / "app" / "git" / "cmd")
    for d in sorted(glob.glob(gh_pattern), reverse=True):
        dirs.append(d)

    # System Git for Windows
    dirs.extend([
        r"C:\Program Files\Git\cmd",
        r"C:\Program Files (x86)\Git\cmd",
    ])

    # Docker Desktop
    dirs.append(r"C:\Program Files\Docker\Docker\resources\bin")

    # Node.js system install
    dirs.append(r"C:\Program Files\nodejs")

    return dirs


def _detect_tool(cmd: str, version_flag: str = "--version") -> dict:
    """
    Find `cmd` on PATH first, then fall back to well-known Windows locations.
    Returns found, path, version, and install_hint.
    """
    # Build an augmented PATH so shutil.which picks up extra dirs
    extra_dirs = _extra_tool_dirs()
    augmented_path = os.pathsep.join(
        [os.environ.get("PATH", "")] + extra_dirs
    )

    found_path = shutil.which(cmd, path=augmented_path)
    hint = _TOOL_HINTS.get(cmd, "")

    if not found_path:
        return {"found": False, "path": None, "version": None, "install_hint": hint}

    try:
        result = subprocess.run(
            [found_path, version_flag], capture_output=True, text=True, timeout=5
        )
        output = (result.stdout or result.stderr or "").strip().splitlines()
        version = output[0] if output else "?"
        return {"found": True, "path": found_path, "version": version, "install_hint": hint}
    except Exception:
        return {"found": True, "path": found_path, "version": "?", "install_hint": hint}


def _find_npm() -> str | None:
    """Locate npm (or npm.cmd on Windows) using the augmented path."""
    augmented = os.pathsep.join([os.environ.get("PATH", "")] + _extra_tool_dirs())
    for name in ("npm.cmd", "npm"):
        found = shutil.which(name, path=augmented)
        if found:
            return found
    return None


# Tools the portal can install on behalf of the user.
# Each entry: display_name, the command list to run, and which _detect_tool
# key to re-check afterwards to confirm success.
_INSTALLABLE: dict[str, dict] = {
    "pio": {
        "display_name": "PlatformIO",
        "cmd_fn": lambda _npm: [sys.executable, "-m", "pip", "install", "platformio", "--user"],
        "check": "pio",
    },
    "codex": {
        "display_name": "OpenAI Codex CLI",
        "cmd_fn": lambda npm: [npm, "install", "-g", "@openai/codex"],
        "needs_npm": True,
        "check": "codex",
    },
    "claude": {
        "display_name": "Claude Code CLI",
        "cmd_fn": lambda npm: [npm, "install", "-g", "@anthropic-ai/claude-code"],
        "needs_npm": True,
        "check": "claude",
    },
}


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

    context_line = ""
    if task.get("context_type") == "project":
        context_line = f"**Scope:** Project — only modify files inside `projects/{task.get('context_id', '')}/`"
    elif task.get("context_type") == "worker":
        context_line = f"**Scope:** Worker — only modify files inside `workers/{task.get('context_id', '')}/`"

    thread_note = ""
    if task.get("parent_task_id"):
        thread_note = f"\n**Note:** This is a follow-up task (parent: `{task['parent_task_id']}`). Review the previous task's diff and address any remaining issues.\n"

    prompt = f"""{system}

---

## Task: {task['title']}

**Project:** {project['name'] if project else '(no project)'}
**Template:** {task.get('template', 'custom')}
{context_line}
{thread_note}
### Description

{task['description']}

### Allowed paths (read + write)

{paths_text}

### Acceptance criteria

{criteria_text}

### Protected paths (never touch)

- `firmware/seed/` — seed template firmware, do not modify
- `firmware/provision/` — provision firmware, do not modify
- `secrets/`, `data/`, `backups/`, `*.env` — always blocked
- Any path not listed in Allowed paths above
"""
    if task.get("context"):
        prompt += f"\n### Additional context\n\n{task['context']}\n"

    prompt += "\n---\n\nBegin. Make the changes, then summarize every file modified and why.\n"
    return prompt


def _infer_allowed_paths(
    context_type: str | None,
    context_id: str | None,
    project_id: str | None,
    template: str,
) -> list[str]:
    """
    Build a sensible default allowed_paths when the user doesn't specify any.

    Priority:
      1. context_type/context_id (most specific — project or worker scope)
      2. template YAML default_allowed_paths
      3. project_id alone (backward compat)
    """
    # 1. Context-scoped inference
    if context_type == "project" and (context_id or project_id):
        pid = context_id or project_id
        paths = [f"projects/{pid}/firmware/", f"projects/{pid}/workers/"]
        if template == "port-to-hub":
            # Also needs the shared workers directory to create hub-side workers
            paths.append("workers/")
        return paths

    if context_type == "worker" and context_id:
        return [f"workers/{context_id}/"]

    # 2. Template YAML defaults — always filter out blocked paths regardless of what YAML says
    templates_dir = AGENT_BENCH_DIR / "task-templates"
    tmpl_path = templates_dir / f"{template}.yaml"
    if tmpl_path.exists():
        try:
            import yaml
            tmpl = yaml.safe_load(tmpl_path.read_text(encoding="utf-8"))
            tmpl_paths = [p for p in tmpl.get("default_allowed_paths", []) if not _is_blocked(p)]
            if tmpl_paths:
                return tmpl_paths
        except Exception:
            pass

    # 3. project_id alone
    if project_id:
        return [f"projects/{project_id}/firmware/", f"projects/{project_id}/workers/"]

    return []


# ── Pydantic models ───────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    description: str
    template: str = "custom"
    project_id: Optional[str] = None
    acceptance_criteria: list[str] = []
    allowed_paths: list[str] = []
    context: Optional[str] = None
    context_type: Optional[str] = None   # "project" | "worker" | "global"
    context_id: Optional[str] = None     # project_id or worker folder name
    parent_task_id: Optional[str] = None # threading: follow-up to an existing task
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
        "manual": {
            "ready": True,
            "install_hint": None,
        },
        "codex-cli": {
            "ready": tools["codex"]["found"],
            "install_hint": _KNOWN_ADAPTERS["codex-cli"]["install_hint"],
        },
        "claude-code-cli": {
            "ready": tools["claude"]["found"],
            "install_hint": _KNOWN_ADAPTERS["claude-code-cli"]["install_hint"],
        },
    }
    return {
        "tools": tools,
        "adapters_ready": adapters_ready,
        "agent_bench_enabled": _is_enabled(),
    }


# ── Install endpoint ──────────────────────────────────────────────────────────

@router.post("/install/{tool_name}")
def install_tool(tool_name: str):
    """
    Install a supported tool (pio, codex, claude) on behalf of the user.
    Runs pip or npm in a subprocess and returns combined stdout+stderr.
    """
    _require_enabled()

    if tool_name not in _INSTALLABLE:
        raise HTTPException(
            400,
            f"'{tool_name}' cannot be installed from the portal. "
            f"Supported: {', '.join(_INSTALLABLE)}",
        )

    meta = _INSTALLABLE[tool_name]
    npm: str | None = None

    if meta.get("needs_npm"):
        npm = _find_npm()
        if not npm:
            raise HTTPException(
                400,
                "npm not found — install Node.js first (https://nodejs.org/) then try again.",
            )

    cmd = meta["cmd_fn"](npm)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(ROOT),
        )
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        success = proc.returncode == 0
    except subprocess.TimeoutExpired:
        return {
            "ok": False, "tool": tool_name,
            "output": "Install timed out after 3 minutes.",
            "exit_code": -1, "now_found": False, "version": None,
        }
    except Exception as exc:
        return {
            "ok": False, "tool": tool_name,
            "output": str(exc),
            "exit_code": -1, "now_found": False, "version": None,
        }

    # Re-detect to confirm and grab the new version string
    check_key = meta["check"]
    detected = _detect_tool(check_key)
    return {
        "ok": success,
        "tool": tool_name,
        "display_name": meta["display_name"],
        "output": output,
        "exit_code": proc.returncode,
        "now_found": detected["found"],
        "version": detected.get("version"),
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
def list_tasks(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    context_type: Optional[str] = None,
    context_id: Optional[str] = None,
    parent_task_id: Optional[str] = None,
):
    _require_enabled()
    conditions: list[str] = []
    params: list = []

    if project_id:
        # Match either direct project_id or context-scoped to the same project
        conditions.append("(project_id=? OR (context_type='project' AND context_id=?))")
        params.extend([project_id, project_id])
    if status:
        conditions.append("status=?"); params.append(status)
    if context_type:
        conditions.append("context_type=?"); params.append(context_type)
    if context_id:
        conditions.append("context_id=?"); params.append(context_id)
    if parent_task_id is not None:
        conditions.append("parent_task_id=?"); params.append(parent_task_id)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"SELECT * FROM agent_tasks {where} ORDER BY created DESC LIMIT 200"

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@router.post("/tasks")
def create_task(data: TaskCreate):
    _require_enabled()
    if data.lane != "dev":
        raise HTTPException(400, "Agent Bench MVP only supports dev lane tasks.")

    # Infer effective project_id from context when not set directly
    effective_project_id = data.project_id
    if not effective_project_id and data.context_type == "project" and data.context_id:
        effective_project_id = data.context_id

    # Infer allowed_paths when not explicitly provided, then enforce block list
    raw_allowed = data.allowed_paths or _infer_allowed_paths(
        data.context_type, data.context_id, effective_project_id, data.template
    )
    blocked_found = [p for p in raw_allowed if _is_blocked(p)]
    if blocked_found:
        raise HTTPException(
            400,
            f"Allowed paths contain protected locations: {', '.join(blocked_found)}. "
            "Use a project context to scope to your project directory instead.",
        )
    allowed = raw_allowed

    # Infer acceptance_criteria when not explicitly provided
    criteria = data.acceptance_criteria or _TEMPLATE_DEFAULT_CRITERIA.get(data.template, [])

    task_id = str(uuid.uuid4())
    now = _now()

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO agent_tasks
               (id, project_id, title, description, template, status,
                allowed_paths, acceptance_criteria, context,
                context_type, context_id, parent_task_id,
                lane, adapter_id, created, updated)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id,
                effective_project_id,
                data.title,
                data.description,
                data.template,
                "draft",
                json.dumps(allowed),
                json.dumps(criteria),
                data.context,
                data.context_type,
                data.context_id,
                data.parent_task_id,
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
    now = _now()
    with get_conn() as conn:
        task_row = conn.execute(
            "SELECT * FROM agent_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if not task_row:
            raise HTTPException(404, f"Task {task_id!r} not found")
        msg_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO agent_task_messages (id, task_id, role, content, timestamp) VALUES (?,?,?,?,?)",
            (msg_id, task_id, data.role, data.content, now),
        )

        # When an agent message is added for a manual-adapter run, snapshot the
        # filesystem so the diff viewer shows what actually changed (not null vs before).
        if data.role == "agent":
            task = dict(task_row)
            allowed = json.loads(task.get("allowed_paths") or "[]")
            snapshot_after = _snapshot_paths(allowed)
            run = conn.execute(
                "SELECT id FROM agent_runs WHERE task_id=? ORDER BY started DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if run:
                conn.execute(
                    "UPDATE agent_runs SET snapshot_after=?, finished=?, status='completed' WHERE id=?",
                    (json.dumps(snapshot_after), now, run["id"]),
                )
            conn.execute(
                "UPDATE agent_tasks SET status='awaiting_review', updated=? WHERE id=?",
                (now, task_id),
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
        return {"diffs": [], "run_id": None, "note": None}
    run = dict(run)
    before = json.loads(run.get("snapshot_before") or "{}")
    raw_after = run.get("snapshot_after")
    if raw_after is None:
        # Snapshot after not yet captured — manual adapter run still in progress
        # or completed before this fix. Don't show a misleading total-deletion diff.
        return {
            "diffs": [],
            "run_id": run["id"],
            "note": "Diff not available — snapshot was not captured for this run. "
                    "Apply changes manually and re-run to see a diff.",
        }
    after = json.loads(raw_after)
    return {"diffs": _compute_diffs(before, after), "run_id": run["id"], "note": None}


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
