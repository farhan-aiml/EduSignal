"""Design system: one product, three distinct role identities.

Shared foundation (spacing, type scale, components, motion rules) with a signature per role:
  student  - "the study notebook": violet + coral, ruled-paper hero, handwritten maths doodles, rounded friendly cards
  teacher  - "the chalkboard":     navy + terracotta, slate chalkboard hero with chalk diagrams, serif headings, ruled cards
  admin    - "the command console": obsidian + electric cyan, live data-grid hero, dark sidebar, mono numerals

CSS is written with [[token]] placeholders (filled from THEMES) instead of f-strings, so braces stay readable.
Everything respects prefers-reduced-motion. Decorative layers never take pointer events.
"""
from __future__ import annotations

import math
from urllib.parse import quote

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

THEMES = {
    "student": {   # green: friendly, energetic, learning-focused
        "primary": "#047857", "primary2": "#10B981", "accent": "#84CC16", "accent2": "#FBBF24",
        "accent3": "#0EA5E9", "ink": "#052E1C", "muted": "#3F6B58", "line": "#C9EAD9", "soft": "#DCF7EA",
        "surface": "rgba(255,255,255,0.90)", "shadow": "4,120,87", "on_primary": "#FFFFFF",
        "bg": "radial-gradient(900px 560px at 100% -10%, rgba(16,185,129,.30) 0%, rgba(16,185,129,0) 60%),"
              "radial-gradient(800px 560px at -6% 110%, rgba(132,204,22,.26) 0%, rgba(132,204,22,0) 55%),"
              "radial-gradient(600px 400px at 55% 50%, rgba(250,204,21,.10) 0%, rgba(250,204,21,0) 60%),"
              "linear-gradient(160deg, #E8FBF2 0%, #D3F5E4 45%, #EAFBF1 100%)",
        "hero": "radial-gradient(circle at 88% 12%, rgba(250,204,21,.40) 0, transparent 30%),"
                "radial-gradient(circle at 62% 130%, rgba(132,204,22,.55) 0, transparent 42%),"
                "repeating-linear-gradient(180deg, transparent 0 31px, rgba(255,255,255,.08) 31px 32px),"
                "linear-gradient(120deg, #064E3B 0%, #047857 48%, #10B981 100%)",
        "hero_ink": "#D1FAE5", "font": "Outfit", "radius": "22px", "eyebrow": "Student portal",
        "font_url": "family=Outfit:wght@500;600;700;800&family=Caveat:wght@600",
        "colorway": ["#047857", "#84CC16", "#0EA5E9", "#FBBF24", "#10B981", "#14B8A6"],
        "side_bg": "linear-gradient(180deg, #F4FFF9 0%, #DDF7EA 100%)", "side_ink": "#052E1C",
        "side_muted": "#3F6B58", "side_active": "#C7F0DB", "side_bar": "#047857", "dark_side": False,
        "num_font": "'Outfit', 'Public Sans', sans-serif",
        # animated background: particle colours, bubble tint, object colours
        "fx": {"stars": ["#10B981", "#34D399", "#FBBF24", "#84CC16"], "bubble": "16,185,129",
               "obj": ["#047857", "#059669", "#65A30D", "#0E7490"], "blob": ["#34D399", "#A3E635", "#FDE68A"]},
    },
    "teacher": {   # red: mature, academic, mentoring-focused
        "primary": "#9F1239", "primary2": "#E11D48", "accent": "#D97706", "accent2": "#475569",
        "accent3": "#FB7185", "ink": "#3B0716", "muted": "#7A4452", "line": "#F6CFD8", "soft": "#FFE4EA",
        "surface": "rgba(255,255,255,0.92)", "shadow": "159,18,57", "on_primary": "#FFFFFF",
        "bg": "radial-gradient(900px 520px at 100% -8%, rgba(225,29,72,.22) 0%, rgba(225,29,72,0) 60%),"
              "radial-gradient(800px 560px at -6% 110%, rgba(251,113,133,.24) 0%, rgba(251,113,133,0) 55%),"
              "linear-gradient(rgba(159,18,57,0.045) 1px, transparent 1px) 0 0/28px 28px,"
              "linear-gradient(90deg, rgba(159,18,57,0.045) 1px, transparent 1px) 0 0/28px 28px,"
              "linear-gradient(160deg, #FFF1F3 0%, #FFE2E8 50%, #FFF4F5 100%)",
        "hero": "radial-gradient(circle at 85% 10%, rgba(251,191,36,.30) 0, transparent 32%),"
                "radial-gradient(ellipse at 15% 120%, rgba(251,113,133,.45) 0, transparent 45%),"
                "linear-gradient(rgba(255,255,255,.06) 1px, transparent 1px) 0 0/24px 24px,"
                "linear-gradient(90deg, rgba(255,255,255,.06) 1px, transparent 1px) 0 0/24px 24px,"
                "linear-gradient(125deg, #4C0519 0%, #881337 45%, #BE123C 100%)",
        "hero_ink": "#FFE4E6", "font": "Fraunces", "radius": "16px", "eyebrow": "Faculty workspace",
        "font_url": "family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Caveat:wght@600",
        "colorway": ["#9F1239", "#D97706", "#475569", "#FB7185", "#E11D48", "#B45309"],
        "side_bg": "linear-gradient(180deg, #FFF8F9 0%, #FFE6EC 100%)", "side_ink": "#3B0716",
        "side_muted": "#7A4452", "side_active": "#FDD5DF", "side_bar": "#BE123C", "dark_side": False,
        "num_font": "'Fraunces', Georgia, serif",
        "fx": {"stars": ["#E11D48", "#FB7185", "#F59E0B", "#FDA4AF"], "bubble": "225,29,72",
               "obj": ["#9F1239", "#BE123C", "#B45309", "#881337"], "blob": ["#FB7185", "#FDA4AF", "#FCD34D"]},
    },
    "admin": {   # gold: powerful, premium, management-focused
        "primary": "#B7791F", "primary2": "#E0A526", "accent": "#78716C", "accent2": "#F5C451",
        "accent3": "#292524", "ink": "#1C1917", "muted": "#6B5E4B", "line": "#EEDDB5", "soft": "#FDF0CF",
        "surface": "rgba(255,255,255,0.92)", "shadow": "120,85,20", "on_primary": "#1C1917",
        "bg": "radial-gradient(1000px 560px at 92% -12%, rgba(245,196,81,.40) 0%, rgba(245,196,81,0) 58%),"
              "radial-gradient(800px 520px at -8% 110%, rgba(217,160,40,.28) 0%, rgba(217,160,40,0) 55%),"
              "radial-gradient(rgba(183,121,31,.10) 1px, transparent 1.3px) 0 0/24px 24px,"
              "linear-gradient(160deg, #FFF9E8 0%, #FCEFC8 50%, #FFF8E6 100%)",
        "hero": "linear-gradient(rgba(226,178,62,.08) 1px, transparent 1px) 0 0/28px 28px,"
                "linear-gradient(90deg, rgba(226,178,62,.08) 1px, transparent 1px) 0 0/28px 28px,"
                "linear-gradient(135deg, #1C1917 0%, #292118 55%, #1A1612 100%)",
        "hero_ink": "#E9DCC0", "font": "Space Grotesk", "radius": "14px", "eyebrow": "Admin console",
        "font_url": "family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@500;700",
        "colorway": ["#B7791F", "#57534E", "#F5C451", "#7C5A14", "#A8A29E", "#D97706"],
        "side_bg": "linear-gradient(180deg, #231E1A 0%, #1C1917 60%, #141110 100%)", "side_ink": "#F3E9D6",
        "side_muted": "#B7A88C", "side_active": "rgba(226,178,62,0.16)", "side_bar": "#E2B23E", "dark_side": True,
        "num_font": "'JetBrains Mono', ui-monospace, monospace",
        "fx": {"stars": ["#E0A526", "#F5C451", "#FDE68A", "#B7791F"], "bubble": "224,165,38",
               "obj": ["#B7791F", "#92650F", "#57534E", "#D49A20"], "blob": ["#F5C451", "#FCD34D", "#E7C27A"]},
    },
}
LABELS = {"student": "Student portal", "teacher": "Faculty workspace", "admin": "Admin console"}


def theme(role: str | None = None) -> dict:
    if role is None:
        user = st.session_state.get("user")
        role = user["role"] if user else st.session_state.get("login_role", "student")
    return THEMES.get(role, THEMES["student"])


def current_role() -> str:
    user = st.session_state.get("user")
    return user["role"] if user else st.session_state.get("login_role", "student") or "student"


# ---------------- icons (24px stroke icons) ----------------
_I = {
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.4"/>',
    "alert": '<path d="M12 3.5 21.5 20h-19z"/><path d="M12 10v4.5"/><path d="M12 17.2v.1"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/><path d="m9 15 2 2 4-4"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>',
    "trend": '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6.2 6.5-6.2s6.5 2.6 6.5 6.2"/><circle cx="17.5" cy="9" r="2.5"/><path d="M16.5 14c2.8 0 5 2.1 5 5"/>',
    "book": '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5V5.5M20 18v3H6.5"/>',
    "shield": '<path d="M12 3 20 6v6c0 5-3.5 8.2-8 9.2C7.5 20.2 4 17 4 12V6z"/><path d="m8.8 12 2.2 2.2 4.2-4.4"/>',
    "db": '<ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "chip": '<rect x="6" y="6" width="12" height="12" rx="2.5"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"/>',
    "cap": '<path d="M2 9.5 12 4.5l10 5-10 5z"/><path d="M6 11.5V16c0 1.5 2.7 3 6 3s6-1.5 6-3v-4.5"/><path d="M22 9.5V15"/>',
    "flag": '<path d="M5 21V4h11.5L15 8l1.5 4H5"/>',
    "spark": '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>',
    "bell": '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "pencil": '<path d="M4 20l1.2-4.6L16.5 4.1a2 2 0 0 1 2.8 0l.6.6a2 2 0 0 1 0 2.8L8.6 18.8z"/><path d="M14.5 6l3.5 3.5"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M21.5 20h-19"/>',
    "gauge": '<path d="M4 17a8 8 0 1 1 16 0"/><path d="m12 17 4-6"/><circle cx="12" cy="17" r="1.3"/>',
    "brain": '<path d="M9 4.5a3 3 0 0 0-3 3 3 3 0 0 0-2 5.2A3 3 0 0 0 7 18a3 3 0 0 0 5 1.5V6a2.5 2.5 0 0 0-3-1.5z"/><path d="M15 4.5a3 3 0 0 1 3 3 3 3 0 0 1 2 5.2A3 3 0 0 1 17 18a3 3 0 0 1-5 1.5"/>',
    "compass": '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.1"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12.2 2.8 2.8L16 9.6"/>',
}


