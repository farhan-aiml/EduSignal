"""Faculty pages: teacher dashboard with interventions, and dataset analytics."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import DATASET_PATH, FEATURE_NAMES, FEATURES, RISK_COLORS, TARGET
from database import database as db
from services import access, audit
from utils.validation import data_quality_report, read_csv_safely
from views.common import (require_role, INK, accent, dialog_head, scoped_roster, scope_banner, analysis, ctx, demo_badge, empty,
                          header, kpis, require_model, risk_chip, role, roster, section, teacher_picker, why)

ACTION_LIBRARY = {
    "Predicted score": "Student ke saath overall progress dekhein aur do short-term goals tay karein",
    "Attendance": "Absence ki wajah samjhein (health, travel, kaam, motivation) aur attendance plan banayein",
    "Assignment score": "Assignments ki completion dekhein aur pending kaam ki deadline tay karein",
    "Internal marks": "Kamzor topics ke liye concept revision ya peer tutoring rakhein",
    "Study hours/day": "Student ka fixed daily study timetable banaane mein madad karein",
    "Previous marks": "Pichhle topics ke liye bridging material dein",
    "Performance trend": "Haal mein kya badla, us par baat karein; non-academic pareshaani bhi check karein",
    "Repeated poor results": "Mentor ke saath formal academic support plan shuru karein",
}


def teacher_dashboard():
    require_role("teacher", "admin")
    bundle = require_model()
    if role() == "admin" and not st.session_state.get("view_teacher"):
        header("Teacher dashboards", "Teacher chunein aur unki classes, watchlist aur interventions bilkul unki nazar se dekhein.",
               eyebrow="Admin console · Faculty")
        teacher_picker(bundle, key="tdb")
        return
    header("Teacher dashboard", "Kisko dhyaan chahiye, kyun, aur kya karna hai.")
    scope_banner()
    df, _ = scoped_roster(bundle)
    if df.empty:
        empty("In classes mein abhi koi student nahi hai. Admin, Admin dashboard par classes assign kar sakte hain ya CSV import kar sakte hain.")
        return
    s = ctx()["settings"]
    n_demo = int(df["Demo"].sum())
    if n_demo:
        st.markdown(demo_badge(f"{n_demo} of {len(df)} students are synthetic demo data"), unsafe_allow_html=True)

    counts = df["Risk"].value_counts()
    kpis([("Students", str(len(df)), "kam se kam ek record ke saath", None),
          ("Average predicted score", f"{df['Predicted score'].mean():.1f}", "latest records se", None),
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
        q = st.text_input("ID ya naam se search karein", placeholder="jaise DEMO-004")
    view = df[df["Risk"].isin(risks) & df["Attendance"].between(*att) & df["Predicted score"].between(*sc)
              & df["Department"].fillna("Unassigned").isin(dep)]
    if q:
        view = view[view["Student"].str.contains(q, case=False) | view["Name"].fillna("").str.contains(q, case=False)]
    view = view.sort_values(["Risk score", "Predicted score"], ascending=[False, True])

    section(f"Students ({len(view)})", "users", "Risk ke hisaab se, sabse zyada pehle")
    if view.empty:
        empty("In filters se koi student match nahi hua. Range badhaayein ya search hataayein.")
    else:
        table = view.assign(Risk=view["Risk"].map(risk_chip),
                            Trend=view["Trend"].map(lambda t: "History nahi" if pd.isna(t) else f"{t:+.1f}"),
                            Action=np.where(view["Intervention"], "Intervene", "Monitor"))
        why("Kisi row par click karein, us student ka quick view khulega.")
        event = st.dataframe(
            table[["Student", "Name", "Class", "Predicted score", "Risk", "Risk score", "Attendance",
                   "Main concern", "Trend", "Action"]], hide_index=True, key="roster_tbl",
            on_select="rerun", selection_mode="single-row",
            column_config={"Predicted score": st.column_config.ProgressColumn(format="%.1f", min_value=0, max_value=100),
                           "Attendance": st.column_config.NumberColumn(format="%.0f%%"),
                           "Trend": st.column_config.TextColumn(help="Pichhle record ke mukaable predicted score mein badlaav")})
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


@st.dialog("Student ka quick view", width="large")
def _quick_view(row):
    r = row["_risk"]
    dialog_head("users", f"{row['Name'] or row['Student']}", f"{row['Student']}, {row['Class'] or 'class nahi'}")
    kpis([("Predicted score", f"{row['Predicted score']:.1f}", "latest record se", None),
          ("Risk level", r["level"], f"Risk score {r['score']:.0f}/100", RISK_COLORS[r["level"]]),
          ("Attendance", f"{row['Attendance']:g}%", "latest record se", None),
          ("Trend", row["Trend"], "pichhle record se", None)])
    if r["factors"]:
        st.markdown("**Flag kyun hua**")
        for f in r["factors"][:4]:
            st.markdown(f"- {f['reason']} (+{f['points']:g})")
    else:
        st.markdown("Koi risk rule trigger nahi hua.")
    c1, c2 = st.columns(2)
    if c1.button("Poori Profile Dekhein", type="primary", width="stretch", icon=":material/person:"):
        st.session_state["pending_student"] = row["Student"]
        pages = st.session_state.get("pages", {})
        if "profile" in pages:
            st.switch_page(pages["profile"])
        st.rerun()
    if c2.button("Band Karein", width="stretch"):
        st.rerun()


@st.dialog("Intervention plan banayein", width="large")
def _intervention_dialog(sid, name, r):
    issues = [f["factor"] for f in r["factors"][:3]]
    actions = [ACTION_LIBRARY[i] for i in issues if i in ACTION_LIBRARY]
    actions += ["Ek hafte ke andar mentoring baatcheet rakhein",
                "Agle 2 hafte performance par nazar rakhein aur dobara assess karein"]
    dialog_head("flag", f"{name or sid} ({sid})", f"{r['level']} risk, risk score {r['score']:.0f} of 100")
    c1, c2 = st.columns(2)
    c1.markdown("**Main issues**\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(issues, 1)))
    c2.markdown("**Suggested actions**\n" + "\n".join(f"- {a}" for a in actions))
    fu = st.date_input("Follow-up ki tareekh", value=date.today() + timedelta(days=14), key="iv_date")
    notes = st.text_area("Notes", key="iv_notes", max_chars=1000, placeholder="Student ke saath kya tay hua?")
    b1, b2 = st.columns(2)
    if b1.button("Cancel Karein", width="stretch"):
        st.rerun()
    if b2.button("Intervention Plan Banayein", type="primary", width="stretch", icon=":material/flag:"):
        me = st.session_state["user"]
        if not access.can_view_student(me, sid):
            st.error("Aapko is student ka access nahi hai.")
            return
        iid = db.create_intervention(sid, me["username"], r["level"], issues, actions, fu.isoformat(), notes)
        audit.log("intervention.create", me, "intervention", iid, {"student": sid, "risk": r["level"]})
        db.add_notification("intervention", "high", "Aapke teacher ne support meeting rakhi hai. "
                            "Usse pehle apna study plan dekh lein.", sid, recipient_student_id=sid)
        st.session_state["flash_iv"] = f"{sid} ke liye intervention plan ban gaya."
        st.rerun()


def _interventions(df):
    section("Early intervention", "flag")
    if msg := st.session_state.pop("flash_iv", None):
        st.success(msg)
    need = df[df["Intervention"]].sort_values("Risk score", ascending=False)
    if need.empty:
        empty("Abhi kisi student ko intervention ki zaroorat nahi hai.")
    else:
        top = need.head(6)
        cols = st.columns(3)
        for i, (_, row) in enumerate(top.iterrows()):
            r = row["_risk"]
            with cols[i % 3]:
                with st.container(key=f"reg_iv{i}"):
                    st.markdown(f"**{row['Name'] or row['Student']}**  \n{row['Student']}, {r['level']} risk "
                                f"({r['score']:.0f})  \nMain concern: {row['Main concern']}")
                    if st.button("Intervention Plan Karein", key=f"ivbtn{i}", icon=":material/flag:", width="stretch"):
                        _intervention_dialog(row["Student"], row["Name"], r)
        if len(need) > 6:
            why(f"Sabse zyada risk wale 6 students dikh rahe hain. {len(need) - 6} aur ko intervention chahiye; "
                "unhe dekhne ke liye table ko High risk par filter karein.")

    ints = db.interventions_df()
    ints = ints[ints["student_id"].isin(df["Student"])] if not ints.empty else ints
    if not ints.empty:
        st.markdown("**Intervention log**")
        edited = st.data_editor(
            ints[["id", "student_id", "created_at", "risk_level", "follow_up_date", "status", "notes"]],
            hide_index=True, disabled=["id", "student_id", "created_at", "risk_level", "follow_up_date"],
            column_config={"status": st.column_config.SelectboxColumn(options=["Open", "In progress", "Closed"])},
            key="iv_editor")
        if st.button("Intervention Updates Save Karein"):
            before = ints.set_index("id")
            for _, row in edited.iterrows():
                old = before.loc[int(row["id"])]
                if old["status"] != row["status"] or (old["notes"] or "") != (row["notes"] or ""):
                    db.update_intervention(int(row["id"]), row["status"], row["notes"] or "")
                    audit.log("intervention.update", st.session_state["user"], "intervention", int(row["id"]),
                              {"status": row["status"]})
            st.success("Intervention log update ho gaya.")


def analytics():
    require_role("teacher", "admin")
    header("Analytics & data quality", "Training dataset kaisa hai, aur us par kitna bharosa kiya ja sakta hai.")
    df, err = read_csv_safely(DATASET_PATH)
    if err:
        st.error(f"Training dataset padha nahi ja saka: {err}")
        return
    rep = data_quality_report(df)
    kpis([("Rows", str(rep["rows"]), "training records", None),
          ("Columns", str(rep["columns"]), "5 inputs + target", None),
          ("Missing values", str(sum(rep["missing"].values())), "saare columns mein", None),
          ("Duplicate rows", str(rep["duplicates"]), "", None),
          ("Lowest correlation", f"{rep['min_pairwise_corr']:.2f}", "kinhi do columns ke beech", None)])
    if rep["rows"] < 30:
        st.warning(f"Abhi ke dataset mein {rep['rows']} rows hain. Yeh prototype dikhane ke liye theek hai "
                   "lekin asli duniya mein bharose ke liye kaafi nahi hai. Final scores ke saath aur records "
                   "import karke retrain karein.")
    if rep["min_pairwise_corr"] > 0.9:
        st.warning("Har column lagbhag ek saath badalta hai, jo asli records se zyada haath se bana sample data lagta hai. "
                   "Model factors ko alag-alag theek se nahi pehchaan sakta.")

    section("Summary statistics", "db")
    d = rep["describe"].round(2)
    d["IQR outliers"] = pd.Series(rep["outliers"])
    st.dataframe(d)

    c1, c2 = st.columns(2)
    with c1:
        col = st.selectbox("Kiska distribution", list(df.select_dtypes("number").columns), key="an_dist")
        fig = px.histogram(df, x=col, nbins=10, title=f"{col} distribution")
        fig.update_traces(marker_color=accent())
        fig.update_layout(height=300)
        st.plotly_chart(fig)
    with c2:
        fig = px.imshow(rep["corr"].round(2), text_auto=True, color_continuous_scale=["#FFFFFF", accent()],
                        zmin=0, zmax=1, title="Correlation matrix")
        fig.update_layout(height=300)
        st.plotly_chart(fig)
    feat = st.selectbox("Final score se rishta", FEATURE_NAMES, format_func=lambda k: FEATURES[k]["label"])
    fig = px.scatter(df, x=feat, y=TARGET, title=f"{FEATURES[feat]['label']} vs final score")
    fig.update_traces(marker=dict(size=11, color=INK))
    fig.update_layout(height=320)
    st.plotly_chart(fig)

    section("Chune hue student ka breakdown", "chart")
    a = analysis()
    v = a["values"]
    sd = pd.DataFrame({"Category": ["Attendance", "Assignment", "Internal", "Previous marks"],
                       "Score": [v["Attendance"], v["Assignment_Score"], v["Internal_Marks"], v["Previous_Marks"]]})
    fig = px.bar(sd, x="Category", y="Score", title="Performance breakdown")
    fig.update_traces(marker_color=accent())
    fig.update_layout(height=280, yaxis=dict(range=[0, 100]))
    st.plotly_chart(fig)
    why("Yeh chart original dashboard ke Analytics tab se rakha gaya hai.")
