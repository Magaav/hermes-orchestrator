"""Bounded model-declared goals with host-verified operation proof."""
from __future__ import annotations

from typing import Any

from . import contracts


MAX_GOALS = 16


def declare(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw or len(raw) > MAX_GOALS:
        raise contracts.ContractError("goal_contract_required")
    goals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, dict):
            raise contracts.ContractError("goal_contract_invalid")
        goal_id = str(value.get("id") or "")
        capability = str(value.get("cap") or "")
        outcome = " ".join(str(value.get("outcome") or "").split())[:300]
        effect = str(value.get("effect") or "")[:120]
        if not contracts.ID.fullmatch(goal_id) or not contracts.ID.fullmatch(capability) or not outcome or goal_id in seen:
            raise contracts.ContractError("goal_contract_invalid")
        seen.add(goal_id)
        if effect and not contracts.ID.fullmatch(effect):
            raise contracts.ContractError("goal_contract_invalid")
        goals.append({"id": goal_id, "cap": capability, "outcome": outcome, "effect": effect, "status": "pending", "operation": ""})
    return goals


def bind(goals: list[dict[str, Any]], operations: list[dict[str, Any]]) -> None:
    declared = {str(item.get("id") or ""): str(item.get("cap") or "") for item in goals}
    for operation in operations:
        goal_id = str(operation.get("goal_id") or "")
        if operation.get("completes_goal") is not True:
            continue
        if not goal_id or declared.get(goal_id) != str(operation.get("cap") or ""):
            raise contracts.ContractError("goal_operation_unbound")


def observe(
    goals: list[dict[str, Any]], operations: list[dict[str, Any]], receipts: list[dict[str, Any]],
    capability_lookup: Any,
) -> list[dict[str, Any]]:
    updated = [dict(item) for item in goals]
    by_id = {str(item.get("id") or ""): item for item in updated}
    for operation, receipt in zip(operations, receipts):
        goal_id = str(operation.get("goal_id") or "")
        goal = by_id.get(goal_id)
        capability = capability_lookup(str(operation.get("cap") or "")) or {}
        proof = set(receipt.get("proof") or [])
        required = set(capability.get("proof") or []) | set(capability.get("completion_proof") or [])
        bound_terminal = (
            goal and operation.get("completes_goal") is True
            and goal.get("cap") == operation.get("cap")
            and (
                capability.get("mode") == "write"
                or (
                    capability.get("mode") == "read"
                    and bool(goal.get("effect"))
                    and goal.get("effect") in set(capability.get("completion_effects") or [])
                )
            )
            and capability.get("goal_completion") is not False
            and (not goal.get("effect") or goal.get("effect") in set(capability.get("completion_effects") or []))
        )
        if bound_terminal:
            goal.update({
                "status": "satisfied" if receipt.get("ok") is True and required.issubset(proof) else "blocked",
                "operation": str(operation.get("id") or ""),
            })
    return updated


def gaps(goals: list[dict[str, Any]]) -> list[str]:
    return [f"goal:{item.get('id')}" for item in goals if item.get("status") != "satisfied"]


def aggregate_status(goals: list[dict[str, Any]], fallback: str) -> str:
    return "blocked" if any(item.get("status") == "blocked" for item in goals) else fallback
