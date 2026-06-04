"""
Caddy config generator — builds a Caddyfile that maps project slugs to their
hub-hosted web apps so they're reachable at {slug}.local without port numbers.

GET  /api/caddy/caddyfile   — return the generated config as plain text
GET  /api/caddy/download    — download as a file attachment
POST /api/caddy/write       — write the config to the path in ESPAI_CADDY_PATH
                               (default: data/Caddyfile; no-op if unset and path absent)
"""
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, FileResponse

from ..config import ROOT
from ..db import get_conn

router = APIRouter()

_CADDY_PATH_ENV = "ESPAI_CADDY_PATH"
_CADDY_DEFAULT  = ROOT / "data" / "Caddyfile"


def _hub_port() -> int:
    return int(os.environ.get("ESPAI_PORT", "7888"))


def _generate() -> str:
    port = _hub_port()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT slug, name, id FROM projects WHERE slug IS NOT NULL ORDER BY name"
        ).fetchall()

    lines = [
        "# ESPAI — auto-generated Caddyfile",
        f"# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "# Place at /etc/caddy/Caddyfile or run: caddy run --config /path/to/Caddyfile",
        "# Requires Caddy 2.x with the local-https adapter or a wildcard *.local DNS entry.",
        "#",
        "# Each block routes {slug}.local → the hub-hosted project web app.",
        "# The hub must also be reachable (espai.local or by IP) for the reverse proxy to work.",
        "",
    ]

    for row in rows:
        slug = row["slug"]
        name = row["name"]
        pid  = row["id"]
        lines += [
            f"# {name}",
            f"{slug}.local {{",
            f"    rewrite * /app/{slug}{{uri}}",
            f"    reverse_proxy localhost:{port}",
            f"}}",
            "",
        ]

    if not rows:
        lines += [
            "# No projects found — create a project in the hub to generate routing entries.",
            "",
        ]

    # Hub admin shortcut: espai.local → hub dashboard
    lines += [
        "# Hub dashboard",
        "espai.local {",
        f"    reverse_proxy localhost:{port}",
        "}",
        "",
    ]

    return "\n".join(lines)


@router.get("/caddyfile", response_class=PlainTextResponse)
def get_caddyfile():
    """Return the generated Caddyfile as plain text."""
    return _generate()


@router.get("/download")
def download_caddyfile():
    """Download the Caddyfile as a file attachment."""
    content = _generate()
    tmp = _CADDY_DEFAULT.parent / "Caddyfile.tmp"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(content, encoding="utf-8")
    return FileResponse(
        path=str(tmp),
        media_type="text/plain",
        filename="Caddyfile",
    )


@router.post("/write")
def write_caddyfile():
    """
    Write the generated Caddyfile to disk.
    Uses ESPAI_CADDY_PATH env var if set, otherwise data/Caddyfile.
    """
    path = Path(os.environ.get(_CADDY_PATH_ENV, str(_CADDY_DEFAULT)))
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _generate()
    path.write_text(content, encoding="utf-8")
    return {"status": "written", "path": str(path), "lines": content.count("\n")}
