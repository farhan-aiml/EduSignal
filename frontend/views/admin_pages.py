"""Admin pages: institution dashboard, data import, model management."""
from __future__ import annotations

import shutil
from datetime import date, datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from backend.config import DATA_DIR, DATASET_PATH, FEATURE_NAMES, RISK_COLORS, TARGET
from backend.database import database as db
from backend.ml.train_model import train
from backend.services import audit, imports, seed, training
from backend.services import models as model_registry
from backend.utils import notifications
from backend.utils.demo_data import generate_demo
from backend.utils.validation import read_csv_safely, validate_dataframe
from frontend.views.common import (require_role, accent, dialog_head, demo_badge, empty, header, kpis, require_model, roster,
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
                seed.seed_structure()
                made = seed.seed_demo_academics()
                notifications.alerts_for_all(bundle)
                audit.log("demo.load", _me(), details=made)
                st.session_state["flash_admin"] = (f"Loaded 36 demo students with {made['sessions']} attendance "
                                                   f"sessions and {made['assessments']} assessments.")
            else:
                db.delete_demo_data()
                audit.log("demo.remove", _me())
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
        audit.log("teacher.update", _me(), "teacher", username, {"subject": subj.strip(), "classes": picked})
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
    _academic_activity()

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
    if not rep.ok:
        key = f"failed_logged_{up.file_id}" if hasattr(up, "file_id") else None
        if key and not st.session_state.get(key):
            imports.record_failed_batch(_me(), up.name, rep.errors)
            st.session_state[key] = True
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
    dups = imports.find_db_duplicates(clean)
    if dups.any():
        st.warning(f"{int(dups.sum())} row(s) are already in the database (same Student_ID and Record_Date) "
                   "and will be skipped, not duplicated.")
    st.markdown(f"**{int((~dups).sum())} new row(s) ready to import**")
    st.dataframe(clean.head(50), hide_index=True)

    has_target = TARGET in clean.columns and clean[TARGET].notna().any()
    add_training = st.checkbox(f"Also add rows with {TARGET} to the training dataset "
                               "(a backup of the current dataset is kept)", disabled=not has_target)
    if msg := st.session_state.pop("flash_import", None):
        st.success(msg)
    if st.button("Import records", type="primary", icon=":material/upload:"):
        _import_dialog(clean, rep.rejected, up.name, add_training and has_target, bundle)


@st.dialog("Import these records?", width="medium")
def _import_dialog(clean, rejected, filename, add_training, bundle):
    n_students = clean["Student_ID"].nunique() if "Student_ID" in clean.columns else len(clean)
    dialog_head("db", f"{len(clean)} valid records", f"About {n_students} students. Alerts run after import.")
    if add_training:
        st.markdown("Rows with a final score will also be added to the training dataset (a backup is kept).")
    b1, b2 = st.columns(2)
    if b1.button("Cancel", width="stretch"):
        st.rerun()
    if b2.button("Import now", type="primary", width="stretch"):
        try:   # all rows in one transaction: either everything valid is saved, or nothing is
            res = imports.import_records(_me(), clean, rejected, filename)
        except Exception as e:
            st.error(f"Import failed and nothing was saved: {e}")
            return
        seed.seed_structure()
        sent = notifications.alerts_for_all(bundle)
        msg = (f"Batch #{res['batch_id']}: imported {res['imported']} record(s) ({res['new_students']} new students), "
               f"rejected {res['rejected']}. {sent} alert(s) generated.")
        if add_training:
            added = _append_training(clean[clean[TARGET].notna()])
            audit.log("training_data.append", _me(), "dataset", "student_performance.csv", {"rows_added": added})
            msg += f" Added {added} row(s) to the training dataset; retrain on Model management to use them."
        st.session_state["flash_import"] = msg
        st.rerun()


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
                f"Uses {n_rows} clean rows (CSV + real final scores in the database). The current model is replaced.")
    st.markdown(f"Current model: **{bundle['model_name']}**, MAE {bundle['metrics']['MAE']:.2f}, "
                f"trained {bundle['trained_at']}.")
    b1, b2 = st.columns(2)
    if b1.button("Cancel", width="stretch"):
        st.rerun()
    if b2.button("Retrain now", type="primary", width="stretch"):
        try:
            with st.spinner("Training and cross-validating models…"):
                data, rep_ = training.assemble()
                nb = train(data=data, data_sources=rep_["sources"])
            version = model_registry.register(nb)
            audit.log("model.retrain", _me(), "model", version,
                      {"model": nb["model_name"], "mae": nb["metrics"]["MAE"], "rows": nb["training_rows"]})
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

    section("Training data", "db", "Real data only: demo students are never used")
    data, trep = training.assemble()
    ready = training.readiness(trep)
    level_col = {"blocked": RISK_COLORS["High"], "demo": RISK_COLORS["High"], "weak": RISK_COLORS["Moderate"],
                 "fair": RISK_COLORS["Moderate"], "good": RISK_COLORS["Low"]}[ready["level"]]
    kpis([("Training rows", str(ready["rows"]), "clean, de-duplicated", level_col, "db"),
          ("Needed for a test set", str(ready["needed_for_test_set"]), "more rows (test set from 40)", None, "target"),
          ("To recommended size", str(ready["needed_recommended"]), "more rows (100 recommended)", None, "chart"),
          ("Duplicates removed", str(trep["duplicates"]), "same row in two sources", None, "layers"),
          ("Demo rows excluded", str(trep["demo_excluded"]), "synthetic, never trained on", None, "shield")])
    if ready["level"] in ("blocked", "demo", "weak"):
        st.warning(ready["message"] + " This model is not production-ready.")
    else:
        st.info(ready["message"])
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("**Where the data came from**")
        st.dataframe(pd.DataFrame(list(trep["sources"].items()), columns=["Source", "Rows"]), hide_index=True)
        if trep["rejected"]:
            st.markdown("**Rejected rows**")
            st.dataframe(pd.DataFrame(list(trep["rejected"].items()), columns=["Reason", "Rows"]), hide_index=True)
    with c2:
        st.markdown("**Data needed for training (one row per student per term)**")
        st.dataframe(pd.DataFrame(training.REQUIRED_DATA, columns=["Column", "What it should contain"]), hide_index=True)
        why("Import real records with a Final_Score through Data import, then retrain.")
    if bundle.get("holdout"):
        h = bundle["holdout"]
        section("Separate test set result", "check")
        kpis([("Test rows", str(h["rows"]), f"trained on {h['train_rows']} rows", None, "db"),
              ("Test MAE", f"{h['MAE']:.2f}", f"baseline {h['baseline_MAE']:.2f}", None, "target"),
              ("Test RMSE", f"{h['RMSE']:.2f}", "points", None, "chart"), ("Test R²", f"{h['R2']:.3f}", "", None, "chart")])
    section("Retrain", "chip")
    if msg := st.session_state.pop("flash_model", None):
        st.success(msg)
    if st.button("Retrain model", type="primary", icon=":material/model_training:",
                 disabled=ready["level"] == "blocked"):
        _retrain_dialog(len(data), bundle)

    section("Model versions", "layers")
    model_registry.register(bundle)
    st.dataframe(model_registry.versions_df(), hide_index=True,
                 column_config={"interval_p80": st.column_config.NumberColumn(
                     "±80% interval", help="Half-width of an ~80% prediction interval from cross-validated residuals")})
    why("Every saved prediction stores the model version and the exact inputs used, so it can be reproduced.")

    section("Checked against real outcomes", "check")
    ev = model_registry.evaluate_against_outcomes(bundle, db.get_settings())
    if not ev["rows"]:
        empty("No records with an actual final score outside the training data yet, so the model can't be checked "
              "against real outcomes. Import records with Final_Score to enable this.", "target")
    else:
        pct = lambda v: "n/a" if v is None else f"{100 * v:.0f}%"
        kpis([("Records checked", str(ev["rows"]), "not used for training", None, "db"),
              ("Prediction MAE", f"{ev['mae']:.1f}", "points vs actual", None, "target"),
              ("80% interval coverage", pct(ev["interval_coverage"]), "should be near 80%", None, "chart"),
              ("High-risk precision", pct(ev["precision"]), f"{ev['tp']} of {ev['tp'] + ev['fp']} flags failed", None, "alert"),
              ("High-risk recall", pct(ev["recall"]), f"{ev['tp']} of {ev['positives']} failures flagged", None, "flag")])
        if not ev["enough"]:
            st.warning(f"Only {ev['rows']} records: too few for reliable numbers (at least {ev['min_rows']} recommended).")

    with st.expander("Saved metadata"):
        st.json({k: v for k, v in bundle.items() if k not in ("pipeline", "background", "target_values", "comparison")})


