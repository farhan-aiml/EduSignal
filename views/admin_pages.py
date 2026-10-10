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
from services import audit, imports, seed, training
from services import models as model_registry
from utils import notifications
from utils.demo_data import generate_demo
from utils.risk_engine import assess
from utils.validation import read_csv_safely, validate_dataframe
from views.common import (require_role, accent, dialog_head, demo_badge, empty, header, kpis, require_model, roster,
                          section, teacher_picker, why)


@st.dialog("Demo data", width="medium")
def _demo_dialog(action, bundle):
    if action == "load":
        dialog_head("users", "36 synthetic demo students load karein",
                    "Har student ke 5 weekly records, subject scores, attendance aur marks, aur unse bane alerts jodta hai.")
        st.markdown("Trends, subjects aur teacher views dikhane ke liye. Demo students ke naam "
                    "par demo badge hota hai aur ek click mein hataaye ja sakte hain.")
        label, kind = "Demo Students Load Karein", "primary"
    else:
        dialog_head("alert", "Saara demo data hataayein",
                    "Demo students ko unke records, interventions aur notifications ke saath delete karta hai.")
        st.markdown("CSV se import kiye asli records par koi asar nahi padega.")
        label, kind = "Demo Data Hataayein", "primary"
    b1, b2 = st.columns(2)
    if b1.button("Cancel Karein", width="stretch"):
        st.rerun()
    with b2.container(key="danger_demo" if action == "remove" else "ok_demo"):
        go_ = st.button(label, type=kind, width="stretch")
    if go_:
        with st.spinner("Kaam ho raha hai…"):
            if action == "load":
                generate_demo()
                seed.seed_structure()
                made = seed.seed_demo_academics()
                _alerts_for_all(bundle)
                audit.log("demo.load", _me(), details=made)
                st.session_state["flash_admin"] = (f"36 demo students load ho gaye, {made['sessions']} attendance "
                                                   f"sessions aur {made['assessments']} assessments ke saath.")
            else:
                db.delete_demo_data()
                audit.log("demo.remove", _me())
                st.session_state["flash_admin"] = "Demo data hata diya gaya."
        st.rerun()


@st.dialog("Teacher edit karein", width="medium")
def _teacher_dialog(username, name, subject):
    dialog_head("users", name, "Is teacher ka subject aur unki classes.")
    subj = st.text_input("Subject", value=subject, max_chars=80, placeholder="jaise Data Structures", key=f"subj_{username}")
    current = db.get_teacher_classes(username)
    options = sorted(set(db.class_sections()) | set(current))
    picked = st.multiselect("Classes", options, default=current, key=f"cls_{username}")
    taken = {c: t for t in db.teachers_df()["username"] if t != username for c in db.get_teacher_classes(t)}
    shared = [c for c in picked if c in taken]
    if shared:
        why("Yeh classes doosre teacher bhi padhaate hain: " + ", ".join(shared) + ". Dono in students ko dekhenge.")
    b1, b2 = st.columns(2)
    if b1.button("Cancel Karein", width="stretch"):
        st.rerun()
    if b2.button("Changes Save Karein", type="primary", width="stretch", icon=":material/check:"):
        db.set_teacher_classes(username, picked)
        db.set_teacher_subject(username, subj.strip())
        audit.log("teacher.update", _me(), "teacher", username, {"subject": subj.strip(), "classes": picked})
        st.session_state["flash_admin"] = f"{name} update ho gaye: {subj.strip() or 'subject nahi'}, classes {', '.join(picked) or 'koi nahi'}."
        st.rerun()


def _teachers_section(bundle):
    section("Faculty directory", "users", "Teacher chunein, phir unka dashboard dekhein")
    teacher_picker(bundle, key="adm", edit_dialog=_teacher_dialog)


