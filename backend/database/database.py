"""SQLite persistence.

SQL is kept to portable types (INTEGER, REAL, TEXT) and plain statements so
the schema can move to PostgreSQL later: swap `connect()` for a psycopg /
SQLAlchemy connection and change `?` placeholders to `%s`.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

import pandas as pd

from backend.config import DB_PATH, DEFAULT_SETTINGS, FEATURE_NAMES

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('student','teacher','admin')),
    student_id TEXT, display_name TEXT, created_at TEXT NOT NULL, subject TEXT);

CREATE TABLE IF NOT EXISTS students (
    student_id TEXT PRIMARY KEY, name TEXT, department TEXT, class_section TEXT,
    source TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS academic_records (
    id INTEGER PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(student_id),
    record_date TEXT NOT NULL,
    attendance REAL NOT NULL, assignment_score REAL NOT NULL, internal_marks REAL NOT NULL,
    study_hours REAL NOT NULL, previous_marks REAL NOT NULL,
    final_score REAL, classes_held INTEGER, classes_attended INTEGER,
    source TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS subject_scores (
    id INTEGER PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(student_id),
    subject TEXT NOT NULL, score REAL NOT NULL, record_date TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY, student_id TEXT, record_id INTEGER, predicted_score REAL NOT NULL,
    grade TEXT, model_name TEXT, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS risk_assessments (
    id INTEGER PRIMARY KEY, student_id TEXT, prediction_id INTEGER REFERENCES predictions(id),
    risk_level TEXT NOT NULL, risk_score REAL NOT NULL, factors_json TEXT, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY, student_id TEXT, assessment_id INTEGER REFERENCES risk_assessments(id),
    priority INTEGER, category TEXT, text TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS interventions (
    id INTEGER PRIMARY KEY, student_id TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT,
    risk_level TEXT, issues_json TEXT, actions_json TEXT,
    status TEXT NOT NULL DEFAULT 'Open', notes TEXT, follow_up_date TEXT);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
    recipient_role TEXT, recipient_student_id TEXT, student_id TEXT,
    type TEXT NOT NULL, severity TEXT NOT NULL, message TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS teacher_classes (
    username TEXT NOT NULL REFERENCES users(username), class_section TEXT NOT NULL,
    PRIMARY KEY (username, class_section));

CREATE INDEX IF NOT EXISTS ix_records_student ON academic_records(student_id, record_date);
CREATE INDEX IF NOT EXISTS ix_subjects_student ON subject_scores(student_id);
CREATE INDEX IF NOT EXISTS ix_notif_student ON notifications(recipient_student_id);
"""

RECORD_COLS = {  # dataframe column -> db column
    "Attendance": "attendance", "Assignment_Score": "assignment_score", "Internal_Marks": "internal_marks",
    "Study_Hours": "study_hours", "Previous_Marks": "previous_marks",
}


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def connect(path=DB_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def query_df(sql: str, params=()) -> pd.DataFrame:
    with connect() as con:
        return pd.read_sql_query(sql, con, params=params)


def execute(sql: str, params=()) -> int:
    with connect() as con:
        cur = con.execute(sql, params)
        return cur.lastrowid


def init_db(backup: bool = True) -> list[str]:
    """Create or upgrade the schema through versioned migrations (backing up first), then default settings."""
    from backend.database.migrations import apply_all
    ran = apply_all(DB_PATH, backup=backup)
    with connect() as con:
        for k, v in DEFAULT_SETTINGS.items():
            con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, json.dumps(v)))
    return ran


# ---------------- settings ----------------
def get_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    with connect() as con:
        for row in con.execute("SELECT key, value FROM settings"):
            s[row["key"]] = json.loads(row["value"])
    return s


def save_settings(values: dict):
    with connect() as con:
        for k, v in values.items():
            con.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, json.dumps(v)))


# ---------------- users ----------------
def get_user(username: str):
    with connect() as con:
        r = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(r) if r else None


def create_user(username, password_hash, role, student_id=None, display_name=None, subject=None):
    execute("INSERT INTO users(username, password_hash, role, student_id, display_name, created_at, subject, "
            "password_changed_at) VALUES (?,?,?,?,?,?,?,?)",
            (username, password_hash, role, student_id, display_name, now(), subject, now()))


def update_password(username, password_hash):
    execute("UPDATE users SET password_hash = ?, password_changed_at = ?, failed_attempts = 0, locked_until = NULL "
            "WHERE username = ?", (password_hash, now(), username))


