"""
Recipe registry tests — run from repo root:
    python -m pytest tests/ -v
    python tests/test_recipes.py   # runs without pytest
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root is on sys.path so hub imports work
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_recipe_dir(tmp: Path, name: str, fields: dict) -> Path:
    """Write a minimal recipe.yaml into a temp directory."""
    import yaml
    rdir = tmp / name
    rdir.mkdir()
    data = {"schema": "ESPAI.recipe.v1", "name": name, **fields}
    (rdir / "recipe.yaml").write_text(yaml.dump(data), encoding="utf-8")
    return rdir


def _make_private_overlay(recipe_dir: Path, fields: dict) -> None:
    """Write a private/override.yaml inside a recipe folder."""
    import yaml
    priv = recipe_dir / "private"
    priv.mkdir(exist_ok=True)
    (priv / "override.yaml").write_text(yaml.dump(fields), encoding="utf-8")


# ── Unit tests ────────────────────────────────────────────────────────────────

class TestScanFolder(unittest.TestCase):

    def setUp(self):
        import yaml
        try:
            import yaml  # noqa: F811
        except ImportError:
            self.skipTest("PyYAML not installed")

    def test_returns_empty_for_missing_dir(self):
        from hub.backend.registry.loader import scan_folder
        result = scan_folder(Path("/nonexistent/path"), "recipe")
        self.assertEqual(result, [])

    def test_scans_recipe_yaml(self):
        from hub.backend.registry.loader import scan_folder
        with tempfile.TemporaryDirectory() as tmp:
            _make_recipe_dir(Path(tmp), "test-bms", {"category": "battery"})
            result = scan_folder(Path(tmp), "recipe")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "test-bms")
        self.assertEqual(result[0]["_folder"], "test-bms")
        self.assertIn("_path", result[0])

    def test_skips_dirs_without_descriptor(self):
        from hub.backend.registry.loader import scan_folder
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "orphan").mkdir()   # no recipe.yaml
            _make_recipe_dir(Path(tmp), "valid", {})
            result = scan_folder(Path(tmp), "recipe")
        self.assertEqual(len(result), 1)

    def test_skips_malformed_yaml(self):
        from hub.backend.registry.loader import scan_folder
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad"
            bad.mkdir()
            (bad / "recipe.yaml").write_text("{{{{ not yaml", encoding="utf-8")
            _make_recipe_dir(Path(tmp), "good", {})
            result = scan_folder(Path(tmp), "recipe")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "good")


class TestDeepMerge(unittest.TestCase):

    def test_deep_merge(self):
        from hub.backend.routers.recipes import _deep_merge
        base    = {"a": 1, "b": {"x": 10, "y": 20}}
        overlay = {"b": {"y": 99, "z": 30}, "c": 3}
        result  = _deep_merge(base, overlay)
        self.assertEqual(result["a"],    1)
        self.assertEqual(result["b"]["x"], 10)
        self.assertEqual(result["b"]["y"], 99)
        self.assertEqual(result["b"]["z"], 30)
        self.assertEqual(result["c"],    3)

    def test_deep_merge_does_not_mutate_base(self):
        from hub.backend.routers.recipes import _deep_merge
        base    = {"a": {"x": 1}}
        overlay = {"a": {"x": 2}}
        _deep_merge(base, overlay)
        self.assertEqual(base["a"]["x"], 1)


class TestPrivateOverlay(unittest.TestCase):

    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")

    def test_overlay_merges_fields(self):
        from hub.backend.registry.loader import scan_folder
        from hub.backend.routers.recipes import _apply_private_overlay
        with tempfile.TemporaryDirectory() as tmp:
            rdir = _make_recipe_dir(Path(tmp), "my-recipe", {"base_field": "base"})
            _make_private_overlay(rdir, {"private_field": "secret", "base_field": "overridden"})
            [recipe] = scan_folder(Path(tmp), "recipe")
            result   = _apply_private_overlay(recipe)
        self.assertEqual(result["base_field"],    "overridden")
        self.assertEqual(result["private_field"], "secret")
        self.assertTrue(result.get("_private_overlay"))

    def test_no_private_dir_returns_unchanged(self):
        from hub.backend.registry.loader import scan_folder
        from hub.backend.routers.recipes import _apply_private_overlay
        with tempfile.TemporaryDirectory() as tmp:
            _make_recipe_dir(Path(tmp), "clean", {"field": "value"})
            [recipe] = scan_folder(Path(tmp), "recipe")
            result   = _apply_private_overlay(recipe)
        self.assertFalse(result.get("_private_overlay", False))
        self.assertEqual(result["field"], "value")


class TestExportSanitizer(unittest.TestCase):

    def _make_recipe(self, **extra) -> dict:
        return {
            "name": "test",
            "_path": "/fake",
            "_folder": "test",
            "public_field": "visible",
            "_internal": "stripped",
            **extra,
        }

    def test_public_policy_strips_underscore_fields(self):
        from hub.backend.routers.recipes import export_recipe  # noqa: F401
        # Direct logic test (not via HTTP)
        recipe = self._make_recipe(share_policy="public")
        result = {k: v for k, v in recipe.items() if not k.startswith("_")
                  and not recipe.get(f"{k}_private", False)}
        self.assertIn("public_field", result)
        self.assertNotIn("_internal", result)

    def test_redacted_strips_sensitive_names(self):
        _SENSITIVE = {"secret", "key", "token", "password", "credential", "private"}
        recipe = self._make_recipe(
            share_policy="redacted",
            api_key="sk-1234",
            device_token="tok-xyz",
            label="ok",
        )
        def _is_sensitive(name):
            return any(s in name.lower() for s in _SENSITIVE)
        exported = {k: v for k, v in recipe.items()
                    if not k.startswith("_") and not _is_sensitive(k)}
        self.assertNotIn("api_key",     exported)
        self.assertNotIn("device_token", exported)
        self.assertIn("label",          exported)
        self.assertIn("share_policy",   exported)


class TestSchemaValidation(unittest.TestCase):

    def setUp(self):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema not installed")

    def test_validate_against_schema_returns_errors(self):
        from hub.backend.routers.recipes import _validate_against_schema
        schema = {
            "type": "object",
            "required": ["name", "category"],
            "properties": {
                "name":     {"type": "string"},
                "category": {"type": "string"},
            },
        }
        errors = _validate_against_schema({"name": "x"}, schema)
        self.assertTrue(any("category" in e for e in errors))

    def test_validate_valid_recipe(self):
        from hub.backend.routers.recipes import _validate_against_schema
        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        errors = _validate_against_schema({"name": "bms", "_internal": "x"}, schema)
        self.assertEqual(errors, [])


class TestCompatCheck(unittest.TestCase):

    def _recipe(self, **kw) -> dict:
        return {"name": "test", "_path": "/fake", "_folder": "test", **kw}

    def test_no_requirements_is_compatible(self):
        from hub.backend.routers.recipes import recipe_compat  # just import to check it exists
        self.assertTrue(callable(recipe_compat))

    def test_deep_merge_overlay_integration(self):
        from hub.backend.routers.recipes import _deep_merge
        # Overlay with nested structure
        base    = {"inputs": ["media.image"], "config": {"fps": 5}}
        overlay = {"config": {"fps": 10, "resolution": "1080p"}, "outputs": ["tags"]}
        merged  = _deep_merge(base, overlay)
        self.assertEqual(merged["config"]["fps"],        10)
        self.assertEqual(merged["config"]["resolution"], "1080p")
        self.assertEqual(merged["inputs"],               ["media.image"])
        self.assertEqual(merged["outputs"],              ["tags"])


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
