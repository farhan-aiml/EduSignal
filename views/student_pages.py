"""Student-facing pages. All read the same analysis from the session context."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import FEATURE_NAMES, FEATURES, RISK_COLORS, SUBJECTS_DEFAULT
from database import database as db
from services import audit
from services import models as model_registry
from ml.explain import global_importance, sensitivity
from ml.predict import predict_many, predict_one
from utils import notifications
from utils.analysis import analyze
from utils.risk_engine import summary_sentence
from utils.validation import validate_inputs
from views.common import (INK, LINE, MUTED, accent, dialog_head, section, analysis, ctx, demo_badge, empty, esc, header,
                          initials, kpis, risk_banner, role, why)


# ---------------- helpers ----------------
def _context_line():
    c = ctx()
    if c["sid"] and c["info"]:
        info = c["info"]
        tag = demo_badge("Demo student, synthetic data") if info.get("is_demo") else ""
        where = ", ".join(x for x in [c["sid"], info.get("class_section")] if x and x != "Unassigned")
        edited = " Prediction page par values edit hui hain, save nahi." if c["edited"] else ""
        name = info["name"] or c["sid"]
        st.markdown(f'<div class="context"><span class="av">{esc(initials(name))}</span><b>{esc(name)}</b>'
                    f'<span class="pill">{esc(where)}</span>{tag}<span>{esc(edited)}</span></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="context"><span class="av">?</span><b>Manual entry</b>'
                    '<span>Yeh saved student nahi hai. Values Prediction page par badlein.</span></div>',
                    unsafe_allow_html=True)


def _trend_kpi(a):
    t = a["risk"]["trend"]
    if not t["available"]:
        return ("Performance trend", "History nahi", "2+ records chahiye", MUTED)
    ch = t["change"]
    col = RISK_COLORS["High"] if t["declining"] else RISK_COLORS["Low"] if ch > 0 else INK
    return ("Performance trend", f"{ch:+.1f}", "pichhle record se", col)


def _kpi_strip(a, s):
    r = a["risk"]
    v = a["values"]
    kpis([
        ("Predicted score", f"{a['prediction']:.1f}", f"Grade {a['grade']}, {a['category'].lower()}", None),
        ("Risk level", r["level"], f"Risk score {r['score']:.0f}/100", RISK_COLORS[r["level"]]),
        ("Attendance", f"{v['Attendance']:g}%", f"Target {s['attendance_target']:g}%",
         RISK_COLORS["High"] if v["Attendance"] < s["attendance_target"] else None),
        ("Study hours", f"{v['Study_Hours']:g} h", f"Target {s['study_hours_target']:g} h/day", None),
        _trend_kpi(a),
    ])


def _extrapolation(a):
    if a["extrapolation"]:
        st.warning("Kam bharosemand: kuch inputs training data ki range se bahar hain. " + "; ".join(a["extrapolation"]) + ".")


def _inputs_vs_targets(a, s):
    v = a["values"]
    targets = {"Attendance": s["attendance_target"], "Assignment_Score": s["assignment_target"],
               "Internal_Marks": s["internal_target"], "Previous_Marks": s["previous_min"]}
    labels = [FEATURES[f]["label"] for f in targets]
    vals = [v[f] for f in targets]
    colors = [accent() if v[f] >= t else RISK_COLORS["High"] for f, t in targets.items()]
    fig = go.Figure(go.Bar(x=vals, y=labels, orientation="h", marker_color=colors,
                           text=[f"{x:g}" for x in vals], textposition="outside", name="Abhi"))
    fig.add_trace(go.Scatter(x=list(targets.values()), y=labels, mode="markers", name="Target",
                             marker=dict(symbol="line-ns", size=26, line=dict(width=3, color=INK))))
    fig.update_layout(height=260, xaxis=dict(range=[0, 108], title=None), yaxis=dict(autorange="reversed"),
                      legend=dict(orientation="h", y=-0.15), title="Abhi vs target (0-100 scale)")
    st.plotly_chart(fig)


# ---------------- pages ----------------
@st.dialog("Yeh recommendation kyun?", width="medium")
def _rec_dialog(r: dict, a: dict):
    dialog_head("spark", r["category"], r["text"])
    st.markdown(f"**Wajah.** {r['why']}")
    if r.get("gain"):
        g1, g2 = st.columns(2)
        g1.metric("Abhi ka prediction", f"{a['prediction']:.1f}")
        g2.metric("Target poora hone par", f"{a['prediction'] + r['gain']:.1f}", f"{r['gain']:+.1f}")
        why("Model ne purane records se andaaza lagaya hai. Yeh guide hai, guarantee nahi.")
    pages = st.session_state.get("pages", {})
    c1, c2 = st.columns(2)
    if "what-if" in pages:
        c1.page_link(pages["what-if"], label="Simulator mein try karein", icon=":material/tune:")
    if "study-plan" in pages:
        c2.page_link(pages["study-plan"], label="Mera study plan kholein", icon=":material/menu_book:")


def _rec_cards(recs: list[dict], a: dict, limit: int = 3):
    """Clean action cards; each opens a details pop-up with the reason and the model's estimate."""
    cols = st.columns(max(3, min(limit, len(recs))), gap="medium")
    for i, (col, r) in enumerate(zip(cols, recs[:limit]), 1):
        with col:
            with st.container(key=f"act{i}"):
                st.markdown(f'<div class="acat">{esc(r["category"])}</div>', unsafe_allow_html=True)
                st.markdown(r["text"])
                if r.get("gain"):
                    why(f"Andaazit fayda +{r['gain']:.1f} points")
                if st.button("Kyun?", key=f"recwhy{i}", icon=":material/info:", type="tertiary"):
                    _rec_dialog(r, a)


def _quick_links():
    pages = st.session_state.get("pages", {})
    links = [("what-if", "Sudhaar karun toh?", ":material/tune:"), ("study-plan", "Aaj ka study plan", ":material/menu_book:"),
             ("assistant", "Assistant se poochhein", ":material/forum:"), ("explain", "Yeh score kyun?", ":material/psychology:")]
    links = [l for l in links if l[0] in pages]
    if not links:
        return
    cols = st.columns(len(links))
    for col, (path, label, ic) in zip(cols, links):
        col.page_link(pages[path], label=label, icon=ic, width="stretch")


def _progress_chart(sid):
    """Predicted score (and attendance) across this student's saved records."""
    if not sid:
        empty("Progress dekhne ke liye sidebar mein student chunein.")
        return
    rec = db.records_df(sid)
    if len(rec) < 2:
        empty("Abhi sirf ek record hai. Agla record save hone ke baad progress dikhega.")
        return
    rec = rec.assign(Predicted=predict_many(ctx()["bundle"], rec).round(1))
    first, last = rec["Predicted"].iloc[0], rec["Predicted"].iloc[-1]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=rec["record_date"], y=rec["Predicted"], name="Predicted score", mode="lines+markers",
                             line=dict(color=accent(), width=3), marker=dict(size=8)))
    fig.add_trace(go.Scatter(x=rec["record_date"], y=rec["Attendance"], name="Attendance %", mode="lines+markers",
                             line=dict(color=accent(1), width=2, dash="dot")))
    fig.update_layout(height=270, yaxis=dict(range=[0, 105]), legend=dict(orientation="h", y=-0.22),
                      title=f"{len(rec)} records mein {last - first:+.1f} points")
    st.plotly_chart(fig)


