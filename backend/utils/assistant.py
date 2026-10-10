"""Rule-based student assistant (no generative AI).

Each question maps to an intent. Every answer is computed from the student's
own analysis (prediction, Shapley contributions, risk rules, study plan) and,
where it says "the model estimates", from real predictions of the trained
model. Nothing is invented; unknown questions get the list of supported ones.
"""
from __future__ import annotations

import re

from backend.config import FEATURES
from backend.ml.predict import grade_for, predict_one
from backend.utils.risk_engine import assess

QUESTIONS = [
    ("why_low", "Mera predicted score kam kyun hai?"),
    ("attendance", "Apni attendance kaise sudhaarun?"),
    ("week", "Is hafte kis cheez par dhyaan dun?"),
    ("assignment", "Assignment marks kaise badhaaun?"),
    ("biggest", "Kaun sa factor meri performance par sabse zyada asar daal raha hai?"),
    ("reduce_risk", "Apna academic risk kaise kam karun?"),
    ("risk_level", "Mera current risk level kya hai?"),
    ("study_hours", "Roz kitne ghante padhna chahiye?"),
    ("next_test", "Agle test ka score kaise sudhaarun?"),
    ("target", "Apna target score paane ke liye kya karun?"),
]
SUGGESTIONS = [q for _, q in QUESTIONS]
BY_TEXT = {q.lower(): i for i, q in QUESTIONS}

