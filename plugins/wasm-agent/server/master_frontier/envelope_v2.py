from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from . import envelope as direct_envelope


SCHEMA = "hermes.wasm_agent.envelope_v2.timeline_event.v1"
LEDGER_SCHEMA = "hermes.wasm_agent.envelope_v2.usage_ledger.v1"
SEMANTIC_SCHEMA = "hermes.wasm_agent.envelope_v2.semantic_decision.v1"
COMMAND_SCHEMA = "hermes.wasm_agent.envelope_v2.command.v1"
EVIDENCE_SCHEMA = "hermes.wasm_agent.envelope_v2.evidence.v1"
GATE_SCHEMA = "hermes.wasm_agent.envelope_v2.final_gate.v1"

EVIDENCE_EVENT_TYPES = {
    "evidence.received",
    "evidence.missing",
    "command.failed",
    "route.missing",
    "capability.missing",
}


def _clip(value: Any, limit: int = 240) -> str:
    return direct_envelope.clipped(str(value or "").strip(), limit)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def _first_int(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key in payload:
            value = _int(payload.get(key))
            if value is not None:
                return value
    return None


def timeline_event(
    event_type: str,
    *,
    turn_id: str = "",
    inference_id: str = "",
    stage: str = "",
    summary: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "type": _clip(event_type, 80),
        "turn_id": _clip(turn_id, 160),
        "inference_id": _clip(inference_id, 160),
        "stage": _clip(stage, 80),
        "summary": _clip(summary, 500),
        "payload": payload or {},
        "created_at": _now_ms(),
    }


def action_name(action: dict[str, Any]) -> str:
    return direct_envelope.canonical_action_name(action)


def action_args(action: dict[str, Any]) -> dict[str, Any]:
    return direct_envelope.action_args(action)


def command_id(action: dict[str, Any], *, inference_id: str = "") -> str:
    material = {
        "inference_id": inference_id,
        "action": action_name(action),
        "args": direct_envelope.redact(action_args(action)),
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"cmd_{digest[:16]}"


def command_proposal(action: dict[str, Any], envelope: dict[str, Any], *, inference_id: str = "") -> dict[str, Any]:
    args = action_args(action)
    route_id = _clip(args.get("route_id") or action.get("route_id") or envelope.get("route_id") or envelope.get("route"), 160)
    name = action_name(action)
    return {
        "schema": COMMAND_SCHEMA,
        "command_id": command_id(action, inference_id=inference_id),
        "action": name,
        "args": direct_envelope.redact(args),
        "route_id": route_id,
        "capability": _clip(name.replace(".", "."), 120),
        "expected_evidence": args.get("inspect") if isinstance(args.get("inspect"), list) else [],
    }


def semantic_decision(parsed: Any, reply: str, envelope: dict[str, Any]) -> dict[str, Any]:
    parsed = parsed if isinstance(parsed, dict) else {}
    actions = parsed.get("actions") if isinstance(parsed.get("actions"), list) else []
    first_action = next((item for item in actions if isinstance(item, dict)), None)
    proposal = command_proposal(first_action, envelope) if first_action else None
    needs = parsed.get("needs") if isinstance(parsed.get("needs"), list) else []
    decision = _clip(parsed.get("decision") or ("answer" if _clip(parsed.get("answer") or reply, 80) else ""), 160)
    return {
        "schema": SEMANTIC_SCHEMA,
        "intent": decision or "answer",
        "referent": _clip((proposal or {}).get("route_id") or envelope.get("surface") or envelope.get("route_id"), 160),
        "uncertainty": [_clip(item, 160) for item in needs[:8] if _clip(item, 160)],
        "needed_capability": _clip((proposal or {}).get("capability") or "", 120),
        "expected_evidence": (proposal or {}).get("expected_evidence") or [],
        "proposed_command": proposal,
    }


def public_reason_summary(parsed: Any, reply: str) -> str:
    parsed = parsed if isinstance(parsed, dict) else {}
    for key in ("answer", "decision"):
        text = _clip(parsed.get(key), 360)
        if text:
            return text
    return _clip(reply, 360) or "Direct head produced a semantic decision."


def inference_started_events(*, turn_id: str, inference_id: str, stage: str, model: str = "") -> list[dict[str, Any]]:
    return [
        timeline_event(
            "llm.inference.started",
            turn_id=turn_id,
            inference_id=inference_id,
            stage=stage,
            summary=f"{stage} inference started",
            payload={"model": _clip(model, 180)},
        )
    ]


def decision_events(
    parsed: Any,
    reply: str,
    envelope: dict[str, Any],
    *,
    turn_id: str,
    inference_id: str,
    stage: str,
) -> list[dict[str, Any]]:
    decision = semantic_decision(parsed, reply, envelope)
    events = [
        timeline_event(
            "llm.reason.summary",
            turn_id=turn_id,
            inference_id=inference_id,
            stage=stage,
            summary=public_reason_summary(parsed, reply),
            payload={"public_reasoning": public_reason_summary(parsed, reply)},
        ),
        timeline_event(
            "semantic.decision",
            turn_id=turn_id,
            inference_id=inference_id,
            stage=stage,
            summary=_clip(decision.get("intent") or "answer", 240),
            payload={"semantic_decision": decision},
        ),
    ]
    proposal = decision.get("proposed_command")
    if isinstance(proposal, dict):
        events.append(
            timeline_event(
                "command.proposed",
                turn_id=turn_id,
                inference_id=inference_id,
                stage=stage,
                summary=_clip(proposal.get("action") or "command", 160),
                payload={"command": proposal},
            )
        )
    return events


def normalize_usage(raw: Any, *, source: str = "", model: str = "") -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    prompt = _first_int(raw, "prompt_tokens", "input_tokens", "input_token_count", "tokens_in")
    completion = _first_int(raw, "completion_tokens", "output_tokens", "output_token_count", "tokens_out")
    total = _first_int(raw, "total_tokens", "total_token_count", "tokens")
    if total is None and (prompt is not None or completion is not None):
        total = int(prompt or 0) + int(completion or 0)
    if total is None:
        return None
    result = {
        "prompt_tokens": int(prompt or 0),
        "completion_tokens": int(completion or 0),
        "total_tokens": int(total or 0),
        "model": _clip(raw.get("model") or model, 180),
        "source": _clip(raw.get("source") or source, 120),
    }
    cached = _first_int(raw, "cached_input_tokens", "cached_tokens", "cache_read_tokens")
    reasoning = _first_int(raw, "reasoning_tokens", "reasoning_output_tokens")
    if cached is not None:
        result["cached_input_tokens"] = cached
    if reasoning is not None:
        result["reasoning_tokens"] = reasoning
    for key in ("duration_ms", "stop_reason"):
        if raw.get(key) not in (None, ""):
            result[key] = raw.get(key)
    return result


def usage_ledger(
    calls: list[dict[str, Any]],
    *,
    turn_id: str,
    estimated_cost: Any = None,
) -> dict[str, Any]:
    normalized = [call for call in calls if isinstance(call, dict)]
    return {
        "schema": LEDGER_SCHEMA,
        "turn_id": _clip(turn_id, 160),
        "inference_count": len(normalized),
        "prompt_tokens_total": sum(int(call.get("prompt_tokens") or 0) for call in normalized),
        "completion_tokens_total": sum(int(call.get("completion_tokens") or 0) for call in normalized),
        "reasoning_tokens_total": sum(int(call.get("reasoning_tokens") or 0) for call in normalized),
        "cached_input_tokens_total": sum(int(call.get("cached_input_tokens") or 0) for call in normalized),
        "total_tokens": sum(int(call.get("total_tokens") or 0) for call in normalized),
        "estimated_cost": estimated_cost,
        "calls": normalized,
    }


def inference_completed_events(
    usage: dict[str, Any] | None,
    prior_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    inference_id: str,
    stage: str,
    model: str = "",
    duration_ms: int | None = None,
    stop_reason: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized = normalize_usage(usage, source=stage, model=model) if usage else None
    if not normalized:
        return [], prior_calls
    if duration_ms is not None:
        normalized["duration_ms"] = duration_ms
    if stop_reason:
        normalized["stop_reason"] = _clip(stop_reason, 120)
    call = {
        "turn_id": _clip(turn_id, 160),
        "inference_id": _clip(inference_id, 160),
        "stage": _clip(stage, 80),
        "model": _clip(normalized.get("model") or model, 180),
        "prompt_tokens": normalized.get("prompt_tokens"),
        "completion_tokens": normalized.get("completion_tokens"),
        "reasoning_tokens": normalized.get("reasoning_tokens"),
        "cached_input_tokens": normalized.get("cached_input_tokens"),
        "total_tokens": normalized.get("total_tokens"),
        "duration_ms": normalized.get("duration_ms"),
        "stop_reason": normalized.get("stop_reason") or "",
    }
    calls = [*prior_calls, call]
    ledger = usage_ledger(calls, turn_id=turn_id)
    return [
        timeline_event(
            "llm.inference.completed",
            turn_id=turn_id,
            inference_id=inference_id,
            stage=stage,
            summary=f"{call['total_tokens']} tokens",
            payload=call,
        ),
        timeline_event(
            "turn.usage.updated",
            turn_id=turn_id,
            inference_id=inference_id,
            stage=stage,
            summary=f"{ledger['total_tokens']} total tokens",
            payload={"ledger": ledger},
        ),
    ], calls


def command_receipt_events(
    tool_results: list[dict[str, Any]],
    *,
    turn_id: str,
    inference_id: str,
    stage: str = "action",
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in tool_results[:12]:
        if not isinstance(item, dict):
            continue
        action = {"action": item.get("tool") or "local-tool", "args": {"route_id": item.get("route_id")}}
        command = command_proposal(action, {"route_id": item.get("route_id")}, inference_id=inference_id)
        status = "accepted" if item.get("ok") else "failed"
        events.extend([
            timeline_event("command.accepted", turn_id=turn_id, inference_id=inference_id, stage=stage, summary=_clip(command.get("action"), 160), payload={"command": command}),
            timeline_event("command.dispatched", turn_id=turn_id, inference_id=inference_id, stage=stage, summary=_clip(command.get("action"), 160), payload={"command": command}),
            timeline_event("command.started", turn_id=turn_id, inference_id=inference_id, stage=stage, summary=_clip(command.get("action"), 160), payload={"command_id": command.get("command_id"), "action": command.get("action")}),
        ])
        if status == "accepted":
            evidence = {
                "schema": EVIDENCE_SCHEMA,
                "command_id": command.get("command_id"),
                "status": "received",
                "kind": _clip(item.get("tool"), 120),
                "summary": item.get("summary") if isinstance(item.get("summary"), dict) else {},
                "route_id": _clip(item.get("route_id"), 160),
                "proof_refs": [],
                "missing": [],
                "error_class": None,
            }
            events.append(timeline_event("evidence.received", turn_id=turn_id, inference_id=inference_id, stage="observe", summary=f"{item.get('tool')}: {item.get('code') or 'ok'}", payload={"evidence": evidence}))
        else:
            events.append(timeline_event("command.failed", turn_id=turn_id, inference_id=inference_id, stage="observe", summary=f"{item.get('tool')}: {item.get('code') or 'failed'}", payload={"command": command, "tool": item}))
            events.append(timeline_event("evidence.missing", turn_id=turn_id, inference_id=inference_id, stage="observe", summary=f"{item.get('tool')}: evidence missing", payload={"command": command, "tool": item}))
    return events


def final_gate_events(
    *,
    turn_id: str,
    status: str,
    reason: str,
    proof_refs: list[str] | None = None,
    missing: list[str] | None = None,
) -> list[dict[str, Any]]:
    decision = {
        "schema": GATE_SCHEMA,
        "status": _clip(status, 80),
        "reason": _clip(reason, 240),
        "allowed_answer_kind": "answer_from_proof" if status == "finished" else "structured_failure",
        "proof_refs": proof_refs or [],
        "missing": missing or [],
    }
    return [
        timeline_event("gate.started", turn_id=turn_id, stage="final_gate", summary="Final gate started", payload={}),
        timeline_event("gate.decision", turn_id=turn_id, stage="final_gate", summary=decision["reason"], payload={"final_gate": decision}),
    ]


def answer_events(*, turn_id: str, answer: str) -> list[dict[str, Any]]:
    return [
        timeline_event("answer.started", turn_id=turn_id, stage="answer", summary="Answer started", payload={}),
        timeline_event("answer.final", turn_id=turn_id, stage="answer", summary=_clip(answer, 360), payload={"answer_chars": len(str(answer or ""))}),
    ]


def loop_violation_event(
    *,
    turn_id: str,
    inference_id: str,
    previous_evidence_count: int,
    current_evidence_count: int,
) -> dict[str, Any] | None:
    if current_evidence_count > previous_evidence_count:
        return None
    return timeline_event(
        "loop_contract_violation",
        turn_id=turn_id,
        inference_id=inference_id,
        stage="continue_or_gate",
        summary="Second LLM decision blocked because no new evidence or structured failure exists after the prior decision.",
        payload={
            "code": "loop_contract_violation",
            "previous_evidence_count": previous_evidence_count,
            "current_evidence_count": current_evidence_count,
            "required_new_events": sorted(EVIDENCE_EVENT_TYPES),
        },
    )
