"""Declared V5 task-mode policy; never infer authority from objective text."""
from __future__ import annotations
from typing import Any

SELF_CONTAINED_CLASSES = frozenset({"conversation", "general_conversation"})
GROUNDED_CLASSES = frozenset({"source_investigation", "runtime_inspection"})
MUTATION_CLASSES = frozenset({"implementation"})
PLANNING_CLASSES = frozenset({"implementation_planning"})
VERIFICATION_CLASSES = frozenset({"verification"})


def request_class(route: dict[str, Any]) -> str:
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    return str(contract.get("request_class") or contract.get("objective_kind") or "").strip().lower()


def llm_autonomous(route: dict[str, Any]) -> bool:
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    return contract.get("decision_mode") == "llm_autonomous"


def direct_completion(route: dict[str, Any]) -> bool:
    # A follow-up is not self-contained merely because its current turn was
    # classified as conversation. Preserve capabilities and let the head decide.
    if route.get("session_context"):
        return False
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    strategy = str(contract.get("strategy") or "minimal_class_allowlist")
    cls = request_class(route)
    allowed = cls in SELF_CONTAINED_CLASSES
    grounded = bool(GROUNDED_CLASSES & set(contract.get("declared_classes") or [cls]))
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


def requires_tool_evidence(route: dict[str, Any]) -> bool:
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    declared = set(contract.get("declared_classes") or [request_class(route)])
    return bool(GROUNDED_CLASSES & declared)


def requires_mutation(route: dict[str, Any]) -> bool:
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    declared = set(contract.get("declared_classes") or [request_class(route)])
    return bool(MUTATION_CLASSES & declared)


def requires_decision(route: dict[str, Any]) -> bool:
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    declared = set(contract.get("declared_classes") or [request_class(route)])
    return bool(PLANNING_CLASSES & declared)


def requires_verification(route: dict[str, Any]) -> bool:
    if llm_autonomous(route):
        return False
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    declared = set(contract.get("declared_classes") or [request_class(route)])
    return bool(VERIFICATION_CLASSES & declared)


def accepts_tool_evidence(route: dict[str, Any], result: dict[str, Any]) -> bool:
    if result.get("ok") is True:
        return True
    return request_class(route) == "runtime_inspection" and result.get("code") == "capability_unavailable"
