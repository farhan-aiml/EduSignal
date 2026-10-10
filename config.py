"""Central configuration: paths, feature schema, default settings.

Everything that other modules need to agree on lives here so nothing is
hard-coded twice.
"""
import os
from pathlib import Path

APP_NAME = "EduSignal"                       # short brand name shown in the UI
APP_SUBTITLE = "Student Success & Early Warning System"

ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "assets"
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"

DATASET_PATH = DATA_DIR / "student_performance.csv"
DB_PATH = Path(os.environ.get("EDUSIGNAL_DB_PATH") or DATA_DIR / "app.db")   # override for tests / deployments
BACKUP_DIR = DATA_DIR / "backups"

# Login protection (server-side, stored per account in the database)
MAX_LOGIN_ATTEMPTS = int(os.environ.get("EDUSIGNAL_MAX_LOGIN_ATTEMPTS", 5))
LOCKOUT_SECONDS = int(os.environ.get("EDUSIGNAL_LOCKOUT_SECONDS", 60))
MODEL_PATH = MODEL_DIR / "student_model.pkl"
METADATA_PATH = MODEL_DIR / "model_metadata.json"

TARGET = "Final_Score"

# Feature schema: column name -> (label, min, max, step, unit, actionable)
# "actionable" = something a student can realistically change this term.
FEATURES = {
    "Attendance":       {"label": "Attendance",       "min": 0, "max": 100, "unit": "%",   "actionable": True,  "step": 1},
    "Assignment_Score": {"label": "Assignment score", "min": 0, "max": 100, "unit": "",    "actionable": True,  "step": 1},
    "Internal_Marks":   {"label": "Internal marks",   "min": 0, "max": 100, "unit": "",    "actionable": True,  "step": 1},
    "Study_Hours":      {"label": "Study hours/day",  "min": 0, "max": 24,  "unit": "h",   "actionable": True,  "step": 0.5},
    "Previous_Marks":   {"label": "Previous marks",   "min": 0, "max": 100, "unit": "",    "actionable": False, "step": 1},
}
FEATURE_NAMES = list(FEATURES)
TARGET_RANGE = (0, 100)

# Default, user-configurable thresholds (stored in the settings table).
DEFAULT_SETTINGS = {
    "attendance_target": 75.0,     # % required by the institution (configurable)
    "assignment_min": 60.0,        # below this = risk factor
    "internal_min": 60.0,
    "study_hours_min": 3.0,
    "previous_min": 50.0,
    "assignment_target": 75.0,     # level the study plan aims for
    "internal_target": 75.0,
    "study_hours_target": 4.0,
    "pass_score": 50.0,            # predicted score below this = high risk
    "watch_score": 70.0,           # predicted score below this = on watch
    "decline_points": 5.0,         # drop between records that counts as a decline
    "risk_high": 50.0,             # risk score cut-offs (0-100)
    "risk_moderate": 25.0,
}

SUBJECTS_DEFAULT = ["Python", "DBMS", "Operating Systems", "Artificial Intelligence", "Mathematics"]
RISK_COLORS = {"Low": "#047857", "Moderate": "#B45309", "High": "#DC2626"}
RISK_ICONS = {"Low": "🟢", "Moderate": "🟡", "High": "🔴"}
