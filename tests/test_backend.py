"""Backend, database and security tests on a throwaway database.

Run:  python -m tests.test_backend
(Runs on a temporary SQLite file; refuses to run against data/app.db.)
"""
import os
import sqlite3
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="edusignal_test_")) / "test.db"
os.environ["EDUSIGNAL_DB_PATH"] = str(_TMP)
os.environ["EDUSIGNAL_MAX_LOGIN_ATTEMPTS"] = "3"
os.environ["EDUSIGNAL_LOCKOUT_SECONDS"] = "2"

import config  # noqa: E402

if Path(config.DB_PATH) != _TMP:   # config was imported earlier with the real path: never touch real data
    raise RuntimeError("Run this file on its own: python -m tests.test_backend")

import pandas as pd  # noqa: E402

from database import database as db  # noqa: E402
from database import migrations  # noqa: E402
from ml.predict import load_bundle  # noqa: E402
from services import access, assessments, attendance, audit, imports, models, seed, snapshots  # noqa: E402
from services.access import PermissionDenied  # noqa: E402
from utils import auth  # noqa: E402
from utils.analysis import analyze  # noqa: E402
from utils.demo_data import generate_demo, seed_dataset_records  # noqa: E402
from utils.validation import validate_dataframe  # noqa: E402

BUNDLE, _ = load_bundle()
ADMIN = {"username": "admin", "role": "admin"}


def setup_module():
    db.init_db(backup=False)
    seed_dataset_records()
    auth.seed_demo_accounts()
    auth.seed_teacher_classes()
    auth.seed_teacher_subjects()
    generate_demo()
    seed.seed_all()
    models.register(BUNDLE)


def _count(table):
    with db.connect() as con:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _user(u):
    return db.get_user(u)


# ---------------- schema and migrations ----------------
def test_migrations_idempotent_and_integrity():
    assert migrations.apply_all(config.DB_PATH, backup=False) == []          # nothing pending twice
    rep = migrations.integrity_report(config.DB_PATH)
    assert rep["integrity"] == "ok" and rep["foreign_key_violations"] == 0 and not rep["pending_migrations"]
    assert rep["records_without_student"] == 0 and rep["marks_above_maximum"] == 0


def test_migration_preserves_existing_v1_data():
    old = _TMP.parent / "v1.db"
    con = sqlite3.connect(old)
    con.executescript(db.SCHEMA)       # an original v1 database with one student and one record
    con.execute("INSERT INTO students(student_id, name, source, created_at) VALUES ('S1','Old','manual','2025-01-01')")
    con.execute("INSERT INTO academic_records(student_id, record_date, attendance, assignment_score, internal_marks, "
                "study_hours, previous_marks, source, created_at) VALUES ('S1','2025-01-01',80,70,70,3,70,'manual','x')")
    con.commit()
    con.close()
    ran = migrations.apply_all(old, backup=True)
    assert len(ran) == len(migrations.MIGRATIONS)
    con = sqlite3.connect(old)
    assert con.execute("SELECT name FROM students WHERE student_id = 'S1'").fetchone()[0] == "Old"
    assert con.execute("SELECT COUNT(*) FROM academic_records").fetchone()[0] == 1
    assert "registration_no" in {r[1] for r in con.execute("PRAGMA table_info(students)")}
    con.close()
    assert list(config.BACKUP_DIR.glob("app_pre_migration_*.db")), "a backup is taken before migrating"


def test_seed_is_repeatable_without_duplicates():
    before = {t: _count(t) for t in ("subjects", "enrollments", "teacher_subjects", "attendance_sessions",
                                     "attendance_records", "assessments", "assessment_marks")}
    seed.seed_all()
    seed.seed_all()
    assert {t: _count(t) for t in before} == before
    assert before["attendance_sessions"] > 0 and before["assessment_marks"] > 0


