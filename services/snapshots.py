"""Feature snapshots: turn raw attendance and assessment data into the model's five inputs,
then refresh the student's prediction, risk assessment, recommendations and alerts.

Sources (stated on every snapshot, never guessed):
  Attendance        <- attendance sessions (present/late over held, excused excluded)
  Assignment_Score  <- average % of assignments and quizzes
  Internal_Marks    <- average % of internal tests and semester exams
  Study_Hours       <- carried forward from the latest record (self-reported; not measured)
  Previous_Marks    <- carried forward from the latest record (last term's result)
If a source has no data yet, the latest record's value is carried forward and labelled as such.
"""
from __future__ import annotations

from datetime import date as _date

from config import FEATURE_NAMES
from database import database as db
from services import access, audit, models
from services.assessments import student_summary
from services.attendance import student_attendance


def build(student_id: str) -> dict:
    rec = db.records_df(student_id)
    last = rec.iloc[-1] if not rec.empty else None
    values, sources = {}, {}

    def carry(f, why):
        if last is not None:
            values[f], sources[f] = float(last[f]), f"carried forward ({why})"
        else:
            values[f], sources[f] = None, "no data"

    att = student_attendance(student_id)
    if att["pct"] is not None:
        values["Attendance"], sources["Attendance"] = att["pct"], f"{att['attended']} of {att['held']} sessions"
    else:
        carry("Attendance", "no attendance sessions yet")
    summ = student_summary(student_id)
    for f, key, label in [("Assignment_Score", "assignment_pct", "assignments and quizzes"),
                          ("Internal_Marks", "internal_pct", "internal tests")]:
        if summ[key] is not None:
            values[f], sources[f] = summ[key], f"average of {label}"
        else:
            carry(f, f"no {label} marked yet")
    carry("Study_Hours", "self-reported")
    carry("Previous_Marks", "last term's result")
    computed = [f for f in ("Attendance", "Assignment_Score", "Internal_Marks") if not sources[f].startswith(("carried", "no"))]
    return {"student_id": student_id, "values": values, "sources": sources, "computed": computed,
            "complete": all(values[f] is not None for f in FEATURE_NAMES), "held": att["held"],
            "attended": att["attended"], "missing_assessments": summ["missing"], "as_of": _date.today().isoformat(),
            "last_record_date": None if last is None else last["record_date"]}


def refresh(actor: dict, bundle: dict, student_id: str, settings: dict) -> dict:
    """Save a new 'computed' record from the snapshot and a full prediction + risk check.
    Re-running on the same day updates that day's computed record instead of duplicating it."""
    from utils import notifications
    from utils.analysis import analyze
    from ml.predict import predict_many
    sec = access.section_of(student_id)
    access.require(sec is not None, "Student nahi mila.")
    access.require(access.can_manage_section(actor, sec), f"Aap class {sec} ke liye assigned nahi hain.")
    snap = build(student_id)
    if not snap["complete"]:
        return {"student_id": student_id, "saved": False, "reason": "Data kaafi nahi: " +
                ", ".join(f for f in FEATURE_NAMES if snap["values"][f] is None)}
    if not snap["computed"]:
        return {"student_id": student_id, "saved": False, "reason": "Abhi tak attendance ya marks nahi bhare gaye."}
    vals = {f: float(snap["values"][f]) for f in FEATURE_NAMES}
    rec = db.records_df(student_id)
    hist_rec = rec[~((rec["record_date"] == snap["as_of"]) & (rec["source"] == "computed"))]
    history = [float(x) for x in predict_many(bundle, hist_rec)] if not hist_rec.empty else []
    a = analyze(bundle, vals, settings, history, None, snap["held"] or None, snap["attended"] if snap["held"] else None)
    with db.connect() as con:
        old = con.execute("SELECT id FROM academic_records WHERE student_id = ? AND record_date = ? AND source = 'computed'",
                          (student_id, snap["as_of"])).fetchone()
        if old:   # replace today's computed record together with its prediction, risk and recommendations
            pids = "SELECT id FROM predictions WHERE record_id = ?"
            aids = f"SELECT id FROM risk_assessments WHERE prediction_id IN ({pids})"
            con.execute(f"DELETE FROM recommendations WHERE assessment_id IN ({aids})", (old[0],))
            con.execute(f"DELETE FROM risk_assessments WHERE prediction_id IN ({pids})", (old[0],))
            con.execute("DELETE FROM predictions WHERE record_id = ?", (old[0],))
            con.execute("DELETE FROM academic_records WHERE id = ?", (old[0],))
        row = con.execute("SELECT name FROM students WHERE student_id = ?", (student_id,)).fetchone()
    rid = db.add_record(student_id, vals, record_date=snap["as_of"], classes_held=snap["held"] or None,
                        classes_attended=snap["attended"] if snap["held"] else None, source="computed")
    version = models.version_of(bundle)
    db.save_assessment(student_id, rid, a["prediction"], a["grade"], bundle["model_name"], a["risk"],
                       a["recommendations"], model_version=version, inputs={"values": vals, "sources": snap["sources"]},
                       interval=models.interval(bundle, a["prediction"]))
    sent = notifications.dispatch(notifications.build_alerts(student_id, row[0] if row else None, a, settings))
    audit.log("prediction.refresh", actor, "student", student_id,
              {"record_id": rid, "predicted": round(a["prediction"], 1), "risk": a["risk"]["level"],
               "model_version": version, "computed_from": snap["computed"]})
    return {"student_id": student_id, "saved": True, "record_id": rid, "predicted": a["prediction"],
            "risk": a["risk"]["level"], "alerts": sent}


def refresh_section(actor: dict, bundle: dict, section: str, settings: dict) -> list[dict]:
    access.require(access.can_manage_section(actor, section), f"Aap class {section} ke liye assigned nahi hain.")
    from services.academics import section_students
    return [refresh(actor, bundle, sid, settings) for sid in section_students(section)["student_id"]]
