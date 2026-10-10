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
        edited = " Values edited on the Prediction page, not saved." if c["edited"] else ""
        name = info["name"] or c["sid"]
        st.markdown(f'<div class="context"><span class="av">{esc(initials(name))}</span><b>{esc(name)}</b>'
                    f'<span class="pill">{esc(where)}</span>{tag}<span>{esc(edited)}</span></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="context"><span class="av">?</span><b>Manual entry</b>'
                    '<span>Not a saved student. Adjust the values on the Prediction page.</span></div>',
                    unsafe_allow_html=True)


def _trend_kpi(a):
    t = a["risk"]["trend"]
    if not t["available"]:
        return ("Performance trend", "No history", "Needs 2+ records", MUTED)
    ch = t["change"]
    col = RISK_COLORS["High"] if t["declining"] else RISK_COLORS["Low"] if ch > 0 else INK
    return ("Performance trend", f"{ch:+.1f}", "vs previous record", col)


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
        st.warning("Less reliable: some inputs are outside the training data. " + "; ".join(a["extrapolation"]) + ".")


def _inputs_vs_targets(a, s):
    v = a["values"]
    targets = {"Attendance": s["attendance_target"], "Assignment_Score": s["assignment_target"],
               "Internal_Marks": s["internal_target"], "Previous_Marks": s["previous_min"]}
    labels = [FEATURES[f]["label"] for f in targets]
    vals = [v[f] for f in targets]
    colors = [accent() if v[f] >= t else RISK_COLORS["High"] for f, t in targets.items()]
    fig = go.Figure(go.Bar(x=vals, y=labels, orientation="h", marker_color=colors,
                           text=[f"{x:g}" for x in vals], textposition="outside", name="Current"))
    fig.add_trace(go.Scatter(x=list(targets.values()), y=labels, mode="markers", name="Target",
                             marker=dict(symbol="line-ns", size=26, line=dict(width=3, color=INK))))
    fig.update_layout(height=260, xaxis=dict(range=[0, 108], title=None), yaxis=dict(autorange="reversed"),
                      legend=dict(orientation="h", y=-0.15), title="Current vs target (0-100 scale)")
    st.plotly_chart(fig)


# ---------------- pages ----------------
@st.dialog("Why this recommendation?", width="medium")
def _rec_dialog(r: dict, a: dict):
    dialog_head("spark", r["category"], r["text"])
    st.markdown(f"**Reason.** {r['why']}")
    if r.get("gain"):
        g1, g2 = st.columns(2)
        g1.metric("Predicted now", f"{a['prediction']:.1f}")
        g2.metric("If this target is reached", f"{a['prediction'] + r['gain']:.1f}", f"{r['gain']:+.1f}")
        why("Estimated by the model from past records. It is a guide, not a guarantee.")
    pages = st.session_state.get("pages", {})
    c1, c2 = st.columns(2)
    if "what-if" in pages:
        c1.page_link(pages["what-if"], label="Try it in the simulator", icon=":material/tune:")
    if "study-plan" in pages:
        c2.page_link(pages["study-plan"], label="Open my study plan", icon=":material/menu_book:")


def _rec_cards(recs: list[dict], a: dict, limit: int = 3):
    """Clean action cards; each opens a details pop-up with the reason and the model's estimate."""
    cols = st.columns(max(3, min(limit, len(recs))), gap="medium")
    for i, (col, r) in enumerate(zip(cols, recs[:limit]), 1):
        with col:
            with st.container(key=f"act{i}"):
                st.markdown(f'<div class="acat">{esc(r["category"])}</div>', unsafe_allow_html=True)
                st.markdown(r["text"])
                if r.get("gain"):
                    why(f"Estimated gain +{r['gain']:.1f} points")
                if st.button("Why this?", key=f"recwhy{i}", icon=":material/info:", type="tertiary"):
                    _rec_dialog(r, a)


def _quick_links():
    pages = st.session_state.get("pages", {})
    links = [("what-if", "What if I improve?", ":material/tune:"), ("study-plan", "Today's study plan", ":material/menu_book:"),
             ("assistant", "Ask the assistant", ":material/forum:"), ("explain", "Why this score?", ":material/psychology:")]
    links = [l for l in links if l[0] in pages]
    if not links:
        return
    cols = st.columns(len(links))
    for col, (path, label, ic) in zip(cols, links):
        col.page_link(pages[path], label=label, icon=ic, width="stretch")


def _progress_chart(sid):
    """Predicted score (and attendance) across this student's saved records."""
    if not sid:
        empty("Choose a student in the sidebar to see progress over time.")
        return
    rec = db.records_df(sid)
    if len(rec) < 2:
        empty("Only one record so far. Progress appears after the next record is saved.")
        return
    rec = rec.assign(Predicted=predict_many(ctx()["bundle"], rec).round(1))
    first, last = rec["Predicted"].iloc[0], rec["Predicted"].iloc[-1]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=rec["record_date"], y=rec["Predicted"], name="Predicted score", mode="lines+markers",
                             line=dict(color=accent(), width=3), marker=dict(size=8)))
    fig.add_trace(go.Scatter(x=rec["record_date"], y=rec["Attendance"], name="Attendance %", mode="lines+markers",
                             line=dict(color=accent(1), width=2, dash="dot")))
    fig.update_layout(height=270, yaxis=dict(range=[0, 105]), legend=dict(orientation="h", y=-0.22),
                      title=f"{last - first:+.1f} points over {len(rec)} records")
    st.plotly_chart(fig)