def institution():
    require_role("admin")
    bundle = require_model()
    header("Admin dashboard", "Poore institution ki performance, risk aur intervention activity.")
    df, _ = roster(bundle)

    n = db.demo_count()
    c1, c2, c3 = st.columns([1.2, 1.2, 2.6])
    if c1.button("Demo Students Load Karein", icon=":material/group_add:", type="primary", disabled=n > 0, width="stretch"):
        _demo_dialog("load", bundle)
    if c2.button(f"Demo Data Hataayein ({n})", icon=":material/delete_sweep:", disabled=n == 0, width="stretch"):
        _demo_dialog("remove", bundle)
    c3.markdown('<div class="why" style="padding-top:.55rem">Demo students synthetic hain, har jagah mark hote hain, '
                'aur training mein kabhi use nahi hote.</div>', unsafe_allow_html=True)
    if msg := st.session_state.pop("flash_admin", None):
        st.success(msg)

    if df.empty:
        empty("Abhi koi student record nahi hai. CSV import karein ya upar demo data load karein.")
        return
    if df["Demo"].any():
        st.markdown(demo_badge(f"{len(df)} mein se {int(df['Demo'].sum())} students synthetic demo data hain"),
                    unsafe_allow_html=True)
    ints = db.interventions_df()
    counts = df["Risk"].value_counts()
    kpis([("Total students", str(len(df)), "", None),
          ("Average predicted score", f"{df['Predicted score'].mean():.1f}", "", None),
          ("High-risk students", str(counts.get("High", 0)), f"kul ka {100 * counts.get('High', 0) / len(df):.0f}%",
           RISK_COLORS["High"]),
          ("Average attendance", f"{df['Attendance'].mean():.1f}%", "", None),
          ("Interventions", str(len(ints)), f"{int((ints['status'] != 'Closed').sum()) if len(ints) else 0} khule", None)])
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
        empty("Abhi koi intervention record nahi hai. Teacher inhe Teacher dashboard se banaate hain.")
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
    header("Data import", "Student records CSV mein upload karein. Kuch bhi save hone se pehle har row check hoti hai.")
    st.markdown("**Zaroori columns:** " + ", ".join(FEATURE_NAMES) + "  \n**Optional:** Student_ID, Name, "
                "Department, Class_Section, Record_Date (YYYY-MM-DD), Classes_Held, Classes_Attended, " + TARGET)
    template = pd.DataFrame([{"Student_ID": "S001", "Name": "Example", "Department": "CSE", "Class_Section": "CSE-A",
                              "Record_Date": date.today().isoformat(), "Attendance": 82, "Assignment_Score": 74,
                              "Internal_Marks": 70, "Study_Hours": 3.5, "Previous_Marks": 68,
                              "Classes_Held": 40, "Classes_Attended": 33, TARGET: ""}])
    st.download_button("CSV Template Download Karein", template.to_csv(index=False), "student_records_template.csv", "text/csv")

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
        st.markdown("**Reject hui rows**")
        st.dataframe(rep.rejected, hide_index=True)
    if not rep.ok:
        return
    clean = rep.clean
    dups = imports.find_db_duplicates(clean)
    if dups.any():
        st.warning(f"{int(dups.sum())} row(s) pehle se database mein hain (wahi Student_ID aur Record_Date) "
                   "aur skip hongi, duplicate nahi banengi.")
    st.markdown(f"**{int((~dups).sum())} nayi row(s) import ke liye taiyaar**")
    st.dataframe(clean.head(50), hide_index=True)

    has_target = TARGET in clean.columns and clean[TARGET].notna().any()
    add_training = st.checkbox(f"{TARGET} wali rows ko training dataset mein bhi jodein "
                               "(abhi ke dataset ka backup rakha jaata hai)", disabled=not has_target)
    if msg := st.session_state.pop("flash_import", None):
        st.success(msg)
    if st.button("Records Import Karein", type="primary", icon=":material/upload:"):
        _import_dialog(clean, rep.rejected, up.name, add_training and has_target, bundle)


