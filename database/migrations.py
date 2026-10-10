"""Versioned, idempotent schema migrations.

Each migration runs once, inside a transaction, and is recorded in `schema_migrations`.
Migrations only ADD tables, columns and indexes: no existing table is dropped or rewritten,
so an existing data/app.db keeps all of its data. `database.manage backup` (and
`apply_all(backup=True)`) copies the database file before any pending migration runs.

SQL stays portable (INTEGER, REAL, TEXT, plain constraints) for a later PostgreSQL move.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from config import BACKUP_DIR, DB_PATH


def _columns(con, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _script(con, sql: str):
    """Run a multi-statement DDL script inside the caller's transaction.
    (sqlite3's executescript() would COMMIT first, breaking atomicity.)"""
    for stmt in sql.split(";"):
        if stmt.strip():
            con.execute(stmt)


def _add_column(con, table: str, column: str, ddl: str):
    if column not in _columns(con, table):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def m001_baseline(con):
    """The original v1 schema (already created by database.SCHEMA) plus the teacher subject column."""
    from database.database import SCHEMA
    _script(con, SCHEMA)
    _add_column(con, "users", "subject", "TEXT")


def m002_identity_and_audit(con):
    """Account status, server-side lockout, and an append-only audit log."""
    _add_column(con, "users", "is_active", "INTEGER NOT NULL DEFAULT 1")
    _add_column(con, "users", "failed_attempts", "INTEGER NOT NULL DEFAULT 0")
    _add_column(con, "users", "locked_until", "TEXT")
    _add_column(con, "users", "last_login_at", "TEXT")
    _add_column(con, "users", "password_changed_at", "TEXT")
    _script(con, """
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, actor TEXT, actor_role TEXT,
        action TEXT NOT NULL, target_type TEXT, target_id TEXT, details_json TEXT,
        outcome TEXT NOT NULL DEFAULT 'ok' CHECK (outcome IN ('ok','denied','failed')));
    CREATE INDEX IF NOT EXISTS ix_audit_time ON audit_log(created_at);
    CREATE INDEX IF NOT EXISTS ix_audit_actor ON audit_log(actor);
    """)


def m003_academic_structure(con):
    """Departments, programs, terms, subjects, sections, enrollments and teacher-subject assignments."""
    _script(con, """
    CREATE TABLE IF NOT EXISTS departments (
        code TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);

    CREATE TABLE IF NOT EXISTS programs (
        code TEXT PRIMARY KEY, name TEXT NOT NULL,
        department_code TEXT NOT NULL REFERENCES departments(code),
        duration_semesters INTEGER NOT NULL DEFAULT 8 CHECK (duration_semesters BETWEEN 1 AND 16),
        created_at TEXT NOT NULL);

    CREATE TABLE IF NOT EXISTS academic_terms (
        id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, academic_year TEXT NOT NULL,
        start_date TEXT NOT NULL, end_date TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 0,
        CHECK (end_date >= start_date));

    CREATE TABLE IF NOT EXISTS subjects (
        code TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL,
        department_code TEXT REFERENCES departments(code),
        credits INTEGER NOT NULL DEFAULT 4 CHECK (credits BETWEEN 0 AND 12), created_at TEXT NOT NULL);

    CREATE TABLE IF NOT EXISTS class_sections (
        code TEXT PRIMARY KEY, department_code TEXT REFERENCES departments(code),
        program_code TEXT REFERENCES programs(code), semester INTEGER CHECK (semester BETWEEN 1 AND 16),
        created_at TEXT NOT NULL);

    CREATE TABLE IF NOT EXISTS enrollments (
        id INTEGER PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(student_id),
        term_id INTEGER NOT NULL REFERENCES academic_terms(id),
        class_section TEXT REFERENCES class_sections(code),
        status TEXT NOT NULL DEFAULT 'enrolled' CHECK (status IN ('enrolled','withdrawn','completed')),
        created_at TEXT NOT NULL, UNIQUE (student_id, term_id));

    CREATE TABLE IF NOT EXISTS teacher_subjects (
        id INTEGER PRIMARY KEY, username TEXT NOT NULL REFERENCES users(username),
        subject_code TEXT NOT NULL REFERENCES subjects(code),
        class_section TEXT NOT NULL REFERENCES class_sections(code),
        term_id INTEGER NOT NULL REFERENCES academic_terms(id),
        UNIQUE (username, subject_code, class_section, term_id));

    CREATE INDEX IF NOT EXISTS ix_enroll_term ON enrollments(term_id, class_section);
    CREATE INDEX IF NOT EXISTS ix_tsub_user ON teacher_subjects(username, term_id);
    """)
    _add_column(con, "students", "registration_no", "TEXT")
    _add_column(con, "students", "program_code", "TEXT")
    _add_column(con, "students", "semester", "INTEGER")
    _add_column(con, "students", "status", "TEXT NOT NULL DEFAULT 'active'")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_students_regno ON students(registration_no) "
                "WHERE registration_no IS NOT NULL")


