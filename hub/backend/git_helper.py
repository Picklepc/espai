"""
Minimal git helper for per-project version control.
Silently no-ops when git is unavailable — the hub works without it.
"""
import glob
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME":     "ESPAI Hub",
    "GIT_AUTHOR_EMAIL":    "espai@local",
    "GIT_COMMITTER_NAME":  "ESPAI Hub",
    "GIT_COMMITTER_EMAIL": "espai@local",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS":         "echo",
}

_git_exe: str | None = None


def _find_git() -> str | None:
    global _git_exe
    if _git_exe:
        return _git_exe

    if found := shutil.which("git"):
        _git_exe = found
        return _git_exe

    home  = Path.home()
    local = home / "AppData" / "Local"
    candidates = [
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        "/usr/bin/git",
        "/usr/local/bin/git",
    ]
    # GitHub Desktop bundled git
    gh_pattern = str(local / "GitHubDesktop" / "app-*" / "resources" / "app" / "git" / "cmd" / "git.exe")
    candidates = sorted(glob.glob(gh_pattern), reverse=True) + candidates

    for c in candidates:
        if Path(c).exists():
            _git_exe = c
            return _git_exe

    return None


def _run(git: str, cwd: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [git, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=15,
        env=_GIT_ENV,
    )


def is_repo(proj_dir: Path) -> bool:
    """Returns True only if the project directory has its OWN .git folder."""
    return (proj_dir / ".git").is_dir()


def git_init(proj_dir: Path, initial_msg: str = "init: project scaffold") -> bool:
    """Init a git repo and make an initial commit. Returns True on success."""
    git = _find_git()
    if not git:
        return False
    try:
        _run(git, proj_dir, "init")
        _run(git, proj_dir, "add", ".")
        r = _run(git, proj_dir, "commit", "-m", initial_msg)
        ok = r.returncode == 0
        if not ok:
            log.debug("git init commit failed: %s", r.stderr[:200])
        return ok
    except Exception as exc:
        log.debug("git_init failed: %s", exc)
        return False


def git_commit(proj_dir: Path, message: str, paths: list[str] | None = None) -> bool:
    """Stage and commit. If paths is None stages everything. Returns True on success."""
    git = _find_git()
    if not git or not is_repo(proj_dir):
        return False
    try:
        if paths:
            for p in paths:
                _run(git, proj_dir, "add", "--", p)
        else:
            _run(git, proj_dir, "add", "-A")
        r = _run(git, proj_dir, "commit", "-m", message)
        # rc 1 with "nothing to commit" is not a real error
        if r.returncode not in (0, 1):
            log.debug("git commit failed: %s", r.stderr[:200])
            return False
        return "nothing to commit" not in r.stdout
    except Exception as exc:
        log.debug("git_commit failed: %s", exc)
        return False


def get_head_sha(proj_dir: Path) -> str | None:
    """Return the current HEAD commit SHA (full 40-char), or None if unavailable."""
    git = _find_git()
    if not git or not is_repo(proj_dir):
        return None
    try:
        r = _run(git, proj_dir, "rev-parse", "HEAD")
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def git_log_path(repo_dir: Path, path: str, limit: int = 20) -> list[dict]:
    """Return commits that touched a specific path within the repo."""
    git = _find_git()
    if not git or not is_repo(repo_dir):
        return []
    try:
        r = _run(git, repo_dir,
                 "log", f"--max-count={limit}",
                 "--pretty=format:%H\x1f%s\x1f%an\x1f%ai",
                 "--", path)
        if r.returncode != 0:
            return []
        commits = []
        for line in r.stdout.strip().splitlines():
            parts = line.split("\x1f", 3)
            if len(parts) == 4:
                commits.append({
                    "hash":      parts[0][:12],
                    "message":   parts[1],
                    "author":    parts[2],
                    "timestamp": parts[3].strip(),
                })
        return commits
    except Exception as exc:
        log.debug("git_log_path failed: %s", exc)
        return []


def git_checkout_path(repo_dir: Path, sha: str, path: str) -> dict:
    """Restore a specific path to its state at commit sha (non-destructive to other files)."""
    git = _find_git()
    if not git or not is_repo(repo_dir):
        return {"ok": False, "error": "Not a git repository"}
    if not re.match(r"^[0-9a-f]{4,40}$", sha):
        return {"ok": False, "error": "Invalid commit hash"}
    try:
        r = _run(git, repo_dir, "checkout", sha, "--", path)
        if r.returncode == 0:
            return {"ok": True, "sha": sha, "path": path}
        return {"ok": False, "error": (r.stderr or r.stdout).strip()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def git_rollback(proj_dir: Path, sha: str) -> dict:
    """Reset the working tree to the state at commit sha (git reset --hard). Returns ok/error."""
    git = _find_git()
    if not git or not is_repo(proj_dir):
        return {"ok": False, "error": "Not a git repository"}
    if not re.match(r"^[0-9a-f]{4,40}$", sha):
        return {"ok": False, "error": "Invalid commit hash"}
    try:
        r = _run(git, proj_dir, "reset", "--hard", sha)
        if r.returncode == 0:
            return {"ok": True, "sha": sha, "output": r.stdout.strip()}
        return {"ok": False, "error": (r.stderr or r.stdout).strip()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def git_log(proj_dir: Path, limit: int = 40) -> list[dict]:
    """Return last N commits as list of dicts."""
    git = _find_git()
    if not git or not is_repo(proj_dir):
        return []
    try:
        r = _run(git, proj_dir,
                 "log", f"--max-count={limit}",
                 "--pretty=format:%H\x1f%s\x1f%an\x1f%ai")
        if r.returncode != 0:
            return []
        commits = []
        for line in r.stdout.strip().splitlines():
            parts = line.split("\x1f", 3)
            if len(parts) == 4:
                commits.append({
                    "hash":      parts[0][:12],
                    "message":   parts[1],
                    "author":    parts[2],
                    "timestamp": parts[3].strip(),
                })
        return commits
    except Exception as exc:
        log.debug("git_log failed: %s", exc)
        return []
