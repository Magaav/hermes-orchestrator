"""Executable V6 kernel over injected repository, client, and MCP adapters."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
from typing import Any, Callable

from . import catalog, contracts, dag, evidence, expectations, redaction, schema, state as working_state


Executor = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
CommentarySink = Callable[[dict[str, Any]], None]
EventSink = Callable[[dict[str, Any]], None]


class Kernel:
    def __init__(self, *, authorities: set[str], commentary_sink: CommentarySink | None = None, event_sink: EventSink | None = None, max_parallel: int = 8, redact: Callable[[Any], Any] = redaction.apply, completion_requirements: set[str] | None = None, cancel_event: threading.Event | None = None) -> None:
        self.catalog = catalog.Catalog()
        self.evidence = evidence.EvidenceStore()
        self.authorities = {str(item) for item in authorities}
        self.commentary_sink = commentary_sink
        self.event_sink = event_sink
        self.max_parallel = max(1, min(int(max_parallel), 32))
        self.executors: dict[str, Executor] = {}
        self.cancel = cancel_event if cancel_event is not None else threading.Event()
        self._commentary_seen: set[str] = set()
        self._redact = redact
        self._ledger_lock = threading.Lock()
        self._operation_ledger: dict[str, dict[str, Any]] = {}
        self._operation_sequence = 0
        self.completion_requirements = {str(item) for item in (completion_requirements or set())}

    def register(self, capability: dict[str, Any], executor: Executor) -> dict[str, Any]:
        item = self.catalog.register(capability)
        self.executors[item["executor"]] = executor
        return item

    def _admit(self, operation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        normalized = contracts.operation(operation)
        capability = self.catalog.get(normalized["cap"])
        if capability is None:
            raise contracts.ContractError("kernel_capability_missing")
        if capability["authority"] not in self.authorities:
            raise contracts.ContractError("kernel_authority_denied")
        if capability["executor"] not in self.executors:
            raise contracts.ContractError("kernel_executor_missing")
        schema.validate(normalized["args"], capability.get("input") or {"type": "object"})
        return normalized, capability

    def _say(self, operation: dict[str, Any]) -> None:
        update = operation.get("say") if isinstance(operation.get("say"), dict) else None
        if update is None or self.commentary_sink is None:
            return
        key = contracts.digest({"phase": update["phase"], "message": update["message"], "op": operation["id"]})
        if key in self._commentary_seen:
            return
        self._commentary_seen.add(key)
        self.commentary_sink({
            "schema": "master.frontier.v6.commentary.v1", "authored_by": "model",
            "visibility": "public", "operation": operation["id"], **update,
        })

    def _execute_one(self, operation: dict[str, Any], capability: dict[str, Any]) -> dict[str, Any]:
        operation_digest = contracts.digest({key: operation.get(key) for key in ("id", "cap", "args", "after", "expect", "completes_goal", "goal_id")})
        with self._ledger_lock:
            existing = self._operation_ledger.get(operation["id"])
            if existing is not None:
                if existing["digest"] != operation_digest:
                    return contracts.receipt({
                        "id": f"rcpt:{operation['id']}:redefined", "op": operation["id"], "ok": False,
                        "state": "rejected", "error": {"code": "operation_redefined"},
                    })
                if isinstance(existing.get("receipt"), dict):
                    if self.event_sink:
                        self.event_sink({"type": "operation.replayed", "operation": operation["id"], "capability": capability["id"], "receipt": existing["receipt"]["id"]})
                    return contracts.receipt(existing["receipt"])
                return contracts.receipt({
                    "id": f"rcpt:{operation['id']}:inflight", "op": operation["id"], "ok": False,
                    "state": "pending", "error": {"code": "operation_inflight"},
                })
            self._operation_sequence += 1
            self._operation_ledger[operation["id"]] = {
                "digest": operation_digest, "receipt": None, "operation": operation,
                "capability": capability["id"], "sequence": self._operation_sequence,
            }
        if self.cancel.is_set():
            receipt = contracts.receipt({
                "id": f"rcpt:{operation['id']}:cancelled", "op": operation["id"], "ok": False,
                "state": "cancelled", "error": {"code": "run_cancelled"},
            })
        else:
            self._say(operation)
            if self.event_sink:
                self.event_sink({
                    "type": "operation.started", "operation": operation["id"],
                    "model_operation_id": operation["id"], "capability": capability["id"],
                    "completes_goal": operation.get("completes_goal") is True,
                })
            try:
                raw = self._redact(self.executors[capability["executor"]](capability, operation))
                if not isinstance(raw, dict):
                    raw = {"ok": False, "error": {"code": "executor_result_invalid"}}
                observed = raw.get("observed") if isinstance(raw.get("observed"), dict) else raw.get("result") if isinstance(raw.get("result"), dict) else {}
                ok = raw.get("ok") is True
                state = str(raw.get("state") or ("completed" if ok else "failed"))
                proof = raw.get("proof") if isinstance(raw.get("proof"), list) else []
                error = raw.get("error") if isinstance(raw.get("error"), dict) else {}
                if ok and operation["expect"] and not expectations.satisfied(operation["expect"], observed):
                    ok, state, error = False, "failed", {"code": "expectation_mismatch", "expected": operation["expect"]}
                receipt = contracts.receipt({
                    "id": str(raw.get("id") or f"rcpt:{operation['id']}"), "op": operation["id"],
                    "ok": ok, "state": state, "observed": observed, "proof": proof, "error": error,
                })
            except Exception as exc:
                safe_error = self._redact(str(exc)[:500])
                receipt = contracts.receipt({
                    "id": f"rcpt:{operation['id']}:error", "op": operation["id"], "ok": False,
                    "state": "failed", "error": {"code": "executor_error", "message": safe_error},
                })
        with self._ledger_lock:
            entry = self._operation_ledger[operation["id"]]
            self._operation_ledger[operation["id"]] = {**entry, "receipt": receipt}
        if self.event_sink:
            self.event_sink({
                "type": "operation.completed", "operation": operation["id"],
                "model_operation_id": operation["id"],
                "capability": capability["id"], "ok": receipt["ok"],
                "state": receipt["state"], "receipt": receipt["id"],
                "completes_goal": operation.get("completes_goal") is True,
            })
        return receipt

    def execute(self, current: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
        admitted: list[dict[str, Any]] = []
        capabilities: dict[str, dict[str, Any]] = {}
        for raw in operations:
            operation, capability = self._admit(raw)
            admitted.append(operation)
            capabilities[capability["id"]] = capability
        def invoke_wave(wave: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if not wave:
                return []
            with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(wave)), thread_name_prefix="mf6") as pool:
                futures = [pool.submit(self._execute_one, item, capabilities[item["cap"]]) for item in wave]
                return [future.result() for future in futures]

        receipts = dag.execute(capabilities, admitted, invoke_wave)
        evidence_items = []
        for receipt in receipts:
            item = self.evidence.put(
                kind="operation.receipt", subject=f"operation:{receipt['op']}",
                summary=f"{receipt['state']} ({'ok' if receipt['ok'] else 'not-ok'})",
                detail=receipt, proof=receipt.get("proof") or [],
            )
            evidence_items.append(item)
        successful = [item["id"] for item, receipt in zip(evidence_items, receipts) if receipt["ok"]]
        failed = [receipt["op"] for receipt in receipts if not receipt["ok"]]
        current = working_state.apply(current, working_state.delta(
            current, add_known=successful, add_open=failed,
            status="complete" if receipts and not failed else "blocked" if failed else "complete",
            plan=[item["id"] for item in admitted],
        ))
        return {
            "schema": "master.frontier.v6.execution.v1", "goal": current.get("goal"),
            "state": current, "operations": admitted, "receipts": receipts,
            "evidence": evidence_items, "ok": not failed,
        }

    def run(self, goal: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
        result = self.execute(working_state.initial(goal), operations)
        return {**result, "schema": "master.frontier.v6.run.v1", "goal": goal}

    def completion_gaps(self) -> list[str]:
        with self._ledger_lock:
            entries = sorted(
                (dict(item) for item in self._operation_ledger.values() if isinstance(item.get("receipt"), dict)),
                key=lambda item: int(item.get("sequence") or 0),
            )
        successful = [item for item in entries if item["receipt"].get("ok") is True and item["receipt"].get("state") in {"acknowledged", "completed"}]
        successful_caps = {str(item.get("capability") or "") for item in successful}
        successful_authorities = {
            str(capability.get("authority") or "")
            for item in successful
            if (capability := self.catalog.get(str(item.get("capability") or "")))
        }
        satisfied = {
            requirement
            for requirement in self.completion_requirements
            if (
                requirement.removeprefix("authority:") in successful_authorities
                if requirement.startswith("authority:")
                else requirement in successful_caps
            )
        }
        if "goal_action" in self.completion_requirements and any(
            item.get("operation", {}).get("completes_goal") is True
            and (self.catalog.get(str(item.get("capability") or "")) or {}).get("mode") == "write"
            and set((self.catalog.get(str(item.get("capability") or "")) or {}).get("completion_proof") or []).issubset(set(item["receipt"].get("proof") or []))
            for item in successful
        ):
            satisfied.add("goal_action")
        gaps = [f"completion:{requirement}" for requirement in sorted(self.completion_requirements - satisfied)]
        for entry in successful:
            capability = self.catalog.get(str(entry.get("capability") or "")) or {}
            required = set(capability.get("requires_after") or [])
            if not required:
                continue
            later = {
                str(item.get("capability") or "")
                for item in successful
                if int(item.get("sequence") or 0) > int(entry.get("sequence") or 0)
            }
            gaps.extend(f"after:{entry['operation']['id']}:{item}" for item in sorted(required - later))
        return list(dict.fromkeys(gaps))

    def answer_ready(self, *, viewed_operations: set[str] | None = None) -> bool:
        """Return true only when completion proof is sufficient for final synthesis."""
        if not self.completion_requirements or self.completion_gaps():
            return False
        authority_requirements = {
            item.removeprefix("authority:")
            for item in self.completion_requirements
            if item.startswith("authority:")
        }
        if not authority_requirements:
            return True
        viewed = {str(item) for item in (viewed_operations or set())}
        with self._ledger_lock:
            entries = [dict(item) for item in self._operation_ledger.values()]
        viewed_authorities = {
            str(capability.get("authority") or "")
            for item in entries
            if str((item.get("operation") or {}).get("id") or "") in viewed
            and isinstance(item.get("receipt"), dict)
            and item["receipt"].get("ok") is True
            and item["receipt"].get("state") in {"acknowledged", "completed"}
            if (capability := self.catalog.get(str(item.get("capability") or "")))
        }
        return authority_requirements <= viewed_authorities

    def journal(self) -> list[dict[str, Any]]:
        with self._ledger_lock:
            entries = sorted(self._operation_ledger.values(), key=lambda item: int(item.get("sequence") or 0))
            return [contracts.decode(contracts.canonical(item)) for item in entries]

    def snapshot(self, current: dict[str, Any]) -> dict[str, Any]:
        with self._ledger_lock:
            ledger = {
                operation_id: {
                    "digest": item.get("digest"), "receipt": item.get("receipt"),
                    "operation": {
                        "id": (item.get("operation") or {}).get("id"),
                        "cap": (item.get("operation") or {}).get("cap"),
                        "completes_goal": (item.get("operation") or {}).get("completes_goal") is True,
                    },
                    "capability": item.get("capability"), "sequence": item.get("sequence"),
                }
                for operation_id, item in self._operation_ledger.items()
            }
            ledger = contracts.decode(contracts.canonical(ledger))
        return {
            "schema": "master.frontier.v6.kernel.snapshot.v1", "state": current,
            "evidence": self.evidence.snapshot(), "operation_ledger": ledger,
        }

    def restore(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        if snapshot.get("schema") != "master.frontier.v6.kernel.snapshot.v1":
            raise contracts.ContractError("kernel_snapshot_invalid")
        current = snapshot.get("state") if isinstance(snapshot.get("state"), dict) else None
        if current is None or not str(current.get("id") or "").startswith("st:"):
            raise contracts.ContractError("kernel_snapshot_state_invalid")
        evidence_snapshot = snapshot.get("evidence") if isinstance(snapshot.get("evidence"), dict) else {}
        self.evidence.restore(evidence_snapshot)
        ledger = snapshot.get("operation_ledger") if isinstance(snapshot.get("operation_ledger"), dict) else {}
        rebuilt: dict[str, dict[str, Any]] = {}
        for operation_id, item in ledger.items():
            if not isinstance(item, dict) or not isinstance(item.get("receipt"), dict):
                raise contracts.ContractError("kernel_snapshot_ledger_invalid")
            operation = contracts.operation(item.get("operation") if isinstance(item.get("operation"), dict) else {})
            capability_id = str(item.get("capability") or operation["cap"])
            if self.catalog.get(capability_id) is None:
                raise contracts.ContractError("kernel_snapshot_capability_missing")
            rebuilt[str(operation_id)] = {
                "digest": str(item.get("digest") or ""), "receipt": contracts.receipt(item["receipt"]),
                "operation": operation, "capability": capability_id,
                "sequence": max(1, int(item.get("sequence") or 0)),
            }
        with self._ledger_lock:
            self._operation_ledger = rebuilt
            self._operation_sequence = max((int(item.get("sequence") or 0) for item in rebuilt.values()), default=0)
        return contracts.decode(contracts.canonical(current))
