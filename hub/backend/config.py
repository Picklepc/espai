import os
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent

DATA_DIR = ROOT / "data"
PROJECTS_DIR = ROOT / "projects"
RECIPES_DIR = ROOT / "recipes"
WORKERS_DIR = ROOT / "workers"
CARDS_DIR = ROOT / "cards"
DESIGN_DIR = ROOT / "design"
FIRMWARE_CATALOG_DIR = ROOT / "firmware-catalog"
POLICIES_DIR = ROOT / "policies"
SCHEMAS_DIR = ROOT / "schemas"

DB_PATH = DATA_DIR / "ESPAI.db"

HOST = os.environ.get("ESPAI_HOST", "0.0.0.0")
PORT = int(os.environ.get("ESPAI_PORT", "7888"))
DEBUG = os.environ.get("ESPAI_DEBUG", "0") == "1"
ACTIVE_THEME = os.environ.get("ESPAI_THEME", "retro")
