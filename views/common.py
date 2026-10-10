"""Shared UI: theme, components, cached loaders and the per-run student context."""
from __future__ import annotations

import html
import json

import pandas as pd
import streamlit as st

from config import FEATURES, MODEL_PATH, RISK_COLORS
from database import database as db
from ml.predict import load_bundle, predict_many
from utils.risk_engine import assess
from views import theme as theme_mod

INK, MUTED, LINE, PAPER = "#22223B", "#5E6178", "#E2DDF0", "#F7F6FB"


def accent(n: int = 0) -> str:
    """Role-specific chart colour: 0 primary, 1 accent, 2 secondary accent, 3 soft."""
    t = theme_of()
    return [t["primary"], t["accent"], t["accent2"], t["soft"], t["primary2"]][n]


def theme_of() -> dict:
    return theme_mod.theme(theme_mod.current_role())


def apply_theme(role: str | None = None):
    theme_mod.apply(role or theme_mod.current_role())


def esc(x) -> str:
    return html.escape(str(x))


def _status_chips() -> str:
    """Live system status shown in the admin hero (real values, not decoration)."""
    c = st.session_state.get("ctx") or {}
    b = c.get("bundle")
    try:
        with db.connect() as con:
            n_rec = con.execute("SELECT COUNT(*) FROM academic_records").fetchone()[0]
            n_stu = con.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        n_demo = db.demo_count()
    except Exception:
        n_rec = n_stu = n_demo = 0
    chips = [(f"Model online: {b['model_name']}" if b else "Model unavailable", bool(b)),
             (f"{n_stu} students, {n_rec} records", True),
             ("Demo data loaded" if n_demo else "No demo data", not n_demo)]
    return "".join(f'<span class="chip"><span class="dot{"" if ok else " off"}"></span>{esc(t)}</span>' for t, ok in chips)


def header(title: str, lede: str | None = None, eyebrow: str | None = None):
    role = theme_mod.current_role()
    chips = f'<div class="chips">{_status_chips()}</div>' if role == "admin" else ""
    eb = eyebrow or theme_mod.LABELS.get(role, "")
    st.markdown(
        f'<div class="hero"><div class="in"><div><div class="eyebrow"><i></i>{esc(eb)}</div><h1>{esc(title)}</h1>'
        f'{f"<p class=lede>{esc(lede)}</p>" if lede else ""}{chips}</div>'
        f'<div class="art">{theme_mod.hero_art(role)}</div></div></div>', unsafe_allow_html=True)


def section(title: str, icon_name: str = "spark", sub: str | None = None):
    """Section heading with a small themed icon and an optional right-aligned note."""
    note = f'<span class="sub">{esc(sub)}</span>' if sub else ""
    st.markdown(f'<div class="sect"><div class="ic">{theme_mod.icon(icon_name, 18)}</div><h3>{esc(title)}</h3>{note}</div>',
                unsafe_allow_html=True)


def kpis(items: list[tuple]):
    """items: (label, value, sub, color|None[, icon])"""
    cells = []
    for it in items:
        l, v, s, c = it[:4]
        ic = it[4] if len(it) > 4 else theme_mod.icon_for(l)
        style = f"--kc:{c};--vc:{c}" if c else ""
        cells.append(f'<div class="kcard" style="{style}"><div class="ic">{theme_mod.icon(ic, 19)}</div>'
                     f'<div class="l">{esc(l)}</div><div class="v{" sm" if len(str(v)) > 9 else ""}">{esc(v)}</div><div class="s">{esc(s or "")}</div></div>')
    st.markdown(f'<div class="kgrid">{"".join(cells)}</div>', unsafe_allow_html=True)


def risk_banner(risk: dict, sentence: str):
    c = RISK_COLORS[risk["level"]]
    meta = "Teacher intervention recommended." if risk["intervention_required"] else "No intervention needed right now."
    on = " on" if risk["level"] == "High" else ""
    st.markdown(f'<div class="risk" style="--rc:{c}"><div class="title"><span class="pulse{on}"></span>{esc(risk["level"])} risk</div>'
                f'<div class="body">Risk score {risk["score"]:.0f} of 100. {esc(sentence)}</div>'
                f'<div class="meta">{esc(meta)}</div></div>', unsafe_allow_html=True)