# ---------------- authentication ----------------
def test_login_success_generic_failures_and_audit():
    acc, err = auth.login("meera", "Meera@123", "teacher")
    assert acc and err is None and acc["last_login_at"]
    _, e1 = auth.login("meera", "wrong-pass1", "teacher")
    _, e2 = auth.login("nobody", "whatever1", "teacher")
    _, e3 = auth.login("meera", "Meera@123", "student")     # right password, wrong role tab
    assert e1 == e2 == auth.GENERIC_FAIL.format(role="teacher")   # never reveals whether an account exists
    assert e3 == auth.GENERIC_FAIL.format(role="student")         # wrong role tab: same generic message for that tab
    log = audit.recent(50, action="login")
    assert (log["outcome"] == "failed").sum() >= 3 and (log["outcome"] == "ok").sum() >= 1
    auth.login("meera", "Meera@123", "teacher")                 # reset counter


def test_lockout_is_server_side_and_expires():
    for _ in range(3):
        auth.login("ajay", "bad-pass-1", "student")
    acc, err = auth.login("ajay", "Ajay@123", "student")        # correct password while locked
    assert acc is None and "Too many failed attempts" in err
    assert _user("ajay")["locked_until"]                         # stored in the DB, survives a page refresh
    time.sleep(2.2)
    acc, err = auth.login("ajay", "Ajay@123", "student")
    assert acc and err is None and _user("ajay")["failed_attempts"] == 0


def test_deactivated_account_cannot_sign_in_and_admin_rules():
    auth.set_active(ADMIN, "fahil", False)
    acc, err = auth.login("fahil", "Fahil@123", "student")
    assert acc is None and "deactivated" in err
    assert auth.authenticate("fahil", "Fahil@123") is None
    auth.set_active(ADMIN, "fahil", True)
    assert auth.login("fahil", "Fahil@123", "student")[0]
    try:
        auth.set_active({"username": "meera", "role": "teacher"}, "fahil", False)
        raise AssertionError("teacher must not deactivate accounts")
    except PermissionDenied:
        pass
    try:
        auth.set_active(ADMIN, "admin", False)
        raise AssertionError("admin must not deactivate themselves")
    except PermissionDenied:
        pass


def test_account_creation_and_password_rules():
    try:
        auth.create_account(ADMIN, "newt", "short", "teacher", "New Teacher")
        raise AssertionError("weak password accepted")
    except ValueError:
        pass
    auth.create_account(ADMIN, "newt", "Teach3r!pass", "teacher", "New Teacher", subject="Physics")
    assert auth.login("newt", "Teach3r!pass", "teacher")[0]["subject"] == "Physics"
    assert "pbkdf2_sha256$" in _user("newt")["password_hash"] and "Teach3r" not in _user("newt")["password_hash"]
    try:
        auth.create_account(ADMIN, "stud2", "Stud3nt!pass", "student", "X", student_id="DEMO-001")
        raise AssertionError("second login for one student accepted")
    except PermissionDenied:
        pass
    auth.reset_password(ADMIN, "newt", "Another1!pass")
    assert auth.authenticate("newt", "Another1!pass")


# ---------------- authorization ----------------
def test_student_and_teacher_data_scopes():
    rahul, meera, arjun = _user("rahul"), _user("meera"), _user("arjun")
    assert access.can_view_student(rahul, "DEMO-001") and not access.can_view_student(rahul, "DEMO-002")
    sec = access.section_of("DEMO-001")
    assert access.can_view_student(meera, "DEMO-001") and sec in access.teacher_sections("meera")
    assert not access.can_view_student(arjun, "DEMO-001")       # arjun teaches ECE only
    assert access.can_manage_section(meera, sec) and not access.can_manage_section(arjun, sec)
    assert not access.can_manage_section(rahul, sec)