def overview():
    a, s = analysis(), ctx()["settings"]
    header("Overview", "Academic summary: abhi kahan hain, kyun, aur aage kya karna hai.")
    _context_line()
    _kpi_strip(a, s)
    _extrapolation(a)

    left, right = st.columns([1, 1.1], gap="large")
    with left:
        section("Risk level aur main factors", "alert")
        risk_banner(a["risk"], summary_sentence(a["risk"]))
        if a["risk"]["factors"]:
            rc = RISK_COLORS[a["risk"]["level"]]
            st.markdown("".join(f'<div class="factor" style="--rc:{rc}"><span class="pts">+{f["points"]:g}</span>'
                                f'<div><b>{esc(f["factor"])}</b> · {esc(f["reason"])}</div></div>'
                                for f in a["risk"]["factors"][:3]), unsafe_allow_html=True)
        else:
            empty("Koi early-warning rule trigger nahi hua.")
    with right:
        section("Haal ka academic progress", "trend")
        _progress_chart(ctx()["sid"])

    section("Suggested actions", "flag")
    _rec_cards(a["recommendations"], a)

    section("Padhai sudhaarne ke sujhaav", "book")
    l2, r2 = st.columns([1.1, 1], gap="large")
    with l2:
        if a["priorities"]:
            for p in a["priorities"][:3]:
                with st.container(key=f"card_imp{p['priority']}"):
                    st.markdown(f"**{p['priority']}. {p['label']}**: now {p['current']:g}, target {p['target']:g}")
                    st.progress(min(1.0, p["current"] / p["target"]) if p["target"] else 1.0,
                                text=f"Target tak pahunchne par lagbhag +{p['gain']:.1f} points")
        else:
            empty("Jo factors badal sakte hain, woh sab target par hain.")
    with r2:
        plan_ = a["plan"]
        with st.container(key="card_today"):
            st.markdown(f"**Aaj ka study plan**, lagbhag {plan_['daily_minutes']} minute")
            for b in plan_["today"][:4]:
                st.markdown(f"{b['order']}. {b['activity']}, {b['minutes']} min")
            pages = st.session_state.get("pages", {})
            if "study-plan" in pages:
                st.page_link(pages["study-plan"], label="Poora study plan kholein", icon=":material/menu_book:")

    with st.expander("Saved assessment log"):
        act = db.activity_df(ctx()["sid"] if role() == "student" or ctx()["sid"] else None, limit=8)
        if act.empty:
            empty("Abhi koi saved assessment nahi hai. Saved predictions aur risk checks yahan dikhenge.")
        else:
            act["predicted_score"] = act["predicted_score"].round(1)
            st.dataframe(act.rename(columns={"created_at": "Kab", "student_id": "Student", "predicted_score": "Predicted",
                                             "grade": "Grade", "risk_level": "Risk"}), hide_index=True)


def _set_value(f):
    st.session_state["profile_values"][f] = float(st.session_state[f"w_{f}"])


@st.dialog("Yeh record save karein?", width="medium")
def _save_dialog(c, vals, a, s, d):
    dialog_head("db", f"{c['sid']} ka naya record", f"Tareekh {d.isoformat()}. Saved records se student ki history banti hai.")
    kpis([("Predicted score", f"{a['prediction']:.1f}", f"Grade {a['grade']}", None),
          ("Risk level", a["risk"]["level"], f"Risk score {a['risk']['score']:.0f}/100", RISK_COLORS[a["risk"]["level"]])])
    st.markdown(", ".join(f"{FEATURES[f]['label']} **{vals[f]:g}**" for f in FEATURE_NAMES) + ".")
    why("Save karne par prediction aur risk check bhi save hote hain, aur rules ke hisaab se alerts jaate hain.")
    c1, c2 = st.columns(2)
    if c1.button("Cancel Karein", width="stretch"):
        st.rerun()
    if c2.button("Record Save Karein", type="primary", width="stretch", icon=":material/check:"):
        rid = db.add_record(c["sid"], vals, record_date=d.isoformat(), source="manual",
                            classes_held=st.session_state.get("classes_held") or None,
                            classes_attended=st.session_state.get("classes_attended") or None)
        db.save_assessment(c["sid"], rid, a["prediction"], a["grade"], c["bundle"]["model_name"],
                           a["risk"], a["recommendations"], model_version=model_registry.version_of(c["bundle"]),
                           inputs={"values": vals, "sources": "entered on the Prediction page"},
                           interval=model_registry.interval(c["bundle"], a["prediction"]))
        audit.log("record.save", st.session_state["user"], "student", c["sid"],
                  {"record_id": rid, "predicted": round(a["prediction"], 1), "risk": a["risk"]["level"]})
        sent = notifications.dispatch(notifications.build_alerts(c["sid"], c["info"]["name"], a, s))
        st.session_state["profile_for"] = "reload"
        st.session_state["flash"] = f"{c['sid']} ka record save ho gaya. {sent} naye alert bane."
        st.rerun()


INPUT_HELP = {
    "Attendance": "Is term mein kitni classes attend ki (0-100%).",
    "Assignment_Score": "Ab tak ke assignments ka average mark (0-100).",
    "Internal_Marks": "Ab tak ke internal tests ka average mark (0-100).",
    "Study_Hours": "Class ke bahar roz kitne ghante self-study (average).",
    "Previous_Marks": "Pichhle term ka final mark. Yeh ab fix hai, badla nahi ja sakta.",
}


def _targets(s):
    return {"Attendance": s["attendance_target"], "Assignment_Score": s["assignment_target"],
            "Internal_Marks": s["internal_target"], "Study_Hours": s["study_hours_target"],
            "Previous_Marks": s["previous_min"]}


def _confidence(a, b):
    """Honest confidence: starts at 3 and loses a step for each known weakness."""
    level, reasons = 3, []
    if b["training_rows"] < 30:
        level -= 1
        reasons.append(f"Model sirf {b['training_rows']} records par trained hai, isliye validation ke numbers bhi pakke nahi hain.")
    if a["extrapolation"]:
        level -= 1
        reasons.append("Kuch inputs training range se bahar hain: " + "; ".join(a["extrapolation"]) + ".")
    if not reasons:
        reasons.append("Inputs training range ke andar hain aur model kaafi records par validate hua hai.")
    label, col = {3: ("Good", RISK_COLORS["Low"]), 2: ("Moderate", RISK_COLORS["Moderate"]),
                  1: ("Limited", RISK_COLORS["High"])}[max(1, level)]
    return max(1, level), label, col, reasons


def _ring(pred, color):
    circ = 2 * 3.14159 * 60
    fill = max(0.0, min(pred, 100.0)) / 100 * circ
    return (f'<div class="pd-ring"><svg viewBox="0 0 148 148" aria-hidden="true">'
            f'<circle cx="74" cy="74" r="60" fill="none" stroke="var(--line)" stroke-width="12"/>'
            f'<circle class="arc" cx="74" cy="74" r="60" fill="none" stroke="{color}" stroke-width="12" stroke-linecap="round" '
            f'stroke-dasharray="{fill:.1f} {circ:.1f}" transform="rotate(-90 74 74)"/></svg>'
            f'<div class="mid"><b>{pred:.1f}</b><span>100 mein se</span></div></div>')


def _meaning(a, s, b):
    pred = a["prediction"]
    if pred < s["pass_score"]:
        verdict = f"Pass mark {s['pass_score']:g} se neeche. Abhi action zaroori hai."
    elif pred < s["watch_score"]:
        verdict = f"Pass, lekin watch level {s['watch_score']:g} se neeche. Dhyaan rakhna zaroori hai."
    else:
        verdict = f"Watch level {s['watch_score']:g} se aaraam se upar."
    contrib = a["explanation"]["contributions"]
    low = min(contrib, key=contrib.get)
    high = max(contrib, key=contrib.get)
    below, n = a["percentile"]
    parts = [f"Agar yeh paanch inputs aise hi rahe, toh model ke hisaab se final score lagbhag <b>{pred:.0f}</b> hoga "
             f"(80% sambhavna {model_registry.interval(b, pred)[0]:.0f} se {model_registry.interval(b, pred)[1]:.0f} ke beech, "
             f"model {model_registry.version_of(b)})."]
    c = ctx()
    if c["sid"]:
        rec = db.records_df(c["sid"])
        if not rec.empty:
            last = rec.iloc[-1]
            parts.append(f"Inputs <b>{esc(last['record_date'])}</b> ke record se hain ({esc(last['source'])})"
                         + (", is page par edit kiye gaye." if c["edited"] else "."))
    if contrib[low] < -0.05:
        parts.append(f"Score ko sabse zyada neeche kheenchne wala factor <b>{esc(FEATURES[low]['label'].lower())}</b> "
                     f"({contrib[low]:+.1f}).")
    if contrib[high] > 0.05:
        parts.append(f"Score ko sabse zyada upar rakhne wala factor <b>{esc(FEATURES[high]['label'].lower())}</b> "
                     f"({contrib[high]:+.1f}).")
    if n:
        parts.append(f"Yeh {n} training records mein se {below} se zyada hai.")
    return verdict, " ".join(parts)