def m004_attendance_and_assessments(con):
    """Session-level attendance and assessment marks (the raw data the features are computed from)."""
    _script(con, """
    CREATE TABLE IF NOT EXISTS attendance_sessions (
        id INTEGER PRIMARY KEY, class_section TEXT NOT NULL REFERENCES class_sections(code),
        subject_code TEXT NOT NULL REFERENCES subjects(code),
        term_id INTEGER REFERENCES academic_terms(id),
        session_date TEXT NOT NULL, period INTEGER NOT NULL DEFAULT 1 CHECK (period BETWEEN 1 AND 12),
        taken_by TEXT, created_at TEXT NOT NULL,
        UNIQUE (class_section, subject_code, session_date, period));

    CREATE TABLE IF NOT EXISTS attendance_records (
        session_id INTEGER NOT NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE,
        student_id TEXT NOT NULL REFERENCES students(student_id),
        status TEXT NOT NULL CHECK (status IN ('present','absent','late','excused')),
        PRIMARY KEY (session_id, student_id));

    CREATE TABLE IF NOT EXISTS assessments (
        id INTEGER PRIMARY KEY, class_section TEXT NOT NULL REFERENCES class_sections(code),
        subject_code TEXT NOT NULL REFERENCES subjects(code),
        term_id INTEGER REFERENCES academic_terms(id),
        title TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('assignment','internal','quiz','semester')),
        max_marks REAL NOT NULL CHECK (max_marks > 0), assessed_on TEXT NOT NULL,
        created_by TEXT, created_at TEXT NOT NULL,
        UNIQUE (class_section, subject_code, title));

    CREATE TABLE IF NOT EXISTS assessment_marks (
        assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
        student_id TEXT NOT NULL REFERENCES students(student_id),
        marks REAL CHECK (marks IS NULL OR marks >= 0), absent INTEGER NOT NULL DEFAULT 0,
        entered_by TEXT, updated_at TEXT NOT NULL,
        PRIMARY KEY (assessment_id, student_id),
        CHECK (absent = 1 OR marks IS NOT NULL));

    CREATE INDEX IF NOT EXISTS ix_att_rec_student ON attendance_records(student_id);
    CREATE INDEX IF NOT EXISTS ix_marks_student ON assessment_marks(student_id);
    CREATE INDEX IF NOT EXISTS ix_assess_section ON assessments(class_section, subject_code);
    """)


def m005_ml_and_operations(con):
    """Model registry, reproducible prediction snapshots, and CSV import history."""
    _script(con, """
    CREATE TABLE IF NOT EXISTS model_versions (
        id INTEGER PRIMARY KEY, version TEXT UNIQUE NOT NULL, model_name TEXT NOT NULL,
        trained_at TEXT NOT NULL, training_rows INTEGER NOT NULL, cv_scheme TEXT,
        mae REAL, rmse REAL, r2 REAL, interval_p80 REAL, dataset_sha256 TEXT, sklearn_version TEXT,
        is_active INTEGER NOT NULL DEFAULT 0, metrics_json TEXT, registered_at TEXT NOT NULL);

    CREATE TABLE IF NOT EXISTS import_batches (
        id INTEGER PRIMARY KEY, filename TEXT, uploaded_by TEXT, uploaded_at TEXT NOT NULL,
        rows_total INTEGER NOT NULL DEFAULT 0, rows_imported INTEGER NOT NULL DEFAULT 0,
        rows_rejected INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL CHECK (status IN ('completed','failed','rejected')), summary_json TEXT);

    CREATE TABLE IF NOT EXISTS import_errors (
        id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
        row_number INTEGER, reason TEXT NOT NULL, raw_json TEXT);
    CREATE INDEX IF NOT EXISTS ix_import_err_batch ON import_errors(batch_id);
    """)
    _add_column(con, "predictions", "model_version", "TEXT")
    _add_column(con, "predictions", "inputs_json", "TEXT")
    _add_column(con, "predictions", "interval_low", "REAL")
    _add_column(con, "predictions", "interval_high", "REAL")
    _add_column(con, "academic_records", "import_batch_id", "INTEGER")


