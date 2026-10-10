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
            f"Predicted score pass mark ({s['pass_score']:g}) se neeche hai.",
            "Teacher overall progress review karein")
    elif predicted < s["watch_score"]:
        add("score", "Predicted score", round(predicted, 1), s["watch_score"], 15,
            f"Predicted score watch level ({s['watch_score']:g}) se neeche hai.",
            "Agle assessments mein progress par nazar rakhein")

    a = values["Attendance"]
    add("attendance", "Attendance", a, s["attendance_target"],
        _below(a, s["attendance_target"], 10, 0.75, 25),
        f"Attendance set kiye gaye {s['attendance_target']:g}% target se kam hai.",
        "Baaki saari classes attend karein; attendance mein rukaavat ki wajah dekhein")

    v = values["Assignment_Score"]
    add("assignment", "Assignment score", v, s["assignment_min"], _below(v, s["assignment_min"], 8, 0.35, 15),
        f"Assignment score {s['assignment_min']:g} se neeche hai.", "Pending assignments poore karein; feedback lein")

    v = values["Internal_Marks"]
    add("internal", "Internal marks", v, s["internal_min"], _below(v, s["internal_min"], 8, 0.35, 15),
        f"Internal marks {s['internal_min']:g} se neeche hain.", "Kamzor concepts revise karein; purane internal papers practice karein")

    v = values["Study_Hours"]
    pts = 0 if v >= s["study_hours_min"] else (15 if v < s["study_hours_min"] / 2 else 10)
    add("study_hours", "Study hours/day", v, s["study_hours_min"], pts,
        f"Padhai ka time {s['study_hours_min']:g} h/day se kam hai.", "Roz ka fixed study schedule banayein")

    v = values["Previous_Marks"]
    add("previous", "Previous marks", v, s["previous_min"], 10 if v < s["previous_min"] else 0,
        f"Previous marks {s['previous_min']:g} se neeche the.", "Pichhle coursework ki kamiyaan door karein")

    trend = {"available": len(history) >= 1, "change": None, "declining": False}
    if history:
        change = predicted - history[-1]
        trend.update(change=round(change, 1), declining=change <= -s["decline_points"])
        if trend["declining"]:
            add("decline", "Performance trend", round(change, 1), -s["decline_points"], 15,
                f"Pichhle record se predicted score {abs(change):.1f} points gira hai.",
                "Student se baat karein ki haal mein kya badla")
        recent = history[-2:] + [predicted]
        poor = sum(p < s["pass_score"] for p in recent)
        if len(recent) >= 3 and poor >= 2:
            add("repeated", "Repeated poor results", poor, 2, 15,
                f"Pichhle {len(recent)} records mein se {poor} pass mark se neeche hain.",
                "Formal academic support plan banayein")

    score = min(100.0, sum(f["points"] for f in factors))
    level = "High" if score >= s["risk_high"] else "Moderate" if score >= s["risk_moderate"] else "Low"
    overrides = []
    if predicted < s["pass_score"] and level != "High":
        level = "High"
        overrides.append("Pass mark se neeche ka predicted score hamesha high risk maana jaata hai.")

    factors.sort(key=lambda f: -f["points"])
    intervene = level == "High" or (level == "Moderate" and trend["declining"])
    return {"level": level, "score": round(score, 1), "factors": factors, "trend": trend,
            "overrides": overrides, "intervention_required": intervene,
            "main_concern": factors[0]["factor"] if factors else "Koi chinta nahi"}


def summary_sentence(risk: dict) -> str:
    if not risk["factors"]:
        return "Koi risk factor trigger nahi hua. Abhi ka routine jaari rakhein."
    names = [f["factor"].lower() for f in risk["factors"][:3]]
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " aur " + names[-1]
    return f"Mainly {joined} ki wajah se."
