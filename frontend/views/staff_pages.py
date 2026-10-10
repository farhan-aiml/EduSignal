"""Faculty pages: teacher dashboard with interventions, and dataset analytics."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from backend.config import DATASET_PATH, FEATURE_NAMES, FEATURES, RISK_COLORS, TARGET
from backend.database import database as db
from backend.services import access, audit
from backend.utils.validation import data_quality_report, read_csv_safely
from frontend.views.common import (require_role, INK, accent, dialog_head, scoped_roster, scope_banner, analysis, ctx, demo_badge, empty,
                          header, kpis, require_model, risk_chip, role, roster, section, teacher_picker, why)

ACTION_LIBRARY = {
    "Predicted score": "Review overall progress with the student and agree two short-term goals",
    "Attendance": "Check the reason for absences (health, travel, work, motivation) and agree an attendance plan",
    "Assignment score": "Review assignment completion and set deadlines for pending work",
    "Internal marks": "Arrange concept revision or peer tutoring for weak topics",
    "Study hours/day": "Help the student set a fixed daily study timetable",
    "Previous marks": "Offer bridging material for prerequisite topics",
    "Performance trend": "Discuss what changed recently; check for non-academic issues",
    "Repeated poor results": "Escalate to a formal academic support plan with the mentor",
}


def teacher_dashboard():
    require_role("teacher", "admin")
    bundle = require_model()
    if role() == "admin" and not st.session_state.get("view_teacher"):
        header("Teacher dashboards", "Choose a teacher to see their classes, watchlist and interventions exactly as they do.",
               eyebrow="Admin console · Faculty")
        teacher_picker(bundle, key="tdb")
        return
    header("Teacher dashboard", "Who needs attention, why, and what to do about it.")
    scope_banner()
    df, _ = scoped_roster(bundle)
    if df.empty:
        empty("No students in these classes yet. An admin can assign classes on the Admin dashboard or import a CSV.")
        return
    s = ctx()["settings"]
    n_demo = int(df["Demo"].sum())
    if n_demo:
        st.markdown(demo_badge(f"{n_demo} of {len(df)} students are synthetic demo data"), unsafe_allow_html=True)

    counts = df["Risk"].value_counts()
    kpis([("Students", str(len(df)), "with at least one record", None),
          ("Average predicted score", f"{df['Predicted score'].mean():.1f}", "latest records", None),
          ("High risk", str(counts.get("High", 0)), "students", RISK_COLORS["High"]),
          ("Moderate risk", str(counts.get("Moderate", 0)), "students", RISK_COLORS["Moderate"]),
          ("Low risk", str(counts.get("Low", 0)), "students", RISK_COLORS["Low"]),
          ("Below attendance target", str(int((df["Attendance"] < s["attendance_target"]).sum())),
           f"target {s['attendance_target']:g}%", None)])

    with st.container(key="card_filters"):
        f1, f2, f3, f4 = st.columns([1.2, 1, 1, 1])
        risks = f1.multiselect("Risk", ["High", "Moderate", "Low"], default=["High", "Moderate", "Low"])
        att = f2.slider("Attendance (%)", 0, 100, (0, 100))
        sc = f3.slider("Predicted score", 0, 100, (0, 100))
        depts = sorted(df["Department"].fillna("Unassigned").unique())
        dep = f4.multiselect("Department", depts, default=depts)
        q = st.text_input("Search by ID or name", placeholder="e.g. DEMO-004")
    view = df[df["Risk"].isin(risks) & df["Attendance"].between(*att) & df["Predicted score"].between(*sc)
              & df["Department"].fillna("Unassigned").isin(dep)]
    if q:
        view = view[view["Student"].str.contains(q, case=False) | view["Name"].fillna("").str.contains(q, case=False)]
    view = view.sort_values(["Risk score", "Predicted score"], ascending=[False, True])

    section(f"Students ({len(view)})", "users", "Sorted by risk, highest first")
    if view.empty:
        empty("No students match these filters. Widen the ranges or clear the search.")
    else:
        table = view.assign(Risk=view["Risk"].map(risk_chip),
                            Trend=view["Trend"].map(lambda t: "No history" if pd.isna(t) else f"{t:+.1f}"),
                            Action=np.where(view["Intervention"], "Intervene", "Monitor"))
        why("Click a row to open a quick view of that student.")
        event = st.dataframe(
            table[["Student", "Name", "Class", "Predicted score", "Risk", "Risk score", "Attendance",
                   "Main concern", "Trend", "Action"]], hide_index=True, key="roster_tbl",
            on_select="rerun", selection_mode="single-row",
            column_config={"Predicted score": st.column_config.ProgressColumn(format="%.1f", min_value=0, max_value=100),
                           "Attendance": st.column_config.NumberColumn(format="%.0f%%"),
                           "Trend": st.column_config.TextColumn(help="Change in predicted score vs previous record")})
        rows = event.selection.rows if event is not None else []
        if rows:
            sid = table.iloc[rows[0]]["Student"]
            if st.session_state.get("qv_last") != sid:
                st.session_state["qv_last"] = sid
                _quick_view(table.iloc[rows[0]])
        else:
            st.session_state["qv_last"] = None

    c1, c2 = st.columns(2)
    with c1:
        order = ["High", "Moderate", "Low"]
        fig = go.Figure(go.Bar(x=order, y=[counts.get(k, 0) for k in order],
                               marker_color=[RISK_COLORS[k] for k in order]))
        fig.update_layout(height=280, title="Risk distribution")
        st.plotly_chart(fig)
    with c2:
        fig = px.histogram(df, x="Attendance", nbins=15, title="Attendance distribution")
        fig.update_traces(marker_color=accent())
        fig.add_vline(x=s["attendance_target"], line_dash="dot", line_color=RISK_COLORS["High"],
                      annotation_text="target")
        fig.update_layout(height=280, yaxis_title="Students")
        st.plotly_chart(fig)
    multi = df[df["Records"] > 1]
    if not multi.empty:
        _, rec = scoped_roster(bundle)
        trend = rec.groupby("record_date", as_index=False)["Predicted"].mean()
        fig = px.line(trend, x="record_date", y="Predicted", markers=True, title="Average predicted score over time")
        fig.update_traces(line_color=accent())
        fig.update_layout(height=280, xaxis_title=None)
        st.plotly_chart(fig)

    _interventions(df)


@st.dialog("Student quick view", width="large")
def _quick_view(row):
    r = row["_risk"]
    dialog_head("users", f"{row['Name'] or row['Student']}", f"{row['Student']}, {row['Class'] or 'no class'}")
    kpis([("Predicted score", f"{row['Predicted score']:.1f}", "latest record", None),
          ("Risk level", r["level"], f"Risk score {r['score']:.0f}/100", RISK_COLORS[r["level"]]),
          ("Attendance", f"{row['Attendance']:g}%", "latest record", None),
          ("Trend", row["Trend"], "vs previous record", None)])
    if r["factors"]:
        st.markdown("**Why flagged**")
        for f in r["factors"][:4]:
            st.markdown(f"- {f['reason']} (+{f['points']:g})")
    else:
        st.markdown("No risk rules triggered.")
    c1, c2 = st.columns(2)
    if c1.button("Open full profile", type="primary", width="stretch", icon=":material/person:"):
        st.session_state["pending_student"] = row["Student"]
        pages = st.session_state.get("pages", {})
        if "profile" in pages:
            st.switch_page(pages["profile"])
        st.rerun()
    if c2.button("Close", width="stretch"):
        st.rerun()


@st.dialog("Plan an intervention", width="large")
def _intervention_dialog(sid, name, r):
    issues = [f["factor"] for f in r["factors"][:3]]
    actions = [ACTION_LIBRARY[i] for i in issues if i in ACTION_LIBRARY]
    actions += ["Schedule a mentoring discussion within a week",
                "Monitor performance for the next 2 weeks and re-assess"]
    dialog_head("flag", f"{name or sid} ({sid})", f"{r['level']} risk, risk score {r['score']:.0f} of 100")
    c1, c2 = st.columns(2)
    c1.markdown("**Main issues**\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(issues, 1)))
    c2.markdown("**Suggested actions**\n" + "\n".join(f"- {a}" for a in actions))
    fu = st.date_input("Follow-up date", value=date.today() + timedelta(days=14), key="iv_date")
    notes = st.text_area("Notes", key="iv_notes", max_chars=1000, placeholder="What was agreed with the student?")
    b1, b2 = st.columns(2)
    if b1.button("Cancel", width="stretch"):
        st.rerun()
    if b2.button("Create intervention plan", type="primary", width="stretch", icon=":material/flag:"):
        me = st.session_state["user"]
        if not access.can_view_student(me, sid):
            st.error("You don't have access to this student.")
            return
        iid = db.create_intervention(sid, me["username"], r["level"], issues, actions, fu.isoformat(), notes)
        audit.log("intervention.create", me, "intervention", iid, {"student": sid, "risk": r["level"]})
        db.add_notification("intervention", "high", "Your teacher has scheduled a support meeting. "
                            "Check your study plan before it.", sid, recipient_student_id=sid)
        st.session_state["flash_iv"] = f"Intervention plan created for {sid}."
        st.rerun()


def _interventions(df):
    section("Early intervention", "flag")
    if msg := st.session_state.pop("flash_iv", None):
        st.success(msg)
    need = df[df["Intervention"]].sort_values("Risk score", ascending=False)
    if need.empty:
        empty("No students currently need an intervention.")
    else:
        top = need.head(6)
        cols = st.columns(3)
        for i, (_, row) in enumerate(top.iterrows()):
            r = row["_risk"]
            with cols[i % 3]:
                with st.container(key=f"reg_iv{i}"):
                    st.markdown(f"**{row['Name'] or row['Student']}**  \n{row['Student']}, {r['level']} risk "
                                f"({r['score']:.0f})  \nMain concern: {row['Main concern']}")
                    if st.button("Plan intervention", key=f"ivbtn{i}", icon=":material/flag:", width="stretch"):
                        _intervention_dialog(row["Student"], row["Name"], r)
        if len(need) > 6:
            why(f"Showing the 6 highest-risk students. {len(need) - 6} more need an intervention; "
                "filter the table to High risk to see them.")

    ints = db.interventions_df()
    ints = ints[ints["student_id"].isin(df["Student"])] if not ints.empty else ints
    if not ints.empty:
        st.markdown("**Intervention log**")
        edited = st.data_editor(
            ints[["id", "student_id", "created_at", "risk_level", "follow_up_date", "status", "notes"]],
            hide_index=True, disabled=["id", "student_id", "created_at", "risk_level", "follow_up_date"],
            column_config={"status": st.column_config.SelectboxColumn(options=["Open", "In progress", "Closed"])},
            key="iv_editor")
        if st.button("Save intervention updates"):
            before = ints.set_index("id")
            for _, row in edited.iterrows():
                old = before.loc[int(row["id"])]
                if old["status"] != row["status"] or (old["notes"] or "") != (row["notes"] or ""):
                    db.update_intervention(int(row["id"]), row["status"], row["notes"] or "")
                    audit.log("intervention.update", st.session_state["user"], "intervention", int(row["id"]),
                              {"status": row["status"]})
            st.success("Intervention log updated.")


def analytics():
    require_role("teacher", "admin")
    header("Analytics & data quality", "What the training dataset looks like, and how far it can be trusted.")
    df, err = read_csv_safely(DATASET_PATH)
    if err:
        st.error(f"Could not read the training dataset: {err}")
        return
    rep = data_quality_report(df)
    kpis([("Rows", str(rep["rows"]), "training records", None),
          ("Columns", str(rep["columns"]), "5 inputs + target", None),
          ("Missing values", str(sum(rep["missing"].values())), "across all columns", None),
          ("Duplicate rows", str(rep["duplicates"]), "", None),
          ("Lowest correlation", f"{rep['min_pairwise_corr']:.2f}", "between any two columns", None)])
    if rep["rows"] < 30:
        st.warning(f"The current dataset has {rep['rows']} rows. It is suitable for demonstrating the prototype "
                   "but is insufficient for strong real-world generalisation. Import more records with final "
                   "scores and retrain to improve it.")
    if rep["min_pairwise_corr"] > 0.9:
        st.warning("Every column moves together almost perfectly, which looks more like hand-made sample data "
                   "than real student records. The model cannot tell factors apart reliably.")

    section("Summary statistics", "db")
    d = rep["describe"].round(2)
    d["IQR outliers"] = pd.Series(rep["outliers"])
    st.dataframe(d)

    c1, c2 = st.columns(2)
    with c1:
        col = st.selectbox("Distribution of", list(df.select_dtypes("number").columns), key="an_dist")
        fig = px.histogram(df, x=col, nbins=10, title=f"{col} distribution")
        fig.update_traces(marker_color=accent())
        fig.update_layout(height=300)
        st.plotly_chart(fig)
    with c2:
        fig = px.imshow(rep["corr"].round(2), text_auto=True, color_continuous_scale=["#FFFFFF", accent()],
                        zmin=0, zmax=1, title="Correlation matrix")
        fig.update_layout(height=300)
        st.plotly_chart(fig)
    feat = st.selectbox("Relationship with final score", FEATURE_NAMES, format_func=lambda k: FEATURES[k]["label"])
    fig = px.scatter(df, x=feat, y=TARGET, title=f"{FEATURES[feat]['label']} vs final score")
    fig.update_traces(marker=dict(size=11, color=INK))
    fig.update_layout(height=320)
    st.plotly_chart(fig)

    section("Current student breakdown", "chart")
    a = analysis()
    v = a["values"]
    sd = pd.DataFrame({"Category": ["Attendance", "Assignment", "Internal", "Previous marks"],
                       "Score": [v["Attendance"], v["Assignment_Score"], v["Internal_Marks"], v["Previous_Marks"]]})
    fig = px.bar(sd, x="Category", y="Score", title="Performance breakdown")
    fig.update_traces(marker_color=accent())
    fig.update_layout(height=280, yaxis=dict(range=[0, 100]))
    st.plotly_chart(fig)
    why("This chart is kept from the original dashboard's Analytics tab.")
