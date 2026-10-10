"""CSV import of student records: validated up front, written in ONE transaction, logged as a batch.

Nothing is deleted or overwritten: existing students keep their data (only empty name/department/
class fields are filled), and a row whose (Student_ID, Record_Date) already exists in the database
is rejected as a duplicate instead of creating a second copy.
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd

from config import FEATURE_NAMES, TARGET
from database import database as db
from services import audit
from services.access import require_role


def _opt(row, col, n=120):
    v = row.get(col)
    return None if v is None or pd.isna(v) or str(v).strip() == "" else str(v).strip()[:n]


def _num(row, col):
    v = row.get(col)
    return None if v is None or pd.isna(v) else float(v)


def find_db_duplicates(clean: pd.DataFrame) -> pd.Series:
    """True for rows whose (Student_ID, Record_Date) is already stored."""
    if "Student_ID" not in clean.columns:
        return pd.Series(False, index=clean.index)
    existing = db.query_df("SELECT student_id, record_date FROM academic_records")
    keys = set(zip(existing["student_id"], existing["record_date"]))
    today = date.today().isoformat()
    return clean.apply(lambda r: (str(r.get("Student_ID") or "").strip()[:40],
                                  _opt(r, "Record_Date") or today) in keys, axis=1)


def import_records(actor: dict, clean: pd.DataFrame, rejected: pd.DataFrame | None, filename: str | None) -> dict:
    """Write validated rows atomically and record the batch with every rejected row and its reason."""
    require_role(actor, "admin")
    dup = find_db_duplicates(clean)
    to_write = clean[~dup]
    # (file row number or None, reason, raw values). Validation keeps the original index, so +2 = CSV line.
    rejected_all = []
    if rejected is not None:
        for idx, r in rejected.iterrows():
            rejected_all.append((int(idx) + 2, str(r.get("Reason")), r.drop(labels=["Reason"], errors="ignore")))
    for _, r in clean[dup].iterrows():
        rejected_all.append((None, "pehle se database mein hai (wahi Student_ID aur Record_Date)", r))
    total = len(clean) + (0 if rejected is None else len(rejected))
    with db.connect() as con:
        bid = con.execute("INSERT INTO import_batches(filename, uploaded_by, uploaded_at, rows_total, rows_imported, "
                          "rows_rejected, status) VALUES (?,?,?,?,?,?,?)",
                          (filename, actor.get("username"), db.now(), total, 0, len(rejected_all), "completed")).lastrowid
        n_existing = con.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        written, new_students = 0, 0
        for i, row in to_write.iterrows():
            sid = (str(row.get("Student_ID") or "").strip() or f"IMP-{n_existing + i + 1:04d}")[:40]
            dept, sec = _opt(row, "Department"), _opt(row, "Class_Section")
            if dept:
                con.execute("INSERT OR IGNORE INTO departments(code, name, created_at) VALUES (?,?,?)",
                            (dept, dept, db.now()))
            if sec:
                con.execute("INSERT OR IGNORE INTO class_sections(code, department_code, created_at) VALUES (?,?,?)",
                            (sec, dept, db.now()))
            exists = con.execute("SELECT 1 FROM students WHERE student_id = ?", (sid,)).fetchone()
            con.execute("INSERT INTO students(student_id, name, department, class_section, source, is_demo, created_at) "
                        "VALUES (?,?,?,?,?,0,?) ON CONFLICT(student_id) DO UPDATE SET "
                        "name = COALESCE(students.name, excluded.name), "
                        "department = COALESCE(students.department, excluded.department), "
                        "class_section = COALESCE(students.class_section, excluded.class_section)",
                        (sid, _opt(row, "Name"), dept, sec, "import", db.now()))
            new_students += not exists
            held, att = _num(row, "Classes_Held"), _num(row, "Classes_Attended")
            con.execute("INSERT INTO academic_records(student_id, record_date, attendance, assignment_score, internal_marks, "
                        "study_hours, previous_marks, final_score, classes_held, classes_attended, source, created_at, "
                        "import_batch_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sid, _opt(row, "Record_Date") or date.today().isoformat(), *[float(row[f]) for f in FEATURE_NAMES],
                         _num(row, TARGET), None if held is None else int(held), None if att is None else int(att),
                         "import", db.now(), bid))
            written += 1
        for rown, reason, r in rejected_all:
            raw = {k: (None if pd.isna(v) else v) for k, v in r.items()}
            con.execute("INSERT INTO import_errors(batch_id, row_number, reason, raw_json) VALUES (?,?,?,?)",
                        (bid, rown, reason, json.dumps(raw, default=str)))
        summary = {"imported": written, "new_students": new_students, "rejected": len(rejected_all),
                   "duplicates_in_db": int(dup.sum())}
        con.execute("UPDATE import_batches SET rows_imported = ?, summary_json = ?, status = ? WHERE id = ?",
                    (written, json.dumps(summary), "completed" if written else "rejected", bid))
        audit.log("import.records", actor, "import_batch", bid, dict(summary, filename=filename), con=con)
    return dict(summary, batch_id=bid)


def record_failed_batch(actor: dict, filename: str | None, errors: list[str]):
    """A file that failed validation entirely is still logged, with its errors."""
    with db.connect() as con:
        bid = con.execute("INSERT INTO import_batches(filename, uploaded_by, uploaded_at, status, summary_json) "
                          "VALUES (?,?,?,?,?)", (filename, actor.get("username"), db.now(), "failed",
                                                 json.dumps({"errors": errors}))).lastrowid
        for e in errors:
            con.execute("INSERT INTO import_errors(batch_id, row_number, reason) VALUES (?,?,?)", (bid, None, e))
        audit.log("import.records", actor, "import_batch", bid, {"filename": filename, "errors": errors[:5]},
                  outcome="failed", con=con)


def batches_df(limit: int = 50) -> pd.DataFrame:
    return db.query_df("SELECT id, uploaded_at, uploaded_by, filename, status, rows_total, rows_imported, rows_rejected "
                       "FROM import_batches ORDER BY id DESC LIMIT ?", (limit,))


def batch_errors(batch_id: int) -> pd.DataFrame:
    return db.query_df("SELECT row_number, reason, raw_json FROM import_errors WHERE batch_id = ? ORDER BY id", (batch_id,))
