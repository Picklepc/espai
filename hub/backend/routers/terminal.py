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
import subprocess
import sys
import threading
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


def _augmented_path() -> str:
    """Return PATH extended with common Windows tool install locations."""
    import glob as _glob
    home    = Path.home()
    appdata = Path(os.environ.get("APPDATA",      str(home / "AppData" / "Roaming")))
    local   = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    extra: list[str] = [str(appdata / "npm")]
    for pyver in ("Python313", "Python312", "Python311", "Python310", "Python39"):
        extra.append(str(appdata / "Python" / pyver / "Scripts"))
    gh_pat = str(local / "GitHubDesktop" / "app-*" / "resources" / "app" / "git" / "cmd")
    extra.extend(sorted(_glob.glob(gh_pat), reverse=True))
    extra += [
        r"C:\Program Files\Git\cmd",
        r"C:\Program Files (x86)\Git\cmd",
        r"C:\Program Files\Docker\Docker\resources\bin",
        r"C:\Program Files\nodejs",
    ]
    return os.pathsep.join([os.environ.get("PATH", "")] + extra)


def _spawn_pty(command: list[str], cwd: str, rows: int = 24, cols: int = 220):
    env = dict(os.environ)
    # Augment PATH so pip-user-installed tools (pio, claude, etc.) are found
    env["PATH"] = _augmented_path()
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

# Temp files — cleaned up when session closes
_prompt_files: dict[str, Path] = {}   # session_id → prompt temp file
_output_files: dict[str, Path] = {}   # session_id → streaming output log

# Agent task metadata — used to update task/run status when the PTY exits
# Only populated for sessions NOT using the streaming-thread approach.
_agent_session_meta: dict[str, dict] = {}   # session_id → {task_id, run_id, allowed_paths}


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


def _finish_agent_session(meta: dict) -> None:
    """Called (in a thread) when an agent PTY session exits. Updates task and run status."""
    from ..db import get_conn
    from ..routers.agent_bench import _snapshot_paths
    now = datetime.now(timezone.utc).isoformat()
    try:
        snapshot_after = _snapshot_paths(meta["allowed_paths"])
    except Exception:
        snapshot_after = {}
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_runs SET status='completed', finished=?, snapshot_after=? WHERE id=?",
            (now, json.dumps(snapshot_after), meta["run_id"]),
        )
        conn.execute(
            "UPDATE agent_tasks SET status='awaiting_review', updated=? WHERE id=?",
            (now, meta["task_id"]),
        )
        conn.execute(
            "INSERT INTO agent_task_messages (id, task_id, role, content, timestamp) VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), meta["task_id"], "system",
             "Terminal agent session finished — review the changes and approve or request revisions.",
             now),
        )