# ---------------- attendance ----------------
def test_attendance_recording_rules_and_maths():
    meera = _user("meera")
    sec = access.section_of("DEMO-001")
    roster = list(academics_roster(sec))
    d = (date.today() - timedelta(days=3)).isoformat()
    statuses = {s: "present" for s in roster}
    statuses[roster[0]], statuses[roster[1]] = "absent", "excused"
    before = attendance.student_attendance(roster[0])
    exc_before = attendance.student_attendance(roster[1])
    sid = attendance.record_session(meera, sec, "PY101", d, statuses, period=5)
    again = attendance.record_session(meera, sec, "PY101", d, statuses, period=5)   # same slot updates, no duplicate
    assert sid == again
    after = attendance.student_attendance(roster[0])
    assert after["held"] == before["held"] + 1 and after["attended"] == before["attended"]
    assert attendance.student_attendance(roster[1])["held"] == exc_before["held"]   # excused: not counted as held
    for bad, why in [({"DEMO-999": "present"}, "not in class"), ({roster[0]: "sleeping"}, "bad status")]:
        try:
            attendance.record_session(meera, sec, "PY101", d, bad, period=6)
            raise AssertionError(why)
        except ValueError:
            pass
    try:
        attendance.record_session(meera, sec, "PY101", (date.today() + timedelta(days=2)).isoformat(), statuses)
        raise AssertionError("future date accepted")
    except ValueError:
        pass
    try:
        attendance.record_session(_user("arjun"), sec, "PY101", d, statuses, period=7)
        raise AssertionError("teacher of another class could record attendance")
    except PermissionDenied:
        pass


def academics_roster(sec):
    from services.academics import section_students
    return section_students(sec)["student_id"]


# ---------------- assessments and marks ----------------
def test_marks_validation_is_all_or_nothing():
    meera = _user("meera")
    sec = access.section_of("DEMO-001")
    aid = assessments.create_assessment(meera, sec, "PY101", "Unit test quiz", "quiz", 10, date.today().isoformat())
    try:
        assessments.create_assessment(meera, sec, "PY101", "Unit test quiz", "quiz", 10, date.today().isoformat())
        raise AssertionError("duplicate assessment title accepted")
    except ValueError:
        pass
    roster = list(academics_roster(sec))
    rows = [{"student_id": roster[0], "marks": 8, "absent": False}, {"student_id": roster[1], "marks": 12, "absent": False}]
    try:
        assessments.save_marks(meera, aid, rows)
        raise AssertionError("mark above maximum accepted")
    except ValueError as e:
        assert "No marks were saved" in str(e)
    assert assessments.marks_sheet(aid)["marks"].notna().sum() == 0          # nothing partially written
    rows[1]["marks"] = 9.5
    rows.append({"student_id": roster[2], "marks": None, "absent": True})
    assert assessments.save_marks(meera, aid, rows) == 3
    sheet = assessments.marks_sheet(aid).set_index("student_id")
    assert sheet.loc[roster[1], "marks"] == 9.5 and bool(sheet.loc[roster[2], "absent"])
    summ = assessments.student_summary(roster[3])
    assert summ["missing"] >= 1                                               # no mark entered = missing submission
    try:
        assessments.save_marks(_user("arjun"), aid, rows)
        raise AssertionError("teacher of another class could enter marks")
    except PermissionDenied:
        pass


