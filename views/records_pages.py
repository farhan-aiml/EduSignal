"""Faculty data entry: attendance sessions, assessments and marks, and refreshing predictions from them.

Uses the existing design components only (header, section, kpis, cards, data editors).
Every write goes through services/, which re-checks that the signed-in teacher manages the class.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import RISK_COLORS
from services import academics, assessments, attendance, snapshots
from services.access import PermissionDenied
from views.common import accent, ctx, empty, header, kpis, require_model, require_role, section, why

STATUS_LABELS = {"present": "Present", "absent": "Absent", "late": "Late", "excused": "Excused"}


def _me() -> dict:
    return st.session_state["user"]


def _pick_class():
    """Class + subject selector limited to what this user may manage."""
    asg = academics.teaching_assignments(_me())
    if asg.empty:
        empty("Is term ke liye aapko koi class ya subject assigned nahi hai. Admin inhe "
              "Users & security, Academic structure mein assign kar sakte hain.", "users")
        return None, None, None
    with st.container(key="card_recpick"):
        c1, c2, c3 = st.columns([1, 1.4, 1.4], vertical_alignment="bottom")
        sec = c1.selectbox("Class", sorted(asg["class_section"].unique()), key="rec_sec")
        subs = asg[asg["class_section"] == sec]
        names = dict(zip(subs["subject_code"], subs["subject_name"]))
        subj = c2.selectbox("Subject", list(names), format_func=lambda k: f"{names[k]} ({k})", key=f"rec_sub_{sec}")
        term = academics.current_term()
        c3.markdown(f'<div class="why" style="padding-bottom:.6rem">Term: <b>{term["name"] if term else "set nahi"}</b></div>',
                    unsafe_allow_html=True)
    return sec, subj, names.get(subj, subj)


def _flash(key):
    msg = st.session_state.pop(key, None)
    if msg and msg[0] == "ok":
        st.success(msg[1])
    elif msg:
        st.error(msg[1])


def _attendance_tab(sec, subj, subj_name):
    _flash("flash_att")
    roster = academics.section_students(sec)
    if roster.empty:
        empty(f"{sec} mein koi active student nahi hai.", "users")
        return
    c1, c2 = st.columns([1, 1])
    d = c1.date_input("Session ki tareekh", value=date.today(), max_value=date.today(), key="att_date")
    period = c2.number_input("Period", 1, 12, 1, key="att_period", help="Ek hi din doosri class ke liye alag period chunein.")
    sheet = roster[["student_id", "name"]].assign(status="present")
    with st.form(f"att_form_{sec}_{subj}", border=False):
        edited = st.data_editor(sheet, hide_index=True, key=f"att_editor_{sec}_{subj}", disabled=["student_id", "name"],
                                column_config={"student_id": "Student", "name": "Name",
                                               "status": st.column_config.SelectboxColumn(
                                                   "Status", options=list(STATUS_LABELS), required=True,
                                                   help="Present aur late attended mein gine jaate hain; excused ko shaamil nahi kiya jaata.")})
        save = st.form_submit_button(f"Attendance Save Karein: {sec}, {subj_name}", type="primary", icon=":material/how_to_reg:")
    if save:
        try:
            sid = attendance.record_session(_me(), sec, subj, d.isoformat(), dict(zip(edited["student_id"], edited["status"])),
                                            int(period))
            n = int(edited["status"].isin(attendance.ATTENDED).sum())
            st.session_state["flash_att"] = ("ok", f"Session #{sid} save ho gaya: {len(edited)} mein se {n} aaye.")
        except (ValueError, PermissionDenied) as e:
            st.session_state["flash_att"] = ("err", str(e))
        st.rerun()
    why("Wahi date aur period dobara save karne par wahi session update hota hai, duplicate nahi banta.")
    hist = attendance.sessions_df(sec, subj)
    if not hist.empty:
        section("Haal ke sessions", "calendar")
        st.dataframe(hist.head(15).rename(columns={"session_date": "Tareekh", "period": "Period", "taken_by": "Kisne liya",
                                                   "present": "Attended", "marked": "Marked"}).drop(columns=["id"]),
                     hide_index=True)


def _marks_tab(sec, subj, subj_name):
    _flash("flash_marks")
    with st.expander("Naya assessment banayein", icon=":material/add_task:", expanded=False):
        with st.form(f"new_assess_{sec}_{subj}", border=False):
            c1, c2 = st.columns([2, 1])
            title = c1.text_input("Title", placeholder="jaise Assignment 3", max_chars=80)
            kind = c2.selectbox("Type", assessments.KINDS, format_func=str.capitalize)
            c3, c4 = st.columns(2)
            mx = c3.number_input("Kul marks", 1.0, 1000.0, 20.0, step=1.0)
            on = c4.date_input("Tareekh", value=date.today())
            if st.form_submit_button("Assessment Banayein", type="primary", icon=":material/add:"):
                try:
                    aid = assessments.create_assessment(_me(), sec, subj, title, kind, mx, on.isoformat())
                    st.session_state["flash_marks"] = ("ok", f"'{title}' ban gaya. Neeche marks bharein.")
                    st.session_state[f"mk_pick_{sec}_{subj}"] = aid
                except (ValueError, PermissionDenied) as e:
                    st.session_state["flash_marks"] = ("err", str(e))
                st.rerun()
    lst = assessments.assessments_df(sec, subj)
    if lst.empty:
        empty(f"{sec} mein {subj_name} ka abhi koi assessment nahi hai. Upar banayein.", "pencil")
        return
    opts = dict(zip(lst["id"], lst.apply(lambda r: f"{r.title} · {r.kind} · {r.max_marks:g} mein se · {r.assessed_on}", axis=1)))
    aid = st.selectbox("Assessment", list(opts), format_func=opts.get, key=f"mk_pick_{sec}_{subj}")
    a = assessments.get_assessment(aid)
    sheet = assessments.marks_sheet(aid)
    with st.form(f"marks_form_{aid}", border=False):
        edited = st.data_editor(sheet, hide_index=True, key=f"marks_editor_{aid}", disabled=["student_id", "name"],
                                column_config={"student_id": "Student", "name": "Name",
                                               "marks": st.column_config.NumberColumn(
                                                   f"Marks ({a['max_marks']:g} mein se)", min_value=0.0,
                                                   max_value=float(a["max_marks"]), step=0.5,
                                                   help="Agar abhi submit nahi hua toh khaali chhodein."),
                                               "absent": st.column_config.CheckboxColumn("Absent")})
        save = st.form_submit_button("Marks Update Karein", type="primary", icon=":material/save:")
    if save:
        try:
            n = assessments.save_marks(_me(), aid, edited.to_dict("records"))
            st.session_state["flash_marks"] = ("ok", f"'{a['title']}' ke {n} marks save ho gaye.")
        except (ValueError, PermissionDenied) as e:
            st.session_state["flash_marks"] = ("err", str(e))
        st.rerun()
    why("Save se pehle har row check hoti hai: agar ek bhi mark galat hai toh kuch bhi save nahi hota.")
    section("Is subject ke saare assessments", "chart")
    st.dataframe(lst.drop(columns=["id", "subject_code"]).rename(columns={
        "title": "Title", "kind": "Type", "max_marks": "Kul marks", "assessed_on": "Tareekh", "entered": "Marks bhare",
        "avg_pct": "Class average %"}), hide_index=True)


def _overview_tab(sec, subj, subj_name, s):
    summ = attendance.section_summary(sec, subj)
    if summ.empty:
        empty("Is class mein koi student nahi hai.", "users")
        return
    target = s["attendance_target"]
    fig = go.Figure(go.Bar(x=summ["student_id"], y=summ["pct"].fillna(0),
                           marker_color=[RISK_COLORS["High"] if (p == p and p < target) else accent() for p in summ["pct"]],
                           hovertext=summ["name"], hovertemplate="%{hovertext}<br>%{y:.1f}%<extra></extra>"))
    fig.add_hline(y=target, line_dash="dot", line_color=RISK_COLORS["High"], annotation_text=f"target {target:g}%")
    fig.update_layout(height=300, title=f"{subj_name} mein attendance", yaxis=dict(range=[0, 105], title="%"), xaxis_title=None)
    st.plotly_chart(fig)
    st.dataframe(summ.rename(columns={"student_id": "Student", "name": "Name", "attended": "Attended",
                                      "held": "Held", "pct": "Attendance %"}), hide_index=True,
                 column_config={"Attendance %": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100)})


def _refresh_tab(sec, s):
    _flash("flash_refresh")
    st.markdown("Is class ke har student ke inputs yahan record ki gayi attendance aur marks se dobara calculate karein, "
                "phir nayi prediction, risk check aur alerts save karein. Aur kuch nahi badalta.")
    st.markdown("- **Attendance**: attend kiye ÷ hue sessions (saare subjects; excused shaamil nahi)\n"
                "- **Assignment score**: assignments aur quizzes ka average %\n"
                "- **Internal marks**: internal tests aur semester exams ka average %\n"
                "- **Study hours** aur **previous marks**: latest record se aage liye jaate hain (yahan measure nahi hote)")
    if st.button(f"Predictions Update Karein: {sec}", type="primary", icon=":material/sync:", key=f"refresh_{sec}"):
        try:
            with st.spinner("Dobara calculate ho raha hai…"):
                res = snapshots.refresh_section(_me(), ctx()["bundle"], sec, s)
            ok = [r for r in res if r["saved"]]
            st.session_state["refresh_result"] = res
            st.session_state["flash_refresh"] = ("ok", f"{len(res)} mein se {len(ok)} students update hue.")
        except (ValueError, PermissionDenied) as e:
            st.session_state["flash_refresh"] = ("err", str(e))
        st.rerun()
    res = st.session_state.get("refresh_result")
    if res:
        df = pd.DataFrame(res)
        cols = [c for c in ["student_id", "saved", "predicted", "risk", "alerts", "reason"] if c in df.columns]
        st.dataframe(df[cols].rename(columns={"student_id": "Student", "saved": "Updated", "predicted": "Predicted",
                                              "risk": "Risk", "alerts": "Alerts", "reason": "Kyun nahi"}),
                     hide_index=True, column_config={"Predicted": st.column_config.NumberColumn(format="%.1f")})


def records():
    require_role("teacher", "admin")
    require_model()
    header("Attendance & marks", "Attendance aur assessment marks record karein. Predictions aur risk isi asli data se update hote hain.")
    sec, subj, subj_name = _pick_class()
    if not sec:
        return
    s = ctx()["settings"]
    summ = attendance.section_summary(sec)
    lst = assessments.assessments_df(sec)
    avg = summ["pct"].mean()
    kpis([("Students", str(len(summ)), sec, None, "users"),
          ("Is subject ke sessions", str(len(attendance.sessions_df(sec, subj))), subj_name, None, "calendar"),
          ("Class attendance", "–" if avg != avg else f"{avg:.1f}%", "saare subjects", None, "calendar"),
          ("Attendance target se neeche", str(int((summ["pct"] < s["attendance_target"]).sum())),
           f"target {s['attendance_target']:g}%", RISK_COLORS["High"], "alert"),
          ("Assessments", str(len(lst)), "saare subjects", None, "pencil")])
    t1, t2, t3, t4 = st.tabs([":material/how_to_reg: Attendance Lein", ":material/edit_note: Assessments & marks",
                              ":material/insights: Class overview", ":material/sync: Predictions update"])
    with t1:
        _attendance_tab(sec, subj, subj_name)
    with t2:
        _marks_tab(sec, subj, subj_name)
    with t3:
        _overview_tab(sec, subj, subj_name, s)
    with t4:
        _refresh_tab(sec, s)
