"""EduSignal frontend entry point: page setup, sign-in, student context and navigation.

Started by the launcher in the project root:  streamlit run app.py
All data access goes through backend/ (database, services, ML).
"""
import streamlit as st

from backend.config import ASSETS_DIR, FEATURE_NAMES  # noqa: E402
from backend.database import database as db  # noqa: E402
from backend.utils import auth  # noqa: E402
from backend.utils.analysis import analyze  # noqa: E402
from backend.utils.demo_data import seed_dataset_records, seed_demo_once  # noqa: E402
from backend.services import access, audit, seed  # noqa: E402
from backend.services import models as model_registry  # noqa: E402
from frontend.views import account_pages, admin_pages, records_pages, reports_pages, security_pages, staff_pages, student_pages  # noqa: E402
from frontend.views.login import login_screen  # noqa: E402
from frontend.views import assistant_panel  # noqa: E402
from frontend.views.common import apply_theme, demo_badge, esc, get_model, predict_many, scope  # noqa: E402
from frontend.views.common import initials as initials_of  # noqa: E402

DEFAULT_VALUES = {"Attendance": 80.0, "Assignment_Score": 75.0, "Internal_Marks": 70.0,
                  "Study_Hours": 4.0, "Previous_Marks": 75.0}   # same defaults as the original app


@st.cache_resource(show_spinner="Preparing demo students…")
def first_run_demo(_bundle, model_key: str):
    seed_demo_once(_bundle)
    seed.seed_structure()          # sections/enrollments for any students added above
    seed.seed_demo_academics()     # synthetic attendance + marks for demo students only (idempotent)
    model_registry.register(_bundle)
    return True


@st.cache_resource
def bootstrap():
    db.init_db()                   # versioned migrations; backs up backend/data/app.db before applying any
    seed_dataset_records()
    auth.seed_demo_accounts()
    auth.seed_teacher_classes()
    auth.seed_teacher_subjects()
    seed.seed_structure()
    return True


def student_selector(user):
    """Teachers and admins choose which student's context the student pages show."""
    if user["role"] == "student":
        return user.get("student_id")
    # Admins choose a teacher explicitly on the Teacher dashboard (views.common.teacher_picker), never here.
    studs = db.students_df()
    classes, _ = scope() if user["role"] == "teacher" else (None, None)
    pending_sid = st.session_state.get("pending_student")
    if classes is not None:   # only students in the teacher's classes (plus one opened from elsewhere)
        studs = studs[studs["class_section"].isin(classes) | (studs["student_id"] == pending_sid)]
    order = studs.sort_values(["is_demo", "student_id"], ascending=[False, True])   # named demo students first
    options = [None] + order["student_id"].tolist()
    if st.session_state.get("selected_student") not in options:
        st.session_state["selected_student"] = None
    pending = st.session_state.pop("pending_student", None)
    if pending is not None and pending in options:
        st.session_state["selected_student"] = pending
    names = dict(zip(studs["student_id"], studs["name"]))
    demo = dict(zip(studs["student_id"], studs["is_demo"]))
    return st.sidebar.selectbox(
        "Viewing student", options, key="selected_student",
        format_func=lambda s: "Manual entry (no saved record)" if s is None else
        f"{names.get(s) or s}{' (demo)' if demo.get(s) else ''}, {s}")


def load_profile(sid):
    """Reset editable values when the selected student changes."""
    if st.session_state.get("profile_for", "unset") == sid:
        return
    values, held, attended = dict(DEFAULT_VALUES), None, None
    if sid:
        rec = db.records_df(sid)
        if not rec.empty:
            last = rec.iloc[-1]
            values = {f: float(last[f]) for f in FEATURE_NAMES}
            held = None if last["classes_held"] != last["classes_held"] else last["classes_held"]
            attended = None if last["classes_attended"] != last["classes_attended"] else last["classes_attended"]
    st.session_state.update(profile_values=values, saved_values=dict(values), profile_for=sid,
                            classes_held=int(held) if held else 0, classes_attended=int(attended) if attended else 0)
    for k in [k for k in st.session_state if str(k).startswith(("w_", "wi_"))]:
        del st.session_state[k]


def build_context(bundle, user, sid):
    settings = db.get_settings()
    info, history, subjects = None, [], None
    if sid:
        studs = db.students_df()
        row = studs[studs["student_id"] == sid]
        info = row.iloc[0].to_dict() if not row.empty else None
        rec = db.records_df(sid)
        if len(rec) > 1:
            history = [float(x) for x in predict_many(bundle, rec.iloc[:-1])]
        sub = db.latest_subject_scores(sid)
        subjects = sub if not sub.empty else None
    held, att = st.session_state.get("classes_held") or None, st.session_state.get("classes_attended")
    a = analyze(bundle, st.session_state["profile_values"], settings, history, subjects,
                held, att if held else None)
    st.session_state["ctx"] = {"sid": sid, "info": info, "settings": settings, "analysis": a,
                               "edited": st.session_state["profile_values"] != st.session_state["saved_values"],
                               "bundle": bundle}


ROLE_STYLE = {"student": ("Student", None), "teacher": ("Faculty", None), "admin": ("Administrator", None)}


