"""
Shared registry item file operations.

Workers, cards, and recipes all live in `{base_dir}/{item_folder}/` with
a descriptor YAML (worker.yaml, card.yaml, recipe.yaml) and optional
support files (main.py, requirements.txt, preview.html, etc.).

This module provides safe path resolution and CRUD helpers used by the
workers, cards, and recipes routers.
"""
import os
import re
import shutil
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

_MAX_READ  = 512 * 1024       # 512 KB — larger files won't load comfortably in CodeMirror
_MAX_WRITE = 1 * 1024 * 1024  # 1 MB write cap
_BLOCKED   = (".env", "secrets", ".private")
_SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,62}$")


class FileWrite(BaseModel):
    content: str


class NewItemRequest(BaseModel):
    name: str          # display name, e.g. "My Sensor Worker"
    slug: str          # folder/identifier, e.g. "my-sensor-worker"
    category: str = "general"
    description: str = ""


def _safe_under(child: Path, parent: Path) -> bool:
    """
    Return True if child is equal to or under parent.

    Uses case-insensitive string comparison so this works correctly on Windows
    and OneDrive where Path.resolve() can produce inconsistent drive-letter
    casing (e.g. C:\\ vs c:\\), causing Path.relative_to() to raise ValueError
    even for perfectly valid paths.
    """
    parent_s = str(parent).lower().rstrip("/\\")
    child_s  = str(child).lower()
    return child_s == parent_s or child_s.startswith(parent_s + os.sep.lower())


def _item_dir(base_dir: Path, folder: str) -> Path:
    """Return the item directory, raising 404 if it doesn't exist."""
    resolved_base = base_dir.resolve()
    d = (base_dir / folder).resolve()
    if not _safe_under(d, resolved_base):
        raise HTTPException(403, "Path traversal not allowed")
    if not d.exists():
        raise HTTPException(404, f"Item folder {folder!r} not found")
    return d


def _resolve(base_dir: Path, folder: str, file_path: str) -> tuple[Path, Path]:
    """Resolve a registry-relative file path. Returns (item_dir, target)."""
    item_dir = _item_dir(base_dir, folder)
    target   = (item_dir / file_path).resolve()
    if not _safe_under(target, item_dir):
        raise HTTPException(403, "Path traversal not allowed")
    lower = file_path.lower()
    if any(p in lower for p in _BLOCKED):
        raise HTTPException(403, f"Access to {file_path!r} is blocked")
    return item_dir, target


def list_files(base_dir: Path, folder: str) -> list[dict]:
    item_dir = _item_dir(base_dir, folder)
    files = []
    for f in sorted(item_dir.rglob("*")):
        if f.is_file():
            rel = f.relative_to(item_dir).as_posix()
            files.append({"path": rel, "size_bytes": f.stat().st_size})
    return {"folder": folder, "files": files}


def read_file(base_dir: Path, folder: str, file_path: str) -> dict:
    _, target = _resolve(base_dir, folder, file_path)
    if not target.exists():
        raise HTTPException(404, "File not found")
    if not target.is_file():
        raise HTTPException(400, "Not a file")
    size = target.stat().st_size
    if size > _MAX_READ:
        raise HTTPException(413, f"File is {size // 1024} KB — too large for in-hub editor (max 512 KB)")
    return {"path": file_path, "content": target.read_text(encoding="utf-8", errors="replace"), "size_bytes": size}


def write_file(base_dir: Path, folder: str, file_path: str, body: FileWrite) -> dict:
    _, target = _resolve(base_dir, folder, file_path)
    encoded = body.content.encode("utf-8")
    if len(encoded) > _MAX_WRITE:
        raise HTTPException(413, "Content exceeds 1 MB write limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")
    return {"path": file_path, "size_bytes": len(encoded), "saved": True}


def create_file(base_dir: Path, folder: str, file_path: str, body: FileWrite) -> dict:
    _, target = _resolve(base_dir, folder, file_path)
    if target.exists():
        raise HTTPException(409, f"{file_path!r} already exists — use PUT to overwrite")
    encoded = body.content.encode("utf-8")
    if len(encoded) > _MAX_WRITE:
        raise HTTPException(413, "Content exceeds 1 MB write limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")
    return {"path": file_path, "size_bytes": len(encoded), "created": True}


def delete_file(base_dir: Path, folder: str, file_path: str) -> dict:
    _, target = _resolve(base_dir, folder, file_path)
    if not target.exists():
        raise HTTPException(404, "File not found")
    if not target.is_file():
        raise HTTPException(400, "Not a file")
    target.unlink()
    return {"path": file_path, "deleted": True}


