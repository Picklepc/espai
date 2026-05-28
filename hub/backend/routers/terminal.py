"""
ESPAI Hub — Browser Terminal

Provides persistent PTY sessions over WebSocket so the dashboard can
host a full interactive terminal. Each session is a real shell process
with a PTY (colors, interactive CLIs, cursor movement all work).

Windows  : pywinpty  (ConPTY, Windows 10 1903+)
Linux/Mac: ptyprocess

Message protocol (JSON over WebSocket):
  Client → Server:
    {"type": "input",  "data": "<keystrokes>"}
    {"type": "resize", "cols": 80, "rows": 24}
    {"type": "ping"}
  Server → Client:
    {"type": "output", "data": "<terminal bytes as text>"}
    {"type": "exit",   "data": "[Session ended]"}
    {"type": "error",  "data": "<message>"}
    {"type": "pong"}
"""
import asyncio
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

from ..config import ROOT

router = APIRouter()

# ── PTY backend ───────────────────────────────────────────────────────────────

_PTY_BACKEND: Optional[str] = None

if sys.platform == "win32":
    try:
        from winpty import PtyProcess as _WinPty  # pywinpty >= 2.0
        _PTY_BACKEND = "winpty"
    except ImportError:
        _WinPty = None
else:
    try:
        from ptyprocess import PtyProcessUnicode as _UnixPty
        _PTY_BACKEND = "ptyprocess"
    except ImportError:
        _UnixPty = None


def pty_available() -> bool:
    return _PTY_BACKEND is not None


def _default_shell() -> list[str]:
    if sys.platform == "win32":
        for cmd in ("pwsh.exe", "powershell.exe", "cmd.exe"):
            if shutil.which(cmd):
                return [cmd]
        return ["cmd.exe"]
    shell = os.environ.get("SHELL", "/bin/bash")
    return [shell]


def _spawn_pty(command: list[str], cwd: str, rows: int = 24, cols: int = 220):
    env = dict(os.environ)
    # Force color output where possible
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("COLORTERM", "truecolor")
    if _PTY_BACKEND == "winpty":
        return _WinPty.spawn(command, cwd=cwd, env=env, dimensions=(rows, cols))
    elif _PTY_BACKEND == "ptyprocess":
        return _UnixPty.spawn(command, cwd=cwd, env=env, dimensions=(rows, cols))
    raise RuntimeError("No PTY backend available. Install pywinpty (Windows) or ptyprocess (Linux/macOS).")


# ── Session store ─────────────────────────────────────────────────────────────

class _Session:
    def __init__(self, session_id: str, pty, command: list[str], title: str):
        self.id       = session_id
        self.pty      = pty
        self.command  = command
        self.title    = title
        self.created  = datetime.now(timezone.utc).isoformat()
        self.connected = False
        self._init_cmds: list[str] = []   # sent once after shell is ready


_sessions: dict[str, _Session] = {}

# Temp prompt files — cleaned up when session closes
_prompt_files: dict[str, Path] = {}   # session_id → temp file path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_read(pty, nbytes: int = 4096) -> Optional[str]:
    """Blocking read that returns None when the PTY closes."""
    try:
        data = pty.read(nbytes)
        return data if data else None
    except (EOFError, OSError):
        return None
    except Exception:
        return None


# ── REST endpoints ────────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    title:        Optional[str]       = None
    command:      Optional[list[str]] = None   # None → default shell
    cwd:          Optional[str]       = None
    init_cmds:    list[str]           = []     # run after shell starts


@router.get("/available")
def terminal_available():
    return {
        "available": pty_available(),
        "backend":   _PTY_BACKEND,
        "platform":  sys.platform,
        "shell":     _default_shell() if pty_available() else None,
    }


@router.get("/sessions")
def list_sessions():
    return [
        {
            "id":        s.id,
            "title":     s.title,
            "command":   s.command,
            "created":   s.created,
            "connected": s.connected,
        }
        for s in _sessions.values()
    ]


@router.post("/sessions")
def create_session(data: SessionCreate):
    if not pty_available():
        raise HTTPException(
            503,
            "No PTY backend. "
            "Install pywinpty on Windows or ptyprocess on Linux/macOS, "
            "then restart the hub.",
        )
    command = data.command or _default_shell()
    cwd     = data.cwd or str(ROOT)
    title   = data.title or Path(command[0]).stem.replace(".exe", "")

    try:
        pty = _spawn_pty(command, cwd=cwd)
    except Exception as exc:
        raise HTTPException(500, f"PTY spawn failed: {exc}")

    sid     = str(uuid.uuid4())
    session = _Session(sid, pty, command, title)
    session._init_cmds = data.init_cmds
    _sessions[sid] = session
    return {"id": sid, "title": title}


@router.delete("/sessions/{session_id}")
def close_session(session_id: str):
    session = _sessions.pop(session_id, None)
    if not session:
        raise HTTPException(404, "Session not found")
    try:
        session.pty.close()
    except Exception:
        pass
    # Clean up temp prompt file if one was created for this session
    pf = _prompt_files.pop(session_id, None)
    if pf and pf.exists():
        try:
            pf.unlink()
        except Exception:
            pass
    return {"status": "closed"}


class AgentSessionCreate(BaseModel):
    task_id:    str
    adapter_id: str = "claude-code-cli"
    cwd:        Optional[str] = None


