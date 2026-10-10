"""Reproducible, idempotent seeding.

seed_structure()      departments, programs, the current term, subjects, class sections, enrollments
                      and demo teacher-subject assignments. Safe to run on every start (INSERT OR IGNORE).
seed_demo_academics() attendance sessions and assessment marks for SYNTHETIC demo students only
                      (is_demo = 1), generated from each student's existing demo record so the stories
                      stay consistent. Skips any class/subject that already has sessions, so it never
                      duplicates and never touches real (non-demo) data.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from database import database as db

DEPARTMENTS = {"CSE": "Computer Science and Engineering", "IT": "Information Technology",
               "ECE": "Electronics and Communication Engineering", "Unassigned": "Unassigned (dataset records)"}
PROGRAMS = {"BTECH-CSE": ("B.Tech Computer Science and Engineering", "CSE"),
            "BTECH-IT": ("B.Tech Information Technology", "IT"),
            "BTECH-ECE": ("B.Tech Electronics and Communication Engineering", "ECE")}
SUBJECTS = [("PY101", "Python", "CSE", 4), ("DB201", "DBMS", "IT", 4), ("OS202", "Operating Systems", "CSE", 4),
            ("AI301", "Artificial Intelligence", "CSE", 3), ("MA101", "Mathematics", None, 4),
            ("EC204", "Digital Electronics", "ECE", 4)]
DEMO_TEACHER_SUBJECTS = {"meera": [("PY101", "CSE-A"), ("PY101", "CSE-B"), ("MA101", "CSE-A")],
                         "arjun": [("EC204", "ECE-A"), ("EC204", "ECE-B")],
                         "sana": [("DB201", "IT-A")]}


def _term_for(today: date) -> tuple[str, str, str, str]:
    """Indian academic calendar: odd semester Jul-Dec, even semester Jan-Jun."""
    if today.month >= 7:
        y = today.year
        return f"{y}-{str(y + 1)[2:]} Odd Semester", f"{y}-{str(y + 1)[2:]}", f"{y}-07-15", f"{y}-12-20"
    y = today.year - 1
    return f"{y}-{str(y + 1)[2:]} Even Semester", f"{y}-{str(y + 1)[2:]}", f"{y + 1}-01-05", f"{y + 1}-06-15"


def seed_structure() -> dict:
    today = date.today()
    name, year, start, end = _term_for(today)
    with db.connect() as con:
        for code, nm in DEPARTMENTS.items():
            con.execute("INSERT OR IGNORE INTO departments(code, name, created_at) VALUES (?,?,?)", (code, nm, db.now()))
        for code, (nm, dept) in PROGRAMS.items():
            con.execute("INSERT OR IGNORE INTO programs(code, name, department_code, created_at) VALUES (?,?,?,?)",
                        (code, nm, dept, db.now()))
        con.execute("INSERT OR IGNORE INTO academic_terms(name, academic_year, start_date, end_date, is_current) "
                    "VALUES (?,?,?,?,0)", (name, year, start, end))
        if not con.execute("SELECT 1 FROM academic_terms WHERE is_current = 1").fetchone():
            con.execute("UPDATE academic_terms SET is_current = (name = ?)", (name,))
        term_id = con.execute("SELECT id FROM academic_terms WHERE is_current = 1").fetchone()[0]
        for code, nm, dept, cr in SUBJECTS:
            con.execute("INSERT OR IGNORE INTO subjects(code, name, department_code, credits, created_at) VALUES (?,?,?,?,?)",
                        (code, nm, dept, cr, db.now()))
        # departments/sections that already exist in student data (e.g. from CSV imports)
        for dept, sec in con.execute("SELECT DISTINCT department, class_section FROM students "
                                     "WHERE class_section IS NOT NULL").fetchall():
            if dept:
                con.execute("INSERT OR IGNORE INTO departments(code, name, created_at) VALUES (?,?,?)", (dept, dept, db.now()))
            prog = f"BTECH-{dept}" if f"BTECH-{dept}" in PROGRAMS else None
            con.execute("INSERT OR IGNORE INTO class_sections(code, department_code, program_code, semester, created_at) "
                        "VALUES (?,?,?,?,?)", (sec, dept, prog, 3 if prog else None, db.now()))
        # demo students: program, semester and a clearly synthetic registration number
        for i, (sid, dept) in enumerate(con.execute("SELECT student_id, department FROM students WHERE is_demo = 1 "
                                                    "AND registration_no IS NULL ORDER BY student_id").fetchall()):
            prog = f"BTECH-{dept}" if f"BTECH-{dept}" in PROGRAMS else None
            con.execute("UPDATE students SET registration_no = ?, program_code = COALESCE(program_code, ?), "
                        "semester = COALESCE(semester, 3) WHERE student_id = ?", (f"DEMO-REG-{sid[5:]}", prog, sid))
        con.execute("INSERT OR IGNORE INTO enrollments(student_id, term_id, class_section, status, created_at) "
                    "SELECT student_id, ?, class_section, 'enrolled', ? FROM students WHERE status = 'active'",
                    (term_id, db.now()))
        for user, pairs in DEMO_TEACHER_SUBJECTS.items():
            if not con.execute("SELECT 1 FROM users WHERE username = ? AND role = 'teacher'", (user,)).fetchone():
                continue
            for subj, sec in pairs:
                if con.execute("SELECT 1 FROM class_sections WHERE code = ?", (sec,)).fetchone():
                    con.execute("INSERT OR IGNORE INTO teacher_subjects(username, subject_code, class_section, term_id) "
                                "VALUES (?,?,?,?)", (user, subj, sec, term_id))
    return {"term": name}


def seed_demo_academics(seed: int = 11, sessions: int = 12, weeks: int = 6) -> dict:
    """Synthetic attendance and marks for demo students, consistent with their latest demo record."""
    from services.assessments import _sync_subject_scores
    rng = np.random.default_rng(seed)
    today = date.today()
    made = {"sessions": 0, "assessments": 0}
    with db.connect() as con:
        term = con.execute("SELECT id FROM academic_terms WHERE is_current = 1").fetchone()
        if term is None:
            return made
        pairs = con.execute("SELECT DISTINCT ts.class_section, ts.subject_code, ts.username FROM teacher_subjects ts "
                            "ORDER BY 1, 2").fetchall()
        synced = []
        for sec, subj, teacher in pairs:
            demo = con.execute(
                "SELECT s.student_id, r.attendance, r.assignment_score, r.internal_marks FROM students s JOIN academic_records r "
                "ON r.id = (SELECT id FROM academic_records WHERE student_id = s.student_id ORDER BY record_date DESC, id DESC LIMIT 1) "
                "WHERE s.is_demo = 1 AND s.status = 'active' AND s.class_section = ?", (sec,)).fetchall()
            if not demo or con.execute("SELECT 1 FROM attendance_sessions WHERE class_section = ? AND subject_code = ?",
                                       (sec, subj)).fetchone():
                continue
            days = [today - timedelta(days=int(d)) for d in np.linspace(weeks * 7, 1, sessions)]
            for d in days:
                d = d - timedelta(days=max(0, d.weekday() - 4))     # move weekend sessions to Friday
                cur = con.execute("INSERT OR IGNORE INTO attendance_sessions(class_section, subject_code, term_id, "
                                  "session_date, period, taken_by, created_at) VALUES (?,?,?,?,?,?,?)",
                                  (sec, subj, term[0], d.isoformat(), 1, teacher, db.now()))
                sid_ = cur.lastrowid if cur.rowcount else None   # ignored insert keeps the OLD lastrowid
                if not sid_:
                    continue
                made["sessions"] += 1
                for st, att, _, _ in demo:
                    u = rng.random()
                    p = float(att) / 100
                    status = "excused" if u > 0.985 else "present" if u < p * 0.93 else "late" if u < p else "absent"
                    con.execute("INSERT INTO attendance_records(session_id, student_id, status) VALUES (?,?,?)",
                                (sid_, st, status))
            for title, kind, mx, ago, col in [("Assignment 1", "assignment", 20, 30, 2), ("Assignment 2", "assignment", 20, 12, 2),
                                              ("Internal Test 1", "internal", 50, 18, 3)]:
                cur = con.execute("INSERT OR IGNORE INTO assessments(class_section, subject_code, term_id, title, kind, max_marks, "
                                  "assessed_on, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                                  (sec, subj, term[0], title, kind, mx, (today - timedelta(days=ago)).isoformat(),
                                   teacher, db.now()))
                aid = cur.lastrowid if cur.rowcount else None
                if not aid:
                    continue
                made["assessments"] += 1
                for row in demo:
                    st, level = row[0], float(row[col])
                    if kind == "assignment" and rng.random() < max(0.02, (60 - level) / 200):
                        continue                                   # missing submission, more likely when struggling
                    pct = float(np.clip(level + rng.normal(0, 7), 0, 100))
                    con.execute("INSERT INTO assessment_marks(assessment_id, student_id, marks, absent, entered_by, updated_at) "
                                "VALUES (?,?,?,0,?,?)", (aid, st, round(mx * pct / 100 * 2) / 2, teacher, db.now()))
            synced.append((subj, [r[0] for r in demo]))
    for subj, ids in synced:
        _sync_subject_scores(ids, subj)
    return made


def seed_all() -> dict:
    out = seed_structure()
    out.update(seed_demo_academics())
    return out