def users_df() -> pd.DataFrame:
    """Every account without password hashes (for the admin user list)."""
    return query_df("SELECT username, role, display_name, student_id, subject, email, phone, is_active, failed_attempts, "
                    "locked_until, last_login_at, created_at FROM users ORDER BY role, username")


def count_users() -> int:
    with connect() as con:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]


# ---------------- students & records ----------------
def upsert_student(student_id, name=None, department=None, class_section=None, source="manual", is_demo=0):
    execute("INSERT INTO students(student_id, name, department, class_section, source, is_demo, created_at) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(student_id) DO UPDATE SET "
            "name = COALESCE(excluded.name, students.name), "
            "department = COALESCE(excluded.department, students.department), "
            "class_section = COALESCE(excluded.class_section, students.class_section)",
            (student_id, name, department, class_section, source, is_demo, now()))


def add_record(student_id, values: dict, record_date=None, final_score=None,
               classes_held=None, classes_attended=None, source="manual") -> int:
    return execute(
        "INSERT INTO academic_records(student_id, record_date, attendance, assignment_score, internal_marks, "
        "study_hours, previous_marks, final_score, classes_held, classes_attended, source, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (student_id, record_date or date.today().isoformat(),
         *[float(values[f]) for f in FEATURE_NAMES],
         final_score, classes_held, classes_attended, source, now()))


def add_subject_score(student_id, subject, score, record_date=None):
    execute("INSERT INTO subject_scores(student_id, subject, score, record_date) VALUES (?,?,?,?)",
            (student_id, subject, float(score), record_date or date.today().isoformat()))


def students_df() -> pd.DataFrame:
    return query_df("SELECT * FROM students ORDER BY student_id")


def records_df(student_id: str | None = None) -> pd.DataFrame:
    sql = ("SELECT r.*, s.name, s.department, s.class_section, s.is_demo FROM academic_records r "
           "JOIN students s ON s.student_id = r.student_id")
    params = ()
    if student_id:
        sql += " WHERE r.student_id = ?"
        params = (student_id,)
    df = query_df(sql + " ORDER BY r.student_id, r.record_date, r.id", params)
    return df.rename(columns={v: k for k, v in RECORD_COLS.items()})


def subject_scores_df(student_id: str | None = None) -> pd.DataFrame:
    if student_id:
        return query_df("SELECT * FROM subject_scores WHERE student_id = ? ORDER BY record_date, id", (student_id,))
    return query_df("SELECT * FROM subject_scores ORDER BY student_id, record_date, id")


def latest_subject_scores(student_id: str) -> pd.DataFrame:
    df = subject_scores_df(student_id)
    if df.empty:
        return df
    return df.sort_values(["record_date", "id"]).groupby("subject", as_index=False).last()


def delete_demo_data():
    with connect() as con:
        ids = "SELECT student_id FROM students WHERE is_demo = 1"
        for t in ["academic_records", "subject_scores", "predictions", "risk_assessments",
                  "recommendations", "interventions", "attendance_records", "assessment_marks", "enrollments", "study_tasks"]:
            con.execute(f"DELETE FROM {t} WHERE student_id IN ({ids})")
        # sessions/assessments that only ever held demo students are now empty: remove them too
        con.execute("DELETE FROM attendance_sessions WHERE id NOT IN (SELECT DISTINCT session_id FROM attendance_records)")
        con.execute("DELETE FROM assessments WHERE id NOT IN (SELECT DISTINCT assessment_id FROM assessment_marks)")
        con.execute(f"DELETE FROM notifications WHERE student_id IN ({ids})")
        con.execute("UPDATE users SET student_id = NULL WHERE student_id IN (" + ids + ")")
        con.execute("DELETE FROM students WHERE is_demo = 1")


def demo_count() -> int:
    with connect() as con:
        return con.execute("SELECT COUNT(*) FROM students WHERE is_demo = 1").fetchone()[0]


# ---------------- assessments, interventions, notifications ----------------
def save_assessment(student_id, record_id, predicted, grade, model_name, risk, recs,
                    model_version=None, inputs=None, interval=None) -> int:
    """Prediction + risk + recommendations in one transaction. `inputs` is the exact feature snapshot
    used, so every stored prediction can be reproduced with the stated model version."""
    lo, hi = interval or (None, None)
    with connect() as con:
        pid = con.execute("INSERT INTO predictions(student_id, record_id, predicted_score, grade, model_name, created_at, "
                          "model_version, inputs_json, interval_low, interval_high) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (student_id, record_id, predicted, grade, model_name, now(), model_version,
                           json.dumps(inputs) if inputs else None, lo, hi)).lastrowid
        aid = con.execute("INSERT INTO risk_assessments(student_id, prediction_id, risk_level, risk_score, factors_json, created_at) "
                          "VALUES (?,?,?,?,?,?)",
                          (student_id, pid, risk["level"], risk["score"], json.dumps(risk["factors"]), now())).lastrowid
        for i, r in enumerate(recs, 1):
            con.execute("INSERT INTO recommendations(student_id, assessment_id, priority, category, text, created_at) "
                        "VALUES (?,?,?,?,?,?)", (student_id, aid, i, r["category"], r["text"], now()))
        return aid


