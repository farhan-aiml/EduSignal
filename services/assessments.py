"""Assessments (assignments, internal tests, quizzes, semester exams) and their marks.

Marks are stored raw (out of max_marks) and converted to percentages only for analysis.
A missing mark (no row, not flagged absent) is reported as a missing submission.
"""
from __future__ import annotations

import math
from datetime import date as _date

import pandas as pd

from database import database as db
from services import audit
from services.academics import check_section_access, current_term, ensure_section, section_students

KINDS = ("assignment", "internal", "quiz", "semester")


def create_assessment(actor: dict, section: str, subject_code: str, title: str, kind: str,
                      max_marks: float, assessed_on: str) -> int:
    check_section_access(actor, section)
    title = (title or "").strip()
    if not title or len(title) > 80:
        raise ValueError("Assessment ka title likhein (80 characters tak).")
    if kind not in KINDS:
        raise ValueError("Type inmein se ek hona chahiye: " + ", ".join(KINDS) + ".")
    try:
        mm = float(max_marks)
    except (TypeError, ValueError):
        raise ValueError("Kul marks ek number hona chahiye.")
    if not (0 < mm <= 1000) or math.isnan(mm):
        raise ValueError("Kul marks 1 se 1000 ke beech hone chahiye.")
    try:
        d = _date.fromisoformat(str(assessed_on)).isoformat()
    except ValueError:
        raise ValueError("Tareekh YYYY-MM-DD format mein honi chahiye.")
    term = current_term()
    with db.connect() as con:
        ensure_section(con, section)
        if con.execute("SELECT 1 FROM assessments WHERE class_section = ? AND subject_code = ? AND title = ?",
                       (section, subject_code, title)).fetchone():
            raise ValueError(f"Is class aur subject mein '{title}' naam ka assessment pehle se hai.")
        aid = con.execute("INSERT INTO assessments(class_section, subject_code, term_id, title, kind, max_marks, "
                          "assessed_on, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                          (section, subject_code, term["id"] if term else None, title, kind, mm, d,
                           actor.get("username"), db.now())).lastrowid
        audit.log("assessment.create", actor, "assessment", aid,
                  {"section": section, "subject": subject_code, "title": title, "kind": kind, "max": mm}, con=con)
    return aid


def get_assessment(aid: int) -> dict | None:
    with db.connect() as con:
        r = con.execute("SELECT * FROM assessments WHERE id = ?", (int(aid),)).fetchone()
    return dict(r) if r else None


def validate_marks(rows: list[dict], max_marks: float, roster: set[str]) -> tuple[list[tuple], list[str]]:
    """rows: {student_id, marks (number or blank), absent (bool)}. Returns (clean rows, error messages).
    Blank and not absent = not entered yet (skipped, reported as missing later)."""
    clean, errors = [], []
    for r in rows:
        sid = r.get("student_id")
        if sid not in roster:
            errors.append(f"{sid}: is class mein nahi hai.")
            continue
        absent = bool(r.get("absent"))
        raw = r.get("marks")
        blank = raw is None or (isinstance(raw, float) and math.isnan(raw)) or (isinstance(raw, str) and not raw.strip())
        if absent:
            clean.append((sid, None, 1))
            continue
        if blank:
            continue
        try:
            m = float(raw)
        except (TypeError, ValueError):
            errors.append(f"{sid}: marks number hone chahiye (mila {raw!r}).")
            continue
        if math.isnan(m) or m < 0 or m > max_marks:
            errors.append(f"{sid}: marks 0 se {max_marks:g} ke beech hone chahiye (mila {m:g}).")
            continue
        clean.append((sid, round(m, 2), 0))
    return clean, errors


def save_marks(actor: dict, assessment_id: int, rows: list[dict]) -> int:
    """Validate every row first; save nothing if any row is invalid (all-or-nothing)."""
    a = get_assessment(assessment_id)
    if a is None:
        raise ValueError("Assessment nahi mila.")
    check_section_access(actor, a["class_section"])
    roster = set(section_students(a["class_section"])["student_id"])
    clean, errors = validate_marks(rows, a["max_marks"], roster)
    if errors:
        raise ValueError("Koi marks save nahi hue. Yeh rows theek karein: " + " ".join(errors[:8])
                         + (f" (+{len(errors) - 8} aur)" if len(errors) > 8 else ""))
    with db.connect() as con:
        con.executemany("INSERT INTO assessment_marks(assessment_id, student_id, marks, absent, entered_by, updated_at) "
                        "VALUES (?,?,?,?,?,?) ON CONFLICT(assessment_id, student_id) DO UPDATE SET "
                        "marks = excluded.marks, absent = excluded.absent, entered_by = excluded.entered_by, "
                        "updated_at = excluded.updated_at",
                        [(int(assessment_id), sid, m, ab, actor.get("username"), db.now()) for sid, m, ab in clean])
        audit.log("marks.save", actor, "assessment", assessment_id,
                  {"title": a["title"], "rows": len(clean)}, con=con)
    _sync_subject_scores([sid for sid, _, _ in clean], a["subject_code"])
    return len(clean)


