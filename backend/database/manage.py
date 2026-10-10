"""Database management commands.

    python -m backend.database.manage status      # applied / pending migrations and row counts
    python -m backend.database.manage backup      # consistent copy into backend/data/backups/
    python -m backend.database.manage migrate     # back up, then apply pending migrations
    python -m backend.database.manage seed        # academic structure + demo accounts (idempotent)
    python -m backend.database.manage seed-demo   # synthetic demo students, attendance and marks (idempotent)
    python -m backend.database.manage check       # integrity, foreign keys and orphan checks

Set EDUSIGNAL_DB_PATH to work on a different database file.
"""
from __future__ import annotations

import json
import sqlite3
import sys

from backend.config import DB_PATH
from backend.database import migrations

TABLES = ["users", "students", "academic_records", "subject_scores", "departments", "programs", "academic_terms",
          "subjects", "class_sections", "enrollments", "teacher_subjects", "attendance_sessions", "attendance_records",
          "assessments", "assessment_marks", "predictions", "risk_assessments", "recommendations", "interventions",
          "notifications", "notification_deliveries", "model_versions", "import_batches", "audit_log",
          "study_tasks", "assistant_conversations", "assistant_messages"]


def counts() -> dict:
    con = sqlite3.connect(DB_PATH)
    try:
        out = {}
        for t in TABLES:
            try:
                out[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.OperationalError:
                out[t] = "missing"
        return out
    finally:
        con.close()


def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:] or ["status"])[0]
    if cmd == "backup":
        print("Backup written to", migrations.backup_database(DB_PATH, "manual") or "(no database yet)")
    elif cmd == "migrate":
        ran = migrations.apply_all(DB_PATH, backup=True)
        print("Applied:", ", ".join(ran) if ran else "nothing (already up to date)")
    elif cmd in ("seed", "seed-demo"):
        from backend.database import database as db
        from backend.services import seed
        from backend.utils import auth
        from backend.utils.demo_data import generate_demo, seed_dataset_records
        db.init_db()
        seed_dataset_records()
        auth.seed_demo_accounts()
        auth.seed_teacher_classes()
        auth.seed_teacher_subjects()
        if cmd == "seed-demo" and db.demo_count() == 0:
            print("Generated", generate_demo(), "synthetic demo students")
        print(json.dumps(seed.seed_all(), indent=2))
    elif cmd == "check":
        rep = migrations.integrity_report(DB_PATH)
        print(json.dumps(rep, indent=2))
        bad = rep["integrity"] != "ok" or rep["foreign_key_violations"] or rep["pending_migrations"] \
            or any(rep.get(k) for k in ("records_without_student", "student_logins_without_student", "marks_above_maximum"))
        return 1 if bad else 0
    elif cmd == "status":
        print("Database:", DB_PATH)
        print("Pending migrations:", migrations.pending(DB_PATH) or "none")
        print(json.dumps(counts(), indent=2) if DB_PATH.exists() else "(not created yet)")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