def activity_df(student_id: str | None = None, limit: int = 10) -> pd.DataFrame:
    sql = ("SELECT p.created_at, p.student_id, p.predicted_score, p.grade, a.risk_level "
           "FROM predictions p LEFT JOIN risk_assessments a ON a.prediction_id = p.id")
    params = ()
    if student_id:
        sql += " WHERE p.student_id = ?"
        params = (student_id,)
    return query_df(sql + " ORDER BY p.id DESC LIMIT ?", params + (limit,))


def create_intervention(student_id, created_by, risk_level, issues, actions, follow_up_date, notes="") -> int:
    return execute("INSERT INTO interventions(student_id, created_at, created_by, risk_level, issues_json, actions_json, "
                   "status, notes, follow_up_date) VALUES (?,?,?,?,?,?,?,?,?)",
                   (student_id, now(), created_by, risk_level, json.dumps(issues), json.dumps(actions),
                    "Open", notes, follow_up_date))


def update_intervention(iid, status, notes):
    execute("UPDATE interventions SET status = ?, notes = ? WHERE id = ?", (status, notes, iid))


def interventions_df(student_id: str | None = None) -> pd.DataFrame:
    if student_id:
        return query_df("SELECT * FROM interventions WHERE student_id = ? ORDER BY id DESC", (student_id,))
    return query_df("SELECT * FROM interventions ORDER BY id DESC")


def add_notification(type_, severity, message, student_id=None, recipient_role=None, recipient_student_id=None):
    """Skips a notification identical to an existing unread one (no spam)."""
    with connect() as con:
        dup = con.execute("SELECT 1 FROM notifications WHERE is_read = 0 AND type = ? AND message = ? "
                          "AND COALESCE(recipient_role,'') = COALESCE(?, '') "
                          "AND COALESCE(recipient_student_id,'') = COALESCE(?, '')",
                          (type_, message, recipient_role, recipient_student_id)).fetchone()
        if dup:
            return None
        return con.execute("INSERT INTO notifications(created_at, recipient_role, recipient_student_id, student_id, "
                           "type, severity, message) VALUES (?,?,?,?,?,?,?)",
                           (now(), recipient_role, recipient_student_id, student_id, type_, severity, message)).lastrowid


def notifications_for(role: str, student_id: str | None) -> pd.DataFrame:
    if role == "student":
        return query_df("SELECT * FROM notifications WHERE recipient_student_id = ? ORDER BY id DESC", (student_id or "",))
    return query_df("SELECT * FROM notifications WHERE recipient_role IN ('teacher','all') "
                    "OR (? = 'admin' AND recipient_role = 'admin') ORDER BY id DESC", (role,))


def mark_read(ids: list[int]):
    if ids:
        with connect() as con:
            con.executemany("UPDATE notifications SET is_read = 1 WHERE id = ?", [(int(i),) for i in ids])


# ---------------- teachers and their classes ----------------
def teachers_df() -> pd.DataFrame:
    return query_df("SELECT username, display_name, subject FROM users WHERE role = 'teacher' ORDER BY display_name")


def set_teacher_subject(username: str, subject: str | None):
    execute("UPDATE users SET subject = ? WHERE username = ? AND role = 'teacher'", (subject or None, username))


def get_teacher_classes(username: str) -> list[str]:
    with connect() as con:
        return [r[0] for r in con.execute(
            "SELECT class_section FROM teacher_classes WHERE username = ? ORDER BY class_section", (username,))]


def set_teacher_classes(username: str, classes: list[str]):
    with connect() as con:
        con.execute("DELETE FROM teacher_classes WHERE username = ?", (username,))
        con.executemany("INSERT INTO teacher_classes(username, class_section) VALUES (?, ?)",
                        [(username, c) for c in sorted(set(classes))])


def class_sections() -> list[str]:
    with connect() as con:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT class_section FROM students WHERE class_section IS NOT NULL ORDER BY class_section")]
