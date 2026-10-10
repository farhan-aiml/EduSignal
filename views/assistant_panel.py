"""Floating assistant in the bottom-right corner of every page.

Closed, it is a "signal orb": a round launcher whose spinning ring takes the colour of
the selected student's risk level, plus a one-time nudge bubble built from their data.
Open, it is a compact chat window above the orb with a live gauge (predicted score vs
target), quick questions and free text.

Same rule-based engine as before (utils/assistant.py): answers are calculated from
the selected student's analysis and the trained model. It is not a generative AI
chatbot, and the window says so.
"""
from __future__ import annotations

import math

import streamlit as st

from config import RISK_COLORS
from utils.assistant import SUGGESTIONS, answer
from views import theme as theme_mod
from services import chat
from services.access import PermissionDenied
from views.common import esc

SHORT = {   # shorter chip labels; the full question is what gets asked
    "Mera predicted score kam kyun hai?": "Score kam kyun?",
    "Apni attendance kaise sudhaarun?": "Attendance sudhaarein",
    "Is hafte kis cheez par dhyaan dun?": "Is hafte ka focus",
    "Assignment marks kaise badhaaun?": "Assignments sudhaarein",
    "Kaun sa factor meri performance par sabse zyada asar daal raha hai?": "Sabse bada factor",
    "Apna academic risk kaise kam karun?": "Risk kam karein",
    "Mera current risk level kya hai?": "Mera risk level",
    "Roz kitne ghante padhna chahiye?": "Roz kitne ghante",
    "Agle test ka score kaise sudhaarun?": "Agla test",
    "Apna target score paane ke liye kya karun?": "Target paayein",
}
# EduSignal heartbeat: a signal line that keeps drawing itself in the window header
WAVE = ('<svg class="ast-wave" viewBox="0 0 120 32" aria-hidden="true">'
        '<path d="M0 18h28l6-10 8 20 8-26 7 22 5-6h58" fill="none" stroke="currentColor" stroke-width="2.4" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>')
BOTS = {"student": ":material/school:", "teacher": ":material/auto_stories:", "admin": ":material/insights:"}


def _sid():
    return (st.session_state.get("ctx") or {}).get("sid")


def _user():
    return st.session_state.get("user") or {}


def _conv_key():
    return f"conv_{_sid()}"


def _history():
    """Messages of the open conversation, read from the database (only the owner can read it)."""
    cid = st.session_state.get(_conv_key())
    if not cid:
        return []
    try:
        return chat.messages(_user(), cid)
    except PermissionDenied:
        st.session_state[_conv_key()] = None
        return []


def _ask(q: str):
    c = st.session_state.get("ctx")
    if not c or not q.strip():
        return
    target = st.session_state.get(f"assist_target_{c['sid']}")
    reply = answer(q, c["analysis"], c["bundle"], target=target, settings=c["settings"])
    try:
        cid = st.session_state.get(_conv_key()) or chat.start(_user(), c["sid"])
        chat.add_exchange(_user(), cid, q.strip(), reply)
        st.session_state[_conv_key()] = cid
    except PermissionDenied as e:
        st.session_state["assist_err"] = str(e)


def _on_chip():
    q = st.session_state.get("assist_chip")
    if q:
        _ask(q)
    st.session_state["assist_chip"] = None


def _on_chat():
    _ask(st.session_state.get("assist_input") or "")


def _toggle():
    st.session_state["assist_open"] = not st.session_state.get("assist_open")
    st.session_state["assist_seen"] = True     # the nudge is shown once per session


def _new_chat():
    st.session_state[_conv_key()] = None


def _open_chat(cid):
    st.session_state[_conv_key()] = cid


def _delete_chat(cid):
    try:
        chat.delete(_user(), cid)
    except PermissionDenied as e:
        st.session_state["assist_err"] = str(e)
    if st.session_state.get(_conv_key()) == cid:
        st.session_state[_conv_key()] = None


def _nudge(a: dict, first: str, other: str = "") -> str:
    """One proactive line, built only from the computed analysis."""
    hi = f"Hi {esc(first)}! " if first else f"<b>{esc(other)}</b>: " if other else "Hi! "
    if a["priorities"]:
        p = a["priorities"][0]
        return (f"{hi}<b>{esc(p['label'])}</b> sabse bada lever hai: <b>{p['target']:g}</b> tak pahunchne par lagbhag <b>+{p['gain']:.1f}</b> points. "
                f"Mujhse poochhein kaise.")
    if a["risk"]["level"] != "Low":
        return f"{hi}Abhi risk <b>{a['risk']['level'].lower()}</b> hai. Mujhse poochhein ise kaise kam karein."
    return f"{hi}<b>{a['prediction']:.0f}</b> par sahi raaste par hain. Poochhein agla target kaise paayein."


def _gauge(pred: float, target: float, color: str) -> str:
    """Ring gauge: arc = predicted score out of 100, tick = target."""
    r = 22
    circ = 2 * math.pi * r
    fill = max(0.0, min(pred, 100.0)) / 100 * circ
    ang = max(0.0, min(target, 100.0)) / 100 * 360 - 90
    return (f'<svg viewBox="0 0 60 60" width="56" height="56" aria-hidden="true">'
            f'<circle cx="30" cy="30" r="{r}" fill="none" stroke="var(--line)" stroke-width="6"/>'
            f'<circle cx="30" cy="30" r="{r}" fill="none" stroke="{color}" stroke-width="6" stroke-linecap="round" '
            f'stroke-dasharray="{fill:.1f} {circ:.1f}" transform="rotate(-90 30 30)"/>'
            f'<path d="M49 30h9" stroke="var(--ink)" stroke-width="2.6" stroke-linecap="round" '
            f'transform="rotate({ang:.1f} 30 30)"/>'
            f'<text x="30" y="34.5" text-anchor="middle" font-size="13" font-weight="800" fill="var(--ink)">'
            f'{pred:.0f}</text></svg>')


