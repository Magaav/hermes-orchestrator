"""Declared V5 task-mode policy; never infer authority from objective text."""
from __future__ import annotations
from typing import Any

SELF_CONTAINED_CLASSES = frozenset({"conversation", "general_conversation"})


def request_class(route: dict[str, Any]) -> str:
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    return str(contract.get("request_class") or contract.get("objective_kind") or "").strip().lower()


def direct_completion(route: dict[str, Any]) -> bool:
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    strategy = str(contract.get("strategy") or "minimal_class_allowlist")
    cls = request_class(route)
    allowed = cls in SELF_CONTAINED_CLASSES
    grounded = bool({"source_investigation", "runtime_inspection"} & set(contract.get("declared_classes") or [cls]))
    if strategy == "minimal_class_allowlist": return allowed
    if strategy == "deny_first_class_policy": return allowed and not grounded
    if strategy == "explicit_completion_mode": return contract.get("completion_mode") == "direct"
    if strategy == "proof_policy_gate": return allowed and contract.get("proof_policy") == "none"
    if strategy == "capability_requirement_gate": return allowed and contract.get("required_capabilities") == []
    if strategy == "evidence_requirement_gate": return allowed and contract.get("evidence_requirements") == []
    if strategy == "route_owned_execution_profile": return contract.get("execution_profile") == "answer_only"
    if strategy == "structured_policy_decision": return allowed and contract.get("authority_source") == "declared_task_contract"
    if strategy == "single_context_profile_constructor": return contract.get("context_profile") == "direct"
    return False