# English and Hinglish keywords (checked in order; the first match wins)
PATTERNS = [
    ("target", r"target|goal|reach\b|aim|lakshya|paana|paane"),
    ("reduce_risk", r"(reduce|lower|decrease|get out of|less|kam karu|kam kar|ghata).*(risk)|risk.*(kam|ghata)"),
    ("risk_level", r"risk level|current risk|am i (at )?risk|my risk|mera risk|risk kya"),
    ("why_risk", r"\brisk|flag|warning|danger|khatra"),
    ("attendance", r"attend|class(es)?\b|absent|bunk|haazri|hazri"),
    ("assignment", r"assignment|homework"),
    ("next_test", r"test|exam|internal|quiz|pariksha"),
    ("study_hours", r"how many hours|hours|study time|how long|kitne ghante|ghante|ghanta"),
    ("biggest", r"factor|affect|most|biggest|main reason|asar|sabse zyada"),
    ("week", r"week|hafte|hafta"),
    ("today", r"today|tonight|now|study plan|schedule|aaj|abhi kya"),
    ("improve_first", r"first|priorit|pehle"),
    ("increase", r"increase|improve|raise|better|boost|higher|sudhaar|sudhar|badhaa|badha"),
    ("why_low", r"why.*(score|low|predict)|reason|explain|kyun|kyon|kam kyu|wajah"),
    ("subjects", r"subject|weak|strong|kamzor|mazboot"),
    ("trend", r"trend|progress|improving|declin|history|pragati"),
    ("model", r"model|accura|reliab|trust|how do you know|bharosa"),
    ("grade", r"grade|score|marks|predict|number"),
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

    if intent == "why_low":
        neg = [(k, x) for k, x in sorted(c.items(), key=lambda kv: kv[1]) if x < 0]
        lines = [f"Aapka predicted score **{p:.1f}** hai (grade {a['grade']}). {a['narrative']}"]
        if neg:
            lines.append("Yeh factors aapka score training data ke average student se neeche kheench rahe hain:")
            lines += [f"- {FEATURES[k]['label']} ({_fmt(k, v[k])}): {x:+.1f} points" for k, x in neg]
        else:
            lines.append("Koi bhi factor aapka score average se neeche nahi kheench raha.")
        return "\n".join(lines)

    if intent == "attendance":
        at = a["attendance"]
        tgt = at["target"]
        from_classes = at["classes_needed"] is not None or at["can_miss"] is not None
        if from_classes and abs(at["current"] - v["Attendance"]) >= 0.5:
            s = [f"Is term aapki overall attendance **{at['current']:g}%** hai (hui aur attend ki gayi classes se); "
                 f"latest record mein {v['Attendance']:g}% hai. Target {tgt:g}% hai."]
        else:
            s = [f"Aapki attendance **{at['current']:g}%** hai aur target {tgt:g}% hai."]
        if at["below_target"]:
            if at["classes_needed"]:
                s.append(f"{tgt:g}% tak pahunchne ke liye agli **{at['classes_needed']} classes lagaataar** attend karein.")
            else:
                s.append(f"Aap {at['gap']:g} points peeche hain. Kitni classes chahiye, yeh dekhne ke liye Early warning page "
                         "par hui aur attend ki gayi classes bharein.")
            g = _gain(bundle, v, "Attendance", tgt)
            s.append(f"Model ke andaaze se {tgt:g}% tak pahunchne par predicted score mein lagbhag **{g:+.1f} points** judenge.")
        else:
            s.append("Aap pehle se target par hain." + (f" Aap zyada se zyada {at['can_miss']} class(es) chhod kar bhi target par rahenge."
                                                       if at["can_miss"] is not None else ""))
        s.append("Practical steps: college jaane ka fixed time rakhein, aage baithein, aur agar kuch attendance mein "
                 "rukaavat daal raha hai toh mentor ko jaldi batayein.")
        return "\n".join(s)

    if intent == "week":
        plan = a["plan"]
        top = a["priorities"][0] if a["priorities"] else None
        s = [f"Is hafte roz lagbhag **{plan['daily_hours_target']:g} ghante padhai** ka lakshya rakhein."]
        if top:
            s.append(f"Main focus: **{top['label'].lower()}**, {_fmt(top['feature'], top['current'])} se "
                     f"{_fmt(top['feature'], top['target'])} tak (lagbhag {top['gain']:+.1f} points).")
        s.append("Aapka hafta:")
        s += [f"- {d['day']}: {d['focus']} ({d['minutes']} min)" for d in plan["weekly"]]
        return "\n".join(s)

    if intent == "assignment":
        cur = v["Assignment_Score"]
        tgt = settings["assignment_target"] if settings else 75.0
        s = [f"Aapka assignment score **{cur:g}** hai aur plan target {tgt:g} hai."]
        if cur < tgt:
            s.append(f"Model ke andaaze se {tgt:g} tak pahunchne par lagbhag **{_gain(bundle, v, 'Assignment_Score', tgt):+.1f} points** judenge.")
        else:
            nxt = min(100.0, cur + 10)
            s.append(f"Aap pehle se target par hain. {nxt:g} tak jaane par lagbhag {_gain(bundle, v, 'Assignment_Score', nxt):+.1f} points judenge.")
        s.append("Steps: pehle pending kaam poora karein, har assignment usi din shuru karein jis din mile, aur agle se "
                 "pehle pichhle do checked assignments par feedback maangein.")
        return "\n".join(s)

    if intent == "biggest":
        neg = min(c.items(), key=lambda kv: kv[1])
        pos = max(c.items(), key=lambda kv: kv[1])
        s = []
        if neg[1] < -0.05:
            s.append(f"Aapka score sabse zyada **{_lab(neg[0])}** ({_fmt(neg[0], v[neg[0]])}) neeche kheench raha hai: "
                     f"average student ke mukaable {neg[1]:+.1f} points.")
        if pos[1] > 0.05:
            s.append(f"Sabse zyada madad **{_lab(pos[0])}** ({_fmt(pos[0], v[pos[0]])}) kar raha hai: {pos[1]:+.1f} points.")
        if not s:
            s.append("Aapke saare factors average ke aas-paas hain, isliye koi alag se nahi dikhta.")
        s.append("_Model ke inputs aapas mein kaafi jude hain, isliye yeh batata hai ki model unhe kaise tolta hai, yeh wajah ka saboot nahi._")
        return "\n".join(s)

    if intent == "reduce_risk":
        if not r["factors"]:
            return f"Aap **{r['level'].lower()} risk** par hain aur koi warning rule trigger nahi hua. Apna routine steady rakhein."
        s = [f"Aapka risk score **{r['score']:.0f}/100** hai ({r['level'].lower()} risk). Inhe theek karne se sabse zyada risk ghatega:"]
        for f in r["factors"][:4]:
            s.append(f"- {f['reason']} **(+{f['points']:g} risk)**. {f['action']}.")
        if settings:   # simulate fixing every changeable factor at its risk threshold
            fixed = dict(v)
            for key, feat, th in [("attendance", "Attendance", "attendance_target"), ("assignment", "Assignment_Score", "assignment_min"),
                                  ("internal", "Internal_Marks", "internal_min"), ("study_hours", "Study_Hours", "study_hours_min")]:
                fixed[feat] = max(fixed[feat], float(settings[th]))
            new_p = predict_one(bundle, fixed)
            new_r = assess(fixed, new_p, settings, a["history"])
            s.append(f"Agar attendance, assignments, internal marks aur study time sab minimum level tak pahunchein, toh model "
                     f"**{new_p:.1f}** predict karta hai aur risk **{new_r['level'].lower()} ({new_r['score']:.0f}/100)** tak aa jaata hai.")
        return "\n".join(s)

    if intent in ("risk_level", "why_risk"):
        if not r["factors"]:
            return f"Aap **{r['level'].lower()} risk** par hain (risk score {r['score']:.0f}/100). Koi warning rule trigger nahi hua."
        s = [f"Aap **{r['level'].lower()} risk** par hain, risk score **{r['score']:.0f}/100** hai. Main wajah:"]
        s += [f"- {f['reason']} (+{f['points']:g})" for f in r["factors"][:4]]
        if r["intervention_required"]:
            s.append("Aapke teacher shayad ek support baatcheet rakhenge.")
        return "\n".join(s)

    if intent == "study_hours":
        cur, plan = v["Study_Hours"], a["plan"]
        tgt = plan["daily_hours_target"]
        s = [f"Aap roz lagbhag **{_fmt('Study_Hours', cur)}** padhte hain. Aapka plan **{tgt:g} ghante** suggest karta hai."]
        g = _gain(bundle, v, "Study_Hours", min(24.0, cur + 1))
        s.append(f"Model ke andaaze se roz ek ghanta zyada padhne par lagbhag **{g:+.1f} points** judenge.")
        lo, hi = bundle["training_ranges"]["Study_Hours"]
        s.append(f"Training data ke students {lo:g}-{hi:g} ghante padhte the, isliye {hi:g} ghante se zyada ke andaaze kam bharosemand hain.")
        s.append("Ek lambe session ki jagah 45-60 minute ke blocks mein chhote breaks ke saath padhein.")
        return "\n".join(s)

    if intent == "next_test":
        cur = v["Internal_Marks"]
        nxt = min(100.0, cur + 10)
        s = [f"Aapke internal marks **{cur:g}** hain. Inhe {nxt:g} tak le jaane par predicted final score mein lagbhag "
             f"**{_gain(bundle, v, 'Internal_Marks', nxt):+.1f} points** judenge."]
        weak = None
        if a["subjects"] is not None and len(a["subjects"]):
            w = a["subjects"].sort_values("score").iloc[0]
            weak = f"{w['subject']} ({w['score']:.0f}%)"
        if weak:
            s.append(f"Sabse kamzor subject se shuru karein: **{weak}**.")
        s.append("Test se pehle: purane internal questions bina notes ke dobara karein, answers check karein, phir sirf galat wale revise karein.")
        return "\n".join(s)

    if intent == "target":
        if target is None:
            return "Upar box mein apna target score set karein, phir dobara poochhein."
        if p >= target:
            return f"Aapka prediction pehle se **{target:g}** tak pahunch raha hai (predicted {p:.1f}). Apna routine steady rakhein."
        new_p, changes, ok = plan_to_target(bundle, v, target)
        if not changes:
            return f"Model ko aise badlaav nahi mile jo prediction ko {target:g} ki taraf le jaayein."
        s = [f"Aapka predicted score {p:.1f} hai. **{target:g}** (grade {grade_for(target)}) tak pahunchne ke liye model ka sujhaav:"
             if ok else f"In realistic badlaavon ke saath bhi model **{new_p:.1f}** predict karta hai, jo {target:g} se kam hai:"]
        s += [f"- {FEATURES[f]['label']}: {_fmt(f, old)} → **{_fmt(f, new)}**" for f, (old, new) in changes.items()]
        s.append(f"In badlaavon ke saath predicted score: **{new_p:.1f}**.")
        s.append("_Model ke saath chhote steps test karke nikala gaya; yahi values What-if simulator mein try karein._")
        return "\n".join(s)

    if intent in ("improve_first", "increase"):
        if not a["priorities"]:
            return "Jo factors aap badal sakte hain, woh sab target par hain. Apna routine steady rakhein."
        top = a["priorities"][0]
        lines = [f"**{top['label'].lower()}** se shuru karein: {_fmt(top['feature'], top['current'])} se "
                 f"{_fmt(top['feature'], top['target'])} tak, lagbhag **{top['gain']:+.1f} points**."]
        lines += [f"{d['priority']}. {d['label']}: {_fmt(d['feature'], d['current'])} → {_fmt(d['feature'], d['target'])} "
                  f"({d['gain']:+.1f})" for d in a["priorities"][1:]]
        return "\n".join(lines)

    if intent == "today":
        plan = a["plan"]
        return "\n".join([f"Aaj ka plan, lagbhag {plan['daily_minutes']} minute:"] +
                         [f"{b['order']}. {b['activity']}: {b['minutes']} min ({b['why']})" for b in plan["today"]])

    if intent == "subjects":
        sub = a["subjects"]
        if sub is None or not len(sub):
            return "Abhi koi subject-wise score record nahi hai, isliye subjects compare nahi ho sakte."
        ss = sub.sort_values("score")
        return (f"Sabse kamzor: **{ss.iloc[0]['subject']}** ({ss.iloc[0]['score']:.0f}%). "
                f"Sabse mazboot: **{ss.iloc[-1]['subject']}** ({ss.iloc[-1]['score']:.0f}%).")

    if intent == "trend":
        h = a["history"]
        if not h:
            return "Abhi sirf ek record hai, isliye koi trend nahi hai."
        return f"Pichhle record se aapka predicted score {h[-1]:.1f} se {p:.1f} hua ({p - h[-1]:+.1f})."

    if intent == "model":
        m = bundle["metrics"]
        return (f"Predictions {bundle['model_name']} se aati hain jo {bundle['training_rows']} records par trained hai; "
                f"validation mein average {m['MAE']:.1f} points ka fark tha. Dataset bahut chhota hai, isliye inhe andaaza samjhein.")

    if intent == "grade":
        return f"Predicted final score **{p:.1f}**, grade **{a['grade']}**, {a['category'].lower()}."

    return "Main aapke apne results ke baare mein yeh sawaal ke jawab de sakta hoon:\n" + "\n".join(f"- {s}" for s in SUGGESTIONS)