def dialog_head(icon_name: str, title: str, desc: str = ""):
    """Coloured icon + title row used at the top of every pop-up."""
    st.markdown(f'<div class="dlg-hero"><div class="ic">{theme_mod.icon(icon_name, 22, "#FFFFFF")}</div>'
                f'<div><div class="t">{esc(title)}</div><div class="d">{esc(desc)}</div></div></div>',
                unsafe_allow_html=True)


def empty(text: str, icon_name: str = "info"):
    st.markdown(f'<div class="empty"><div class="ic">{theme_mod.icon(icon_name, 20)}</div><div>{esc(text)}</div></div>',
                unsafe_allow_html=True)


def demo_badge(text="Synthetic demo data"):
    return f'<span class="badge demo">{esc(text)}</span>'


def why(text: str):
    st.markdown(f'<div class="why">{esc(text)}</div>', unsafe_allow_html=True)


# ---------------- cached loaders ----------------
@st.cache_resource(show_spinner="Loading model…")
def _model(mtime: float):
    bundle, err = load_bundle()
    if bundle is None:
        from ml.train_model import train
        try:
            bundle = train()
            bundle["_notice"] = err + " A new model was trained from data/student_performance.csv."
        except Exception as e:
            return None, f"{err} Retraining also failed: {e}"
    return bundle, None


def get_model():
    mtime = MODEL_PATH.stat().st_mtime if MODEL_PATH.exists() else 0.0
    return _model(mtime)


def require_model():
    bundle, err = get_model()
    if bundle is None:
        st.error(f"The prediction model is unavailable. {err} "
                 "Fix the dataset in data/student_performance.csv, then run `python -m ml.train_model`.")
        st.stop()
    return bundle


def _data_key():
    with db.connect() as con:
        return tuple(con.execute("SELECT COUNT(*), COALESCE(MAX(id),0) FROM academic_records").fetchone())


@st.cache_data(show_spinner=False)
def _roster(_bundle, model_key, settings_json, data_key):
    """Latest record + risk for every student. Recomputed when data, settings or model change."""
    s = json.loads(settings_json)
    rec = db.records_df()
    if rec.empty:
        return pd.DataFrame(), pd.DataFrame()
    rec["Predicted"] = predict_many(_bundle, rec)
    rows = []
    for sid, g in rec.groupby("student_id", sort=True):
        g = g.sort_values(["record_date", "id"])
        last = g.iloc[-1]
        values = {f: float(last[f]) for f in FEATURES}
        hist = g["Predicted"].tolist()[:-1]
        r = assess(values, float(last["Predicted"]), s, hist)
        rows.append({"Student": sid, "Name": last["name"], "Department": last["department"],
                     "Class": last["class_section"], "Demo": bool(last["is_demo"]),
                     "Predicted score": round(float(last["Predicted"]), 1), "Risk": r["level"],
                     "Risk score": r["score"], "Attendance": values["Attendance"],
                     "Assignment": values["Assignment_Score"], "Internal": values["Internal_Marks"],
                     "Study hours": values["Study_Hours"], "Main concern": r["main_concern"],
                     "Trend": float("nan") if r["trend"]["change"] is None else r["trend"]["change"], "Records": len(g),
                     "Intervention": r["intervention_required"], "_risk": r})
    return pd.DataFrame(rows), rec


def roster(bundle):
    s = db.get_settings()
    return _roster(bundle, bundle["trained_at"] + str(bundle["training_rows"]), json.dumps(s, sort_keys=True), _data_key())


def risk_chip(level: str) -> str:
    return {"Low": "🟢 Low", "Moderate": "🟡 Moderate", "High": "🔴 High"}[level]


def ctx():
    return st.session_state["ctx"]


def analysis():
    return st.session_state["ctx"]["analysis"]


def role() -> str:
    return st.session_state["user"]["role"]


def require_role(*roles):
    """Second line of defence: pages check the role themselves, not only the navigation menu."""
    if role() not in roles:
        st.error("You don't have access to this page.")
        st.stop()