def _result_card(a, s, b):
    pred, r = a["prediction"], a["risk"]
    rc = RISK_COLORS[r["level"]]
    lvl, clabel, ccol, _ = _confidence(a, b)
    lo, hi = model_registry.interval(b, pred)       # ~80% range from cross-validated residuals
    verdict, meaning = _meaning(a, s, b)
    badges = (f'<span class="pd-badge"><i></i>Grade {esc(a["grade"])}</span>'
              f'<span class="pd-badge" style="--bc:{rc}"><i></i>{r["level"]} risk · {r["score"]:.0f}/100</span>'
              f'<span class="pd-badge" style="--bc:{ccol}" title="Is number par kitna bharosa karein"><i></i>{clabel} confidence</span>')
    if r["trend"]["available"]:
        ch = r["trend"]["change"]
        tc = RISK_COLORS["High"] if r["trend"]["declining"] else RISK_COLORS["Low"] if ch > 0 else "#64748B"
        badges += f'<span class="pd-badge" style="--bc:{tc}"><i></i>{ch:+.1f} vs last record</span>'
    ticks = "".join(f"<span>{x}</span>" for x in (0, 25, 50, 75, 100))
    st.markdown(
        f'<div class="pd-hero"><div class="pd-top">{_ring(pred, rc)}<div class="pd-main">'
        f'<div class="pd-k">Predicted final score</div>'
        f'<div class="pd-title">{esc(a["category"])} · {esc(verdict)}</div><div class="pd-badges">{badges}</div></div></div>'
        f'<div class="pd-scale" style="--pass:{s["pass_score"]:g}%;--watch:{s["watch_score"]:g}%">'
        f'<div class="pd-track"><div class="pd-band" style="left:{lo:.1f}%;width:{max(hi - lo, .8):.1f}%" '
        f'title="Lagbhag 80% sambhavit range: {lo:.1f} se {hi:.1f}"></div>'
        f'<div class="pd-pin" style="left:{pred:.1f}%" data-v="{pred:.1f}"></div></div>'
        f'<div class="pd-ticks">{ticks}</div>'
        f'<div class="pd-legend"><span><i style="background:#FECACA"></i>Pass se neeche ({s["pass_score"]:g})</span>'
        f'<span><i style="background:#FDE68A"></i>Watch zone</span><span><i style="background:#A7F3D0"></i>'
        f'Watch se upar ({s["watch_score"]:g})</span><span><i style="background:color-mix(in srgb, var(--ink) 25%, transparent)"></i>'
        f'80% range {lo:.0f}–{hi:.0f}</span></div></div>'
        f'<div class="pd-mean"><b>Iska matlab.</b> {meaning}</div></div>', unsafe_allow_html=True)


def _confidence_card(a, b):
    lvl, label, col, reasons = _confidence(a, b)
    meter = "".join(f'<span class="{"on" if i < lvl else ""}"></span>' for i in range(3))
    with st.container(key="card_conf"):
        st.markdown(f'<div class="pd-k">Kitna bharosa karein</div>'
                    f'<div class="pd-conf" style="--cc:{col}"><div><div style="font-family:var(--hf);font-weight:700;'
                    f'font-size:1.15rem;color:{col}">{label} confidence</div><div class="meter">{meter}</div></div></div>',
                    unsafe_allow_html=True)
        st.markdown("\n".join(f"- {esc(x)}" for x in reasons))
        why(f"{b['model_name']}, {b['cv_scheme'].lower()}. Typical error ±{b['metrics']['MAE']:.1f}, "
            f"RMSE {b['metrics']['RMSE']:.1f} points.")


def _drivers_card(a):
    contrib = a["explanation"]["contributions"]
    order = sorted(contrib, key=lambda k: -abs(contrib[k]))
    m = max(0.5, max(abs(v) for v in contrib.values()))
    rows = []
    for k in order:
        v = contrib[k]
        w = abs(v) / m * 50
        col = RISK_COLORS["Low"] if v >= 0 else RISK_COLORS["High"]
        pos = f"left:50%;width:{w:.1f}%" if v >= 0 else f"left:{50 - w:.1f}%;width:{w:.1f}%"
        rows.append(f'<div class="drv"><div class="lab" title="{esc(FEATURES[k]["label"])}">{esc(FEATURES[k]["label"])}</div>'
                    f'<div class="axis"><span style="{pos};background:{col}"></span></div>'
                    f'<div class="val" style="color:{col}">{v:+.1f}</div></div>')
    with st.container(key="card_drivers"):
        st.markdown(f'<div class="pd-k">Yeh score kyun</div><div style="font-size:.84rem;color:var(--muted);margin:2px 0 6px">'
                    f'Har factor average prediction mein kitne points jodta ya ghataata hai ({a["explanation"]["base"]:.1f}).</div>'
                    + "".join(rows), unsafe_allow_html=True)
        pages = st.session_state.get("pages", {})
        if "explain" in pages:
            st.page_link(pages["explain"], label="Poori explanation", icon=":material/psychology:")