def _run_agent_stream(
    sid: str,
    prompt: str,
    cli_bin: str,
    out_file: Path,
    task_id: str,
    run_id: str,
    allowed_paths: list,
) -> None:
    """
    Background thread: run claude via subprocess.communicate() (captures all
    output at once — Node.js buffers stdout on pipes so line-by-line reads block
    until the process exits anyway).  A heartbeat thread writes a progress line
    every 15 s so the user can confirm it's alive via Get-Content -Wait.
    DB is updated here; _finish_agent_session is NOT used for these sessions.
    """
    import time
    from ..db import get_conn
    from ..routers.agent_bench import _snapshot_paths, _extra_tool_dirs

    cli_env = {**os.environ}
    cli_env["PATH"]     = os.pathsep.join([cli_env.get("PATH", "")] + _extra_tool_dirs())
    cli_env["CI"]       = "true"   # suppress interactive prompts in many CLIs
    cli_env["NO_COLOR"] = "1"      # disable ANSI codes that may confuse pipe reads
    cli_env["TERM"]     = "dumb"   # tell node it is not a TTY so it won't wait for input

    # Write immediate confirmation so Get-Content -Wait has something to show
    def _log(msg: str) -> None:
        try:
            with open(out_file, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass

    _log("[Claude started — waiting for output (Node buffers stdout; full output appears when done)]")

    # Heartbeat so the user can see it's alive
    stop_hb = threading.Event()
    start_ts = time.time()

    def _heartbeat() -> None:
        while not stop_hb.wait(15):
            elapsed = int(time.time() - start_ts)
            _log(f"[Still running... {elapsed}s elapsed]")

    threading.Thread(target=_heartbeat, daemon=True).start()

    exit_ok = False
    stdout_text = ""
    try:
        proc = subprocess.Popen(
            [cli_bin, "--verbose", "--print"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
            env=cli_env,
        )
        stdout_text, _ = proc.communicate(input=prompt, timeout=600)
        exit_ok = proc.returncode == 0

    except subprocess.TimeoutExpired:
        proc.kill()
        _log("\n[Timed out after 600 s — task may be too large]\n")
    except Exception as exc:
        _log(f"\n[Error launching claude: {exc}]\n")
    finally:
        stop_hb.set()

    # Dump all output now that the process finished
    if stdout_text:
        _log("\n--- Claude output ---")
        _log(stdout_text)

    # Write visible completion marker
    marker = (
        "=== Agent finished — go back to Agent Bench to review changes ==="
        if exit_ok else
        "=== Agent exited with an error — see output above ==="
    )
    _log(marker)

    # Update DB
    now = datetime.now(timezone.utc).isoformat()
    try:
        snapshot_after = _snapshot_paths(allowed_paths)
    except Exception:
        snapshot_after = {}
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE agent_runs SET status=?, finished=?, snapshot_after=? WHERE id=?",
                ("completed" if exit_ok else "failed", now, json.dumps(snapshot_after), run_id),
            )
            conn.execute(
                "UPDATE agent_tasks SET status='awaiting_review', updated=? WHERE id=?",
                (now, task_id),
            )
            conn.execute(
                "INSERT INTO agent_task_messages (id, task_id, role, content, timestamp) VALUES (?,?,?,?,?)",
                (str(uuid.uuid4()), task_id, "system",
                 "Agent run complete — review changes and approve or request revisions.", now),
            )
    except Exception:
        pass

    # Temp-file cleanup (prompt file cleaned up by close_session)
    _output_files.pop(sid, None)


# ── REST endpoints ────────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    title:        Optional[str]       = None
    command:      Optional[list[str]] = None   # None → default shell
    cwd:          Optional[str]       = None
    project_id:   Optional[str]       = None   # resolved to PROJECTS_DIR/id server-side
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
    from ..config import PROJECTS_DIR
    command = data.command or _default_shell()
    # Resolve cwd: explicit path > project_id lookup > ROOT fallback
    if data.cwd:
        cwd = data.cwd
    elif data.project_id:
        proj_dir = PROJECTS_DIR / data.project_id
        cwd = str(proj_dir) if proj_dir.exists() else str(ROOT)
    else:
        cwd = str(ROOT)
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
    _agent_session_meta.pop(session_id, None)
    of = _output_files.pop(session_id, None)
    if of and of.exists():
        try:
            of.unlink()
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
    Open an interactive Claude Code session pre-loaded with task context.

    Architecture: the hub writes the full task brief to a temp file, starts
    claude in interactive (REPL) mode inside the PTY, then injects a short
    trigger message that tells claude to read the brief and begin.  The user
    sees every tool call in real time, can type follow-up messages, and asks
    claude to commit when satisfied.  The session stays interactive so the
    developer controls the whole conversation — exactly like VS Code chat.
    """
    if not pty_available():
        raise HTTPException(503, "No PTY backend available.")

    # ── Fetch task and build prompt ──────────────────────────────────────────
    from ..db import get_conn
    from ..routers.agent_bench import _build_prompt, _snapshot_paths
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM agent_tasks WHERE id=?", (data.task_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Task {data.task_id!r} not found")
    task = dict(row)
    if task["status"] not in ("draft", "needs_changes"):
        raise HTTPException(400, f"Task is '{task['status']}' — only draft or needs_changes tasks can be run")

    project = None
    if task.get("project_id"):
        with get_conn() as conn:
            p = conn.execute("SELECT * FROM projects WHERE id=?", (task["project_id"],)).fetchone()
        project = dict(p) if p else None

    prompt = _build_prompt(task, project)

    # ── Write task brief to a temp file — no shell-quoting of prompt content ─
    import tempfile
    tf = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False,
        encoding="utf-8", prefix="espai_task_"
    )
    tf.write(prompt)
    tf.flush()
    tf.close()
    prompt_path = Path(tf.name)

    # ── Find CLI binary ───────────────────────────────────────────────────────
    from ..routers.agent_bench import _extra_tool_dirs
    augmented = os.pathsep.join([os.environ.get("PATH", "")] + _extra_tool_dirs())
    cli_name  = "claude" if "claude" in data.adapter_id else "codex"
    cli_bin   = shutil.which(cli_name, path=augmented) or cli_name

    title = task.get("title", "Agent Task")
    cwd   = data.cwd or str(ROOT)

    # ── Build init commands ───────────────────────────────────────────────────
    # Start the interactive claude REPL.  A trigger message is injected via PTY
    # ~6 s later (see _send_init in the WebSocket handler) once the REPL is ready.
    safe_title = title.replace("'", "''")
    cbin = str(cli_bin)

    if sys.platform == "win32":
        header = (
            f"Write-Host '=== {safe_title} ===' -ForegroundColor Cyan; "
            f"Write-Host 'Task brief will be sent once Claude is ready.' -ForegroundColor Yellow; "
            f"Write-Host 'First run? Log in when prompted then press Enter.' -ForegroundColor DarkGray"
        )
        start_claude = f"& '{cbin}'"
        init_cmds = [header, start_claude]
    else:
        header = (
            f"echo '=== {safe_title} ==='; "
            f"echo 'Task brief will be sent once Claude is ready. First run: log in then press Enter.'"
        )
        start_claude = f"'{cbin}'"
        init_cmds = [header, start_claude]

    # Trigger message injected into Claude's REPL once it shows its prompt.
    # Wraps the task brief path in a single message so Claude reads and executes it.
    trigger_msg = (
        f"Please read the task brief at '{prompt_path}' and complete it. "
        f"Show me what you're doing as you work. "
        f"When finished, run git commit with a descriptive message. "
        f"Ask me if anything is unclear."
    )

    # ── Spawn PTY ────────────────────────────────────────────────────────────
    try:
        pty = _spawn_pty(_default_shell(), cwd=cwd)
    except Exception as exc:
        prompt_path.unlink(missing_ok=True)
        raise HTTPException(500, f"PTY spawn failed: {exc}")

    sid     = str(uuid.uuid4())
    session = _Session(sid, pty, _default_shell(), title)
    session._init_cmds = init_cmds
    _sessions[sid]     = session
    _prompt_files[sid] = prompt_path

    # ── Create agent_run record and set task to "running" ─────────────────────
    allowed         = json.loads(task.get("allowed_paths") or "[]")
    snapshot_before = _snapshot_paths(allowed)
    run_id          = str(uuid.uuid4())
    now             = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agent_runs (id, task_id, adapter_id, status, started, snapshot_before) VALUES (?,?,?,?,?,?)",
            (run_id, data.task_id, data.adapter_id, "running", now, json.dumps(snapshot_before)),
        )
        conn.execute(
            "UPDATE agent_tasks SET status='running', updated=? WHERE id=?",
            (now, data.task_id),
        )
        conn.execute(
            "INSERT INTO agent_task_messages (id, task_id, role, content, timestamp) VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), data.task_id, "system",
             f"[{data.adapter_id}] Interactive session started — using {cli_bin}", now),
        )

    # Store meta so _finish_agent_session updates DB when the PTY closes,
    # and so _send_init can inject the trigger message.
    _agent_session_meta[sid] = {
        "task_id":      data.task_id,
        "run_id":       run_id,
        "allowed_paths": allowed,
        "trigger_msg":  trigger_msg,
    }

    return {"id": sid, "title": title}


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

    # Send init commands shortly after the shell is ready, then inject the
    # agent trigger message (if any) once the claude REPL has had time to start.
    async def _send_init():
        nl = "\r\n" if sys.platform == "win32" else "\n"
        await asyncio.sleep(0.6)
        for cmd in session._init_cmds:
            if done.is_set():
                break
            try:
                session.pty.write(cmd + nl)
                await asyncio.sleep(0.25)
            except Exception:
                pass

        # For interactive agent sessions, inject the trigger message only once
        # Claude's REPL prompt is visible in the output stream.
        # We watch the output buffer for Claude's "> " prompt rather than using
        # a fixed sleep, so injection works regardless of startup speed.
        meta = _agent_session_meta.get(session_id)
        trigger = meta.get("trigger_msg") if meta else None
        if trigger and not done.is_set():
            # Poll the output buffer until we see Claude's prompt character,
            # or fall back after 30 s (in case the prompt detection misses).
            _claude_ready = asyncio.Event()
            meta["_claude_ready"] = _claude_ready
            try:
                await asyncio.wait_for(_claude_ready.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
            if not done.is_set():
                try:
                    session.pty.write(trigger)
                    await asyncio.sleep(0.1)
                    session.pty.write(nl)
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
                # Signal when Claude's REPL prompt is visible so the trigger
                # message is injected at the right moment instead of a fixed delay.
                meta = _agent_session_meta.get(session_id)
                if meta and "_claude_ready" in meta and not meta["_claude_ready"].is_set():
                    # Claude's interactive prompt starts with "> " or "? "
                    if "> " in data or "\n> " in data or data.strip().endswith(">"):
                        meta["_claude_ready"].set()
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
        # Update agent task/run status if this was an agent session
        meta = _agent_session_meta.pop(session_id, None)
        if meta:
            await loop.run_in_executor(None, _finish_agent_session, meta)
