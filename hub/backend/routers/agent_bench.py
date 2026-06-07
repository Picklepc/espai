"""
Agent Bench — optional AI-assisted development feature.

All endpoints return 503 when ESPAI_AGENT_BENCH != "true".

Security model (enforced here, not delegated to the agent):
- Blocked paths are never writable by any adapter
- OTA to non-dev devices is rejected
- All adapter actions are logged in agent_runs
- Workers created by agents are committed to git for review
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

from ..config import ROOT, AGENTS_DIR, AGENT_BENCH_DIR, PROJECTS_DIR, WORKERS_DIR
from ..db import get_conn
from .. import git_helper

router = APIRouter()

# ── Constants ─────────────────────────────────────────────────────────────────

_BLOCKED_PATH_PATTERNS = [
    # Secrets and private data — always blocked
    ".env", "secrets/", ".private.yaml", ".private.json",
    "local.yaml", "secrets.yaml", "data/", "backups/",
    "captures/private/", "firmware/seed/secrets.ini",
    # ESPAI platform code — agents work *on* projects, not *on* the hub itself
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

    # PlatformIO — VSCode extension installs pio here (not on PATH)
    # Cross-platform: ~/.platformio/penv/Scripts (Windows) or .../bin (Unix)
    dirs.append(str(home / ".platformio" / "penv" / "Scripts"))  # Windows
    dirs.append(str(home / ".platformio" / "penv" / "bin"))      # Linux/macOS
    # Also the raw .platformio/packages path some versions use
    dirs.append(str(home / ".platformio" / "packages" / "tool-scons" / "bin"))

    # GitHub Desktop bundled git — pick the newest app-x.y.z folder
    gh_pattern = str(local / "GitHubDesktop" / "app-*" / "resources" / "app" / "git" / "cmd")
    for d in sorted(glob.glob(gh_pattern), reverse=True):
        dirs.append(d)

    # System Git for Windows
    dirs.extend([
        r"C:\Program Files\Git\cmd",
        r"C:\Program Files (x86)\Git\cmd",
    ])

    # Node.js system install (Windows installer default)
    dirs.append(r"C:\Program Files\nodejs")
    # nvm-windows puts node versions here
    dirs.append(str(appdata / "nvm"))
    nvm_glob = str(appdata / "nvm" / "v*")
    for d in sorted(glob.glob(nvm_glob), reverse=True)[:3]:
        dirs.append(d)

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


_SNAPSHOT_MAX_FILE_BYTES = 256 * 1024   # skip files larger than 256 KB
_SNAPSHOT_SKIP_EXTS = frozenset({
    ".bin", ".elf", ".hex", ".o", ".a", ".so", ".dll", ".exe",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".mp4", ".mp3", ".wav", ".ogg", ".flac",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
    ".pdf", ".db", ".sqlite", ".pyc", ".pyo",
})
_SNAPSHOT_SKIP_DIRS = frozenset({".pio", ".git", "__pycache__", "node_modules", ".venv", "venv"})


def _snapshot_paths(allowed_paths: list[str]) -> dict[str, str | None]:
    """
    Capture text file contents for all files under allowed paths.
    Skips binary files, large files, and build/cache directories to avoid
    OOM on routers with limited RAM.
    """
    snapshot: dict[str, str | None] = {}

    def _should_skip_dir(d: "Path") -> bool:
        return d.name in _SNAPSHOT_SKIP_DIRS

    def _read_file(f: "Path", key: str) -> None:
        if f.suffix.lower() in _SNAPSHOT_SKIP_EXTS:
            return
        try:
            if f.stat().st_size > _SNAPSHOT_MAX_FILE_BYTES:
                return
        except OSError:
            return
        try:
            snapshot[key] = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            snapshot[key] = None

    for rel_path in allowed_paths:
        base = ROOT / rel_path.lstrip("/")
        if base.is_file():
            _read_file(base, rel_path)
        elif base.is_dir():
            for f in base.rglob("*"):
                if not f.is_file():
                    continue
                if any(_should_skip_dir(p) for p in f.parents):
                    continue
                key = str(f.relative_to(ROOT)).replace("\\", "/")
                _read_file(f, key)
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
    from ..config import PROJECTS_DIR as _PROJECTS_DIR
    adapter_dir = AGENTS_DIR / "adapters"
    system_path = adapter_dir / "claude-code" / "prompts" / "system.md"
    system = system_path.read_text(encoding="utf-8") if system_path.exists() else ""

    # Inject agents/rules.md — explicit do/do-not list
    rules_md = ""
    rules_path = ROOT / "agents" / "rules.md"
    if rules_path.exists():
        try:
            rules_md = "\n---\n\n" + rules_path.read_text(encoding="utf-8") + "\n"
        except Exception:
            pass

    # Inject per-project ESPAI.md when present — project-specific context
    project_context_md = ""
    proj_id = (
        task.get("context_id") if task.get("context_type") == "project"
        else (project.get("id") if project else None)
    )
    if proj_id:
        espai_path = _PROJECTS_DIR / proj_id / "ESPAI.md"
        if espai_path.exists():
            try:
                project_context_md = (
                    "\n---\n\n## Project Context (from projects/"
                    + proj_id + "/ESPAI.md)\n\n"
                    + espai_path.read_text(encoding="utf-8") + "\n"
                )
            except Exception:
                pass

    # Inject brief registry summary — lists existing cards and recipes so agents
    # know what primitives are available to reuse before creating new ones.
    registry_summary = ""
    try:
        from ..registry.loader import scan_folder
        from ..config import ROOT as _ROOT
        card_names   = [c.get("name") or c.get("_folder","") for c in scan_folder(_ROOT / "cards",   "card")   if c.get("name") or c.get("_folder")]
        recipe_names = [r.get("name") or r.get("_folder","") for r in scan_folder(_ROOT / "recipes", "recipe") if r.get("name") or r.get("_folder")]
        worker_names = [w.get("name") or w.get("_folder","") for w in scan_folder(_ROOT / "workers", "worker") if w.get("name") or w.get("_folder")]
        parts = []
        if card_names:   parts.append("**Cards** (dashboard widgets): " + ", ".join(f"`{n}`" for n in card_names))
        if recipe_names: parts.append("**Recipes** (YAML pipelines): "  + ", ".join(f"`{n}`" for n in recipe_names))
        if worker_names: parts.append("**Workers** (Python modules): "  + ", ".join(f"`{n}`" for n in worker_names))
        if parts:
            registry_summary = (
                "\n---\n\n## Available registry primitives\n\n"
                + "\n".join(parts)
                + "\n\nReuse existing primitives where appropriate. "
                + "Create new workers/cards/recipes only when no suitable one exists.\n"
            )
    except Exception:
        pass

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

    prompt = f"""{system}{rules_md}{project_context_md}{registry_summary}
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
        if template in ("hub-feature", "port-to-hub", "api-integration"):
            # Hub-side tasks may need to create or reuse shared workers, cards, and recipes
            paths += ["workers/", "cards/", "recipes/"]
        elif template == "firmware-feature":
            # Firmware tasks may need hub workers for offloaded processing
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
    reject_paths: list[str] = []  # file paths to revert to snapshot_before

    @field_validator("decision")
    @classmethod
    def valid_decision(cls, v: str) -> str:
        if v not in ("approved", "rejected", "needs_changes"):
            raise ValueError("decision must be approved, rejected, or needs_changes")
        return v