def marks_sheet(assessment_id: int) -> pd.DataFrame:
    """Every active student in the class with their current mark (blank if not entered)."""
    a = get_assessment(assessment_id)
    if a is None:
        return pd.DataFrame()
    roster = section_students(a["class_section"])[["student_id", "name"]]
    m = db.query_df("SELECT student_id, marks, absent FROM assessment_marks WHERE assessment_id = ?", (int(assessment_id),))
    out = roster.merge(m, on="student_id", how="left")
    out["absent"] = out["absent"].fillna(0).astype(bool)
    return out


def assessments_df(section: str, subject_code: str | None = None) -> pd.DataFrame:
    sql = ("SELECT a.id, a.title, a.kind, a.subject_code, a.max_marks, a.assessed_on, "
           "COUNT(m.student_id) AS entered, ROUND(AVG(100.0 * m.marks / a.max_marks), 1) AS avg_pct "
           "FROM assessments a LEFT JOIN assessment_marks m ON m.assessment_id = a.id WHERE a.class_section = ?")
    params = [section]
    if subject_code:
        sql += " AND a.subject_code = ?"
        params.append(subject_code)
    return db.query_df(sql + " GROUP BY a.id ORDER BY a.assessed_on DESC, a.id DESC", tuple(params))


def student_marks(student_id: str) -> pd.DataFrame:
    """All assessments for the student's class, with their mark as a percentage (NaN = missing)."""
    return db.query_df(
        "SELECT a.id, a.title, a.kind, a.subject_code, sub.name AS subject, a.assessed_on, a.max_marks, m.marks, "
        "COALESCE(m.absent, 0) AS absent, CASE WHEN m.marks IS NULL THEN NULL ELSE ROUND(100.0 * m.marks / a.max_marks, 1) END AS pct "
        "FROM assessments a JOIN students st ON st.class_section = a.class_section AND st.student_id = ? "
        "LEFT JOIN assessment_marks m ON m.assessment_id = a.id AND m.student_id = st.student_id "
        "LEFT JOIN subjects sub ON sub.code = a.subject_code ORDER BY a.assessed_on, a.id", (student_id,))


def student_summary(student_id: str) -> dict:
    """Average percentage per assessment kind, per subject, and missing/absent counts."""
    df = student_marks(student_id)
    if df.empty:
        return {"assignment_pct": None, "internal_pct": None, "by_subject": pd.DataFrame(), "missing": 0, "absent": 0,
                "count": 0}
    scored = df[df["pct"].notna()]
    absent = int(df["absent"].sum())
    missing = int(((df["pct"].isna()) & (df["absent"] == 0)).sum())

    def avg(kinds):
        s = scored[scored["kind"].isin(kinds)]["pct"]
        return round(float(s.mean()), 1) if len(s) else None

    by_subject = (scored.groupby("subject", as_index=False)["pct"].mean().round(1) if len(scored) else pd.DataFrame())
    return {"assignment_pct": avg(["assignment", "quiz"]), "internal_pct": avg(["internal", "semester"]),
            "by_subject": by_subject, "missing": missing, "absent": absent, "count": int(len(df))}


def _sync_subject_scores(student_ids: list[str], subject_code: str):
    """Keep the subject-wise view (subject_scores) in step with entered marks: one derived row per day."""
    if not student_ids:
        return
    with db.connect() as con:
        name = con.execute("SELECT name FROM subjects WHERE code = ?", (subject_code,)).fetchone()
        subject = name[0] if name else subject_code
        today = _date.today().isoformat()
        for sid in set(student_ids):
            r = con.execute("SELECT AVG(100.0 * m.marks / a.max_marks) FROM assessment_marks m JOIN assessments a "
                            "ON a.id = m.assessment_id WHERE m.student_id = ? AND a.subject_code = ? AND m.marks IS NOT NULL",
                            (sid, subject_code)).fetchone()
            if r[0] is None:
                continue
            con.execute("DELETE FROM subject_scores WHERE student_id = ? AND subject = ? AND record_date = ?",
                        (sid, subject, today))
            con.execute("INSERT INTO subject_scores(student_id, subject, score, record_date) VALUES (?,?,?,?)",
                        (sid, subject, round(float(r[0]), 1), today))
