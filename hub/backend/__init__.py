from pathlib import Path as _Path

_VERSION_FILE = _Path(__file__).parent.parent.parent / "VERSION"
__version__: str = _VERSION_FILE.read_text(encoding="utf-8").strip() if _VERSION_FILE.exists() else "0.1.0"
