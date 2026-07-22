"""Fail-closed route and task authority for Master:frontier tools."""
from __future__ import annotations

from typing import Any


REPO_READ = "repo.read"
REPO_EDIT = "repo.edit"
TEST_RUN = "test.run"
RUNTIME_INSPECT = "runtime.inspect"
RUNTIME_INSPECT_UNAVAILABLE = "runtime.inspect.unavailable"
PROOF_REPORT = "proof.report"

V5_TOOLS = ("search", "read", "inspect", "edit", "test", "diff", "prove")
TOOL_CAPABILITY = {
    "search": REPO_READ,
    "read": REPO_READ,
    "inspect": RUNTIME_INSPECT,
    "edit": REPO_EDIT,
    "test": TEST_RUN,
    "diff": PROOF_REPORT,
    "prove": PROOF_REPORT,
}

_READ_TOOLS = frozenset({"search", "read"})
_RUNTIME_TOOLS = frozenset({"inspect"})
_IMPLEMENTATION_TOOLS = frozenset(V5_TOOLS)
_VERIFICATION_TOOLS = frozenset({"search", "read", "test", "diff", "prove"})

_CLASS_TOOLS = {
    "conversation": _READ_TOOLS,
    "general_conversation": _READ_TOOLS,
    "source_investigation": _READ_TOOLS,
    "implementation_planning": _READ_TOOLS,
    "runtime_inspection": _RUNTIME_TOOLS,
    "implementation": _IMPLEMENTATION_TOOLS,
    "verification": _VERIFICATION_TOOLS,
}
_CLASS_DEFAULT_AUTHORITY = {
    "conversation": frozenset({REPO_READ}),
    "general_conversation": frozenset({REPO_READ}),
    "source_investigation": frozenset({REPO_READ}),
    "implementation_planning": frozenset({REPO_READ}),
    "runtime_inspection": frozenset({RUNTIME_INSPECT}),
    "implementation": frozenset({REPO_READ, REPO_EDIT, TEST_RUN, PROOF_REPORT}),
    "verification": frozenset({REPO_READ, TEST_RUN, PROOF_REPORT}),
}
_KNOWN_CAPABILITIES = frozenset({REPO_READ, REPO_EDIT, TEST_RUN, RUNTIME_INSPECT, PROOF_REPORT})
_CONCRETE_EVIDENCE_CLASSES = {
    "conceptual": frozenset({"conversation", "general_conversation"}),
    "source": frozenset({"source_investigation", "implementation_planning", "implementation", "verification"}),
    "runtime": frozenset({"runtime_inspection", "implementation"}),
    "proof": frozenset({"implementation", "verification"}),
}
_EVIDENCE_CAPABILITY = {
    "source_investigation": REPO_READ,
    "implementation_planning": REPO_READ,
    "runtime_inspection": RUNTIME_INSPECT,
}
_WORKFLOW_CAPABILITIES = {
    "implementation": frozenset({REPO_READ, REPO_EDIT, TEST_RUN, PROOF_REPORT}),
    "verification": frozenset({TEST_RUN, PROOF_REPORT}),
}


