"""Rule-based student assistant (no generative AI).

Each question maps to an intent. Every answer is computed from the student's
own analysis (prediction, Shapley contributions, risk rules, study plan) and,
where it says "the model estimates", from real predictions of the trained
model. Nothing is invented; unknown questions get the list of supported ones.
"""
from __future__ import annotations

import re

from config import FEATURES
from ml.predict import grade_for, predict_one
from utils.risk_engine import assess

QUESTIONS = [
    ("why_low", "Why is my predicted score low?"),
    ("attendance", "How can I improve my attendance?"),
    ("week", "What should I focus on this week?"),
    ("assignment", "How can I improve my assignment marks?"),
    ("biggest", "Which factor is affecting my performance the most?"),
    ("reduce_risk", "How can I reduce my academic risk?"),
    ("risk_level", "What is my current risk level?"),
    ("study_hours", "How many hours should I study daily?"),
    ("next_test", "How can I improve my next test score?"),
    ("target", "What should I do to reach my target score?"),
]
SUGGESTIONS = [q for _, q in QUESTIONS]
BY_TEXT = {q.lower(): i for i, q in QUESTIONS}

PATTERNS = [
    ("target", r"target|goal|reach\b|aim"),
    ("reduce_risk", r"(reduce|lower|decrease|get out of|less).*(risk)"),
    ("risk_level", r"risk level|current risk|am i (at )?risk|my risk"),
    ("why_risk", r"\brisk|flag|warning|danger"),
    ("attendance", r"attend|class(es)?\b|absent|bunk"),
    ("assignment", r"assignment|homework"),
    ("next_test", r"test|exam|internal|quiz"),
    ("study_hours", r"how many hours|hours|study time|how long"),
    ("biggest", r"factor|affect|most|biggest|main reason"),
    ("week", r"week"),
    ("today", r"today|tonight|now|study plan|schedule"),
    ("improve_first", r"first|priorit"),
    ("increase", r"increase|improve|raise|better|boost|higher"),
    ("why_low", r"why.*(score|low|predict)|reason|explain"),
    ("subjects", r"subject|weak|strong"),
    ("trend", r"trend|progress|improving|declin|history"),
    ("model", r"model|accura|reliab|trust|how do you know"),
    ("grade", r"grade|score|marks|predict"),
]

STEP = {"Attendance": 5.0, "Assignment_Score": 5.0, "Internal_Marks": 5.0, "Study_Hours": 0.5}
CAP = {"Attendance": 100.0, "Assignment_Score": 100.0, "Internal_Marks": 100.0, "Study_Hours": 8.0}


def _md(text: str) -> str:
    """Insert a blank line wherever a list ends, so the next sentence isn't absorbed into the last bullet."""
    out, prev_list = [], False
    for line in text.split("\n"):
        is_list = bool(re.match(r"\s*(- |\d+\. )", line))
        if prev_list and not is_list and line.strip():
            out.append("")
        if is_list and out and not prev_list and out[-1].strip():
            out.append("")
        out.append(line)
        prev_list = is_list
    return "\n".join(out)


def detect_intent(q: str) -> str:
    t = q.strip().lower()
    if t in BY_TEXT:
        return BY_TEXT[t]
    for name, pattern in PATTERNS:
        if re.search(pattern, t):
            return name
    return "unknown"


def _lab(f):
    return FEATURES[f]["label"].lower()


def _fmt(f, v):
    return f"{v:g}%" if f == "Attendance" else f"{v:g} h" if f == "Study_Hours" else f"{v:g}"


def _gain(bundle, values, f, new):
    return predict_one(bundle, dict(values, **{f: new})) - predict_one(bundle, values)


