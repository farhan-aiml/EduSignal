"""Password hashing (PBKDF2-SHA256, stdlib only) and demo account seeding.

Passwords are never stored in plain text. Hash format:
pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from backend.database import database as db

ITERATIONS = 200_000
# Demo accounts (username, password, role, linked student, display name).
# Created on first run and kept in sync by seed_demo_accounts(); change passwords in Settings.
DEMO_ACCOUNTS = [
    ("rahul", "Rahul@123", "student", "DEMO-001", "Rahul Sharma"),
    ("ajay", "Ajay@123", "student", "DEMO-002", "Ajay Verma"),
    ("fahil", "Fahil@123", "student", "DEMO-003", "Fahil Khan"),
    ("meera", "Meera@123", "teacher", None, "Dr. Meera Iyer"),
    ("arjun", "Arjun@123", "teacher", None, "Prof. Arjun Rao"),
    ("sana", "Sana@123", "teacher", None, "Ms. Sana Qureshi"),
    ("admin", "Admin@123", "admin", None, "Administrator"),
    ("vikram", "Vikram@123", "admin", None, "Vikram Mehta"),
    ("neha", "Neha@123", "admin", None, "Neha Kapoor"),
]
# Classes each demo teacher is responsible for. Rahul and Ajay are in CSE-A / CSE-B (Dr. Meera Iyer),
# Fahil is in IT-A (Ms. Sana Qureshi). Admins can change these on the Admin dashboard.
DEMO_TEACHER_CLASSES = {"meera": ["CSE-A", "CSE-B"], "arjun": ["ECE-A", "ECE-B"], "sana": ["IT-A", "Unassigned"]}
DEMO_TEACHER_SUBJECTS = {"meera": "Data Structures & Python", "arjun": "Digital Electronics",
                         "sana": "Database Systems"}
DEMO_STUDENT_LINKS = {u: sid for u, _, r, sid, _ in DEMO_ACCOUNTS if r == "student"}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), h)
    except (ValueError, AttributeError):
        return False


def authenticate(username: str, password: str):
    """Pure credential check (no lockout bookkeeping). Inactive accounts never authenticate."""
    user = db.get_user(username.strip().lower())
    if user and user.get("is_active", 1) and verify_password(password, user["password_hash"]):
        return user
    return None


GENERIC_FAIL = "Is username aur password se koi {role} account match nahi hua."


def login(username: str, password: str, role: str) -> tuple[dict | None, str | None]:
    """Full sign-in with server-side protection. Returns (account, error message).

    * The role tab must match the account's role; mismatches fail with the same generic message
      as a wrong password, so the form never reveals which accounts exist.
    * Failed attempts are counted per account in the database; after MAX_LOGIN_ATTEMPTS the account
      is locked for LOCKOUT_SECONDS (a page refresh does not reset this).
    * Every attempt is written to the audit log."""
    from datetime import datetime, timedelta

    from backend.config import LOCKOUT_SECONDS, MAX_LOGIN_ATTEMPTS
    from backend.services import audit
    uname = (username or "").strip().lower()
    if not uname or not password:
        return None, "Apna username aur password bharein."
    user = db.get_user(uname)
    generic = GENERIC_FAIL.format(role=role)
    if user is None:
        verify_password(password, f"pbkdf2_sha256${ITERATIONS}${'00' * 16}${'00' * 32}")   # same cost as a real check
        audit.log("login", uname, details={"role_tab": role}, outcome="failed")
        return None, generic
    now = datetime.now()
    if user.get("locked_until"):
        until = datetime.fromisoformat(user["locked_until"])
        if until > now:
            audit.log("login", user, details={"reason": "locked"}, outcome="denied")
            return None, f"Bahut zyada galat attempts. {int((until - now).total_seconds()) + 1} second baad dobara try karein."
    ok = verify_password(password, user["password_hash"]) and user["role"] == role
    if ok and not user.get("is_active", 1):
        audit.log("login", user, details={"reason": "inactive"}, outcome="denied")
        return None, "Yeh account deactivate hai. Apne administrator se sampark karein."
    if not ok:
        fails = int(user.get("failed_attempts") or 0) + 1
        locked = None
        if fails >= MAX_LOGIN_ATTEMPTS:
            locked, fails = (now + timedelta(seconds=LOCKOUT_SECONDS)).isoformat(timespec="seconds"), 0
        db.execute("UPDATE users SET failed_attempts = ?, locked_until = ? WHERE username = ?", (fails, locked, uname))
        audit.log("login", user, details={"role_tab": role, "locked": bool(locked)}, outcome="failed")
        if locked:
            return None, f"Bahut zyada galat attempts. Login {LOCKOUT_SECONDS} second ke liye ruka hai."
        return None, generic
    db.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ? WHERE username = ?",
               (db.now(), uname))
    audit.log("login", user, details={"role_tab": role})
    return db.get_user(uname), None


# ---------------- account administration (admin only, audited) ----------------
def create_account(actor: dict, username: str, password: str, role: str, display_name: str,
                   student_id: str | None = None, subject: str | None = None) -> str:
    from backend.services import audit
    from backend.services.access import require, require_role
    require_role(actor, "admin")
    uname = (username or "").strip().lower()
    require(uname.replace("_", "").replace(".", "").isalnum() and 3 <= len(uname) <= 32,
            "Username: 3-32 letters, digits, dots ya underscores.")
    require(role in ("student", "teacher", "admin"), "Galat role.")
    require(db.get_user(uname) is None, "Yeh username pehle se liya hua hai.")
    if (msg := validate_new_password(password)):
        raise ValueError(msg)
    if role == "student":
        require(bool(student_id) and not db.query_df("SELECT 1 FROM students WHERE student_id = ?", (student_id,)).empty,
                "Student account kisi maujooda student record se juda hona chahiye.")
        require(db.query_df("SELECT 1 FROM users WHERE student_id = ? AND role = 'student'", (student_id,)).empty,
                "Is student ka login pehle se hai.")
    db.create_user(uname, hash_password(password), role, student_id if role == "student" else None,
                   (display_name or uname).strip()[:80], subject if role == "teacher" else None)
    audit.log("user.create", actor, "user", uname, {"role": role, "student_id": student_id})
    return uname


def set_active(actor: dict, username: str, active: bool):
    from backend.services import audit
    from backend.services.access import require, require_role
    require_role(actor, "admin")
    require(username != actor.get("username") or active, "Aap apna khud ka account deactivate nahi kar sakte.")
    if not active and (u := db.get_user(username)) and u["role"] == "admin":
        n_admins = db.query_df("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND is_active = 1").iloc[0]["n"]
        require(n_admins > 1, "Kam se kam ek active admin account rehna chahiye.")
    db.execute("UPDATE users SET is_active = ?, failed_attempts = 0, locked_until = NULL WHERE username = ?",
               (1 if active else 0, username))
    audit.log("user.activate" if active else "user.deactivate", actor, "user", username)


def reset_password(actor: dict, username: str, new_password: str):
    from backend.services import audit
    from backend.services.access import require, require_role
    require_role(actor, "admin")
    require(db.get_user(username) is not None, "User nahi mila.")
    if (msg := validate_new_password(new_password)):
        raise ValueError(msg)
    db.update_password(username, hash_password(new_password))
    audit.log("user.password_reset", actor, "user", username)


def update_contact(actor: dict, username: str, email: str | None, phone: str | None) -> str | None:
    """Set an account's email/phone for alerts. The account owner or an admin only. Returns an error or None."""
    from backend.services import audit
    from backend.services.access import require
    from backend.utils.notifications import EMAIL_RE, PHONE_RE
    require(actor.get("username") == username or actor.get("role") == "admin",
            "Aap sirf apni contact details badal sakte hain.")
    email = (email or "").strip() or None
    phone = (phone or "").replace(" ", "").strip() or None
    if email and not EMAIL_RE.match(email):
        return "Email sahi format mein likhein, jaise naam@college.edu."
    if phone and not PHONE_RE.match(phone):
        return "Phone country code ke saath likhein, jaise +919876543210."
    db.execute("UPDATE users SET email = ?, phone = ? WHERE username = ?", (email, phone, username))
    audit.log("user.contact", actor, "user", username, {"email": bool(email), "phone": bool(phone)})
    return None


