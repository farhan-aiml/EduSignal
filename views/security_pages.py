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
    kpis([("Accounts", str(len(users)), "saare roles", None, "users"),
          ("Active", str(int(users["is_active"].sum())), "login kar sakte hain", None, "check"),
          ("Deactivated", str(int((users["is_active"] == 0).sum())), "login nahi kar sakte", None, "shield"),
          ("Abhi locked", str(int(users["locked_until"].notna().sum())), "galat attempts ke baad", None, "alert")])
    st.dataframe(users.assign(is_active=users["is_active"].astype(bool)), hide_index=True,
                 column_config={"is_active": st.column_config.CheckboxColumn("Active"),
                                "failed_attempts": "Failed attempts", "locked_until": "Locked until",
                                "last_login_at": "Aakhri login"})
    c1, c2 = st.columns(2, gap="large")
    with c1:
        section("Account status aur password", "shield")
        u = st.selectbox("Account", users["username"].tolist(), key="sec_user")
        row = users[users["username"] == u].iloc[0]
        b1, b2 = st.columns(2)
        if row["is_active"]:
            if b1.button("Deactivate Karein", icon=":material/block:", width="stretch", key="sec_deact"):
                _run(lambda: auth.set_active(_me(), u, False), f"{u} ab login nahi kar sakta.")
        elif b1.button("Activate Karein", icon=":material/check_circle:", width="stretch", key="sec_act"):
            _run(lambda: auth.set_active(_me(), u, True), f"{u} dobara login kar sakta hai.")
        with st.form("sec_reset", border=False):
            pw = st.text_input("Naya password", type="password", help="Kam se kam 8 characters, letters ke saath numbers ya symbols.")
            if st.form_submit_button("Password Reset Karein", icon=":material/key:"):
                _run(lambda: auth.reset_password(_me(), u, pw), f"{u} ka password reset ho gaya.")
    with c2:
        section("Naya account banayein", "users")
        with st.form("sec_create", border=False):
            r1, r2 = st.columns(2)
            uname = r1.text_input("Username")
            role = r2.selectbox("Role", ["student", "teacher", "admin"])
            name = st.text_input("Display name")
            studs = db.students_df()
            linked = set(users["student_id"].dropna())
            free = [s for s in studs["student_id"] if s not in linked]
            sid = st.selectbox("Linked student record (sirf students)", [None] + free,
                               format_func=lambda s: "Koi nahi" if s is None else s)
            subj = st.text_input("Subject (sirf teachers)")
            pw = st.text_input("Shuruaati password", type="password")
            if st.form_submit_button("Account Banayein", type="primary", icon=":material/person_add:"):
                _run(lambda: auth.create_account(_me(), uname, pw, role, name, sid, subj or None), f"{uname} ban gaya.")


def _audit_tab():
    log = audit.recent(500)
    if log.empty:
        empty("Abhi koi audited action nahi hai.", "shield")
        return
    c1, c2 = st.columns(2)
    actions = sorted(log["action"].unique())
    pick = c1.multiselect("Action", actions, key="aud_actions")
    outcome = c2.segmented_control("Outcome", ["Sab", "ok", "failed", "denied"], default="Sab", key="aud_outcome")
    view = log[log["action"].isin(pick)] if pick else log
    if outcome and outcome != "Sab":
        view = view[view["outcome"] == outcome]
    st.dataframe(view.rename(columns={"created_at": "Kab", "actor": "Kaun", "actor_role": "Role", "action": "Action",
                                      "target_type": "Target", "target_id": "Target id", "outcome": "Outcome",
                                      "details_json": "Details"}), hide_index=True)
    why("Audit log mein sirf entries judti hain, hat-ti nahi: logins, data changes, imports, retraining aur mana hue access.")


def _imports_tab():
    b = imports.batches_df()
    if b.empty:
        empty("Abhi tak koi CSV import nahi hua. Import yahan har reject hui row aur uski wajah ke saath dikhenge.", "db")
        return
    st.dataframe(b.rename(columns={"uploaded_at": "Kab", "uploaded_by": "Kisne", "filename": "File", "status": "Status",
                                   "rows_total": "Rows", "rows_imported": "Imported", "rows_rejected": "Rejected"}),
                 hide_index=True)
    bid = st.selectbox("Is batch ki reject hui rows dikhayein", b["id"].tolist(), key="imp_batch")
    errs = imports.batch_errors(bid)
    if errs.empty:
        why("Is batch mein koi row reject nahi hui.")
    else:
        st.dataframe(errs.rename(columns={"row_number": "CSV line", "reason": "Wajah", "raw_json": "Values"}), hide_index=True)


def _structure_tab():
    term = academics.current_term()
    st.markdown(f"**Current term:** {term['name'] if term else 'set nahi'}"
                + (f" ({term['start_date']} se {term['end_date']})" if term else ""))
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
            if st.form_submit_button("Assign Karein", type="primary", icon=":material/add_link:"):
                _run(lambda: academics.assign_teacher_subject(_me(), t, sj, cl), f"{t} ko {cl} mein {sj} assign ho gaya.")


def _channels_tab():
    from utils import notifications
    status = notifications.channel_status()
    c1, c2 = st.columns(2, gap="large")
    for col, ch, label in [(c1, "email", "Email (SMTP)"), (c2, "sms", "SMS")]:
        with col:
            with st.container(key=f"card_ch_{ch}"):
                stt = status[ch]
                st.markdown(f"**{label}**")
                if stt["configured"]:
                    st.success("Configured hai.")
                else:
                    st.warning("Configure nahi hai. Koi email/SMS nahi bheja jaayega. Missing environment variables: "
                               + ", ".join(stt["missing"]))
                with st.form(f"test_{ch}", border=False):
                    to = st.text_input("Test bhejne ka pata" if ch == "email" else "Test phone number",
                                       placeholder="naam@college.edu" if ch == "email" else "+919876543210")
                    if st.form_submit_button("Test Bhejein", icon=":material/send:", disabled=not stt["configured"]):
                        ok, err = notifications.send_test(_me(), ch, to)
                        if ok:
                            st.success("Provider ne message accept kar liya.")
                        else:
                            st.error(f"Nahi bheja ja saka: {err}")
    why("Credentials sirf environment variables mein rakhein (.env.example dekhein). Sirf high severity alerts "
        "bahar bheje jaate hain (NOTIFY_EXTERNAL_MIN_SEVERITY se badal sakte hain).")
    section("Delivery log", "bell")
    log = notifications.deliveries_df()
    if log.empty:
        empty("Abhi tak koi email/SMS attempt nahi hua.", "bell")
    else:
        st.dataframe(log.rename(columns={"attempted_at": "Kab", "channel": "Channel", "recipient": "Kisko", "status": "Status",
                                         "error": "Error", "type": "Alert", "severity": "Severity", "message": "Message"}),
                     hide_index=True)


def users_security():
    require_role("admin")
    header("Users & security", "Accounts, access, audit trail, import history aur academic structure.")
    _flash()
    t1, t2, t3, t4, t5 = st.tabs([":material/manage_accounts: Users", ":material/policy: Audit log",
                                  ":material/upload_file: Import history", ":material/account_tree: Academic structure",
                                  ":material/mail: Email / SMS"])
    with t1:
        _users_tab()
    with t2:
        _audit_tab()
    with t3:
        _imports_tab()
    with t4:
        _structure_tab()
    with t5:
        _channels_tab()