def sidebar(user, bundle):
    word = "logo_wordmark_light.svg" if user["role"] == "admin" else "logo_wordmark.svg"
    st.logo(str(ASSETS_DIR / word), icon_image=str(ASSETS_DIR / "logo_mark.svg"), size="large")
    name = user["display_name"] or user["username"]
    initials = initials_of(name)
    label, color = ROLE_STYLE[user["role"]]
    st.sidebar.markdown(
        f'<div class="usercard"><div class="avatar">{esc(initials)}</div>'
        f'<div><div class="uname">{esc(name)}</div><span class="rolepill">{label}</span>'
        f'</div></div>', unsafe_allow_html=True)
    n_demo = db.demo_count()
    if n_demo and user["role"] != "student":
        st.sidebar.markdown(demo_badge(f"Includes {n_demo} synthetic demo students"), unsafe_allow_html=True)
    if bundle.get("_notice"):
        st.sidebar.warning(bundle["_notice"])


def main():
    st.set_page_config(page_title="EduSignal: Student Success & Early Warning",
                       page_icon=str(ASSETS_DIR / "logo_mark.svg"), layout="wide")
    bootstrap()
    pre_bundle, _ = get_model()
    if pre_bundle is not None:
        first_run_demo(pre_bundle, pre_bundle["trained_at"])   # one-time demo seeding happens before sign-in
    user = st.session_state.get("user")
    if not user:
        login_screen()
        return
    apply_theme(user["role"])

    bundle, err = get_model()
    if bundle is None:
        st.error(f"The prediction model is unavailable: {err}")
        st.info("Check backend/data/student_performance.csv, then run `python -m backend.ml.train_model` from the project folder.")
        st.stop()
    first_run_demo(bundle, bundle["trained_at"])

    sidebar(user, bundle)
    sid = student_selector(user)
    user = db.get_user(user["username"]) or {}          # re-read the account: role/status come from the DB, not the session
    if not user.get("is_active", 1):
        st.session_state.clear()
        st.error("This account has been deactivated. Contact your administrator.")
        st.stop()
    if not access.can_view_student(user, sid):        # server-side check, whatever the page asked for
        audit.log("student.view", user, "student", sid, outcome="denied")
        st.session_state["selected_student"] = None
        st.error("You don't have access to this student's records.")
        st.stop()
    load_profile(sid)
    build_context(bundle, user, sid)

    P = st.Page
    sections = {
        "Student success": [
            P(student_pages.overview, title="Overview", icon="🏠", url_path="overview", default=user["role"] == "student"),
            P(student_pages.prediction, title="Prediction", icon="🎯", url_path="prediction"),
            P(student_pages.explainable, title="Explainable AI", icon="🧠", url_path="explain"),
            P(student_pages.what_if, title="What-if simulator", icon="🔮", url_path="what-if"),
            P(student_pages.plan, title="Study plan", icon="📚", url_path="study-plan"),
            P(student_pages.early_warning, title="Early warning", icon="🚨", url_path="early-warning"),
            P(student_pages.profile, title="Student profile", icon="👤", url_path="profile"),
            P(reports_pages.reports_page, title="Reports", icon="📄", url_path="reports"),
        ],
    }
    if user["role"] in ("teacher", "admin"):
        sections["Faculty"] = [
            P(staff_pages.teacher_dashboard, title="Teacher dashboard", icon="👨‍🏫", url_path="teacher",
              default=user["role"] == "teacher"),
            P(records_pages.records, title="Attendance & marks", icon="📝", url_path="records"),
            P(staff_pages.analytics, title="Analytics & data quality", icon="📊", url_path="analytics"),
        ]
    if user["role"] == "admin":
        sections["Institution"] = [
            P(admin_pages.institution, title="Admin dashboard", icon="🏛️", url_path="admin",
              default=user["role"] == "admin"),
            P(admin_pages.data_import, title="Data import", icon="📥", url_path="import"),
            P(admin_pages.model_management, title="Model management", icon="⚙️", url_path="models"),
            P(security_pages.users_security, title="Users & security", icon="🔐", url_path="security"),
        ]
    unread = int((db.notifications_for(user["role"], user.get("student_id"))["is_read"] == 0).sum())
    sections["Account"] = [
        P(account_pages.notifications, title=f"Notifications ({unread})" if unread else "Notifications",
          icon="🔔", url_path="notifications"),
        P(account_pages.settings, title="Settings", icon="⚙️", url_path="settings"),
        P(account_pages.responsible_ai, title="AI limitations", icon="⚖️", url_path="responsible-ai"),
    ]
    st.session_state["pages"] = {pg.url_path: pg for group in sections.values() for pg in group}
    page = st.navigation(sections, expanded=True)
    goto = st.session_state.pop("_goto", None)
    if goto and goto in st.session_state["pages"]:
        st.switch_page(st.session_state["pages"][goto])
    if st.sidebar.button("Sign out", icon=":material/logout:", width="stretch"):
        audit.log("logout", user)
        st.session_state.clear()
        st.rerun()
    page.run()
    assistant_panel.render()
