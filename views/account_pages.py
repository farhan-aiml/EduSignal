"""Account pages: notification center, settings, AI limitations."""
from __future__ import annotations

import streamlit as st

from config import DEFAULT_SETTINGS
from database import database as db
from utils import auth
from config import RISK_COLORS
from services import audit
from views.common import empty, esc, header, role, section, why

SEVERITY_COLOR = {"high": RISK_COLORS["High"], "medium": RISK_COLORS["Moderate"], "low": RISK_COLORS["Low"]}
LABELS = {
    "attendance_target": ("Attendance target (%)", 0.0, 100.0, 1.0),
    "assignment_min": ("Assignment score: risk below", 0.0, 100.0, 1.0),
    "internal_min": ("Internal marks: risk below", 0.0, 100.0, 1.0),
    "study_hours_min": ("Study hours/day: risk below", 0.0, 24.0, 0.5),
    "previous_min": ("Previous marks: risk below", 0.0, 100.0, 1.0),
    "assignment_target": ("Assignment score: plan target", 0.0, 100.0, 1.0),
    "internal_target": ("Internal marks: plan target", 0.0, 100.0, 1.0),
    "study_hours_target": ("Study hours/day: plan target", 0.0, 12.0, 0.5),
    "pass_score": ("Pass mark (predicted score)", 0.0, 100.0, 1.0),
    "watch_score": ("Watch level (predicted score)", 0.0, 100.0, 1.0),
    "decline_points": ("Decline alert: drop of at least (points)", 0.0, 50.0, 0.5),
    "risk_high": ("High risk from risk score", 0.0, 100.0, 1.0),
    "risk_moderate": ("Moderate risk from risk score", 0.0, 100.0, 1.0),
}


def notifications():
    user = st.session_state["user"]
    header("Notifications", "Alerts about risk, attendance, assignments, declines and interventions.")
    df = db.notifications_for(user["role"], user.get("student_id"))
    if df.empty:
        empty("No notifications. Alerts appear when records are saved or imported and a rule is triggered.")
        return
    show = st.radio("Show", ["Unread", "All"], horizontal=True)
    view = df[df["is_read"] == 0] if show == "Unread" else df
    types = sorted(view["type"].unique())
    pick = st.multiselect("Type", types, default=types)
    view = view[view["type"].isin(pick)]
    if view.empty:
        empty("Nothing unread. Switch to All to see earlier alerts.")
        return
    if st.button(f"Mark {len(view)} as read"):
        db.mark_read(view["id"].tolist())
        st.rerun()
    cards = []
    for r in view.head(200).itertuples():
        col = SEVERITY_COLOR.get(r.severity, "#64748B")
        new = '<span class="tag2" style="margin-left:6px">New</span>' if not r.is_read else ""
        cards.append(f'<div class="factor" style="--rc:{col}"><span class="pts">{esc(r.severity.capitalize())}</span>'
                     f'<div><b>{esc(r.type.replace("_", " ").capitalize())}</b>{new}'
                     f'<span class="why"> · {esc(r.created_at)}</span><br>{esc(r.message)}</div></div>')
    with st.container(key="card_notifs"):
        st.markdown("".join(cards), unsafe_allow_html=True)
    why("Delivery is in-app for now. The notification module has a channel interface for adding email or SMS.")


def settings():
    user = st.session_state["user"]
    header("Settings", "Thresholds used by the early-warning system and study planner.")
    s = db.get_settings()
    editable = role() in ("teacher", "admin")
    if not editable:
        why("Only teachers and admins can change thresholds.")
    with st.form("thresholds"):
        cols = st.columns(3)
        new = {}
        for i, (k, (label, lo, hi, step)) in enumerate(LABELS.items()):
            new[k] = cols[i % 3].number_input(label, lo, hi, float(s[k]), step=step, disabled=not editable, key=f"set_{k}")
        c1, c2 = st.columns([1, 4])
        save = c1.form_submit_button("Save settings", type="primary", disabled=not editable)
        reset = c2.form_submit_button("Restore defaults", disabled=not editable)
    if save:
        if new["risk_moderate"] >= new["risk_high"]:
            st.error("Moderate-risk cut-off must be lower than the high-risk cut-off.")
        elif new["pass_score"] >= new["watch_score"]:
            st.error("Pass mark must be lower than the watch level.")
        else:
            changed = {k: (s[k], v) for k, v in new.items() if s.get(k) != v}
            db.save_settings(new)
            audit.log("settings.update", user, "settings", None, {"changed": changed})
            st.success("Settings saved. All dashboards now use the new thresholds.")
            st.rerun()
    if reset:
        db.save_settings(DEFAULT_SETTINGS)
        audit.log("settings.reset", user, "settings")
        for k in LABELS:
            st.session_state.pop(f"set_{k}", None)
        st.success("Default thresholds restored.")
        st.rerun()

    section("Account", "shield")
    with st.form("pw"):
        cur = st.text_input("Current password", type="password")
        pw1 = st.text_input("New password", type="password")
        pw2 = st.text_input("Repeat new password", type="password")
        ok = st.form_submit_button("Change password")
    if ok:
        err = auth.change_own_password(user, cur, pw1, pw2)
        if err:
            st.error(err)
        else:
            st.success("Password changed.")


def responsible_ai():
    header("AI limitations", "How to use this system responsibly.")
    b = st.session_state["ctx"]["bundle"]
    st.markdown(f"""
**Predictions are estimates.** The model was trained on {b['training_rows']} records. In validation its
predictions were off by {b['metrics']['MAE']:.1f} points on average, and that figure itself is uncertain
because it comes from so few records.

**Support, not replacement.** The system flags students and suggests actions; teachers decide. It cannot
see illness, family circumstances, workload or anything else outside its five inputs.

**Small or biased data reduces reliability.** A model reflects the records it learned from. If those records
under-represent some groups of students, its predictions for them may be worse. The current dataset is too
small to check this.

**Not for high-impact decisions on its own.** Predictions must not be the sole basis for grading, progression,
scholarships or disciplinary action.

**Explanations show association, not cause.** The Explainable AI page describes how the model uses its inputs.
Because every input in the current data moves together, the model cannot reliably separate one factor from another.

**Handle student data securely.** Records are stored locally in `data/app.db`. Passwords are hashed with
PBKDF2. Before real use: change the demo passwords, restrict access to the database file, keep backups
encrypted, and follow your institution's data-protection policy.
""")
    for lim in b["limitations"]:
        st.warning(lim)