def change_own_password(user: dict, current: str, new: str, repeat: str) -> str | None:
    """Returns an error message, or None on success."""
    from backend.services import audit
    if not authenticate(user["username"], current):
        audit.log("password.change", user, outcome="failed")
        return "Abhi ka password galat hai."
    if new != repeat:
        return "Naye passwords match nahi hue."
    if (msg := validate_new_password(new)):
        return msg
    db.update_password(user["username"], hash_password(new))
    audit.log("password.change", user)
    return None


def seed_demo_accounts():
    """Create any missing demo account. Existing accounts (and changed passwords) are left alone."""
    for u, p, role, sid, name in DEMO_ACCOUNTS:
        if db.get_user(u) is None:
            db.create_user(u, hash_password(p), role, sid, name)


def seed_teacher_classes():
    """Give demo teachers their classes once. Later edits by an admin are kept."""
    if db.get_settings().get("teacher_classes_seeded"):
        return
    for u, classes in DEMO_TEACHER_CLASSES.items():
        if db.get_user(u) and not db.get_teacher_classes(u):
            db.set_teacher_classes(u, classes)
    db.save_settings({"teacher_classes_seeded": True})


def seed_teacher_subjects():
    """Give demo teachers a subject if they have none. Later edits by an admin are kept."""
    for u, subject in DEMO_TEACHER_SUBJECTS.items():
        user = db.get_user(u)
        if user and not user.get("subject"):
            db.set_teacher_subject(u, subject)


def relink_demo_students():
    """Re-attach demo student logins after demo data is regenerated."""
    for u, sid in DEMO_STUDENT_LINKS.items():
        db.execute("UPDATE users SET student_id = ? WHERE username = ? AND role = 'student'", (sid, u))


def validate_new_password(pw: str) -> str | None:
    if len(pw) < 8:
        return "Kam se kam 8 characters use karein."
    if pw.isalpha() or pw.isdigit():
        return "Letters ke saath numbers ya symbols milaayein."
    return None
