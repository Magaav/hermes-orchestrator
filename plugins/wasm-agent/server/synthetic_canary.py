"""Short-lived, objective-bound production canary grants."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from typing import Any


PROVIDER = "synthetic-canary"
PATH = "/agent/canary/envelope"
PROVIDER_PATH = "/agent/provider/envelope"


def canonical_provider_path(path: str) -> str:
    return PROVIDER_PATH if path == PATH else path


def is_canary_path(path: str) -> bool:
    return path == PATH


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS synthetic_canary_grant_tb (
          user_id INTEGER PRIMARY KEY,
          objective_sha256 TEXT NOT NULL,
          session_id TEXT NOT NULL,
          expires_at INTEGER NOT NULL,
          created_at INTEGER NOT NULL
        )
    """)


def objective_sha256(objective: str) -> str:
    return hashlib.sha256(objective.encode("utf-8")).hexdigest()


def active(conn: sqlite3.Connection, user_id: str, *, now: int | None = None) -> bool:
    ensure_schema(conn)
    row = conn.execute(
        "SELECT expires_at FROM synthetic_canary_grant_tb WHERE user_id = ?",
        (int(user_id),),
    ).fetchone()
    return bool(row and int(row[0]) >= int(now or time.time()))


def authorize(conn: sqlite3.Connection, user_id: str, body: dict[str, Any], *, now: int | None = None) -> bool:
    ensure_schema(conn)
    envelope = body.get("envelope") if isinstance(body.get("envelope"), dict) else {}
    objective = str(envelope.get("objective") or "")
    session_id = str(body.get("session_id") or "")
    if not objective or not session_id:
        return False
    row = conn.execute(
        "SELECT objective_sha256, session_id, expires_at FROM synthetic_canary_grant_tb WHERE user_id = ?",
        (int(user_id),),
    ).fetchone()
    return bool(
        row
        and int(row[2]) >= int(now or time.time())
        and str(row[0]) == objective_sha256(objective)
        and str(row[1]) == session_id
    )


def user_allowed(is_admin: bool, connect: Any, user_id: str, body: dict[str, Any]) -> bool:
    if is_admin:
        return True
    if body.get("_synthetic_canary_authorized") is not True:
        return False
    with connect() as conn:
        return authorize(conn, user_id, body)
