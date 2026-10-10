"""Append-only audit log of security-relevant and data-changing actions."""
from __future__ import annotations

import json

import pandas as pd

from database import database as db


def log(action: str, actor: dict | str | None = None, target_type: str | None = None,
        target_id: str | None = None, details: dict | None = None, outcome: str = "ok", con=None):
    """Record one action. Pass `con` to write inside the caller's transaction."""
    if isinstance(actor, dict):
        name, role = actor.get("username"), actor.get("role")
    else:
        name, role = actor, None
    sql = ("INSERT INTO audit_log(created_at, actor, actor_role, action, target_type, target_id, details_json, outcome) "
           "VALUES (?,?,?,?,?,?,?,?)")
    params = (db.now(), name, role, action, target_type, None if target_id is None else str(target_id),
              json.dumps(details, default=str) if details else None, outcome)
    if con is not None:
        con.execute(sql, params)
    else:
        db.execute(sql, params)


def recent(limit: int = 200, action: str | None = None, actor: str | None = None) -> pd.DataFrame:
    sql, params = "SELECT created_at, actor, actor_role, action, target_type, target_id, outcome, details_json FROM audit_log", []
    where = []
    if action:
        where.append("action = ?")
        params.append(action)
    if actor:
        where.append("actor = ?")
        params.append(actor)
    if where:
        sql += " WHERE " + " AND ".join(where)
    return db.query_df(sql + " ORDER BY id DESC LIMIT ?", tuple(params) + (int(limit),))
