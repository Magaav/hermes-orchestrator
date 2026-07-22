"""Trusted read-only run-store collector for the bounded runtime snapshot contract."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import runtime_snapshot

MAX_SCAN_ROWS = 64
TERMINAL = frozenset({"completed", "failed", "interrupted", "cancelled"})


class CollectorError(RuntimeError):
    """The scoped read-only runtime source could not produce a snapshot."""


def _iso(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _route_id(summary_text: str) -> str:
    try:
        summary = json.loads(summary_text or "{}")
    except (TypeError, ValueError):
        return ""
    if not isinstance(summary, dict):
        return ""
    direct = str(summary.get("route_id") or "").strip()
    if direct:
        return direct
    envelope = summary.get("envelope") if isinstance(summary.get("envelope"), dict) else {}
    return str(envelope.get("route_id") or "").strip()


def proof_reference(route_id: str, entity_id: str, row: sqlite3.Row) -> dict[str, str]:
    compact = {
        "route_id": route_id,
        "entity_id": entity_id,
        "status": str(row["status"] or "unknown"),
        "created_at": int(row["created_at"] or 0),
        "updated_at": int(row["updated_at"] or 0),
        "terminal_at": int(row["terminal_at"] or 0),
    }
    digest = hashlib.sha256(json.dumps(compact, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    proof_id = f"run-store-{digest[:24]}"
    return {
        "id": proof_id,
        "kind": "scoped_run_history",
        "digest": f"sha256:{digest}",
        "lookup": f"runtime.proof.get:{proof_id}",
    }


def scoped_rows(db_path: Path, *, user_id: str, route_id: str) -> list[sqlite3.Row]:
    """Return only bounded rows in the trusted adapter; callers must not project them."""
    if not db_path.is_file():
        raise CollectorError("runtime_store_unavailable")
    if not user_id.strip() or not route_id.strip():
        raise CollectorError("runtime_scope_invalid")
    try:
        connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(agent_run_tb)")}
        required = {"user_id", "status", "created_at", "updated_at", "terminal_at", "request_summary_json"}
        if not required <= columns:
            raise CollectorError("runtime_store_schema_invalid")
        rows = connection.execute(
            """SELECT status,created_at,updated_at,terminal_at,request_summary_json
                 FROM agent_run_tb WHERE user_id=? ORDER BY updated_at DESC LIMIT ?""",
            (user_id, MAX_SCAN_ROWS),
        ).fetchall()
    except sqlite3.Error as exc:
        raise CollectorError("runtime_store_read_failed") from exc
    finally:
        if "connection" in locals():
            connection.close()
    return [row for row in rows if _route_id(str(row["request_summary_json"] or "{}")) == route_id]


def collect(
    db_path: Path,
    *,
    user_id: str,
    route_id: str,
    entity_id: str,
    entity_kind: str,
    now_ms: int,
    max_age_ms: int = 30_000,
) -> dict[str, Any]:
    if not user_id.strip() or not route_id.strip() or not entity_id.strip() or not entity_kind.strip():
        raise CollectorError("runtime_scope_invalid")
    if now_ms < 0 or max_age_ms < 1 or max_age_ms > 86_400_000:
        raise CollectorError("runtime_freshness_invalid")
    matched = scoped_rows(db_path, user_id=user_id, route_id=route_id)
    counters = {
        "runs": len(matched),
        "active": sum(str(row["status"] or "") not in TERMINAL for row in matched),
        "completed": sum(str(row["status"] or "") == "completed" for row in matched),
        "failed": sum(str(row["status"] or "") in {"failed", "interrupted", "cancelled"} for row in matched),
    }
    proof_refs = [proof_reference(route_id, entity_id, matched[0])] if matched else []
    unknowns = [{"code": "live_state_not_collected", "field": "status"}]
    if not matched:
        unknowns.append({"code": "entity_not_observed", "field": "run_history"})
    raw = {
        "entity": {"route_id": route_id, "id": entity_id, "kind": entity_kind},
        "status": "degraded" if matched else "unknown",
        "freshness": {"state": "fresh", "observed_at": _iso(now_ms), "age_ms": 0, "max_age_ms": max_age_ms, "trusted": True},
        "capabilities": {"run_history.read": True, "runtime.live_state": False, "runtime.control": False},
        "counters": counters,
        "proof_refs": proof_refs,
        "unknowns": unknowns,
        "redaction": {"applied": True, "class": "scoped-run-aggregate-v1"},
    }
    return runtime_snapshot.normalize(raw)
