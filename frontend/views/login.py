"""Role-based sign-in screen: choose Student, Teacher or Admin, then sign in.

Each role gets its own scene so the difference is felt on arrival:
  student - a notebook page with sticky notes and handwritten maths
  teacher - a chalkboard with a chalk-drawn class chart and a chalk tray
  admin   - a monitoring console with live counts from the database

An account can only sign in through its own role, so a teacher account used
on the Student tab fails with the same generic message as a wrong password
(no hint about which accounts exist). Repeated failures trigger a short
lockout to slow down password guessing.
"""
from __future__ import annotations


import streamlit as st

from backend.config import APP_NAME, APP_SUBTITLE, ASSETS_DIR
from backend.database import database as db
from backend.utils import auth

ROLES = {
    "student": {"label": ":material/school: Student", "name": "Student", "title": "Wapas swagat hai",
                "sub": "Login karke apna predicted score, uski wajah aur apna study plan dekhein."},
    "teacher": {"label": ":material/co_present: Teacher", "name": "Teacher", "title": "Faculty login",
                "sub": "Jin students ko sabse pehle aapki zaroorat hai, unhe pehchaanein aur interventions plan karein."},
    "admin": {"label": ":material/admin_panel_settings: Admin", "name": "Admin", "title": "Console access",
              "sub": "Institution ka data, faculty aur prediction model manage karein."},
}
DEMO = {r: [(u, p, name) for u, p, role, _, name in auth.DEMO_ACCOUNTS if role == r] for r in ("student", "teacher", "admin")}

