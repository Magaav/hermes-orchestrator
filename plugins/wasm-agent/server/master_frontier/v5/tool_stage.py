"""Derive currently useful tools from deterministic workflow receipts."""

from __future__ import annotations

from typing import Any

from . import progress, task_policy


def _successful_step(state: dict[str, Any], tool: str) -> bool:
    if any(
        isinstance(item, dict)
        and item.get("tool") == tool
        and item.get("status") == "completed"
        and isinstance(item.get("result"), dict)
        and item["result"].get("ok") is True
        for item in (state.get("steps") or [])
    ):
        return True
    for value in (state.get("completed_actions") or {}).values():
        if not isinstance(value, dict) or value.get("tool") != tool:
            continue
        observation = value.get("observation") if isinstance(value.get("observation"), dict) else value
        if observation.get("ok") is True:
            return True
    return False


def _open_requirement(state: dict[str, Any], tool: str) -> bool:
    executive = state.get("executive") if isinstance(state.get("executive"), dict) else {}
    return any(
        isinstance(item, dict)
        and item.get("state") == "open"
        and item.get("requires") == tool
        for item in (executive.get("outcomes") or [])
    )


def _consecutive_completed(state: dict[str, Any], tool: str) -> int:
    count = 0
    for item in reversed(state.get("steps") or []):
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "system":
            continue
        if item.get("tool") == tool and item.get("status") == "completed":
            count += 1
            continue
        break
    return count


def _search_sufficient(state: dict[str, Any]) -> bool:
    return _successful_step(state, "read") and not _open_requirement(state, "search")


def _read_sufficient(state: dict[str, Any]) -> bool:
    if progress.owner_fully_read(state):
        return True
    ledger = state.get("operation_ledger") if isinstance(state.get("operation_ledger"), dict) else {}
    revision = int(ledger.get("revision") or 0)
    check = ledger.get("check") if isinstance(ledger.get("check"), dict) else {}
    executive = state.get("executive") if isinstance(state.get("executive"), dict) else {}
    decision = executive.get("decision") if isinstance(executive.get("decision"), dict) else {}
    return (
        revision == 0
        and check.get("rev") == 0
        and check.get("ok") is True
        and decision.get("state") in {"selected", "blocked", "rejected", "overscoped"}
        and not _open_requirement(state, "read")
    )


def active_names(route: dict[str, Any], state: dict[str, Any], names: list[str]) -> list[str]:
    if task_policy.requires_decision(route):
        if state.get("decision_finalization") is True:
            return [name for name in names if name == "checkpoint"]
        return [name for name in names if name in {"checkpoint", "search", "read", "inspect"}]
    request_class = task_policy.request_class(route)
    if request_class not in {"verification", "implementation"}:
        return names
    active = list(names)
    steps = [item for item in (state.get("steps") or []) if isinstance(item, dict)]
    counters = state.get("loop_counters") if isinstance(state.get("loop_counters"), dict) else {}
    discovery_stalled = (
        task_policy.llm_autonomous(route)
        and request_class == "implementation"
        and _successful_step(state, "read")
        and int(counters.get("no_progress") or 0) >= 3
    )
    if discovery_stalled:
        active = [name for name in active if name not in {"search", "read"}]
    if task_policy.llm_autonomous(route) and request_class == "implementation" and _consecutive_completed(state, "checkpoint") >= 3:
        active = [name for name in active if name != "checkpoint"]
    if task_policy.llm_autonomous(route) and _search_sufficient(state):
        active = [name for name in active if name != "search"]
    if (
        task_policy.llm_autonomous(route) and _read_sufficient(state)
    ) or (
        not task_policy.llm_autonomous(route)
        and any(item.get("tool") == "read" and item.get("status") == "completed" for item in steps)
    ):
        active = [name for name in active if name != "read"]
        if not task_policy.llm_autonomous(route):
            active = [name for name in active if name != "search"]
    ledger = state.get("operation_ledger") if isinstance(state.get("operation_ledger"), dict) else {}
    revision = int(ledger.get("revision") or 0)
    if request_class == "implementation" and revision > 0:
        active = [name for name in active if name not in {"search", "read"}]
    check = ledger.get("check") if isinstance(ledger.get("check"), dict) else {}
    if check.get("rev") == revision and check.get("ok") is True:
        active = [name for name in active if name != "test"]
        if revision > 0:
            active = [name for name in active if name != "edit"]
    diff = ledger.get("diff") if isinstance(ledger.get("diff"), dict) else {}
    if diff.get("rev") == revision:
        active = [name for name in active if name != "diff"]
    proof = ledger.get("proof") if isinstance(ledger.get("proof"), dict) else {}
    if proof.get("rev") == revision and proof.get("ok") is True:
        active = [name for name in active if name != "prove"]
    return active
