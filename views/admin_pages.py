"""Admin pages: institution dashboard, data import, model management."""
from __future__ import annotations

import shutil
from datetime import date, datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import DATA_DIR, DATASET_PATH, FEATURE_NAMES, RISK_COLORS, TARGET
from database import database as db
from ml.predict import predict_many
from ml.train_model import train
from utils import notifications
from utils.demo_data import generate_demo
from utils.risk_engine import assess
from utils.validation import read_csv_safely, validate_dataframe
from views.common import (require_role, accent, dialog_head, demo_badge, empty, header, kpis, require_model, roster,
                          section, teacher_picker, why)


@st.dialog("Demo data", width="medium")
def _demo_dialog(action, bundle):
    if action == "load":
        dialog_head("users", "Load 36 synthetic demo students",
                    "Adds 5 weekly records and subject scores per student, plus the alerts they trigger.")
        st.markdown("Use this to demonstrate trends, subjects and the teacher views. Demo students are named "
                    "*Demo student NN*, carry a demo badge, and can be removed in one click.")
        label, kind = "Load demo students", "primary"
    else:
        dialog_head("alert", "Remove all demo data",
                    "Deletes demo students with their records, interventions and notifications.")
        st.markdown("Real records imported from your CSV files are not affected.")
        label, kind = "Remove demo data", "primary"
    b1, b2 = st.columns(2)
    if b1.button("Cancel", width="stretch"):
        st.rerun()
    with b2.container(key="danger_demo" if action == "remove" else "ok_demo"):
        go_ = st.button(label, type=kind, width="stretch")
    if go_:
        with st.spinner("Working…"):
            if action == "load":
                generate_demo()
                _alerts_for_all(bundle)
                st.session_state["flash_admin"] = "Loaded 36 demo students."
            else:
                db.delete_demo_data()
                st.session_state["flash_admin"] = "Demo data removed."
        st.rerun()


@st.dialog("Edit teacher", width="medium")
def _teacher_dialog(username, name, subject):
    dialog_head("users", name, "Subject and the classes this teacher is responsible for.")
    subj = st.text_input("Subject", value=subject, max_chars=80, placeholder="e.g. Data Structures", key=f"subj_{username}")
    current = db.get_teacher_classes(username)
    options = sorted(set(db.class_sections()) | set(current))
    picked = st.multiselect("Classes", options, default=current, key=f"cls_{username}")
    taken = {c: t for t in db.teachers_df()["username"] if t != username for c in db.get_teacher_classes(t)}
    shared = [c for c in picked if c in taken]
    if shared:
        why("Also taught by another teacher: " + ", ".join(shared) + ". Both will see these students.")
    b1, b2 = st.columns(2)
    if b1.button("Cancel", width="stretch"):
        st.rerun()
    if b2.button("Save changes", type="primary", width="stretch", icon=":material/check:"):
        db.set_teacher_classes(username, picked)
        db.set_teacher_subject(username, subj.strip())
        st.session_state["flash_admin"] = f"Updated {name}: {subj.strip() or 'no subject'}, classes {', '.join(picked) or 'none'}."
        st.rerun()


def _teachers_section(bundle):
    section("Faculty directory", "users", "Select a teacher, then view their dashboard")
    teacher_picker(bundle, key="adm", edit_dialog=_teacher_dialog)


