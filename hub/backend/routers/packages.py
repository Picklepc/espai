"""
Worker Package Manager

Aggregates dependency declarations from installed worker.yaml files, proxies
PyPI package lookups, and manages pip install / uninstall at runtime.

Build-type awareness:
  source  — pip installs go into the running Python environment (dev venv)
  docker  — pip installs go into the container layer (ephemeral unless committed)
  frozen  — pip cannot install into a bundled exe; use the Docker workers image

System deps (ffmpeg, etc.) are shown with detected install status and
install hints but are NEVER managed by ESPAI — they are OS-level packages
that may be shared with other applications.
"""
import importlib.metadata
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import WORKERS_DIR

router = APIRouter()

_SAFE_NAME = re.compile(r'^[a-zA-Z0-9_\-\.]+$')


# ── Build-type detection ───────────────────────────────────────────────────────

def _build_type() -> str:
    import os
    if getattr(sys, "frozen", False):
        return "frozen"
    if Path("/.dockerenv").exists() or "DOCKER_ENV" in os.environ:
        return "docker"
    return "source"


# ── Dependency scanning ────────────────────────────────────────────────────────

def _pkg_version(import_name: str, pip_name: str) -> Optional[str]:
    try:
        return importlib.metadata.version(pip_name)
    except importlib.metadata.PackageNotFoundError:
        pass
    if importlib.util.find_spec(import_name):
        return "installed"
    return None


def _collect_declared() -> tuple[dict, dict]:
    python: dict[str, dict] = {}
    system: dict[str, dict] = {}

    for yf in sorted(WORKERS_DIR.glob("*/worker.yaml")):
        try:
            w = yaml.safe_load(yf.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        label = w.get("display_name") or w.get("name") or yf.parent.name

        for dep in w.get("python_deps", []):
            n = dep.get("name", "")
            if not n:
                continue
            if n not in python:
                python[n] = {
                    "name":    n,
                    "type":    "python",
                    "import":  dep.get("import", n.replace("-", "_").split(".")[0]),
                    "version": dep.get("version", ""),
                    "note":    dep.get("note", ""),
                    "workers": [],
                }
            python[n]["workers"].append(label)

        for dep in w.get("system_deps", []):
            cmd = dep.get("command") or dep.get("name", "")
            if not cmd:
                continue
            if cmd not in system:
                system[cmd] = {
                    "name":         dep.get("name", cmd),
                    "type":         "system",
                    "command":      cmd,
                    "note":         dep.get("note", ""),
                    "shared_risk":  dep.get("shared_risk", "low"),
                    "install_hint": dep.get("install_hint", ""),
                    "workers":      [],
                }
            system[cmd]["workers"].append(label)

    return python, system


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/")
def list_deps():
    """All deps declared by installed workers, with install status and build metadata."""
    bt = _build_type()
    py_decl, sys_decl = _collect_declared()

    python_rows = []
    for dep in py_decl.values():
        ver = _pkg_version(dep["import"], dep["name"])
        python_rows.append({
            **dep,
            "installed":         ver is not None,
            "version_installed": ver,
            "can_manage":        bt in ("source", "docker"),
        })

    system_rows = []
    for dep in sys_decl.values():
        found = shutil.which(dep["command"])
        ver_str = None
        if found:
            try:
                r = subprocess.run(
                    [dep["command"], "-version"],
                    capture_output=True, text=True, timeout=3,
                )
                ver_str = (r.stdout or r.stderr).strip().splitlines()[0][:120]
            except Exception:
                ver_str = "installed"
        system_rows.append({
            **dep,
            "installed":         found is not None,
            "version_installed": ver_str,
            # System packages are never managed by ESPAI — they may be shared
            # with other applications on the host.
            "managed_by_espai":  False,
        })

    return {
        "build_type":  bt,
        "can_install": bt in ("source", "docker"),
        "python":      python_rows,
        "system":      system_rows,
    }


@router.get("/installed")
def list_installed():
    """Full list of pip-installed Python packages (name + version)."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json"],
            capture_output=True, text=True, timeout=30,
        )
        pkgs = json.loads(r.stdout) if r.returncode == 0 else []
    except Exception:
        pkgs = []
    return {"packages": pkgs, "build_type": _build_type()}


class SearchBody(BaseModel):
    name: str

@router.post("/search")
def search_pypi(body: SearchBody):
    """
    Look up a package by name on PyPI.  Returns package info, latest version,
    and the 10 most recent release versions if found.
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Package name required")
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ESPAI-hub/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"found": False, "name": name}
        raise HTTPException(502, f"PyPI returned {exc.code}")
    except Exception as exc:
        raise HTTPException(502, f"PyPI unreachable: {exc}")

    info = data.get("info", {})
    versions = sorted(data.get("releases", {}).keys(), reverse=True)[:10]
    return {
        "found":           True,
        "name":            info.get("name"),
        "version":         info.get("version"),
        "summary":         info.get("summary", ""),
        "home_page":       info.get("home_page") or info.get("project_url") or "",
        "license":         info.get("license", ""),
        "requires_python": info.get("requires_python", ""),
        "versions":        versions,
    }


class InstallBody(BaseModel):
    name: str
    version: str = ""

@router.post("/install")
def install_package(body: InstallBody):
    """pip install a Python package. Blocked for frozen/bundled builds."""
    bt = _build_type()
    if bt == "frozen":
        raise HTTPException(400,
            "Cannot pip install into a bundled build.  "
            "Switch to the Docker :workers image or run from source.")

    name = body.name.strip()
    if not name or not _SAFE_NAME.match(name):
        raise HTTPException(400, "Invalid package name")

    spec = f"{name}{body.version}" if body.version else name
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", spec],
            capture_output=True, text=True, timeout=120,
        )
    except Exception as exc:
        raise HTTPException(500, str(exc))

    if r.returncode != 0:
        raise HTTPException(400, r.stderr.strip() or "pip install failed")

    return {"ok": True, "output": r.stdout.strip()}


@router.delete("/{name}")
def remove_package(name: str):
    """pip uninstall a Python package.  Never removes system packages."""
    if _build_type() == "frozen":
        raise HTTPException(400, "Cannot remove packages from a bundled build.")
    if not _SAFE_NAME.match(name):
        raise HTTPException(400, "Invalid package name")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "-y", name],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if r.returncode != 0:
        raise HTTPException(400, r.stderr.strip() or "pip uninstall failed")
    return {"ok": True, "output": r.stdout.strip()}