@router.post("/sessions/agent")
def create_agent_session(data: AgentSessionCreate):
    """
    Create a terminal session pre-loaded to run an agent task.

    Writes the task prompt to a temp file (avoids all shell-quoting issues),
    then opens a shell with init commands that pipe the file to the CLI adapter.
    The user sees a real interactive terminal and can watch/respond as the
    agent works.
    """
    if not pty_available():
        raise HTTPException(503, "No PTY backend available.")

    # ── Fetch task and build prompt ──────────────────────────────────────────
    from ..db import get_conn
    from ..routers.agent_bench import _build_prompt
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM agent_tasks WHERE id=?", (data.task_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Task {data.task_id!r} not found")
    task = dict(row)

    project = None
    if task.get("project_id"):
        with get_conn() as conn:
            p = conn.execute("SELECT * FROM projects WHERE id=?", (task["project_id"],)).fetchone()
        project = dict(p) if p else None

    prompt = _build_prompt(task, project)

    # ── Write prompt to temp file ─────────────────────────────────────────────
    import tempfile
    tf = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False,
        encoding="utf-8", prefix="espai_task_"
    )
    tf.write(prompt)
    tf.flush()
    tf.close()
    prompt_path = Path(tf.name)

    # ── Build adapter CLI command ─────────────────────────────────────────────
    from ..routers.agent_bench import _extra_tool_dirs
    augmented = os.pathsep.join([os.environ.get("PATH", "")] + _extra_tool_dirs())
    cli_name  = "claude" if "claude" in data.adapter_id else "codex"
    cli_bin   = shutil.which(cli_name, path=augmented) or cli_name

    # ── Build shell-safe init commands ───────────────────────────────────────
    # All path quoting stays inside this function — no prompt text in shell args.
    title = task.get("title", "Agent Task")
    cwd   = data.cwd or str(ROOT)

    if sys.platform == "win32":
        ppath = str(prompt_path).replace("\\", "\\\\")
        cbin  = cli_bin.replace("\\", "\\\\")
        init_cmds = [
            f'Write-Host "=== {title.replace(chr(34), chr(39))} ===" -ForegroundColor Cyan',
            f'Write-Host "Adapter: {data.adapter_id}  |  Prompt: {ppath}" -ForegroundColor DarkGray',
            f'Write-Host "Starting..." -ForegroundColor Yellow',
            f'Get-Content -Path \'{str(prompt_path)}\' -Raw | & \'{cbin}\' --dangerously-skip-permissions',
        ]
    else:
        init_cmds = [
            f'echo "=== {title} ==="',
            f'echo "Prompt file: {prompt_path}"',
            f'"{cli_bin}" --dangerously-skip-permissions < "{prompt_path}"',
        ]

    # ── Spawn PTY ────────────────────────────────────────────────────────────
    try:
        pty = _spawn_pty(_default_shell(), cwd=cwd)
    except Exception as exc:
        prompt_path.unlink(missing_ok=True)
        raise HTTPException(500, f"PTY spawn failed: {exc}")

    sid     = str(uuid.uuid4())
    session = _Session(sid, pty, _default_shell(), title)
    session._init_cmds = init_cmds
    _sessions[sid]      = session
    _prompt_files[sid]  = prompt_path

    return {"id": sid, "title": title, "prompt_path": str(prompt_path)}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws/{session_id}")
async def terminal_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()

    session = _sessions.get(session_id)
    if not session:
        await websocket.send_text(json.dumps({"type": "error", "data": "Session not found\r\n"}))
        await websocket.close()
        return

    session.connected = True
    loop = asyncio.get_event_loop()
    done = asyncio.Event()

    # Send init commands shortly after the shell is ready
    async def _send_init():
        await asyncio.sleep(0.4)
        for cmd in session._init_cmds:
            if done.is_set():
                break
            try:
                session.pty.write(cmd + ("\r\n" if sys.platform == "win32" else "\n"))
                await asyncio.sleep(0.08)
            except Exception:
                pass

    asyncio.create_task(_send_init())

    async def _pty_to_ws():
        while not done.is_set():
            try:
                data = await loop.run_in_executor(None, _safe_read, session.pty)
                if data is None:
                    done.set()
                    break
                await websocket.send_text(json.dumps({"type": "output", "data": data}))
            except Exception:
                done.set()
                break
        try:
            await websocket.send_text(
                json.dumps({"type": "exit", "data": "\r\n\x1b[2m[Session ended]\x1b[0m\r\n"})
            )
        except Exception:
            pass

    async def _ws_to_pty():
        while not done.is_set():
            try:
                raw = await websocket.receive_text()
                msg = json.loads(raw)
                t   = msg.get("type")
                if t == "input":
                    session.pty.write(msg["data"])
                elif t == "resize":
                    try:
                        session.pty.setwinsize(int(msg.get("rows", 24)), int(msg.get("cols", 80)))
                    except Exception:
                        pass
                elif t == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except WebSocketDisconnect:
                done.set()
                break
            except Exception:
                done.set()
                break

    try:
        await asyncio.gather(_pty_to_ws(), _ws_to_pty())
    finally:
        session.connected = False
        # Reap dead sessions automatically
        if not (session.pty.isalive() if hasattr(session.pty, "isalive") else True):
            _sessions.pop(session_id, None)