@st.dialog("Yeh records import karein?", width="medium")
def _import_dialog(clean, rejected, filename, add_training, bundle):
    n_students = clean["Student_ID"].nunique() if "Student_ID" in clean.columns else len(clean)
    dialog_head("db", f"{len(clean)} valid records", f"Lagbhag {n_students} students. Import ke baad alerts chalenge.")
    if add_training:
        st.markdown("Final score wali rows training dataset mein bhi judengi (backup rakha jaata hai).")
    b1, b2 = st.columns(2)
    if b1.button("Cancel Karein", width="stretch"):
        st.rerun()
    if b2.button("Abhi Import Karein", type="primary", width="stretch"):
        try:   # all rows in one transaction: either everything valid is saved, or nothing is
            res = imports.import_records(_me(), clean, rejected, filename)
        except Exception as e:
            st.error(f"Import fail ho gaya, kuch bhi save nahi hua: {e}")
            return
        seed.seed_structure()
        sent = _alerts_for_all(bundle)
        msg = (f"Batch #{res['batch_id']}: {res['imported']} record(s) import hue ({res['new_students']} naye students), "
               f"{res['rejected']} reject hue. {sent} naye alert bane.")
        if add_training:
            added = _append_training(clean[clean[TARGET].notna()])
            audit.log("training_data.append", _me(), "dataset", "student_performance.csv", {"rows_added": added})
            msg += f" Training dataset mein {added} row(s) judi; inhe use karne ke liye Model management mein retrain karein."
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
    dialog_head("chip", "Model dobara train karein",
                f"{n_rows} saaf rows use hongi (CSV + database ke asli final scores). Purana model replace hoga.")
    st.markdown(f"Abhi ka model: **{bundle['model_name']}**, MAE {bundle['metrics']['MAE']:.2f}, "
                f"{bundle['trained_at']} ko trained.")
    b1, b2 = st.columns(2)
    if b1.button("Cancel Karein", width="stretch"):
        st.rerun()
    if b2.button("Abhi Retrain Karein", type="primary", width="stretch"):
        try:
            with st.spinner("Models train aur cross-validate ho rahe hain…"):
                data, rep_ = training.assemble()
                nb = train(data=data, data_sources=rep_["sources"])
            version = model_registry.register(nb)
            audit.log("model.retrain", _me(), "model", version,
                      {"model": nb["model_name"], "mae": nb["metrics"]["MAE"], "rows": nb["training_rows"]})
            st.cache_resource.clear()
            st.cache_data.clear()
            st.session_state["flash_model"] = (f"Retrain ho gaya. Chuna gaya: {nb['model_name']} "
                                               f"(MAE {nb['metrics']['MAE']:.2f}).")
            st.rerun()
        except ValueError as e:
            st.error(f"Retraining fail ho gayi: {e}")


