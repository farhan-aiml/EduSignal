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

from config import FEATURES
from ml.predict import predict_one

TARGET_KEYS = {"Attendance": "attendance_target", "Assignment_Score": "assignment_target",
               "Internal_Marks": "internal_target", "Study_Hours": "study_hours_target"}

ADVICE = {
    "Attendance": ("Attendance", "Har class attend karein jab tak attendance {t:g}% se upar na aa jaaye.{extra}"),
    "Assignment_Score": ("Assignments", "Pehle pending assignments poore karein, phir pichhle do checked assignments par feedback maangein."),
    "Internal_Marks": ("Concept revision", "Sabse kamzor internal test ke topics revise karein aur uske questions bina notes ke dobara karein."),
    "Study_Hours": ("Study routine", "Padhai roz {v:g} h se {t:g} h tak badhaayein, roz ek hi time par fixed blocks mein."),
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
            extra = f" Matlab agli {attendance['classes_needed']} classes lagaataar."
        recs.append({"category": cat,
                     "text": text.format(t=p["target"], v=p["current"], extra=extra),
                     "why": f"{p['label']} abhi {p['current']:g} hai, target {p['target']:g}. "
                            f"Model ke andaaze se target poora hone par +{p['gain']:.1f} points.",
                     "gain": p["gain"]})
    if subjects is not None and len(subjects):
        weak = subjects[subjects["score"] < 60].sort_values("score")
        for _, r in weak.head(2).iterrows():
            recs.append({"category": "Kamzor subject", "text": f"Roz pehla study block {r['subject']} ko dein.",
                         "why": f"{r['subject']} {r['score']:.0f}% par hai, 60% se neeche.", "gain": None})
    if values["Previous_Marks"] < 50:
        recs.append({"category": "Foundations", "text": "Hafte mein ek session pichhle term ke basic topics par lagaayein.",
                     "why": "Previous marks 50 se neeche hain; unhe badla nahi ja sakta, lekin unki kamiyaan door ki ja sakti hain.",
                     "gain": None})
    if risk["intervention_required"]:
        recs.append({"category": "Support", "text": "Is hafte mentor ya class teacher se milkar plan tay karein.",
                     "why": f"Early-warning system is profile ko {risk['level'].lower()} risk maanta hai.", "gain": None})
    if not recs:
        recs.append({"category": "Banaaye rakhein", "text": "Abhi ka routine jaari rakhein aur har topic hafte mein ek baar revise karein.",
                     "why": "Badalne wale saare factors target par hain.", "gain": None})
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
        blocks.append(("Assignment catch-up", 45, "Assignment score target se neeche hai."))
        reserved += 45
    if "Internal_Marks" in weak_factor:
        blocks.append(("Purane internal questions", 30, "Internal marks target se neeche hain."))
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
                subject_blocks.append((sub, mins, f"{sub} {score:.0f}% par hai, 75% se neeche."))
        blocks = subject_blocks + blocks
    elif remaining:
        blocks.insert(0, ("Abhi ka coursework", remaining, "Subject scores record nahi hain, isliye time abhi ke topics ko jaata hai."))
    blocks.append(("Aaj ki classes ka revision", revision, "Roz ka chhota review yaad rakhne mein madad karta hai."))

    today = [{"order": i, "activity": a, "minutes": m, "why": w} for i, (a, m, w) in enumerate(blocks, 1)]

    weekly = []
    rotation = [b for b in blocks if b[0] not in ("Aaj ki classes ka revision",)] or blocks
    for i, day in enumerate(DAYS[:5]):
        first = rotation[i % len(rotation)]
        weekly.append({"day": day, "focus": first[0], "minutes": total})
    weekly.append({"day": "Saturday", "focus": "Sabse kamzor area par timed practice test", "minutes": max(60, total // 2)})
    weekly.append({"day": "Sunday", "focus": "Halka review aur agle hafte ka plan", "minutes": 30})

    return {"daily_minutes": sum(m for _, m, _ in blocks), "daily_hours_target": daily_h,
            "today": today, "weekly": weekly, "weak_subjects": weak_subjects}