# ---------------- prediction pipeline ----------------
def test_refresh_builds_snapshot_from_real_data_and_is_reproducible():
    meera = _user("meera")
    sid = "DEMO-001"
    n_before = _count("academic_records")
    res = snapshots.refresh(meera, BUNDLE, sid, db.get_settings())
    assert res["saved"], res
    snap = snapshots.build(sid)
    att = attendance.student_attendance(sid)
    assert abs(snap["values"]["Attendance"] - att["pct"]) < 1e-9 and "Attendance" in snap["computed"]
    snapshots.refresh(meera, BUNDLE, sid, db.get_settings())                  # same day: replaced, not duplicated
    assert _count("academic_records") == n_before + 1
    with db.connect() as con:
        p = con.execute("SELECT model_version, inputs_json, interval_low, interval_high, predicted_score FROM predictions "
                        "WHERE student_id = ? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    assert p["model_version"] == models.version_of(BUNDLE) and p["inputs_json"]
    assert p["interval_low"] <= p["predicted_score"] <= p["interval_high"]
    import json
    from ml.predict import predict_one
    assert abs(predict_one(BUNDLE, json.loads(p["inputs_json"])["values"]) - p["predicted_score"]) < 1e-6
    try:
        snapshots.refresh(_user("arjun"), BUNDLE, sid, db.get_settings())
        raise AssertionError("teacher of another class could refresh predictions")
    except PermissionDenied:
        pass


def test_what_if_never_writes_to_the_database():
    counts = {t: _count(t) for t in ("academic_records", "predictions", "attendance_records", "assessment_marks")}
    base = db.records_df("DEMO-002").iloc[-1]
    vals = {f: float(base[f]) for f in config.FEATURE_NAMES}
    a1 = analyze(BUNDLE, vals, db.get_settings())
    a2 = analyze(BUNDLE, dict(vals, Attendance=min(100, vals["Attendance"] + 10)), db.get_settings())
    assert a2["prediction"] >= a1["prediction"] - 0.5
    assert {t: _count(t) for t in counts} == counts


def test_evaluation_never_uses_training_rows():
    ev = models.evaluate_against_outcomes(BUNDLE, db.get_settings())
    assert ev["rows"] == 0                    # only the 10 dataset (training) rows have final scores: none are used
    assert models.versions_df()["is_active"].sum() == 1


# ---------------- CSV import ----------------
def test_csv_import_is_atomic_deduplicated_and_logged():
    df = pd.DataFrame([
        dict(Student_ID="IMP-T1", Name="Import One", Department="CSE", Class_Section="CSE-A", Record_Date="2026-09-01",
             Attendance=88, Assignment_Score=77, Internal_Marks=70, Study_Hours=3, Previous_Marks=72, Final_Score=74),
        dict(Student_ID="IMP-T2", Name="Import Two", Department="CSE", Class_Section="CSE-A", Record_Date="2026-09-01",
             Attendance=130, Assignment_Score=77, Internal_Marks=70, Study_Hours=3, Previous_Marks=72),
    ])
    rep = validate_dataframe(df)
    assert len(rep.clean) == 1 and len(rep.rejected) == 1
    res = imports.import_records(ADMIN, rep.clean, rep.rejected, "test.csv")
    assert res["imported"] == 1 and res["rejected"] == 1
    res2 = imports.import_records(ADMIN, rep.clean, None, "test.csv")         # same file again
    assert res2["imported"] == 0 and res2["duplicates_in_db"] == 1
    assert len(db.records_df("IMP-T1")) == 1
    errs = imports.batch_errors(res["batch_id"])
    assert len(errs) == 1 and "Attendance outside" in errs.iloc[0]["reason"] and errs.iloc[0]["row_number"] == 3
    try:
        imports.import_records(_user("meera"), rep.clean, None, "x.csv")
        raise AssertionError("teacher could import")
    except PermissionDenied:
        pass


# ---------------- assistant, persistence ----------------
def test_assistant_answers_only_from_the_given_analysis():
    from utils.assistant import answer
    base = db.records_df("DEMO-001").iloc[-1]
    a = analyze(BUNDLE, {f: float(base[f]) for f in config.FEATURE_NAMES}, db.get_settings())
    reply = answer("What is my current risk level?", a, BUNDLE, settings=db.get_settings())
    assert a["risk"]["level"].lower() in reply.lower()
    other = db.query_df("SELECT name FROM students WHERE student_id = 'DEMO-002'").iloc[0]["name"]
    assert other not in reply                                                  # no other student's data


def test_data_persists_across_new_connections():
    con = sqlite3.connect(config.DB_PATH)
    try:
        assert con.execute("SELECT COUNT(*) FROM assessment_marks WHERE entered_by = 'meera'").fetchone()[0] > 0
        assert con.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'marks.save'").fetchone()[0] >= 1
    finally:
        con.close()


if __name__ == "__main__":
    setup_module()
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("passed", name)
            except Exception as e:   # report every failure, not just the first
                failures += 1
                print("FAILED", name, "-", type(e).__name__, e)
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