def institution():
    require_role("admin")
    bundle = require_model()
    header("Admin dashboard", "Institution-wide performance, risk and intervention activity.")
    df, _ = roster(bundle)

    n = db.demo_count()
    c1, c2, c3 = st.columns([1.2, 1.2, 2.6])
    if c1.button("Load demo students", icon=":material/group_add:", type="primary", disabled=n > 0, width="stretch"):
        _demo_dialog("load", bundle)
    if c2.button(f"Remove demo data ({n})", icon=":material/delete_sweep:", disabled=n == 0, width="stretch"):
        _demo_dialog("remove", bundle)
    c3.markdown('<div class="why" style="padding-top:.55rem">Demo students are synthetic, marked everywhere, '
                'and never used for training.</div>', unsafe_allow_html=True)
    if msg := st.session_state.pop("flash_admin", None):
        st.success(msg)

    if df.empty:
        empty("No student records yet. Import a CSV or load demo data above.")
        return
    if df["Demo"].any():
        st.markdown(demo_badge(f"{int(df['Demo'].sum())} of {len(df)} students are synthetic demo data"),
                    unsafe_allow_html=True)
    ints = db.interventions_df()
    counts = df["Risk"].value_counts()
    kpis([("Total students", str(len(df)), "", None),
          ("Average predicted score", f"{df['Predicted score'].mean():.1f}", "", None),
          ("High-risk students", str(counts.get("High", 0)), f"{100 * counts.get('High', 0) / len(df):.0f}% of total",
           RISK_COLORS["High"]),
          ("Average attendance", f"{df['Attendance'].mean():.1f}%", "", None),
          ("Interventions", str(len(ints)), f"{int((ints['status'] != 'Closed').sum()) if len(ints) else 0} open", None)])

    c1, c2 = st.columns(2)
    with c1:
        fig = px.histogram(df, x="Predicted score", nbins=12, title="Predicted score distribution")
        fig.update_traces(marker_color=accent())
        fig.update_layout(height=300, yaxis_title="Students")
        st.plotly_chart(fig)
    with c2:
        fig = px.box(df, x="Department", y="Attendance", title="Attendance by department", points="all")
        fig.update_traces(marker_color=accent(), line_color=accent())
        fig.update_layout(height=300)
        st.plotly_chart(fig)

    _teachers_section(bundle)

    section("Department and class statistics", "layers")
    g = df.groupby(["Department", "Class"]).agg(
        Students=("Student", "count"), Avg_predicted=("Predicted score", "mean"),
        Avg_attendance=("Attendance", "mean"),
        High_risk=("Risk", lambda s: int((s == "High").sum())),
        Moderate_risk=("Risk", lambda s: int((s == "Moderate").sum()))).round(1).reset_index()
    st.dataframe(g.rename(columns=lambda c: c.replace("_", " ")), hide_index=True)
    stacked = df.groupby(["Department", "Risk"]).size().reset_index(name="Students")
    fig = px.bar(stacked, x="Department", y="Students", color="Risk", title="Risk by department",
                 color_discrete_map=RISK_COLORS, category_orders={"Risk": ["High", "Moderate", "Low"]})
    fig.update_layout(height=300)
    st.plotly_chart(fig)

    section("Intervention statistics", "flag")
    if ints.empty:
        empty("No interventions recorded yet. Teachers create them from the Teacher dashboard.")
    else:
        stat = ints["status"].value_counts().reindex(["Open", "In progress", "Closed"], fill_value=0)
        fig = go.Figure(go.Bar(x=stat.index, y=stat.values, marker_color=accent()))
        fig.update_layout(height=260, title="Interventions by status")
        st.plotly_chart(fig)


def _alerts_for_all(bundle):
    s = db.get_settings()
    rec = db.records_df()
    if rec.empty:
        return 0
    rec["Predicted"] = predict_many(bundle, rec)
    sent = 0
    for sid, g in rec.groupby("student_id"):
        g = g.sort_values(["record_date", "id"])
        last = g.iloc[-1]
        values = {f: float(last[f]) for f in FEATURE_NAMES}
        r = assess(values, float(last["Predicted"]), s, g["Predicted"].tolist()[:-1])
        sent += notifications.dispatch(notifications.build_alerts(sid, last["name"], {"risk": r, "values": values}, s))
    return sent


def data_import():
    require_role("admin")
    bundle = require_model()
    header("Data import", "Upload student records as CSV. Every row is checked before anything is saved.")
    st.markdown("**Required columns:** " + ", ".join(FEATURE_NAMES) + "  \n**Optional:** Student_ID, Name, "
                "Department, Class_Section, Record_Date (YYYY-MM-DD), Classes_Held, Classes_Attended, " + TARGET)
    template = pd.DataFrame([{"Student_ID": "S001", "Name": "Example", "Department": "CSE", "Class_Section": "CSE-A",
                              "Record_Date": date.today().isoformat(), "Attendance": 82, "Assignment_Score": 74,
                              "Internal_Marks": 70, "Study_Hours": 3.5, "Previous_Marks": 68,
                              "Classes_Held": 40, "Classes_Attended": 33, TARGET: ""}])
    st.download_button("Download CSV template", template.to_csv(index=False), "student_records_template.csv", "text/csv")

    up = st.file_uploader("CSV file", type=["csv"])
    if not up:
        return
    df, err = read_csv_safely(up)
    if err:
        st.error(err)
        return
    rep = validate_dataframe(df)
    for e in rep.errors:
        st.error(e)
    for w in rep.warnings:
        st.warning(w)
    if rep.rejected is not None and not rep.rejected.empty:
        st.markdown("**Rejected rows**")
        st.dataframe(rep.rejected, hide_index=True)
    if not rep.ok:
        return
    clean = rep.clean
    st.markdown(f"**{len(clean)} valid row(s) ready to import**")
    st.dataframe(clean.head(50), hide_index=True)

    has_target = TARGET in clean.columns and clean[TARGET].notna().any()
    add_training = st.checkbox(f"Also add rows with {TARGET} to the training dataset "
                               "(a backup of the current dataset is kept)", disabled=not has_target)
    if msg := st.session_state.pop("flash_import", None):
        st.success(msg)
    if st.button("Import records", type="primary", icon=":material/upload:"):
        _import_dialog(clean, add_training and has_target, bundle)