def icon(name: str, size: int = 20, color: str = "currentColor", width: float = 1.8) -> str:
    return (f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'{_I.get(name, _I["spark"])}</svg>')


def icon_for(label: str) -> str:
    l = label.lower()
    for keys, name in [(("risk",), "alert"), (("attendance", "classes", "gap"), "calendar"),
                       (("hour", "time", "minute", "today"), "clock"), (("trend", "change"), "trend"),
                       (("student", "users"), "users"), (("grade",), "cap"), (("model",), "chip"),
                       (("rows", "records", "column", "duplicate", "missing"), "db"),
                       (("intervention",), "flag"), (("subject", "priorit", "plan"), "book"),
                       (("correlation", "r²", "mae", "rmse"), "chart"),
                       (("score", "prediction", "predicted"), "target")]:
        if any(k in l for k in keys):
            return name
    return "spark"


# ---------------- assistant logos (one per role) ----------------
def assistant_logo(role: str, size: int = 64) -> str:
    """Role-specific assistant mark. Teacher: 'Mentor' - open book, graduation cap and a
    neural constellation above it (education + teaching + intelligence)."""
    if role == "teacher":
        return (f'<svg viewBox="0 0 64 64" width="{size}" height="{size}" aria-hidden="true">'
                # neural constellation (intelligence)
                '<path d="M14 15 24 9l8 5 8-5 10 6" fill="none" stroke="#F4B183" stroke-width="1.6" opacity=".9"/>'
                '<path d="M24 9v-.5M32 14v6M40 9" stroke="#F4B183" stroke-width="1.6"/>'
                '<circle cx="14" cy="15" r="2.4" fill="#F4B183"/><circle cx="24" cy="9" r="2.4" fill="#FFFFFF"/>'
                '<circle cx="32" cy="14" r="3" fill="#FFD7BF"/><circle cx="40" cy="9" r="2.4" fill="#FFFFFF"/>'
                '<circle cx="50" cy="15" r="2.4" fill="#F4B183"/>'
                # graduation cap (teaching)
                '<path d="M32 20 50 27.5 32 35 14 27.5z" fill="#FFFFFF"/>'
                '<path d="M21 31v5c0 2.6 5 4.6 11 4.6s11-2 11-4.6v-5L32 35.5z" fill="#E5ECF7"/>'
                '<path d="M32 27.5 45 30v7" stroke="#F4B183" stroke-width="1.8" fill="none" stroke-linecap="round"/>'
                '<circle cx="45" cy="38.5" r="2" fill="#F4B183"/>'
                # open book (knowledge)
                '<path d="M32 46c-5-3.6-12-4-19-2.4v11c7-1.6 14-1.2 19 2.4z" fill="#FFFFFF" opacity=".95"/>'
                '<path d="M32 46c5-3.6 12-4 19-2.4v11c-7-1.6-14-1.2-19 2.4z" fill="#DCE5F3"/>'
                '<path d="M17 47.5c3.5-.6 7-.3 10 .9M17 51c3.5-.6 7-.3 10 .9M37 48.4c3-1.2 6.5-1.5 10-.9" '
                'stroke="#9FB2CE" stroke-width="1.2" fill="none" stroke-linecap="round"/></svg>')
    if role == "admin":
        return (f'<svg viewBox="0 0 64 64" width="{size}" height="{size}" aria-hidden="true">'
                '<path d="M32 6 54 18.5v27L32 58 10 45.5v-27z" fill="none" stroke="#F5C451" stroke-width="2.2"/>'
                '<rect x="20" y="34" width="5" height="11" rx="1.5" fill="#FFFFFF" opacity=".6"/>'
                '<rect x="29.5" y="27" width="5" height="18" rx="1.5" fill="#FFFFFF" opacity=".85"/>'
                '<rect x="39" y="21" width="5" height="24" rx="1.5" fill="#FFFFFF"/>'
                '<path d="M18 30 27 23l7 4 11-9" fill="none" stroke="#FDE68A" stroke-width="2" stroke-linecap="round"/>'
                '<circle cx="45" cy="18" r="2.6" fill="#FDE68A"/></svg>')
    return (f'<svg viewBox="0 0 64 64" width="{size}" height="{size}" aria-hidden="true">'   # student: cap + idea spark
            '<path d="M32 14 54 24 32 34 10 24z" fill="#FFFFFF"/>'
            '<path d="M19 28.5v8c0 3.4 5.8 6.2 13 6.2s13-2.8 13-6.2v-8L32 34.5z" fill="#EDE6FF"/>'
            '<path d="M32 24 49 27v10" stroke="#FFC46B" stroke-width="2" fill="none" stroke-linecap="round"/>'
            '<circle cx="49" cy="39.5" r="2.4" fill="#FFC46B"/>'
            '<path d="M16 48c4 2 8 2.6 12 1.6M36 49.6c4 1 8 .4 12-1.6" stroke="#FFFFFF" stroke-width="2" '
            'fill="none" stroke-linecap="round" opacity=".7"/>'
            '<path d="M50 6l1.4 3.6L55 11l-3.6 1.4L50 16l-1.4-3.6L45 11l3.6-1.4z" fill="#FFC46B"/></svg>')


ASSISTANT_NAMES = {"student": ("Study Coach", "Your EduSignal study assistant"),
                   "teacher": ("Mentor Assist", "Teacher's EduSignal assistant"),
                   "admin": ("Insight Desk", "EduSignal admin assistant")}


def svg_data_uri(svg: str) -> str:
    return "data:image/svg+xml;utf8," + quote(svg.replace(' aria-hidden="true"', ' xmlns="http://www.w3.org/2000/svg"'))


# ---------------- floating decor ----------------
def _formula(text, color, size=22, font="Caveat"):
    return (f'<span style="font-family:\'{font}\',cursive;font-size:{size}px;color:{color};white-space:nowrap;'
            f'font-weight:600">{text}</span>')


def _cap(fill="#1E1B3A", tassel="#F5A524", w=74):
    return (f'<svg viewBox="0 0 90 66" width="{w}" height="{w * 66 // 90}"><path d="M45 6 86 24 45 42 4 24z" fill="{fill}"/>'
            f'<path d="M20 31v14c0 6 11 12 25 12s25-6 25-12V31L45 42z" fill="{fill}" opacity=".82"/>'
            f'<path d="M45 24 74 28v20" stroke="{tassel}" stroke-width="2.6" fill="none" stroke-linecap="round"/>'
            f'<circle cx="74" cy="51" r="4" fill="{tassel}"/></svg>')


def _books(c1, c2, c3, w=86):
    return (f'<svg viewBox="0 0 90 70" width="{w}" height="{w * 70 // 90}"><rect x="8" y="48" width="72" height="14" rx="3" fill="{c1}"/>'
            f'<rect x="14" y="34" width="64" height="14" rx="3" fill="{c2}"/><rect x="6" y="20" width="68" height="14" rx="3" fill="{c3}"/>'
            '<path d="M14 55h56M20 41h50M12 27h54" stroke="rgba(255,255,255,.55)" stroke-width="2"/></svg>')


def _notebook(c):
    return (f'<svg viewBox="0 0 80 96" width="66" height="80"><rect x="10" y="4" width="64" height="88" rx="8" fill="#FFFFFF" stroke="{c}" stroke-width="2"/>'
            f'<path d="M24 4v88" stroke="#F2665A" stroke-width="1.6" opacity=".7"/>'
            f'<path d="M30 24h34M30 36h34M30 48h28M30 60h34M30 72h20" stroke="{c}" stroke-width="2" opacity=".3" stroke-linecap="round"/>'
            + "".join(f'<circle cx="10" cy="{y}" r="3.4" fill="#FFFFFF" stroke="{c}" stroke-width="2"/>' for y in (16, 34, 52, 70, 86))
            + '</svg>')


def _pencil():
    return ('<svg viewBox="0 0 120 24" width="108" height="22"><rect x="18" y="4" width="78" height="16" rx="2" fill="#F5A524"/>'
            '<rect x="18" y="4" width="78" height="5" fill="#FFC46B"/><rect x="96" y="4" width="14" height="16" rx="3" fill="#F2665A"/>'
            '<rect x="92" y="4" width="5" height="16" fill="#CBD5E1"/><path d="M18 4 2 12l16 8z" fill="#F4D7B5"/>'
            '<path d="M7 9.5 2 12l5 2.5z" fill="#1E1B3A"/></svg>')


def _protractor(c):
    ticks = "".join(f'<path d="M{50 + 38 * math.cos(a):.1f} {50 - 38 * math.sin(a):.1f} '
                    f'L{50 + 44 * math.cos(a):.1f} {50 - 44 * math.sin(a):.1f}" stroke="{c}" stroke-width="1.4"/>'
                    for a in [i * 3.14159 / 12 for i in range(13)])
    return (f'<svg viewBox="0 0 100 56" width="110" height="62"><path d="M4 50a46 46 0 0 1 92 0z" fill="none" stroke="{c}" stroke-width="2"/>'
            f'<path d="M24 50a26 26 0 0 1 52 0" fill="none" stroke="{c}" stroke-width="1.4"/>{ticks}</svg>')


def _compass(c):
    return (f'<svg viewBox="0 0 60 70" width="46" height="54"><circle cx="30" cy="9" r="6" fill="none" stroke="{c}" stroke-width="2.2"/>'
            f'<path d="M27 14 10 64M33 14l17 50" stroke="{c}" stroke-width="2.6" stroke-linecap="round"/>'
            f'<path d="M18 42h24" stroke="{c}" stroke-width="2"/></svg>')


def _mini_chart(c, c2):
    return (f'<svg viewBox="0 0 120 80" width="120" height="80"><rect x="1" y="1" width="118" height="78" rx="12" fill="none" stroke="{c}" stroke-width="1.6"/>'
            f'<rect x="16" y="46" width="12" height="20" rx="3" fill="{c}" opacity=".5"/><rect x="36" y="34" width="12" height="32" rx="3" fill="{c}" opacity=".7"/>'
            f'<rect x="56" y="24" width="12" height="42" rx="3" fill="{c}"/><path d="M80 56 92 40l10 6 10-22" stroke="{c2}" stroke-width="2.4" fill="none" stroke-linecap="round"/></svg>')


def _donut(c, c2):
    return (f'<svg viewBox="0 0 80 80" width="74" height="74"><circle cx="40" cy="40" r="28" fill="none" stroke="{c}" stroke-opacity=".25" stroke-width="10"/>'
            f'<circle cx="40" cy="40" r="28" fill="none" stroke="{c2}" stroke-width="10" stroke-dasharray="120 176" transform="rotate(-90 40 40)" stroke-linecap="round"/></svg>')