def overview():
    a, s = analysis(), ctx()["settings"]
    header("Overview", "Academic summary: where things stand, why, and what to do next.")
    _context_line()
    _kpi_strip(a, s)
    _extrapolation(a)

    left, right = st.columns([1, 1.1], gap="large")
    with left:
        section("Risk level and main factors", "alert")
        risk_banner(a["risk"], summary_sentence(a["risk"]))
        if a["risk"]["factors"]:
            rc = RISK_COLORS[a["risk"]["level"]]
            st.markdown("".join(f'<div class="factor" style="--rc:{rc}"><span class="pts">+{f["points"]:g}</span>'
                                f'<div><b>{esc(f["factor"])}</b> · {esc(f["reason"])}</div></div>'
                                for f in a["risk"]["factors"][:3]), unsafe_allow_html=True)
        else:
            empty("No early-warning rules are triggered.")
    with right:
        section("Recent academic progress", "trend")
        _progress_chart(ctx()["sid"])

    section("Recommended actions", "flag")
    _rec_cards(a["recommendations"], a)

    section("Study improvement suggestions", "book")
    l2, r2 = st.columns([1.1, 1], gap="large")
    with l2:
        if a["priorities"]:
            for p in a["priorities"][:3]:
                with st.container(key=f"card_imp{p['priority']}"):
                    st.markdown(f"**{p['priority']}. {p['label']}**: now {p['current']:g}, target {p['target']:g}")
                    st.progress(min(1.0, p["current"] / p["target"]) if p["target"] else 1.0,
                                text=f"Reaching the target adds about +{p['gain']:.1f} points")
        else:
            empty("Every factor you can change already meets its target.")
    with r2:
        plan_ = a["plan"]
        with st.container(key="card_today"):
            st.markdown(f"**Today's study plan**, about {plan_['daily_minutes']} minutes")
            for b in plan_["today"][:4]:
                st.markdown(f"{b['order']}. {b['activity']}, {b['minutes']} min")
            pages = st.session_state.get("pages", {})
            if "study-plan" in pages:
                st.page_link(pages["study-plan"], label="Open the full study plan", icon=":material/menu_book:")

    with st.expander("Saved assessment log"):
        act = db.activity_df(ctx()["sid"] if role() == "student" or ctx()["sid"] else None, limit=8)
        if act.empty:
            empty("No saved assessments yet. Saved predictions and risk checks appear here.")
        else:
            act["predicted_score"] = act["predicted_score"].round(1)
            st.dataframe(act.rename(columns={"created_at": "When", "student_id": "Student", "predicted_score": "Predicted",
                                             "grade": "Grade", "risk_level": "Risk"}), hide_index=True)


def _set_value(f):
    st.session_state["profile_values"][f] = float(st.session_state[f"w_{f}"])


@st.dialog("Save this record?", width="medium")
def _save_dialog(c, vals, a, s, d):
    dialog_head("db", f"New record for {c['sid']}", f"Dated {d.isoformat()}. Saved records build this student's history.")
    kpis([("Predicted score", f"{a['prediction']:.1f}", f"Grade {a['grade']}", None),
          ("Risk level", a["risk"]["level"], f"Risk score {a['risk']['score']:.0f}/100", RISK_COLORS[a["risk"]["level"]])])
    st.markdown(", ".join(f"{FEATURES[f]['label']} **{vals[f]:g}**" for f in FEATURE_NAMES) + ".")
    why("Saving also stores the prediction and risk check and sends any alerts the rules trigger.")
    c1, c2 = st.columns(2)
    if c1.button("Cancel", width="stretch"):
        st.rerun()
    if c2.button("Save record", type="primary", width="stretch", icon=":material/check:"):
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
        st.session_state["flash"] = f"Saved record for {c['sid']}. {sent} alert(s) created."
        st.rerun()


INPUT_HELP = {
    "Attendance": "Share of classes attended this term (0-100%).",
    "Assignment_Score": "Average assignment mark so far (0-100).",
    "Internal_Marks": "Average internal test mark so far (0-100).",
    "Study_Hours": "Average self-study hours per day, outside class.",
    "Previous_Marks": "Final mark from the previous term. Already fixed, so it can't be improved now.",
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
        reasons.append(f"Trained on only {b['training_rows']} records, so validation numbers are themselves uncertain.")
    if a["extrapolation"]:
        level -= 1
        reasons.append("Some inputs are outside the range the model was trained on: " + "; ".join(a["extrapolation"]) + ".")
    if not reasons:
        reasons.append("Inputs are inside the training range and the model was validated on enough records.")
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
            f'<div class="mid"><b>{pred:.1f}</b><span>out of 100</span></div></div>')


