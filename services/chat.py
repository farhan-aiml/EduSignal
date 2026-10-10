"""Assistant chat history.

Privacy rules: a conversation belongs to the account that started it, and ONLY that account can list, read,
continue or delete it (admins included: conversations can contain a student's private academic data).
Deleting a conversation removes its messages permanently (ON DELETE CASCADE). Each conversation remembers
which student it was about, so history is shown per student context.
"""
from __future__ import annotations

import pandas as pd

from database import database as db
from services import audit
from services.access import PermissionDenied, can_view_student

MAX_CONVERSATIONS = 50       # per user and student; the oldest are removed beyond this
MAX_MESSAGE_CHARS = 4000


def _owner(con, conv_id: int) -> dict | None:
    r = con.execute("SELECT id, username, student_id, title FROM assistant_conversations WHERE id = ?",
                    (int(conv_id),)).fetchone()
    return dict(r) if r else None


def _check(con, user: dict, conv_id: int) -> dict:
    c = _owner(con, conv_id)
    if c is None or c["username"] != user.get("username"):
        raise PermissionDenied("Yeh conversation aapki nahi hai.")
    return c


def start(user: dict, student_id: str | None) -> int:
    if student_id and not can_view_student(user, student_id):
        raise PermissionDenied("Aapko is student ka data dekhne ki permission nahi hai.")
    with db.connect() as con:
        cid = con.execute("INSERT INTO assistant_conversations(username, student_id, title, created_at, updated_at) "
                          "VALUES (?,?,?,?,?)", (user["username"], student_id, "Nayi baatcheet", db.now(), db.now())).lastrowid
        old = con.execute("SELECT id FROM assistant_conversations WHERE username = ? AND COALESCE(student_id,'') = COALESCE(?, '') "
                          "ORDER BY updated_at DESC, id DESC LIMIT -1 OFFSET ?", (user["username"], student_id,
                                                                                 MAX_CONVERSATIONS)).fetchall()
        for (oid,) in old:
            con.execute("DELETE FROM assistant_conversations WHERE id = ?", (oid,))
    return cid


def add_exchange(user: dict, conv_id: int, question: str, answer: str) -> None:
    with db.connect() as con:
        c = _check(con, user, conv_id)
        con.executemany("INSERT INTO assistant_messages(conversation_id, role, content, created_at) VALUES (?,?,?,?)",
                        [(int(conv_id), "user", question[:MAX_MESSAGE_CHARS], db.now()),
                         (int(conv_id), "assistant", answer[:MAX_MESSAGE_CHARS], db.now())])
        title = c["title"] if c["title"] != "Nayi baatcheet" else (question.strip()[:60] or "Nayi baatcheet")
        con.execute("UPDATE assistant_conversations SET updated_at = ?, title = ? WHERE id = ?", (db.now(), title, int(conv_id)))


def messages(user: dict, conv_id: int) -> list[dict]:
    with db.connect() as con:
        _check(con, user, conv_id)
        rows = con.execute("SELECT role, content FROM assistant_messages WHERE conversation_id = ? ORDER BY id",
                           (int(conv_id),)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def conversations(user: dict, student_id: str | None) -> pd.DataFrame:
    return db.query_df(
        "SELECT c.id, c.title, c.updated_at, COUNT(m.id) / 2 AS questions FROM assistant_conversations c "
        "LEFT JOIN assistant_messages m ON m.conversation_id = c.id WHERE c.username = ? "
        "AND COALESCE(c.student_id,'') = COALESCE(?, '') GROUP BY c.id HAVING COUNT(m.id) > 0 "
        "ORDER BY c.updated_at DESC, c.id DESC", (user["username"], student_id))


def delete(user: dict, conv_id: int) -> None:
    with db.connect() as con:
        _check(con, user, conv_id)
        con.execute("DELETE FROM assistant_conversations WHERE id = ?", (int(conv_id),))
        audit.log("chat.delete", user, "conversation", conv_id, con=con)


def delete_all(user: dict) -> int:
    with db.connect() as con:
        n = con.execute("DELETE FROM assistant_conversations WHERE username = ?", (user["username"],)).rowcount
        audit.log("chat.delete_all", user, details={"conversations": n}, con=con)
    return n