class ConfigUpdate(BaseModel):
    enabled: bool = False
    allow_dev_device_deploy: bool = False
    allowed_adapters: list[str] = ["manual"]
    claude_tool_mode: str = "full"   # "full" | "safe"


# Tools pre-approved in /root/.claude/settings.json for each mode.
# "full"  — shell + web + file tools (enables pio, wget, jadx, decompilation, etc.)
# "safe"  — file tools only, no shell execution or network access
_CLAUDE_TOOL_MODES: dict[str, list[str]] = {
    "full": [
        "Bash(*)", "Read(*)", "Write(*)", "Edit(*)",
        "Glob(*)", "Grep(*)", "WebFetch(*)", "WebSearch(*)",
        "TodoWrite(*)", "TodoRead(*)",
    ],
    "safe": [
        "Read(*)", "Write(*)", "Edit(*)",
        "Glob(*)", "Grep(*)",
        "TodoWrite(*)", "TodoRead(*)",
    ],
}


# ── Template list endpoint ────────────────────────────────────────────────────

@router.get("/templates")
def list_templates(device_type: str = "esp32"):
    """
    Return task templates applicable to the given device_type.
    Templates without applicable_types are shown for all types.
    """
    import yaml as _yaml
    templates_dir = AGENT_BENCH_DIR / "task-templates"
    result = []
    for p in sorted(templates_dir.glob("*.yaml")):
        try:
            tmpl = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        applicable = tmpl.get("applicable_types")
        if applicable and device_type not in applicable:
            continue
        result.append({
            "id":          tmpl.get("id", p.stem),
            "name":        tmpl.get("name", p.stem),
            "description": tmpl.get("description", ""),
            "applicable_types": applicable or ["esp32", "integration", "hybrid"],
        })
    # Always include 'custom'
    if not any(t["id"] == "custom" for t in result):
        result.append({"id": "custom", "name": "Custom", "description": "Free-form task",
                       "applicable_types": ["esp32", "integration", "hybrid"]})
    return result