def _meaning(a, s, b):
    pred = a["prediction"]
    if pred < s["pass_score"]:
        verdict = f"Below the pass mark of {s['pass_score']:g}. Action is needed now."
    elif pred < s["watch_score"]:
        verdict = f"Passing, but under the watch level of {s['watch_score']:g}. Worth keeping a close eye on."
    else:
        verdict = f"Comfortably above the watch level of {s['watch_score']:g}."
    contrib = a["explanation"]["contributions"]
    low = min(contrib, key=contrib.get)
    high = max(contrib, key=contrib.get)
    below, n = a["percentile"]
    parts = [f"If these five inputs stay as they are, the model expects a final score of about <b>{pred:.0f}</b> "
             f"(about 80% likely between {model_registry.interval(b, pred)[0]:.0f} and {model_registry.interval(b, pred)[1]:.0f}, "
             f"model {model_registry.version_of(b)})."]
    c = ctx()
    if c["sid"]:
        rec = db.records_df(c["sid"])
        if not rec.empty:
            last = rec.iloc[-1]
            parts.append(f"Inputs come from the record dated <b>{esc(last['record_date'])}</b> ({esc(last['source'])})"
                         + (", edited on this page." if c["edited"] else "."))
    if contrib[low] < -0.05:
        parts.append(f"The biggest factor pulling it down is <b>{esc(FEATURES[low]['label'].lower())}</b> "
                     f"({contrib[low]:+.1f}).")
    if contrib[high] > 0.05:
        parts.append(f"The biggest factor holding it up is <b>{esc(FEATURES[high]['label'].lower())}</b> "
                     f"({contrib[high]:+.1f}).")
    if n:
        parts.append(f"It is higher than {below} of the {n} training records.")
    return verdict, " ".join(parts)


def _result_card(a, s, b):
    pred, r = a["prediction"], a["risk"]
    rc = RISK_COLORS[r["level"]]
    lvl, clabel, ccol, _ = _confidence(a, b)
    lo, hi = model_registry.interval(b, pred)       # ~80% range from cross-validated residuals
    verdict, meaning = _meaning(a, s, b)
    badges = (f'<span class="pd-badge"><i></i>Grade {esc(a["grade"])}</span>'
              f'<span class="pd-badge" style="--bc:{rc}"><i></i>{r["level"]} risk · {r["score"]:.0f}/100</span>'
              f'<span class="pd-badge" style="--bc:{ccol}" title="How much to trust this number"><i></i>{clabel} confidence</span>')
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
        f'title="About 80% likely range: {lo:.1f} to {hi:.1f}"></div>'
        f'<div class="pd-pin" style="left:{pred:.1f}%" data-v="{pred:.1f}"></div></div>'
        f'<div class="pd-ticks">{ticks}</div>'
        f'<div class="pd-legend"><span><i style="background:#FECACA"></i>Below pass ({s["pass_score"]:g})</span>'
        f'<span><i style="background:#FDE68A"></i>Watch zone</span><span><i style="background:#A7F3D0"></i>'
        f'Above watch ({s["watch_score"]:g})</span><span><i style="background:color-mix(in srgb, var(--ink) 25%, transparent)"></i>'
        f'80% range {lo:.0f}–{hi:.0f}</span></div></div>'
        f'<div class="pd-mean"><b>What this means.</b> {meaning}</div></div>', unsafe_allow_html=True)


