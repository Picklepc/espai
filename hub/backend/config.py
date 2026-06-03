import os
import sys
from pathlib import Path

# Two-directory model (frozen / installed builds only):
#
#   INSTALL_DIR  — where the exe and bundled read-only assets live.
#                  Overwritten on every update.  (~\AppData\Local\Programs\ESPAI)
#
#   USER_DIR     — where all mutable user data lives.
#                  NEVER touched by the installer; survives updates and reinstalls.
#                  (~\Documents\ESPAI  on Windows, ~/Documents/ESPAI on Linux/macOS)
#
# In source / dev mode both dirs collapse to the repo root so nothing changes.

if getattr(sys, "frozen", False):
    INSTALL_DIR = Path(sys.executable).parent
    USER_DIR    = Path.home() / "Documents" / "ESPAI"
else:
    INSTALL_DIR = Path(__file__).parent.parent.parent  # repo root
    USER_DIR    = INSTALL_DIR

# ROOT is kept as an alias for USER_DIR so that any router importing ROOT
# (e.g. agent_bench.py) automatically resolves paths relative to user data.
ROOT = USER_DIR

DATA_DIR             = USER_DIR / "data"
PROJECTS_DIR         = USER_DIR / "projects"
RECIPES_DIR          = USER_DIR / "recipes"
WORKERS_DIR          = USER_DIR / "workers"
CARDS_DIR            = USER_DIR / "cards"
DESIGN_DIR           = USER_DIR / "design"
FIRMWARE_CATALOG_DIR = USER_DIR / "firmware-catalog"
POLICIES_DIR         = USER_DIR / "policies"
SCHEMAS_DIR          = USER_DIR / "schemas"
AGENTS_DIR           = USER_DIR / "agents"
AGENT_BENCH_DIR      = USER_DIR / "agent-bench"

DB_PATH = DATA_DIR / "espai.db"

HOST = os.environ.get("ESPAI_HOST", "0.0.0.0")
PORT = int(os.environ.get("ESPAI_PORT", "7888"))
DEBUG = os.environ.get("ESPAI_DEBUG", "0") == "1"
ACTIVE_THEME = os.environ.get("ESPAI_THEME", "retro")
# Set ESPAI_MDNS=0 to disable mDNS advertisement and discovery.
# Recommended for Docker on OpenWrt — multicast is unreliable in that
# environment; manual IP add and subnet scan still work without it.
MDNS_ENABLED = os.environ.get("ESPAI_MDNS", "1") != "0"
