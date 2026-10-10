"""Alert generation and delivery channels.

Rules decide WHAT to alert; channels decide HOW it is delivered.
  * In-app (always on): stored in `notifications` with read/unread status. Identical unread alerts are skipped,
    which is also the de-duplication point for every other channel.
  * Email (SMTP) and SMS (Twilio or a generic webhook): used only when configured through environment variables,
    and only for alerts at or above NOTIFY_EXTERNAL_MIN_SEVERITY (default: high). Every attempt is recorded in
    `notification_deliveries` with its real outcome: sent / failed (with the error) / not_configured / no_contact.
    Nothing is ever reported as sent without the provider accepting it.
"""
from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

from backend.database import database as db

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[0-9]{8,15}$")


def _env(name, default=None):
    v = os.environ.get(name, default)
    return v.strip() if isinstance(v, str) else v


class Channel:
    name = "base"
    required: tuple = ()

    def missing(self) -> list[str]:
        return [k for k in self.required if not _env(k)]

    def configured(self) -> bool:
        return not self.missing()

    def send(self, to: str, subject: str, body: str) -> tuple[bool, str | None]:
        raise NotImplementedError


class InAppChannel:
    name = "in_app"

    def send(self, n: dict):
        return db.add_notification(n["type"], n["severity"], n["message"], n.get("student_id"),
                                   n.get("recipient_role"), n.get("recipient_student_id"))


