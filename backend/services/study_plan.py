"""Study-plan task tracking.

The daily plan is generated from the student's analysis (utils/recommendations.study_plan). The first time a
plan is shown on a given day, its blocks are stored as study_tasks for that date; their status then persists
across refreshes and logins. Only the student who owns the plan can change a task's status; teachers and admins
can see progress but not edit it.
"""
from __future__ import annotations

from datetime import date as _date

import pandas as pd

from backend.database import database as db
from backend.services import audit
from backend.services.access import PermissionDenied, can_view_student

STATUSES = ("pending", "in_progress", "completed")
LABELS = {"pending": "Pending", "in_progress": "In Progress", "completed": "Completed"}


def sync_today(student_id: str, today_blocks: list[dict], on: str | None = None) -> pd.DataFrame:
    """Store today's plan blocks once (existing tasks and their status are never overwritten)."""
    d = on or _date.today().isoformat()
    with db.connect() as con:
        con.executemany(
            "INSERT OR IGNORE INTO study_tasks(student_id, plan_date, block_order, activity, minutes, reason, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            [(student_id, d, int(b["order"]), str(b["activity"])[:200], int(b["minutes"]), str(b.get("why", ""))[:500],
              db.now()) for b in today_blocks])
    return tasks_for(student_id, d)


def tasks_for(student_id: str, on: str | None = None) -> pd.DataFrame:
    return db.query_df("SELECT id, plan_date, block_order, activity, minutes, reason, status, updated_at, completed_at "
                       "FROM study_tasks WHERE student_id = ? AND plan_date = ? ORDER BY block_order",
                       (student_id, on or _date.today().isoformat()))


def progress(tasks: pd.DataFrame) -> dict:
    n = len(tasks)
    done = int((tasks["status"] == "completed").sum()) if n else 0
    doing = int((tasks["status"] == "in_progress").sum()) if n else 0
    mins = int(tasks["minutes"].sum()) if n else 0
    done_min = int(tasks.loc[tasks["status"] == "completed", "minutes"].sum()) if n else 0
    return {"total": n, "completed": done, "in_progress": doing, "pending": n - done - doing,
            "pct": round(100 * done / n) if n else 0, "minutes": mins, "minutes_done": done_min}


def set_status(user: dict, task_id: int, status: str) -> None:
    """Only the student who owns the task may change it."""
    if status not in STATUSES:
        raise ValueError("Invalid status.")
    with db.connect() as con:
        row = con.execute("SELECT student_id, status FROM study_tasks WHERE id = ?", (int(task_id),)).fetchone()
        if row is None:
            raise ValueError("Task not found.")
        if not user or user.get("role") != "student" or user.get("student_id") != row["student_id"]:
            raise PermissionDenied("Only the student can update their own study tasks.")
        con.execute("UPDATE study_tasks SET status = ?, updated_by = ?, updated_at = ?, completed_at = ? WHERE id = ?",
                    (status, user["username"], db.now(), db.now() if status == "completed" else None, int(task_id)))
        audit.log("study_task.status", user, "study_task", task_id, {"from": row["status"], "to": status}, con=con)


def history(user: dict, student_id: str, days: int = 30) -> pd.DataFrame:
    """Daily completion for the last `days` days (read access follows the normal student-view rules)."""
    if not can_view_student(user, student_id):
        raise PermissionDenied("You don't have permission to view this student's data.")
    return db.query_df(
        "SELECT plan_date, COUNT(*) AS tasks, SUM(status = 'completed') AS completed, SUM(minutes) AS minutes, "
        "SUM(CASE WHEN status = 'completed' THEN minutes ELSE 0 END) AS minutes_done FROM study_tasks "
        "WHERE student_id = ? AND plan_date >= date('now', 'localtime', ?) GROUP BY plan_date ORDER BY plan_date",
        (student_id, f"-{int(days)} days"))
