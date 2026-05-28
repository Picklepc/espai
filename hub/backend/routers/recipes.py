import json
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..config import RECIPES_DIR, SCHEMAS_DIR
from ..db import get_conn
from ..registry.loader import scan_folder

router = APIRouter()


def _load_schema(kind: str) -> dict | None:
    path = SCHEMAS_DIR / f"{kind}.schema.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge *overlay* into a copy of *base*."""
    result = dict(base)
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _apply_private_overlay(recipe: dict) -> dict:
    """
    Merge YAML files found in {recipe_folder}/private/ on top of *recipe*.

    Private overlay files are loaded in sorted order so layering is deterministic.
    Fields merged from overlays are available at runtime but are stripped by
    the export endpoint (which already removes all `_`-prefixed fields).

    A `_private_overlay: true` flag is set on the returned dict to signal
    that private data is present — callers can use this to avoid caching.
    """
    try:
        import yaml
    except ImportError:
        return recipe

    private_dir = Path(recipe.get("_path", "")) / "private"
    if not private_dir.is_dir():
        return recipe

    result = dict(recipe)
    applied: list[str] = []
    for yf in sorted(private_dir.glob("*.yaml")):
        try:
            with open(yf, encoding="utf-8") as fh:
                overlay = yaml.safe_load(fh) or {}
            if isinstance(overlay, dict):
                result = _deep_merge(result, overlay)
                applied.append(yf.name)
        except Exception:
            pass

    if applied:
        result["_private_overlay"] = True
        result["_private_files"]   = applied
    return result


def _validate_against_schema(data: dict, schema: dict) -> list[str]:
    """Validate *data* against *schema*. Returns a list of error messages."""
    try:
        import jsonschema
        clean = {k: v for k, v in data.items() if not k.startswith("_")}
        validator = jsonschema.Draft202012Validator(schema)
        return [e.message for e in validator.iter_errors(clean)]
    except ImportError:
        # Fallback: check required fields only
        required = schema.get("required", [])
        return [f"Missing required field: '{f}'" for f in required if f not in data]


@router.get("/")
def list_recipes():
    recipes = scan_folder(RECIPES_DIR, "recipe")
    return [_apply_private_overlay(r) for r in recipes]


@router.get("/{recipe_name}")
def get_recipe(recipe_name: str):
    all_recipes = scan_folder(RECIPES_DIR, "recipe")
    for r in all_recipes:
        if r.get("name") == recipe_name or r.get("_folder") == recipe_name:
            return _apply_private_overlay(r)
    raise HTTPException(404, f"Recipe {recipe_name!r} not found")


@router.get("/{recipe_name}/validate")
def validate_recipe(recipe_name: str):
    """Validate a recipe against schemas/recipe.schema.json."""
    all_recipes = scan_folder(RECIPES_DIR, "recipe")
    recipe = next(
        (r for r in all_recipes if r.get("name") == recipe_name or r.get("_folder") == recipe_name),
        None,
    )
    if not recipe:
        raise HTTPException(404, f"Recipe {recipe_name!r} not found")

    schema = _load_schema("recipe")
    if schema is None:
        return {"valid": None, "errors": [], "note": "No schema file found — skipped validation"}

    errors = _validate_against_schema(recipe, schema)
    return {"valid": len(errors) == 0, "errors": errors, "recipe": recipe_name}


@router.get("/{recipe_name}/export")
def export_recipe(recipe_name: str):
    """
    Return a sanitized copy of a recipe suitable for sharing.

    Fields are stripped according to the recipe's share_policy:
      - share_policy: "public"   → remove fields prefixed with _ or marked private
      - share_policy: "redacted" → also remove credentials, keys, tokens, secrets
      - share_policy: "private"  → deny export entirely (403)
      - (default, no policy)     → same as "public"

    Private-field detection: any field whose name contains "secret", "key",
    "token", "password", "credential", or "private" (case-insensitive).
    """
    all_recipes = scan_folder(RECIPES_DIR, "recipe")
    recipe = next(
        (r for r in all_recipes if r.get("name") == recipe_name or r.get("_folder") == recipe_name),
        None,
    )
    if not recipe:
        raise HTTPException(404, f"Recipe {recipe_name!r} not found")

    policy = str(recipe.get("share_policy", "public")).lower()
    if policy == "private":
        raise HTTPException(403, "Recipe share_policy is 'private' — export not allowed")

    _SENSITIVE = {"secret", "key", "token", "password", "credential", "private"}

    def _is_sensitive(field_name: str) -> bool:
        lower = field_name.lower()
        return any(s in lower for s in _SENSITIVE)

    # Always strip internal loader fields and explicitly private fields
    exported = {
        k: v for k, v in recipe.items()
        if not k.startswith("_")
        and not recipe.get(f"{k}_private", False)
    }

    if policy == "redacted":
        exported = {k: v for k, v in exported.items() if not _is_sensitive(k)}

    exported["_exported"] = True
    exported["_share_policy"] = policy
    return exported


@router.get("/{recipe_name}/compat")
def recipe_compat(recipe_name: str):
    """
    Check whether the hub environment satisfies a recipe's declared requirements.

    Checks:
    - compatible_boards: any paired device must match at least one entry
    - requires_workers:  each named worker must exist in the workers registry
    - requires_tools:    each named external tool (ffmpeg, pio, etc.) must be on PATH
    - min_devices:       minimum number of paired devices needed
    """
    from ..config import WORKERS_DIR
    all_recipes = scan_folder(RECIPES_DIR, "recipe")
    recipe = next(
        (r for r in all_recipes if r.get("name") == recipe_name or r.get("_folder") == recipe_name),
        None,
    )
    if not recipe:
        raise HTTPException(404, f"Recipe {recipe_name!r} not found")

    issues: list[str] = []
    satisfied: list[str] = []

    # Fleet check
    with get_conn() as conn:
        paired_devices = conn.execute(
            "SELECT id, board FROM devices WHERE paired=1"
        ).fetchall()
    paired_boards = {(r["board"] or "").strip() for r in paired_devices}
    paired_count  = len(paired_devices)

    compatible_boards = recipe.get("compatible_boards") or []
    if compatible_boards:
        matched = [b for b in compatible_boards if b in paired_boards]
        if matched:
            satisfied.append(f"board match: {', '.join(matched)}")
        else:
            issues.append(
                f"No paired device matches compatible_boards: {compatible_boards} "
                f"(fleet has: {sorted(paired_boards) or ['none']})"
            )

    min_devices = recipe.get("min_devices") or 0
    if min_devices > 0:
        if paired_count >= min_devices:
            satisfied.append(f"min_devices {min_devices} met ({paired_count} paired)")
        else:
            issues.append(f"Requires {min_devices} paired device(s); fleet has {paired_count}")

    # Worker dependency check
    requires_workers = recipe.get("requires_workers") or []
    if requires_workers:
        from ..registry.loader import scan_folder as _sf
        available_workers = {w.get("name") or w.get("_folder") for w in _sf(WORKERS_DIR, "worker")}
        for wname in requires_workers:
            if wname in available_workers:
                satisfied.append(f"worker '{wname}' available")
            else:
                issues.append(f"Required worker '{wname}' not in registry")

    # External tool check
    requires_tools = recipe.get("requires_tools") or []
    for tool in requires_tools:
        if shutil.which(tool):
            satisfied.append(f"tool '{tool}' found on PATH")
        else:
            issues.append(f"External tool '{tool}' not found on PATH")

    return {
        "recipe":    recipe_name,
        "compatible": len(issues) == 0,
        "issues":    issues,
        "satisfied": satisfied,
    }