def _nodes(c):
    pts = [(10, 40), (40, 12), (70, 34), (50, 66), (90, 60)]
    lines = "".join(f'<path d="M{a[0]} {a[1]}L{b[0]} {b[1]}" stroke="{c}" stroke-width="1.4" opacity=".6"/>'
                    for a, b in [(pts[0], pts[1]), (pts[1], pts[2]), (pts[2], pts[3]), (pts[0], pts[3]), (pts[2], pts[4]), (pts[3], pts[4])])
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="4" fill="{c}"/>' for x, y in pts)
    return f'<svg viewBox="0 0 100 76" width="100" height="76">{lines}{dots}</svg>'


def _ruler(c, w=120):
    ticks = "".join(f'<path d="M{8 + i * 8} 3v{9 if i % 5 == 0 else 5}" stroke="#FFFFFF" stroke-width="1.4" opacity=".85"/>'
                    for i in range(14))
    return (f'<svg viewBox="0 0 124 26" width="{w}" height="{w * 26 // 124}"><rect x="1" y="1" width="122" height="24" rx="4" '
            f'fill="{c}"/>{ticks}</svg>')


def _calculator(c, w=54):
    keys = "".join(f'<rect x="{10 + (i % 3) * 13}" y="{30 + (i // 3) * 12}" width="9" height="8" rx="2" fill="#FFFFFF" opacity=".8"/>'
                   for i in range(9))
    return (f'<svg viewBox="0 0 56 70" width="{w}" height="{w * 70 // 56}"><rect x="3" y="3" width="50" height="64" rx="9" fill="{c}"/>'
            f'<rect x="9" y="9" width="38" height="14" rx="3" fill="#FFFFFF" opacity=".9"/>'
            f'<path d="M30 16h12" stroke="{c}" stroke-width="2.4" stroke-linecap="round"/>{keys}</svg>')


def _pen(c, w=96):
    return (f'<svg viewBox="0 0 110 20" width="{w}" height="{w * 20 // 110}"><rect x="16" y="4" width="78" height="12" rx="6" fill="{c}"/>'
            f'<rect x="80" y="2" width="4" height="16" rx="2" fill="#FFFFFF" opacity=".7"/><path d="M16 4 2 10l14 6z" fill="#E7E5E4"/>'
            f'<path d="M6 8.4 2 10l4 1.6z" fill="#1C1917"/><rect x="94" y="5" width="12" height="10" rx="3" fill="{c}" opacity=".7"/></svg>')


def _open_book(c, w=78):
    return (f'<svg viewBox="0 0 90 60" width="{w}" height="{w * 60 // 90}"><path d="M45 10C35 3 18 3 5 7v46c13-4 30-4 40 3z" fill="{c}"/>'
            f'<path d="M45 10c10-7 27-7 40-3v46c-13-4-30-4-40 3z" fill="{c}" opacity=".8"/>'
            '<path d="M45 12c-9-5-22-5-34-2v38c12-3 25-3 34 2zM45 12c9-5 22-5 34-2v38c-12-3-25-3-34 2z" fill="#FFFFFF" opacity=".92"/>'
            f'<path d="M17 20h20M17 27h20M17 34h14M53 20h20M53 27h20M53 34h12" stroke="{c}" stroke-width="2" opacity=".35" stroke-linecap="round"/></svg>')


def _gear(c, w=56):
    teeth = "".join(f'<rect x="27" y="2" width="8" height="12" rx="2" fill="{c}" transform="rotate({a} 31 31)"/>' for a in range(0, 360, 45))
    return (f'<svg viewBox="0 0 62 62" width="{w}" height="{w}">{teeth}<circle cx="31" cy="31" r="19" fill="{c}"/>'
            f'<circle cx="31" cy="31" r="8" fill="#FFFFFF" opacity=".85"/></svg>')


def _hex(c, w=60):
    return (f'<svg viewBox="0 0 60 60" width="{w}" height="{w}"><path d="M30 3 54 16v28L30 57 6 44V16z" fill="none" '
            f'stroke="{c}" stroke-width="2.4"/><path d="M30 15 43 22.5v15L30 45 17 37.5v-15z" fill="{c}" opacity=".35"/></svg>')


def _star_svg(c, w=22):
    return (f'<svg viewBox="0 0 24 24" width="{w}" height="{w}"><path d="M12 1.5l2.4 7.1 7.1 2.4-7.1 2.4L12 22.5l-2.4-9.1L2.5 11l7.1-2.4z" '
            f'fill="{c}"/></svg>')


FX_SYMBOLS = {"student": ["π", "Σ", "√x", "∞", "a²+b²", "÷", "x²", "∫", "%", "+"],
              "teacher": ["A+", "f(x)", "Δ", "∫", "✓", "x̄", "∑", "≈", "¶", "?"],
              "admin": ["%", "Σ", "↑", "∆", "#", "≥", "∞", "×", "$", "μ"]}


def _fx_objects(role: str, c: dict) -> list[str]:
    o = c["fx"]["obj"]
    if role == "student":
        return [_pencil(), _ruler(o[0]), _calculator(o[1]), _cap(o[0], c["accent2"], 70), _books(o[0], c["accent"], c["accent3"], 76),
                _protractor(o[2]), _open_book(o[1]), _notebook(o[0]), _compass(o[3]), _star_svg(c["accent2"], 26)]
    if role == "teacher":
        return [_open_book(o[0]), _pen(o[1]), _ruler(o[2]), _cap(o[3], c["accent"], 66), _compass(o[0]),
                _books(o[0], c["accent"], c["accent2"], 72), _protractor(o[1]), _calculator(o[3]), _pencil(), _star_svg(c["accent"], 24)]
    return [_mini_chart(o[0], o[3]), _donut(o[2], o[0]), _hex(o[0]), _gear(o[1]), _nodes(o[0]), _calculator(o[2]),
            _hex(o[3], 44), _gear(o[3], 40), _mini_chart(o[1], o[0]), _star_svg(o[3], 24)]


def decor_html(role: str) -> str:
    """Animated, lightweight background: drifting gradient blobs, twinkling glow stars, rising bubbles and drops,
    and educational objects wandering slowly. CSS-only (transform/opacity), seeded so the markup is identical on
    every rerun (animations never restart), never takes clicks, and stops under prefers-reduced-motion."""
    import random
    c = THEMES[role]
    fx = c["fx"]
    rnd = random.Random(f"edusignal-{role}")
    x = lambda lo=0.0, hi=96.0: f"calc(var(--sbw) + (100vw - var(--sbw)) * {rnd.uniform(lo, hi) / 100:.3f})"
    parts = []
    for i, col in enumerate(fx["blob"]):   # soft gradient shapes
        size = rnd.randint(320, 520)
        parts.append(f'<div class="fx-blob" style="left:{x(0, 80)};top:{rnd.uniform(-10, 70):.0f}%;width:{size}px;height:{size}px;'
                     f'background:radial-gradient(circle, {col} 0%, transparent 65%);animation-duration:{rnd.randint(26, 40)}s;'
                     f'animation-delay:-{rnd.randint(0, 20)}s"></div>')
    for i in range(34):   # glowing stars / particles
        col = rnd.choice(fx["stars"])
        s = rnd.choice([3, 3, 4, 4, 5, 6])
        star = i % 6 == 0
        inner = _star_svg(col, s * 3) if star else ""
        style = (f"left:{x()};top:{rnd.uniform(2, 96):.1f}%;--g:{col};--tw:{rnd.uniform(2.5, 6):.1f}s;"
                 f"--dr:{rnd.randint(16, 34)}s;--dx:{rnd.randint(-40, 40)}px;--dy:{rnd.randint(-50, -10)}px;"
                 f"animation-delay:-{rnd.uniform(0, 8):.1f}s, -{rnd.uniform(0, 30):.1f}s")
        if not star:
            style += f";width:{s}px;height:{s}px"
        parts.append(f'<i class="fx-p{" fx-star" if star else ""}" style="{style}">{inner}</i>')
    for i in range(14):   # rising bubbles and water drops
        s = rnd.randint(10, 46)
        drop = i % 4 == 3
        parts.append(f'<i class="fx-b{" fx-drop" if drop else ""}" style="left:{x(2, 94)};width:{s}px;height:{s}px;--bc:{fx["bubble"]};'
                     f'--d:{rnd.randint(18, 38)}s;--sx:{rnd.randint(-60, 60)}px;--o:{rnd.uniform(.35, .75):.2f};'
                     f'animation-delay:-{rnd.uniform(0, 38):.1f}s, -{rnd.uniform(0, 6):.1f}s"></i>')
    objs = _fx_objects(role, c)
    symbols = FX_SYMBOLS[role]
    for i, svg in enumerate(objs):   # educational objects wandering slowly
        parts.append(f'<div class="fx-o w{i % 4 + 1}" style="left:{x(0, 88)};top:{rnd.uniform(4, 84):.0f}%;'
                     f'--r0:{rnd.randint(-25, 25)}deg;animation-duration:{rnd.randint(38, 70)}s;'
                     f'animation-delay:-{rnd.randint(0, 60)}s">{svg}</div>')
    for i, sym in enumerate(symbols):   # mathematical symbols
        col = rnd.choice(fx["obj"])
        parts.append(f'<div class="fx-o fx-sym w{(i + 2) % 4 + 1}" style="left:{x(0, 92)};top:{rnd.uniform(4, 90):.0f}%;'
                     f'color:{col};font-size:{rnd.randint(20, 36)}px;--r0:{rnd.randint(-20, 20)}deg;'
                     f'animation-duration:{rnd.randint(34, 60)}s;animation-delay:-{rnd.randint(0, 50)}s">{sym}</div>')
    return f'<div class="decor fx fx-{role}" aria-hidden="true">{"".join(parts)}</div>'


# ---------------- CSS ----------------
BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?[[font_url]]&display=swap');
:root { --p: [[primary]]; --p2: [[primary2]]; --a: [[accent]]; --a2: [[accent2]]; --a3: [[accent3]];
  --ink: [[ink]]; --muted: [[muted]]; --line: [[line]]; --soft: [[soft]]; --surface: [[surface]];
  --sr: [[shadow]]; --onp: [[on_primary]]; --rad: [[radius]]; --hf: [[head_font]]; --nf: [[num_font]]; --sbw: 0px;
  --ok: #059669; --warn: #D97706; --bad: #DC2626; }
@media (min-width: 992px) { :root { --sbw: 300px; } }

.stApp { background: [[bg]]; background-attachment: fixed; color: var(--ink); }
[data-testid="stHeader"] { background: transparent; }
.block-container { position: relative; z-index: 1; padding-top: 2rem; padding-bottom: 7rem; max-width: 1240px; }
h1, h2, h3, .hero h1, .kcard .v, .wi-num { font-family: var(--hf); }
h2, h3 { color: var(--ink); letter-spacing: -0.01em; }
h3 { font-size: 1.22rem !important; }
.why { color: var(--muted); font-size: .86rem; }
.sect { display: flex; align-items: center; gap: 10px; margin: 1.6rem 0 .7rem; }
.sect .ic { width: 34px; height: 34px; border-radius: 11px; display: grid; place-items: center; color: var(--p);
  background: var(--soft); flex: none; }
.sect h3 { margin: 0; padding: 0; }
.sect .sub { color: var(--muted); font-size: .84rem; margin-left: auto; }

/* animated background (all CSS, transform/opacity only) */
.decor { position: fixed; inset: 0; z-index: -1; pointer-events: none; overflow: hidden; contain: strict; }
.decor .fl { position: fixed; animation: float 12s ease-in-out infinite; transform: rotate(var(--r)); }
@keyframes float { 0%, 100% { transform: translate3d(0,0,0) rotate(var(--r)); }
  50% { transform: translate3d(0,-14px,0) rotate(calc(var(--r) + 4deg)); } }
@keyframes rise { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(52,211,153,.6); } 70% { box-shadow: 0 0 0 9px rgba(52,211,153,0); } 100% { box-shadow: 0 0 0 0 rgba(52,211,153,0); } }
.fx-blob { position: absolute; border-radius: 50%; opacity: .55; filter: blur(30px); will-change: transform;
  animation: blob 30s ease-in-out infinite alternate; }
