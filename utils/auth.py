"""Password hashing (PBKDF2-SHA256, stdlib only) and demo account seeding.

Passwords are never stored in plain text. Hash format:
pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from database import database as db

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
    user = db.get_user(username.strip().lower())
    if user and verify_password(password, user["password_hash"]):
        return user
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
        return "Use at least 8 characters."
    if pw.isalpha() or pw.isdigit():
        return "Mix letters with numbers or symbols."
    return None
