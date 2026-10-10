"""Backend, database and security tests on a throwaway database.

Run:  python -m tests.test_backend
(Runs on a temporary SQLite file; refuses to run against backend/data/app.db.)
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

from backend import config  # noqa: E402

if Path(config.DB_PATH) != _TMP:   # config was imported earlier with the real path: never touch real data
    raise RuntimeError("Run this file on its own: python -m tests.test_backend")

import pandas as pd  # noqa: E402

from backend.database import database as db  # noqa: E402
from backend.database import migrations  # noqa: E402
from backend.ml.predict import load_bundle  # noqa: E402
from backend.services import access, assessments, attendance, audit, imports, models, seed, snapshots  # noqa: E402
from backend.services.access import PermissionDenied  # noqa: E402
from backend.utils import auth  # noqa: E402
from backend.utils.analysis import analyze  # noqa: E402
from backend.utils.demo_data import generate_demo, seed_dataset_records  # noqa: E402
from backend.utils.validation import validate_dataframe  # noqa: E402

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
    assert acc is None and "Bahut zyada galat attempts" in err
    assert _user("ajay")["locked_until"]                         # stored in the DB, survives a page refresh
    time.sleep(2.2)
    acc, err = auth.login("ajay", "Ajay@123", "student")
    assert acc and err is None and _user("ajay")["failed_attempts"] == 0


def test_deactivated_account_cannot_sign_in_and_admin_rules():
    auth.set_active(ADMIN, "fahil", False)
    acc, err = auth.login("fahil", "Fahil@123", "student")
    assert acc is None and "deactivate" in err
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
    from backend.services.academics import section_students
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
        assert "Koi marks save nahi hue" in str(e)
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
    from backend.ml.predict import predict_one
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
    assert len(errs) == 1 and "Attendance range" in errs.iloc[0]["reason"] and errs.iloc[0]["row_number"] == 3
    try:
        imports.import_records(_user("meera"), rep.clean, None, "x.csv")
        raise AssertionError("teacher could import")
    except PermissionDenied:
        pass


# ---------------- assistant, persistence ----------------
def test_assistant_answers_only_from_the_given_analysis():
    from backend.utils.assistant import answer
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


# ---------------- study plan tracking ----------------
def test_study_plan_status_persists_and_is_owner_only():
    from backend.services import study_plan
    from backend.utils.analysis import analyze as _an
    base = db.records_df("DEMO-001").iloc[-1]
    a = _an(BUNDLE, {f: float(base[f]) for f in config.FEATURE_NAMES}, db.get_settings())
    tasks = study_plan.sync_today("DEMO-001", a["plan"]["today"])
    assert len(tasks) == len(a["plan"]["today"]) > 0 and set(tasks["status"]) == {"pending"}
    again = study_plan.sync_today("DEMO-001", a["plan"]["today"])          # same day: no duplicates
    assert len(again) == len(tasks)
    rahul, ajay, meera = _user("rahul"), _user("ajay"), _user("meera")
    t1, t2 = int(tasks.iloc[0]["id"]), int(tasks.iloc[1]["id"]) if len(tasks) > 1 else int(tasks.iloc[0]["id"])
    study_plan.set_status(rahul, t1, "completed")
    study_plan.set_status(rahul, t2, "in_progress")
    for who in (ajay, meera, ADMIN):                                        # only the owner can change status
        try:
            study_plan.set_status(who, t1, "pending")
            raise AssertionError(f"{who.get('username')} changed another student's task")
        except PermissionDenied:
            pass
    fresh = study_plan.tasks_for("DEMO-001")                                # new read = what survives a refresh/login
    assert fresh.set_index("id").loc[t1, "status"] == "completed"
    prog = study_plan.progress(fresh)
    assert prog["completed"] >= 1 and prog["pct"] == round(100 * prog["completed"] / prog["total"])
    try:
        study_plan.set_status(rahul, t1, "done")
        raise AssertionError("invalid status accepted")
    except ValueError:
        pass


# ---------------- reports ----------------
def test_reports_formats_and_permissions():
    import io
    from openpyxl import load_workbook
    from backend.services import reports
    for rep in reports.REPORTS:
        for fmt in ("pdf", "xlsx"):
            data, name, mime, meta = reports.export(ADMIN, rep, "institution", None, fmt)
            assert (data[:4] == b"%PDF") if fmt == "pdf" else load_workbook(io.BytesIO(data)).active["A1"].value.startswith("EduSignal")
    df, meta = reports.build(_user("rahul"), "marks", "student", "DEMO-002")   # asks for someone else
    assert set(df["Student ID"]) <= {"DEMO-001"} and meta["scope"] == "Student DEMO-001"
    sp, _ = reports.build(_user("rahul"), "study_plan", "student", None)
    assert len(sp) >= 1                                                        # rows from the tracked tasks above
    for user, args in [(_user("arjun"), ("marks", "class", access.section_of("DEMO-001"))),
                       (_user("rahul"), ("marks", "institution", None)),
                       (_user("arjun"), ("attendance", "student", "DEMO-001"))]:
        try:
            reports.build(user, *args)
            raise AssertionError("unauthorized report allowed")
        except PermissionDenied:
            pass


# ---------------- notifications ----------------
def test_external_channels_unconfigured_are_reported_honestly():
    from backend.utils import notifications
    for k in ("SMTP_HOST", "SMTP_FROM", "SMS_PROVIDER"):
        os.environ.pop(k, None)
    st_ = notifications.channel_status()
    assert not st_["email"]["configured"] and "SMTP_HOST" in st_["email"]["missing"]
    assert not st_["sms"]["configured"]
    alert = {"type": "unit_test", "severity": "high", "message": f"unit test {time.time()}", "student_id": "DEMO-001",
             "recipient_student_id": "DEMO-001"}
    assert notifications.dispatch([alert]) == 1
    assert notifications.dispatch([alert]) == 0                               # duplicate unread alert is skipped
    log = notifications.deliveries_df()
    mine = log[log["message"] == alert["message"]]
    assert set(mine["status"]) == {"not_configured"} and len(mine) == 2       # email + sms, never "sent"
    ok, err = notifications.send_test(ADMIN, "email", "x@y.com")
    assert not ok and "Configure nahi" in err
    try:
        notifications.send_test(_user("meera"), "email", "x@y.com")
        raise AssertionError("teacher could send test messages")
    except PermissionDenied:
        pass
    os.environ.update(SMTP_HOST="127.0.0.1", SMTP_PORT="9", SMTP_FROM="edusignal@test.local", SMTP_TLS="none")
    try:   # configured but unreachable server: must record 'failed' with the error, not 'sent'
        auth.update_contact(_user("rahul"), "rahul", "rahul@example.com", None)
        alert2 = dict(alert, type="unit_test_smtp", message=f"unit test smtp {time.time()}")
        notifications.dispatch([alert2])
        row = notifications.deliveries_df()
        row = row[(row["message"] == alert2["message"]) & (row["channel"] == "email")]
        assert list(row["status"]) == ["failed"] and row.iloc[0]["error"]
    finally:
        for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_FROM", "SMTP_TLS"):
            os.environ.pop(k, None)
    assert auth.update_contact(_user("rahul"), "rahul", "not-an-email", None)   # validation error message
    try:
        auth.update_contact(_user("ajay"), "rahul", "a@b.com", None)
        raise AssertionError("user changed someone else's contact details")
    except PermissionDenied:
        pass


def test_alert_not_duplicated_when_wording_or_value_changes():
    """Regression: re-running alerts created copies when the text changed (new value, or English -> Hinglish)."""
    first = db.add_notification("attendance", "medium", "Attendance is 61%, below target.", "DEMO-005",
                                recipient_student_id="DEMO-005")
    again = db.add_notification("attendance", "medium", "Attendance 59% hai, target se kam hai.", "DEMO-005",
                                recipient_student_id="DEMO-005")
    other = db.add_notification("assignment", "medium", "Assignment score kam hai.", "DEMO-005",
                                recipient_student_id="DEMO-005")
    assert first and again is None and other                  # same type+student skipped, other type allowed
    db.mark_read([first])
    assert db.add_notification("attendance", "medium", "Attendance 58% hai.", "DEMO-005",
                               recipient_student_id="DEMO-005")  # once read, a fresh alert is allowed


# ---------------- assistant chat history ----------------
def test_chat_history_is_private_and_deletable():
    from backend.services import chat
    rahul, ajay = _user("rahul"), _user("ajay")
    cid = chat.start(rahul, "DEMO-001")
    chat.add_exchange(rahul, cid, "Mera risk level kya hai?", "Aap high risk par hain.")
    assert chat.messages(rahul, cid)[0]["content"] == "Mera risk level kya hai?"
    assert cid in chat.conversations(rahul, "DEMO-001")["id"].tolist()
    assert chat.conversations(ajay, "DEMO-001").empty
    for fn in (lambda: chat.messages(ajay, cid), lambda: chat.add_exchange(ajay, cid, "q", "a"),
               lambda: chat.delete(ajay, cid), lambda: chat.messages(ADMIN, cid)):
        try:
            fn()
            raise AssertionError("another account accessed a private conversation")
        except PermissionDenied:
            pass
    try:
        chat.start(ajay, "DEMO-001")
        raise AssertionError("student started a chat about another student")
    except PermissionDenied:
        pass
    chat.delete(rahul, cid)
    assert _count_where("assistant_messages", "conversation_id", cid) == 0   # messages removed, not hidden


def _count_where(table, col, val):
    with db.connect() as con:
        return con.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (val,)).fetchone()[0]


# ---------------- training workflow ----------------
def test_training_uses_real_rows_and_holds_out_a_test_set():
    import numpy as np
    from backend.ml.train_model import train
    from backend.services import training
    data, rep = training.assemble()
    assert rep["demo_excluded"] == 0 and all("demo" not in k for k in rep["sources"])
    assert "database: import" in rep["sources"]                               # the imported row with a Final_Score
    assert training.readiness({"rows": 3})["level"] == "blocked"
    # 60 rows of TEST-ONLY data (never saved) to exercise the hold-out path
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"Attendance": rng.uniform(50, 100, 60), "Assignment_Score": rng.uniform(40, 100, 60),
                      "Internal_Marks": rng.uniform(40, 100, 60), "Study_Hours": rng.uniform(1, 6, 60),
                      "Previous_Marks": rng.uniform(40, 95, 60)})
    X["Final_Score"] = (0.3 * X["Attendance"] + 0.2 * X["Assignment_Score"] + 0.3 * X["Internal_Marks"]
                        + 2 * X["Study_Hours"] + 0.1 * X["Previous_Marks"] + rng.normal(0, 3, 60)).clip(0, 100)
    b = train(data=X, save=False)
    assert b["holdout"] and b["holdout"]["rows"] == 12 and b["holdout"]["train_rows"] == 48
    assert b["holdout"]["MAE"] < b["holdout"]["baseline_MAE"]                  # beats predicting the mean
    assert not any("Alag test set nahi" in lim for lim in b["limitations"])


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
