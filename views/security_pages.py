"""Admin: users and access, audit log, import history, academic structure."""
from __future__ import annotations


import streamlit as st

from database import database as db
from services import academics, audit, imports
from services.access import PermissionDenied
from utils import auth
from views.common import empty, header, kpis, require_role, section, why


def _me() -> dict:
    return st.session_state["user"]


def _flash():
    msg = st.session_state.pop("flash_sec", None)
    if msg and msg[0] == "ok":
        st.success(msg[1])
    elif msg:
        st.error(msg[1])


def _run(fn, ok_text):
    try:
        fn()
        st.session_state["flash_sec"] = ("ok", ok_text)
    except (ValueError, PermissionDenied) as e:
        st.session_state["flash_sec"] = ("err", str(e))
    st.rerun()


def _users_tab():
    users = db.users_df()
    kpis([("Accounts", str(len(users)), "all roles", None, "users"),
          ("Active", str(int(users["is_active"].sum())), "can sign in", None, "check"),
          ("Deactivated", str(int((users["is_active"] == 0).sum())), "cannot sign in", None, "shield"),
          ("Locked now", str(int(users["locked_until"].notna().sum())), "after failed attempts", None, "alert")])
    st.dataframe(users.assign(is_active=users["is_active"].astype(bool)), hide_index=True,
                 column_config={"is_active": st.column_config.CheckboxColumn("Active"),
                                "failed_attempts": "Failed attempts", "locked_until": "Locked until",
                                "last_login_at": "Last sign-in"})
    c1, c2 = st.columns(2, gap="large")
    with c1:
        section("Account status and password", "shield")
        u = st.selectbox("Account", users["username"].tolist(), key="sec_user")
        row = users[users["username"] == u].iloc[0]
        b1, b2 = st.columns(2)
        if row["is_active"]:
            if b1.button("Deactivate", icon=":material/block:", width="stretch", key="sec_deact"):
                _run(lambda: auth.set_active(_me(), u, False), f"{u} can no longer sign in.")
        elif b1.button("Activate", icon=":material/check_circle:", width="stretch", key="sec_act"):
            _run(lambda: auth.set_active(_me(), u, True), f"{u} can sign in again.")
        with st.form("sec_reset", border=False):
            pw = st.text_input("New password", type="password", help="At least 8 characters, letters with numbers or symbols.")
            if st.form_submit_button("Reset password", icon=":material/key:"):
                _run(lambda: auth.reset_password(_me(), u, pw), f"Password reset for {u}.")
    with c2:
        section("Create an account", "users")
        with st.form("sec_create", border=False):
            r1, r2 = st.columns(2)
            uname = r1.text_input("Username")
            role = r2.selectbox("Role", ["student", "teacher", "admin"])
            name = st.text_input("Display name")
            studs = db.students_df()
            linked = set(users["student_id"].dropna())
            free = [s for s in studs["student_id"] if s not in linked]
            sid = st.selectbox("Linked student record (students only)", [None] + free,
                               format_func=lambda s: "None" if s is None else s)
            subj = st.text_input("Subject (teachers only)")
            pw = st.text_input("Initial password", type="password")
            if st.form_submit_button("Create account", type="primary", icon=":material/person_add:"):
                _run(lambda: auth.create_account(_me(), uname, pw, role, name, sid, subj or None), f"Created {uname}.")


def _audit_tab():
    log = audit.recent(500)
    if log.empty:
        empty("No audited actions yet.", "shield")
        return
    c1, c2 = st.columns(2)
    actions = sorted(log["action"].unique())
    pick = c1.multiselect("Action", actions, key="aud_actions")
    outcome = c2.segmented_control("Outcome", ["All", "ok", "failed", "denied"], default="All", key="aud_outcome")
    view = log[log["action"].isin(pick)] if pick else log
    if outcome and outcome != "All":
        view = view[view["outcome"] == outcome]
    st.dataframe(view.rename(columns={"created_at": "When", "actor": "Who", "actor_role": "Role", "action": "Action",
                                      "target_type": "Target", "target_id": "Target id", "outcome": "Outcome",
                                      "details_json": "Details"}), hide_index=True)
    why("The audit log is append-only: sign-ins, data changes, imports, retraining and permission denials.")


def _imports_tab():
    b = imports.batches_df()
    if b.empty:
        empty("No CSV imports yet. They appear here with every rejected row and its reason.", "db")
        return
    st.dataframe(b.rename(columns={"uploaded_at": "When", "uploaded_by": "By", "filename": "File", "status": "Status",
                                   "rows_total": "Rows", "rows_imported": "Imported", "rows_rejected": "Rejected"}),
                 hide_index=True)
    bid = st.selectbox("Show rejected rows for batch", b["id"].tolist(), key="imp_batch")
    errs = imports.batch_errors(bid)
    if errs.empty:
        why("No rejected rows in this batch.")
    else:
        st.dataframe(errs.rename(columns={"row_number": "CSV line", "reason": "Reason", "raw_json": "Values"}), hide_index=True)


def _structure_tab():
    term = academics.current_term()
    st.markdown(f"**Current term:** {term['name'] if term else 'not set'}"
                + (f" ({term['start_date']} to {term['end_date']})" if term else ""))
    c1, c2 = st.columns(2, gap="large")
    with c1:
        section("Departments", "layers")
        st.dataframe(academics.departments_df(), hide_index=True)
        section("Subjects", "book")
        st.dataframe(academics.subjects_df(), hide_index=True)
    with c2:
        section("Teacher-subject assignments", "users")
        ts = db.query_df("SELECT ts.username AS teacher, s.name AS subject, ts.class_section AS class FROM teacher_subjects ts "
                         "JOIN subjects s ON s.code = ts.subject_code ORDER BY 1, 3, 2")
        st.dataframe(ts, hide_index=True)
        teachers = db.teachers_df()
        subs = academics.subjects_df()
        with st.form("assign_ts", border=False):
            t = st.selectbox("Teacher", teachers["username"].tolist(),
                             format_func=dict(zip(teachers["username"], teachers["display_name"])).get)
            sj = st.selectbox("Subject", subs["code"].tolist(), format_func=dict(zip(subs["code"], subs["name"])).get)
            cl = st.selectbox("Class", db.class_sections())
            if st.form_submit_button("Assign", type="primary", icon=":material/add_link:"):
                _run(lambda: academics.assign_teacher_subject(_me(), t, sj, cl), f"Assigned {t} to {sj} in {cl}.")


def users_security():
    require_role("admin")
    header("Users & security", "Accounts, access, the audit trail, import history and the academic structure.")
    _flash()
    t1, t2, t3, t4 = st.tabs([":material/manage_accounts: Users", ":material/policy: Audit log",
                              ":material/upload_file: Import history", ":material/account_tree: Academic structure"])
    with t1:
        _users_tab()
    with t2:
        _audit_tab()
    with t3:
        _imports_tab()
    with t4:
        _structure_tab()