def render():
    c = st.session_state.get("ctx")
    if not c:
        return
    a = c["analysis"]
    level = a["risk"]["level"]
    risk_color = RISK_COLORS.get(level, "#64748B")
    name = c["info"]["name"] if c["sid"] and c["info"] else "is profile"
    role = st.session_state["user"]["role"]
    bot = BOTS.get(role, BOTS["student"])
    title, subtitle = theme_mod.ASSISTANT_NAMES.get(role, theme_mod.ASSISTANT_NAMES["student"])
    is_open = st.session_state.setdefault("assist_open", False)
    st.markdown(f"<style>:root {{ --risk: {risk_color}; }}</style>", unsafe_allow_html=True)

    # the orb stays in the corner in both states: role logo when closed, close button when open
    with st.container(key="assist_orb_open" if is_open else "assist_orb"):
        st.button("", icon=":material/close:" if is_open else bot, on_click=_toggle,
                  help="Assistant band karein" if is_open else f"{subtitle}. Chuna hua student: {level.lower()} risk.")

    if not is_open:
        if not st.session_state.get("assist_seen"):
            own = c["sid"] and st.session_state["user"].get("student_id") == c["sid"]
            first = name.split()[0] if own and c["info"] else ""
            other = "" if own else (name if c["sid"] else "Manual entry")
            st.markdown(f'<div class="ast-nudge" role="status"><span class="who">{esc(title)}</span>'
                        f'{_nudge(a, first, other)}</div>', unsafe_allow_html=True)
        return

    with st.container(key="assist_panel"):
        st.markdown(
            f'<div class="ast-head">{WAVE}<div class="ast-logo">{theme_mod.assistant_logo(role, 40)}</div><div>'
            f'<div class="ast-t">{esc(title)}</div>'
            f'<div class="ast-s"><span class="ast-live"></span>{esc(name)} ka data padh raha hoon · rule-based, '
            f'generative AI nahi</div></div></div>', unsafe_allow_html=True)
        hist = _history()
        with st.container(key="assist_clear"):
            st.button("", icon=":material/add_comment:", on_click=_new_chat, help="Nayi Baat Shuru Karein", type="tertiary",
                      key="assist_new")
        if err := st.session_state.pop("assist_err", None):
            st.error(err)
        past = chat.conversations(_user(), c["sid"])
        if not past.empty:
            with st.popover(f"Purani Baatein ({len(past)})", icon=":material/history:", width="stretch"):
                st.caption("Sirf aap apni baatein dekh sakte hain. Delete karne par hamesha ke liye hat jaati hain.")
                for r in past.head(15).itertuples():
                    c1, c2 = st.columns([4, 1], vertical_alignment="center")
                    c1.button(f"{r.title[:38]} · {r.updated_at[5:16]}", key=f"open_conv_{r.id}", on_click=_open_chat,
                              args=(r.id,), width="stretch", type="tertiary",
                              icon=":material/chat:" if r.id != st.session_state.get(_conv_key()) else ":material/radio_button_checked:")
                    c2.button("", key=f"del_conv_{r.id}", icon=":material/delete:", on_click=_delete_chat, args=(r.id,),
                              help="Yeh baatcheet delete karein")

        default_target = float(min(95, max(60, (int(a["prediction"]) // 10 + 1) * 10)))
        tkey = f"assist_target_{c['sid']}"
        target = float(st.session_state.get(tkey, default_target))
        gap = target - a["prediction"]
        status = "target poora" if gap <= 0 else f"{gap:.1f} points aur"
        with st.container(key="assist_strip", horizontal=True, vertical_alignment="center"):
            st.markdown(
                f'<div class="ast-pulse">{_gauge(a["prediction"], target, risk_color)}<div>'
                f'<div class="k">Predicted → target</div>'
                f'<div class="v">{a["prediction"]:.1f} <span>→ {target:.0f}</span></div>'
                f'<div class="g" style="color:{risk_color}">● {level} risk · {status}</div></div></div>',
                unsafe_allow_html=True)
            st.number_input("Target", 0.0, 100.0, default_target, step=1.0, format="%.0f", key=tkey, width=92)

        with st.container(height=270, key="assist_msgs", border=False):
            if not hist:
                with st.chat_message("assistant", avatar=bot):
                    st.markdown(f"Namaste! Maine {name} ke results padh liye hain: score, risk, attendance aur study plan. "
                                "Neeche koi sawaal chunein ya apna sawaal likhein.")
            for m in hist:
                with st.chat_message(m["role"], avatar=bot if m["role"] == "assistant" else None):
                    st.markdown(m["content"])

        with st.container(key="assist_chips"):
            st.pills("Quick questions", SUGGESTIONS, key="assist_chip", on_change=_on_chip,
                     format_func=lambda q: SHORT.get(q, q), label_visibility="collapsed")
        st.chat_input("Score, risk, attendance ke baare mein poochhein…", key="assist_input", on_submit=_on_chat, max_chars=300)