def _clean(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _project_request_class(contract: dict[str, Any], objective_kind: str) -> str:
    """Resolve task modality only from host-declared intent/evidence fields."""
    explicit = _clean(contract.get("request_class"))
    if explicit:
        return explicit
    intent = _clean(contract.get("intent") or objective_kind)
    evidence = _clean(contract.get("evidence_floor"))
    route_intent = _clean(contract.get("route_intent"))
    if intent == "implementation":
        return "implementation"
    if intent == "verification":
        return "verification"
    if evidence == "runtime" or route_intent == "runtime_support":
        return "runtime_inspection"
    if evidence == "source":
        return "source_investigation"
    if evidence == "conceptual":
        return "conversation"
    return {
        "answer": "conversation",
        "capability_inquiry": "conversation",
        "diagnosis": "source_investigation",
        "runtime_inspection": "runtime_inspection",
        "source_investigation": "source_investigation",
    }.get(intent, intent)


def _evidence_compatible(contract: dict[str, Any], declared_class: str) -> bool:
    evidence = _clean(contract.get("evidence_floor"))
    compatible = _CONCRETE_EVIDENCE_CLASSES.get(evidence)
    return compatible is None or declared_class in compatible


def project_task_contract(envelope: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    """Preserve host authority and project modality from structured evidence, never caps."""
    declared = envelope.get("task_contract")
    result = dict(declared) if isinstance(declared, dict) else {}
    for field in ("request_class", "intent", "evidence_floor", "route_intent"):
        if not result.get(field) and envelope.get(field):
            result[field] = envelope[field]
    objective_kind = str(result.get("objective_kind") or envelope.get("objective_kind") or "").strip()
    result["objective_kind"] = objective_kind
    result["request_class"] = _project_request_class(result, objective_kind)
    return result


def _task_contract(route: dict[str, Any]) -> dict[str, Any]:
    value = route.get("task_contract")
    return value if isinstance(value, dict) else {}


def request_class(route: dict[str, Any]) -> str:
    contract = _task_contract(route)
    return _clean(contract.get("request_class") or contract.get("objective_kind"))


def _explicit_task_authority(route: dict[str, Any]) -> frozenset[str] | None:
    contract = _task_contract(route)
    if "authority" not in contract:
        return None
    raw = contract.get("authority")
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(
        value
        for item in raw[:24]
        if (value := str(item or "").strip().lower()) in _KNOWN_CAPABILITIES
    )


def _route_authority(route: dict[str, Any]) -> frozenset[str]:
    raw = route.get("caps")
    if not isinstance(raw, list):
        return frozenset()
    declared = {str(item or "").strip().lower() for item in raw[:24]}
    available = declared & _KNOWN_CAPABILITIES
    if RUNTIME_INSPECT_UNAVAILABLE in declared:
        # This sentinel grants only the ability to request a typed unavailable
        # observation; it does not claim that live inspection exists.
        available.add(RUNTIME_INSPECT)
    write_roots = route.get("allowed_write_roots")
    if not isinstance(write_roots, list) or not any(str(item or "").strip() for item in write_roots):
        available.discard(REPO_EDIT)
    return frozenset(available)


def _allowed_tools(route: dict[str, Any], *, explicit: bool) -> frozenset[str]:
    declared_class = request_class(route)
    if declared_class in _CLASS_TOOLS:
        return _CLASS_TOOLS[declared_class]
    return _IMPLEMENTATION_TOOLS if explicit else _READ_TOOLS


def _runtime_scope_available(route: dict[str, Any]) -> bool:
    if request_class(route) != "runtime_inspection":
        return True
    declared = {str(item or "").strip().lower() for item in (route.get("caps") or [])}
    if RUNTIME_INSPECT_UNAVAILABLE in declared:
        return True
    entities = route.get("entities") if isinstance(route.get("entities"), list) else []
    return any(
        isinstance(item, dict)
        and str(item.get("id") or "").strip()
        and str(item.get("kind") or "").strip()
        for item in entities[:24]
    )


def _contract_blocks(contract: dict[str, Any]) -> list[str]:
    raw = contract.get("block_codes") if isinstance(contract.get("block_codes"), list) else []
    blocks = [str(item or "").strip()[:120] for item in raw[:8] if str(item or "").strip()]
    if _clean(contract.get("executor")) == "blocked" and not blocks:
        blocks.append("executor_blocked")
    return blocks


def _workflow_class_mismatch(contract: dict[str, Any], declared_class: str) -> list[str]:
    raw = contract.get("declared_classes") if isinstance(contract.get("declared_classes"), list) else []
    workflows = sorted({
        value for item in raw
        if (value := _clean(item)) in _WORKFLOW_CAPABILITIES
    })
    if not workflows:
        return []
    return [] if len(workflows) == 1 and workflows[0] == declared_class else workflows


def _base_effective(route: dict[str, Any]) -> frozenset[str]:
    explicit_authority = _explicit_task_authority(route)
    explicit = explicit_authority is not None
    requested = explicit_authority if explicit else _CLASS_DEFAULT_AUTHORITY.get(
        request_class(route), frozenset({REPO_READ}),
    )
    allowed_capabilities = {TOOL_CAPABILITY[name] for name in _allowed_tools(route, explicit=explicit)}
    return frozenset(_route_authority(route) & requested & allowed_capabilities)


def effective(route: dict[str, Any] | None) -> frozenset[str]:
    scoped = route if isinstance(route, dict) else {}
    contract = _task_contract(scoped)
    if (
        _contract_blocks(contract)
        or _workflow_class_mismatch(contract, request_class(scoped))
        or not _evidence_compatible(contract, request_class(scoped))
        or not _runtime_scope_available(scoped)
    ):
        return frozenset()
    available = _base_effective(scoped)
    required = _WORKFLOW_CAPABILITIES.get(request_class(scoped), frozenset())
    return available if required.issubset(available) else frozenset()


def coherence(route: dict[str, Any] | None) -> dict[str, Any]:
    """Return a compact fail-closed check for evidence, class, and exposed authority."""
    scoped = route if isinstance(route, dict) else {}
    contract = _task_contract(scoped)
    declared_class = request_class(scoped)
    evidence = _clean(contract.get("evidence_floor")) or "route"
    blocks = _contract_blocks(contract)
    if blocks:
        return {
            "ok": False,
            "code": "task_contract_blocked",
            "class": declared_class,
            "evidence": evidence,
            "blocks": blocks,
            "caps": [],
        }
    workflow_mismatch = _workflow_class_mismatch(contract, declared_class)
    if workflow_mismatch:
        return {
            "ok": False,
            "code": "declared_class_mismatch",
            "class": declared_class,
            "evidence": evidence,
            "declared_workflows": workflow_mismatch,
            "caps": [],
        }
    if not _evidence_compatible(contract, declared_class):
        return {
            "ok": False,
            "code": "evidence_class_mismatch",
            "class": declared_class,
            "evidence": evidence,
            "caps": [],
        }
    required = _EVIDENCE_CAPABILITY.get(declared_class)
    route_available = _route_authority(scoped)
    if required and required not in route_available:
        return {
            "ok": False,
            "code": "evidence_capability_missing",
            "class": declared_class,
            "evidence": evidence,
            "required": required,
            "caps": sorted(route_available),
        }
    if not _runtime_scope_available(scoped):
        return {
            "ok": False,
            "code": "runtime_entity_scope_missing",
            "class": declared_class,
            "evidence": evidence,
            "required": "route.entities[id,kind]",
            "caps": [],
        }
    base_available = _base_effective(scoped)
    workflow_required = _WORKFLOW_CAPABILITIES.get(declared_class, frozenset())
    workflow_missing = sorted(workflow_required - base_available)
    if workflow_missing:
        return {
            "ok": False,
            "code": "task_capability_missing",
            "class": declared_class,
            "evidence": evidence,
            "required": workflow_missing,
            "caps": sorted(base_available),
        }
    available = effective(scoped)
    if required and required not in available:
        return {
            "ok": False,
            "code": "evidence_capability_missing",
            "class": declared_class,
            "evidence": evidence,
            "required": required,
            "caps": sorted(available),
        }
    return {
        "ok": True,
        "code": "ok",
        "class": declared_class,
        "evidence": evidence,
        "caps": sorted(available),
    }


def known_tool(name: str) -> bool:
    return str(name or "").strip() in TOOL_CAPABILITY


def tool_allowed(name: str, route: dict[str, Any] | None) -> bool:
    clean = str(name or "").strip()
    if clean not in TOOL_CAPABILITY:
        return False
    scoped = route if isinstance(route, dict) else {}
    explicit = _explicit_task_authority(scoped) is not None
    return clean in _allowed_tools(scoped, explicit=explicit) and TOOL_CAPABILITY[clean] in effective(scoped)


def required_capability(name: str) -> str:
    return TOOL_CAPABILITY.get(str(name or "").strip(), "")