LOGIN_CSS = """
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display: none; }
:root { --sbw: 0px !important; }
.decor .hide-md { display: none; }
.block-container { padding-top: 2rem; max-width: 1200px; }
.scene { position: relative; overflow: hidden; border-radius: 28px; padding: 32px 36px 26px; min-height: 600px; display: flex;
  flex-direction: column; animation: rise .55s ease both; }
.scene > * { position: relative; z-index: 1; }
.scene .brandrow { display: flex; align-items: center; gap: 12px; }
.scene .brandrow svg { width: 44px; height: 44px; flex: none; }
.scene .bname { font-size: 1.35rem; font-weight: 700; line-height: 1.1; font-family: var(--hf); }
.scene .bsub { font-size: .8rem; opacity: .72; }
.scene h1 { font-family: var(--hf); line-height: 1.12; letter-spacing: -.02em; padding: 0; margin: 26px 0 10px; max-width: 16ch; }
.scene .lede2 { font-size: 1rem; max-width: 46ch; margin-bottom: 18px; }
.scene .foot { margin-top: auto; padding-top: 18px; font-size: .78rem; opacity: .7; }
.scene .flo { position: absolute; z-index: 0; pointer-events: none; animation: float 11s ease-in-out infinite; }
.hand { font-family: 'Caveat', cursive; font-weight: 600; }

/* in-scene sparkles and bubbles (reuse the theme's twinkle/drift/bubble/sway keyframes) */
.sfx { position: absolute; inset: 0; z-index: 0 !important; pointer-events: none; overflow: hidden; border-radius: inherit; }
.sfx i { position: absolute; display: block; border-radius: 50%; }
.sfx .p { background: var(--g); box-shadow: 0 0 8px 2px var(--g), 0 0 18px 4px color-mix(in srgb, var(--g) 45%, transparent);
  animation: twinkle var(--tw) ease-in-out infinite, drift var(--dr) ease-in-out infinite alternate; }
.sfx .b { bottom: -50px; opacity: 0; border: 1px solid rgba(255,255,255,.65);
  background: radial-gradient(circle at 32% 28%, rgba(255,255,255,.9) 0 9%, rgba(255,255,255,.25) 10% 24%, rgba(255,255,255,.08) 60%, rgba(255,255,255,.18) 100%);
  animation: bubble var(--d) linear infinite, sway 5s ease-in-out infinite alternate; }

/* student: glowing green study space */
.scene.student { background: radial-gradient(circle at 90% 6%, rgba(250,204,21,.38) 0, transparent 32%),
  radial-gradient(circle at 8% 100%, rgba(163,230,53,.38) 0, transparent 40%),
  repeating-linear-gradient(180deg, transparent 0 33px, rgba(255,255,255,.06) 33px 34px),
  linear-gradient(150deg, #064E3B 0%, #047857 55%, #10B981 100%);
  box-shadow: 0 30px 60px -30px rgba(4,120,87,.7), inset 0 0 0 1px rgba(255,255,255,.12); color: #ECFDF5; padding-left: 64px; }
.scene.student::before { content: ""; position: absolute; left: 44px; top: 0; bottom: 0; width: 2px; background: rgba(253,230,138,.55); z-index: 0; }
.scene.student::after { content: ""; position: absolute; left: 14px; top: 30px; bottom: 30px; width: 14px; z-index: 0;
  background: radial-gradient(circle, rgba(6,78,59,.9) 0 4px, rgba(209,250,229,.55) 4.5px 6px, transparent 6.5px) 0 0/14px 40px; }
.scene.student .bname { color: #FFFFFF; }
.scene.student h1 { font-size: 2.45rem; color: #FFFFFF; font-weight: 800; text-shadow: 0 2px 18px rgba(6,78,59,.5); }
.scene.student h1 em { font-style: normal; background: linear-gradient(transparent 62%, rgba(250,204,21,.6) 62%); }
.scene.student .hi { color: #FDE68A; font-size: 1.6rem; transform: rotate(-3deg); display: inline-block; margin-top: 18px; }
.scene.student .lede2 { color: #D1FAE5; }
.notes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 6px; }
.note { padding: 14px 14px 12px; border-radius: 4px 4px 14px 4px; box-shadow: 0 14px 24px -14px rgba(2,44,34,.65);
  transform: rotate(var(--t)); transition: transform .25s ease; font-size: .86rem; color: #052E1C; }
.note:hover { transform: rotate(0) translateY(-4px); }
.note b { display: block; font-size: .95rem; margin-bottom: 4px; }
.note .ic { width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; background: rgba(255,255,255,.6); margin-bottom: 8px; }

/* teacher: crimson lecture board */
.scene.teacher { background: radial-gradient(circle at 88% 8%, rgba(251,191,36,.28) 0, transparent 32%),
  radial-gradient(ellipse at 10% 105%, rgba(251,113,133,.45) 0, transparent 45%),
  linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px) 0 0/26px 26px,
  linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px) 0 0/26px 26px,
  linear-gradient(150deg, #4C0519 0%, #881337 50%, #BE123C 100%);
  border-bottom: 6px solid #F5B971; box-shadow: inset 0 0 70px rgba(40,0,10,.35), 0 34px 60px -30px rgba(136,19,55,.75);
  color: #FFE4E6; }
.scene.teacher .bname { color: #FFFFFF; }
.scene.teacher .lesson { color: #FDE68A; font-size: 1.5rem; margin-top: 20px; }
.scene.teacher h1 { font-size: 2.35rem; color: #FFFFFF; font-weight: 600; margin-top: 4px; max-width: 12ch; }
.scene.teacher .lede2 { color: #FECDD3; }
.chalk-list { list-style: none; padding: 0 !important; margin: 0 !important; }
.chalk-list li { margin: 0 !important; display: flex; gap: 12px; align-items: baseline; padding: 7px 0; border-top: 1px dashed rgba(255,228,230,.25); }
.chalk-list li .hand { color: #FDE68A; font-size: 1.35rem; min-width: 26px; }
.chalk-list li b { color: #FFFFFF; } .chalk-list li span { color: #FECDD3; font-size: .92rem; }
.tray { display: none; }

/* admin: gold command console */
.scene.admin { background: linear-gradient(rgba(226,178,62,.08) 1px, transparent 1px) 0 0/30px 30px,
  linear-gradient(90deg, rgba(226,178,62,.08) 1px, transparent 1px) 0 0/30px 30px,
  radial-gradient(circle at 85% 0%, rgba(224,165,38,.55) 0, transparent 45%), radial-gradient(circle at 0% 100%, rgba(124,90,20,.6) 0, transparent 45%),
  linear-gradient(150deg, #1C1917 0%, #292118 100%);
  border: 1px solid rgba(226,178,62,.35); box-shadow: 0 34px 70px -34px rgba(60,40,5,.9); color: #F3E9D6; }
.scene.admin .bname { color: #FFFFFF; }
.statusbar { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 20px; font-family: 'JetBrains Mono', monospace; font-size: .74rem; color: #CBB88F; }
.statusbar span { display: inline-flex; align-items: center; gap: 6px; }
.statusbar i { width: 7px; height: 7px; border-radius: 50%; background: #34D399; box-shadow: 0 0 10px #34D399; }
.scene.admin h1 { font-size: 2.35rem; color: #FFFFFF; font-weight: 700; margin-top: 16px; }
.scene.admin h1 em { font-style: normal; background: linear-gradient(90deg, #F5C451, #E0A526 50%, #FDE68A); -webkit-background-clip: text; background-clip: text; color: transparent; }
.scene.admin .lede2 { color: #E9DCC0; }
.tiles { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.tile { border-radius: 14px; padding: 12px 14px; background: rgba(255,255,255,.04); border: 1px solid rgba(226,178,62,.28); }
.tile .k { font-family: 'JetBrains Mono', monospace; font-size: .68rem; color: #CBB88F; letter-spacing: .06em; text-transform: uppercase; }
.tile .v { font-family: 'JetBrains Mono', monospace; font-size: 1.45rem; font-weight: 700; color: #FFFFFF; }
.tile svg { display: block; margin-top: 4px; }
.spark path.l { stroke-dasharray: 300; animation: draw2 3s ease-out both; }
@keyframes draw2 { from { stroke-dashoffset: 300; } to { stroke-dashoffset: 0; } }
.st-key-card_signin { background: rgba(255,255,255,.88) !important; backdrop-filter: blur(10px); }

/* sign-in side */
.signin { animation: rise .55s .08s ease both; }
.signin .k { font-size: .74rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--p); margin-top: 8px; }
.signin h2 { font-size: 2rem; font-weight: 700; margin: 4px 0 2px; padding: 0; font-family: var(--hf); color: var(--ink); }
.signin p { color: var(--muted); margin-bottom: 12px; }
.st-key-card_signin { padding: 22px 24px 16px !important; box-shadow: 0 30px 60px -36px rgba(var(--sr), .55) !important; }
[data-testid="stSegmentedControl"] button { transition: all .2s ease; }
[class*="st-key-card_demo"] { padding: 12px 14px !important; }
[class*="st-key-card_demo"] p { font-size: .86rem; }
@media (max-width: 900px) {
  .block-container { padding-top: 1rem; }
  .scene { min-height: auto; padding: 22px 22px 20px; }
  .scene.student { padding-left: 52px; }
  .scene h1 { margin: 14px 0 0; font-size: 1.6rem !important; }
  .scene .lede2, .notes, .chalk-list, .tiles, .scene .foot, .scene .flo { display: none; }
}
</style>
"""