# ---------------- teacher scope ----------------
def scope() -> tuple[list[str] | None, str | None]:
    """Which classes the current view covers.
    Teacher: their own classes (None = no classes assigned yet, so everything is shown).
    Admin: the teacher chosen in the sidebar, or None for the whole institution."""
    user = st.session_state.get("user") or {}
    if user.get("role") == "teacher":
        return (db.get_teacher_classes(user["username"]) or None), user["username"]
    if user.get("role") == "admin" and st.session_state.get("view_teacher"):
        t = st.session_state["view_teacher"]
        return db.get_teacher_classes(t), t
    return None, None


def teacher_name(username: str | None) -> str:
    if not username:
        return ""
    u = db.get_user(username)
    return (u or {}).get("display_name") or username


def scoped_roster(bundle):
    df, rec = roster(bundle)
    classes, _ = scope()
    if classes is not None and not df.empty:
        df = df[df["Class"].isin(classes)]
        rec = rec[rec["class_section"].isin(classes)]
    return df, rec


TEACHER_HUES = [("#1E3A6E", "#3B6DB3"), ("#C8643B", "#E3925F"), ("#2B7A78", "#43A8A5"),
                ("#6D28D9", "#9B6BF2"), ("#0E7490", "#22B8D6"), ("#9A3412", "#C2410C")]
TITLES = ("dr", "prof", "ms", "mr", "mrs")


def initials(name: str) -> str:
    words = [w for w in str(name).replace(".", " ").split() if w[:1].isalnum() and w.lower() not in TITLES]
    return "".join(w[0] for w in words)[:2].upper() or "?"


def avatar(name: str, seed: str, big: bool = False, status: str | None = None) -> str:
    c1, c2 = TEACHER_HUES[sum(map(ord, seed)) % len(TEACHER_HUES)]
    st_ = f";--st:{status}" if status else ""
    return f'<div class="tav{" lg" if big else ""}" style="--c1:{c1};--c2:{c2}{st_}">{esc(initials(name))}</div>'


def teacher_directory(bundle) -> list[dict]:
    """Every teacher with subject, classes and live statistics from their students' latest records."""
    df, _ = roster(bundle)
    ints = db.interventions_df()
    out = []
    for t in db.teachers_df().itertuples():
        classes = db.get_teacher_classes(t.username)
        mine = df[df["Class"].isin(classes)] if not df.empty else df
        n = len(mine)
        high = int((mine["Risk"] == "High").sum()) if n else 0
        open_iv = (int((ints["student_id"].isin(mine["Student"]) & (ints["status"] != "Closed")).sum())
                   if n and not ints.empty else 0)
        status = RISK_COLORS["High"] if n and high / n >= .25 else RISK_COLORS["Moderate"] if high else RISK_COLORS["Low"]
        out.append({"username": t.username, "name": t.display_name or t.username,
                    "subject": t.subject or "Subject not set", "classes": classes, "students": n, "high": high,
                    "open": open_iv, "status": status, "avg": float(mine["Predicted score"].mean()) if n else None})
    return out


def teacher_card_html(t: dict, big: bool = False) -> str:
    chips = "".join(f'<span class="tag2">{esc(c)}</span>' for c in t["classes"]) or \
        '<span class="why">No classes assigned</span>'
    avg = f"{t['avg']:.0f}" if t["avg"] is not None else "–"
    hc = RISK_COLORS["High"] if t["high"] else "inherit"
    return (f'<div class="tcard">{avatar(t["name"], t["username"], big, t["status"])}<div>'
            f'<div class="tname">{esc(t["name"])}</div><div class="tsub">@{esc(t["username"])}</div>'
            f'<div class="tsubj">{theme_mod.icon("book", 13)} {esc(t["subject"])}</div></div></div>'
            f'<div class="tagrow" style="margin-top:10px">{chips}</div>'
            f'<div class="tstats"><div><b>{t["students"]}</b><span>Students</span></div>'
            f'<div><b style="color:{hc}">{t["high"]}</b><span>High risk</span></div>'
            f'<div><b>{avg}</b><span>Avg score</span></div><div><b>{t["open"]}</b><span>Open plans</span></div></div>')


