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
    console=False,         # no terminal window on launch; hub logs go to data/espai-hub.log
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
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
