from __future__ import annotations

from typing import Any

from . import budget as budget_policy
from . import intent
from . import route_contracts


SCHEMA = "hermes.wasm_agent.master_frontier.task_contract.v1"


def _caps(envelope: dict[str, Any], route_contract: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for source in (envelope.get("capabilities"), route_contract.get("caps")):
        if not isinstance(source, list):
            continue
        for item in source[:24]:
            cap = route_contracts.clipped(str(item or "").strip(), 80)
            if cap and cap not in result:
                result.append(cap)
    return result


def _route_id(envelope: dict[str, Any], route_contract: dict[str, Any]) -> str:
    return route_contracts.clipped(str(route_contract.get("route_id") or envelope.get("route_id") or envelope.get("route") or "").strip(), 160)


def _workspace_root(route_contract: dict[str, Any]) -> str:
    return route_contracts.clipped(str(route_contract.get("workspace_root") or "").strip(), 500)


def _proof(intent_name: str) -> list[str]:
    if intent_name == "implementation_planning":
        return ["route", "evidence", "decision"]
    if intent_name == "implementation":
        return ["route", "changed_files", "checks", "proof"]
    if intent_name == "verification":
        return ["route", "checks", "proof"]
    if intent_name == "diagnosis":
        return ["route", "evidence", "cause", "next_action"]
    return ["route", "evidence", "answer"]


def _evidence_floor(envelope: dict[str, Any], intent_name: str, caps: list[str]) -> str:
    requested = str(envelope.get("evidence_floor") or envelope.get("evidenceFloor") or "").strip().lower()
    if requested in {"conceptual", "route", "source", "proof", "runtime"}:
        return requested
    objective_kind = str(envelope.get("objective_kind") or "").strip().lower()
    if objective_kind == "conversation":
        return "conceptual"
    if intent_name in {"implementation", "verification"}:
        return "proof"
    if intent_name == "implementation_planning":
        return "source"
    if intent.objective_requires_source_evidence(envelope):
        return "source"
    if intent_name == "diagnosis" or "runtime.inspect" in caps:
        objective = str(envelope.get("objective") or "").lower()
        runtime_terms = ("runtime", "node", "session", "timeline", "state", "happened", "since creation")
        if any(term in objective for term in runtime_terms):
            return "runtime"
    return "route"


def _route_intent(intent_name: str, evidence_floor: str) -> str:
    if evidence_floor == "conceptual":
        return "conceptual"
    if intent_name == "implementation" or evidence_floor == "proof":
        return "implementation"
    if evidence_floor == "runtime":
        return "runtime_support"
    return "informational"


def _depth(envelope: dict[str, Any], intent_name: str) -> dict[str, Any]:
    requested = str(envelope.get("depth") or envelope.get("answer_depth") or "").strip().lower()
    if requested in {"quick", "normal", "deep", "free"}:
        level = requested
    else:
        if intent_name == "diagnosis":
            level = "deep"
        else:
            level = "normal"
    result = {"level": level}
    if level == "free":
        result["budget_hint"] = "open"
        result["rule"] = "prefer complete architectural reasoning; harness/proof loops keep cost cheap"
    elif level == "deep":
        result["budget_hint"] = "generous"
        result["rule"] = "expand reasoning when the user asks for critique, design, or root-cause analysis"
    else:
        result["budget_hint"] = "bounded"
    return result


def _recall_budget(envelope: dict[str, Any], evidence_floor: str, depth: dict[str, Any]) -> dict[str, Any]:
    level = str(depth.get("level") or "")
    if evidence_floor != "conceptual":
        if level in {"deep", "free"}:
            return {
                "mode": "bounded_recent",
                "transcript_turns": 4,
                "rule": "deep diagnosis may include a tiny recent-turn window; exact older turns stay pull-on-demand",
            }
        return {"mode": "on_demand", "transcript_turns": 6}
    if level in {"deep", "free"}:
        return {
            "mode": "reflective",
            "transcript_turns": 10,
            "rule": "reflective turns may read a small prior-turn window when exact back-and-forth improves critique",
        }
    return {"mode": "on_demand", "transcript_turns": 6}


def _budget(envelope: dict[str, Any], route_contract: dict[str, Any]) -> dict[str, Any]:
    source = route_contract.get("budget") if isinstance(route_contract.get("budget"), dict) else {}
    override = envelope.get("budget") if isinstance(envelope.get("budget"), dict) else {}
    return budget_policy.resolve(source, override)


def _provider_policy(route_contract: dict[str, Any]) -> dict[str, Any]:
    policy = route_contract.get("provider_policy") if isinstance(route_contract.get("provider_policy"), dict) else {}
    result: dict[str, Any] = {}
    for key in ("default", "hermes", "missing_route"):
        value = route_contracts.clipped(str(policy.get(key) or "").strip(), 120)
        if value:
            result[key] = value
    return result


def _tools_first(intent_name: str, caps: list[str], route_id: str, evidence_floor: str = "") -> list[str]:
    tools = ["kernel.resolve"]
    if evidence_floor == "conceptual":
        return tools
    if route_id:
        tools.append("code.memory.search")
    if intent_name == "implementation":
        tools.extend(["code.memory.impact", "kernel.act", "kernel.prove"])
    elif intent_name == "verification":
        tools.append("kernel.prove")
    elif evidence_floor == "runtime":
        tools.extend(["kernel.inspect", "kernel.prove"])
    elif evidence_floor == "route":
        tools.append("kernel.inspect")
    return list(dict.fromkeys(tools))


def _intent_name(envelope: dict[str, Any]) -> str:
    objective_kind = str(envelope.get("objective_kind") or "").strip().lower()
    if objective_kind in {"conversation", "implementation", "implementation_planning", "verification", "diagnosis"}:
        if objective_kind == "conversation":
            return "answer"
        return objective_kind
    objective = str(envelope.get("objective") or "")
    if intent.text_is_capability_inquiry(objective):
        return "capability_inquiry"
    if intent.objective_is_implementation_intent(envelope) or intent.goal_requires_change_artifact(envelope):
        return "implementation"
    if intent.objective_is_diagnosis_intent(envelope):
        return "diagnosis"
    return "answer"


def task_contract(envelope: dict[str, Any]) -> dict[str, Any]:
    route_contract = envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else {}
    route_id = _route_id(envelope, route_contract)
    caps = _caps(envelope, route_contract)
    intent_name = _intent_name(envelope)
    proof = _proof(intent_name)
    evidence_floor = _evidence_floor(envelope, intent_name, caps)
    route_intent = _route_intent(intent_name, evidence_floor)
    depth = _depth(envelope, intent_name)
    recall_budget = _recall_budget(envelope, evidence_floor, depth)
    tools_first = _tools_first(intent_name, caps, route_id, evidence_floor)
    workspace_root = _workspace_root(route_contract)
    block_codes: list[str] = []
    if not route_id:
        block_codes.append("route_contract_missing")
    if route_id and not workspace_root:
        block_codes.append("workspace_root_missing")
    if intent_name == "implementation" and "repo.edit" not in caps:
        block_codes.append("capability_missing")
    executor = "provider_head"
    if intent_name == "implementation":
        executor = "local_kernel"
    if block_codes:
        executor = "blocked"
    generated = {
        "schema": SCHEMA,
        "intent": intent_name,
        "route_id": route_id,
        "workspace_root": workspace_root,
        "caps": caps,
        "evidence_floor": evidence_floor,
        "route_intent": route_intent,
        "depth": depth,
        "recall_budget": recall_budget,
        "budget": _budget(envelope, route_contract),
        "provider_policy": _provider_policy(route_contract),
        "tools_first": tools_first,
        "executor": executor,
        "proof_required": proof,
        "block_codes": block_codes,
        "hermes": "subagent_harness_only",
    }
    declared = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    for key in (
        "request_class", "objective_kind", "declared_classes", "authority",
        "decision_mode", "completion_mode", "proof_policy", "execution_profile",
    ):
        if key in declared:
            generated[key] = declared[key]
    return generated