def plan_to_target(bundle, values: dict, target: float):
    """Search with the real model, spreading effort: each round raises every changeable factor by one small,
    realistic step (5 points, or half an hour of study), most useful first, until the target is reached.
    Study time is capped at the range seen in training so the estimate stays reliable."""
    caps = dict(CAP, Study_Hours=min(CAP["Study_Hours"], bundle["training_ranges"]["Study_Hours"][1]))
    cur = dict(values)
    pred = predict_one(bundle, cur)
    for _ in range(25):
        if pred >= target:
            break
        open_ = [f for f in STEP if cur[f] < caps[f]]
        if not open_:
            break
        gains = {f: predict_one(bundle, dict(cur, **{f: min(caps[f], cur[f] + STEP[f])})) - pred for f in open_}
        moved = False
        for f in sorted(open_, key=lambda k: -gains[k]):
            if gains[f] <= 0:
                continue
            cur[f] = min(caps[f], cur[f] + STEP[f])
            pred = predict_one(bundle, cur)
            moved = True
            if pred >= target:
                break
        if not moved:
            break
    changes = {f: (values[f], cur[f]) for f in STEP if cur[f] != values[f]}
    return pred, changes, pred >= target


def answer(q: str, a: dict, bundle: dict, target: float | None = None, settings: dict | None = None) -> str:
    return _md(_answer(q, a, bundle, target, settings))