def _mark_svg() -> str:
    try:
        return (ASSETS_DIR / "logo_mark.svg").read_text()
    except OSError:
        return ""


def _fill_demo(u: str, p: str):
    st.session_state["login_user"], st.session_state["login_pw"] = u, p


SCENE_FX = {"student": (["#FDE68A", "#6EE7B7", "#BEF264", "#FFFFFF"], 18, 9),
            "teacher": (["#FDE68A", "#FDA4AF", "#FFFFFF", "#FECDD3"], 16, 8),
            "admin": (["#F5C451", "#FDE68A", "#E0A526", "#FFFFFF"], 20, 7)}


def _scene_fx(role: str) -> str:
    """Glowing particles and rising bubbles inside the login scene. Seeded, so identical on every rerun."""
    import random
    colors, n_p, n_b = SCENE_FX[role]
    rnd = random.Random(f"scene-{role}")
    ps = "".join(f'<i class="p" style="left:{rnd.uniform(2, 97):.0f}%;top:{rnd.uniform(3, 96):.0f}%;'
                 f'width:{(s := rnd.choice([3, 3, 4, 5]))}px;height:{s}px;--g:{rnd.choice(colors)};'
                 f'--tw:{rnd.uniform(2.2, 5):.1f}s;--dr:{rnd.randint(10, 22)}s;--dx:{rnd.randint(-30, 30)}px;'
                 f'--dy:{rnd.randint(-40, -8)}px;animation-delay:-{rnd.uniform(0, 5):.1f}s,-{rnd.uniform(0, 20):.1f}s"></i>'
                 for _ in range(n_p))
    bs = "".join(f'<i class="b" style="left:{rnd.uniform(4, 94):.0f}%;width:{(s := rnd.randint(10, 34))}px;height:{s}px;'
                 f'--d:{rnd.randint(14, 26)}s;--sx:{rnd.randint(-30, 30)}px;--o:{rnd.uniform(.4, .8):.2f};'
                 f'animation-delay:-{rnd.uniform(0, 26):.1f}s,-{rnd.uniform(0, 5):.1f}s"></i>' for _ in range(n_b))
    return f'<div class="sfx" aria-hidden="true">{ps}{bs}</div>'


