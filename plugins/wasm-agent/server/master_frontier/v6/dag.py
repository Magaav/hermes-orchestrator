"""Conflict-aware scheduling for independent V6 operations."""
from __future__ import annotations

from typing import Any, Callable

from . import contracts


def _conflicts(capability: dict[str, Any], operation: dict[str, Any]) -> set[str]:
    templates = capability.get("conflicts") if isinstance(capability.get("conflicts"), list) else []
    args = operation.get("args") if isinstance(operation.get("args"), dict) else {}
    values: set[str] = set()
    for template in templates:
        try:
            value = str(template).format_map({key: str(item) for key, item in args.items()})
        except (KeyError, ValueError):
            value = str(template)
        if value:
            values.add(value[:300])
    if capability.get("mode") == "write" and not values:
        values.add("global:mutation")
    return values


def waves(capabilities: dict[str, dict[str, Any]], operations: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    normalized = [contracts.operation(item) for item in operations]
    by_id = {item["id"]: item for item in normalized}
    if len(by_id) != len(normalized):
        raise contracts.ContractError("dag_operation_duplicate")
    for item in normalized:
        if item["cap"] not in capabilities:
            raise contracts.ContractError("dag_capability_missing")
        if any(dependency not in by_id for dependency in item["after"]):
            raise contracts.ContractError("dag_dependency_missing")
    pending = dict(by_id)
    complete: set[str] = set()
    result: list[list[dict[str, Any]]] = []
    while pending:
        ready = [item for item in pending.values() if set(item["after"]).issubset(complete)]
        if not ready:
            raise contracts.ContractError("dag_cycle")
        wave: list[dict[str, Any]] = []
        held: set[str] = set()
        for item in ready:
            conflicts = _conflicts(capabilities[item["cap"]], item)
            if conflicts & held:
                continue
            held.update(conflicts)
            wave.append(item)
        if not wave:
            wave = [ready[0]]
        result.append(wave)
        for item in wave:
            pending.pop(item["id"])
            complete.add(item["id"])
    return result


def execute(
    capabilities: dict[str, dict[str, Any]], operations: list[dict[str, Any]],
    invoke_wave: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    successful: set[str] = set()
    for wave in waves(capabilities, operations):
        runnable = [item for item in wave if set(item["after"]).issubset(successful)]
        blocked = [item for item in wave if item not in runnable]
        for item in blocked:
            receipts.append(contracts.receipt({
                "id": f"rcpt:{item['id']}:blocked", "op": item["id"], "ok": False, "state": "rejected",
                "error": {"code": "dependency_failed"},
            }))
        observed = invoke_wave(runnable) if runnable else []
        by_op = {str(item.get("op") or ""): contracts.receipt(item) for item in observed if isinstance(item, dict)}
        for item in runnable:
            receipt = by_op.get(item["id"])
            if receipt is None:
                receipt = contracts.receipt({
                    "id": f"rcpt:{item['id']}:missing", "op": item["id"], "ok": False,
                    "state": "interrupted", "error": {"code": "executor_receipt_missing"},
                })
            receipts.append(receipt)
            if receipt["ok"] and receipt["state"] in {"acknowledged", "completed"}:
                successful.add(item["id"])
    return receipts