@keyframes blob { 0% { transform: translate(0,0) scale(1); } 50% { transform: translate(8vw,-6vh) scale(1.18); }
  100% { transform: translate(-6vw,5vh) scale(.92); } }
.fx-p { position: absolute; display: block; border-radius: 50%; background: var(--g);
  box-shadow: 0 0 6px 1px var(--g), 0 0 14px 2px color-mix(in srgb, var(--g) 55%, transparent);
  animation: twinkle var(--tw) ease-in-out infinite, drift var(--dr) ease-in-out infinite alternate; will-change: transform, opacity; }
.fx-p.fx-star { background: none; box-shadow: none; filter: drop-shadow(0 0 5px var(--g)); }
.fx-p.fx-star svg { display: block; }
@keyframes twinkle { 0%, 100% { opacity: .2; scale: .65; } 50% { opacity: 1; scale: 1.15; } }
@keyframes drift { from { translate: 0 0; } to { translate: var(--dx) var(--dy); } }
.fx-b { position: absolute; bottom: -60px; display: block; border-radius: 50%; opacity: 0;
  background: radial-gradient(circle at 32% 28%, rgba(255,255,255,.95) 0 9%, rgba(255,255,255,.35) 10% 22%,
    rgba(var(--bc), .18) 45%, rgba(var(--bc), .32) 100%);
  border: 1px solid rgba(255,255,255,.7); box-shadow: inset 0 -3px 8px rgba(var(--bc), .25), 0 4px 14px rgba(var(--bc), .18);
  animation: bubble var(--d) linear infinite, sway 6s ease-in-out infinite alternate; will-change: transform, opacity; }
.fx-b.fx-drop { border-radius: 50% 50% 50% 0; rotate: -45deg; }
@keyframes bubble { 0% { transform: translateY(0); opacity: 0; } 8% { opacity: var(--o); } 88% { opacity: var(--o); }
  100% { transform: translateY(-115vh); opacity: 0; } }
@keyframes sway { from { translate: 0 0; } to { translate: var(--sx) 0; } }
.fx-o { position: absolute; opacity: .3; will-change: transform; rotate: var(--r0); animation-timing-function: ease-in-out;
  animation-iteration-count: infinite; filter: drop-shadow(0 6px 10px rgba(0,0,0,.08)); }
.fx-o svg { display: block; }
.fx-sym { font-family: 'Caveat', 'Outfit', cursive; font-weight: 600; line-height: 1; opacity: .38; }
.fx-admin .fx-sym { font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 18px !important; }
.fx-o.w1 { animation-name: wander1; } .fx-o.w2 { animation-name: wander2; } .fx-o.w3 { animation-name: wander3; } .fx-o.w4 { animation-name: wander4; }
@keyframes wander1 { 0%, 100% { transform: translate(0,0) rotate(0deg); } 25% { transform: translate(5vw,-6vh) rotate(9deg); }
  50% { transform: translate(9vw,2vh) rotate(-4deg); } 75% { transform: translate(3vw,7vh) rotate(6deg); } }
@keyframes wander2 { 0%, 100% { transform: translate(0,0) rotate(0deg); } 25% { transform: translate(-6vw,5vh) rotate(-8deg); }
  50% { transform: translate(-2vw,11vh) rotate(5deg); } 75% { transform: translate(4vw,4vh) rotate(-6deg); } }
@keyframes wander3 { 0%, 100% { transform: translate(0,0) rotate(0deg); } 33% { transform: translate(7vw,8vh) rotate(12deg); }
  66% { transform: translate(-4vw,4vh) rotate(-7deg); } }
@keyframes wander4 { 0%, 100% { transform: translate(0,0) rotate(0deg); } 33% { transform: translate(-5vw,-7vh) rotate(-10deg); }
  66% { transform: translate(6vw,-3vh) rotate(8deg); } }
.fx-admin .fx-o { opacity: .28; }
.fx-admin .fx-b { border-color: rgba(255,255,255,.55); }
@media (max-width: 1100px) { .fx-o:nth-of-type(n+6), .fx-p:nth-of-type(n+24) { display: none; } }
@media (max-width: 700px) { .decor .fx-o { opacity: .18; } .fx-b:nth-of-type(n+8) { display: none; } .fx-blob { opacity: .4; } }

/* hero */
.hero { position: relative; overflow: hidden; border-radius: calc(var(--rad) + 4px); margin: 0 0 1.1rem; padding: 26px 32px;
  background: [[hero]]; color: #FFFFFF; box-shadow: 0 22px 44px -26px rgba(var(--sr), .7);
  animation: rise .5s cubic-bezier(.2,.8,.2,1) both; }
.hero .in { position: relative; z-index: 1; display: flex; gap: 22px; align-items: center; justify-content: space-between; }
.hero .eyebrow { display: inline-flex; align-items: center; gap: 8px; font-size: .74rem; font-weight: 700; letter-spacing: .12em;
  text-transform: uppercase; color: [[hero_ink]]; opacity: .9; margin-bottom: 6px; }
