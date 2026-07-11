from __future__ import annotations

from typing import Any

from . import entity_resolution
from . import route_contracts


SCHEMA = "hermes.wasm_agent.master_frontier.proof_packet.v1"


def clipped(value: Any, limit: int = 160) -> str:
    return route_contracts.clipped(str(value or "").strip(), limit)


def _local_tool_receipts(local_tool_results: list[dict[str, Any]] | None) -> list[str]:
    receipts: list[str] = []
    for item in (local_tool_results or [])[:12]:
        if not isinstance(item, dict):
            continue
        tool = clipped(item.get("tool"), 80)
        if not tool:
            continue
        code = clipped(item.get("code") or ("ok" if item.get("ok") else "error"), 60)
        receipt = f"{tool}={code or 'unknown'}"
        if receipt not in receipts:
            receipts.append(receipt)
    return receipts


def _source_status(envelope: dict[str, Any], local_tool_results: list[dict[str, Any]] | None) -> str:
    local_tool_results = local_tool_results or []
    if entity_resolution.source_summaries(local_tool_results):
        return "read"
    if entity_resolution.code_memory_has_object_evidence(envelope, local_tool_results):
        return "found"
    return "missing"


def _runtime_scope_status(envelope: dict[str, Any], local_tool_results: list[dict[str, Any]] | None) -> str:
    if not entity_resolution.needs_runtime_scope_proof(envelope):
        return "not_required"
    if entity_resolution.runtime_scope_proof_satisfied(envelope, local_tool_results or []):
        return "proved"
    return "missing"


def _plan(envelope: dict[str, Any], local_tool_results: list[dict[str, Any]] | None) -> list[str]:
    resolved = entity_resolution.resolve(envelope)
    if resolved.get("is_repo_object_question"):
        plan = ["code.memory.search"]
        source_status = _source_status(envelope, local_tool_results)
        if source_status == "found":
            plan.append("file.read_bounded")
        elif source_status == "read":
            plan.extend([
                "file.read_bounded",
                "answer_with_runtime_caveat"
                if _runtime_scope_status(envelope, local_tool_results) == "missing"
                else "answer",
            ])
        else:
            plan.append("source_lookup")
        return list(dict.fromkeys(plan))
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    tools_first = contract.get("tools_first") if isinstance(contract.get("tools_first"), list) else []
    return [clipped(item, 80) for item in tools_first[:5] if clipped(item, 80)] or ["answer"]


def _provider_decision(parsed: Any) -> str:
    if not isinstance(parsed, dict):
        return ""
    decision = clipped(parsed.get("decision"), 120)
    if decision:
        return decision
    actions = parsed.get("actions") if isinstance(parsed.get("actions"), list) else []
    if actions and isinstance(actions[0], dict):
        return clipped(actions[0].get("action") or actions[0].get("id"), 120)
    return "answer" if clipped(parsed.get("answer"), 80) else ""


def _controller_decision(envelope: dict[str, Any], local_tool_results: list[dict[str, Any]] | None) -> str:
    resolved = entity_resolution.resolve(envelope)
    if resolved.get("is_repo_object_question"):
        source_status = _source_status(envelope, local_tool_results)
        runtime_status = _runtime_scope_status(envelope, local_tool_results)
        if source_status == "read" and runtime_status == "missing":
            return "answer_with_runtime_caveat"
        if source_status == "read":
            return "answer_from_source"
        if source_status == "found":
            return "read_source"
        return "find_source"
    return ""


def _loop_gate(loop_state: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(loop_state, dict):
        return {}
    critique = loop_state.get("critique") if isinstance(loop_state.get("critique"), dict) else {}
    return {
        "status": clipped(loop_state.get("status"), 80),
        "reason": clipped(critique.get("reason"), 120),
    }


def _line(packet: dict[str, Any]) -> str:
    obj = packet.get("object") if isinstance(packet.get("object"), dict) else {}
    gate = packet.get("final_gate") if isinstance(packet.get("final_gate"), dict) else {}
    parts = ["MF/1"]

    def add(key: str, value: Any) -> None:
        text = clipped(value, 240)
        if text:
            parts.append(f"{key}:{text}")

    add("stage", packet.get("stage"))
    add("route", packet.get("route_id"))
    add("intent", packet.get("intent") or packet.get("objective_kind"))
    if obj.get("kind") or obj.get("id"):
        parts.append(f"obj:{clipped(obj.get('kind'), 60)}:{clipped(obj.get('id'), 120)}")
    add("scope", obj.get("scope"))
    add("plan", ">".join(packet.get("plan") or []))
    add("tools", ",".join(packet.get("tool_receipts") or []))
    add("src", packet.get("source_status"))
    add("rt", packet.get("runtime_scope"))
    add("ctrl", packet.get("controller_decision"))
    add("gate", gate.get("status"))
    add("reason", gate.get("reason"))
    return " ".join(parts)[:1200]


def build(
    envelope: dict[str, Any],
    *,
    stage: str,
    local_tool_results: list[dict[str, Any]] | None = None,
    parsed: Any = None,
    loop_state: dict[str, Any] | None = None,
    dispatch_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    resolved = entity_resolution.resolve(envelope)
    evidence = entity_resolution.evidence_packet(envelope, local_tool_results or [])
    compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    quest_state = evidence.get("quest_state") or compact_state.get("quest_state") or {}
    packet = {
        "schema": SCHEMA,
        "stage": clipped(stage, 80),
        "route_id": clipped(envelope.get("route_id") or envelope.get("route"), 160),
        "intent": clipped(contract.get("intent"), 80),
        "objective_kind": clipped(envelope.get("objective_kind"), 80),
        "object": {
            "kind": clipped(resolved.get("kind"), 60),
            "id": clipped(resolved.get("object_id") or resolved.get("query"), 120),
            "scope": clipped(resolved.get("scope_id"), 120),
        },
        "plan": _plan(envelope, local_tool_results),
        "tool_receipts": _local_tool_receipts(local_tool_results),
        "source_status": _source_status(envelope, local_tool_results),
        "runtime_scope": _runtime_scope_status(envelope, local_tool_results),
        "quest_state": quest_state,
        "qs_line": clipped(evidence.get("quest_line") or (quest_state.get("line") if isinstance(quest_state, dict) else ""), 600),
        "source_line": clipped(evidence.get("source_line") or envelope.get("repo_object_evidence_line"), 600),
        "provider_decision": _provider_decision(parsed),
        "controller_decision": _controller_decision(envelope, local_tool_results),
        "dispatch": "present" if isinstance(dispatch_result, dict) else "none",
        "final_gate": _loop_gate(loop_state),
    }
    packet = {key: value for key, value in packet.items() if value not in ("", [], {})}
    packet["line"] = _line(packet)
    return packet


def summary(packet: dict[str, Any]) -> str:
    return clipped(packet.get("line"), 260) or "MF/1"