def _brand(sub_color: str = "") -> str:
    return (f'<div class="brandrow">{_mark_svg()}<div><div class="bname">{APP_NAME}</div>'
            f'<div class="bsub" style="{sub_color}">{APP_SUBTITLE}</div></div></div>')


def _student_scene(theme_mod) -> str:
    notes = [("#FFE7A3", "-2deg", "trend", "Aapka score", "Predicted final score, jo sudhaar ke saath update hota hai."),
             ("#E9DDFF", "1.5deg", "brain", "Aisa kyun", "Dekhein kaun si aadatein score badhaati ya ghataati hain."),
             ("#FFD9D2", "-1deg", "book", "Aapka plan", "Kamzor subjects ke hisaab se roz ka study plan.")]
    cards = "".join(f'<div class="note" style="background:{bg};--t:{t}"><div class="ic">{theme_mod.icon(ic, 17, "#1E1B3A")}</div>'
                    f'<b>{title}</b>{text}</div>' for bg, t, ic, title, text in notes)
    flo = [("π r²", "bottom:14px;right:26px", "#FDE68A", 26, 4)]
    floats = "".join(f'<span class="flo hand" style="{pos};color:{c};font-size:{sz}px;animation-delay:-{d}s;--r:0deg;opacity:.55">{t}</span>'
                     for t, pos, c, sz, d in flo)
    cap = (f'<div class="flo" style="top:22px;right:24px;--r:-8deg;opacity:.9">'
           f'{theme_mod._cap("#052E1C", "#FBBF24", 70)}</div>')
    return (f'<div class="scene student">{_scene_fx("student")}{floats}{cap}{_brand("color:#A7F3D0")}'
            f'<span class="hand hi">Hello, future graduate ✎</span>'
            f'<h1>Apna score jaanein. Semester <em>apne haath</em> mein lein.</h1>'
            f'<div class="lede2">EduSignal attendance, assignments aur test marks se saaf dikhata hai ki aap kahan '
            f'khade hain, aur aage kya karna hai.</div><div class="notes">{cards}</div>'
            f'<div class="foot">Predictions aapki madad ke liye andaaze hain, grades nahi.</div></div>')


