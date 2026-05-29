import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import ACTIVE_THEME, DESIGN_DIR
from ..db import get_setting, set_setting
from ..registry.loader import scan_folder
from .. import theme_scheduler

_SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,62}$")

router = APIRouter()

_BUILTIN_THEMES = {"default-dark", "retro"}  # undeletable


def _resolve_active_theme() -> str:
    """DB setting → env var → 'retro'."""
    return get_setting("active_theme") or ACTIVE_THEME or "retro"


@router.get("/themes")
def list_themes():
    themes = scan_folder(DESIGN_DIR / "themes", "theme")
    active = _resolve_active_theme()
    for t in themes:
        t["is_active"] = (t.get("name") == active)
        t["builtin"]   = t.get("name") in _BUILTIN_THEMES
    return themes


@router.get("/themes/{theme_name}")
def get_theme(theme_name: str):
    themes = scan_folder(DESIGN_DIR / "themes", "theme")
    for t in themes:
        if t.get("name") == theme_name or t.get("_folder") == theme_name:
            return t
    raise HTTPException(404, f"Theme {theme_name!r} not found")


@router.get("/theme/active")
def get_active_theme():
    active = _resolve_active_theme()
    themes = scan_folder(DESIGN_DIR / "themes", "theme")
    match  = next((t for t in themes if t.get("name") == active), None)
    return {"active": active, "theme": match}


class ThemeActivate(BaseModel):
    theme: str


@router.put("/theme/active")
def set_active_theme(body: ThemeActivate):
    themes = scan_folder(DESIGN_DIR / "themes", "theme")
    names  = [t.get("name") for t in themes]
    if body.theme not in names:
        raise HTTPException(404, f"Theme {body.theme!r} not found")
    set_setting("active_theme", body.theme)
    return {"active": body.theme}


class ThemeCreate(BaseModel):
    slug: str
    display_name: str
    tokens: dict


@router.post("/themes")
def create_theme(body: ThemeCreate):
    if not _SAFE_SLUG.match(body.slug):
        raise HTTPException(400, "Slug must be lowercase letters, digits, hyphens, or underscores")
    # New themes always go in custom/ — gitignored, never committed to the official pack
    custom_dir = DESIGN_DIR / "themes" / "custom"
    custom_dir.mkdir(parents=True, exist_ok=True)
    # Ensure custom/ is gitignored
    gi = DESIGN_DIR / "themes" / ".gitignore"
    if not gi.exists():
        gi.write_text("custom/\n", encoding="utf-8")
    theme_dir = custom_dir / body.slug
    if theme_dir.exists():
        raise HTTPException(409, f"Theme {body.slug!r} already exists")
    theme_dir.mkdir(parents=True)
    import yaml as _yaml
    data = {
        "schema": "ESPAI.theme.v1",
        "name": body.slug,
        "display_name": body.display_name,
        "tokens": body.tokens,
    }
    (theme_dir / "theme.yaml").write_text(
        _yaml.dump(data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    return {"slug": body.slug, "display_name": body.display_name, "created": True}


@router.delete("/themes/{theme_name}")
def delete_theme(theme_name: str):
    if theme_name in _BUILTIN_THEMES:
        raise HTTPException(400, f"Theme {theme_name!r} is built-in and cannot be deleted")
    themes = scan_folder(DESIGN_DIR / "themes", "theme")
    match = next((t for t in themes if t.get("name") == theme_name or t.get("_folder") == theme_name), None)
    if not match:
        raise HTTPException(404, f"Theme {theme_name!r} not found")
    import shutil
    shutil.rmtree(Path(match["_path"]))
    active = _resolve_active_theme()
    if active == theme_name:
        set_setting("active_theme", "retro")
    return {"deleted": theme_name}


@router.get("/tokens")
def get_active_tokens():
    """Return the merged token set for the active theme, including dynamic overrides."""
    themes = scan_folder(DESIGN_DIR / "themes", "theme")

    # Resolve active theme: dynamic override → DB setting → env var → retro
    dynamic_theme = theme_scheduler.get_dynamic_theme()
    theme_name    = dynamic_theme or _resolve_active_theme()

    match = next((t for t in themes if t.get("name") == theme_name), None)
    if not match and themes:
        match = next((t for t in themes if t.get("name") == "retro"), themes[0])

    base_tokens = match.get("tokens", {}) if match else {}
    return {**base_tokens, **theme_scheduler.get_active_overrides()}


@router.get("/dynamic-overrides")
def get_dynamic_overrides():
    """Return only the currently active dynamic token overrides (for debugging)."""
    return {
        "overrides":      theme_scheduler.get_active_overrides(),
        "dynamic_theme":  theme_scheduler.get_dynamic_theme(),
    }


@router.get("/skins")
def list_skins():
    return scan_folder(DESIGN_DIR / "skins", "skin")


@router.get("/nav")
def list_nav():
    return scan_folder(DESIGN_DIR / "nav", "nav")
