from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
AUTOMATION_DIR = PROJECT_ROOT / "automation"
SCRIPTS_DIR = AUTOMATION_DIR / "scripts"
TMP_DIR = AUTOMATION_DIR / "_tmp"
DB_PATH = PROJECT_ROOT / "activities" / "_db" / "投放数据.db"