def delete_item(base_dir: Path, folder: str) -> dict:
    item_dir = _item_dir(base_dir, folder)
    shutil.rmtree(item_dir)
    return {"folder": folder, "deleted": True}


# ── Scaffold generators ──────────────────────────────────────────────────────

def scaffold_worker(base_dir: Path, req: NewItemRequest) -> dict:
    if not _SAFE_SLUG.match(req.slug):
        raise HTTPException(400, "Slug must be lowercase letters, digits, hyphens, or underscores (max 63 chars)")
    folder = base_dir / req.slug
    if folder.exists():
        raise HTTPException(409, f"Worker {req.slug!r} already exists")
    folder.mkdir(parents=True)

    (folder / "worker.yaml").write_text(f"""\
schema: ESPAI.worker.v1
name: {req.slug}
display_name: "{req.name}"
description: "{req.description}"
runtime: python
category: {req.category}
inputs: []
outputs: []
permissions:
  filesystem: project-media-only
  network: none
  secrets: none
resource_cost:
  cpu: low
  memory: low
  disk: low
  realtime_safe: false
sandbox:
  preferred: docker
  native_allowed: true
entrypoint: main.py
requirements: requirements.txt
enabled: true
""", encoding="utf-8")

    (folder / "main.py").write_text(f'''\
"""
{req.name} — ESPAI Worker

Inputs (via ESPAI_INPUTS JSON):
  project_id  - str   required: project this worker belongs to
  # TODO: document your inputs here
  # image_file_id - str  optional: set to a project_media file_id;
  #   the runner sets ESPAI_MEDIA_PATH_IMAGE to the local file path

Environment variables provided by the runner:
  ESPAI_JOB_ID         - current job ID
  ESPAI_INPUTS         - JSON-encoded inputs dict
  ESPAI_HUB_URL        - hub base URL (e.g. http://localhost:7888)
  ESPAI_MEDIA_DIR      - local path to hub media storage root
  ESPAI_MEDIA_PATH_*   - resolved local path for any *_file_id input

Outputs (JSON to stdout):
  ok     - bool
  events - list of ESPAI events to emit  [{{"type":"...","data":{{...}}}}]
  error  - set on failure
"""
import json
import os
import sys


def run(inputs: dict) -> dict:
    # TODO: implement worker logic
    return {{
        "ok": True,
        "events": [],
    }}


if __name__ == "__main__":
    raw = os.environ.get("ESPAI_INPUTS", "{{}}")
    try:
        inputs = json.loads(raw)
    except json.JSONDecodeError:
        inputs = {{}}
    result = run(inputs)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("ok") else 1)
''', encoding="utf-8")

    (folder / "requirements.txt").write_text("# Add pip dependencies here\n", encoding="utf-8")
    return {"slug": req.slug, "folder": str(folder), "created": True}


def scaffold_card(base_dir: Path, req: NewItemRequest) -> dict:
    if not _SAFE_SLUG.match(req.slug):
        raise HTTPException(400, "Slug must be lowercase letters, digits, hyphens, or underscores")
    folder = base_dir / req.slug
    if folder.exists():
        raise HTTPException(409, f"Card {req.slug!r} already exists")
    folder.mkdir(parents=True)

    (folder / "card.yaml").write_text(f"""\
schema: ESPAI.card.v1
name: {req.slug}
display_name: "{req.name}"
category: {req.category}
description: "{req.description}"

event_source:
  type: hub_data_store          # reads from /api/projects/{{id}}/data/latest
  polling_interval_ms: 5000

config:
  fields:
    - key: value
      label: Value
      unit: ""
      sparkline: false

compatible_boards:
  - esp32
  - esp32s3

share_policy:
  export_public: false
""", encoding="utf-8")

    return {"slug": req.slug, "folder": str(folder), "created": True}


def scaffold_recipe(base_dir: Path, req: NewItemRequest) -> dict:
    if not _SAFE_SLUG.match(req.slug):
        raise HTTPException(400, "Slug must be lowercase letters, digits, hyphens, or underscores")
    folder = base_dir / req.slug
    if folder.exists():
        raise HTTPException(409, f"Recipe {req.slug!r} already exists")
    folder.mkdir(parents=True)

    (folder / "recipe.yaml").write_text(f"""\
schema: ESPAI.recipe.v1
name: {req.name}
category: {req.category}
summary: "{req.description}"

compatibility:
  compatible_boards:
    - esp32
    - esp32s3
    - esp32c3

requires_workers: []

pipeline: []

config: {{}}

share_policy:
  export_public: false
""", encoding="utf-8")

    return {"slug": req.slug, "folder": str(folder), "created": True}