def _teacher_scene() -> str:
    chart = ('<svg class="flo" style="top:150px;right:26px;--r:0deg;opacity:.55" viewBox="0 0 170 120" width="130" height="92" fill="none" stroke-linecap="round">'
             '<path d="M14 106V14M14 106h146" stroke="rgba(241,245,249,.7)" stroke-width="2.4"/>'
             '<path d="M30 106V80M56 106V64M82 106V72M108 106V46M134 106V34" stroke="rgba(241,245,249,.35)" stroke-width="13"/>'
             '<path d="M26 84 54 66l26 8 26-26 26-12" stroke="#F4B183" stroke-width="3"/>'
             '<text x="92" y="18" font-family="Caveat, cursive" font-size="20" fill="rgba(241,245,249,.8)" stroke="none">class avg ↑</text></svg>')
    eq = ('<span class="flo hand" style="top:26px;right:30px;color:rgba(241,245,249,.45);font-size:22px;--r:-4deg">'
          'σ² = Σ(x − x̄)² / n</span>')
    items = [("1", "Watchlist", "Pehle kiski madad karein, samajh mein aane wale risk score se ranked."),
             ("2", "Interventions", "Har student ke liye taiyaar plan, follow-up date aur status log."),
             ("3", "Class trends", "Har record mein attendance aur predicted scores.")]
    lis = "".join(f'<li><span class="hand">{n}.</span><div><b>{t}</b><br><span>{d}</span></div></li>' for n, t, d in items)
    tray = ('<div class="tray"><i style="left:16%;width:34px;background:#F8FAFC"></i><i style="left:24%;width:22px;background:#F4B183"></i>'
            '<i style="left:70%;width:44px;height:10px;background:#8A6A4E;border-radius:4px"></i></div>')
    return (f'<div class="scene teacher">{_scene_fx("teacher")}{chart}{eq}{_brand("color:#FECDD3")}'
            f'<div class="hand lesson">Aaj ka lesson:</div>'
            f'<h1>Exam se pehle har student tak pahunchein.</h1>'
            f'<div class="lede2">Early warnings, jinki wajah aap check kar sakte hain, aur actions jo is hafte le sakte hain.</div>'
            f'<ul class="chalk-list">{lis}</ul>'
            f'<div class="foot">Predictions aapke faisle mein madad karti hain, uski jagah nahi leti.</div>{tray}</div>')


def _admin_counts():
    try:
        with db.connect() as con:
            n_stu = con.execute("SELECT COUNT(*) FROM students").fetchone()[0]
            n_rec = con.execute("SELECT COUNT(*) FROM academic_records").fetchone()[0]
            n_t = con.execute("SELECT COUNT(*) FROM users WHERE role = 'teacher'").fetchone()[0]
            n_iv = con.execute("SELECT COUNT(*) FROM interventions WHERE status != 'Closed'").fetchone()[0]
        return n_stu, n_rec, n_t, n_iv
    except Exception:
        return 0, 0, 0, 0


def _admin_scene() -> str:
    n_stu, n_rec, n_t, n_iv = _admin_counts()
    spark = ('<svg class="spark" viewBox="0 0 120 26" width="100%" height="26"><path class="l" d="M2 22 18 16l14 4 16-12 16 6 14-10 16 8 22-12" '
             'fill="none" stroke="#F5C451" stroke-width="2" stroke-linecap="round"/></svg>')
    bars = ('<svg viewBox="0 0 120 26" width="100%" height="26">' + "".join(
        f'<rect x="{4 + i * 15}" y="{26 - h}" width="9" height="{h}" rx="2" fill="#E0A526" opacity="{.45 + i * .07:.2f}"/>'
        for i, h in enumerate([8, 12, 10, 16, 14, 20, 18, 24])) + '</svg>')
    tiles = [("Students", n_stu, spark), ("Records", n_rec, bars), ("Teachers", n_t, ""), ("Khule interventions", n_iv, "")]
    tl = "".join(f'<div class="tile"><div class="k">{k}</div><div class="v">{v:,}</div>{extra}</div>' for k, v, extra in tiles)
    return (f'<div class="scene admin">{_scene_fx("admin")}{_brand("color:#CBB88F")}'
            f'<div class="statusbar"><span><i></i>SYSTEM ONLINE</span><span>DB · SQLite</span><span>AUTH · PBKDF2</span></div>'
            f'<h1>Institution ko andaaze se nahi, <em>signal</em> se chalaayein.</h1>'
            f'<div class="lede2">Institution KPIs, faculty dashboards, data import aur model management ek hi console mein.</div>'
            f'<div class="tiles">{tl}</div>'
            f'<div class="foot">Is installation ke database se live counts.</div></div>')


