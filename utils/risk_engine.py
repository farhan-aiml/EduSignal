"""Multi-factor early-warning risk engine.

Risk is NOT just the predicted score. Each rule below adds points to a
0-100 risk score, and every point is traceable to a named factor, the
student's value and the configured threshold, so a teacher can see exactly
why a student was flagged. Thresholds come from Settings (not hard-coded
institutional rules).

Trend rules only fire when real history exists; with a single record they
are reported as "not enough history" rather than guessed.
"""
from __future__ import annotations


def _below(value, threshold, base, per_point, cap):
    gap = threshold - value
    return 0.0 if gap <= 0 else min(cap, base + gap * per_point)


def assess(values: dict, predicted: float, s: dict, history: list[float] | None = None) -> dict:
    """values: model inputs; history: earlier predicted scores, oldest first (excluding current)."""
    history = history or []
    factors = []

    def add(key, label, value, threshold, points, reason, action):
        if points > 0:
            factors.append({"key": key, "factor": label, "value": value, "threshold": threshold,
                            "points": round(points, 1), "reason": reason, "action": action})

    if predicted < s["pass_score"]:
        add("score", "Predicted score", round(predicted, 1), s["pass_score"], 35,
            f"Predicted score is below the pass mark ({s['pass_score']:g}).",
            "Teacher review of overall progress")
    elif predicted < s["watch_score"]:
        add("score", "Predicted score", round(predicted, 1), s["watch_score"], 15,
            f"Predicted score is below the watch level ({s['watch_score']:g}).",
            "Monitor progress over the next assessments")

    a = values["Attendance"]
    add("attendance", "Attendance", a, s["attendance_target"],
        _below(a, s["attendance_target"], 10, 0.75, 25),
        f"Attendance is below the configured target of {s['attendance_target']:g}%.",
        "Attend all remaining classes; check for barriers to attendance")

    v = values["Assignment_Score"]
    add("assignment", "Assignment score", v, s["assignment_min"], _below(v, s["assignment_min"], 8, 0.35, 15),
        f"Assignment score is below {s['assignment_min']:g}.", "Complete pending assignments; seek feedback")

    v = values["Internal_Marks"]
    add("internal", "Internal marks", v, s["internal_min"], _below(v, s["internal_min"], 8, 0.35, 15),
        f"Internal marks are below {s['internal_min']:g}.", "Revise weak concepts; practise past internal papers")

    v = values["Study_Hours"]
    pts = 0 if v >= s["study_hours_min"] else (15 if v < s["study_hours_min"] / 2 else 10)
    add("study_hours", "Study hours/day", v, s["study_hours_min"], pts,
        f"Study time is below {s['study_hours_min']:g} h/day.", "Build a fixed daily study schedule")

    v = values["Previous_Marks"]
    add("previous", "Previous marks", v, s["previous_min"], 10 if v < s["previous_min"] else 0,
        f"Previous marks were below {s['previous_min']:g}.", "Bridge gaps from earlier coursework")

    trend = {"available": len(history) >= 1, "change": None, "declining": False}
    if history:
        change = predicted - history[-1]
        trend.update(change=round(change, 1), declining=change <= -s["decline_points"])
        if trend["declining"]:
            add("decline", "Performance trend", round(change, 1), -s["decline_points"], 15,
                f"Predicted score fell {abs(change):.1f} points since the previous record.",
                "Talk to the student about what changed recently")
        recent = history[-2:] + [predicted]
        poor = sum(p < s["pass_score"] for p in recent)
        if len(recent) >= 3 and poor >= 2:
            add("repeated", "Repeated poor results", poor, 2, 15,
                f"{poor} of the last {len(recent)} records are below the pass mark.",
                "Formal academic support plan")

    score = min(100.0, sum(f["points"] for f in factors))
    level = "High" if score >= s["risk_high"] else "Moderate" if score >= s["risk_moderate"] else "Low"
    overrides = []
    if predicted < s["pass_score"] and level != "High":
        level = "High"
        overrides.append("Predicted score below the pass mark always counts as high risk.")

    factors.sort(key=lambda f: -f["points"])
    intervene = level == "High" or (level == "Moderate" and trend["declining"])
    return {"level": level, "score": round(score, 1), "factors": factors, "trend": trend,
            "overrides": overrides, "intervention_required": intervene,
            "main_concern": factors[0]["factor"] if factors else "No concern"}


def summary_sentence(risk: dict) -> str:
    if not risk["factors"]:
        return "No risk factors triggered. Keep the current routine going."
    names = [f["factor"].lower() for f in risk["factors"][:3]]
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"Driven mainly by {joined}."