def model_management():
    require_role("admin")
    bundle = require_model()
    header("Model management", "Kaun sa model use ho raha hai, kaise chuna gaya, aur validation mein kitna sahi raha.")
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
                     help="Ek input badhne par prediction mein sabse badi giraavat (score points). "
                          "0.5 se zyada hone par sanity check fail hota hai.")})
    why(f"Saare metrics {bundle['cv_scheme'].lower()} se aaye hain: har record ko aisa model predict karta hai jisne "
        "use kabhi dekha nahi. Baseline hamesha average score batata hai; achha model usse behtar hona chahiye.")
    fig = px.bar(comp, x="Model", y="RMSE", title="Cross-validated RMSE (kam behtar hai)",
                 color="Sanity check", color_discrete_map={"Pass": accent(), "Fail": RISK_COLORS["High"]})
    fig.update_layout(height=300, xaxis_title=None)
    st.plotly_chart(fig)

    section("Training data", "db", "Sirf asli data: demo students kabhi shaamil nahi")
    data, trep = training.assemble()
    ready = training.readiness(trep)
    level_col = {"blocked": RISK_COLORS["High"], "demo": RISK_COLORS["High"], "weak": RISK_COLORS["Moderate"],
                 "fair": RISK_COLORS["Moderate"], "good": RISK_COLORS["Low"]}[ready["level"]]
    kpis([("Training rows", str(ready["rows"]), "saaf, bina duplicate", level_col, "db"),
          ("Test set ke liye aur chahiye", str(ready["needed_for_test_set"]), "rows (40 par alag test set)", None, "target"),
          ("Recommended tak", str(ready["needed_recommended"]), "rows aur (100 recommended)", None, "chart"),
          ("Duplicates hataaye", str(trep["duplicates"]), "do sources mein same row", None, "layers"),
          ("Demo rows chhode", str(trep["demo_excluded"]), "synthetic, kabhi train nahi", None, "shield")])
    if ready["level"] in ("blocked", "demo", "weak"):
        st.warning(ready["message"] + " Yeh model production-ready nahi hai.")
    else:
        st.info(ready["message"])
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("**Data kahan se aaya**")
        st.dataframe(pd.DataFrame(list(trep["sources"].items()), columns=["Source", "Rows"]), hide_index=True)
        if trep["rejected"]:
            st.markdown("**Reject hui rows**")
            st.dataframe(pd.DataFrame(list(trep["rejected"].items()), columns=["Wajah", "Rows"]), hide_index=True)
    with c2:
        st.markdown("**Training ke liye zaroori data (har student-term ke liye ek row)**")
        st.dataframe(pd.DataFrame(training.REQUIRED_DATA, columns=["Column", "Kya chahiye"]), hide_index=True)
        why("Real records Data import se Final_Score ke saath import karein, phir retrain karein.")
    if bundle.get("holdout"):
        h = bundle["holdout"]
        section("Alag test set ka result", "check")
        kpis([("Test rows", str(h["rows"]), f"train par {h['train_rows']} rows", None, "db"),
              ("Test MAE", f"{h['MAE']:.2f}", f"baseline {h['baseline_MAE']:.2f}", None, "target"),
              ("Test RMSE", f"{h['RMSE']:.2f}", "points", None, "chart"), ("Test R²", f"{h['R2']:.3f}", "", None, "chart")])
    section("Retrain", "chip")
    if msg := st.session_state.pop("flash_model", None):
        st.success(msg)
    if st.button("Model Retrain Karein", type="primary", icon=":material/model_training:",
                 disabled=ready["level"] == "blocked"):
        _retrain_dialog(len(data), bundle)

    section("Model versions", "layers")
    model_registry.register(bundle)
    st.dataframe(model_registry.versions_df(), hide_index=True,
                 column_config={"interval_p80": st.column_config.NumberColumn(
                     "±80% interval", help="Cross-validated residuals se ~80% prediction interval ki aadhi chaudaai")})
    why("Har saved prediction mein model version aur exact inputs save hote hain, taaki use dobara banaya ja sake.")

    section("Asli results se jaanch", "check")
    ev = model_registry.evaluate_against_outcomes(bundle, db.get_settings())
    if not ev["rows"]:
        empty("Training data ke bahar asli final score wala koi record abhi nahi hai, isliye model ko asli results se "
              "check nahi kiya ja sakta. Iske liye Final_Score ke saath records import karein.", "target")
    else:
        pct = lambda v: "n/a" if v is None else f"{100 * v:.0f}%"
        kpis([("Records checked", str(ev["rows"]), "training mein use nahi hue", None, "db"),
              ("Prediction MAE", f"{ev['mae']:.1f}", "asli ke mukaable points", None, "target"),
              ("80% interval coverage", pct(ev["interval_coverage"]), "80% ke aas-paas hona chahiye", None, "chart"),
              ("High-risk precision", pct(ev["precision"]), f"{ev['tp'] + ev['fp']} flags mein se {ev['tp']} fail hue", None, "alert"),
              ("High-risk recall", pct(ev["recall"]), f"{ev['positives']} failures mein se {ev['tp']} flag hue", None, "flag")])
        if not ev["enough"]:
            st.warning(f"Sirf {ev['rows']} records: bharosemand numbers ke liye bahut kam (kam se kam {ev['min_rows']} recommended).")

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
    section("Academic activity", "calendar", "Record kiye sessions, marks aur system logs se")
    kpis([("Attendance sessions", str(sessions), "teachers ne record kiye", None, "calendar"),
          ("Session attendance", "–" if att is None else f"{att:.1f}%", "present ya late", None, "check"),
          ("Assessments", str(n_assess), "–" if avg_mark is None else f"average mark {avg_mark:.0f}%", None, "pencil"),
          ("Unread alerts", str(unread), "saare recipients", None, "bell"),
          ("CSV imports", str(imports_n), "Users & security mein dekhein", None, "db"),
          ("Fail ya mana hue actions", str(denied), "pichhle 7 din", RISK_COLORS["High"] if denied else None, "shield")])


def _me() -> dict:
    return st.session_state.get("user") or {}