@st.dialog("Import these records?", width="medium")
def _import_dialog(clean, add_training, bundle):
    n_students = clean["Student_ID"].nunique() if "Student_ID" in clean.columns else len(clean)
    dialog_head("db", f"{len(clean)} valid records", f"About {n_students} students. Alerts run after import.")
    if add_training:
        st.markdown("Rows with a final score will also be added to the training dataset (a backup is kept).")
    b1, b2 = st.columns(2)
    if b1.button("Cancel", width="stretch"):
        st.rerun()
    if b2.button("Import now", type="primary", width="stretch"):
        n_existing = len(db.students_df())
        for i, row in clean.iterrows():
            sid = str(row.get("Student_ID") or "").strip() or f"IMP-{n_existing + i + 1:04d}"
            sid = sid[:40]
            db.upsert_student(sid, name=_opt(row, "Name"), department=_opt(row, "Department"),
                              class_section=_opt(row, "Class_Section"), source="import")
            db.add_record(sid, {f: row[f] for f in FEATURE_NAMES}, record_date=_opt(row, "Record_Date"),
                          final_score=_num(row, TARGET), classes_held=_int(row, "Classes_Held"),
                          classes_attended=_int(row, "Classes_Attended"), source="import")
        sent = _alerts_for_all(bundle)
        msg = f"Imported {len(clean)} record(s). {sent} alert(s) generated."
        if add_training:
            added = _append_training(clean[clean[TARGET].notna()])
            msg += f" Added {added} row(s) to the training dataset; retrain on Model management to use them."
        st.session_state["flash_import"] = msg
        st.rerun()


def _opt(row, col):
    v = row.get(col)
    return None if v is None or pd.isna(v) or str(v).strip() == "" else str(v).strip()[:120]


def _num(row, col):
    v = row.get(col)
    return None if v is None or pd.isna(v) else float(v)


def _int(row, col):
    v = _num(row, col)
    return None if v is None else int(v)


def _append_training(rows: pd.DataFrame) -> int:
    backups = DATA_DIR / "backups"
    backups.mkdir(exist_ok=True)
    shutil.copy(DATASET_PATH, backups / f"student_performance_{datetime.now():%Y%m%d_%H%M%S}.csv")
    cur, _ = read_csv_safely(DATASET_PATH)
    new = rows[FEATURE_NAMES + [TARGET]]
    merged = pd.concat([cur, new], ignore_index=True).drop_duplicates()
    merged.to_csv(DATASET_PATH, index=False)
    return len(merged) - len(cur)


@st.dialog("Retrain the model?", width="medium")
def _retrain_dialog(n_rows, bundle):
    dialog_head("chip", "Retrain and re-compare all models",
                f"Uses {n_rows} rows from data/student_performance.csv. The current model is replaced.")
    st.markdown(f"Current model: **{bundle['model_name']}**, MAE {bundle['metrics']['MAE']:.2f}, "
                f"trained {bundle['trained_at']}.")
    b1, b2 = st.columns(2)
    if b1.button("Cancel", width="stretch"):
        st.rerun()
    if b2.button("Retrain now", type="primary", width="stretch"):
        try:
            with st.spinner("Training and cross-validating models…"):
                nb = train()
            st.cache_resource.clear()
            st.cache_data.clear()
            st.session_state["flash_model"] = (f"Retrained. Selected {nb['model_name']} "
                                               f"(MAE {nb['metrics']['MAE']:.2f}).")
            st.rerun()
        except ValueError as e:
            st.error(f"Retraining failed: {e}")


def model_management():
    require_role("admin")
    bundle = require_model()
    header("Model management", "Which model is in use, how it was chosen, and how well it validated.")
    m = bundle["metrics"]
    kpis([("Model in use", bundle["model_name"], "", None),
          ("R² (cross-validated)", f"{m['R2']:.3f}", "", None),
          ("MAE", f"{m['MAE']:.2f}", "points", None),
          ("RMSE", f"{m['RMSE']:.2f}", "points", None),
          ("Training rows", str(bundle["training_rows"]), bundle["trained_at"], None)])
    st.markdown(f"**Why this model:** {bundle['selection_reason']}")
    for lim in bundle["limitations"]:
        st.warning(lim)

    section("Model comparison", "chart")
    comp = pd.DataFrame(bundle["comparison"])
    st.dataframe(comp.round(3), hide_index=True,
                 column_config={"Worst drop": st.column_config.NumberColumn(
                     help="Largest fall in prediction when one input increases (score points). "
                          "Above 0.5 fails the sanity check.")})
    why(f"All metrics come from {bundle['cv_scheme'].lower()}: each record is predicted by a model that "
        "never saw it. The baseline always predicts the average score; a useful model must beat it.")
    fig = px.bar(comp, x="Model", y="RMSE", title="Cross-validated RMSE (lower is better)",
                 color="Sanity check", color_discrete_map={"Pass": accent(), "Fail": RISK_COLORS["High"]})
    fig.update_layout(height=300, xaxis_title=None)
    st.plotly_chart(fig)

    section("Retrain", "chip")
    df, err = read_csv_safely(DATASET_PATH)
    st.markdown(f"Dataset: `data/student_performance.csv`, {len(df) if df is not None else 0} rows. "
                "Retraining re-runs the comparison and replaces the saved model.")
    if msg := st.session_state.pop("flash_model", None):
        st.success(msg)
    if st.button("Retrain model", type="primary", icon=":material/model_training:"):
        _retrain_dialog(len(df) if df is not None else 0, bundle)

    with st.expander("Saved metadata"):
        st.json({k: v for k, v in bundle.items() if k not in ("pipeline", "background", "target_values", "comparison")})