def _academic_activity():
    """Institution-wide counts from attendance sessions, assessments, imports, notifications and the audit log."""
    with db.connect() as con:
        q = lambda sql: con.execute(sql).fetchone()[0]
        sessions = q("SELECT COUNT(*) FROM attendance_sessions")
        att = q("SELECT 100.0 * SUM(status IN ('present','late')) / NULLIF(SUM(status != 'excused'), 0) FROM attendance_records")
        n_assess = q("SELECT COUNT(*) FROM assessments")
        avg_mark = q("SELECT AVG(100.0 * m.marks / a.max_marks) FROM assessment_marks m JOIN assessments a ON a.id = m.assessment_id")
        unread = q("SELECT COUNT(*) FROM notifications WHERE is_read = 0")
        imports_n = q("SELECT COUNT(*) FROM import_batches")
        denied = q("SELECT COUNT(*) FROM audit_log WHERE outcome != 'ok' AND created_at >= datetime('now', 'localtime', '-7 days')")
    section("Academic activity", "calendar", "From recorded sessions, marks and system logs")
    kpis([("Attendance sessions", str(sessions), "recorded by teachers", None, "calendar"),
          ("Session attendance", "–" if att is None else f"{att:.1f}%", "present or late", None, "check"),
          ("Assessments", str(n_assess), "–" if avg_mark is None else f"average mark {avg_mark:.0f}%", None, "pencil"),
          ("Unread alerts", str(unread), "all recipients", None, "bell"),
          ("CSV imports", str(imports_n), "see Users & security", None, "db"),
          ("Failed or denied actions", str(denied), "last 7 days", RISK_COLORS["High"] if denied else None, "shield")])


def _me() -> dict:
    return st.session_state.get("user") or {}
