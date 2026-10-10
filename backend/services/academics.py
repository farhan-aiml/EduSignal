"""Academic structure: departments, programs, terms, subjects, class sections, enrollments
and teacher-subject assignments."""
from __future__ import annotations

import pandas as pd

from backend.database import database as db
from backend.services import audit
from backend.services.access import can_manage_section, require, require_role, teacher_sections


# ---------------- reads ----------------
def current_term() -> dict | None:
    with db.connect() as con:
        r = con.execute("SELECT * FROM academic_terms WHERE is_current = 1 ORDER BY id DESC LIMIT 1").fetchone()
        if r is None:
            r = con.execute("SELECT * FROM academic_terms ORDER BY start_date DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def subjects_df() -> pd.DataFrame:
    return db.query_df("SELECT code, name, department_code, credits FROM subjects ORDER BY name")


def departments_df() -> pd.DataFrame:
    return db.query_df("SELECT d.code, d.name, COUNT(s.student_id) AS students FROM departments d "
                       "LEFT JOIN students s ON s.department = d.code GROUP BY d.code, d.name ORDER BY d.code")


def section_students(section: str, include_inactive: bool = False) -> pd.DataFrame:
    sql = ("SELECT student_id, name, registration_no, status, is_demo FROM students WHERE class_section = ?"
           + ("" if include_inactive else " AND status = 'active'") + " ORDER BY student_id")
    return db.query_df(sql, (section,))


def teaching_assignments(user: dict) -> pd.DataFrame:
    """(subject, section) pairs the user may manage in the current term.
    Teachers: their teacher_subjects rows, plus every subject for sections assigned via teacher_classes.
    Admins: every subject offered to any section."""
    term = current_term()
    tid = term["id"] if term else None
    if user.get("role") == "admin":
        return db.query_df(
            "SELECT DISTINCT ts.class_section, ts.subject_code, s.name AS subject_name FROM teacher_subjects ts "
            "JOIN subjects s ON s.code = ts.subject_code WHERE ts.term_id IS ? OR ? IS NULL "
            "ORDER BY ts.class_section, s.name", (tid, tid))
    if user.get("role") != "teacher":
        return pd.DataFrame(columns=["class_section", "subject_code", "subject_name"])
    own = db.query_df(
        "SELECT ts.class_section, ts.subject_code, s.name AS subject_name FROM teacher_subjects ts "
        "JOIN subjects s ON s.code = ts.subject_code WHERE ts.username = ? AND (ts.term_id IS ? OR ? IS NULL)",
        (user["username"], tid, tid))
    if own.empty:   # assigned classes but no subjects yet: allow any subject for those classes
        secs = teacher_sections(user["username"])
        subs = subjects_df()
        rows = [{"class_section": c, "subject_code": r.code, "subject_name": r.name} for c in secs for r in subs.itertuples()]
        own = pd.DataFrame(rows, columns=["class_section", "subject_code", "subject_name"])
    return own.drop_duplicates().sort_values(["class_section", "subject_name"]).reset_index(drop=True)


# ---------------- writes (admin) ----------------
def assign_teacher_subject(actor: dict, username: str, subject_code: str, section: str) -> None:
    require_role(actor, "admin")
    term = current_term()
    require(term is not None, "Create an academic term first.")
    with db.connect() as con:
        con.execute("INSERT OR IGNORE INTO teacher_subjects(username, subject_code, class_section, term_id) "
                    "VALUES (?,?,?,?)", (username, subject_code, section, term["id"]))
        con.execute("INSERT OR IGNORE INTO teacher_classes(username, class_section) VALUES (?,?)", (username, section))
        audit.log("teacher_subject.assign", actor, "teacher", username,
                  {"subject": subject_code, "section": section, "term": term["name"]}, con=con)


def ensure_section(con, code: str, department: str | None = None):
    """Make sure a class section (and its department) exists before anything references it."""
    if department:
        con.execute("INSERT OR IGNORE INTO departments(code, name, created_at) VALUES (?,?,?)",
                    (department, department, db.now()))
    con.execute("INSERT OR IGNORE INTO class_sections(code, department_code, created_at) VALUES (?,?,?)",
                (code, department if department else None, db.now()))


def enroll(con, student_id: str, section: str | None, term_id: int):
    con.execute("INSERT INTO enrollments(student_id, term_id, class_section, status, created_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(student_id, term_id) DO UPDATE SET class_section = excluded.class_section",
                (student_id, term_id, section, "enrolled", db.now()))


def set_student_status(actor: dict, student_id: str, status: str):
    require_role(actor, "admin")
    require(status in ("active", "inactive", "graduated", "withdrawn"), "Unknown status.")
    with db.connect() as con:
        con.execute("UPDATE students SET status = ? WHERE student_id = ?", (status, student_id))
        audit.log("student.status", actor, "student", student_id, {"status": status}, con=con)


def check_section_access(actor: dict, section: str):
    require(can_manage_section(actor, section), f"You are not assigned to class {section}.")
