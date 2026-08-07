"""Insert-only external anchor store for Master:frontier event ledgers.

The store contains no event content. User and run identifiers are domain-hashed
before persistence. SQLite triggers reject row mutation, and every checkpoint
commits to the prior stored checkpoint. This is a separate process-level trust
boundary, not protection from an administrator replacing the database itself.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import event_integrity


SCHEMA = "hermes.wasm_agent.master_frontier.event_anchor_store.v1"
MAX_CHECKPOINTS_PER_RUN = 512
ZERO_RECORD = "0" * 64


class EventAnchorStoreError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def default_path(private_state_root: str | Path) -> Path:
    return Path(private_state_root) / "event-anchors" / "sqlite" / "mf_event_anchors.sqlite3"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _scope(kind: str, value: Any) -> str:
    text = str(value or "")
    if not text:
        raise EventAnchorStoreError(f"anchor_{kind}_missing", f"Anchor {kind} is required.")
    return _sha(f"WASM-AGENT-ANCHOR-{kind.upper()}\0{text}".encode())


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str,
    ).encode()


def _hex(value: Any, field: str) -> str:
    text = str(value or "").lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise EventAnchorStoreError("anchor_invalid", f"Anchor {field} must be SHA-256 hex.")
    return text


def _anchor(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EventAnchorStoreError("anchor_invalid", "Anchor must be an object.")
    if value.get("schema") != event_integrity.ANCHOR_SCHEMA:
        raise EventAnchorStoreError("anchor_invalid", "Anchor schema is invalid.")
    if value.get("algorithm") != event_integrity.ALGORITHM:
        raise EventAnchorStoreError("anchor_invalid", "Anchor algorithm is invalid.")
    try:
        declared = int(value.get("declared") or 0)
    except (TypeError, ValueError) as exc:
        raise EventAnchorStoreError("anchor_invalid", "Anchor declared count is invalid.") from exc
    if declared <= 0 or declared > event_integrity.MAX_EVENTS:
        raise EventAnchorStoreError("anchor_invalid", "Anchor declared count is outside the event bound.")
    return {
        "schema": event_integrity.ANCHOR_SCHEMA,
        "algorithm": event_integrity.ALGORITHM,
        "run_id": str(value.get("run_id") or ""),
        "declared": declared,
        "head": _hex(value.get("head"), "head"),
    }


def _record_digest(
    *,
    principal_hash: str,
    run_hash: str,
    checkpoint: int,
    declared: int,
    head: str,
    previous_record: str,
    final: bool,
    created_at: int,
) -> str:
    return _sha(_canonical({
        "checkpoint": checkpoint,
        "created_at": created_at,
        "declared": declared,
        "final": final,
        "head": head,
        "previous_record": previous_record,
        "principal_hash": principal_hash,
        "run_hash": run_hash,
        "schema": SCHEMA,
    }))


class EventAnchorStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            connection = sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3,
            )
            connection.execute("PRAGMA query_only=ON")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS event_anchor_meta (
                    schema TEXT PRIMARY KEY,
                    created_at INTEGER NOT NULL
                ) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS event_anchor (
                    principal_hash TEXT NOT NULL,
                    run_hash TEXT NOT NULL,
                    checkpoint INTEGER NOT NULL,
                    declared INTEGER NOT NULL,
                    head TEXT NOT NULL,
                    previous_record TEXT NOT NULL,
                    record_digest TEXT NOT NULL,
                    final INTEGER NOT NULL CHECK (final IN (0, 1)),
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (principal_hash, run_hash, checkpoint),
                    UNIQUE (record_digest)
                ) WITHOUT ROWID;
                CREATE TRIGGER IF NOT EXISTS event_anchor_no_update
                BEFORE UPDATE ON event_anchor
                BEGIN
                    SELECT RAISE(ABORT, 'event_anchor_append_only');
                END;
                CREATE TRIGGER IF NOT EXISTS event_anchor_no_delete
                BEFORE DELETE ON event_anchor
                BEGIN
                    SELECT RAISE(ABORT, 'event_anchor_append_only');
                END;
                CREATE TRIGGER IF NOT EXISTS event_anchor_meta_no_update
                BEFORE UPDATE ON event_anchor_meta
                BEGIN
                    SELECT RAISE(ABORT, 'event_anchor_append_only');
                END;
                CREATE TRIGGER IF NOT EXISTS event_anchor_meta_no_delete
                BEFORE DELETE ON event_anchor_meta
                BEGIN
                    SELECT RAISE(ABORT, 'event_anchor_append_only');
                END;
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO event_anchor_meta(schema, created_at) VALUES (?, ?)",
                (SCHEMA, int(time.time() * 1000)),
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def append(
        self,
        *,
        user_id: str,
        run_id: str,
        anchor: dict[str, Any],
        final: bool = False,
        created_at: int | None = None,
    ) -> dict[str, Any]:
        value = _anchor(anchor)
        if value["run_id"] != str(run_id or ""):
            raise EventAnchorStoreError("anchor_scope_mismatch", "Anchor run_id does not match the store scope.")
        principal_hash = _scope("principal", user_id)
        run_hash = _scope("run", run_id)
        timestamp = int(created_at if created_at is not None else time.time() * 1000)
        self.initialize()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                """
                SELECT * FROM event_anchor
                 WHERE principal_hash = ? AND run_hash = ?
                 ORDER BY checkpoint DESC LIMIT 1
                """,
                (principal_hash, run_hash),
            ).fetchone()
            if latest is not None:
                if int(latest["declared"]) == value["declared"] and str(latest["head"]) == value["head"]:
                    if bool(latest["final"]) != bool(final):
                        connection.rollback()
                        raise EventAnchorStoreError(
                            "anchor_finalization_mismatch",
                            "An idempotent anchor retry must preserve finalization.",
                        )
                    connection.commit()
                    return self._public(latest, idempotent=True)
                if bool(latest["final"]):
                    connection.rollback()
                    raise EventAnchorStoreError("anchor_run_finalized", "A finalized run cannot accept another anchor.")
                if value["declared"] <= int(latest["declared"]):
                    connection.rollback()
                    raise EventAnchorStoreError(
                        "anchor_declared_not_monotonic",
                        "Anchor declared count must increase for each checkpoint.",
                    )
                checkpoint = int(latest["checkpoint"]) + 1
                previous_record = str(latest["record_digest"])
            else:
                checkpoint = 1
                previous_record = ZERO_RECORD
            if checkpoint > MAX_CHECKPOINTS_PER_RUN:
                connection.rollback()
                raise EventAnchorStoreError(
                    "anchor_checkpoint_bound_exceeded",
                    f"A run cannot exceed {MAX_CHECKPOINTS_PER_RUN} anchor checkpoints.",
                )
            record_digest = _record_digest(
                principal_hash=principal_hash,
                run_hash=run_hash,
                checkpoint=checkpoint,
                declared=value["declared"],
                head=value["head"],
                previous_record=previous_record,
                final=bool(final),
                created_at=timestamp,
            )
            connection.execute(
                """
                INSERT INTO event_anchor(
                    principal_hash, run_hash, checkpoint, declared, head,
                    previous_record, record_digest, final, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    principal_hash, run_hash, checkpoint, value["declared"], value["head"],
                    previous_record, record_digest, int(bool(final)), timestamp,
                ),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT * FROM event_anchor
                 WHERE principal_hash = ? AND run_hash = ? AND checkpoint = ?
                """,
                (principal_hash, run_hash, checkpoint),
            ).fetchone()
            return self._public(row, idempotent=False)

    @staticmethod
    def _public(row: sqlite3.Row, *, idempotent: bool) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "status": "stored",
            "checkpoint": int(row["checkpoint"]),
            "declared": int(row["declared"]),
            "head": str(row["head"]),
            "record_digest": str(row["record_digest"]),
            "final": bool(row["final"]),
            "created_at": int(row["created_at"]),
            "idempotent": idempotent,
        }

    def latest(self, *, user_id: str, run_id: str) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        with self._connect(read_only=True) as connection:
            row = connection.execute(
                """
                SELECT * FROM event_anchor
                 WHERE principal_hash = ? AND run_hash = ?
                 ORDER BY checkpoint DESC LIMIT 1
                """,
                (_scope("principal", user_id), _scope("run", run_id)),
            ).fetchone()
        if row is None:
            return None
        return {
            **self._public(row, idempotent=False),
            "anchor": {
                "schema": event_integrity.ANCHOR_SCHEMA,
                "algorithm": event_integrity.ALGORITHM,
                "run_id": str(run_id),
                "declared": int(row["declared"]),
                "head": str(row["head"]),
            },
        }

    def verify_chain(self, *, user_id: str, run_id: str) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema": f"{SCHEMA}.verification",
                "status": "missing",
                "ok": False,
                "checkpoints": 0,
                "failures": ["store_missing"],
            }
        principal_hash = _scope("principal", user_id)
        run_hash = _scope("run", run_id)
        with self._connect(read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT * FROM event_anchor
                 WHERE principal_hash = ? AND run_hash = ?
                 ORDER BY checkpoint
                """,
                (principal_hash, run_hash),
            ).fetchall()
        failures: list[str] = []
        previous_record = ZERO_RECORD
        previous_declared = 0
        finalized = False
        for expected_checkpoint, row in enumerate(rows, start=1):
            checkpoint = int(row["checkpoint"])
            declared = int(row["declared"])
            if checkpoint != expected_checkpoint:
                failures.append(f"checkpoint:{expected_checkpoint}")
            if declared <= previous_declared:
                failures.append(f"declared:{checkpoint}")
            if str(row["previous_record"]) != previous_record:
                failures.append(f"previous:{checkpoint}")
            expected_digest = _record_digest(
                principal_hash=principal_hash,
                run_hash=run_hash,
                checkpoint=checkpoint,
                declared=declared,
                head=str(row["head"]),
                previous_record=str(row["previous_record"]),
                final=bool(row["final"]),
                created_at=int(row["created_at"]),
            )
            if str(row["record_digest"]) != expected_digest:
                failures.append(f"digest:{checkpoint}")
            if finalized:
                failures.append(f"after_final:{checkpoint}")
            finalized = bool(row["final"])
            previous_record = str(row["record_digest"])
            previous_declared = declared
        return {
            "schema": f"{SCHEMA}.verification",
            "status": "pass" if rows and not failures else "fail" if rows else "missing",
            "ok": bool(rows) and not failures,
            "checkpoints": len(rows),
            "declared": previous_declared,
            "record_digest": previous_record if rows else "",
            "final": finalized,
            "failures": failures,
        }
