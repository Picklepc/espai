"""
Registry loader: scans folder trees for ESPAI.*.v1 YAML manifests.
Each primitive type (recipe, worker, card, theme, skin, nav) lives in its
own subfolder with a single descriptor file. Unknown or malformed entries
are logged and skipped rather than crashing the hub.
"""
import logging
from pathlib import Path
from typing import Any

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False

log = logging.getLogger(__name__)

_DESCRIPTOR_NAMES = {
    "recipe":  "recipe.yaml",
    "worker":  "worker.yaml",
    "card":    "card.yaml",
    "theme":   "theme.yaml",
    "skin":    "skin.yaml",
    "nav":     "nav.yaml",
    "policy":  "policy.yaml",
}


def _load_yaml(path: Path) -> dict | None:
    if not _YAML_OK:
        log.warning("PyYAML not installed — cannot parse %s", path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        log.warning("Failed to parse %s: %s", path, exc)
        return None


def scan_folder(root: Path, kind: str) -> list[dict[str, Any]]:
    """Return a list of parsed manifests for *kind* found under *root*."""
    descriptor = _DESCRIPTOR_NAMES.get(kind)
    if not descriptor:
        raise ValueError(f"Unknown registry kind: {kind!r}")

    results: list[dict[str, Any]] = []
    if not root.exists():
        return results

    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir():
            continue
        manifest_path = candidate / descriptor
        if not manifest_path.exists():
            continue
        data = _load_yaml(manifest_path)
        if data is None:
            continue
        data["_path"] = str(candidate)
        data["_folder"] = candidate.name
        results.append(data)

    return results


def load_all(
    recipes_dir: Path,
    workers_dir: Path,
    cards_dir: Path,
    design_dir: Path,
    policies_dir: Path,
) -> dict[str, list[dict]]:
    themes_dir = design_dir / "themes"
    skins_dir  = design_dir / "skins"
    nav_dir    = design_dir / "nav"

    return {
        "recipes":  scan_folder(recipes_dir, "recipe"),
        "workers":  scan_folder(workers_dir, "worker"),
        "cards":    scan_folder(cards_dir,   "card"),
        "themes":   scan_folder(themes_dir,  "theme"),
        "skins":    scan_folder(skins_dir,   "skin"),
        "nav":      scan_folder(nav_dir,     "nav"),
        "policies": scan_folder(policies_dir,"policy"),
    }
