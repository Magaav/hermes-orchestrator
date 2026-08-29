"""Disposable V7 thesis pilot: compile verified trajectories into procedures."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable


SCHEMA = "master.frontier.v7.procedure.v1"
MAP_SCHEMA = "master.frontier.v7.procedure-map.v1"
RECEIPT_STATES = {"acknowledged", "completed"}


class ProcedureError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _bounded_text(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit]


def compile_success(
    *, intent: dict[str, Any], operation: dict[str, Any], receipt: dict[str, Any],
    account_scope: str, environment: dict[str, str], source: dict[str, str],
) -> dict[str, Any]:
    """Compile one proof-complete terminal operation; never compile its answer."""
    capability = str(operation.get("cap") or "")
    required_proof = sorted({str(item) for item in (operation.get("required_proof") or []) if str(item)})
    observed_proof = set(str(item) for item in (receipt.get("proof") or []))
    if not capability or not required_proof:
        raise ProcedureError("procedure_contract_incomplete")
    if not (
        receipt.get("ok") is True
        and str(receipt.get("state") or "") in RECEIPT_STATES
        and set(required_proof) <= observed_proof
    ):
        raise ProcedureError("trajectory_not_proof_complete")
    intent_id = str(intent.get("id") or "")
    if not intent_id:
        raise ProcedureError("intent_contract_missing")
    procedure_id = f"proc:{digest({'account_scope': account_scope, 'intent': intent, 'cap': capability, 'environment': environment})[:24]}"
    body = {
        "schema": SCHEMA,
        "id": procedure_id,
        "intent": {
            "id": intent_id,
            "required": dict(intent.get("required") or {}),
            "forbidden": dict(intent.get("forbidden") or {}),
            "arguments": dict(intent.get("arguments") or {}),
        },
        "account_scope": str(account_scope),
        "environment": dict(environment),
        "operation": {
            "cap": capability,
            "args": dict(operation.get("args") or {}),
            "argument_fields": sorted(str(item) for item in (operation.get("argument_fields") or [])),
        },
        "required_proof": required_proof,
        "authorization": str(operation.get("authorization") or "reviewed"),
        "source": {
            "run_id": str(source.get("run_id") or ""),
            "trajectory_head": str(source.get("trajectory_head") or ""),
        },
        "state": "candidate",
        "successes": 1,
        "failures": 0,
        "created_at": int(time.time()),
    }
    return {**body, "digest": digest(body)}


class Registry:
    """SQLite-backed cross-session registry; session identity is intentionally absent."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS procedure_tb (
              id TEXT PRIMARY KEY, account_scope TEXT NOT NULL, intent_id TEXT NOT NULL,
              state TEXT NOT NULL, digest TEXT NOT NULL, payload_json TEXT NOT NULL,
              successes INTEGER NOT NULL, failures INTEGER NOT NULL, updated_at INTEGER NOT NULL
            )
        """)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def save(self, procedure: dict[str, Any]) -> dict[str, Any]:
        self.connection.execute(
            """INSERT INTO procedure_tb VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json,
                 state=excluded.state,digest=excluded.digest,successes=excluded.successes,
                 failures=excluded.failures,updated_at=excluded.updated_at""",
            (
                procedure["id"], procedure["account_scope"], procedure["intent"]["id"],
                procedure["state"], procedure["digest"], canonical(procedure),
                int(procedure["successes"]), int(procedure["failures"]), int(time.time()),
            ),
        )
        self.connection.commit()
        return procedure

    def get(self, procedure_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT payload_json FROM procedure_tb WHERE id=?", (procedure_id,),
        ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def calibrate(self, procedure_id: str) -> dict[str, Any]:
        procedure = self.get(procedure_id)
        if not procedure:
            raise ProcedureError("procedure_missing")
        procedure["successes"] = int(procedure.get("successes") or 0) + 1
        procedure["state"] = "promoted" if procedure["successes"] >= 2 else "calibrated"
        unsigned = {key: value for key, value in procedure.items() if key != "digest"}
        procedure["digest"] = digest(unsigned)
        return self.save(procedure)

    def prune(self, procedure_id: str, reason: str) -> dict[str, Any]:
        procedure = self.get(procedure_id)
        if not procedure:
            raise ProcedureError("procedure_missing")
        procedure["state"] = "pruned"
        procedure["failures"] = int(procedure.get("failures") or 0) + 1
        procedure["pruned_reason"] = _bounded_text(reason, 160)
        unsigned = {key: value for key, value in procedure.items() if key != "digest"}
        procedure["digest"] = digest(unsigned)
        return self.save(procedure)

    def compact_map(self, account_scope: str) -> dict[str, Any]:
        rows = self.connection.execute(
            """SELECT payload_json FROM procedure_tb
               WHERE account_scope=? AND state IN ('candidate','calibrated','promoted')
               ORDER BY intent_id,id LIMIT 64""",
            (account_scope,),
        ).fetchall()
        procedures = [json.loads(row["payload_json"]) for row in rows]
        return {
            "schema": MAP_SCHEMA,
            "count": len(procedures),
            "procedures": [{
                "id": item["id"], "intent": item["intent"]["id"],
                "cap": item["operation"]["cap"], "state": item["state"],
                "in": item["operation"]["argument_fields"],
                "proof": item["required_proof"], "d": item["digest"][:12],
            } for item in procedures],
        }

    def match(
        self, *, account_scope: str, intent: dict[str, Any], environment: dict[str, str],
    ) -> dict[str, Any]:
        rows = self.connection.execute(
            """SELECT payload_json FROM procedure_tb
               WHERE account_scope=? AND intent_id=? AND state='promoted'""",
            (account_scope, str(intent.get("id") or "")),
        ).fetchall()
        compatible = []
        for row in rows:
            procedure = json.loads(row["payload_json"])
            if procedure["environment"] != environment:
                self.prune(procedure["id"], "environment_or_capability_digest_changed")
                continue
            values = dict(intent.get("values") or {})
            if any(values.get(key) != value for key, value in procedure["intent"]["required"].items()):
                continue
            if any(values.get(key) == value for key, value in procedure["intent"]["forbidden"].items()):
                continue
            compatible.append(procedure)
        if not compatible:
            raise ProcedureError("procedure_rediscovery_required")
        if len(compatible) != 1:
            raise ProcedureError("procedure_match_ambiguous")
        return compatible[0]


def execute(
    procedure: dict[str, Any], *, intent: dict[str, Any],
    invoke: Callable[[str, dict[str, Any]], dict[str, Any]], registry: Registry,
) -> dict[str, Any]:
    args = dict(procedure["operation"]["args"])
    values = dict(intent.get("values") or {})
    for field in procedure["operation"]["argument_fields"]:
        if field not in values:
            raise ProcedureError(f"procedure_argument_missing:{field}")
        args[field] = values[field]
    receipt = invoke(procedure["operation"]["cap"], args)
    proof = set(str(item) for item in (receipt.get("proof") or []))
    if not (
        receipt.get("ok") is True
        and str(receipt.get("state") or "") in RECEIPT_STATES
        and set(procedure["required_proof"]) <= proof
    ):
        registry.prune(procedure["id"], "fresh_proof_failed")
        raise ProcedureError("procedure_fresh_proof_failed")
    answer = _bounded_text((receipt.get("observed") or {}).get("answer"), 600)
    if not answer:
        raise ProcedureError("procedure_answer_missing")
    return {
        "ok": True, "answer": answer, "receipt": receipt,
        "procedure_id": procedure["id"], "provider_calls": 0,
    }