def m006_tracking_delivery_chat(con):
    """Study-plan task status, contact details + external delivery log, and assistant chat history."""
    _script(con, """
    CREATE TABLE IF NOT EXISTS study_tasks (
        id INTEGER PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(student_id),
        plan_date TEXT NOT NULL, block_order INTEGER NOT NULL, activity TEXT NOT NULL, minutes INTEGER NOT NULL,
        reason TEXT, status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','in_progress','completed')),
        updated_by TEXT, updated_at TEXT NOT NULL, completed_at TEXT,
        UNIQUE (student_id, plan_date, activity));
    CREATE INDEX IF NOT EXISTS ix_tasks_student ON study_tasks(student_id, plan_date);

    CREATE TABLE IF NOT EXISTS notification_deliveries (
        id INTEGER PRIMARY KEY, notification_id INTEGER NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
        channel TEXT NOT NULL CHECK (channel IN ('email','sms')), recipient TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('sent','failed','not_configured','no_contact')),
        error TEXT, attempted_at TEXT NOT NULL, UNIQUE (notification_id, channel, recipient));

    CREATE TABLE IF NOT EXISTS assistant_conversations (
        id INTEGER PRIMARY KEY, username TEXT NOT NULL REFERENCES users(username), student_id TEXT,
        title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_conv_user ON assistant_conversations(username, updated_at);

    CREATE TABLE IF NOT EXISTS assistant_messages (
        id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('user','assistant')), content TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_msg_conv ON assistant_messages(conversation_id)
    """)
    _add_column(con, "users", "email", "TEXT")
    _add_column(con, "users", "phone", "TEXT")


MIGRATIONS = [
    ("001_baseline", m001_baseline),
    ("002_identity_and_audit", m002_identity_and_audit),
    ("003_academic_structure", m003_academic_structure),
    ("004_attendance_and_assessments", m004_attendance_and_assessments),
    ("005_ml_and_operations", m005_ml_and_operations),
    ("006_tracking_delivery_chat", m006_tracking_delivery_chat),
]


def backup_database(path=DB_PATH, label: str = "manual") -> str | None:
    """Copy the database file (consistent copy via SQLite's backup API). Returns the backup path."""
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / f"app_{label}_{datetime.now():%Y%m%d_%H%M%S}.db"
    src = sqlite3.connect(path)
    try:
        out = sqlite3.connect(dest)
        with out:
            src.backup(out)
        out.close()
    finally:
        src.close()
    return str(dest)


def applied(con) -> set[str]:
    con.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    return {r[0] for r in con.execute("SELECT version FROM schema_migrations")}


def pending(path=DB_PATH) -> list[str]:
    if not path.exists():
        return [v for v, _ in MIGRATIONS]
    con = sqlite3.connect(path)
    try:
        done = applied(con)
    finally:
        con.close()
    return [v for v, _ in MIGRATIONS if v not in done]


def apply_all(path=DB_PATH, backup: bool = True) -> list[str]:
    """Apply every pending migration in order. Each one is its own transaction."""
    todo = pending(path)
    if not todo:
        return []
    if backup and path.exists():
        backup_database(path, "pre_migration")
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, isolation_level=None)   # explicit BEGIN/COMMIT per migration
    con.execute("PRAGMA foreign_keys = ON")
    ran = []
    try:
        done = applied(con)
        for version, fn in MIGRATIONS:
            if version in done:
                continue
            try:
                con.execute("BEGIN")
                fn(con)
                con.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                            (version, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                con.commit()
                ran.append(version)
            except Exception:
                con.rollback()
                raise
    finally:
        con.close()
    return ran


def integrity_report(path=DB_PATH) -> dict:
    """SQLite integrity + foreign-key check + application-level orphan checks."""
    con = sqlite3.connect(path)
    try:
        report = {"integrity": con.execute("PRAGMA integrity_check").fetchone()[0],
                  "foreign_key_violations": len(con.execute("PRAGMA foreign_key_check").fetchall()),
                  "pending_migrations": [v for v, _ in MIGRATIONS if v not in applied(con)]}
        checks = {
            "records_without_student": "SELECT COUNT(*) FROM academic_records r LEFT JOIN students s "
                                       "ON s.student_id = r.student_id WHERE s.student_id IS NULL",
            "student_logins_without_student": "SELECT COUNT(*) FROM users u LEFT JOIN students s "
                                              "ON s.student_id = u.student_id WHERE u.role = 'student' "
                                              "AND u.student_id IS NOT NULL AND s.student_id IS NULL",
            "marks_above_maximum": "SELECT COUNT(*) FROM assessment_marks m JOIN assessments a "
                                   "ON a.id = m.assessment_id WHERE m.marks > a.max_marks",
            "duplicate_student_records_same_day": "SELECT COUNT(*) FROM (SELECT student_id, record_date, source "
                                                  "FROM academic_records GROUP BY 1, 2, 3 HAVING COUNT(*) > 1)",
        }
        for k, sql in checks.items():
            try:
                report[k] = con.execute(sql).fetchone()[0]
            except sqlite3.OperationalError:
                report[k] = None   # table not created yet
        return report
    finally:
        con.close()
