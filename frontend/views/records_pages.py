"""Faculty data entry: attendance sessions, assessments and marks, and refreshing predictions from them.

Uses the existing design components only (header, section, kpis, cards, data editors).
Every write goes through services/, which re-checks that the signed-in teacher manages the class.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backend.config import RISK_COLORS
from backend.services import academics, assessments, attendance, snapshots
from backend.services.access import PermissionDenied
from frontend.views.common import accent, ctx, empty, header, kpis, require_model, require_role, section, why

STATUS_LABELS = {"present": "Present", "absent": "Absent", "late": "Late", "excused": "Excused"}


def _me() -> dict:
    return st.session_state["user"]


def _pick_class():
    """Class + subject selector limited to what this user may manage."""
    asg = academics.teaching_assignments(_me())
    if asg.empty:
        empty("You have no classes or subjects assigned for the current term. An admin can assign them on the "
              "Admin dashboard (Faculty directory, Edit).", "users")
        return None, None, None
    with st.container(key="card_recpick"):
        c1, c2, c3 = st.columns([1, 1.4, 1.4], vertical_alignment="bottom")
        sec = c1.selectbox("Class", sorted(asg["class_section"].unique()), key="rec_sec")
        subs = asg[asg["class_section"] == sec]
        names = dict(zip(subs["subject_code"], subs["subject_name"]))
        subj = c2.selectbox("Subject", list(names), format_func=lambda k: f"{names[k]} ({k})", key=f"rec_sub_{sec}")
        term = academics.current_term()
        c3.markdown(f'<div class="why" style="padding-bottom:.6rem">Term: <b>{term["name"] if term else "not set"}</b></div>',
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
        empty(f"No active students in {sec}.", "users")
        return
    c1, c2 = st.columns([1, 1])
    d = c1.date_input("Session date", value=date.today(), max_value=date.today(), key="att_date")
    period = c2.number_input("Period", 1, 12, 1, key="att_period", help="Use a different period for a second class on the same day.")
    sheet = roster[["student_id", "name"]].assign(status="present")
    with st.form(f"att_form_{sec}_{subj}", border=False):
        edited = st.data_editor(sheet, hide_index=True, key=f"att_editor_{sec}_{subj}", disabled=["student_id", "name"],
                                column_config={"student_id": "Student", "name": "Name",
                                               "status": st.column_config.SelectboxColumn(
                                                   "Status", options=list(STATUS_LABELS), required=True,
                                                   help="Present and late count as attended; excused is left out.")})
        save = st.form_submit_button(f"Save attendance for {sec}, {subj_name}", type="primary", icon=":material/how_to_reg:")
    if save:
        try:
            sid = attendance.record_session(_me(), sec, subj, d.isoformat(), dict(zip(edited["student_id"], edited["status"])),
                                            int(period))
            n = int(edited["status"].isin(attendance.ATTENDED).sum())
            st.session_state["flash_att"] = ("ok", f"Saved session #{sid}: {n} of {len(edited)} attended.")
        except (ValueError, PermissionDenied) as e:
            st.session_state["flash_att"] = ("err", str(e))
        st.rerun()
    why("Saving the same date and period again updates that session instead of creating a duplicate.")
    hist = attendance.sessions_df(sec, subj)
    if not hist.empty:
        section("Recent sessions", "calendar")
        st.dataframe(hist.head(15).rename(columns={"session_date": "Date", "period": "Period", "taken_by": "Taken by",
                                                   "present": "Attended", "marked": "Marked"}).drop(columns=["id"]),
                     hide_index=True)


def _marks_tab(sec, subj, subj_name):
    _flash("flash_marks")
    with st.expander("Create an assessment", icon=":material/add_task:", expanded=False):
        with st.form(f"new_assess_{sec}_{subj}", border=False):
            c1, c2 = st.columns([2, 1])
            title = c1.text_input("Title", placeholder="e.g. Assignment 3", max_chars=80)
            kind = c2.selectbox("Type", assessments.KINDS, format_func=str.capitalize)
            c3, c4 = st.columns(2)
            mx = c3.number_input("Maximum marks", 1.0, 1000.0, 20.0, step=1.0)
            on = c4.date_input("Date", value=date.today())
            if st.form_submit_button("Create assessment", type="primary", icon=":material/add:"):
                try:
                    aid = assessments.create_assessment(_me(), sec, subj, title, kind, mx, on.isoformat())
                    st.session_state["flash_marks"] = ("ok", f"Created '{title}'. Enter marks below.")
                    st.session_state[f"mk_pick_{sec}_{subj}"] = aid
                except (ValueError, PermissionDenied) as e:
                    st.session_state["flash_marks"] = ("err", str(e))
                st.rerun()
    lst = assessments.assessments_df(sec, subj)
    if lst.empty:
        empty(f"No assessments yet for {subj_name} in {sec}. Create one above.", "pencil")
        return
    opts = dict(zip(lst["id"], lst.apply(lambda r: f"{r.title} · {r.kind} · out of {r.max_marks:g} · {r.assessed_on}", axis=1)))
    aid = st.selectbox("Assessment", list(opts), format_func=opts.get, key=f"mk_pick_{sec}_{subj}")
    a = assessments.get_assessment(aid)
    sheet = assessments.marks_sheet(aid)
    with st.form(f"marks_form_{aid}", border=False):
        edited = st.data_editor(sheet, hide_index=True, key=f"marks_editor_{aid}", disabled=["student_id", "name"],
                                column_config={"student_id": "Student", "name": "Name",
                                               "marks": st.column_config.NumberColumn(
                                                   f"Marks (out of {a['max_marks']:g})", min_value=0.0,
                                                   max_value=float(a["max_marks"]), step=0.5,
                                                   help="Leave blank if not submitted yet."),
                                               "absent": st.column_config.CheckboxColumn("Absent")})
        save = st.form_submit_button("Save marks", type="primary", icon=":material/save:")
    if save:
        try:
            n = assessments.save_marks(_me(), aid, edited.to_dict("records"))
            st.session_state["flash_marks"] = ("ok", f"Saved {n} mark(s) for '{a['title']}'.")
        except (ValueError, PermissionDenied) as e:
            st.session_state["flash_marks"] = ("err", str(e))
        st.rerun()
    why("All rows are checked before anything is saved: if one mark is invalid, nothing is written.")
    section("All assessments in this subject", "chart")
    st.dataframe(lst.drop(columns=["id", "subject_code"]).rename(columns={
        "title": "Title", "kind": "Type", "max_marks": "Out of", "assessed_on": "Date", "entered": "Marks entered",
        "avg_pct": "Class average %"}), hide_index=True)


def _overview_tab(sec, subj, subj_name, s):
    summ = attendance.section_summary(sec, subj)
    if summ.empty:
        empty("No students in this class.", "users")
        return
    target = s["attendance_target"]
    fig = go.Figure(go.Bar(x=summ["student_id"], y=summ["pct"].fillna(0),
                           marker_color=[RISK_COLORS["High"] if (p == p and p < target) else accent() for p in summ["pct"]],
                           hovertext=summ["name"], hovertemplate="%{hovertext}<br>%{y:.1f}%<extra></extra>"))
    fig.add_hline(y=target, line_dash="dot", line_color=RISK_COLORS["High"], annotation_text=f"target {target:g}%")
    fig.update_layout(height=300, title=f"Attendance in {subj_name}", yaxis=dict(range=[0, 105], title="%"), xaxis_title=None)
    st.plotly_chart(fig)
    st.dataframe(summ.rename(columns={"student_id": "Student", "name": "Name", "attended": "Attended",
                                      "held": "Held", "pct": "Attendance %"}), hide_index=True,
                 column_config={"Attendance %": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100)})


def _refresh_tab(sec, s):
    _flash("flash_refresh")
    st.markdown("Recalculate every student's inputs in this class from the attendance and marks recorded here, "
                "then save a new prediction, risk check and alerts. Nothing else is changed.")
    st.markdown("- **Attendance**: attended ÷ held sessions (all subjects; excused excluded)\n"
                "- **Assignment score**: average % of assignments and quizzes\n"
                "- **Internal marks**: average % of internal tests and semester exams\n"
                "- **Study hours** and **previous marks**: carried forward from the latest record (not measured here)")
    if st.button(f"Update predictions for {sec}", type="primary", icon=":material/sync:", key=f"refresh_{sec}"):
        try:
            with st.spinner("Recomputing…"):
                res = snapshots.refresh_section(_me(), ctx()["bundle"], sec, s)
            ok = [r for r in res if r["saved"]]
            st.session_state["refresh_result"] = res
            st.session_state["flash_refresh"] = ("ok", f"Updated {len(ok)} of {len(res)} students.")
        except (ValueError, PermissionDenied) as e:
            st.session_state["flash_refresh"] = ("err", str(e))
        st.rerun()
    res = st.session_state.get("refresh_result")
    if res:
        df = pd.DataFrame(res)
        cols = [c for c in ["student_id", "saved", "predicted", "risk", "alerts", "reason"] if c in df.columns]
        st.dataframe(df[cols].rename(columns={"student_id": "Student", "saved": "Updated", "predicted": "Predicted",
                                              "risk": "Risk", "alerts": "Alerts", "reason": "Why not"}),
                     hide_index=True, column_config={"Predicted": st.column_config.NumberColumn(format="%.1f")})


def records():
    require_role("teacher", "admin")
    require_model()
    header("Attendance & marks", "Record attendance and assessment marks. Predictions and risk update from this real data.")
    sec, subj, subj_name = _pick_class()
    if not sec:
        return
    s = ctx()["settings"]
    summ = attendance.section_summary(sec)
    lst = assessments.assessments_df(sec)
    avg = summ["pct"].mean()
    kpis([("Students", str(len(summ)), sec, None, "users"),
          ("Sessions in this subject", str(len(attendance.sessions_df(sec, subj))), subj_name, None, "calendar"),
          ("Class attendance", "–" if avg != avg else f"{avg:.1f}%", "all subjects", None, "calendar"),
          ("Below attendance target", str(int((summ["pct"] < s["attendance_target"]).sum())),
           f"target {s['attendance_target']:g}%", RISK_COLORS["High"], "alert"),
          ("Assessments", str(len(lst)), "all subjects", None, "pencil")])
    t1, t2, t3, t4 = st.tabs([":material/how_to_reg: Take attendance", ":material/edit_note: Assessments & marks",
                              ":material/insights: Class overview", ":material/sync: Update predictions"])
    with t1:
        _attendance_tab(sec, subj, subj_name)
    with t2:
        _marks_tab(sec, subj, subj_name)
    with t3:
        _overview_tab(sec, subj, subj_name, s)
    with t4:
        _refresh_tab(sec, s)
