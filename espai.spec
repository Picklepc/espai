# -*- mode: python ; coding: utf-8 -*-
#
# ESPAI Hub — PyInstaller one-dir spec
#
# Build:
#   pip install pyinstaller
#   pyinstaller espai.spec
#
# Output: dist/espai/  (one-dir bundle)
#   dist/espai/espai.exe        ← entry point (Windows)
#   dist/espai/espai             ← entry point (Linux/macOS)
#   dist/espai/hub/frontend/    ← static files
#   dist/espai/recipes/         ← starter recipes
#   dist/espai/workers/         ← starter workers
#   dist/espai/cards/           ← starter cards
#   dist/espai/design/          ← themes, skins, nav
#   dist/espai/agents/          ← agent rules and adapter stubs
#   dist/espai/policies/        ← default policy
#   dist/espai/schemas/         ← YAML schemas
#
# data/ and projects/ are created at runtime by espai.py next to the exe.

import sys
from pathlib import Path

ROOT = Path(SPECPATH)

# Make hub.* importable during analysis so collect_submodules can find it.
# This is needed because espai.py references hub.backend.main as a string
# in the non-frozen path; without this, PyInstaller won't follow the imports.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyInstaller.utils.hooks import collect_submodules  # noqa: E402
_hub_hidden = collect_submodules("hub")

block_cipher = None


def _datas():
    """Collect all non-Python data directories that must ship with the bundle."""
    pairs = [
        # (src_dir,                       dest_in_bundle)
        ("hub/frontend",                  "hub/frontend"),
        ("hub/matter",                    "hub/matter"),
        ("recipes",                       "recipes"),
        ("workers",                       "workers"),
        ("cards",                         "cards"),
        ("design",                        "design"),
        ("agents",                        "agents"),
        ("agent-bench",                   "agent-bench"),
        ("policies",                      "policies"),
        ("schemas",                       "schemas"),
    ]
    result = []
    for src, dst in pairs:
        src_path = ROOT / src
        if src_path.exists():
            result.append((str(src_path), dst))
    # Also bundle the single-file VERSION marker
    vf = ROOT / "VERSION"
    if vf.exists():
        result.append((str(vf), "."))
    return result


a = Analysis(
    [str(ROOT / "espai.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=_datas(),
    hiddenimports=[
        # ── hub.backend — all submodules (belt-and-suspenders alongside the
        # direct import in espai.py; catches dynamically-loaded routers) ──
        *_hub_hidden,
        # FastAPI + uvicorn internals not always auto-detected
        "uvicorn.lifespan.on",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.logging",
        "fastapi",
        "pydantic",
        "pydantic.v1",
        "yaml",
        "aiofiles",
        "anyio",
        "anyio._backends._asyncio",
        "sniffio",
        # Optional hub deps
        "pystray",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        # mDNS
        "zeroconf",
        "zeroconf._utils.ipaddress",
        "zeroconf._handlers",
        # PTY terminal (Windows)
        "winpty",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Dev/test extras we don't need at runtime
        "pytest",
        "black",
        "mypy",
        "ruff",
        "IPython",
        "jupyter",
        "notebook",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Read version string from VERSION file for embedding in the exe.
_ver_str = (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").exists() else "0.0.0"

# Windows-only: embed VERSIONINFO PE resource so Explorer and SmartScreen
# show the publisher name. On Linux the version= param must be None.
_win_version_info = None
if sys.platform == "win32":
    _ver_tuple = tuple(int(x) for x in (_ver_str.split(".")[:3] + ["0", "0", "0"])[:4])
    _win_version_info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=_ver_tuple,
            prodvers=_ver_tuple,
            mask=0x3f,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo([
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName",      "ESPAI Project"),
                        StringStruct("FileDescription",  "ESPAI Hub — Local-first ESP32 fleet management"),
                        StringStruct("FileVersion",      _ver_str),
                        StringStruct("InternalName",     "espai"),
                        StringStruct("LegalCopyright",   "MIT License"),
                        StringStruct("OriginalFilename", "espai.exe"),
                        StringStruct("ProductName",      "ESPAI"),
                        StringStruct("ProductVersion",   _ver_str),
                    ],
                )
            ]),
            VarFileInfo([VarStruct("Translation", [0x0409, 0x04B0])]),
        ],
    )

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="espai",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # console=False hides the terminal on Windows; keep True on Linux so the
    # AppImage can still print to stdout when run from a terminal.
    console=(sys.platform != "win32"),
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_win_version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="espai",
)