class EmailChannel(Channel):
    """SMTP_HOST, SMTP_FROM required; SMTP_PORT (587), SMTP_USER/SMTP_PASSWORD, SMTP_TLS (starttls|ssl|none)."""
    name = "email"
    required = ("SMTP_HOST", "SMTP_FROM")

    def send(self, to, subject, body):
        if not EMAIL_RE.match(to or ""):
            return False, "Galat email address."
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = _env("SMTP_FROM"), to, subject
        msg.set_content(body)
        host, port = _env("SMTP_HOST"), int(_env("SMTP_PORT", "587") or 587)
        mode = (_env("SMTP_TLS", "starttls") or "starttls").lower()
        try:
            if mode == "ssl":
                server = smtplib.SMTP_SSL(host, port, timeout=10, context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(host, port, timeout=10)
                if mode == "starttls":
                    server.starttls(context=ssl.create_default_context())
            with server:
                if _env("SMTP_USER"):
                    server.login(_env("SMTP_USER"), _env("SMTP_PASSWORD") or "")
                refused = server.send_message(msg)
            return (False, f"Server ne recipient reject kiya: {refused}") if refused else (True, None)
        except (smtplib.SMTPException, OSError) as e:
            return False, f"{type(e).__name__}: {e}"[:300]


class SMSChannel(Channel):
    """SMS_PROVIDER = twilio (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM)
    or webhook (SMS_WEBHOOK_URL, optional SMS_WEBHOOK_TOKEN; receives JSON {"to", "message"})."""
    name = "sms"

    def missing(self):
        provider = (_env("SMS_PROVIDER") or "").lower()
        if provider == "twilio":
            return [k for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM") if not _env(k)]
        if provider == "webhook":
            return [k for k in ("SMS_WEBHOOK_URL",) if not _env(k)]
        return ["SMS_PROVIDER (twilio ya webhook)"]

    def send(self, to, subject, body):
        if not PHONE_RE.match((to or "").replace(" ", "")):
            return False, "Galat phone number (country code ke saath likhein, jaise +919876543210)."
        text = f"{subject}: {body}"[:480]
        provider = (_env("SMS_PROVIDER") or "").lower()
        try:
            if provider == "twilio":
                sid = _env("TWILIO_ACCOUNT_SID")
                req = urllib.request.Request(
                    f"https://api.twilio.com/2010-04-01/Accounts/{urllib.parse.quote(sid)}/Messages.json",
                    data=urllib.parse.urlencode({"To": to, "From": _env("TWILIO_FROM"), "Body": text}).encode(),
                    method="POST")
                import base64
                tok = base64.b64encode(f"{sid}:{_env('TWILIO_AUTH_TOKEN')}".encode()).decode()
                req.add_header("Authorization", f"Basic {tok}")
            else:
                req = urllib.request.Request(_env("SMS_WEBHOOK_URL"), data=json.dumps({"to": to, "message": text}).encode(),
                                             method="POST", headers={"Content-Type": "application/json"})
                if _env("SMS_WEBHOOK_TOKEN"):
                    req.add_header("Authorization", f"Bearer {_env('SMS_WEBHOOK_TOKEN')}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                ok = 200 <= resp.status < 300
                return (True, None) if ok else (False, f"HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
        except (urllib.error.URLError, OSError, ValueError) as e:
            return False, f"{type(e).__name__}: {e}"[:300]


IN_APP = InAppChannel()
EXTERNAL = [EmailChannel(), SMSChannel()]
CHANNELS = [IN_APP]   # kept for backwards compatibility


def channel_status() -> dict:
    return {ch.name: {"configured": ch.configured(), "missing": ch.missing()} for ch in EXTERNAL}


def _recipients(n: dict) -> list[dict]:
    """Accounts that should receive an external copy of an alert."""
    if n.get("recipient_student_id"):
        sql, params = "SELECT username, email, phone FROM users WHERE role = 'student' AND is_active = 1 AND student_id = ?", \
            (n["recipient_student_id"],)
    elif n.get("recipient_role") == "teacher":
        sql = ("SELECT DISTINCT u.username, u.email, u.phone FROM users u JOIN teacher_classes tc ON tc.username = u.username "
               "JOIN students s ON s.class_section = tc.class_section WHERE u.is_active = 1 AND s.student_id = ?")
        params = (n.get("student_id"),)
    elif n.get("recipient_role") == "admin":
        sql, params = "SELECT username, email, phone FROM users WHERE role = 'admin' AND is_active = 1", ()
    else:
        return []
    return db.query_df(sql, params).to_dict("records")


def _record(nid, channel, recipient, status, error=None):
    with db.connect() as con:
        con.execute("INSERT OR IGNORE INTO notification_deliveries(notification_id, channel, recipient, status, error, "
                    "attempted_at) VALUES (?,?,?,?,?,?)", (nid, channel, recipient, status, error, db.now()))


def deliver_external(nid: int, n: dict) -> list[dict]:
    """Send one stored notification over the configured external channels and record every outcome."""
    min_sev = SEVERITY_RANK.get((_env("NOTIFY_EXTERNAL_MIN_SEVERITY", "high") or "high").lower(), 2)
    if SEVERITY_RANK.get(n.get("severity"), 0) < min_sev:
        return []
    out = []
    people = _recipients(n)
    for ch in EXTERNAL:
        if not ch.configured():
            _record(nid, ch.name, "-", "not_configured", "Missing: " + ", ".join(ch.missing()))
            out.append({"channel": ch.name, "status": "not_configured"})
            continue
        for p in people:
            to = p.get("email") if ch.name == "email" else p.get("phone")
            if not to:
                _record(nid, ch.name, p["username"], "no_contact")
                out.append({"channel": ch.name, "status": "no_contact"})
                continue
            ok, err = ch.send(to, f"EduSignal alert ({n['severity']})", n["message"])
            _record(nid, ch.name, to, "sent" if ok else "failed", err)
            out.append({"channel": ch.name, "status": "sent" if ok else "failed", "error": err})
    return out


def send_test(actor: dict, channel: str, to: str) -> tuple[bool, str | None]:
    """Admin-only test message. Returns the provider's real result."""
    from backend.services import audit
    from backend.services.access import require_role
    require_role(actor, "admin")
    ch = next((c for c in EXTERNAL if c.name == channel), None)
    if ch is None:
        return False, "Unknown channel."
    if not ch.configured():
        return False, "Configure nahi hai. Missing: " + ", ".join(ch.missing())
    ok, err = ch.send(to, "EduSignal test", "Yeh EduSignal ka test message hai.")
    audit.log("notification.test", actor, "channel", channel, {"to": to}, outcome="ok" if ok else "failed")
    return ok, err


def deliveries_df(limit: int = 200):
    return db.query_df("SELECT d.attempted_at, d.channel, d.recipient, d.status, d.error, n.type, n.severity, n.message "
                       "FROM notification_deliveries d JOIN notifications n ON n.id = d.notification_id "
                       "ORDER BY d.id DESC LIMIT ?", (limit,))


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
        both("high_risk", "high", "Aapki profile high risk par hai. Wajah Early warning page par dekhein.",
             f"{who} high risk par hai (risk score {r['score']:.0f}). Main concern: {r['main_concern']}.")
    if v["Attendance"] < settings["attendance_target"]:
        both("attendance", "medium", f"Attendance {v['Attendance']:g}% hai, jo {settings['attendance_target']:g}% target se kam hai.",
             f"{who}: attendance {v['Attendance']:g}% target se kam hai.")
    if v["Assignment_Score"] < settings["assignment_min"]:
        both("assignment", "medium", f"Assignment score {v['Assignment_Score']:g} hai, jo {settings['assignment_min']:g} se kam hai.",
             f"{who}: assignment score {v['Assignment_Score']:g} kam hai.")
    if r["trend"]["declining"]:
        both("decline", "high", f"Aapka predicted score pichhle record se {abs(r['trend']['change']):.1f} points gira hai.",
             f"{who}: predicted score {abs(r['trend']['change']):.1f} points gira hai.")
    if r["intervention_required"]:
        alerts.append({"type": "intervention", "severity": "high", "student_id": student_id,
                       "recipient_role": "teacher", "message": f"{who} ke liye intervention plan chahiye."})
    return alerts


def alerts_for_all(bundle) -> int:
    """Run the alert rules on every student's latest record (after imports and demo loading)."""
    from backend.config import FEATURE_NAMES
    from backend.ml.predict import predict_many
    from backend.utils.risk_engine import assess
    s = db.get_settings()
    rec = db.records_df()
    if rec.empty:
        return 0
    rec["Predicted"] = predict_many(bundle, rec)
    sent = 0
    for sid, g in rec.groupby("student_id"):
        g = g.sort_values(["record_date", "id"])
        last = g.iloc[-1]
        values = {f: float(last[f]) for f in FEATURE_NAMES}
        r = assess(values, float(last["Predicted"]), s, g["Predicted"].tolist()[:-1])
        sent += dispatch(build_alerts(sid, last["name"], {"risk": r, "values": values}, s))
    return sent


def dispatch(alerts: list[dict]) -> int:
    """Store each alert in-app (skipping identical unread ones), then try external channels for the new ones.
    Returns the number of new in-app notifications."""
    sent = 0
    for a in alerts:
        nid = IN_APP.send(a)
        if nid:
            sent += 1
            deliver_external(nid, a)
    return sent
