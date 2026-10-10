"""Reports: preview and download PDF / Excel built from stored data (permissions enforced in services.reports)."""
from __future__ import annotations

import streamlit as st

from backend.services import reports
from backend.services.access import PermissionDenied
from frontend.views.common import empty, header, kpis, section, tone, why

SCOPE_LABELS = {"student": "One student", "class": "One class", "institution": "Whole institution"}


def reports_page():
    user = st.session_state["user"]
    header("Reports", tone("Download your progress in one tap: attendance, marks, performance, predictions and your "
                           "study plan, straight from your records.",
                           "Attendance, marks, performance, AI prediction and study-plan reports built from stored records."))
    scopes = reports.allowed_scopes(user)
    if not scopes:
        st.error("You don't have permission to access this page.")
        return
    with st.container(key="card_reportpick"):
        c1, c2 = st.columns([1.3, 1])
        rep = c1.selectbox("Report", list(reports.REPORTS), format_func=reports.REPORTS.get, key="rp_report")
        scope = c2.segmented_control("Scope", scopes, default=scopes[0], format_func=SCOPE_LABELS.get,
                                     key="rp_scope", required=True)
        value = None
        if scope in ("student", "class"):
            opts = reports.scope_options(user, scope)
            if not opts:
                empty("No students or classes are assigned to you yet.", "users")
                return
            if user.get("role") == "student":
                value = opts[0]
                st.markdown(f'<div class="why">Your own record: <b>{value}</b></div>', unsafe_allow_html=True)
            else:
                value = st.selectbox("Student" if scope == "student" else "Class", opts, key=f"rp_val_{scope}")
    try:
        df, meta = reports.build(user, rep, scope, value)
    except PermissionDenied as e:
        st.error(str(e))
        return
    except Exception:
        st.error("The data could not be loaded. Please try again.")
        return
    kpis([("Report", meta["title"], meta["scope"], None, "book"),
          ("Rows", str(meta["rows"]), "from the database", None, "db"),
          ("Students", str(meta["students"]), "in this scope", None, "users")])
    section("Preview", "layers", "First 50 rows")
    if df.empty:
        empty(tone("Nothing to report here yet. It will fill up as your teachers record attendance and marks.",
                   "There is no data for this report yet. A downloaded file will say the same."), "info")
    else:
        st.dataframe(df.head(50), hide_index=True)
    section("Download", "flag")
    c1, c2 = st.columns([1, 2], vertical_alignment="bottom")
    fmt = c1.segmented_control("Format", ["pdf", "xlsx"], default="pdf", required=True, key="rp_fmt",
                               format_func={"pdf": "PDF", "xlsx": "Excel"}.get)
    key = (rep, scope, value, fmt)
    if c2.button("Generate report", type="primary", icon=":material/description:", key="rp_make"):
        try:
            st.session_state["rp_file"] = (key, *reports.export(user, rep, scope, value, fmt))
        except PermissionDenied as e:
            st.error(str(e))
        except Exception:
            st.error("The report could not be generated. Please try again.")
    made = st.session_state.get("rp_file")
    if made and made[0] == key:
        _, data, name, mime, meta2 = made
        st.download_button("Download report", data, file_name=name, mime=mime, icon=":material/download:",
                           key="rp_download")
        why(f"{name}: {meta2['rows']} rows, generated {meta2['generated_at']}.")
