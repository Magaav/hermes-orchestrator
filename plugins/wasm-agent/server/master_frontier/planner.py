from __future__ import annotations

from typing import Any

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
    if intent_name == "implementation":
        return ["route", "changed_files", "checks", "proof"]
    if intent_name == "diagnosis":
        return ["route", "evidence", "cause", "next_action"]
    return ["route", "evidence", "answer"]


def _budget(envelope: dict[str, Any], route_contract: dict[str, Any]) -> dict[str, Any]:
    source = route_contract.get("budget") if isinstance(route_contract.get("budget"), dict) else {}
    override = envelope.get("budget") if isinstance(envelope.get("budget"), dict) else {}
    budget: dict[str, Any] = {}
    for key in ("head_tokens_max", "provider_tokens_max", "api_calls_max", "wall_ms_max"):
        value = override.get(key, source.get(key))
        if isinstance(value, int) and value >= 0:
            budget[key] = value
    max_output = override.get("max_output_tokens")
    if isinstance(max_output, int) and max_output >= 0:
        budget["max_output_tokens"] = max_output
    return budget


def _provider_policy(route_contract: dict[str, Any]) -> dict[str, Any]:
    policy = route_contract.get("provider_policy") if isinstance(route_contract.get("provider_policy"), dict) else {}
    result: dict[str, Any] = {}
    for key in ("default", "hermes", "missing_route"):
        value = route_contracts.clipped(str(policy.get(key) or "").strip(), 120)
        if value:
            result[key] = value
    return result


def _tools_first(intent_name: str, caps: list[str], route_id: str) -> list[str]:
    tools = ["kernel.resolve"]
    if route_id:
        tools.append("code.memory.search")
    if intent_name == "implementation":
        tools.extend(["code.memory.impact", "kernel.act", "kernel.prove"])
    elif "runtime.inspect" in caps:
        tools.extend(["kernel.inspect", "kernel.prove"])
    else:
        tools.append("kernel.inspect")
    return list(dict.fromkeys(tools))


def _intent_name(envelope: dict[str, Any]) -> str:
    objective = str(envelope.get("objective") or "")
    if intent.text_is_capability_inquiry(objective):
        return "capability_inquiry"
    if intent.objective_is_implementation_intent(envelope) or intent.goal_requires_change_artifact(envelope):
        return "implementation"
    text = intent.goal_completion_text(envelope)
    if any(word in text for word in ("why", "failed", "error", "bug", "diagnose", "inspect")):
        return "diagnosis"
    return "answer"


def task_contract(envelope: dict[str, Any]) -> dict[str, Any]:
    route_contract = envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else {}
    route_id = _route_id(envelope, route_contract)
    caps = _caps(envelope, route_contract)
    intent_name = _intent_name(envelope)
    proof = _proof(intent_name)
    tools_first = _tools_first(intent_name, caps, route_id)
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
    return {
        "schema": SCHEMA,
        "intent": intent_name,
        "route_id": route_id,
        "workspace_root": workspace_root,
        "caps": caps,
        "budget": _budget(envelope, route_contract),
        "provider_policy": _provider_policy(route_contract),
        "tools_first": tools_first,
        "executor": executor,
        "proof_required": proof,
        "block_codes": block_codes,
        "hermes": "subagent_harness_only",
    }
