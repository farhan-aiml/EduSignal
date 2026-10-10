"""Alert generation and delivery channels.

Rules decide WHAT to alert; channels decide HOW it is delivered. The first
version ships the in-app channel. Email/SMS channels share the same
interface and can be enabled later without touching the rules.
"""
from __future__ import annotations

import os

from database import database as db


class Channel:
    name = "base"

    def send(self, n: dict) -> bool:
        raise NotImplementedError


class InAppChannel(Channel):
    name = "in_app"

    def send(self, n: dict) -> bool:
        db.add_notification(n["type"], n["severity"], n["message"], n.get("student_id"),
                            n.get("recipient_role"), n.get("recipient_student_id"))
        return True


class EmailChannel(Channel):
    """Placeholder: set SMTP_HOST, SMTP_USER, SMTP_PASSWORD to enable (not implemented in v1)."""
    name = "email"

    def enabled(self) -> bool:
        return bool(os.getenv("SMTP_HOST"))

    def send(self, n: dict) -> bool:
        return False


CHANNELS = [InAppChannel()]


def build_alerts(student_id: str, name: str, analysis: dict, settings: dict) -> list[dict]:
    r, v = analysis["risk"], analysis["values"]
    who = f"{name or student_id} ({student_id})"
    alerts = []

    def both(type_, sev, student_msg, teacher_msg):
        alerts.append({"type": type_, "severity": sev, "message": student_msg,
                       "student_id": student_id, "recipient_student_id": student_id})
        alerts.append({"type": type_, "severity": sev, "message": teacher_msg,
                       "student_id": student_id, "recipient_role": "teacher"})

    if r["level"] == "High":
        both("high_risk", "high", f"Your profile is rated high risk. See Early warning for the reasons.",
             f"{who} is high risk (risk score {r['score']:.0f}). Main concern: {r['main_concern']}.")
    if v["Attendance"] < settings["attendance_target"]:
        both("attendance", "medium", f"Attendance is {v['Attendance']:g}%, below the {settings['attendance_target']:g}% target.",
             f"{who}: attendance {v['Attendance']:g}% is below target.")
    if v["Assignment_Score"] < settings["assignment_min"]:
        both("assignment", "medium", f"Assignment score {v['Assignment_Score']:g} is below {settings['assignment_min']:g}.",
             f"{who}: assignment score {v['Assignment_Score']:g} is low.")
    if r["trend"]["declining"]:
        both("decline", "high", f"Your predicted score dropped {abs(r['trend']['change']):.1f} points since last record.",
             f"{who}: predicted score dropped {abs(r['trend']['change']):.1f} points.")
    if r["intervention_required"]:
        alerts.append({"type": "intervention", "severity": "high", "student_id": student_id,
                       "recipient_role": "teacher", "message": f"{who} needs an intervention plan."})
    return alerts


def dispatch(alerts: list[dict]) -> int:
    sent = 0
    for a in alerts:
        for ch in CHANNELS:
            sent += bool(ch.send(a))
    return sent