def view_teacher(username: str | None):
    """Open (or leave) a teacher's dashboard as admin. Only ever called from an explicit admin action."""
    st.session_state["view_teacher"] = username
    st.session_state.pop("tpick", None)
    if username:
        st.session_state["_goto"] = "teacher"


def _pick(username):
    st.session_state["tpick"] = username


def _on_switch():
    st.session_state["view_teacher"] = st.session_state.get("switch_teacher")


def teacher_picker(bundle, key: str = "tp", edit_dialog=None):
    """Admin: choose a teacher explicitly, then open their dashboard. Nothing opens automatically."""
    teachers = teacher_directory(bundle)
    if not teachers:
        empty("No teacher accounts yet.", "users")
        return
    names = {t["username"]: t for t in teachers}
    with st.container(key=f"card_{key}_bar"):
        c1, c2 = st.columns([2.2, 1.2], vertical_alignment="bottom")
        c1.selectbox("Select teacher", list(names), index=None, key="tpick", placeholder="Choose a teacher…",
                     format_func=lambda u: f"{names[u]['name']} · {names[u]['subject']}")
        chosen = st.session_state.get("tpick")
        c2.button("View teacher dashboard", type="primary", icon=":material/dashboard:", width="stretch",
                  disabled=chosen not in names, on_click=view_teacher, args=(chosen,), key=f"{key}_view")
        why("Pick a teacher from the list or a card below, then open their dashboard to see exactly what they see.")
    cols = st.columns(min(3, len(teachers)), gap="medium")
    for i, t in enumerate(teachers):
        u = t["username"]
        selected = st.session_state.get("tpick") == u
        with cols[i % len(cols)]:
            with st.container(key=f"card_hover_{'tpick_sel' if selected else 'tpick'}_{key}_{u}"):
                st.markdown(teacher_card_html(t), unsafe_allow_html=True)
                b1, b2 = st.columns(2)
                b1.button("Selected" if selected else "Select", key=f"{key}_sel_{u}", width="stretch",
                          icon=":material/check_circle:" if selected else ":material/radio_button_unchecked:",
                          on_click=_pick, args=(u,))
                if edit_dialog:
                    if b2.button("Edit", key=f"{key}_edit_{u}", icon=":material/edit:", width="stretch"):
                        edit_dialog(u, t["name"], "" if t["subject"] == "Subject not set" else t["subject"])
                else:
                    b2.button("Open", key=f"{key}_open_{u}", icon=":material/arrow_forward:", width="stretch",
                              on_click=view_teacher, args=(u,), type="tertiary")


def scope_banner():
    """Whose students are shown. For an admin viewing a teacher: a switcher bar with that teacher's profile."""
    classes, t = scope()
    r = role()
    if r == "teacher":
        text = (f"Your classes: {', '.join(classes)}." if classes else
                "No classes are assigned to you yet, so all students are shown. Ask an admin to assign your classes.")
    elif r == "admin" and t:
        teachers = teacher_directory(st.session_state["ctx"]["bundle"])
        me = next((x for x in teachers if x["username"] == t), None)
        if me is None:   # teacher account no longer exists
            st.session_state["view_teacher"] = None
            st.rerun()
        with st.container(key="card_viewas"):
            c1, c2 = st.columns([2.3, 1.2], vertical_alignment="center", gap="large")
            c1.markdown('<div class="why" style="margin-bottom:8px;letter-spacing:.08em">VIEWING AS ADMIN</div>'
                        + teacher_card_html(me, big=True), unsafe_allow_html=True)
            with c2:
                ids = [x["username"] for x in teachers]
                st.session_state["switch_teacher"] = t
                st.selectbox("Switch teacher", ids, key="switch_teacher", on_change=_on_switch,
                             format_func=lambda u: next(x["name"] for x in teachers if x["username"] == u))
                st.button("Back to teacher list", on_click=view_teacher, args=(None,), icon=":material/arrow_back:",
                          width="stretch", key="viewas_back")
        return
    elif r == "admin":
        text = "Showing all students in the institution. Open the Teacher dashboard to view one teacher's classes."
    else:
        return
    st.markdown(f'<div class="context">{esc(text)}</div>', unsafe_allow_html=True)