def _answer(q, a, bundle, target=None, settings=None) -> str:
    intent = detect_intent(q)
    p, r, v = a["prediction"], a["risk"], a["values"]
    c = a["explanation"]["contributions"]
    pri = {d["feature"]: d for d in a["priorities"]}

    if intent == "why_low":
        neg = [(k, x) for k, x in sorted(c.items(), key=lambda kv: kv[1]) if x < 0]
        lines = [f"Your predicted score is **{p:.1f}** (grade {a['grade']}). {a['narrative']}"]
        if neg:
            lines.append("Factors pulling it below the average student in the training data:")
            lines += [f"- {FEATURES[k]['label']} ({_fmt(k, v[k])}): {x:+.1f} points" for k, x in neg]
        else:
            lines.append("No factor is pulling your score below average.")
        return "\n".join(lines)

    if intent == "attendance":
        at = a["attendance"]
        tgt = at["target"]
        from_classes = at["classes_needed"] is not None or at["can_miss"] is not None
        if from_classes and abs(at["current"] - v["Attendance"]) >= 0.5:
            s = [f"Your overall attendance this term is **{at['current']:g}%** (from classes held and attended); "
                 f"your latest record shows {v['Attendance']:g}%. The target is {tgt:g}%."]
        else:
            s = [f"Your attendance is **{at['current']:g}%** and the target is {tgt:g}%."]
        if at["below_target"]:
            if at["classes_needed"]:
                s.append(f"Attend the next **{at['classes_needed']} classes in a row** to reach {tgt:g}%.")
            else:
                s.append(f"You are {at['gap']:g} points short. Enter classes held and attended on the Early warning page "
                         "to see exactly how many classes you need.")
            g = _gain(bundle, v, "Attendance", tgt)
            s.append(f"The model estimates reaching {tgt:g}% adds about **{g:+.1f} points** to your predicted score.")
        else:
            s.append("You are already on target." + (f" You could miss at most {at['can_miss']} class(es) and stay there."
                                                     if at["can_miss"] is not None else ""))
        s.append("Practical steps: set a fixed time to leave for college, sit near the front, and tell your mentor "
                 "early if something is stopping you from attending.")
        return "\n".join(s)

    if intent == "week":
        plan = a["plan"]
        top = a["priorities"][0] if a["priorities"] else None
        s = [f"This week, aim for about **{plan['daily_hours_target']:g} hours of study a day**."]
        if top:
            s.append(f"Main focus: **{top['label'].lower()}**, from {_fmt(top['feature'], top['current'])} to "
                     f"{_fmt(top['feature'], top['target'])} (about {top['gain']:+.1f} points).")
        s.append("Your week:")
        s += [f"- {d['day']}: {d['focus']} ({d['minutes']} min)" for d in plan["weekly"]]
        return "\n".join(s)

    if intent == "assignment":
        cur = v["Assignment_Score"]
        tgt = settings["assignment_target"] if settings else 75.0
        s = [f"Your assignment score is **{cur:g}** and the plan target is {tgt:g}."]
        if cur < tgt:
            s.append(f"The model estimates reaching {tgt:g} adds about **{_gain(bundle, v, 'Assignment_Score', tgt):+.1f} points**.")
        else:
            nxt = min(100.0, cur + 10)
            s.append(f"You are already on target. Going to {nxt:g} would add about {_gain(bundle, v, 'Assignment_Score', nxt):+.1f} points.")
        s.append("Steps: finish pending work first, start each assignment the day it is set, and ask for feedback "
                 "on your last two graded assignments before the next one.")
        return "\n".join(s)

    if intent == "biggest":
        neg = min(c.items(), key=lambda kv: kv[1])
        pos = max(c.items(), key=lambda kv: kv[1])
        s = []
        if neg[1] < -0.05:
            s.append(f"The factor pulling your score down most is **{_lab(neg[0])}** ({_fmt(neg[0], v[neg[0]])}), "
                     f"at {neg[1]:+.1f} points compared with the average student.")
        if pos[1] > 0.05:
            s.append(f"The factor helping you most is **{_lab(pos[0])}** ({_fmt(pos[0], v[pos[0]])}), at {pos[1]:+.1f} points.")
        if not s:
            s.append("Your factors are all close to average, so none stands out.")
        s.append("_The model's inputs move together a lot, so this shows how the model weighs them, not proof of cause._")
        return "\n".join(s)

    if intent == "reduce_risk":
        if not r["factors"]:
            return f"You are **{r['level'].lower()} risk** with no warning rules triggered. Keep your routine steady."
        s = [f"Your risk score is **{r['score']:.0f}/100** ({r['level'].lower()} risk). Fixing these removes the most risk:"]
        for f in r["factors"][:4]:
            s.append(f"- {f['reason']} **(+{f['points']:g} risk)**. {f['action']}.")
        if settings:   # simulate fixing every changeable factor at its risk threshold
            fixed = dict(v)
            for key, feat, th in [("attendance", "Attendance", "attendance_target"), ("assignment", "Assignment_Score", "assignment_min"),
                                  ("internal", "Internal_Marks", "internal_min"), ("study_hours", "Study_Hours", "study_hours_min")]:
                fixed[feat] = max(fixed[feat], float(settings[th]))
            new_p = predict_one(bundle, fixed)
            new_r = assess(fixed, new_p, settings, a["history"])
            s.append(f"If attendance, assignments, internal marks and study time all reach their minimum levels, the model "
                     f"predicts **{new_p:.1f}** and risk drops to **{new_r['level'].lower()} ({new_r['score']:.0f}/100)**.")
        return "\n".join(s)

    if intent in ("risk_level", "why_risk"):
        if not r["factors"]:
            return f"You are **{r['level'].lower()} risk** (risk score {r['score']:.0f}/100). No warning rules are triggered."
        s = [f"You are **{r['level'].lower()} risk** with a risk score of **{r['score']:.0f}/100**. Main reasons:"]
        s += [f"- {f['reason']} (+{f['points']:g})" for f in r["factors"][:4]]
        if r["intervention_required"]:
            s.append("Your teacher is likely to arrange a support conversation.")
        return "\n".join(s)

    if intent == "study_hours":
        cur, plan = v["Study_Hours"], a["plan"]
        tgt = plan["daily_hours_target"]
        s = [f"You study about **{_fmt('Study_Hours', cur)}** a day. Your plan suggests **{tgt:g} hours**."]
        g = _gain(bundle, v, "Study_Hours", min(24.0, cur + 1))
        s.append(f"The model estimates one extra hour a day adds about **{g:+.1f} points**.")
        lo, hi = bundle["training_ranges"]["Study_Hours"]
        s.append(f"Students in the training data studied {lo:g}-{hi:g} hours, so estimates beyond {hi:g} hours are less reliable.")
        s.append("Split the time into 45-60 minute blocks with short breaks rather than one long session.")
        return "\n".join(s)

    if intent == "next_test":
        cur = v["Internal_Marks"]
        nxt = min(100.0, cur + 10)
        s = [f"Your internal marks are **{cur:g}**. Raising them to {nxt:g} would add about "
             f"**{_gain(bundle, v, 'Internal_Marks', nxt):+.1f} points** to your predicted final score."]
        weak = None
        if a["subjects"] is not None and len(a["subjects"]):
            w = a["subjects"].sort_values("score").iloc[0]
            weak = f"{w['subject']} ({w['score']:.0f}%)"
        if weak:
            s.append(f"Start with your weakest subject: **{weak}**.")
        s.append("Before the test: redo past internal questions without notes, check answers, then revise only what you got wrong.")
        return "\n".join(s)

    if intent == "target":
        if target is None:
            return "Set your target score in the box above the questions, then ask again."
        if p >= target:
            return f"You are already predicted to reach **{target:g}** (predicted {p:.1f}). Keep your routine steady."
        new_p, changes, ok = plan_to_target(bundle, v, target)
        if not changes:
            return f"The model can't find changes that raise your prediction toward {target:g}."
        s = [f"Your predicted score is {p:.1f}. To reach **{target:g}** (grade {grade_for(target)}), the model suggests:"
             if ok else f"Even with these realistic changes the model predicts **{new_p:.1f}**, short of {target:g}:"]
        s += [f"- {FEATURES[f]['label']}: {_fmt(f, old)} → **{_fmt(f, new)}**" for f, (old, new) in changes.items()]
        s.append(f"Predicted score with these changes: **{new_p:.1f}**.")
        s.append("_Found by testing small steps with the model; try the same values in the What-if simulator._")
        return "\n".join(s)

    if intent in ("improve_first", "increase"):
        if not a["priorities"]:
            return "Every factor you can change already meets its target. Keep your routine steady."
        top = a["priorities"][0]
        lines = [f"Start with **{top['label'].lower()}**: from {_fmt(top['feature'], top['current'])} to "
                 f"{_fmt(top['feature'], top['target'])}, about **{top['gain']:+.1f} points**."]
        lines += [f"{d['priority']}. {d['label']}: {_fmt(d['feature'], d['current'])} → {_fmt(d['feature'], d['target'])} "
                  f"({d['gain']:+.1f})" for d in a["priorities"][1:]]
        return "\n".join(lines)

    if intent == "today":
        plan = a["plan"]
        return "\n".join([f"Today's plan, about {plan['daily_minutes']} minutes:"] +
                         [f"{b['order']}. {b['activity']}: {b['minutes']} min ({b['why']})" for b in plan["today"]])

    if intent == "subjects":
        sub = a["subjects"]
        if sub is None or not len(sub):
            return "No subject-wise scores are recorded yet, so subjects can't be compared."
        ss = sub.sort_values("score")
        return f"Weakest: **{ss.iloc[0]['subject']}** ({ss.iloc[0]['score']:.0f}%). Strongest: **{ss.iloc[-1]['subject']}** ({ss.iloc[-1]['score']:.0f}%)."

    if intent == "trend":
        h = a["history"]
        if not h:
            return "Only one record exists, so there is no trend yet."
        return f"Your predicted score moved from {h[-1]:.1f} to {p:.1f} ({p - h[-1]:+.1f}) since the previous record."

    if intent == "model":
        m = bundle["metrics"]
        return (f"Predictions come from a {bundle['model_name']} trained on {bundle['training_rows']} records, off by "
                f"{m['MAE']:.1f} points on average in validation. The dataset is very small, so treat them as estimates.")

    if intent == "grade":
        return f"Predicted final score **{p:.1f}**, grade **{a['grade']}**, {a['category'].lower()}."

    return "I can answer these questions about your own results:\n" + "\n".join(f"- {s}" for s in SUGGESTIONS)
