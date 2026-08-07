"""Scope-bound server persistence for V6 kernel/controller snapshots."""
from __future__ import annotations

import hashlib
import json
import time
import zlib
from typing import Any, Callable

from . import contracts


SNAPSHOT_SCHEMA = "master.frontier.v6.controller.snapshot.v1"
REF_SCHEMA = "master.frontier.v6.checkpoint.ref.v1"
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_COMPRESSED_BYTES = 4 * 1024 * 1024
Connect = Callable[[], Any]


class PersistenceError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def route_digest(route: dict[str, Any]) -> str:
    return contracts.digest({
        key: route.get(key)
        for key in ("route_id", "owner", "workspace_root", "allowed_read_roots", "allowed_write_roots", "caps", "checks", "client_ui", "mcp")
    })


def _ensure(conn: Any) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS master_frontier_v6_snapshot_tb (
          run_id TEXT PRIMARY KEY,
          turn_id TEXT NOT NULL,
          user_id TEXT NOT NULL,
          session_id TEXT NOT NULL,
          route_id TEXT NOT NULL,
          route_digest TEXT NOT NULL,
          snapshot_sha256 TEXT NOT NULL,
          snapshot_zlib BLOB NOT NULL,
          updated_at INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS master_frontier_v6_snapshot_scope_idx ON master_frontier_v6_snapshot_tb(user_id, session_id, route_id, updated_at)")


def save(
    connect: Connect, *, user_id: str, session_id: str, route: dict[str, Any],
    run_id: str, turn_id: str, snapshot: dict[str, Any],
) -> dict[str, Any]:
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise PersistenceError("v6_snapshot_schema_invalid")
    raw = contracts.canonical(snapshot).encode("utf-8")
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise PersistenceError("v6_snapshot_too_large")
    compressed = zlib.compress(raw, level=6)
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise PersistenceError("v6_snapshot_compressed_too_large")
    sha256 = hashlib.sha256(raw).hexdigest()
    digest = route_digest(route)
    with connect() as conn:
        _ensure(conn)
        conn.execute("""
            INSERT INTO master_frontier_v6_snapshot_tb (
              run_id, turn_id, user_id, session_id, route_id, route_digest,
              snapshot_sha256, snapshot_zlib, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
              turn_id=excluded.turn_id, user_id=excluded.user_id, session_id=excluded.session_id,
              route_id=excluded.route_id, route_digest=excluded.route_digest,
              snapshot_sha256=excluded.snapshot_sha256, snapshot_zlib=excluded.snapshot_zlib,
              updated_at=excluded.updated_at
        """, (
            str(run_id), str(turn_id), str(user_id), str(session_id), str(route.get("route_id") or ""), digest,
            sha256, compressed, int(time.time() * 1000),
        ))
    return {
        "schema": REF_SCHEMA, "protocol": "v6", "source_run_id": str(run_id),
        "source_turn_id": str(turn_id), "sha256": sha256,
    }


def load(
    connect: Connect, *, user_id: str, session_id: str, route: dict[str, Any],
    source_run_id: str, expected_sha256: str = "",
) -> dict[str, Any]:
    with connect() as conn:
        _ensure(conn)
        row = conn.execute("""
            SELECT * FROM master_frontier_v6_snapshot_tb
             WHERE run_id = ? AND user_id = ? AND session_id = ? AND route_id = ?
        """, (str(source_run_id), str(user_id), str(session_id), str(route.get("route_id") or ""))).fetchone()
    if not row:
        raise PersistenceError("v6_checkpoint_not_found")
    if str(row["route_digest"]) != route_digest(route):
        raise PersistenceError("v6_checkpoint_route_stale")
    compressed = bytes(row["snapshot_zlib"])
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise PersistenceError("v6_checkpoint_compressed_too_large")
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(compressed, MAX_SNAPSHOT_BYTES + 1)
    if len(raw) > MAX_SNAPSHOT_BYTES or decompressor.unconsumed_tail:
        raise PersistenceError("v6_checkpoint_too_large")
    sha256 = hashlib.sha256(raw).hexdigest()
    if sha256 != str(row["snapshot_sha256"]) or (expected_sha256 and sha256 != expected_sha256):
        raise PersistenceError("v6_checkpoint_digest_mismatch")
    try:
        snapshot = contracts.decode(raw.decode("utf-8"), max_bytes=MAX_SNAPSHOT_BYTES)
    except (UnicodeDecodeError, contracts.ContractError) as exc:
        raise PersistenceError("v6_checkpoint_invalid") from exc
    if not isinstance(snapshot, dict) or snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise PersistenceError("v6_checkpoint_invalid")
    return snapshot
