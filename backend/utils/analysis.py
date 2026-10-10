"""One call that runs the whole chain for a student profile:
predict -> explain -> assess risk -> prioritise -> recommend -> plan.
Every page reads from this result, so all pages agree with each other."""
from __future__ import annotations

from backend.ml.explain import explain_one, narrative
from backend.ml.predict import (category_for, extrapolation_notes, grade_for, percentile_in_training,
                        predict_one)
from backend.utils.attendance import attendance_status
from backend.utils.recommendations import improvement_priorities, recommendations, study_plan
from backend.utils.risk_engine import assess


def analyze(bundle, values: dict, settings: dict, history: list[float] | None = None,
            subjects=None, classes_held=None, classes_attended=None) -> dict:
    pred = predict_one(bundle, values)
    exp = explain_one(bundle, values)
    risk = assess(values, pred, settings, history)
    att = attendance_status(values["Attendance"], settings["attendance_target"], classes_held, classes_attended)
    pri = improvement_priorities(bundle, values, settings)
    recs = recommendations(pri, risk, att, values, subjects)
    below, n = percentile_in_training(bundle, pred)
    return {
        "values": values, "prediction": pred, "grade": grade_for(pred), "category": category_for(pred),
        "explanation": exp, "narrative": narrative(exp), "risk": risk, "attendance": att,
        "priorities": pri, "recommendations": recs,
        "plan": study_plan(values, settings, pri, subjects), "subjects": subjects,
        "history": history or [], "percentile": (below, n),
        "extrapolation": extrapolation_notes(bundle, values),
    }
