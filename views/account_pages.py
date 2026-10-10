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
    "assignment_min": ("Assignment score: isse neeche risk", 0.0, 100.0, 1.0),
    "internal_min": ("Internal marks: isse neeche risk", 0.0, 100.0, 1.0),
    "study_hours_min": ("Study hours/day: isse neeche risk", 0.0, 24.0, 0.5),
    "previous_min": ("Previous marks: isse neeche risk", 0.0, 100.0, 1.0),
    "assignment_target": ("Assignment score: plan target", 0.0, 100.0, 1.0),
    "internal_target": ("Internal marks: plan target", 0.0, 100.0, 1.0),
    "study_hours_target": ("Study hours/day: plan target", 0.0, 12.0, 0.5),
    "pass_score": ("Pass mark (predicted score)", 0.0, 100.0, 1.0),
    "watch_score": ("Watch level (predicted score)", 0.0, 100.0, 1.0),
    "decline_points": ("Decline alert: kam se kam itni giraavat (points)", 0.0, 50.0, 0.5),
    "risk_high": ("Is risk score se High risk", 0.0, 100.0, 1.0),
    "risk_moderate": ("Is risk score se Moderate risk", 0.0, 100.0, 1.0),
}


def notifications():
    user = st.session_state["user"]
    header("Notifications", "Risk, attendance, assignments, giraavat aur interventions ke alerts.")
    df = db.notifications_for(user["role"], user.get("student_id"))
    if df.empty:
        empty("Koi notification nahi hai. Records save ya import hone par jab koi rule trigger hota hai tab alerts aate hain.")
        return
    show = st.radio("Dikhayein", ["Unread", "Sab"], horizontal=True)
    view = df[df["is_read"] == 0] if show == "Unread" else df
    types = sorted(view["type"].unique())
    pick = st.multiselect("Type", types, default=types)
    view = view[view["type"].isin(pick)]
    if view.empty:
        empty("Kuch bhi unread nahi hai. Purane alerts dekhne ke liye Sab chunein.")
        return
    if st.button(f"{len(view)} ko Read Mark Karein"):
        db.mark_read(view["id"].tolist())
        st.rerun()
    cards = []
    for r in view.head(200).itertuples():
        col = SEVERITY_COLOR.get(r.severity, "#64748B")
        new = '<span class="tag2" style="margin-left:6px">Naya</span>' if not r.is_read else ""
        cards.append(f'<div class="factor" style="--rc:{col}"><span class="pts">{esc(r.severity.capitalize())}</span>'
                     f'<div><b>{esc(r.type.replace("_", " ").capitalize())}</b>{new}'
                     f'<span class="why"> · {esc(r.created_at)}</span><br>{esc(r.message)}</div></div>')
    with st.container(key="card_notifs"):
        st.markdown("".join(cards), unsafe_allow_html=True)
    why("Alerts app ke andar hamesha dikhte hain. Email/SMS tabhi jaate hain jab admin ne unhe configure kiya ho (Users & security, Email / SMS).")


def settings():
    user = st.session_state["user"]
    header("Settings", "Early-warning system aur study planner ke thresholds.")
    s = db.get_settings()
    editable = role() in ("teacher", "admin")
    if not editable:
        why("Thresholds sirf teachers aur admins badal sakte hain.")
    with st.form("thresholds"):
        cols = st.columns(3)
        new = {}
        for i, (k, (label, lo, hi, step)) in enumerate(LABELS.items()):
            new[k] = cols[i % 3].number_input(label, lo, hi, float(s[k]), step=step, disabled=not editable, key=f"set_{k}")
        c1, c2 = st.columns([1, 4])
        save = c1.form_submit_button("Settings Save Karein", type="primary", disabled=not editable)
        reset = c2.form_submit_button("Default Wapas Laayein", disabled=not editable)
    if save:
        if new["risk_moderate"] >= new["risk_high"]:
            st.error("Moderate-risk cut-off high-risk cut-off se kam hona chahiye.")
        elif new["pass_score"] >= new["watch_score"]:
            st.error("Pass mark watch level se kam hona chahiye.")
        else:
            changed = {k: (s[k], v) for k, v in new.items() if s.get(k) != v}
            db.save_settings(new)
            audit.log("settings.update", user, "settings", None, {"changed": changed})
            st.success("Settings save ho gayi. Ab saare dashboards naye thresholds use karenge.")
            st.rerun()
    if reset:
        db.save_settings(DEFAULT_SETTINGS)
        audit.log("settings.reset", user, "settings")
        for k in LABELS:
            st.session_state.pop(f"set_{k}", None)
        st.success("Default thresholds wapas aa gaye.")
        st.rerun()

    section("Contact details", "bell", "Email/SMS alerts ke liye")
    me = db.get_user(user["username"]) or {}
    with st.form("contact"):
        c1, c2 = st.columns(2)
        email = c1.text_input("Email", value=me.get("email") or "", placeholder="naam@college.edu")
        phone = c2.text_input("Phone", value=me.get("phone") or "", placeholder="+919876543210")
        if st.form_submit_button("Contact Details Save Karein"):
            err = auth.update_contact(me, user["username"], email, phone)
            if err:
                st.error(err)
            else:
                st.success("Contact details save ho gayi.")
    why("Email ya SMS tabhi jaayega jab admin ne email/SMS service configure ki ho. Status Users & security mein dikhta hai.")

    section("Account", "shield")
    with st.form("pw"):
        cur = st.text_input("Abhi ka password", type="password")
        pw1 = st.text_input("Naya password", type="password")
        pw2 = st.text_input("Naya password dobara", type="password")
        ok = st.form_submit_button("Password Badlein")
    if ok:
        err = auth.change_own_password(user, cur, pw1, pw2)
        if err:
            st.error(err)
        else:
            st.success("Password badal gaya.")


def responsible_ai():
    header("AI limitations", "Is system ko zimmedaari se kaise use karein.")
    b = st.session_state["ctx"]["bundle"]
    st.markdown(f"""
**Predictions andaaze hain.** Model {b['training_rows']} records par trained hai. Validation mein uski predictions
average {b['metrics']['MAE']:.1f} points se alag thi, aur yeh number bhi pakka nahi hai kyunki bahut kam records se aaya hai.

**Madad ke liye, jagah lene ke liye nahi.** System students ko flag karta hai aur actions suggest karta hai; faisla teacher
karte hain. Yeh beemaari, ghar ke haalaat, kaam ka bojh ya apne paanch inputs ke bahar kuch bhi nahi dekh sakta.

**Kam ya biased data se bharosa ghatta hai.** Model wahi seekhta hai jo records mein hai. Agar kuch groups ke students kam
hain, toh unke liye predictions kharaab ho sakti hain. Abhi ka dataset itna chhota hai ki yeh check nahi ho sakta.

**Bade faislon ke liye akele use na karein.** Grading, promotion, scholarship ya disciplinary action sirf predictions ke
aadhaar par nahi hone chahiye.

**Explanations rishta dikhati hain, wajah nahi.** Explainable AI page batata hai ki model inputs ko kaise use karta hai.
Abhi ke data mein saare inputs saath-saath badalte hain, isliye model factors ko alag-alag theek se nahi pehchaan sakta.

**Student data surakshit rakhein.** Records `data/app.db` mein locally save hote hain. Passwords PBKDF2 se hashed hain.
Asli use se pehle: demo passwords badlein, database file ka access seemit karein, backups encrypted rakhein, aur apne
institution ki data-protection policy follow karein.
""")
    for lim in b["limitations"]:
        st.warning(lim)
