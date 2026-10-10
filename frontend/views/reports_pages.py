"""Reports: preview and download PDF / Excel built from stored data (permissions enforced in services.reports)."""
from __future__ import annotations

import streamlit as st

from backend.services import reports
from backend.services.access import PermissionDenied
from frontend.views.common import empty, header, kpis, section, why

SCOPE_LABELS = {"student": "Ek student", "class": "Ek class", "institution": "Poora institution"}


def reports_page():
    user = st.session_state["user"]
    header("Reports", "Database ke asli records se Attendance, Marks, Performance, AI Prediction aur Study Plan reports.")
    scopes = reports.allowed_scopes(user)
    if not scopes:
        st.error("Aapko Is Page Ko Access Karne Ki Permission Nahi Hai.")
        return
    with st.container(key="card_reportpick"):
        c1, c2 = st.columns([1.3, 1])
        rep = c1.selectbox("Report chunein", list(reports.REPORTS), format_func=reports.REPORTS.get, key="rp_report")
        scope = c2.segmented_control("Kiske liye", scopes, default=scopes[0], format_func=SCOPE_LABELS.get,
                                     key="rp_scope", required=True)
        value = None
        if scope in ("student", "class"):
            opts = reports.scope_options(user, scope)
            if not opts:
                empty("Aapke liye koi student ya class assigned nahi hai.", "users")
                return
            if user.get("role") == "student":
                value = opts[0]
                st.markdown(f'<div class="why">Sirf aapka record: <b>{value}</b></div>', unsafe_allow_html=True)
            else:
                value = st.selectbox("Student chunein" if scope == "student" else "Class chunein", opts, key=f"rp_val_{scope}")
    try:
        df, meta = reports.build(user, rep, scope, value)
    except PermissionDenied as e:
        st.error(str(e))
        return
    except Exception:
        st.error("Data Load Nahi Ho Paya. Dobara Try Karein.")
        return
    kpis([("Report", meta["title"], meta["scope"], None, "book"),
          ("Rows", str(meta["rows"]), "database se", None, "db"),
          ("Students", str(meta["students"]), "is scope mein", None, "users")])
    section("Preview", "layers", "Pehli 50 rows")
    if df.empty:
        empty("Is report ke liye database mein abhi koi data nahi hai. Download karne par file mein bhi yahi likha hoga.", "info")
    else:
        st.dataframe(df.head(50), hide_index=True)
    section("Report Download Karein", "flag")
    c1, c2 = st.columns([1, 2], vertical_alignment="bottom")
    fmt = c1.segmented_control("Format", ["pdf", "xlsx"], default="pdf", required=True, key="rp_fmt",
                               format_func={"pdf": "PDF", "xlsx": "Excel"}.get)
    key = (rep, scope, value, fmt)
    if c2.button("Report Taiyaar Karein", type="primary", icon=":material/description:", key="rp_make"):
        try:
            st.session_state["rp_file"] = (key, *reports.export(user, rep, scope, value, fmt))
        except PermissionDenied as e:
            st.error(str(e))
        except Exception:
            st.error("Report Ban Nahi Payi. Dobara Try Karein.")
    made = st.session_state.get("rp_file")
    if made and made[0] == key:
        _, data, name, mime, meta2 = made
        st.download_button("Report Download Karein", data, file_name=name, mime=mime, icon=":material/download:",
                           key="rp_download")
        why(f"{name}: {meta2['rows']} rows, {meta2['generated_at']} par bani.")