.hero .eyebrow i { width: 18px; height: 2px; background: currentColor; display: inline-block; border-radius: 2px; }
.hero h1 { color: #FFFFFF; font-size: 2.05rem; line-height: 1.12; margin: 0 0 6px; padding: 0; font-weight: 700; letter-spacing: -0.02em; }
.hero .lede { color: [[hero_ink]]; font-size: 1rem; margin: 0; max-width: 64ch; }
.hero .art { flex: none; }
.hero .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.hero .chip { display: inline-flex; align-items: center; gap: 7px; padding: 5px 12px; border-radius: 999px;
  background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.16); color: #E2E8F0; font-size: .8rem; }
.chip .dot { width: 8px; height: 8px; border-radius: 50%; background: #34D399; animation: pulse 2.2s infinite; }
.chip .dot.off { background: #F59E0B; animation: none; }
.context { color: var(--muted); font-size: .9rem; margin: -.1rem 0 1rem; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.context b { color: var(--ink); }
.context .av { width: 30px; height: 30px; border-radius: 10px; display: grid; place-items: center; color: #FFFFFF; font-weight: 800;
  font-size: .78rem; background: linear-gradient(135deg, var(--p), var(--p2)); }
.context .pill { padding: 2px 10px; border-radius: 999px; background: var(--soft); color: var(--p); font-weight: 600; font-size: .8rem; }

/* KPI cards */
.kgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: .2rem 0 1.2rem; }
.kcard { position: relative; background: var(--surface); border: 1px solid var(--line); border-radius: var(--rad);
  padding: 15px 17px 13px; box-shadow: 0 1px 2px rgba(var(--sr), .05), 0 12px 26px -20px rgba(var(--sr), .45); overflow: hidden;
  animation: rise .45s cubic-bezier(.2,.8,.2,1) both; transition: transform .2s ease, box-shadow .2s ease; }
.kcard:nth-child(2) { animation-delay: .04s; } .kcard:nth-child(3) { animation-delay: .08s; }
.kcard:nth-child(4) { animation-delay: .12s; } .kcard:nth-child(5) { animation-delay: .16s; } .kcard:nth-child(6) { animation-delay: .2s; }
.kcard:hover { transform: translateY(-2px); box-shadow: 0 18px 32px -18px rgba(var(--sr), .5); }
.kcard .ic { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; margin-bottom: 10px;
  color: var(--kc, var(--p)); background: color-mix(in srgb, var(--kc, var(--p)) 12%, #FFFFFF); }
.kcard .l { color: var(--muted); font-size: .8rem; font-weight: 500; }
.kcard .v { font-size: 1.7rem; font-weight: 700; line-height: 1.2; font-variant-numeric: tabular-nums; color: var(--vc, var(--ink));
  font-family: var(--nf); letter-spacing: -.01em; }
.kcard .v.sm { font-size: 1.12rem; line-height: 1.5; font-family: var(--hf); }
.kcard .s { color: var(--muted); font-size: .76rem; }

/* risk banner */
.risk { position: relative; border-radius: var(--rad); padding: 16px 20px 14px 26px; margin: .2rem 0 1rem; overflow: hidden;
  background: color-mix(in srgb, var(--rc) 7%, #FFFFFF); border: 1px solid color-mix(in srgb, var(--rc) 25%, #FFFFFF);
  animation: rise .5s .1s cubic-bezier(.2,.8,.2,1) both; }
.risk::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 6px; background: var(--rc); }
.risk .title { display: flex; align-items: center; gap: 10px; font-size: 1.25rem; font-weight: 700; color: var(--rc); font-family: var(--hf); }
.risk .pulse { width: 11px; height: 11px; border-radius: 50%; background: var(--rc); position: relative; }
.risk .pulse.on::after { content: ""; position: absolute; inset: -6px; border-radius: 50%; border: 2px solid var(--rc); animation: ring 1.8s ease-out infinite; }
@keyframes ring { from { transform: scale(.5); opacity: .9; } to { transform: scale(1.6); opacity: 0; } }
.risk .body { color: var(--ink); max-width: 78ch; margin-top: 2px; }
.risk .meta { color: var(--muted); font-size: .84rem; margin-top: 4px; }
.factor { display: flex; gap: 10px; align-items: flex-start; padding: 9px 0; border-top: 1px dashed var(--line); font-size: .92rem; }
.factor:first-of-type { border-top: 0; }
.factor .pts { flex: none; min-width: 42px; text-align: center; padding: 1px 8px; border-radius: 999px; font-weight: 700; font-size: .78rem;
  color: var(--rc, var(--bad)); background: color-mix(in srgb, var(--rc, var(--bad)) 11%, #FFFFFF); font-variant-numeric: tabular-nums; }
.factor b { color: var(--ink); }

/* containers used as cards */
[class*="st-key-card"] { background: var(--surface); border: 1px solid var(--line) !important; border-radius: var(--rad);
  padding: 16px 18px; box-shadow: 0 1px 2px rgba(var(--sr), .05), 0 12px 28px -22px rgba(var(--sr), .5); }
[class*="st-key-card_hover"], [class*="st-key-act"] { transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease; }
[class*="st-key-card_hover"]:hover, [class*="st-key-act"]:hover { transform: translateY(-2px);
  box-shadow: 0 20px 34px -20px rgba(var(--sr), .55); border-color: color-mix(in srgb, var(--p) 35%, var(--line)) !important; }
[class*="st-key-act"] { background: var(--surface); border: 1px solid var(--line); border-radius: var(--rad); padding: 14px 16px 8px 20px;
  position: relative; box-shadow: 0 12px 26px -22px rgba(var(--sr), .5); height: 100%; }
[class*="st-key-act"]::before { content: ""; position: absolute; left: 0; top: 14px; bottom: 14px; width: 4px; border-radius: 0 4px 4px 0;
  background: linear-gradient(180deg, var(--p), var(--a)); }
.acat { display: inline-flex; align-items: center; gap: 6px; color: var(--p); font-weight: 700; font-size: .8rem;
  text-transform: uppercase; letter-spacing: .06em; }
[class*="st-key-reg"] { background: var(--surface); border: 1px solid var(--line); border-left: 0; border-radius: 4px var(--rad) var(--rad) 4px;
  padding: 14px 18px 12px 26px; position: relative; box-shadow: 0 12px 26px -22px rgba(var(--sr), .5); }
[class*="st-key-reg"]::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 8px;
  background: repeating-linear-gradient(180deg, var(--p) 0 2px, transparent 2px 9px), var(--soft); }

/* pills, tags, chips */
.tagrow { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 2px; }
.tag2 { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; font-size: .8rem; font-weight: 600;
  background: var(--soft); color: var(--p); border: 1px solid color-mix(in srgb, var(--p) 18%, transparent); }
.tag2.ok { background: #ECFDF5; color: #047857; border-color: #A7F3D0; }
.tag2.bad { background: #FEF2F2; color: #B91C1C; border-color: #FECACA; }
.tag2.warn { background: #FFFBEB; color: #B45309; border-color: #FDE68A; }

/* what-if */
.wi-result { border-radius: calc(var(--rad) + 2px); padding: 22px 22px 18px; color: #FFFFFF; background: linear-gradient(135deg, var(--p), var(--p2));
  box-shadow: 0 22px 40px -24px rgba(var(--sr), .8); }
.wi-result .row { display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; }
.wi-result .cap { font-size: .8rem; opacity: .85; }
.wi-num { font-size: 2.6rem; font-weight: 700; line-height: 1; font-variant-numeric: tabular-nums; font-family: var(--nf) !important; }
.wi-arrow { font-size: 1.6rem; opacity: .8; padding-bottom: 6px; }
.wi-delta { display: inline-block; margin-top: 14px; padding: 6px 14px; border-radius: 999px; font-weight: 700;
  background: rgba(255,255,255,.2); font-variant-numeric: tabular-nums; }
.wi-sub { margin-top: 10px; font-size: .92rem; opacity: .95; }
.wi-bar { height: 12px; border-radius: 999px; background: rgba(255,255,255,.22); position: relative; margin-top: 16px; overflow: hidden; }
.wi-bar span { position: absolute; top: 0; bottom: 0; left: 0; border-radius: 999px; transition: width .4s ease; }
.wi-bar .old { background: rgba(255,255,255,.55); } .wi-bar .new { background: #FFFFFF; height: 6px; top: 3px; }
.wi-why li { margin-bottom: 6px; }
.chg { font-weight: 700; padding: 1px 8px; border-radius: 999px; font-size: .8rem; font-variant-numeric: tabular-nums; }
.chg.up { background: #DCFCE7; color: #166534; } .chg.down { background: #FEE2E2; color: #991B1B; } .chg.same { background: #F1F5F9; color: #475569; }

/* early warning chalkboard */
.board { position: relative; border-radius: 16px; padding: 26px 30px 30px; margin: .2rem 0 1.2rem; color: #F1F5F9;
  background: radial-gradient(circle at 20% 20%, rgba(255,255,255,.05) 0, transparent 40%),
    radial-gradient(circle at 80% 70%, rgba(255,255,255,.04) 0, transparent 45%), linear-gradient(160deg, #26343F 0%, #1C2731 100%);
  border: 10px solid #6B4F3A; box-shadow: inset 0 0 40px rgba(0,0,0,.35), 0 22px 40px -26px rgba(0,0,0,.6); animation: rise .5s ease both; }
.board::after { content: ""; position: absolute; left: 8%; right: 8%; bottom: -10px; height: 7px; background: #574030; border-radius: 0 0 6px 6px; }
.board .top { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.board .lvl { font-size: 2rem; font-weight: 700; letter-spacing: -.01em; font-family: 'Caveat', var(--hf); font-size: 2.4rem; }
.board .score { padding: 4px 12px; border-radius: 999px; border: 1.5px dashed rgba(241,245,249,.6); font-weight: 700; }
.board .sum { margin: 8px 0 14px; color: #CBD5E1; max-width: 72ch; }
.board ul { margin: 0; padding-left: 1.1rem; } .board li { margin: 3px 0; color: #F1F5F9; }
.board li span { color: #FBCFA6; font-weight: 700; }
.board .chalk { display: inline-block; width: 46px; height: 8px; border-radius: 3px; background: #F1F5F9; opacity: .85; margin-left: 10px; vertical-align: middle; }
.legend { display: flex; gap: 10px; flex-wrap: wrap; margin: 0 0 1rem; }
.legend .lg { display: flex; align-items: center; gap: 8px; padding: 8px 14px; border-radius: 12px; background: var(--surface);
  border: 1px solid var(--line); font-size: .9rem; }
.legend .lg b { font-variant-numeric: tabular-nums; }
.legend .lg i { width: 10px; height: 10px; border-radius: 50%; background: var(--rc); display: inline-block; }
.watch { border-radius: var(--rad); background: var(--surface); border: 1px solid var(--line); padding: 14px 16px 12px; height: 100%;
  border-top: 4px solid var(--rc); box-shadow: 0 12px 24px -20px rgba(var(--sr), .5); transition: transform .2s ease; }
.watch:hover { transform: translateY(-2px); }
.watch .n { font-weight: 700; color: var(--ink); } .watch .m { color: var(--muted); font-size: .84rem; }
.watch .r { margin-top: 8px; font-size: .9rem; } .watch .a { margin-top: 6px; font-size: .88rem; color: var(--ink); }
.watch .tag { display: inline-block; padding: 1px 9px; border-radius: 999px; font-size: .76rem; font-weight: 700;
  color: var(--rc); background: color-mix(in srgb, var(--rc) 12%, #FFFFFF); }

/* buttons */
.stButton button, .stDownloadButton button, [data-testid="stFormSubmitButton"] button { border-radius: 12px; font-weight: 600;
  transition: transform .18s ease, box-shadow .18s ease, background .18s ease, border-color .18s ease; }
.stButton button:hover, .stDownloadButton button:hover, [data-testid="stFormSubmitButton"] button:hover { transform: translateY(-1px); }
.stButton button:active { transform: translateY(0) scale(.98); }
.stButton button[kind="secondary"]:hover, .stDownloadButton button:hover { border-color: var(--p); color: var(--p); }
button[kind="primary"], button[kind="primaryFormSubmit"] { background: linear-gradient(120deg, var(--p), var(--p2)) !important;
  border: none !important; color: var(--onp) !important; box-shadow: 0 10px 22px -12px rgba(var(--sr), .75); }
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover { box-shadow: 0 14px 26px -12px rgba(var(--sr), .85); }
button[kind="primary"] p, button[kind="primaryFormSubmit"] p { color: var(--onp) !important; font-weight: 600; }
button[kind="tertiary"] { color: var(--p) !important; }
button:disabled, button[disabled] { opacity: .45 !important; box-shadow: none !important; transform: none !important;
  filter: grayscale(.4); cursor: not-allowed; }
button:focus-visible, a:focus-visible, [tabindex]:focus-visible { outline: 3px solid color-mix(in srgb, var(--p) 55%, #FFFFFF) !important; outline-offset: 2px; }
[data-testid="stPageLink"] a { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 10px 14px;
  transition: transform .18s ease, background .18s ease, border-color .18s ease; }
[data-testid="stPageLink"] a:hover { background: var(--soft); transform: translateY(-1px); border-color: color-mix(in srgb, var(--p) 30%, var(--line)); }
[class*="st-key-danger"] button { background: linear-gradient(120deg, #B91C1C, #DC2626) !important; border: none !important;
  color: #FFFFFF !important; box-shadow: 0 10px 22px -12px rgba(185,28,28,.8) !important; }
[class*="st-key-danger"] button p { color: #FFFFFF !important; }

/* inputs, tables, charts */
[data-testid="stButtonGroup"] button[aria-checked="true"], [data-testid="stButtonGroup"] button[kind*="Active"] {
  background: linear-gradient(120deg, var(--p), var(--p2)) !important; border-color: transparent !important; color: var(--onp) !important; }
[data-testid="stButtonGroup"] button[aria-checked="true"] *, [data-testid="stButtonGroup"] button[kind*="Active"] * { color: var(--onp) !important; }
[data-testid="stButtonGroup"] button[aria-checked="false"]:hover { color: var(--p) !important; border-color: var(--p) !important; }
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div { border-radius: 12px !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within { border-color: var(--p) !important;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--p) 18%, transparent) !important; }
[data-baseweb="tag"] { background: var(--p) !important; }
[data-testid="stSlider"] [role="slider"] { background: var(--p) !important; box-shadow: 0 0 0 4px color-mix(in srgb, var(--p) 18%, transparent) !important; }
[data-testid="stSliderThumbValue"] { color: var(--p) !important; font-weight: 700; font-family: var(--nf); }
[data-testid="stDataFrame"], [data-testid="stPlotlyChart"] { background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--rad); padding: 6px; box-shadow: 0 12px 26px -24px rgba(var(--sr), .55); }
[data-testid="stExpander"] details { background: var(--surface); border-radius: var(--rad); border-color: var(--line); }
[data-testid="stExpander"] summary:hover { color: var(--p); }
[data-testid="stAlert"] { border-radius: var(--rad); background: rgba(255,255,255,.88); }
[data-testid="stChatMessage"] { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; }
[data-testid="stProgress"] > div > div > div > div { background: linear-gradient(90deg, var(--p), var(--p2)) !important; }
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--line); }
[data-testid="stTabs"] button[role="tab"] { border-radius: 10px 10px 0 0; padding: 8px 14px; font-weight: 600; }
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] { color: var(--p); }
[data-testid="stTabs"] [data-baseweb="tab-highlight"] { background: var(--p) !important; height: 3px; border-radius: 3px; }
[data-testid="stMetricValue"] { font-family: var(--nf); }
[data-testid="stSpinner"] i { border-top-color: var(--p) !important; }
.step { display: flex; gap: 14px; align-items: flex-start; }
.step .sn { flex: none; width: 34px; height: 34px; border-radius: 11px; display: grid; place-items: center; font-weight: 700;
  color: var(--onp); background: linear-gradient(135deg, var(--p), var(--p2)); font-family: var(--nf); }
.focus { position: relative; width: 170px; height: 170px; margin: 6px auto 14px; }
.focus .fl2 { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; }
.focus .fl2 b { font-size: 2.4rem; font-family: var(--nf); color: var(--p); line-height: 1; }
.focus .fl2 span { color: var(--muted); font-size: .85rem; }
@keyframes fill { to { stroke-dashoffset: 0; } }

/* empty states */
.empty { display: flex; gap: 14px; align-items: center; border: 1.5px dashed color-mix(in srgb, var(--p) 25%, var(--line));
  border-radius: var(--rad); padding: 18px 20px; color: var(--muted); background: color-mix(in srgb, var(--soft) 45%, #FFFFFF); }
.empty .ic { width: 40px; height: 40px; border-radius: 12px; flex: none; display: grid; place-items: center; color: var(--p); background: #FFFFFF;
  border: 1px solid var(--line); }

/* pop-ups */
div[role="dialog"] { border-radius: calc(var(--rad) + 6px) !important; overflow: hidden; border: 1px solid var(--line);
  box-shadow: 0 40px 90px -30px rgba(var(--sr), .55) !important; animation: pop .3s cubic-bezier(.2,.9,.3,1.1) both; }
@keyframes pop { from { opacity: 0; transform: translateY(16px) scale(.97); } to { opacity: 1; transform: none; } }
div[data-baseweb="modal"] > div:first-child { backdrop-filter: blur(5px); }
.dlg-hero { display: flex; gap: 14px; align-items: center; margin-bottom: 10px; }
.dlg-hero .ic { width: 46px; height: 46px; border-radius: 14px; display: grid; place-items: center; flex: none; color: #FFFFFF;
  background: linear-gradient(135deg, var(--p), var(--p2)); box-shadow: 0 10px 20px -10px rgba(var(--sr), .8); }
.dlg-hero .t { font-weight: 700; font-size: 1.05rem; color: var(--ink); }
.dlg-hero .d { color: var(--muted); font-size: .9rem; }

/* teacher directory (admin) */
.tstats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin: 10px 0 8px; }
.tstats div { background: var(--soft); border-radius: 10px; padding: 7px 6px; text-align: center; }
.tstats b { display: block; font-size: 1.15rem; font-family: var(--nf); font-variant-numeric: tabular-nums; color: var(--ink); }
.tstats span { font-size: .68rem; color: var(--muted); line-height: 1.2; display: block; }
.tcard { display: flex; gap: 12px; align-items: center; }
.tav { width: 52px; height: 52px; border-radius: 16px; flex: none; display: grid; place-items: center; color: #FFFFFF; font-weight: 700;
  font-size: 1.05rem; font-family: var(--hf); background: linear-gradient(135deg, var(--c1), var(--c2)); position: relative;
  box-shadow: 0 10px 18px -10px var(--c1); }
.tav::after { content: ""; position: absolute; right: -3px; bottom: -3px; width: 13px; height: 13px; border-radius: 50%;
  background: var(--st, #10B981); border: 2.5px solid #FFFFFF; }
.tav.lg { width: 64px; height: 64px; font-size: 1.3rem; border-radius: 20px; }
.tname { font-weight: 700; color: var(--ink); font-size: 1.02rem; line-height: 1.2; }
.tsub { color: var(--muted); font-size: .82rem; }
.tsubj { display: inline-flex; align-items: center; gap: 5px; margin-top: 3px; font-size: .78rem; font-weight: 600; color: var(--p); }
[class*="st-key-tpick_sel"] { border-color: var(--p) !important; box-shadow: 0 0 0 3px color-mix(in srgb, var(--p) 22%, transparent),
  0 20px 34px -20px rgba(var(--sr), .55) !important; }
[class*="st-key-viewas"] { background: linear-gradient(120deg, #1C1917, #2A2219) !important; border: 1px solid rgba(226,178,62,.25) !important;
  color: #F3E9D6; }
[class*="st-key-viewas"] .tname { color: #FFFFFF; } [class*="st-key-viewas"] .tsub, [class*="st-key-viewas"] p { color: #B8C6DA; }
[class*="st-key-viewas"] .tsubj { color: #F5C451; }
[class*="st-key-viewas"] label p { color: #B8C6DA !important; }
[class*="st-key-viewas"] .tstats div { background: rgba(255,255,255,.06); }
[class*="st-key-viewas"] .tstats b { color: #FFFFFF; } [class*="st-key-viewas"] .tstats span { color: #94A3B8; }

/* prediction dashboard */
.pd-hero { position: relative; border-radius: calc(var(--rad) + 4px); padding: 22px 24px; background: var(--surface);
  border: 1px solid var(--line); box-shadow: 0 1px 2px rgba(var(--sr), .05), 0 20px 40px -28px rgba(var(--sr), .55); overflow: hidden;
  animation: rise .45s ease both; }
.pd-hero::before { content: ""; position: absolute; inset: 0 0 auto 0; height: 4px; background: linear-gradient(90deg, var(--p), var(--a)); }
.pd-top { display: flex; gap: 22px; align-items: center; flex-wrap: wrap; }
.pd-ring { position: relative; width: 148px; height: 148px; flex: none; }
.pd-ring svg { width: 148px; height: 148px; }
.pd-ring .arc { animation: arc 1s cubic-bezier(.2,.8,.2,1) both; }
@keyframes arc { from { stroke-dasharray: 0 400; } }
.pd-ring .mid { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; }
.pd-ring .mid b { font-family: var(--nf); font-size: 2.3rem; line-height: 1; color: var(--ink); letter-spacing: -.02em; }
.pd-ring .mid span { font-size: .74rem; color: var(--muted); }
.pd-main { flex: 1; min-width: 220px; }
.pd-k { font-size: .74rem; text-transform: uppercase; letter-spacing: .09em; color: var(--muted); font-weight: 700; }
.pd-title { font-family: var(--hf); font-size: 1.45rem; font-weight: 700; color: var(--ink); line-height: 1.25; margin: 4px 0 6px; }
.pd-badges { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 4px; }
.pd-badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 11px; border-radius: 999px; font-size: .8rem; font-weight: 700;
  background: color-mix(in srgb, var(--bc, var(--p)) 11%, #FFFFFF); color: var(--bc, var(--p));
  border: 1px solid color-mix(in srgb, var(--bc, var(--p)) 25%, #FFFFFF); }
.pd-badge i { width: 8px; height: 8px; border-radius: 50%; background: currentColor; display: inline-block; }
.pd-scale { margin-top: 34px; }
.pd-track { position: relative; height: 14px; border-radius: 999px; overflow: visible;
  background: linear-gradient(90deg, #FECACA 0 var(--pass), #FDE68A var(--pass) var(--watch), #A7F3D0 var(--watch) 100%); }
.pd-band { position: absolute; top: -4px; bottom: -4px; border-radius: 999px; background: color-mix(in srgb, var(--ink) 22%, transparent);
  border: 1.5px solid color-mix(in srgb, var(--ink) 45%, transparent); }
.pd-pin { position: absolute; top: -9px; width: 4px; height: 32px; margin-left: -2px; border-radius: 3px; background: var(--ink);
  box-shadow: 0 0 0 3px #FFFFFF; transition: left .4s ease; }
.pd-pin::after { content: attr(data-v); position: absolute; top: -24px; left: 50%; transform: translateX(-50%); font-size: .74rem;
  font-weight: 700; color: var(--ink); white-space: nowrap; font-family: var(--nf); }
.pd-ticks { display: flex; justify-content: space-between; font-size: .7rem; color: var(--muted); margin-top: 8px; font-variant-numeric: tabular-nums; }
.pd-legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: .76rem; color: var(--muted); margin-top: 8px; }
.pd-legend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }
.pd-mean { margin-top: 14px; padding: 12px 14px; border-radius: 12px; background: var(--soft); color: var(--ink); font-size: .92rem; }
.pd-mean b { color: var(--p); }
.pd-conf { display: flex; gap: 12px; align-items: flex-start; }
.pd-conf .meter { display: flex; gap: 4px; margin-top: 4px; }
.pd-conf .meter span { width: 26px; height: 8px; border-radius: 4px; background: var(--line); }
.pd-conf .meter span.on { background: var(--cc); }
.inp { display: grid; grid-template-columns: 1fr auto; gap: 2px 10px; align-items: center; padding: 10px 0; border-top: 1px solid var(--line); }
.inp:first-child { border-top: 0; }
.inp .n { font-weight: 600; color: var(--ink); font-size: .92rem; }
.inp .v { font-family: var(--nf); font-weight: 700; color: var(--ink); font-variant-numeric: tabular-nums; }
.inp .bar { grid-column: 1 / -1; position: relative; height: 7px; border-radius: 999px; background: var(--line); }
.inp .bar span { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px; background: var(--bc); transition: width .4s ease; }
.inp .bar i { position: absolute; top: -3px; width: 2px; height: 13px; background: var(--ink); opacity: .6; border-radius: 2px; }
.inp .meta { grid-column: 1 / -1; display: flex; justify-content: space-between; font-size: .74rem; color: var(--muted); }
.drv { display: grid; grid-template-columns: 1fr auto; grid-template-areas: 'lab val' 'axis axis'; gap: 4px 10px; align-items: center;
  padding: 6px 0; font-size: .88rem; }
.drv .lab { grid-area: lab; } .drv .axis { grid-area: axis; } .drv .val { grid-area: val; }
[class*="st-key-card_conf"] li, [class*="st-key-card_conf"] p { font-size: .88rem; line-height: 1.5; }
.drv .lab { color: var(--ink); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.drv .axis { position: relative; height: 12px; border-radius: 6px; background: var(--soft); }
.drv .axis::before { content: ""; position: absolute; left: 50%; top: -3px; bottom: -3px; width: 1.5px; background: var(--muted); opacity: .5; }
.drv .axis span { position: absolute; top: 0; bottom: 0; border-radius: 6px; }
.drv .val { font-family: var(--nf); font-weight: 700; text-align: right; font-variant-numeric: tabular-nums; }

/* sidebar */
[data-testid="stSidebar"] { background: [[side_bg]]; border-right: 1px solid [[side_line]]; }
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] { border-radius: 11px; transition: background .18s ease, transform .18s ease; }
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] span { color: [[side_ink]]; }
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover { transform: translateX(3px); background: [[side_active]]; }
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] { background: [[side_active]];
  box-shadow: inset 3px 0 0 [[side_bar]]; }
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] span { font-weight: 700; }
[data-testid="stSidebar"] [data-testid="stNavSectionHeader"], [data-testid="stSidebar"] header span { color: [[side_muted]];
  text-transform: uppercase; letter-spacing: .08em; font-size: .72rem !important; font-weight: 700; }
[data-testid="stSidebar"] label, [data-testid="stSidebar"] p { color: [[side_ink]]; }
.usercard { display: flex; align-items: center; gap: 11px; padding: 11px 12px; margin-bottom: 8px; border-radius: 14px;
  background: [[usercard_bg]]; border: 1px solid [[usercard_line]]; }
.usercard .avatar { width: 40px; height: 40px; border-radius: 13px; color: var(--onp); font-weight: 700; display: grid; place-items: center;
  background: linear-gradient(135deg, var(--p), var(--p2)); flex: none; font-family: var(--hf); }
.usercard .uname { font-weight: 700; line-height: 1.2; color: [[side_ink]]; }
.rolepill { font-size: .72rem; font-weight: 700; color: [[side_bar]]; text-transform: uppercase; letter-spacing: .06em; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .76rem; font-weight: 700; border: 1px solid currentColor; }
.demo { color: #7A4E00; background: #FFF4DB; border-color: #E6C77A; }

@media (max-width: 700px) {
  .hero { padding: 20px 18px 18px !important; } .hero .art { display: none; } .hero h1 { font-size: 1.55rem; }
  .wi-num { font-size: 2rem; } .board { padding: 18px 18px 22px; border-width: 7px; } .board .lvl { font-size: 1.8rem; }
  .pd-ring, .pd-ring svg { width: 120px; height: 120px; } .pd-ring .mid b { font-size: 1.9rem; }
  .tstats { grid-template-columns: repeat(2, 1fr); }
}
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
"""

ASSIST_CSS = """
/* corner assistant: role-logo orb + floating chat window */
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes popin { from { opacity: 0; transform: translateY(18px) scale(.94); } to { opacity: 1; transform: none; } }
@keyframes nudge { 0% { opacity: 0; transform: translateX(14px) scale(.96); } 6%, 90% { opacity: 1; transform: none; }
  100% { opacity: 0; transform: translateX(8px); visibility: hidden; } }
@keyframes draw { 0% { stroke-dashoffset: 180; } 55%, 100% { stroke-dashoffset: 0; } }
@keyframes livedot { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
@keyframes glow { 0%, 100% { box-shadow: 0 18px 34px -12px rgba(var(--sr), .85), 0 0 0 0 color-mix(in srgb, var(--p) 40%, transparent); }
  50% { box-shadow: 0 18px 34px -12px rgba(var(--sr), .85), 0 0 0 8px color-mix(in srgb, var(--p) 0%, transparent); } }
.st-key-assist_orb, .st-key-assist_orb_open { position: fixed !important; right: 24px; bottom: 24px; z-index: 61; width: auto !important; }
.st-key-assist_orb button, .st-key-assist_orb_open button { position: relative; width: 66px; height: 66px; min-height: 0; padding: 0;
  border: none !important; border-radius: 22px !important; color: var(--onp) !important; overflow: visible;
  background: [[orb_bg]] !important; box-shadow: 0 18px 34px -12px rgba(var(--sr), .85), inset 0 -4px 10px rgba(0,0,0,.18) !important;
  transition: transform .25s cubic-bezier(.2,.8,.2,1), border-radius .25s ease; animation: rise .4s ease both, glow 3.6s ease-in-out 1s infinite; }
.st-key-assist_orb button { background: url("[[assist_logo]]") center / 46px 46px no-repeat, [[orb_bg]] !important; }
.st-key-assist_orb button [data-testid="stIconMaterial"], .st-key-assist_orb button span[data-testid] { opacity: 0; }
.st-key-assist_orb button:hover, .st-key-assist_orb_open button:hover { transform: translateY(-3px) rotate(-3deg); border-radius: 50% !important; }
.st-key-assist_orb_open button * { color: var(--onp) !important; font-size: 1.6rem !important; }
/* risk-coloured signal ring orbiting the closed orb, plus a risk dot */
.st-key-assist_orb button::before { content: ""; position: absolute; inset: -7px; border-radius: 26px; pointer-events: none;
  background: conic-gradient(from 0deg, var(--risk), transparent 35%, var(--risk) 50%, transparent 85%, var(--risk));
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); -webkit-mask-composite: xor;
  mask: linear-gradient(#000 0 0) content-box exclude, linear-gradient(#000 0 0); padding: 2.5px; opacity: .9;
  animation: spin 4s linear infinite; }
.st-key-assist_orb button::after { content: ""; position: absolute; top: -3px; right: -3px; width: 14px; height: 14px; border-radius: 50%;
  background: var(--risk); border: 2.5px solid #FFFFFF; pointer-events: none; }
.st-key-assist_orb_open button { background: var(--ink) !important; border-radius: 50% !important; }
.ast-nudge { position: fixed; right: 104px; bottom: 34px; z-index: 60; max-width: 280px; padding: 11px 14px; pointer-events: none;
  background: #FFFFFF; color: var(--ink); font-size: .84rem; line-height: 1.45; border-radius: 16px 16px 4px 16px;
  border: 1px solid var(--line); border-left: 4px solid var(--risk); box-shadow: 0 18px 36px -18px rgba(var(--sr), .7);
  animation: nudge 12s ease .8s both; }
.ast-nudge .who { display: block; font-size: .7rem; text-transform: uppercase; letter-spacing: .08em; font-weight: 700; color: var(--muted); margin-bottom: 2px; }
.ast-nudge b { color: var(--p); }

.st-key-assist_panel { position: fixed; right: 24px; bottom: 104px; width: 390px; max-height: calc(100vh - 134px); z-index: 60;
  background: rgba(255,255,255,.97); backdrop-filter: blur(16px); border: 1px solid var(--line); border-radius: 26px 26px 8px 26px;
  box-shadow: 0 40px 80px -30px rgba(var(--sr), .65); padding: 0 14px 12px !important; overflow-y: auto; overflow-x: hidden;
  gap: .5rem !important; transform-origin: bottom right; animation: popin .35s cubic-bezier(.2,.8,.2,1) both; }
.ast-head { position: relative; display: flex; gap: 12px; align-items: center; margin: 0 -14px 2px; padding: 14px 60px 14px 16px;
  color: #FFFFFF; overflow: hidden; background: [[orb_bg]]; }
.ast-logo { width: 48px; height: 48px; flex: none; border-radius: 15px; display: grid; place-items: center;
  background: rgba(255,255,255,.12); box-shadow: inset 0 0 0 1px rgba(255,255,255,.22); }
.ast-wave { position: absolute; right: 56px; bottom: 4px; width: 120px; height: 32px; opacity: .3; color: #FFFFFF; }
.ast-wave path { stroke-dasharray: 180; animation: draw 2.8s ease-in-out infinite; }
.ast-t { position: relative; font-weight: 700; font-family: var(--hf); font-size: 1.08rem; line-height: 1.2; }
.ast-s { position: relative; font-size: .74rem; opacity: .9; display: flex; align-items: center; gap: 6px; margin-top: 3px; }
.ast-live { width: 7px; height: 7px; border-radius: 50%; background: #A7F3D0; flex: none; animation: livedot 1.6s infinite; }
.st-key-assist_clear { position: absolute !important; top: 18px; right: 12px; z-index: 3; width: auto !important; }
.st-key-assist_clear button { color: #FFFFFF !important; background: rgba(255,255,255,.16) !important; border-radius: 10px !important; }
.st-key-assist_clear button * { color: #FFFFFF !important; }
.st-key-assist_strip { justify-content: space-between; gap: 8px !important; background: var(--soft); border-radius: 16px; padding: 6px 10px; }
.ast-pulse { display: flex; align-items: center; gap: 10px; }
.ast-pulse .k { font-size: .68rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }
.ast-pulse .v { font-family: var(--nf); font-weight: 700; font-size: 1.15rem; color: var(--ink); line-height: 1.2; }
.ast-pulse .v span { color: var(--muted); font-weight: 700; font-size: .95rem; }
.ast-pulse .g { font-size: .74rem; font-weight: 700; }
.st-key-assist_msgs { background: color-mix(in srgb, var(--soft) 45%, #FFFFFF); border-radius: 16px; padding: 4px 6px; }
.st-key-assist_msgs [data-testid="stChatMessage"] { background: #FFFFFF; border: 1px solid var(--line); border-radius: 16px 16px 16px 4px;
  padding: 8px 10px; margin: 6px 18px 6px 0; box-shadow: 0 6px 14px -12px rgba(var(--sr), .6); animation: rise .3s ease both; }
.st-key-assist_msgs [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { flex-direction: row-reverse;
  margin: 6px 0 6px 28px; border: none; border-radius: 16px 16px 4px 16px; background: linear-gradient(135deg, var(--p), var(--p2)); }
.st-key-assist_msgs [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) * { color: var(--onp) !important; }
.st-key-assist_msgs [data-testid="stChatMessage"] p, .st-key-assist_msgs [data-testid="stChatMessage"] li { font-size: .88rem; }
.st-key-assist_msgs [data-testid="stChatMessageAvatarUser"] { display: none; }
.st-key-assist_msgs [data-testid="stChatMessageAvatarCustom"], .st-key-assist_msgs [data-testid="stChatMessageAvatarAssistant"] {
  background: [[orb_bg]] !important; color: #FFFFFF !important; border-radius: 10px !important; }
.st-key-assist_msgs [data-testid="stChatMessageAvatarCustom"] *, .st-key-assist_msgs [data-testid="stChatMessageAvatarAssistant"] * {
  color: #FFFFFF !important; fill: #FFFFFF !important; }
/* quick questions: one swipeable row instead of a wall of chips */
.st-key-assist_chips [data-testid="stButtonGroup"] div:has(> button) { flex-wrap: nowrap !important; overflow-x: auto; padding-bottom: 4px;
  scrollbar-width: thin; }
.st-key-assist_chips button { font-size: .78rem !important; padding: 2px 11px !important; min-height: 0 !important; white-space: nowrap;
  border-radius: 999px !important; flex: none; }
@media (max-width: 700px) {
  .st-key-assist_panel { left: 10px; right: 10px; width: auto; bottom: 100px; max-height: calc(100vh - 124px); }
  .ast-nudge { right: 100px; max-width: calc(100vw - 124px); }
}
"""

ORB_BG = {"student": "radial-gradient(circle at 30% 20%, rgba(250,204,21,.35), transparent 45%), linear-gradient(140deg, #064E3B 0%, #047857 55%, #10B981 120%)",
          "teacher": "radial-gradient(circle at 30% 20%, rgba(251,191,36,.28), transparent 45%), linear-gradient(140deg, #4C0519 0%, #9F1239 60%, #E11D48 120%)",
          "admin": "radial-gradient(circle at 75% 15%, rgba(245,196,81,.45), transparent 45%), linear-gradient(150deg, #1C1917 0%, #3A2E1C 100%)"}

STUDENT_CSS = """
/* student: notebook page signature */
.hero::after { content: ""; position: absolute; left: 22px; top: 0; bottom: 0; width: 2px; background: rgba(255,196,107,.55); }
.hero .in { padding-left: 14px; }
.hero h1 { font-weight: 800; }
.kcard::after { content: ""; position: absolute; right: -18px; top: -18px; width: 64px; height: 64px; border-radius: 50%;
  background: color-mix(in srgb, var(--kc, var(--p)) 9%, transparent); }
[class*="st-key-card"] { border-radius: 22px; }
.doodle { font-family: 'Caveat', cursive; color: var(--a); font-size: 1.25rem; font-weight: 600; }
/* glowing green sparkles drifting through the hero */
.hero .in::before, .hero .in::after { content: ""; position: absolute; width: 6px; height: 6px; border-radius: 50%; pointer-events: none;
  background: #FDE68A; box-shadow: 0 0 10px 3px rgba(253,230,138,.8), 0 0 22px 6px rgba(16,185,129,.5);
  animation: twinkle 3.4s ease-in-out infinite, drift 9s ease-in-out infinite alternate; --dx: 30px; --dy: -14px; }
.hero .in::before { left: 46%; top: 6px; } .hero .in::after { left: 70%; bottom: 4px; animation-delay: -1.7s, -4s; --dx: -26px; }
[data-testid="stSidebar"] { box-shadow: inset -1px 0 0 rgba(4,120,87,.12); }
"""

TEACHER_CSS = """
/* teacher: crimson lecture-board + academic register signature */
.hero { border-bottom: 4px solid #F5B971; box-shadow: inset 0 0 60px rgba(40,0,10,.35), 0 22px 44px -26px rgba(136,19,55,.75); }
.hero::before { content: ""; position: absolute; width: 360px; height: 220px; right: 18%; top: -120px; border-radius: 50%;
  background: #FB7185; opacity: .35; filter: blur(50px); pointer-events: none; animation: blob 18s ease-in-out infinite alternate; }
.hero h1 { font-weight: 600; letter-spacing: -.01em; }
.hero .eyebrow { color: #FDE68A; }
.hero .lede { font-family: 'Public Sans', sans-serif; }
.kcard { border-top: 3px solid var(--kc, var(--p)); }
.kcard .ic { border-radius: 8px; }
.sect h3 { font-weight: 600; }
.sect .ic { border-radius: 8px; background: #FFFFFF; border: 1px solid var(--line); color: var(--a); }
"""

ADMIN_CSS = """
/* admin: command console signature */
.hero { border: 1px solid rgba(226,178,62,.22); }
.hero::before, .hero::after { content: ""; position: absolute; border-radius: 50%; filter: blur(50px); pointer-events: none;
  animation: aurora 16s ease-in-out infinite alternate; }
.hero::before { width: 420px; height: 240px; background: #B7791F; opacity: .45; top: -130px; right: 8%; }
.hero::after { width: 320px; height: 220px; background: #7C5A14; opacity: .4; bottom: -150px; right: 36%; animation-duration: 20s; }
@keyframes aurora { from { transform: translate(0,0) scale(1); } to { transform: translate(-60px,30px) scale(1.15); } }
.hero .eyebrow { color: #F5C451; font-family: 'JetBrains Mono', monospace; letter-spacing: .06em; }
.kcard { border: 1px solid transparent; background: linear-gradient(#FFFFFF, #FFFFFF) padding-box,
  linear-gradient(135deg, #E2B23E, #8A6A2A 55%, #F5C451) border-box; }
.kcard .v { color: var(--vc, #1C1917); }
.kcard .l { text-transform: uppercase; letter-spacing: .06em; font-size: .7rem; font-weight: 700; }
.kcard .ic { border-radius: 9px; }
[data-testid="stSidebar"] [data-baseweb="select"] > div { background: rgba(255,255,255,.06); border-color: rgba(226,178,62,.28); color: #F3E9D6; }
[data-testid="stSidebar"] [data-baseweb="select"] svg { fill: #F3E9D6; }
[data-testid="stSidebar"] .stButton button { background: rgba(255,255,255,.05); color: #F3E9D6; border-color: rgba(226,178,62,.28); }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.1); }
[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] svg { fill: #E2E8F0; color: #F3E9D6; }
"""


def _fill(template: str, values: dict) -> str:
    for k, v in values.items():
        template = template.replace(f"[[{k}]]", str(v))
    return template


def css(role: str) -> str:
    c = THEMES[role]
    dark = c["dark_side"]
    values = dict(c, head_font=f"'{c['font']}', 'Public Sans', system-ui, sans-serif",
                  side_line="rgba(255,255,255,.07)" if dark else c["line"],
                  usercard_bg="rgba(255,255,255,.06)" if dark else "var(--soft)",
                  usercard_line="rgba(226,178,62,.25)" if dark else "var(--line)",
                  orb_bg=ORB_BG[role], assist_logo=svg_data_uri(assistant_logo(role)))
    extra = {"student": STUDENT_CSS, "teacher": TEACHER_CSS, "admin": ADMIN_CSS}[role]
    return _fill(BASE_CSS + ASSIST_CSS + extra, values) + "</style>"


# ---------------- hero artwork ----------------
def hero_art(role: str) -> str:
    if role == "student":   # cap on a stack of books with a handwritten formula and a spark
        return ('<svg viewBox="0 0 190 130" width="190" height="130" aria-hidden="true">'
                '<text x="4" y="30" font-family="Caveat, cursive" font-size="24" fill="rgba(255,255,255,.75)" font-weight="600">E = mc²</text>'
                '<text x="118" y="122" font-family="Caveat, cursive" font-size="20" fill="rgba(255,255,255,.6)" font-weight="600">Σ n²</text>'
                '<rect x="40" y="96" width="104" height="18" rx="4" fill="#F2665A"/><rect x="48" y="78" width="92" height="18" rx="4" fill="#FFFFFF"/>'
                '<rect x="36" y="60" width="98" height="18" rx="4" fill="#F5A524"/>'
                '<path d="M48 105h84M58 87h72M46 69h78" stroke="rgba(30,27,58,.18)" stroke-width="2.4"/>'
                '<path d="M90 14 140 34 90 54 40 34z" fill="#1E1B3A"/><path d="M62 43v9c0 5 12 9 28 9s28-4 28-9v-9L90 54z" fill="#2E2A55"/>'
                '<path d="M90 34 128 40v18" stroke="#FFC46B" stroke-width="3" fill="none" stroke-linecap="round"/><circle cx="128" cy="60" r="4" fill="#FFC46B"/>'
                '<path d="M164 18l2.4 6 6 2.4-6 2.4-2.4 6-2.4-6-6-2.4 6-2.4z" fill="#FFC46B"/></svg>')
    if role == "teacher":   # chalk-drawn chart, formula and pointer on the chalkboard
        return ('<svg viewBox="0 0 200 130" width="200" height="130" aria-hidden="true" fill="none" stroke-linecap="round">'
                '<path d="M20 112V22M20 112h150" stroke="rgba(241,245,249,.75)" stroke-width="2.4"/>'
                '<path d="M34 112V82M60 112V66M86 112V74M112 112V48M138 112V36" stroke="rgba(241,245,249,.5)" stroke-width="12"/>'
                '<path d="M30 88 58 70l26 8 26-26 28-12" stroke="#F4B183" stroke-width="3"/>'
                '<circle cx="138" cy="40" r="5" fill="#F4B183" stroke="none"/>'
                '<text x="128" y="22" font-family="Caveat, cursive" font-size="22" fill="rgba(241,245,249,.85)" stroke="none" font-weight="600">x̄ ↑</text>'
                '<path d="M176 60 150 104" stroke="#C8A27C" stroke-width="5"/><path d="M178 56l-3 6" stroke="#F1F5F9" stroke-width="5"/></svg>')
    return ('<svg viewBox="0 0 210 130" width="210" height="130" aria-hidden="true">'   # console widgets
            '<rect x="2" y="8" width="120" height="74" rx="12" fill="rgba(255,255,255,.05)" stroke="rgba(226,178,62,.4)"/>'
            '<path d="M14 64 36 50l18 6 22-22 22 8 14-14" fill="none" stroke="#E0A526" stroke-width="2.6" stroke-linecap="round"/>'
            '<path d="M14 64 36 50l18 6 22-22 22 8 14-14V74H14z" fill="rgba(226,178,62,.12)"/>'
            '<rect x="134" y="8" width="72" height="74" rx="12" fill="rgba(255,255,255,.05)" stroke="rgba(99,102,241,.45)"/>'
            '<circle cx="170" cy="45" r="21" fill="none" stroke="rgba(255,255,255,.12)" stroke-width="8"/>'
            '<circle cx="170" cy="45" r="21" fill="none" stroke="#F5C451" stroke-width="8" stroke-dasharray="92 132" transform="rotate(-90 170 45)" stroke-linecap="round"/>'
            '<rect x="2" y="92" width="204" height="32" rx="10" fill="rgba(255,255,255,.05)" stroke="rgba(148,163,184,.3)"/>'
            '<circle cx="20" cy="108" r="5" fill="#34D399"/><rect x="34" y="104" width="60" height="8" rx="4" fill="rgba(255,255,255,.35)"/>'
            '<rect x="104" y="104" width="34" height="8" rx="4" fill="rgba(226,178,62,.6)"/><rect x="148" y="104" width="46" height="8" rx="4" fill="rgba(255,255,255,.18)"/></svg>')


def plotly_template(role: str):
    c = THEMES[role]
    tpl = go.layout.Template(pio.templates["plotly_white"])
    tpl.layout.update(font=dict(family="Public Sans, system-ui, sans-serif", color=c["ink"], size=13),
                      colorway=c["colorway"], margin=dict(l=12, r=12, t=46, b=12),
                      title=dict(font=dict(size=15, family=f"{c['font']}, Public Sans, sans-serif")),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      hoverlabel=dict(bgcolor="#FFFFFF", bordercolor=c["line"], font=dict(color=c["ink"])),
                      xaxis=dict(gridcolor=c["line"], zerolinecolor=c["line"]),
                      yaxis=dict(gridcolor=c["line"], zerolinecolor=c["line"]))
    name = f"role_{role}"
    pio.templates[name] = tpl
    pio.templates.default = name


def apply(role: str):
    st.markdown(css(role) + decor_html(role), unsafe_allow_html=True)
    plotly_template(role)
