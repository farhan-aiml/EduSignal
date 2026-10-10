"""Authorization rules, checked on the server side for every data access.

  student  -> only their own linked student record
  teacher  -> students in their assigned classes (a teacher with no classes assigned sees none of the
              protected write actions; the dashboard keeps its existing read-only fallback)
  admin    -> everything
"""
from __future__ import annotations

from backend.database import database as db


class PermissionDenied(Exception):
    pass


def teacher_sections(username: str) -> list[str]:
    """Class sections a teacher may manage: explicit class assignments plus subject assignments."""
    classes = set(db.get_teacher_classes(username))
    with db.connect() as con:
        classes |= {r[0] for r in con.execute("SELECT DISTINCT class_section FROM teacher_subjects WHERE username = ?",
                                               (username,))}
    return sorted(classes)


def section_of(student_id: str) -> str | None:
    with db.connect() as con:
        r = con.execute("SELECT class_section FROM students WHERE student_id = ?", (student_id,)).fetchone()
    return r[0] if r else None


def can_view_student(user: dict | None, student_id: str | None) -> bool:
    if not user or not student_id:
        return bool(user) and student_id is None   # manual-entry profile has no private data
    if user.get("role") == "admin":
        return True
    if user.get("role") == "student":
        return user.get("student_id") == student_id
    if user.get("role") == "teacher":
        sections = teacher_sections(user["username"])
        if not sections:            # no classes assigned yet: legacy behaviour shows all (read-only)
            return True
        return section_of(student_id) in sections
    return False


def can_manage_section(user: dict | None, section: str) -> bool:
    """Write access (attendance, marks, record refresh) for a whole class section."""
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    return user.get("role") == "teacher" and section in teacher_sections(user["username"])


def require(condition: bool, message: str = "You don't have permission for this action."):
    if not condition:
        raise PermissionDenied(message)


def require_role(user: dict | None, *roles: str):
    require(bool(user) and user.get("role") in roles, "This action needs a " + " or ".join(roles) + " account.")
