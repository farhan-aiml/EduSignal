"""Session-level attendance.

Counting rule (documented, used everywhere): 'present' and 'late' count as attended,
'absent' counts as missed, 'excused' is left out of both held and attended.
"""
from __future__ import annotations

from datetime import date as _date

import pandas as pd

from database import database as db
from services import audit
from services.academics import check_section_access, current_term, ensure_section, section_students

STATUSES = ("present", "absent", "late", "excused")
ATTENDED = ("present", "late")


def record_session(actor: dict, section: str, subject_code: str, session_date: str, statuses: dict[str, str],
                   period: int = 1) -> int:
    """Create (or update) one attendance session with a status per student, in one transaction.
    Rejects students who are not in the section and unknown statuses. Returns the session id."""
    check_section_access(actor, section)
    try:
        d = _date.fromisoformat(str(session_date))
    except ValueError:
        raise ValueError("Session ki tareekh YYYY-MM-DD format mein honi chahiye.")
    if d > _date.today():
        raise ValueError("Aane wali tareekh ki attendance record nahi ho sakti.")
    if not 1 <= int(period) <= 12:
        raise ValueError("Period 1 se 12 ke beech hona chahiye.")
    roster = set(section_students(section)["student_id"])
    bad_ids = [s for s in statuses if s not in roster]
    if bad_ids:
        raise ValueError(f"Yeh {section} mein nahi hain: {', '.join(bad_ids[:5])}.")
    bad_status = {s: v for s, v in statuses.items() if v not in STATUSES}
    if bad_status:
        raise ValueError("Galat status: " + ", ".join(sorted(set(bad_status.values()))) + ".")
    if not statuses:
        raise ValueError("Kam se kam ek student ki attendance lagaayein.")
    term = current_term()
    with db.connect() as con:
        ensure_section(con, section)
        row = con.execute("SELECT id FROM attendance_sessions WHERE class_section = ? AND subject_code = ? "
                          "AND session_date = ? AND period = ?", (section, subject_code, d.isoformat(), int(period))).fetchone()
        if row:
            sid = row[0]
        else:
            sid = con.execute("INSERT INTO attendance_sessions(class_section, subject_code, term_id, session_date, period, "
                              "taken_by, created_at) VALUES (?,?,?,?,?,?,?)",
                              (section, subject_code, term["id"] if term else None, d.isoformat(), int(period),
                               actor.get("username"), db.now())).lastrowid
        con.executemany("INSERT INTO attendance_records(session_id, student_id, status) VALUES (?,?,?) "
                        "ON CONFLICT(session_id, student_id) DO UPDATE SET status = excluded.status",
                        [(sid, s, v) for s, v in statuses.items()])
        audit.log("attendance.record", actor, "attendance_session", sid,
                  {"section": section, "subject": subject_code, "date": d.isoformat(), "period": int(period),
                   "present": sum(v in ATTENDED for v in statuses.values()), "marked": len(statuses)}, con=con)
    return sid


def student_attendance(student_id: str, subject_code: str | None = None) -> dict:
    """held / attended / percentage for one student (optionally one subject). None pct when no sessions."""
    sql = ("SELECT SUM(r.status IN ('present','late')) AS attended, SUM(r.status != 'excused') AS held "
           "FROM attendance_records r JOIN attendance_sessions s ON s.id = r.session_id WHERE r.student_id = ?")
    params = [student_id]
    if subject_code:
        sql += " AND s.subject_code = ?"
        params.append(subject_code)
    with db.connect() as con:
        r = con.execute(sql, params).fetchone()
    held, att = int(r["held"] or 0), int(r["attended"] or 0)
    return {"held": held, "attended": att, "pct": round(100 * att / held, 1) if held else None}


def by_subject(student_id: str) -> pd.DataFrame:
    df = db.query_df(
        "SELECT s.subject_code, sub.name AS subject, SUM(r.status IN ('present','late')) AS attended, "
        "SUM(r.status != 'excused') AS held FROM attendance_records r JOIN attendance_sessions s ON s.id = r.session_id "
        "LEFT JOIN subjects sub ON sub.code = s.subject_code WHERE r.student_id = ? GROUP BY s.subject_code, sub.name",
        (student_id,))
    if not df.empty:
        df["pct"] = (100 * df["attended"] / df["held"].where(df["held"] > 0)).round(1)
    return df


def section_summary(section: str, subject_code: str | None = None) -> pd.DataFrame:
    """Per-student attendance for a class (and optionally a subject)."""
    sql = ("SELECT st.student_id, st.name, SUM(x.status IN ('present','late')) AS attended, "
           "SUM(x.status != 'excused') AS held FROM students st LEFT JOIN ("
           "SELECT r.student_id, r.status FROM attendance_records r JOIN attendance_sessions s ON s.id = r.session_id"
           + (" WHERE s.subject_code = ?" if subject_code else "")
           + ") x ON x.student_id = st.student_id "
           "WHERE st.class_section = ? AND st.status = 'active' GROUP BY st.student_id, st.name ORDER BY st.student_id")
    params = ((subject_code,) if subject_code else ()) + (section,)
    df = db.query_df(sql, params)
    df[["attended", "held"]] = df[["attended", "held"]].fillna(0).astype(int)
    df["pct"] = (100 * df["attended"] / df["held"].where(df["held"] > 0)).round(1)
    return df


def sessions_df(section: str, subject_code: str) -> pd.DataFrame:
    return db.query_df(
        "SELECT s.id, s.session_date, s.period, s.taken_by, SUM(r.status IN ('present','late')) AS present, "
        "COUNT(r.student_id) AS marked FROM attendance_sessions s LEFT JOIN attendance_records r ON r.session_id = s.id "
        "WHERE s.class_section = ? AND s.subject_code = ? GROUP BY s.id ORDER BY s.session_date DESC, s.period DESC",
        (section, subject_code))