def _confidence_card(a, b):
    lvl, label, col, reasons = _confidence(a, b)
    meter = "".join(f'<span class="{"on" if i < lvl else ""}"></span>' for i in range(3))
    with st.container(key="card_conf"):
        st.markdown(f'<div class="pd-k">How much to trust it</div>'
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
        st.markdown(f'<div class="pd-k">Why this score</div><div style="font-size:.84rem;color:var(--muted);margin:2px 0 6px">'
                    f'Points each factor adds or removes from the average prediction ({a["explanation"]["base"]:.1f}).</div>'
                    + "".join(rows), unsafe_allow_html=True)
        pages = st.session_state.get("pages", {})
        if "explain" in pages:
            st.page_link(pages["explain"], label="Full explanation", icon=":material/psychology:")


def _inputs_table(a, s):
    v, t = a["values"], _targets(s)
    rows = []
    for f in FEATURE_NAMES:
        spec = FEATURES[f]
        top = 12.0 if f == "Study_Hours" else 100.0
        ok = v[f] >= t[f]
        col = RISK_COLORS["Low"] if ok else RISK_COLORS["High"] if v[f] < t[f] * .8 else RISK_COLORS["Moderate"]
        unit = spec["unit"]
        tag = '<span class="tag2 ok">On target</span>' if ok else \
            ('<span class="tag2 bad">Well below</span>' if col == RISK_COLORS["High"] else '<span class="tag2 warn">Below target</span>')
        fixed = " · fixed" if not spec["actionable"] else ""
        rows.append(f'<div class="inp" style="--bc:{col}"><div class="n">{esc(spec["label"])}{fixed}</div>'
                    f'<div class="v">{v[f]:g}{unit} {tag}</div>'
                    f'<div class="bar"><span style="width:{min(100, v[f] / top * 100):.1f}%"></span>'
                    f'<i style="left:{min(100, t[f] / top * 100):.1f}%"></i></div>'
                    f'<div class="meta"><span>Target {t[f]:g}{unit}</span>'
                    f'<span>{"" if ok else f"{t[f] - v[f]:g}{unit} to go"}</span></div></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)
    why("The tick on each bar is the target set in Settings. Previous marks use the risk threshold, since they can't change.")


def _trend_tab(c, b, s):
    sid = c["sid"]
    if not sid:
        empty("Trends need saved records. Choose a student in the sidebar to see how their prediction has moved.", "trend")
        return
    rec = db.records_df(sid)
    if len(rec) < 2:
        empty("Only one record so far. The trend appears after the next record is saved.", "trend")
        return
    rec = rec.assign(Predicted=predict_many(b, rec).round(1))
    f1, f2 = st.columns([2, 1])
    measures = f1.pills("Show", ["Predicted", "Attendance", "Assignment_Score", "Internal_Marks"], default=["Predicted", "Attendance"],
                        selection_mode="multi", key="pd_measures",
                        format_func=lambda m: {"Predicted": "Predicted score", "Assignment_Score": "Assignment",
                                               "Internal_Marks": "Internal"}.get(m, m))
    span = f2.segmented_control("Records", ["All", "Last 3"], default="All", key="pd_span")
    if span == "Last 3":
        rec = rec.tail(3)
    if not measures:
        empty("Pick at least one measure to plot.", "chart")
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
                      title=f"Predicted score {last - first:+.1f} points over {len(rec)} records", hovermode="x unified")
    st.plotly_chart(fig)


def _compare_tab(a, b, c):
    t = b.get("target_values") or []
    options = ["Training records"] + (["Current students"] if role() in ("teacher", "admin") else [])
    group = st.segmented_control("Compare with", options, default="Training records", key="pd_cmp") or "Training records"
    if group == "Training records":
        if not t:
            empty("The saved model has no training scores to compare with.", "chart")
            return
        values, label = t, "Actual final scores in the training data"
    else:
        from views.common import scoped_roster
        df, _ = scoped_roster(c["bundle"])
        if df.empty:
            empty("No current students to compare with.", "users")
            return
        values, label = df["Predicted score"].tolist(), "Latest predicted scores of current students"
    fig = go.Figure(go.Histogram(x=values, nbinsx=12, marker_color=accent(), opacity=.85,
                                 hovertemplate="%{x}<br>%{y} records<extra></extra>"))
    fig.add_vline(x=a["prediction"], line_width=3, line_color=INK, annotation_text=f"this student {a['prediction']:.1f}",
                  annotation_position="top")
    fig.update_layout(height=300, title=label, xaxis=dict(range=[0, 100], title="Score"), yaxis_title="Records", bargap=.08)
    st.plotly_chart(fig)
    below = sum(v < a["prediction"] for v in values)
    why(f"{below} of {len(values)} are lower than this prediction. A small or unusual comparison group makes this a rough guide.")


def _model_tab(b):
    m = b["metrics"]
    kpis([("Model in use", b["model_name"], "selected by cross-validation", None, "chip"),
          ("Typical error (MAE)", f"±{m['MAE']:.2f}", "points", None, "target"),
          ("RMSE", f"{m['RMSE']:.2f}", "points", None, "chart"),
          ("Training records", str(b["training_rows"]), b["trained_at"], None, "db")])
    rng = pd.DataFrame([{"Input": FEATURES[f]["label"], "Lowest seen": lo, "Highest seen": hi}
                        for f, (lo, hi) in b["training_ranges"].items()])
    st.dataframe(rng, hide_index=True)
    why("Inputs outside these ranges are extrapolation: the model is guessing beyond what it has seen.")


def _reset_inputs():
    for f in FEATURE_NAMES:
        st.session_state["profile_values"][f] = float(st.session_state["saved_values"][f])
        st.session_state[f"w_{f}"] = float(st.session_state["saved_values"][f])


def prediction():
    c = ctx()
    s, b = c["settings"], c["bundle"]
    who = (c["info"]["name"] if c["sid"] and c["info"] else None)
    header("Prediction", f"{who}'s predicted final score, what it means, and how far to trust it."
           if who else "Enter the five inputs the model uses. The prediction updates as you move the sliders.")
    _context_line()
    if msg := st.session_state.pop("flash", None):
        st.success(msg)
    vals = st.session_state["profile_values"]

    left, right = st.columns([0.85, 1.5], gap="large")
    with left:
        with st.container(key="card_inputs"):
            st.markdown('<div class="pd-k">Inputs</div><div style="font-size:.84rem;color:var(--muted);margin-bottom:6px">'
                        'Move a slider and every number on the right updates.</div>', unsafe_allow_html=True)
            for f in FEATURE_NAMES:
                spec = FEATURES[f]
                key = f"w_{f}"
                if key not in st.session_state:
                    st.session_state[key] = float(vals[f])
                st.slider(spec["label"] + (f" ({spec['unit']})" if spec["unit"] else ""), float(spec["min"]),
                          float(spec["max"]), step=float(spec["step"]), format="%.0f" if spec["step"] >= 1 else "%.1f",
                          key=key, on_change=_set_value, args=(f,), help=INPUT_HELP[f])
            if c["edited"]:
                st.button("Reset to saved values", icon=":material/restart_alt:", on_click=_reset_inputs,
                          width="stretch", key="pd_reset")

    problems = validate_inputs(vals)
    if problems:
        with right:
            st.error("Fix these inputs: " + " ".join(problems))
        return
    a = analysis()
    with right:
        _result_card(a, s, b)
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            _drivers_card(a)
        with c2:
            _confidence_card(a, b)

    section("Explore the prediction", "compass")
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
        section("Save as a new record", "db")
        with st.container(key="card_save"):
            s1, s2 = st.columns([1, 1.2], vertical_alignment="bottom")
            d = s1.date_input("Record date", value=date.today(), key="save_date")
            if s2.button("Save as new record", type="primary", icon=":material/save:", width="stretch"):
                _save_dialog(c, vals, a, s, d)
            why("Saving stores these inputs, the prediction and the risk check, and sends any alerts the rules trigger.")
    elif c["edited"]:
        why("These edited values are not saved. Teachers can save them as a new record.")


def explainable():
    a, c = analysis(), ctx()
    b = c["bundle"]
    header("Explainable AI", "Why the model produced this prediction, factor by factor.")
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
    fig.update_layout(height=360, yaxis=dict(autorange="reversed"), title="Contribution to this prediction (points)",
                      xaxis=dict(range=[min(0, exp["base"] - 30), 105]))
    st.plotly_chart(fig)

    p, n = st.columns(2)
    pos = [(k, v) for k, v in contrib.items() if v > 0.05]
    neg = [(k, v) for k, v in contrib.items() if v < -0.05]
    with p:
        section("Raising the prediction", "trend")
        if pos:
            for k, v in sorted(pos, key=lambda x: -x[1]):
                st.markdown(f"**{FEATURES[k]['label']}**: {v:+.1f}")
        else:
            empty("No factor is above the training average.")
    with n:
        section("Lowering the prediction", "alert")
        if neg:
            for k, v in sorted(neg, key=lambda x: x[1]):
                st.markdown(f"**{FEATURES[k]['label']}**: {v:+.1f}")
        else:
            empty("No factor is below the training average.")

    section("Performance drivers across all students", "chart")
    imp = global_importance(b)
    fig2 = go.Figure(go.Bar(x=imp.values, y=[FEATURES[k]["label"] for k in imp.index], orientation="h",
                            marker_color=accent(), text=[f"{x:.2f}" for x in imp.values], textposition="outside"))
    fig2.update_layout(height=250, yaxis=dict(autorange="reversed"),
                       title="Average size of each factor's contribution (points)")
    st.plotly_chart(fig2)
    if b["details"]:
        coef = b["details"]["coefficients"]
        st.markdown("Model weights per unit change: " + ", ".join(
            f"{FEATURES[k]['label']} {v:+.2f}" for k, v in coef.items()) + ".")

    if st.button("How these explanations work", icon=":material/help:"):
        _explain_dialog(b)


@st.dialog("How explanations work", width="large")
def _explain_dialog(b):
    dialog_head("spark", "Exact Shapley values", "The same quantity the SHAP library estimates, computed exactly.")
    st.markdown(
        "For each factor, the model is evaluated with and without that factor's real value across every "
        "combination of the other factors (32 combinations), with missing factors filled from the training "
        "data. Contributions always add up exactly to *this prediction minus the average prediction*.\n\n"
        "They describe **how the model uses each input**, not what causes a student's result.")
    for lim in b["limitations"]:
        st.warning(lim)


ACTIONABLE = ["Attendance", "Assignment_Score", "Internal_Marks", "Study_Hours"]
PLAIN_WHY = {
    "Attendance": "Students who attended more classes tended to score higher in the training records.",
    "Assignment_Score": "Higher assignment marks went with higher final scores in the training records.",
    "Internal_Marks": "Internal test marks are closely linked to final scores in the training records.",
    "Study_Hours": "More daily study time went with higher final scores in the training records.",
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
    header("What-if simulator", "Change a habit and see what the AI model predicts. Nothing here is saved.")
    _context_line()
    base_vals = st.session_state["profile_values"]
    for f in FEATURE_NAMES:
        st.session_state.setdefault(f"wi_{f}", float(base_vals[f]))

    left, right = st.columns([1.05, 1], gap="large")
    with left:
        section("1. Change your habits", "pencil")
        q1, q2 = st.columns(2)
        q1.button("Attend 10% more classes", on_click=_bump, args=("Attendance", 10), icon=":material/event_available:", width="stretch")
        q2.button("Study 1 more hour a day", on_click=_bump, args=("Study_Hours", 1), icon=":material/schedule:", width="stretch")
        q3, q4 = st.columns(2)
        q3.button("Reach all my targets", on_click=_apply_targets, disabled=not a["priorities"], icon=":material/flag:", width="stretch")
        q4.button("Reset to my real values", on_click=_reset_scenario, icon=":material/restart_alt:", width="stretch")
        for f in ACTIONABLE:
            spec = FEATURES[f]
            st.slider(f"{spec['label']} (now {_fmt(f, base_vals[f])})", float(spec["min"]),
                      float(max(12, base_vals[f]) if f == "Study_Hours" else spec["max"]), step=float(spec["step"]),
                      format="%.0f" if spec["step"] >= 1 else "%.1f", key=f"wi_{f}")
        st.session_state[f"wi_Previous_Marks"] = float(base_vals["Previous_Marks"])
        why(f"Previous marks ({base_vals['Previous_Marks']:g}) are already final, so they stay fixed here.")

    scen = {f: float(st.session_state[f"wi_{f}"]) for f in FEATURE_NAMES}
    after = analyze(b, scen, s, a["history"], a["subjects"])
    delta = after["prediction"] - a["prediction"]
    changed = [f for f in ACTIONABLE if abs(scen[f] - base_vals[f]) > 1e-9]

    with right:
        section("2. Compare the scores", "target")
        word = "improves" if delta > 0.05 else "drops" if delta < -0.05 else "stays the same"
        old_w, new_w = max(0, min(100, a["prediction"])), max(0, min(100, after["prediction"]))
        st.markdown(
            f'<div class="wi-result"><div class="row"><div><div class="cap">Predicted now</div>'
            f'<div class="wi-num">{a["prediction"]:.1f}</div></div><div class="wi-arrow">→</div>'
            f'<div style="text-align:right"><div class="cap">With your changes</div><div class="wi-num">{after["prediction"]:.1f}</div></div></div>'
            f'<div class="wi-bar"><span class="old" style="width:{old_w}%"></span><span class="new" style="width:{new_w}%"></span></div>'
            f'<span class="wi-delta">{delta:+.1f} points</span>'
            f'<div class="wi-sub">Your score {word}. {_change_text("Grade", a["grade"], after["grade"])} '
            f'{_change_text("Risk", a["risk"]["level"], after["risk"]["level"])}</div></div>', unsafe_allow_html=True)

        section("3. What changed and why", "spark")
        if not changed:
            empty("Move a slider or press a button on the left. The effect of each change will be explained here.")
        else:
            items = []
            for f in changed:
                solo = predict_one(b, dict(base_vals, **{f: scen[f]})) - a["prediction"]
                cls = "up" if solo > 0.05 else "down" if solo < -0.05 else "same"
                items.append(f'<li><b>{FEATURES[f]["label"]}</b> {_fmt(f, base_vals[f])} → {_fmt(f, scen[f])}: '
                             f'<span class="chg {cls}">{solo:+.1f} points</span> on its own. '
                             f'<span class="why">{PLAIN_WHY[f]}</span></li>')
            st.markdown(f'<ul class="wi-why">{"".join(items)}</ul>', unsafe_allow_html=True)
            if len(changed) > 1:
                why(f"All changes together: {delta:+.1f} points.")
        if after["extrapolation"]:
            st.warning("Some values are outside what the model has seen before, so treat this estimate as rough: "
                       + "; ".join(after["extrapolation"]) + ".")
        why("These are estimates from patterns in past records, not a guarantee.")

    with st.expander("See how one habit changes the score, step by step"):
        f = st.selectbox("Habit", ACTIONABLE, format_func=lambda k: FEATURES[k]["label"], key="wi_sens")
        sens = sensitivity(b, scen, f)
        fig = px.line(sens, x=f, y="Predicted", title=f"Predicted score as {FEATURES[f]['label'].lower()} changes")
        fig.update_traces(line_color=accent(), line_width=3)
        lo, hi = b["training_ranges"][f]
        fig.add_vrect(x0=lo, x1=hi, fillcolor=accent(3), opacity=0.6, line_width=0,
                      annotation_text="range seen in training", annotation_position="top left")
        fig.add_scatter(x=[scen[f]], y=[after["prediction"]], mode="markers", name="Your scenario",
                        marker=dict(size=12, color=INK))
        fig.update_layout(height=320, showlegend=False, yaxis_title="Predicted score")
        st.plotly_chart(fig)


FOCUS_TIPS = {
    "Assignment catch-up": "Start with the assignment due soonest. Finish one before opening the next.",
    "Past internal questions": "Answer without notes first, then check. Mark the questions you got wrong to revisit.",
    "Revision of today's classes": "Close your notes and write down the three main ideas from each class.",
}
DEFAULT_TIP = "Put your phone in another room. Work until the ring fills, then take a five-minute break."


@st.dialog("Focus session", width="medium")
def _focus_dialog(b):
    dialog_head("clock", b["activity"], f"{b['minutes']} minutes. {b['why']}")
    secs = int(b["minutes"]) * 60
    st.markdown(f'''
<div class="focus"><svg viewBox="0 0 120 120" width="170" height="170">
<circle cx="60" cy="60" r="52" fill="none" stroke="var(--soft)" stroke-width="10"/>
<circle class="ring" cx="60" cy="60" r="52" fill="none" stroke="var(--p)" stroke-width="10" stroke-linecap="round"
 pathLength="100" stroke-dasharray="100" stroke-dashoffset="100" transform="rotate(-90 60 60)"
 style="animation: fill {secs}s linear forwards"/></svg>
<div class="fl2"><b>{b["minutes"]}</b><span>minutes</span></div></div>''', unsafe_allow_html=True)
    st.markdown(f"**Tip.** {FOCUS_TIPS.get(b['activity'], DEFAULT_TIP)}")
    why("The ring fills over the full session. Closing this window stops it.")
    if st.button("Done", type="primary", width="stretch", icon=":material/check:"):
        st.rerun()


def _set_task(task_id, key):
    from services import study_plan
    try:
        study_plan.set_status(st.session_state["user"], task_id, st.session_state[key])
    except (ValueError, Exception) as e:   # PermissionDenied or invalid status: show it, never fake success
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
        c4.metric("Study time done", f"{prog['minutes_done']} / {prog['minutes']} min")
        st.progress(prog["pct"] / 100, text=f"Aaj ka progress: {prog['pct']}%")
        if not editable:
            why("Yeh progress sirf dekh sakte hain. Status sirf student khud badal sakta hai.")
    tag = {"pending": "", "in_progress": "warn", "completed": "ok"}
    for t in tasks.itertuples():
        with st.container(key=f"card_hover_blk{t.block_order}"):
            c1, c2 = st.columns([2.6, 1.6], vertical_alignment="center")
            c1.markdown(f'<div class="step"><span class="sn">{t.block_order}</span><div><b>{esc(t.activity)}</b> '
                        f'<span class="tag2 {tag[t.status]}">{study_plan.LABELS[t.status]}</span>'
                        f'<div class="why">{t.minutes} min. {esc(t.reason or "")}</div></div></div>', unsafe_allow_html=True)
            with c2:
                if editable:
                    key = f"task_status_{t.id}"
                    st.session_state[key] = t.status
                    st.segmented_control("Status", study_plan.STATUSES, key=key, format_func=study_plan.LABELS.get,
                                         on_change=_set_task, args=(t.id, key), label_visibility="collapsed",
                                         required=True, width="stretch")
                    b1, b2 = st.columns(2)
                    b1.button("Complete Karein", key=f"task_done_{t.id}", icon=":material/check:", width="stretch",
                              disabled=t.status == "completed", on_click=_complete_task, args=(t.id,), type="primary")
                    if b2.button("Shuru Karein", key=f"focus{t.block_order}", icon=":material/timer:", width="stretch"):
                        _focus_dialog({"activity": t.activity, "minutes": t.minutes, "why": t.reason or ""})
                else:
                    st.markdown(f'<div class="why">Status: <b>{study_plan.LABELS[t.status]}</b></div>', unsafe_allow_html=True)
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


@st.dialog("How risk is calculated", width="large")
def _rules_dialog(s):
    dialog_head("alert", "Every point has a rule", "Rules add points to a 0-100 risk score. Thresholds are set in Settings.")
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
    ], columns=["Rule", "Triggers when", "Risk points"])
    st.dataframe(rules, hide_index=True)
    st.markdown(f"🔴 **High** from {s['risk_high']:g} points, 🟡 **Moderate** from {s['risk_moderate']:g}, 🟢 **Low** below that. "
                "A predicted score below the pass mark is always high risk.")


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
        empty("No students in these classes yet.")
        return
    counts = df["Risk"].value_counts()
    legend = "".join(
        f'<div class="lg" style="--rc:{RISK_COLORS[k]}"><i></i>{k} risk <b>{counts.get(k, 0)}</b></div>'
        for k in ["High", "Moderate", "Low"])
    section("Focus on these students first", "users")
    st.markdown(f'<div class="legend">{legend}</div>', unsafe_allow_html=True)
    top = df[df["Risk"] != "Low"].sort_values(["Risk score", "Predicted score"], ascending=[False, True]).head(6)
    if top.empty:
        empty("No student is at moderate or high risk right now.")
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
                f'<div class="r"><b>Why:</b> {esc(f0["reason"] if f0 else "Combined factors")}</div>'
                f'<div class="a"><b>Action:</b> {esc(f0["action"] if f0 else "Monitor")}</div></div>',
                unsafe_allow_html=True)
            st.button("Open this student", key=f"ew_open_{row['Student']}", on_click=_open_student,
                      args=(row["Student"],), type="tertiary", icon=":material/arrow_forward:")
    n_more = int((df["Risk"] != "Low").sum()) - len(top)
    if n_more > 0:
        why(f"{n_more} more students are at moderate or high risk. See the Teacher dashboard for the full list.")