@st.dialog("Password bhool gaye?", width="small")
def _forgot():
    from frontend.views.common import dialog_head
    dialog_head("shield", "Apne administrator se poochhein", "Passwords surakshit save hote hain, dikhaaye ya email nahi kiye ja sakte.")
    st.markdown("Aapke administrator aapke liye naya password set kar sakte hain. Login ke baad aap ise kabhi bhi "
                "**Settings, Account** mein badal sakte hain.")
    st.markdown("Demo use kar rahe hain? Apna role chunein aur kisi demo account par **Use** dabaayein.")
    if st.button("Samajh Gaya", type="primary", width="stretch"):
        st.rerun()


def login_screen():
    role = st.session_state.get("login_role") or "student"
    from frontend.views import theme as theme_mod
    theme_mod.apply(role)
    t = theme_mod.theme(role)
    st.markdown(LOGIN_CSS.replace("var(--hf)", f"'{t['font']}', 'Public Sans', sans-serif"), unsafe_allow_html=True)
    left, right = st.columns([1.12, 1], gap="large")
    with left:
        scene = {"student": lambda: _student_scene(theme_mod), "teacher": _teacher_scene, "admin": _admin_scene}[role]()
        st.markdown(scene, unsafe_allow_html=True)
    with right:
        role = st.segmented_control("Role", list(ROLES), default="student", required=True, key="login_role",
                                    format_func=lambda r: ROLES[r]["label"], label_visibility="collapsed",
                                    width="stretch")
        info = ROLES[role]
        with st.container(key="card_signin"):
            st.markdown(f'<div class="signin"><div class="k">{theme_mod.LABELS[role]}</div><h2>{info["title"]}</h2>'
                        f'<p>{info["sub"]}</p></div>', unsafe_allow_html=True)
            with st.form("login", border=False):
                user = st.text_input("Username", key="login_user", autocomplete="username",
                                     placeholder="jaise rahul" if role == "student" else "Aapka username")
                pw = st.text_input("Password", type="password", key="login_pw", autocomplete="current-password")
                ok = st.form_submit_button(f"{info['name']} ke roop mein Login Karein", type="primary", width="stretch",
                                           icon=":material/login:")
            if ok:   # lockout, role match, account status and audit are all enforced server-side in auth.login
                account, error = auth.login(user, pw, role)
                if account:
                    st.session_state.pop("login_pw", None)
                    st.session_state["user"] = account
                    st.rerun()
                st.error(error)
            if st.button("Password bhool gaye?", type="tertiary", key="forgot_btn"):
                _forgot()

        st.markdown(f"**Demo {info['name'].lower()} accounts**")
        cols = st.columns(len(DEMO[role]))
        for col, (u, p, name) in zip(cols, DEMO[role]):
            with col:
                with st.container(key=f"card_demo_{u}"):
                    st.markdown(f"**{name}**  \nUser `{u}`  \nPass `{p}`")
                    st.button("Use", key=f"use_{u}", on_click=_fill_demo, args=(u, p), help=f"{name} ka login bharein",
                              icon=":material/bolt:", width="stretch")
        if role == "student":
            why_text = "Rahul, Ajay aur Fahil alag-alag risk levels wale synthetic demo students hain."
        else:
            why_text = "Demo accounts app try karne ke liye hain. Asli use se pehle Settings mein passwords badlein."
        st.markdown(f'<div class="why">{why_text}</div>', unsafe_allow_html=True)
