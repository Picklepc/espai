from fastapi import APIRouter, HTTPException

from ..config import ACTIVE_THEME, DESIGN_DIR
from ..registry.loader import scan_folder
from .. import theme_scheduler

router = APIRouter()


@router.get("/themes")
def list_themes():
    return scan_folder(DESIGN_DIR / "themes", "theme")


@router.get("/themes/{theme_name}")
def get_theme(theme_name: str):
    themes = scan_folder(DESIGN_DIR / "themes", "theme")
    for t in themes:
        if t.get("name") == theme_name or t.get("_folder") == theme_name:
            return t
    raise HTTPException(404, f"Theme {theme_name!r} not found")


@router.get("/tokens")
def get_active_tokens():
    """
    Return the merged token set for the active theme.
    Includes any dynamic overrides from the theme scheduler (time/event rules).
    """
    themes = scan_folder(DESIGN_DIR / "themes", "theme")

    # Resolve active theme: dynamic override → env var → default-dark → first
    dynamic_theme = theme_scheduler.get_dynamic_theme()
    theme_name    = dynamic_theme or ACTIVE_THEME

    match = next((t for t in themes if t.get("name") == theme_name), None)
    if not match and themes:
        match = next((t for t in themes if t.get("name") == "default-dark"), themes[0])

    base_tokens = match.get("tokens", {}) if match else {}
    # Merge scheduler-driven overrides on top (highest precedence)
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
