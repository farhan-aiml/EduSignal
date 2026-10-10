"""Recommendation engine and personalised study plan.

How priorities are chosen (explainable by design):
  1. For each factor a student can change (attendance, assignments,
     internal marks, study hours) that is below its configured target,
     ask the model: "what is the predicted score if only this factor
     reaches its target?" The difference is the estimated gain.
  2. Factors are ranked by that gain. Previous marks cannot be changed
     now, so they are reported but never ranked as an action.
  3. Study time is split across weak subjects (if subject scores exist)
     in proportion to how far each is below 75, plus revision and
     practice blocks tied to the weak factors.

The gains reflect the model's learned association on the training data,
not a guaranteed causal effect; the UI says so.
"""
from __future__ import annotations

from backend.config import FEATURES
from backend.ml.predict import predict_one

TARGET_KEYS = {"Attendance": "attendance_target", "Assignment_Score": "assignment_target",
               "Internal_Marks": "internal_target", "Study_Hours": "study_hours_target"}

ADVICE = {
    "Attendance": ("Attendance", "Attend every class until you are back above {t:g}%.{extra}"),
    "Assignment_Score": ("Assignments", "Finish pending assignments first, then ask for feedback on the last two graded ones."),
    "Internal_Marks": ("Concept revision", "Revise the topics from your weakest internal test and redo its questions without notes."),
    "Study_Hours": ("Study routine", "Increase study time from {v:g} h to {t:g} h a day, in fixed blocks at the same time daily."),
}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def improvement_priorities(bundle, values: dict, s: dict) -> list[dict]:
    base = predict_one(bundle, values)
    out = []
    for f, key in TARGET_KEYS.items():
        target = float(s[key])
        current = float(values[f])
        if current >= target:
            continue
        trial = dict(values, **{f: target})
        gain = predict_one(bundle, trial) - base
        out.append({"feature": f, "label": FEATURES[f]["label"], "current": current, "target": target,
                    "gain": round(gain, 1)})
    out.sort(key=lambda d: -d["gain"])
    for i, d in enumerate(out, 1):
        d["priority"] = i
    return out


def recommendations(priorities: list[dict], risk: dict, attendance: dict, values: dict,
                    subjects=None) -> list[dict]:
    recs = []
    for p in priorities:
        cat, text = ADVICE[p["feature"]]
        extra = ""
        if p["feature"] == "Attendance" and attendance.get("classes_needed"):
            extra = f" That means the next {attendance['classes_needed']} classes in a row."
        recs.append({"category": cat,
                     "text": text.format(t=p["target"], v=p["current"], extra=extra),
                     "why": f"{p['label']} is {p['current']:g}, target {p['target']:g}. "
                            f"The model estimates +{p['gain']:.1f} points if this target is reached.",
                     "gain": p["gain"]})
    if subjects is not None and len(subjects):
        weak = subjects[subjects["score"] < 60].sort_values("score")
        for _, r in weak.head(2).iterrows():
            recs.append({"category": "Weak subject", "text": f"Give {r['subject']} the first study block each day.",
                         "why": f"{r['subject']} is at {r['score']:.0f}%, below 60%.", "gain": None})
    if values["Previous_Marks"] < 50:
        recs.append({"category": "Foundations", "text": "Spend one session a week on prerequisites from last term.",
                     "why": "Previous marks are below 50 and cannot be changed, but gaps from them can be closed.",
                     "gain": None})
    if risk["intervention_required"]:
        recs.append({"category": "Support", "text": "Meet your mentor or class teacher this week to agree a plan.",
                     "why": f"The early-warning system rates this profile {risk['level'].lower()} risk.", "gain": None})
    if not recs:
        recs.append({"category": "Maintain", "text": "Keep your current routine and review each topic weekly.",
                     "why": "All changeable factors meet their targets.", "gain": None})
    return recs


def study_plan(values: dict, s: dict, priorities: list[dict], subjects=None) -> dict:
    """Daily + weekly plan in minutes. Returns blocks with a 'why' for each."""
    daily_h = max(float(values["Study_Hours"]), float(s["study_hours_target"]))
    daily_h = min(daily_h, 8.0)          # keep plans humane
    total = int(round(daily_h * 60 / 15) * 15)
    weak_factor = {p["feature"] for p in priorities}

    blocks = []
    weak_subjects = []
    if subjects is not None and len(subjects):
        ws = subjects[subjects["score"] < 75].sort_values("score")
        weak_subjects = [(r["subject"], float(r["score"])) for _, r in ws.iterrows()]

    reserved = 0
    if "Assignment_Score" in weak_factor:
        blocks.append(("Assignment catch-up", 45, "Assignment score is below target."))
        reserved += 45
    if "Internal_Marks" in weak_factor:
        blocks.append(("Past internal questions", 30, "Internal marks are below target."))
        reserved += 30
    revision = max(15, int(total * 0.2) // 15 * 15)
    remaining = max(0, total - reserved - revision)

    if weak_subjects:
        need = [(sub, 75 - sc) for sub, sc in weak_subjects]
        tot_need = sum(n for _, n in need)
        subject_blocks = []
        for sub, n in need:
            mins = int(round(remaining * n / tot_need / 15)) * 15
            if mins >= 15:
                score = dict(weak_subjects)[sub]
                subject_blocks.append((sub, mins, f"{sub} is at {score:.0f}%, below 75%."))
        blocks = subject_blocks + blocks
    elif remaining:
        blocks.insert(0, ("Current coursework", remaining, "No subject scores recorded, so time goes to current topics."))
    blocks.append(("Revision of today's classes", revision, "Short daily review improves retention."))

    today = [{"order": i, "activity": a, "minutes": m, "why": w} for i, (a, m, w) in enumerate(blocks, 1)]

    weekly = []
    rotation = [b for b in blocks if b[0] not in ("Revision of today's classes",)] or blocks
    for i, day in enumerate(DAYS[:5]):
        first = rotation[i % len(rotation)]
        weekly.append({"day": day, "focus": first[0], "minutes": total})
    weekly.append({"day": "Saturday", "focus": "Timed practice test on the weakest area", "minutes": max(60, total // 2)})
    weekly.append({"day": "Sunday", "focus": "Light review and plan next week", "minutes": 30})

    return {"daily_minutes": sum(m for _, m, _ in blocks), "daily_hours_target": daily_h,
            "today": today, "weekly": weekly, "weak_subjects": weak_subjects}