def early_warning():
    a, c = analysis(), ctx()
    s = c["settings"]
    r = a["risk"]
    header("Early warning", "Who is at risk, why, and what to do about it. Every point of risk comes from a rule you can see.")
    if role() in ("teacher", "admin"):
        _watchlist()
        section("Selected student", "target")
    _context_line()

    name = c["info"]["name"] if c["sid"] and c["info"] else "This profile"
    reasons = "".join(f'<li>{esc(f["reason"])} <span>+{f["points"]:g}</span></li>' for f in r["factors"]) or \
        "<li>No warning rules are triggered.</li>"
    actions = list(dict.fromkeys(f["action"] for f in r["factors"]))
    if r["intervention_required"]:
        actions.append("Teacher intervention: schedule a mentoring conversation this week")
    acts = "".join(f"<li>{esc(x)}</li>" for x in (actions or ["Keep the current routine and re-check after the next assessment"]))
    st.markdown(
        f'<div class="board"><div class="top"><span class="lvl" style="color:{ {"High": "#FF9C8F", "Moderate": "#F9D976", "Low": "#9BE3B0"}[r["level"]] }">'
        f'{r["level"]} risk</span><span class="score">Risk score {r["score"]:.0f} / 100</span><span class="chalk"></span></div>'
        f'<div class="sum">{esc(name)}: {esc(summary_sentence(r))}</div>'
        f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px">'
        f'<div><b>Reasons</b><ul>{reasons}</ul></div><div><b>Recommended actions</b><ul>{acts}</ul></div></div></div>',
        unsafe_allow_html=True)
    for o in r["overrides"]:
        why(o)
    if not r["trend"]["available"]:
        why("Trend rules need at least two records for this student, so they are not applied yet.")

    c1, c2 = st.columns([1, 3])
    if c1.button("How risk is calculated", icon=":material/rule:"):
        _rules_dialog(s)
    c2.markdown(f'<div class="why" style="padding-top:.55rem">High from {s["risk_high"]:g} points, moderate from '
                f'{s["risk_moderate"]:g}. Thresholds are editable in Settings.</div>', unsafe_allow_html=True)
    if r["factors"]:
        with st.expander("Risk factors in detail"):
            df = pd.DataFrame(r["factors"])[["factor", "value", "threshold", "points", "reason"]]
            df.columns = ["Factor", "Value", "Threshold", "Risk points", "Reason"]
            st.dataframe(df, hide_index=True)

    section("Attendance intelligence", "calendar")
    c1, c2 = st.columns(2)
    for col, k, label in [(c1, "classes_held", "Classes held so far"), (c2, "classes_attended", "Classes attended")]:
        st.session_state.setdefault(f"w_{k}", int(st.session_state.get(k) or 0))
        col.number_input(label, 0, 2000, step=1, key=f"w_{k}", on_change=_copy_widget, args=(k,))
    at = a["attendance"]
    kpis([("Current", f"{at['current']:g}%", "from classes" if at["classes_needed"] is not None or at["can_miss"] is not None else "from the attendance input", None),
          ("Target", f"{at['target']:g}%", "set in Settings", None),
          ("Gap", f"{at['gap']:g} pts", "below target" if at["below_target"] else "on target",
           RISK_COLORS["High"] if at["below_target"] else RISK_COLORS["Low"]),
          ("Classes needed", str(at["classes_needed"]) if at["classes_needed"] is not None else
           (f"Can miss {at['can_miss']}" if at["can_miss"] is not None else "n/a"),
           "attended in a row to reach target" if at["classes_needed"] is not None else "", None)])
    if at["below_target"]:
        st.warning("Attendance is below the configured target.")
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
    section("Academic record", "cap", "From attendance sessions and assessment marks")
    kpis([("Registration no.", info.get("registration_no") or "Not set", info.get("program_code") or "No programme", None, "cap"),
          ("Semester", str(info.get("semester") or "–"), term["name"] if term else "No current term", None, "calendar"),
          ("Recorded attendance", "–" if att["pct"] is None else f"{att['pct']:g}%",
           f"{att['attended']} of {att['held']} sessions" if att["held"] else "No sessions recorded",
           RISK_COLORS["High"] if att["pct"] is not None and att["pct"] < s["attendance_target"] else None, "calendar"),
          ("Missing submissions", str(summ["missing"]), f"of {summ['count']} assessments",
           RISK_COLORS["Moderate"] if summ["missing"] else None, "flag")])
    by_sub = svc_att.by_subject(sid)
    marks = svc_assess.student_marks(sid)
    if by_sub.empty and marks.empty:
        empty("No attendance sessions or assessment marks are recorded for this student yet. Teachers enter them on "
              "the Attendance & marks page.", "calendar")
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
        empty("Choose a student in the sidebar to see their profile. Manual-entry profiles have no saved history.")
        return
    info = c["info"]
    header(info["name"] or c["sid"])
    tag = demo_badge() if info.get("is_demo") else ""
    st.markdown(f'<p class="why">{esc(c["sid"])}, {esc(info.get("department") or "No department")}, '
                f'{esc(info.get("class_section") or "no class")}, source: {esc(info["source"])} {tag}</p>',
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
                           '<span class="why">None at target yet.</span>') + "</div>", unsafe_allow_html=True)
    with r_:
        with st.container(key="card_weak"):
            st.markdown('<div class="pd-k">Needs work</div><div class="tagrow">'
                        + ("".join(f'<span class="tag2 bad">{esc(x)}</span>' for x in weaknesses) or
                           '<span class="why">Nothing below target.</span>') + "</div>", unsafe_allow_html=True)

    section("Subject-wise performance", "book")
    if sub is None:
        empty("No subject scores recorded. Add them below or import them to enable subject analysis.")
    else:
        sub = sub.sort_values("score")
        colors = [RISK_COLORS["High"] if x < 60 else RISK_COLORS["Moderate"] if x < 75 else RISK_COLORS["Low"]
                  for x in sub["score"]]
        fig = go.Figure(go.Bar(x=sub["score"], y=sub["subject"], orientation="h", marker_color=colors,
                               text=[f"{x:.0f}%" for x in sub["score"]], textposition="outside"))
        fig.update_layout(height=60 + 42 * len(sub), xaxis=dict(range=[0, 108]), yaxis=dict(autorange="reversed"),
                          title="Latest score per subject (green 75+, amber 60-74, red below 60)")
        st.plotly_chart(fig)
        st.markdown(f"Priority subject: **{sub.iloc[0]['subject']}** ({sub.iloc[0]['score']:.0f}%).")

    section("Progress history", "trend")
    rec = db.records_df(c["sid"])
    if len(rec) < 2:
        empty("Only one record so far. Each new record (Prediction page, Save, or Data import) adds to this history.")
    else:
        rec = rec.assign(Predicted=predict_many(b, rec).round(1))
        first, last = rec["Predicted"].iloc[0], rec["Predicted"].iloc[-1]
        st.markdown(f"Predicted score moved **{last - first:+.1f} points** across {len(rec)} records "
                    f"({rec['record_date'].iloc[0]} to {rec['record_date'].iloc[-1]}).")
        long = rec.melt(id_vars="record_date", value_vars=["Predicted", "Attendance", "Assignment_Score"],
                        var_name="Measure", value_name="Value")
        long["Measure"] = long["Measure"].replace({"Assignment_Score": "Assignment"})
        fig = px.line(long, x="record_date", y="Value", color="Measure", markers=True)
        fig.update_layout(height=320, xaxis_title=None, legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig)
        if rec["final_score"].notna().any():
            why("Actual final scores are recorded for some records and shown in the table below.")
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
        with st.expander("Add subject scores"):
            with st.form("subj"):
                subj = st.selectbox("Subject", SUBJECTS_DEFAULT + ["Other"])
                other = st.text_input("Subject name (if Other)")
                score = st.number_input("Score (%)", 0.0, 100.0, 70.0)
                d = st.date_input("Date", value=date.today())
                if st.form_submit_button("Add score"):
                    name = other.strip() if subj == "Other" else subj
                    if not name:
                        st.error("Enter a subject name.")
                    else:
                        db.add_subject_score(c["sid"], name[:60], score, d.isoformat())
                        st.success(f"Added {name}: {score:g}%.")
                        st.rerun()
