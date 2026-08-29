"""Exact-repeat, proof-bound procedure memory for terminal read capabilities."""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Callable

from . import contracts, persistence


SCHEMA = "master.frontier.v6.procedure-memory.v1"
Connect = Callable[[], Any]
ACTIVE_STATES = frozenset({"candidate", "promoted"})
SUCCESS_STATES = frozenset({"acknowledged", "completed"})


def enabled() -> bool:
    return os.environ.get("MF_V6_PROCEDURE_MEMORY", "1").strip().lower() not in {"0", "false", "no", "off"}


def normalize_objective(value: Any) -> str:
    return " ".join(str(value or "").split())[:2_000]


def objective_digest(value: Any) -> str:
    return hashlib.sha256(normalize_objective(value).encode("utf-8")).hexdigest()


def environment_digest(route: dict[str, Any], topology: dict[str, Any]) -> str:
    return contracts.digest({
        "route": persistence.route_digest(route),
        "topology": topology if isinstance(topology, dict) else {},
    })


def capability_digest(capability: dict[str, Any]) -> str:
    return contracts.digest({
        key: capability.get(key)
        for key in (
            "id", "kind", "authority", "executor", "mode", "input", "result",
            "proof", "terminal_result", "authorization", "requires_after",
        )
    })


def _ensure(conn: Any) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS master_frontier_v6_procedure_tb (
          user_id TEXT NOT NULL,
          route_id TEXT NOT NULL,
          objective_sha256 TEXT NOT NULL,
          environment_digest TEXT NOT NULL,
          capability_id TEXT NOT NULL,
          capability_digest TEXT NOT NULL,
          args_json TEXT NOT NULL,
          proof_json TEXT NOT NULL,
          state TEXT NOT NULL,
          successes INTEGER NOT NULL,
          last_run_id TEXT NOT NULL,
          updated_at INTEGER NOT NULL,
          PRIMARY KEY (user_id, route_id, objective_sha256)
        )
    """)


def _decode(row: Any) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "user_id": str(row["user_id"]),
        "route_id": str(row["route_id"]),
        "objective_sha256": str(row["objective_sha256"]),
        "environment_digest": str(row["environment_digest"]),
        "capability_id": str(row["capability_id"]),
        "capability_digest": str(row["capability_digest"]),
        "args": json.loads(str(row["args_json"] or "{}")),
        "proof": json.loads(str(row["proof_json"] or "[]")),
        "state": str(row["state"]),
        "successes": int(row["successes"] or 0),
        "last_run_id": str(row["last_run_id"]),
    }


def lookup(
    connect: Connect, *, user_id: str, route: dict[str, Any], objective: str,
    topology: dict[str, Any], catalog: Any,
) -> dict[str, Any] | None:
    if not user_id or not normalize_objective(objective):
        return None
    key = objective_digest(objective)
    route_id = str(route.get("route_id") or "")
    with connect() as conn:
        _ensure(conn)
        row = conn.execute(
            """SELECT * FROM master_frontier_v6_procedure_tb
                 WHERE user_id=? AND route_id=? AND objective_sha256=? AND state='promoted'""",
            (user_id, route_id, key),
        ).fetchone()
        if not row:
            return None
        procedure = _decode(row)
        capability = catalog.get(procedure["capability_id"])
        valid = bool(
            isinstance(capability, dict)
            and procedure["environment_digest"] == environment_digest(route, topology)
            and procedure["capability_digest"] == capability_digest(capability)
            and capability.get("mode") == "read"
            and capability.get("terminal_result") is True
            and not ((capability.get("input") or {}).get("required") or [])
        )
        if valid:
            return procedure
        conn.execute(
            """UPDATE master_frontier_v6_procedure_tb SET state='pruned',updated_at=?
                 WHERE user_id=? AND route_id=? AND objective_sha256=?""",
            (int(time.time() * 1000), user_id, route_id, key),
        )
    return None


def prune(connect: Connect, procedure: dict[str, Any]) -> None:
    with connect() as conn:
        _ensure(conn)
        conn.execute(
            """UPDATE master_frontier_v6_procedure_tb SET state='pruned',updated_at=?
                 WHERE user_id=? AND route_id=? AND objective_sha256=?""",
            (
                int(time.time() * 1000), procedure["user_id"], procedure["route_id"],
                procedure["objective_sha256"],
            ),
        )


def replay(connect: Connect, procedure: dict[str, Any], *, agent: Any, objective: str) -> dict[str, Any] | None:
    capability = agent.catalog.get(procedure["capability_id"]) or {}
    operation = {
        "id": f"procedure:{procedure['objective_sha256'][:16]}",
        "cap": procedure["capability_id"],
        "args": dict(procedure.get("args") or {}),
    }
    result = agent.run(objective, [operation])
    receipts = result.get("receipts") if isinstance(result.get("receipts"), list) else []
    receipt = receipts[0] if len(receipts) == 1 and isinstance(receipts[0], dict) else {}
    required_proof = set(str(item) for item in (procedure.get("proof") or []))
    observed_proof = set(str(item) for item in (receipt.get("proof") or []))
    observed = receipt.get("observed") if isinstance(receipt.get("observed"), dict) else {}
    answer = " ".join(str(observed.get("answer") or "").split())[:600]
    valid = bool(
        capability.get("mode") == "read"
        and receipt.get("ok") is True
        and str(receipt.get("state") or "") in SUCCESS_STATES
        and required_proof
        and required_proof <= observed_proof
        and not agent.completion_gaps()
        and answer
    )
    if not valid:
        prune(connect, procedure)
        return None
    return {
        "ok": True,
        "schema": "master.frontier.v6.controller.v1",
        "answer": answer,
        "state": result["state"],
        "trace": [],
        "evidence": agent.evidence.list(),
        "procedure_replay": {
            "schema": SCHEMA,
            "objective_sha256": procedure["objective_sha256"],
            "capability": procedure["capability_id"],
            "fresh_proof": sorted(observed_proof),
        },
    }


def observe_success(
    connect: Connect, *, user_id: str, route: dict[str, Any], objective: str,
    topology: dict[str, Any], run_id: str, journal: list[dict[str, Any]], catalog: Any,
) -> dict[str, Any] | None:
    if not user_id or not normalize_objective(objective) or not run_id or len(journal) != 1:
        return None
    entry = journal[0] if isinstance(journal[0], dict) else {}
    operation = entry.get("operation") if isinstance(entry.get("operation"), dict) else {}
    receipt = entry.get("receipt") if isinstance(entry.get("receipt"), dict) else {}
    capability_id = str(entry.get("capability") or operation.get("cap") or "")
    capability = catalog.get(capability_id) or {}
    required_proof = sorted({str(item) for item in (capability.get("proof") or []) if str(item)})
    observed_proof = set(str(item) for item in (receipt.get("proof") or []))
    args = operation.get("args") if isinstance(operation.get("args"), dict) else {}
    eligible = bool(
        capability_id
        and capability.get("mode") == "read"
        and capability.get("terminal_result") is True
        and not ((capability.get("input") or {}).get("required") or [])
        and receipt.get("ok") is True
        and str(receipt.get("state") or "") in SUCCESS_STATES
        and required_proof
        and set(required_proof) <= observed_proof
        and isinstance(args, dict)
    )
    if not eligible:
        return None
    key = objective_digest(objective)
    route_id = str(route.get("route_id") or "")
    env_digest = environment_digest(route, topology)
    cap_digest = capability_digest(capability)
    now = int(time.time() * 1000)
    with connect() as conn:
        _ensure(conn)
        row = conn.execute(
            """SELECT * FROM master_frontier_v6_procedure_tb
                 WHERE user_id=? AND route_id=? AND objective_sha256=?""",
            (user_id, route_id, key),
        ).fetchone()
        same = bool(
            row
            and str(row["environment_digest"]) == env_digest
            and str(row["capability_id"]) == capability_id
            and str(row["capability_digest"]) == cap_digest
            and str(row["args_json"]) == contracts.canonical(args)
            and str(row["proof_json"]) == contracts.canonical(required_proof)
        )
        successes = int(row["successes"] or 0) if same else 0
        last_run_id = str(row["last_run_id"] or "") if same else ""
        if run_id != last_run_id:
            successes += 1
        state = "promoted" if successes >= 2 else "candidate"
        conn.execute(
            """INSERT INTO master_frontier_v6_procedure_tb VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id,route_id,objective_sha256) DO UPDATE SET
                 environment_digest=excluded.environment_digest,
                 capability_id=excluded.capability_id,
                 capability_digest=excluded.capability_digest,
                 args_json=excluded.args_json,
                 proof_json=excluded.proof_json,
                 state=excluded.state,
                 successes=excluded.successes,
                 last_run_id=excluded.last_run_id,
                 updated_at=excluded.updated_at""",
            (
                user_id, route_id, key, env_digest, capability_id, cap_digest,
                contracts.canonical(args), contracts.canonical(required_proof), state,
                successes, run_id, now,
            ),
        )
    return {
        "schema": SCHEMA, "state": state, "successes": successes,
        "objective_sha256": key, "capability": capability_id,
    }