def _inputs_table(a, s):
    v, t = a["values"], _targets(s)
    rows = []
    for f in FEATURE_NAMES:
        spec = FEATURES[f]
        top = 12.0 if f == "Study_Hours" else 100.0
        ok = v[f] >= t[f]
        col = RISK_COLORS["Low"] if ok else RISK_COLORS["High"] if v[f] < t[f] * .8 else RISK_COLORS["Moderate"]
        unit = spec["unit"]
        tag = '<span class="tag2 ok">Target par</span>' if ok else \
            ('<span class="tag2 bad">Bahut neeche</span>' if col == RISK_COLORS["High"] else '<span class="tag2 warn">Target se neeche</span>')
        fixed = " · fixed" if not spec["actionable"] else ""
        rows.append(f'<div class="inp" style="--bc:{col}"><div class="n">{esc(spec["label"])}{fixed}</div>'
                    f'<div class="v">{v[f]:g}{unit} {tag}</div>'
                    f'<div class="bar"><span style="width:{min(100, v[f] / top * 100):.1f}%"></span>'
                    f'<i style="left:{min(100, t[f] / top * 100):.1f}%"></i></div>'
                    f'<div class="meta"><span>Target {t[f]:g}{unit}</span>'
                    f'<span>{"" if ok else f"{t[f] - v[f]:g}{unit} aur chahiye"}</span></div></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)
    why("Har bar par nishaan Settings mein set target hai. Previous marks ke liye risk threshold use hota hai, kyunki woh badal nahi sakte.")


def _trend_tab(c, b, s):
    sid = c["sid"]
    if not sid:
        empty("Trend ke liye saved records chahiye. Sidebar mein student chunein.", "trend")
        return
    rec = db.records_df(sid)
    if len(rec) < 2:
        empty("Abhi sirf ek record hai. Agla record save hone ke baad trend dikhega.", "trend")
        return
    rec = rec.assign(Predicted=predict_many(b, rec).round(1))
    f1, f2 = st.columns([2, 1])
    measures = f1.pills("Dikhayein", ["Predicted", "Attendance", "Assignment_Score", "Internal_Marks"], default=["Predicted", "Attendance"],
                        selection_mode="multi", key="pd_measures",
                        format_func=lambda m: {"Predicted": "Predicted score", "Assignment_Score": "Assignment",
                                               "Internal_Marks": "Internal"}.get(m, m))
    span = f2.segmented_control("Records", ["All", "Aakhri 3"], default="All", key="pd_span")
    if span == "Aakhri 3":
        rec = rec.tail(3)
    if not measures:
        empty("Kam se kam ek measure chunein.", "chart")
        return
    fig = go.Figure()
    for i, m in enumerate(measures):
        fig.add_trace(go.Scatter(x=rec["record_date"], y=rec[m], mode="lines+markers", name=m.replace("_", " "),
                                 line=dict(width=3 if m == "Predicted" else 2, dash=None if m == "Predicted" else "dot"),
                                 marker=dict(size=8 if m == "Predicted" else 6),
                                 hovertemplate="%{x}<br>%{y:.1f}<extra>" + m.replace("_", " ") + "</extra>"))
    fig.add_hrect(y0=0, y1=s["pass_score"], fillcolor=RISK_COLORS["High"], opacity=0.05, line_width=0)
    fig.add_hline(y=s["pass_score"], line_dash="dot", line_color=RISK_COLORS["High"], annotation_text="pass mark",
                  annotation_position="bottom left")
    first, last = rec["Predicted"].iloc[0], rec["Predicted"].iloc[-1]
    fig.update_layout(height=320, yaxis=dict(range=[0, 105]), legend=dict(orientation="h", y=-0.2),
                      title=f"Predicted score: {len(rec)} records mein {last - first:+.1f} points", hovermode="x unified")
    st.plotly_chart(fig)


def _compare_tab(a, b, c):
    t = b.get("target_values") or []
    options = ["Training records"] + (["Abhi ke students"] if role() in ("teacher", "admin") else [])
    group = st.segmented_control("Kisse compare karein", options, default="Training records", key="pd_cmp") or "Training records"
    if group == "Training records":
        if not t:
            empty("Saved model mein compare karne ke liye training scores nahi hain.", "chart")
            return
        values, label = t, "Training data ke asli final scores"
    else:
        from views.common import scoped_roster
        df, _ = scoped_roster(c["bundle"])
        if df.empty:
            empty("Compare karne ke liye abhi koi student nahi hai.", "users")
            return
        values, label = df["Predicted score"].tolist(), "Abhi ke students ke latest predicted scores"
    fig = go.Figure(go.Histogram(x=values, nbinsx=12, marker_color=accent(), opacity=.85,
                                 hovertemplate="%{x}<br>%{y} records<extra></extra>"))
    fig.add_vline(x=a["prediction"], line_width=3, line_color=INK, annotation_text=f"yeh student {a['prediction']:.1f}",
                  annotation_position="top")
    fig.update_layout(height=300, title=label, xaxis=dict(range=[0, 100], title="Score"), yaxis_title="Records", bargap=.08)
    st.plotly_chart(fig)
    below = sum(v < a["prediction"] for v in values)
    why(f"{len(values)} mein se {below} is prediction se neeche hain. Chhota ya alag group ho toh yeh sirf mota andaaza hai.")


def _model_tab(b):
    m = b["metrics"]
    kpis([("Model in use", b["model_name"], "cross-validation se chuna gaya", None, "chip"),
          ("Typical error (MAE)", f"±{m['MAE']:.2f}", "points", None, "target"),
          ("RMSE", f"{m['RMSE']:.2f}", "points", None, "chart"),
          ("Training records", str(b["training_rows"]), b["trained_at"], None, "db")])
    rng = pd.DataFrame([{"Input": FEATURES[f]["label"], "Sabse kam dekha": lo, "Sabse zyada dekha": hi}
                        for f, (lo, hi) in b["training_ranges"].items()])
    st.dataframe(rng, hide_index=True)
    why("In ranges ke bahar ke inputs extrapolation hain: model wahan andaaza laga raha hai jo usne dekha nahi.")


def _reset_inputs():
    for f in FEATURE_NAMES:
        st.session_state["profile_values"][f] = float(st.session_state["saved_values"][f])
        st.session_state[f"w_{f}"] = float(st.session_state["saved_values"][f])


def prediction():
    c = ctx()
    s, b = c["settings"], c["bundle"]
    who = (c["info"]["name"] if c["sid"] and c["info"] else None)
    header("Prediction", f"{who} ka predicted final score, iska matlab, aur kitna bharosa karein."
           if who else "Model ke paanch inputs bharein. Slider hilaate hi prediction update hoti hai.")
    _context_line()
    if msg := st.session_state.pop("flash", None):
        st.success(msg)
    vals = st.session_state["profile_values"]

    left, right = st.columns([0.85, 1.5], gap="large")
    with left:
        with st.container(key="card_inputs"):
            st.markdown('<div class="pd-k">Inputs</div><div style="font-size:.84rem;color:var(--muted);margin-bottom:6px">'
                        'Slider hilaayein, right side ka har number update hoga.</div>', unsafe_allow_html=True)
            for f in FEATURE_NAMES:
                spec = FEATURES[f]
                key = f"w_{f}"
                if key not in st.session_state:
                    st.session_state[key] = float(vals[f])
                st.slider(spec["label"] + (f" ({spec['unit']})" if spec["unit"] else ""), float(spec["min"]),
                          float(spec["max"]), step=float(spec["step"]), format="%.0f" if spec["step"] >= 1 else "%.1f",
                          key=key, on_change=_set_value, args=(f,), help=INPUT_HELP[f])
            if c["edited"]:
                st.button("Saved values par wapas jaayein", icon=":material/restart_alt:", on_click=_reset_inputs,
                          width="stretch", key="pd_reset")

    problems = validate_inputs(vals)
    if problems:
        with right:
            st.error("Yeh inputs theek karein: " + " ".join(problems))
        return
    a = analysis()
    with right:
        _result_card(a, s, b)
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            _drivers_card(a)
        with c2:
            _confidence_card(a, b)

    section("Prediction ko explore karein", "compass")
    t1, t2, t3, t4 = st.tabs([":material/fact_check: Inputs vs targets", ":material/show_chart: Trend",
                              ":material/groups: Compare", ":material/memory: Model"])
    with t1:
        _inputs_table(a, s)
    with t2:
        _trend_tab(c, b, s)
    with t3:
        _compare_tab(a, b, c)
    with t4:
        _model_tab(b)

    if c["sid"] and role() in ("teacher", "admin"):
        section("Naye record ke roop mein save karein", "db")
        with st.container(key="card_save"):
            s1, s2 = st.columns([1, 1.2], vertical_alignment="bottom")
            d = s1.date_input("Record ki tareekh", value=date.today(), key="save_date")
            if s2.button("Naya Record Save Karein", type="primary", icon=":material/save:", width="stretch"):
                _save_dialog(c, vals, a, s, d)
            why("Save karne par yeh inputs, prediction aur risk check save hote hain, aur rules ke hisaab se alerts jaate hain.")
    elif c["edited"]:
        why("Yeh edit kiye values save nahi hain. Teacher inhe naye record ke roop mein save kar sakte hain.")


def explainable():
    a, c = analysis(), ctx()
    b = c["bundle"]
    header("Explainable AI", "Model ne yeh prediction kyun di, factor-dar-factor.")
    _context_line()
    exp = a["explanation"]
    st.info(a["narrative"])

    contrib = exp["contributions"]
    order = sorted(contrib, key=lambda k: -abs(contrib[k]))
    fig = go.Figure(go.Waterfall(
        orientation="h", measure=["absolute"] + ["relative"] * len(order) + ["total"],
        y=["Average prediction"] + [f"{FEATURES[k]['label']} = {a['values'][k]:g}" for k in order] + ["This prediction"],
        x=[exp["base"]] + [contrib[k] for k in order] + [0],
        text=[f"{exp['base']:.1f}"] + [f"{contrib[k]:+.1f}" for k in order] + [f"{a['prediction']:.1f}"],
        textposition="outside",
        increasing=dict(marker=dict(color=RISK_COLORS["Low"])), decreasing=dict(marker=dict(color=RISK_COLORS["High"])),
        totals=dict(marker=dict(color=INK)), connector=dict(line=dict(color=LINE))))
    fig.update_layout(height=360, yaxis=dict(autorange="reversed"), title="Is prediction mein har factor ka yogdaan (points)",
                      xaxis=dict(range=[min(0, exp["base"] - 30), 105]))
    st.plotly_chart(fig)

    p, n = st.columns(2)
    pos = [(k, v) for k, v in contrib.items() if v > 0.05]
    neg = [(k, v) for k, v in contrib.items() if v < -0.05]
    with p:
        section("Prediction badhane wale", "trend")
        if pos:
            for k, v in sorted(pos, key=lambda x: -x[1]):
                st.markdown(f"**{FEATURES[k]['label']}**: {v:+.1f}")
        else:
            empty("Koi factor training average se upar nahi hai.")
    with n:
        section("Prediction ghataane wale", "alert")
        if neg:
            for k, v in sorted(neg, key=lambda x: x[1]):
                st.markdown(f"**{FEATURES[k]['label']}**: {v:+.1f}")
        else:
            empty("Koi factor training average se neeche nahi hai.")

    section("Saare students mein performance drivers", "chart")
    imp = global_importance(b)
    fig2 = go.Figure(go.Bar(x=imp.values, y=[FEATURES[k]["label"] for k in imp.index], orientation="h",
                            marker_color=accent(), text=[f"{x:.2f}" for x in imp.values], textposition="outside"))
    fig2.update_layout(height=250, yaxis=dict(autorange="reversed"),
                       title="Har factor ka average yogdaan (points)")
    st.plotly_chart(fig2)
    if b["details"]:
        coef = b["details"]["coefficients"]
        st.markdown("Har unit badlaav par model weights: " + ", ".join(
            f"{FEATURES[k]['label']} {v:+.2f}" for k, v in coef.items()) + ".")

    if st.button("Yeh explanations kaise kaam karti hain", icon=":material/help:"):
        _explain_dialog(b)


@st.dialog("Explanations kaise kaam karti hain", width="large")
def _explain_dialog(b):
    dialog_head("spark", "Exact Shapley values", "Wahi cheez jo SHAP library andaaze se nikaalti hai, yahan exact calculate hoti hai.")
    st.markdown(
        "For each factor, the model is evaluated with and without that factor's real value across every "
        "combination of the other factors (32 combinations), with missing factors filled from the training "
        "data. Contributions always add up exactly to *this prediction minus the average prediction*.\n\n"
        "They describe **how the model uses each input**, not what causes a student's result.")
    for lim in b["limitations"]:
        st.warning(lim)


ACTIONABLE = ["Attendance", "Assignment_Score", "Internal_Marks", "Study_Hours"]
PLAIN_WHY = {
    "Attendance": "Training records mein zyada classes attend karne wale students ke score aam taur par zyada the.",
    "Assignment_Score": "Training records mein zyada assignment marks ke saath final score bhi zyada tha.",
    "Internal_Marks": "Training records mein internal marks final score se kaafi jude hue hain.",
    "Study_Hours": "Training records mein roz zyada padhai ke saath final score bhi zyada tha.",
}


def _reset_scenario():
    for f in FEATURE_NAMES:
        st.session_state[f"wi_{f}"] = float(st.session_state["profile_values"][f])


def _apply_targets():
    _reset_scenario()
    for p in analysis()["priorities"]:
        st.session_state[f"wi_{p['feature']}"] = float(p["target"])


def _bump(feature, amount):
    spec = FEATURES[feature]
    cur = float(st.session_state.get(f"wi_{feature}", st.session_state["profile_values"][feature]))
    st.session_state[f"wi_{feature}"] = float(min(spec["max"], max(spec["min"], cur + amount)))


def _fmt(f, v):
    return f"{v:g}%" if f == "Attendance" else f"{v:g} h" if f == "Study_Hours" else f"{v:g}"


def _change_text(what, old, new):
    return f"{what} stays {old}." if old == new else f"{what} {old} → {new}."


def what_if():
    a, c = analysis(), ctx()
    b, s = c["bundle"], c["settings"]
    header("What-if simulator", "Koi aadat badlein aur dekhein AI model kya predict karta hai. Yahan kuch save nahi hota.")
    _context_line()
    base_vals = st.session_state["profile_values"]
    for f in FEATURE_NAMES:
        st.session_state.setdefault(f"wi_{f}", float(base_vals[f]))

    left, right = st.columns([1.05, 1], gap="large")
    with left:
        section("1. Apni aadatein badlein", "pencil")
        q1, q2 = st.columns(2)
        q1.button("10% zyada classes attend karein", on_click=_bump, args=("Attendance", 10), icon=":material/event_available:", width="stretch")
        q2.button("Roz 1 ghanta zyada padhein", on_click=_bump, args=("Study_Hours", 1), icon=":material/schedule:", width="stretch")
        q3, q4 = st.columns(2)
        q3.button("Saare targets poore karein", on_click=_apply_targets, disabled=not a["priorities"], icon=":material/flag:", width="stretch")
        q4.button("Asli values par wapas jaayein", on_click=_reset_scenario, icon=":material/restart_alt:", width="stretch")
        for f in ACTIONABLE:
            spec = FEATURES[f]
            st.slider(f"{spec['label']} (abhi {_fmt(f, base_vals[f])})", float(spec["min"]),
                      float(max(12, base_vals[f]) if f == "Study_Hours" else spec["max"]), step=float(spec["step"]),
                      format="%.0f" if spec["step"] >= 1 else "%.1f", key=f"wi_{f}")
        st.session_state[f"wi_Previous_Marks"] = float(base_vals["Previous_Marks"])
        why(f"Previous marks ({base_vals['Previous_Marks']:g}) final ho chuke hain, isliye yahan fix rehte hain.")

    scen = {f: float(st.session_state[f"wi_{f}"]) for f in FEATURE_NAMES}
    after = analyze(b, scen, s, a["history"], a["subjects"])
    delta = after["prediction"] - a["prediction"]
    changed = [f for f in ACTIONABLE if abs(scen[f] - base_vals[f]) > 1e-9]

    with right:
        section("2. Scores compare karein", "target")
        word = "badhta hai" if delta > 0.05 else "girta hai" if delta < -0.05 else "wahi rehta hai"
        old_w, new_w = max(0, min(100, a["prediction"])), max(0, min(100, after["prediction"]))
        st.markdown(
            f'<div class="wi-result"><div class="row"><div><div class="cap">Abhi ka prediction</div>'
            f'<div class="wi-num">{a["prediction"]:.1f}</div></div><div class="wi-arrow">→</div>'
            f'<div style="text-align:right"><div class="cap">Aapke badlaav ke saath</div><div class="wi-num">{after["prediction"]:.1f}</div></div></div>'
            f'<div class="wi-bar"><span class="old" style="width:{old_w}%"></span><span class="new" style="width:{new_w}%"></span></div>'
            f'<span class="wi-delta">{delta:+.1f} points</span>'
            f'<div class="wi-sub">Aapka score {word}. {_change_text("Grade", a["grade"], after["grade"])} '
            f'{_change_text("Risk", a["risk"]["level"], after["risk"]["level"])}</div></div>', unsafe_allow_html=True)

        section("3. Kya badla aur kyun", "spark")
        if not changed:
            empty("Left side slider hilaayein ya button dabaayein. Har badlaav ka asar yahan samjhaaya jaayega.")
        else:
            items = []
            for f in changed:
                solo = predict_one(b, dict(base_vals, **{f: scen[f]})) - a["prediction"]
                cls = "up" if solo > 0.05 else "down" if solo < -0.05 else "same"
                items.append(f'<li><b>{FEATURES[f]["label"]}</b> {_fmt(f, base_vals[f])} → {_fmt(f, scen[f])}: '
                             f'<span class="chg {cls}">{solo:+.1f} points</span> akele iska asar. '
                             f'<span class="why">{PLAIN_WHY[f]}</span></li>')
            st.markdown(f'<ul class="wi-why">{"".join(items)}</ul>', unsafe_allow_html=True)
            if len(changed) > 1:
                why(f"Saare badlaav milakar: {delta:+.1f} points.")
        if after["extrapolation"]:
            st.warning("Kuch values model ki dekhi hui range se bahar hain, isliye yeh andaaza mota hai: "
                       + "; ".join(after["extrapolation"]) + ".")
        why("Yeh purane records ke patterns se andaaze hain, guarantee nahi.")

    with st.expander("Dekhein ek aadat score ko step-by-step kaise badalti hai"):
        f = st.selectbox("Aadat", ACTIONABLE, format_func=lambda k: FEATURES[k]["label"], key="wi_sens")
        sens = sensitivity(b, scen, f)
        fig = px.line(sens, x=f, y="Predicted", title=f"{FEATURES[f]['label']} badalne par predicted score")
        fig.update_traces(line_color=accent(), line_width=3)
        lo, hi = b["training_ranges"][f]
        fig.add_vrect(x0=lo, x1=hi, fillcolor=accent(3), opacity=0.6, line_width=0,
                      annotation_text="training mein dekhi range", annotation_position="top left")
        fig.add_scatter(x=[scen[f]], y=[after["prediction"]], mode="markers", name="Aapka scenario",
                        marker=dict(size=12, color=INK))
        fig.update_layout(height=320, showlegend=False, yaxis_title="Predicted score")
        st.plotly_chart(fig)


FOCUS_TIPS = {
    "Assignment catch-up": "Jo assignment sabse pehle due hai, usse shuru karein. Ek poora karke hi agla kholein.",
    "Purane internal questions": "Pehle bina notes ke answer karein, phir check karein. Galat wale questions mark karein taaki dobara dekh sakein.",
    "Aaj ki classes ka revision": "Notes band karein aur har class ke teen main points likhein.",
}
DEFAULT_TIP = "Phone doosre kamre mein rakh dein. Ring bharne tak padhein, phir paanch minute ka break lein."


@st.dialog("Focus session", width="medium")
def _focus_dialog(b):
    dialog_head("clock", b["activity"], f"{b['minutes']} minute. {b['why']}")
    secs = int(b["minutes"]) * 60
    st.markdown(f'''
<div class="focus"><svg viewBox="0 0 120 120" width="170" height="170">
<circle cx="60" cy="60" r="52" fill="none" stroke="var(--soft)" stroke-width="10"/>
<circle class="ring" cx="60" cy="60" r="52" fill="none" stroke="var(--p)" stroke-width="10" stroke-linecap="round"
 pathLength="100" stroke-dasharray="100" stroke-dashoffset="100" transform="rotate(-90 60 60)"
 style="animation: fill {secs}s linear forwards"/></svg>
<div class="fl2"><b>{b["minutes"]}</b><span>minute</span></div></div>''', unsafe_allow_html=True)
    st.markdown(f"**Tip.** {FOCUS_TIPS.get(b['activity'], DEFAULT_TIP)}")
    why("Ring poore session mein bharti hai. Window band karne par ruk jaati hai.")
    if st.button("Ho Gaya", type="primary", width="stretch", icon=":material/check:"):
        st.rerun()


def _set_task(task_id, key):
    from services import study_plan
    try:
        study_plan.set_status(st.session_state["user"], task_id, st.session_state[key])
    except Exception as e:   # PermissionDenied or invalid status: show it, never fake success
        st.session_state["flash_plan"] = str(e)


def _complete_task(task_id):
    from services import study_plan
    try:
        study_plan.set_status(st.session_state["user"], task_id, "completed")
    except Exception as e:
        st.session_state["flash_plan"] = str(e)


def _plan_tracker(sid, today_blocks):
    """Today's blocks as tracked tasks (status saved in the database)."""
    from services import study_plan
    tasks = study_plan.sync_today(sid, today_blocks)
    prog = study_plan.progress(tasks)
    me = st.session_state["user"]
    editable = me.get("role") == "student" and me.get("student_id") == sid
    if msg := st.session_state.pop("flash_plan", None):
        st.error(msg)
    with st.container(key="card_planprog"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Complete", f"{prog['completed']} / {prog['total']}")
        c2.metric("In Progress", prog["in_progress"])
        c3.metric("Pending", prog["pending"])
        c4.metric(f"Padhai (min, kul {prog['minutes']})", prog["minutes_done"])
        st.progress(prog["pct"] / 100, text=f"Aaj ka progress: {prog['pct']}%")
        if not editable:
            why("Yeh progress sirf dekh sakte hain. Status sirf student khud badal sakta hai.")
    tag = {"pending": "", "in_progress": "warn", "completed": "ok"}
    for t in tasks.itertuples():
        with st.container(key=f"card_hover_blk{t.block_order}"):
            st.markdown(f'<div class="step"><span class="sn">{t.block_order}</span><div><b>{esc(t.activity)}</b> '
                        f'<span class="tag2 {tag[t.status]}">{study_plan.LABELS[t.status]}</span>'
                        f'<div class="why">{t.minutes} min. {esc(t.reason or "")}</div></div></div>', unsafe_allow_html=True)
            if editable:
                c1, c2, c3 = st.columns([2.2, 1.3, 1.1], vertical_alignment="center")
                key = f"task_status_{t.id}"
                st.session_state[key] = t.status
                c1.segmented_control("Status", study_plan.STATUSES, key=key, format_func=study_plan.LABELS.get,
                                     on_change=_set_task, args=(t.id, key), label_visibility="collapsed",
                                     required=True, width="stretch")
                c2.button("Complete Karein", key=f"task_done_{t.id}", icon=":material/check:", width="stretch",
                          disabled=t.status == "completed", on_click=_complete_task, args=(t.id,), type="primary")
                if c3.button("Shuru Karein", key=f"focus{t.block_order}", icon=":material/timer:", width="stretch"):
                    _focus_dialog({"activity": t.activity, "minutes": t.minutes, "why": t.reason or ""})
    hist = study_plan.history(me, sid, days=14)
    if len(hist) > 1:
        with st.expander("Pichhle 14 din ka progress"):
            st.dataframe(hist.rename(columns={"plan_date": "Date", "tasks": "Tasks", "completed": "Complete",
                                              "minutes": "Planned min", "minutes_done": "Done min"}), hide_index=True)


def plan():
    a, s = analysis(), ctx()["settings"]
    sid = ctx()["sid"]
    header("Study plan", "Student ki kamzor cheezon aur subjects ke hisaab se bana plan, har item ki wajah ke saath.")
    _context_line()
    p = a["plan"]
    kpis([("Suggested study time", f"{p['daily_hours_target']:g} h/day", f"Abhi {a['values']['Study_Hours']:g} h", None),
          ("Aaj ka plan", f"{p['daily_minutes']} min", f"{len(p['today'])} blocks", None),
          ("Priority areas", str(len(a["priorities"])), "target se neeche", None),
          ("Kamzor subjects", str(len(p["weak_subjects"])) if a["subjects"] is not None else "Data nahi",
           "75% se neeche" if a["subjects"] is not None else "Subject scores record nahi hain", None)])

    section("Priority areas", "target")
    if a["priorities"]:
        pr = pd.DataFrame(a["priorities"])[["priority", "label", "current", "target", "gain"]]
        pr.columns = ["Priority", "Factor", "Abhi", "Target", "Andaazit fayda (points)"]
        st.dataframe(pr, hide_index=True)
        why("Model ke andaaze se ranked: agar sirf yeh factor target tak pahunche toh kitna fayda. Previous marks "
            "shaamil nahi hain kyunki unhe ab badla nahi ja sakta.")
    else:
        empty("Badalne wale saare factors target par hain. Neeche ka plan routine ko steady rakhta hai.")

    left, right = st.columns([1.25, 1], gap="large")
    with left:
        section("Aaj ka plan", "clock", "Status database mein save hota hai")
        if sid:
            _plan_tracker(sid, p["today"])
        else:
            empty("Manual entry profile ka progress save nahi hota. Progress track karne ke liye sidebar mein "
                  "student chunein.", "clock")
            for b in p["today"]:
                with st.container(key=f"card_hover_blk{b['order']}"):
                    c1, c2 = st.columns([3, 1.3], vertical_alignment="center")
                    c1.markdown(f'<div class="step"><span class="sn">{b["order"]}</span><div><b>{esc(b["activity"])}</b>'
                                f'<div class="why">{b["minutes"]} min. {esc(b["why"])}</div></div></div>', unsafe_allow_html=True)
                    if c2.button("Shuru Karein", key=f"focus{b['order']}", icon=":material/timer:", width="stretch"):
                        _focus_dialog(b)
    with right:
        section("Weekly plan", "calendar")
        st.dataframe(pd.DataFrame(p["weekly"]).rename(columns={"day": "Din", "focus": "Main focus",
                                                               "minutes": "Minutes"}), hide_index=True)
    section("Recommendations", "flag")
    _rec_cards(a["recommendations"], a, limit=4)


@st.dialog("Risk kaise calculate hota hai", width="large")
def _rules_dialog(s):
    dialog_head("alert", "Har point ke peeche ek rule hai", "Rules 0-100 risk score mein points jodte hain. Thresholds Settings mein set hote hain.")
    rules = pd.DataFrame([
        ("Predicted score below pass mark", f"below {s['pass_score']:g}", "35"),
        ("Predicted score below watch level", f"below {s['watch_score']:g}", "15"),
        ("Attendance below target", f"below {s['attendance_target']:g}%", "10 + 0.75 per point, max 25"),
        ("Assignment score low", f"below {s['assignment_min']:g}", "8 + 0.35 per point, max 15"),
        ("Internal marks low", f"below {s['internal_min']:g}", "8 + 0.35 per point, max 15"),
        ("Study time low", f"below {s['study_hours_min']:g} h/day", "10, or 15 if below half"),
        ("Previous marks low", f"below {s['previous_min']:g}", "10"),
        ("Predicted score falling", f"drop of {s['decline_points']:g}+ points", "15"),
        ("Repeated poor results", "2 of last 3 below pass", "15"),
    ], columns=["Rule", "Kab lagta hai", "Risk points"])
    st.dataframe(rules, hide_index=True)
    st.markdown(f"🔴 **High** from {s['risk_high']:g} points, 🟡 **Moderate** from {s['risk_moderate']:g}, 🟢 **Low** below that. "
                "Pass mark se neeche ka predicted score hamesha high risk hota hai.")


def _copy_widget(k):
    st.session_state[k] = st.session_state[f"w_{k}"]


def _open_student(sid, page="early-warning"):
    st.session_state["pending_student"] = sid
    st.session_state["_goto"] = page


def _watchlist():
    """Staff view: students to focus on first, highest risk first."""
    from views.common import scope_banner, scoped_roster
    scope_banner()
    df, _ = scoped_roster(ctx()["bundle"])
    if df.empty:
        empty("In classes mein abhi koi student nahi hai.")
        return
    counts = df["Risk"].value_counts()
    legend = "".join(
        f'<div class="lg" style="--rc:{RISK_COLORS[k]}"><i></i>{k} risk <b>{counts.get(k, 0)}</b></div>'
        for k in ["High", "Moderate", "Low"])
    section("Pehle in students par dhyaan dein", "users")
    st.markdown(f'<div class="legend">{legend}</div>', unsafe_allow_html=True)
    top = df[df["Risk"] != "Low"].sort_values(["Risk score", "Predicted score"], ascending=[False, True]).head(6)
    if top.empty:
        empty("Abhi koi student moderate ya high risk par nahi hai.")
        return
    cols = st.columns(3, gap="medium")
    for i, (_, row) in enumerate(top.iterrows()):
        r = row["_risk"]
        f0 = r["factors"][0] if r["factors"] else None
        demo = " (demo)" if row["Demo"] else ""
        with cols[i % 3]:
            st.markdown(
                f'<div class="watch" style="--rc:{RISK_COLORS[r["level"]]}"><span class="tag">{r["level"]} risk, {r["score"]:.0f}/100</span>'
                f'<div class="n" style="margin-top:6px">{esc(row["Name"] or row["Student"])}{demo}</div>'
                f'<div class="m">{esc(row["Student"])}, {esc(row["Class"] or "")}, predicted {row["Predicted score"]:.1f}</div>'
                f'<div class="r"><b>Kyun:</b> {esc(f0["reason"] if f0 else "Kai factors milkar")}</div>'
                f'<div class="a"><b>Action:</b> {esc(f0["action"] if f0 else "Monitor")}</div></div>',
                unsafe_allow_html=True)
            st.button("Yeh student kholein", key=f"ew_open_{row['Student']}", on_click=_open_student,
                      args=(row["Student"],), type="tertiary", icon=":material/arrow_forward:")
    n_more = int((df["Risk"] != "Low").sum()) - len(top)
    if n_more > 0:
        why(f"{n_more} aur students moderate ya high risk par hain. Poori list Teacher dashboard par hai.")


def early_warning():
    a, c = analysis(), ctx()
    s = c["settings"]
    r = a["risk"]
    header("Early warning", "Kaun risk par hai, kyun, aur kya karna hai. Risk ka har point ek dikhne wale rule se aata hai.")
    if role() in ("teacher", "admin"):
        _watchlist()
        section("Chuna hua student", "target")
    _context_line()

    name = c["info"]["name"] if c["sid"] and c["info"] else "Yeh profile"
    reasons = "".join(f'<li>{esc(f["reason"])} <span>+{f["points"]:g}</span></li>' for f in r["factors"]) or \
        "<li>Koi warning rule trigger nahi hua.</li>"
    actions = list(dict.fromkeys(f["action"] for f in r["factors"]))
    if r["intervention_required"]:
        actions.append("Teacher intervention: is hafte mentoring baatcheet rakhein")
    acts = "".join(f"<li>{esc(x)}</li>" for x in (actions or ["Abhi ka routine jaari rakhein aur agle assessment ke baad dobara check karein"]))
    st.markdown(
        f'<div class="board"><div class="top"><span class="lvl" style="color:{ {"High": "#FF9C8F", "Moderate": "#F9D976", "Low": "#9BE3B0"}[r["level"]] }">'
        f'{r["level"]} risk</span><span class="score">Risk score {r["score"]:.0f} / 100</span><span class="chalk"></span></div>'
        f'<div class="sum">{esc(name)}: {esc(summary_sentence(r))}</div>'
        f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px">'
        f'<div><b>Wajah</b><ul>{reasons}</ul></div><div><b>Suggested actions</b><ul>{acts}</ul></div></div></div>',
        unsafe_allow_html=True)
    for o in r["overrides"]:
        why(o)
    if not r["trend"]["available"]:
        why("Trend rules ke liye is student ke kam se kam do records chahiye, isliye abhi lagaaye nahi gaye.")

    c1, c2 = st.columns([1, 3])
    if c1.button("Risk kaise calculate hota hai", icon=":material/rule:"):
        _rules_dialog(s)
    c2.markdown(f'<div class="why" style="padding-top:.55rem">High {s["risk_high"]:g} points se, moderate '
                f'{s["risk_moderate"]:g} se. Thresholds Settings mein badal sakte hain.</div>', unsafe_allow_html=True)
    if r["factors"]:
        with st.expander("Risk factors vistaar se"):
            df = pd.DataFrame(r["factors"])[["factor", "value", "threshold", "points", "reason"]]
            df.columns = ["Factor", "Value", "Threshold", "Risk points", "Wajah"]
            st.dataframe(df, hide_index=True)

    section("Attendance intelligence", "calendar")
    c1, c2 = st.columns(2)
    for col, k, label in [(c1, "classes_held", "Ab tak kitni classes hui"), (c2, "classes_attended", "Kitni classes attend ki")]:
        st.session_state.setdefault(f"w_{k}", int(st.session_state.get(k) or 0))
        col.number_input(label, 0, 2000, step=1, key=f"w_{k}", on_change=_copy_widget, args=(k,))
    at = a["attendance"]
    kpis([("Current", f"{at['current']:g}%", "classes se" if at["classes_needed"] is not None or at["can_miss"] is not None else "attendance input se", None),
          ("Target", f"{at['target']:g}%", "Settings mein set", None),
          ("Gap", f"{at['gap']:g} pts", "target se neeche" if at["below_target"] else "target par",
           RISK_COLORS["High"] if at["below_target"] else RISK_COLORS["Low"]),
          ("Kitni classes chahiye", str(at["classes_needed"]) if at["classes_needed"] is not None else
           (f"{at['can_miss']} chhod sakte hain" if at["can_miss"] is not None else "n/a"),
           "lagaataar attend karke target tak" if at["classes_needed"] is not None else "", None)])
    if at["below_target"]:
        st.warning("Attendance set kiye gaye target se kam hai.")
    if at["note"]:
        why(at["note"])
    if c["sid"]:
        rec = db.records_df(c["sid"])
        if len(rec) > 1:
            fig = px.line(rec, x="record_date", y="Attendance", markers=True, title="Attendance trend")
            fig.add_hline(y=s["attendance_target"], line_dash="dot", line_color=RISK_COLORS["High"],
                          annotation_text="target")
            fig.update_traces(line_color=accent())
            fig.update_layout(height=280, xaxis_title=None)
            st.plotly_chart(fig)


def _academic_record(sid, info, s):
    """Registration, programme and term, plus subject-wise attendance and marks from recorded sessions/assessments."""
    from services import academics, assessments as svc_assess, attendance as svc_att
    term = academics.current_term()
    att = svc_att.student_attendance(sid)
    summ = svc_assess.student_summary(sid)
    section("Academic record", "cap", "Attendance sessions aur assessment marks se")
    kpis([("Registration no.", info.get("registration_no") or "Set nahi", info.get("program_code") or "Programme nahi", None, "cap"),
          ("Semester", str(info.get("semester") or "–"), term["name"] if term else "Koi current term nahi", None, "calendar"),
          ("Recorded attendance", "–" if att["pct"] is None else f"{att['pct']:g}%",
           f"{att['held']} mein se {att['attended']} sessions" if att["held"] else "Koi session record nahi",
           RISK_COLORS["High"] if att["pct"] is not None and att["pct"] < s["attendance_target"] else None, "calendar"),
          ("Missing submissions", str(summ["missing"]), f"{summ['count']} assessments mein se",
           RISK_COLORS["Moderate"] if summ["missing"] else None, "flag")])
    by_sub = svc_att.by_subject(sid)
    marks = svc_assess.student_marks(sid)
    if by_sub.empty and marks.empty:
        empty("Is student ke liye abhi koi attendance session ya marks record nahi hain. Teacher inhe "
              "Attendance & marks page par bharte hain.", "calendar")
        return
    c1, c2 = st.columns([1, 1.5], gap="large")
    with c1:
        if not by_sub.empty:
            st.dataframe(by_sub[["subject", "attended", "held", "pct"]].rename(columns={
                "subject": "Subject", "attended": "Attended", "held": "Held", "pct": "Attendance %"}), hide_index=True,
                column_config={"Attendance %": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100)})
    with c2:
        if not marks.empty:
            view = marks.assign(Status=marks.apply(lambda r: "Absent" if r.absent else ("Missing" if pd.isna(r.marks) else "Marked"),
                                                   axis=1))
            st.dataframe(view[["assessed_on", "subject", "title", "kind", "marks", "max_marks", "pct", "Status"]].rename(columns={
                "assessed_on": "Date", "subject": "Subject", "title": "Assessment", "kind": "Type", "marks": "Marks",
                "max_marks": "Out of", "pct": "%"}), hide_index=True)


def profile():
    c, a = ctx(), analysis()
    s, b = c["settings"], c["bundle"]
    if not c["sid"] or not c["info"]:
        header("Student profile")
        empty("Profile dekhne ke liye sidebar mein student chunein. Manual entry profile ki koi saved history nahi hoti.")
        return
    info = c["info"]
    header(info["name"] or c["sid"])
    tag = demo_badge() if info.get("is_demo") else ""
    st.markdown(f'<p class="why">{esc(c["sid"])}, {esc(info.get("department") or "Department nahi")}, '
                f'{esc(info.get("class_section") or "class nahi")}, source: {esc(info["source"])} {tag}</p>',
                unsafe_allow_html=True)
    _kpi_strip(a, s)
    risk_banner(a["risk"], summary_sentence(a["risk"]))
    _academic_record(c["sid"], info, s)

    v = a["values"]
    targets = {"Attendance": s["attendance_target"], "Assignment_Score": s["assignment_target"],
               "Internal_Marks": s["internal_target"], "Study_Hours": s["study_hours_target"],
               "Previous_Marks": s["previous_min"]}
    strengths = [FEATURES[f]["label"] for f, t in targets.items() if v[f] >= t]
    weaknesses = [FEATURES[f]["label"] for f, t in targets.items() if v[f] < t]
    sub = a["subjects"]
    if sub is not None:
        strengths += [f"{r.subject} ({r.score:.0f}%)" for r in sub.itertuples() if r.score >= 75]
        weaknesses += [f"{r.subject} ({r.score:.0f}%)" for r in sub.itertuples() if r.score < 60]
    l, r_ = st.columns(2, gap="medium")
    with l:
        with st.container(key="card_strengths"):
            st.markdown('<div class="pd-k">Strengths</div><div class="tagrow">'
                        + ("".join(f'<span class="tag2 ok">{esc(x)}</span>' for x in strengths) or
                           '<span class="why">Abhi koi target par nahi.</span>') + "</div>", unsafe_allow_html=True)
    with r_:
        with st.container(key="card_weak"):
            st.markdown('<div class="pd-k">Sudhaar chahiye</div><div class="tagrow">'
                        + ("".join(f'<span class="tag2 bad">{esc(x)}</span>' for x in weaknesses) or
                           '<span class="why">Kuch bhi target se neeche nahi.</span>') + "</div>", unsafe_allow_html=True)

    section("Subject-wise performance", "book")
    if sub is None:
        empty("Koi subject score record nahi hai. Neeche jodein ya import karein.")
    else:
        sub = sub.sort_values("score")
        colors = [RISK_COLORS["High"] if x < 60 else RISK_COLORS["Moderate"] if x < 75 else RISK_COLORS["Low"]
                  for x in sub["score"]]
        fig = go.Figure(go.Bar(x=sub["score"], y=sub["subject"], orientation="h", marker_color=colors,
                               text=[f"{x:.0f}%" for x in sub["score"]], textposition="outside"))
        fig.update_layout(height=60 + 42 * len(sub), xaxis=dict(range=[0, 108]), yaxis=dict(autorange="reversed"),
                          title="Har subject ka latest score (green 75+, amber 60-74, red 60 se neeche)")
        st.plotly_chart(fig)
        st.markdown(f"Sabse pehle dhyaan: **{sub.iloc[0]['subject']}** ({sub.iloc[0]['score']:.0f}%).")

    section("Progress history", "trend")
    rec = db.records_df(c["sid"])
    if len(rec) < 2:
        empty("Abhi sirf ek record hai. Har naya record (Prediction page, Save, ya Data import) is history mein judta hai.")
    else:
        rec = rec.assign(Predicted=predict_many(b, rec).round(1))
        first, last = rec["Predicted"].iloc[0], rec["Predicted"].iloc[-1]
        st.markdown(f"{len(rec)} records mein predicted score **{last - first:+.1f} points** badla "
                    f"({rec['record_date'].iloc[0]} to {rec['record_date'].iloc[-1]}).")
        long = rec.melt(id_vars="record_date", value_vars=["Predicted", "Attendance", "Assignment_Score"],
                        var_name="Measure", value_name="Value")
        long["Measure"] = long["Measure"].replace({"Assignment_Score": "Assignment"})
        fig = px.line(long, x="record_date", y="Value", color="Measure", markers=True)
        fig.update_layout(height=320, xaxis_title=None, legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig)
        if rec["final_score"].notna().any():
            why("Kuch records ke asli final scores record hain, neeche table mein dikh rahe hain.")
        st.dataframe(rec[["record_date", "Attendance", "Assignment_Score", "Internal_Marks", "Study_Hours",
                          "Previous_Marks", "Predicted", "final_score"]].rename(columns={"final_score": "Actual final"}),
                     hide_index=True)

    section("Recommendations", "flag")
    _rec_cards(a["recommendations"], a, limit=3)

    ints = db.interventions_df(c["sid"])
    if not ints.empty:
        section("Interventions", "flag")
        st.dataframe(ints[["created_at", "status", "risk_level", "follow_up_date", "notes"]], hide_index=True)

    if role() in ("teacher", "admin"):
        with st.expander("Subject scores jodein"):
            with st.form("subj"):
                subj = st.selectbox("Subject", SUBJECTS_DEFAULT + ["Other"])
                other = st.text_input("Subject ka naam (agar Other)")
                score = st.number_input("Score (%)", 0.0, 100.0, 70.0)
                d = st.date_input("Date", value=date.today())
                if st.form_submit_button("Score Jodein"):
                    name = other.strip() if subj == "Other" else subj
                    if not name:
                        st.error("Subject ka naam likhein.")
                    else:
                        db.add_subject_score(c["sid"], name[:60], score, d.isoformat())
                        st.success(f"{name}: {score:g}% jod diya.")
                        st.rerun()
