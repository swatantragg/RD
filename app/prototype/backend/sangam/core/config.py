"""Runtime configuration (architecture §22). Every value can be overridden by environment."""
from __future__ import annotations

import os
from pathlib import Path

PROTOTYPE_DIR = Path(__file__).resolve().parents[3]            # app/prototype
DATA_DIR = Path(os.environ.get("SANGAM_DATA_DIR", PROTOTYPE_DIR / "data")).resolve()
DB_PATH = Path(os.environ.get("SANGAM_DB", DATA_DIR / "sangam.db"))
STORAGE_DIR = DATA_DIR / "storage"                              # raw uploads, keyed by sha256
EXPORT_DIR = DATA_DIR / "exports"                               # generated workbooks
FRONTEND_DIST = Path(os.environ.get("SANGAM_FRONTEND_DIST", PROTOTYPE_DIR / "frontend" / "dist"))
REFERENCE_INPUT_DIR = Path(os.environ.get(
    "SANGAM_REFERENCE_INPUT", PROTOTYPE_DIR.parents[1] / "Docs" / "input"))

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "64"))
RECON_TOLERANCE = float(os.environ.get("RECON_TOLERANCE", "0.05"))
COVERAGE_DEFAULT_MODE = os.environ.get("COVERAGE_DEFAULT_MODE", "RESOLVED")
MERGE_SUGGEST_THRESHOLD = float(os.environ.get("MERGE_SUGGEST_THRESHOLD", "0.70"))
MERGE_REVIEW_THRESHOLD = float(os.environ.get("MERGE_REVIEW_THRESHOLD", "0.40"))
SKV_BASE_GENERATION = int(os.environ.get("SKV_BASE_GENERATION", "7"))
JOB_WORKERS = int(os.environ.get("SANGAM_JOB_WORKERS", "2"))

ROLES = ("viewer", "analyst", "admin")
DECIDER_ROLES = ("analyst", "admin")                            # only analyst+ may decide a merge


def ensure_dirs() -> None:
    for d in (DATA_DIR, STORAGE_DIR, EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