# ── Config endpoints ──────────────────────────────────────────────────────────

@router.get("/config")
def get_config():
    enabled = _is_enabled()
    allow_dev = os.environ.get("ESPAI_AGENT_ALLOW_DEV_DEPLOY", "false").lower() == "true"
    allowed = os.environ.get("ESPAI_AGENT_ADAPTERS", "manual").split(",")
    tool_mode = os.environ.get("ESPAI_CLAUDE_TOOL_MODE", "full")
    if tool_mode not in _CLAUDE_TOOL_MODES:
        tool_mode = "full"
    return {
        "enabled":                enabled,
        "allow_dev_device_deploy": allow_dev,
        "require_human_review":   False,   # removed — agent changes always auto-apply; use git to roll back
        "allowed_adapters":       [a.strip() for a in allowed],
        "available_adapters":     list(_KNOWN_ADAPTERS.keys()),
        "claude_tool_mode":       tool_mode,
    }


@router.post("/config")
def update_config(data: ConfigUpdate):
    """Write config back to .env (simple key=value update)."""
    env_path = ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    tool_mode = data.claude_tool_mode if data.claude_tool_mode in _CLAUDE_TOOL_MODES else "full"
    updates = {
        "ESPAI_AGENT_BENCH":           "true" if data.enabled else "false",
        "ESPAI_AGENT_ALLOW_DEV_DEPLOY": "true" if data.allow_dev_device_deploy else "false",
        "ESPAI_AGENT_ADAPTERS":        ",".join(data.allowed_adapters),
        "ESPAI_CLAUDE_TOOL_MODE":      tool_mode,
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

def _claude_authenticated() -> bool:
    """Check whether Claude Code CLI has stored credentials."""
    import pathlib
    home = pathlib.Path.home()
    candidates = [
        home / ".claude" / ".credentials.json",
        home / ".claude" / "credentials.json",
        home / ".config" / "claude" / "credentials.json",
        pathlib.Path(os.environ.get("APPDATA", "")) / "Claude" / "credentials.json",
    ]
    return any(p.exists() and p.stat().st_size > 10 for p in candidates)


def _codex_authenticated() -> bool:
    """Check whether the Codex CLI has usable credentials.
    Accepts either an OPENAI_API_KEY env var or a stored credentials file."""
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return True
    import pathlib
    home = pathlib.Path.home()
    candidates = [
        home / ".openai" / "credentials.json",
        home / ".config" / "openai" / "credentials.json",
        pathlib.Path(os.environ.get("APPDATA", "")) / "OpenAI" / "credentials.json",
    ]
    return any(p.exists() and p.stat().st_size > 10 for p in candidates)


@router.get("/doctor")
def agent_doctor():
    tools = {
        "python":    _detect_tool("python",    "--version"),
        "git":       _detect_tool("git",       "--version"),
        "pio":       _detect_tool("pio",       "--version"),
        "codex":     _detect_tool("codex",     "--version"),
        "claude":    _detect_tool("claude",    "--version"),
        "node":      _detect_tool("node",      "--version"),
    }
    claude_installed = tools["claude"]["found"]
    claude_authed    = claude_installed and _claude_authenticated()
    codex_installed  = tools["codex"]["found"]
    codex_authed     = codex_installed and _codex_authenticated()
    adapters_ready = {
        "manual": {
            "ready": True,
            "install_hint": None,
        },
        "codex-cli": {
            "ready":         codex_installed and codex_authed,
            "install_hint":  _KNOWN_ADAPTERS["codex-cli"]["install_hint"],
            "installed":     codex_installed,
            "authenticated": codex_authed,
        },
        "claude-code-cli": {
            "ready":         claude_installed and claude_authed,
            "install_hint":  _KNOWN_ADAPTERS["claude-code-cli"]["install_hint"],
            "authenticated": claude_authed,
            "installed":     claude_installed,
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

    # Pass the augmented PATH to the subprocess so that npm's own child
    # processes (e.g. `node install.cjs` in postinstall scripts) can find
    # node, python, etc. even when the hub was launched with a stripped PATH.
    augmented_env = os.environ.copy()
    augmented_env["PATH"] = os.pathsep.join(
        [os.environ.get("PATH", "")] + _extra_tool_dirs()
    )

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(ROOT),
            env=augmented_env,
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


_UNINSTALLABLE = {
    "codex":  {"display_name": "OpenAI Codex CLI",  "cmd_fn": lambda npm: [npm, "uninstall", "-g", "@openai/codex"],             "needs_npm": True, "check": "codex"},
    "claude": {"display_name": "Claude Code CLI",   "cmd_fn": lambda npm: [npm, "uninstall", "-g", "@anthropic-ai/claude-code"], "needs_npm": True, "check": "claude"},
    "pio":    {"display_name": "PlatformIO",         "cmd_fn": lambda _:   [sys.executable, "-m", "pip", "uninstall", "platformio", "-y"], "check": "pio"},
}


@router.post("/uninstall/{tool_name}")
def uninstall_tool(tool_name: str):
    """Uninstall a supported tool (pio, codex, claude)."""
    _require_enabled()
    if tool_name not in _UNINSTALLABLE:
        raise HTTPException(400, f"'{tool_name}' cannot be uninstalled from the portal. Supported: {', '.join(_UNINSTALLABLE)}")

    meta = _UNINSTALLABLE[tool_name]
    npm: str | None = None
    if meta.get("needs_npm"):
        npm = _find_npm()
        if not npm:
            return {"ok": False, "tool": tool_name, "output": "npm not found — cannot uninstall npm package", "exit_code": 1, "now_found": False}

    cmd = meta["cmd_fn"](npm)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(ROOT))
        output  = ((proc.stdout or "") + (proc.stderr or "")).strip()
        success = proc.returncode == 0
    except subprocess.TimeoutExpired:
        return {"ok": False, "tool": tool_name, "output": "Uninstall timed out.", "exit_code": -1, "now_found": True}
    except Exception as exc:
        return {"ok": False, "tool": tool_name, "output": str(exc), "exit_code": -1, "now_found": True}

    check_key = meta["check"]
    detected = _detect_tool(check_key)
    return {"ok": success, "tool": tool_name, "display_name": meta["display_name"],
            "output": output, "exit_code": proc.returncode,
            "now_found": detected["found"], "version": detected.get("version")}


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
            # Expose auth state so the frontend can show login prompts
            if key == "claude-code-cli":
                info["authenticated"] = info["installed"] and _claude_authenticated()
            elif key == "codex-cli":
                info["authenticated"] = info["installed"] and _codex_authenticated()
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

        # When an agent message arrives for a manual run, auto-approve and commit.
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
                    "INSERT INTO agent_reviews (id, task_id, run_id, decision, notes, created) VALUES (?,?,?,?,?,?)",
                    (str(uuid.uuid4()), task_id, run["id"], "approved",
                     "auto-applied (manual) — use git log to review changes", now),
                )
            conn.execute(
                "UPDATE agent_tasks SET status='approved', updated=? WHERE id=?",
                (now, task_id),
            )

    # Auto-commit project git on manual run completion
    if data.role == "agent":
        task_data = dict(task_row)
        proj_id = (task_data.get("context_id") if task_data.get("context_type") == "project"
                   else task_data.get("project_id"))
        title = task_data.get("title", task_id)[:60]
        if proj_id:
            try:
                git_helper.git_commit(PROJECTS_DIR / proj_id, f"agent: {title} (auto-applied)")
            except Exception:
                pass

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

    # CLI adapters — locate binary
    meta = _KNOWN_ADAPTERS[adapter]
    cli_cmd = meta.get("cli_command")
    augmented_path = os.pathsep.join([os.environ.get("PATH", "")] + _extra_tool_dirs())
    cli_bin = shutil.which(cli_cmd, path=augmented_path)

    if not cli_bin:
        err_log = (
            f"{cli_cmd!r} not found on PATH or in common install locations.\n"
            f"Searched: {augmented_path[:500]}\n"
            f"Install with: {meta.get('install_hint', 'see Doctor')}"
        )
        with get_conn() as conn:
            conn.execute(
                "UPDATE agent_runs SET status='failed', finished=?, log=? WHERE id=?",
                (_now(), err_log, run_id),
            )
            conn.execute(
                "INSERT INTO agent_task_messages (id, task_id, role, content, timestamp) VALUES (?,?,?,?,?)",
                (str(uuid.uuid4()), task_id, "system",
                 f"ERROR: {cli_cmd} not found. Run Doctor to diagnose, or check PATH.\n\n{err_log}",
                 _now()),
            )
            conn.execute(
                "UPDATE agent_tasks SET status='draft', updated=? WHERE id=?",
                (_now(), task_id),
            )
        raise HTTPException(
            400,
            f"{cli_cmd} not found. Run Agent Bench → Doctor to diagnose. "
            f"Install with: {meta.get('install_hint', '')}",
        )

    # Build subprocess env: inherit current env + augmented PATH so the CLI can
    # find its own dependencies (node, npm-linked tools, etc.)
    # HOME must be explicit so Claude Code finds ~/.claude/settings.json even
    # when spawned as a subprocess (some environments strip HOME from inherited env).
    _home = os.path.expanduser("~")
    cli_env = {**os.environ, "PATH": augmented_path,
               "HOME": _home, "CI": "true", "NO_COLOR": "1", "TERM": "dumb"}

    # Post a "starting" message so the thread shows activity immediately
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agent_task_messages (id, task_id, role, content, timestamp) VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), task_id, "system",
             f"[{adapter}] Starting — using {cli_bin}",
             _now()),
        )

    def _run_cli():
        proc = None
        try:
            if adapter == "claude-code-cli":
                # Write /root/.claude/settings.json fresh from the current tool
                # mode setting so permissions are always in sync with the UI toggle.
                import os as _os, json as _json, pathlib as _pl
                _tool_mode = _os.environ.get("ESPAI_CLAUDE_TOOL_MODE", "full")
                if _tool_mode not in _CLAUDE_TOOL_MODES:
                    _tool_mode = "full"
                _claude_dir = _pl.Path(_os.path.expanduser("~")) / ".claude"
                _claude_dir.mkdir(parents=True, exist_ok=True)
                (_claude_dir / "settings.json").write_text(
                    _json.dumps({"permissions": {"allow": _CLAUDE_TOOL_MODES[_tool_mode]}},
                                indent=2),
                    encoding="utf-8",
                )
                # --dangerously-skip-permissions is rejected when running as root.
                # The settings.json above handles tool approval instead.
                _root = hasattr(_os, "getuid") and _os.getuid() == 0
                args = [cli_bin, "--print"]
                if not _root:
                    args.append("--dangerously-skip-permissions")
                proc = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=str(ROOT),
                    env=cli_env,
                )
                stdout, stderr = proc.communicate(input=prompt, timeout=600)

            elif adapter == "codex-cli":
                args = [cli_bin, "exec", "--json", "-"]
                proc = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=str(ROOT),
                    env=cli_env,
                )
                stdout, stderr = proc.communicate(input=prompt, timeout=600)

            else:
                stdout, stderr = "", "Unknown adapter"
                proc = type("P", (), {"returncode": 1})()

            finished       = _now()
            output         = (stdout or "").strip() or (stderr or "").strip() or "(no output)"
            snapshot_after = _snapshot_paths(allowed)
            success        = proc.returncode == 0

            # Agent changes always auto-apply — use git log to review history and roll back.
            new_task_status = "approved" if success else "needs_changes"

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
                        "completed" if success else "failed",
                        finished, proc.returncode,
                        json.dumps(snapshot_after),
                        stderr[:4096] if stderr else None,
                        run_id,
                    ),
                )
                conn.execute(
                    "UPDATE agent_tasks SET status=?, updated=? WHERE id=?",
                    (new_task_status, finished, task_id),
                )
                if new_task_status == "approved":
                    conn.execute(
                        "INSERT INTO agent_reviews (id, task_id, run_id, decision, notes, created) VALUES (?,?,?,?,?,?)",
                        (str(uuid.uuid4()), task_id, run_id, "approved",
                         "auto-applied — use git log to review changes", finished),
                    )

            # Auto-approve side-effect: git commit
            if new_task_status == "approved":
                try:
                    proj_id = None
                    with get_conn() as conn:
                        t_row = conn.execute(
                            "SELECT context_type, context_id, project_id, title FROM agent_tasks WHERE id=?",
                            (task_id,),
                        ).fetchone()
                    if t_row:
                        proj_id = (t_row["context_id"] if t_row["context_type"] == "project"
                                   else t_row["project_id"])
                    if proj_id:
                        import hub.backend.git_helper as _gh
                        _gh.git_commit(
                            PROJECTS_DIR / proj_id,
                            f"agent: {(t_row['title'] or task_id)[:60]} (auto-applied)",
                        )
                except Exception as _exc:
                    log.warning("Auto-approve git commit failed: %s", _exc)

        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            err = "Agent run timed out after 600 seconds. The task may be too large — try narrowing the scope."
            with get_conn() as conn:
                conn.execute(
                    "UPDATE agent_runs SET status='failed', finished=?, log=? WHERE id=?",
                    (_now(), err, run_id),
                )
                conn.execute(
                    "INSERT INTO agent_task_messages (id, task_id, role, content, timestamp) VALUES (?,?,?,?,?)",
                    (str(uuid.uuid4()), task_id, "system", f"ERROR: {err}", _now()),
                )
                conn.execute(
                    "UPDATE agent_tasks SET status='draft', updated=? WHERE id=?",
                    (_now(), task_id),
                )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            with get_conn() as conn:
                conn.execute(
                    "UPDATE agent_runs SET status='failed', finished=?, log=? WHERE id=?",
                    (_now(), err[:2048], run_id),
                )
                conn.execute(
                    "INSERT INTO agent_task_messages (id, task_id, role, content, timestamp) VALUES (?,?,?,?,?)",
                    (str(uuid.uuid4()), task_id, "system", f"ERROR: {err}", _now()),
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
    # Revert any explicitly rejected paths to their before-snapshot content
    if data.reject_paths and data.decision in ("approved", "needs_changes"):
        with get_conn() as conn:
            run_row = conn.execute(
                "SELECT snapshot_before FROM agent_runs WHERE task_id=? ORDER BY started DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        if run_row and run_row["snapshot_before"]:
            before = json.loads(run_row["snapshot_before"])
            for rel_path in data.reject_paths:
                if rel_path in before:
                    # Restore to before content
                    abs_path = ROOT / rel_path
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    abs_path.write_text(before[rel_path], encoding="utf-8")
                elif (ROOT / rel_path).exists():
                    # File didn't exist before — delete it
                    (ROOT / rel_path).unlink()

    # Auto-commit project git history when task is approved
    if data.decision == "approved":
        proj_id = task.get("context_id") if task.get("context_type") == "project" else task.get("project_id")
        if proj_id:
            proj_dir = PROJECTS_DIR / proj_id
            title    = task.get("title", task_id)[:60]
            git_helper.git_commit(proj_dir, f"agent: {title} (approved)")

    return {"review_id": review_id, "task_id": task_id, "decision": data.decision, "status": new_status}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str):
    """Permanently delete a task and all its runs, messages, reviews, and artifacts."""
    _require_enabled()
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM agent_tasks WHERE id=?", (task_id,)).fetchone():
            raise HTTPException(404, f"Task {task_id!r} not found")
        conn.execute("DELETE FROM agent_task_messages WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM agent_reviews     WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM agent_artifacts   WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM agent_runs        WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM agent_tasks       WHERE id=?",      (task_id,))
    return {"status": "deleted", "task_id": task_id}


@router.post("/tasks/{task_id}/reset")
def reset_task(task_id: str):
    """Reset a stuck running task back to draft so it can be re-run."""
    _require_enabled()
    now = _now()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM agent_tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Task {task_id!r} not found")
        conn.execute(
            "UPDATE agent_tasks SET status='draft', updated=? WHERE id=?",
            (now, task_id),
        )
        conn.execute(
            "UPDATE agent_runs SET status='failed', finished=? WHERE task_id=? AND status='running'",
            (now, task_id),
        )
    return {"status": "reset", "task_id": task_id}


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
