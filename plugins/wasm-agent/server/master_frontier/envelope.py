from __future__ import annotations

import json
import re
import hashlib
from difflib import SequenceMatcher
from typing import Any

from . import dispatch
from . import cyphers_v3
from . import entity_resolution
from . import protocol
from . import route_contracts


SCHEMA = "hermes.wasm_agent.direct_envelope.v1"
RESULT_SCHEMA = "hermes.wasm_agent.direct_envelope_result.v1"
MAX_JSON_CHARS = 24_000
ALLOWED_KEYS = (
    "schema",
    "version",
    "trace_id",
    "objective",
    "objective_kind",
    "intent",
    "route",
    "route_id",
    "surface",
    "route_contract",
    "state_summary",
    "compact_state",
    "capabilities",
    "constraints",
    "evidence",
    "evidence_refs",
    "allowed_actions",
    "action_schemas",
    "budget",
    "stream",
    "output_schema",
    "head_identity",
    "last_feedback",
    "cypher_history",
)
DEFAULT_OUTPUT_SCHEMA = protocol.DEFAULT_OUTPUT_SCHEMA
LOCAL_TOOL_PATHS = protocol.LOCAL_TOOL_PATHS
SYSTEM_PROMPT = (
    "You are wasm-agent's direct LLM-native head. Use only the provided compact "
    "envelope; do not assume hidden Hermes conversation, memory, tool, or session "
    "context exists. Prefer the local Agent Kernel before Hermes. If an answer "
    "depends on unknown runtime, entity, workspace, file, timeline, or proof "
    "state, choose kernel.resolve, kernel.inspect, or kernel.prove before "
    "answering. For implementation objectives, route to the owned repo action "
    "and proof lane first; runtime/entity routes are supporting evidence, not "
    "the primary task route. If runtime_entity_routes are present for an "
    "informational objective, inspect or dispatch using that declared route "
    "rather than the enclosing UI route. Request proof when "
    "blocked. When LOCAL_KERNEL_EVIDENCE is present, use it as MCP/tool evidence "
    "and compose the best human answer you can; do not dump raw proof, table "
    "lists, or mechanical key=value summaries unless the user asks for audit "
    "details. Existing ROUTE/ROOT/file-receipt proof is enough to answer basic "
    "codebase-access questions; do not announce future inspection unless you "
    "emit the matching executable action. Keep normal answers as plain text for humans."
)


def provider_messages(
    body: dict[str, Any],
    envelope: dict[str, Any],
    semantic: str,
    *,
    clip: Any,
) -> list[dict[str, str]]:
    if cyphers_v3.is_v3(envelope):
        return [
            {"role": "system", "content": cyphers_v3.SYSTEM_PROMPT},
            {"role": "user", "content": semantic},
        ]
    instructions = clip(str(body.get("instructions") or "").strip(), 4000)
    content = [
        "Treat this compact semantic envelope as the complete context for this decision.",
        (
            "For a direct answer, return plain human-readable text only. "
            "Do not wrap normal answers in JSON. If any tool, file, runtime, transcript, "
            "kernel, or Hermes work is required, return only minified JSON as the first byte "
            "of the response: no prose, no markdown fence, no explanation before or after. "
            "Action JSON must contain answer, decision, actions, state_delta, needs, and "
            "confidence. Use actions like {\"action\":\"kernel.inspect\",\"args\":{...}} "
            "or {\"action\":\"dispatch.hermes\",\"objective\":\"...\",\"caps\":[...],"
            "\"escalation_reason\":\"...\",\"refs\":[...],\"proof\":[...]}. "
            "Never say you are dispatching, inspecting, reading, running, or executing unless "
            "the same JSON contains that executable action."
        ),
        semantic,
    ]
    if instructions:
        content.insert(2, f"Additional operator instructions:\n{instructions}")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(content)},
    ]

SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|authorization|bearer|cookie|password|secret|(^|[_-])(access|auth|id|refresh|session)?[_-]?token($|[_-]))",
    re.IGNORECASE,
)
TOOL_INTENT_RE = re.compile(
    r"\b("
    r"dispatch(?:ing|ed)?(?:\s+bounded)?(?:\s+(?:inspection|inspections|work|hermes))?"
    r"|kernel\.(?:inspect|resolve|act|prove|capabilities)"
    r"|transcript\.read|messages\.read"
    r"|hermes\s+dispatch"
    r")\b",
    re.IGNORECASE,
)
FUTURE_INSPECTION_CLAIM_RE = re.compile(
    r"\b(?:let me|i(?:'ll| will| am going to| need to| have to))\s+"
    r"(?:inspect|read|check|locate|search|scan|verify)\b",
    re.IGNORECASE,
)
REPO_OBJECT_TERM_RE = re.compile(
    r"\b(?:widget|component|module|file|function|class|route|endpoint|screen|view|panel|tool|code|implementation)\b",
    re.IGNORECASE,
)
MISSING_REPO_CONTEXT_RE = re.compile(
    r"\b(?:i\s+(?:do\s+not|don't)\s+(?:have|see)|no\s+attachments?|nothing\s+.*contains|"
    r"could\s+you\s+(?:paste|send|attach)|please\s+(?:paste|send|attach))\b",
    re.IGNORECASE,
)
RUNTIME_PROOF_CAVEAT_RE = re.compile(
    r"\b(?:runtime|scope|availability).*\b(?:not\s+(?:proven|verified|inspected)|unverified|missing)\b"
    r"|\b(?:not\s+(?:proven|verified|inspected)|unverified|missing).*\b(?:runtime|scope|availability)\b"
    r"|\bi\s+(?:do\s+not|don't)\s+have\b.*\b(?:runtime|scope|availability)\b.*\bproof\b",
    re.IGNORECASE,
)
BARE_INSPECTION_DECISION_RE = re.compile(
    r"(?:^|[\s_-])(?:inspect|read|check|locate|search|scan)(?:$|[\s_-])",
    re.IGNORECASE,
)
KERNEL_ACTION_DECISION_RE = re.compile(
    r"\b(?:route\s+to|dispatch|use|call|run)\s+kernel\.(?:inspect|resolve|act|prove|capabilities)\b",
    re.IGNORECASE,
)
EXECUTIVE_INTENT_RE = re.compile(
    r"\b(now|next|will|I'll|I will|I'm|I am|dispatching|executing|running|starting)\b",
    re.IGNORECASE,
)


def clipped(value: str, limit: int) -> str:
    return route_contracts.clipped(value, limit)


def json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=True))


def redact(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[depth-clipped]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 80:
                result["__clipped_keys__"] = len(value) - index
                break
            clean_key = clipped(str(key), 120)
            result[clean_key] = "[redacted]" if SENSITIVE_KEY_RE.search(clean_key) else redact(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        result = [redact(item, depth=depth + 1) for item in value[:80]]
        if len(value) > 80:
            result.append({"__clipped_items__": len(value) - 80})
        return result
    if isinstance(value, str):
        return clipped(value, 6000)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return clipped(str(value), 1000)


def json_text(value: Any, *, limit: int = MAX_JSON_CHARS) -> str:
    return clipped(json.dumps(value, ensure_ascii=True, separators=(",", ":")), limit)


def inline(value: Any, limit: int = 1200) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return clipped(value, limit)
    return json_text(value, limit=limit)


def output_schema_projection(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    projected = redact(value)
    properties = projected.get("properties") if isinstance(projected, dict) and isinstance(projected.get("properties"), dict) else {}
    if "state_feedback" in properties:
        properties.pop("state_feedback", None)
    return projected


def reflection_contract_projection(envelope: dict[str, Any]) -> dict[str, Any]:
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    if contract.get("evidence_floor") != "conceptual" and state_mode_projection(envelope) != "reflective":
        return {}
    return {
        "model_reflection": "allowed_labeled_self_model_not_proof",
        "rule": "separate subjective/metaphorical self-critique from inspected factual claims",
    }


def last_feedback_projection(envelope: dict[str, Any]) -> dict[str, Any]:
    raw = envelope.get("last_feedback") if isinstance(envelope.get("last_feedback"), dict) else {}
    status = clipped(str(raw.get("status") or ""), 40)
    if status not in {"accepted", "corrected", "rejected", "unclear"}:
        status = ""
    result: dict[str, Any] = {}
    if status:
        result["status"] = status
    for key, limit in (("last_action", 80), ("reply_sha16", 32)):
        value = clipped(str(raw.get(key) or ""), limit)
        if value:
            result[key] = value
    return result


def recent_transcript_projection(envelope: dict[str, Any]) -> dict[str, Any]:
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    recall_budget = contract.get("recall_budget") if isinstance(contract.get("recall_budget"), dict) else {}
    if state_mode_projection(envelope) != "reflective" and recall_budget.get("mode") not in {"reflective", "bounded_recent"}:
        return {}
    transcript_cache = envelope.get("transcript_cache") if isinstance(envelope.get("transcript_cache"), dict) else {}
    turns = transcript_cache.get("turns") if isinstance(transcript_cache.get("turns"), list) else []
    if not turns:
        return {}
    try:
        limit = max(1, min(4, int(recall_budget.get("transcript_turns") or 4)))
    except Exception:
        limit = 4
    projected_turns: list[dict[str, Any]] = []
    for turn in turns[-limit:]:
        if not isinstance(turn, dict):
            continue
        role = clipped(str(turn.get("role") or turn.get("r") or ""), 16)
        if role == "u":
            role = "user"
        elif role == "a":
            role = "assistant"
        content = clipped(str(turn.get("content") or turn.get("text") or turn.get("message") or ""), 280)
        anchor = clipped(str(turn.get("anchor") or turn.get("kind") or ""), 80)
        sha16 = clipped(str(turn.get("sha16") or turn.get("digest") or ""), 32)
        item = {
            "i": turn.get("i") if isinstance(turn.get("i"), int) else turn.get("index"),
            "r": role,
            "a": anchor,
            "sha16": sha16,
            "text": content,
        }
        item = {key: value for key, value in item.items() if value not in (None, "", [], {})}
        if item:
            projected_turns.append(redact(item))
    if not projected_turns:
        return {}
    return {
        "mode": "session_local_reflective",
        "turns": projected_turns,
        "source": "transcript_cache",
        "persistent": False,
    }


def names(value: Any, key: str = "id") -> str:
    if isinstance(value, str):
        return clipped(value, 1000)
    if isinstance(value, list):
        result = []
        for item in value[:24]:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                result.append(str(item.get(key) or item.get("name") or item.get("type") or item.get("action") or "item"))
        return ", ".join(clipped(str(item), 80) for item in result if str(item).strip())
    if isinstance(value, dict):
        return ", ".join(clipped(str(key), 80) for key in list(value.keys())[:24])
    return clipped(str(value), 1000)


def compact_string_list(value: Any, *, limit: int = 6, item_limit: int = 120) -> list[str]:
    if isinstance(value, str):
        return [clipped(value, item_limit)] if value.strip() else []
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = ":".join(
                part
                for part in (
                    str(item.get("turn") or item.get("i") or item.get("id") or "").strip(),
                    str(item.get("kind") or item.get("type") or "").strip(),
                    str(item.get("anchor") or item.get("summary") or item.get("label") or "").strip(),
                )
                if part
            )
        else:
            text = str(item)
        text = clipped(text.strip(), item_limit)
        if text and text not in result:
            result.append(text)
    return result


def state_projection(envelope: dict[str, Any]) -> dict[str, Any]:
    compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    state_summary = envelope.get("state_summary")
    if isinstance(state_summary, dict):
        source = state_summary
    else:
        source = compact_state
    result: dict[str, Any] = {}
    for key in ("arc", "open_commitments", "last_proof", "user_tone", "affect", "state_mode"):
        value = source.get(key) if isinstance(source, dict) else None
        if value not in (None, "", [], {}):
            result[key] = redact(value)
    compact_extra = {
        key: value
        for key, value in compact_state.items()
        if key not in {"continuity", "coverage", "anchors"} and value not in (None, "", [], {})
    }
    if compact_extra:
        result["compact"] = redact(compact_extra)
    return result


def state_mode_projection(envelope: dict[str, Any]) -> str:
    compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    state_summary = envelope.get("state_summary") if isinstance(envelope.get("state_summary"), dict) else {}
    raw = envelope.get("state_mode") or envelope.get("stateMode") or state_summary.get("state_mode") or compact_state.get("state_mode")
    value = clipped(str(raw or "").strip().lower(), 60)
    aliases = {
        "blocked": "blocked_on_proof",
        "blocked_on_proof": "blocked_on_proof",
        "explore": "exploring",
        "exploring": "exploring",
        "converge": "converging",
        "converging": "converging",
        "debug": "debugging",
        "debugging": "debugging",
        "reflect": "reflective",
        "reflective": "reflective",
    }
    if value in aliases:
        return aliases[value]
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    if contract.get("evidence_floor") == "conceptual":
        return "reflective"
    return ""


def affect_projection(envelope: dict[str, Any]) -> str:
    compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    state_summary = envelope.get("state_summary") if isinstance(envelope.get("state_summary"), dict) else {}
    raw = envelope.get("affect") or envelope.get("affective_state") or state_summary.get("affect") or compact_state.get("affect") or state_summary.get("user_tone") or compact_state.get("user_tone")
    value = clipped(str(raw or "").strip().lower(), 40)
    aliases = {
        "debug": "debugging",
        "debugging": "debugging",
        "urgent": "urgent",
        "play": "playful",
        "playful": "playful",
        "focus": "focused",
        "focused": "focused",
        "reflect": "reflective",
        "reflective": "reflective",
    }
    if value in aliases:
        return aliases[value]
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    if contract.get("evidence_floor") == "conceptual":
        return "reflective"
    return ""


def caps_verified_projection(envelope: dict[str, Any]) -> list[str]:
    raw = envelope.get("caps_verified") or envelope.get("verified_caps") or envelope.get("capabilities_verified")
    if not raw:
        route_contract = envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else {}
        raw = route_contract.get("caps_verified") or route_contract.get("verified_caps")
    return compact_string_list(raw, limit=10, item_limit=80)


def coverage_projection(envelope: dict[str, Any]) -> dict[str, Any]:
    compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    state_summary = envelope.get("state_summary") if isinstance(envelope.get("state_summary"), dict) else {}
    raw = (
        envelope.get("coverage")
        or envelope.get("context_coverage")
        or state_summary.get("coverage")
        or compact_state.get("coverage")
    )
    if isinstance(raw, dict):
        level = clipped(str(raw.get("level") or raw.get("state") or ""), 40)
        gaps = compact_string_list(raw.get("gaps"), limit=4, item_limit=80)
    else:
        level = clipped(str(raw or ""), 40)
        gaps = []
    if level not in {"rich", "thin", "ambiguous", "stale"}:
        continuity = compact_state.get("continuity") if isinstance(compact_state.get("continuity"), dict) else {}
        if continuity.get("stale"):
            level = "stale"
        elif continuity.get("csc") and (continuity.get("digest") or continuity.get("covers")):
            level = "rich"
        elif continuity.get("csc") or envelope.get("state_summary") or compact_state:
            level = "thin"
        else:
            level = "ambiguous"
    result: dict[str, Any] = {"level": level}
    if gaps:
        result["gaps"] = gaps
    return result


def anchors_projection(envelope: dict[str, Any]) -> list[str]:
    compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    transcript_cache = envelope.get("transcript_cache") if isinstance(envelope.get("transcript_cache"), dict) else {}
    candidates = (
        envelope.get("anchors")
        or envelope.get("state_anchors")
        or compact_state.get("anchors")
        or transcript_cache.get("anchors")
        or []
    )
    anchors = compact_string_list(candidates, limit=4, item_limit=120)
    if anchors:
        return anchors
    continuity = compact_state.get("continuity") if isinstance(compact_state.get("continuity"), dict) else {}
    csc = str(continuity.get("csc") or "")
    inferred: list[str] = []
    for line in csc.splitlines()[:12]:
        if not line or line.startswith(("CSC/", "TRC/")):
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 5:
            inferred.append(":".join(part for part in (parts[0], parts[2], parts[3]) if part))
    return compact_string_list(inferred, limit=3, item_limit=120)


def kernel_projection(envelope: dict[str, Any]) -> dict[str, Any]:
    contract = envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else None
    route_id = str((contract or {}).get("route_id") or envelope.get("route_id") or envelope.get("route") or "")
    return {
        "schema": "hermes.wasm_agent.kernel.projection.v1",
        "mode": "local-first",
        "route_id": route_id,
        "actions": ["kernel.capabilities", "kernel.resolve", "kernel.inspect", "kernel.act", "kernel.prove"],
        "rule": "unknown_state_requires_kernel_before_answer",
        "intent_priority": "implementation_uses_owned_repo_action_lane_before_entity_inspection",
        "hermes": "capability-gap-only",
    }


def task_contract_projection(envelope: dict[str, Any]) -> dict[str, Any]:
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    if not contract:
        return {}
    projected = {
        "i": contract.get("intent"),
        "x": contract.get("executor"),
        "f": contract.get("evidence_floor"),
        "r": contract.get("route_intent"),
        "d": contract.get("depth"),
        "rb": contract.get("recall_budget"),
        "t": contract.get("tools_first"),
        "p": contract.get("proof_required"),
        "b": contract.get("block_codes"),
        "h": contract.get("hermes"),
    }
    return {key: value for key, value in projected.items() if value not in (None, "", [], {})}


def evidence_floor(envelope: dict[str, Any]) -> str:
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    return clipped(str(contract.get("evidence_floor") or envelope.get("evidence_floor") or ""), 80)


def conceptual_evidence_floor(envelope: dict[str, Any]) -> bool:
    return evidence_floor(envelope) == "conceptual"


def normalize_conceptual_result(envelope: dict[str, Any], parsed: Any, result: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    downgraded = downgraded_conceptual_answer(envelope, parsed, str(result.get("reply") or ""))
    if not downgraded:
        return parsed, result
    reply = suppress_duplicate_answer_blocks(str(downgraded.get("answer") or ""))
    normalized = {**downgraded, "answer": reply}
    return normalized, {**result, "parsed": normalized, "reply": reply}


def evidence_projection(envelope: dict[str, Any]) -> dict[str, Any]:
    compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    continuity = compact_state.get("continuity") if isinstance(compact_state.get("continuity"), dict) else {}
    local_evidence = envelope.get("local_kernel_evidence")
    refs = envelope.get("evidence_refs") or envelope.get("evidence")
    transcript_cache = envelope.get("transcript_cache") if isinstance(envelope.get("transcript_cache"), dict) else {}
    result: dict[str, Any] = {}
    result["coverage"] = coverage_projection(envelope).get("level")
    if envelope.get("route_id") or envelope.get("route"):
        result["route"] = "declared"
    if isinstance(envelope.get("route_contract"), dict):
        result["route_contract"] = "attached"
    if refs:
        result["refs"] = names(refs, key="ref")
    if isinstance(local_evidence, list) and local_evidence:
        result["local"] = len(local_evidence[:80])
    elif isinstance(local_evidence, dict) and local_evidence:
        result["local"] = "attached"
    if continuity.get("handle"):
        recall_state = "fresh" if continuity.get("csc") and (continuity.get("digest") or transcript_cache.get("digest")) else "ambiguous"
        if continuity.get("stale") or transcript_cache.get("stale"):
            recall_state = "stale"
        result["recall"] = {
            "state": recall_state,
            "csc": bool(continuity.get("csc")),
            "handle": clipped(str(continuity.get("handle") or ""), 240),
            "pull": "transcript.read",
        }
        cover_digest = transcript_cache.get("cover_digest") or transcript_cache.get("coverDigest") or transcript_cache.get("span_digest") or transcript_cache.get("spanDigest")
        if cover_digest:
            result["recall"]["cover_digest"] = clipped(str(cover_digest), 80)
    actions = names(envelope.get("allowed_actions"))
    recall_actions = [item for item in ("transcript.read", "memory.search", "messages.read") if item in actions]
    if recall_actions:
        result["recall_tools"] = recall_actions
    return result


def self_check_projection(envelope: dict[str, Any], parsed: Any, reply: str, *, local_tool_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    text = tool_intent_text(parsed, reply)
    actions = local_tool_actions(parsed) or ([hermes_dispatch_action(parsed)] if hermes_dispatch_action(parsed) else [])
    lower = text.lower()
    proof_words = ("verified", "confirmed", "inspected", "proved")
    proof_claimed = any(word in lower for word in proof_words)
    has_local_evidence = bool(local_tool_results) or bool(envelope.get("local_kernel_evidence"))
    route_declared = bool(envelope.get("route_id") or envelope.get("route") or isinstance(envelope.get("route_contract"), dict))
    claims_verified = proof_claimed and (has_local_evidence or route_declared)
    actions_claimed = bool(TOOL_INTENT_RE.search(text) and EXECUTIVE_INTENT_RE.search(text))
    actions_present = bool(actions)
    return {
        "claims_verified": bool(claims_verified),
        "actions_claimed": bool(actions_claimed),
        "actions_present": bool(actions_present),
        "proof_overclaim": bool(proof_claimed and not (has_local_evidence or route_declared)),
    }


def state_writeback_projection(
    envelope: dict[str, Any],
    parsed: Any,
    reply: str,
    *,
    local_tool_results: list[dict[str, Any]] | None = None,
    dispatch_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed_dict = parsed if isinstance(parsed, dict) else {}
    state_delta = parsed_dict.get("state_delta") if isinstance(parsed_dict.get("state_delta"), dict) else {}
    state_feedback = parsed_dict.get("state_feedback") if isinstance(parsed_dict.get("state_feedback"), dict) else {}
    model_reflection = parsed_dict.get("model_reflection") if isinstance(parsed_dict.get("model_reflection"), dict) else {}
    actions = parsed_dict.get("actions") if isinstance(parsed_dict.get("actions"), list) else []
    last_action = "answer"
    if isinstance(dispatch_result, dict):
        last_action = "dispatch"
    elif local_tool_results:
        last_action = "tool"
    elif actions:
        first = actions[0] if isinstance(actions[0], dict) else {}
        last_action = clipped(str(first.get("action") or first.get("id") or first.get("type") or "action"), 80)
    feedback_status = clipped(str(state_feedback.get("last_feedback") or state_feedback.get("status") or "accepted"), 40)
    coverage = clipped(str(state_feedback.get("coverage") or coverage_projection(envelope).get("level") or ""), 40)
    mode = clipped(str(state_feedback.get("state_mode") or state_feedback.get("mode") or state_mode_projection(envelope) or ""), 60)
    suggested_anchor = clipped(str(state_feedback.get("suggested_anchor") or ""), 160)
    repo_object_context: dict[str, Any] = {}
    for item in (local_tool_results or [])[:8]:
        if not isinstance(item, dict) or item.get("tool") != "code.memory.search":
            continue
        result_item = item.get("result") if isinstance(item.get("result"), dict) else {}
        code_items = result_item.get("items") if isinstance(result_item.get("items"), list) else []
        paths: list[str] = []
        names_found: list[str] = []
        for code_item in code_items[:6]:
            if not isinstance(code_item, dict):
                continue
            path = clipped(str(code_item.get("file") or code_item.get("file_path") or code_item.get("path") or ""), 240)
            name = clipped(str(code_item.get("name") or code_item.get("qualified_name") or ""), 240)
            if path and path not in paths:
                paths.append(path)
            if name and name not in names_found:
                names_found.append(name)
        if paths or names_found:
            repo_object_context = {
                "query": clipped(str(result_item.get("query") or ""), 120),
                "paths": paths[:4],
                "names": names_found[:4],
            }
            break
    result = {
        "schema": "hermes.wasm_agent.state_writeback.v1",
        "state_delta": redact(state_delta),
        "state_feedback": redact(state_feedback),
        "model_reflection": redact(model_reflection),
        "last_action": last_action,
        "last_feedback": feedback_status if feedback_status in {"accepted", "corrected", "rejected", "unclear"} else "accepted",
        "next": {
            "coverage": coverage,
            "state_mode": mode,
            "suggested_anchor": suggested_anchor,
            "repo_object_context": repo_object_context,
            "quest_state": entity_resolution.quest_state_from_evidence(envelope, local_tool_results or []),
        },
        "reply_sha16": hashlib.sha256(str(reply or "").encode("utf-8", errors="ignore")).hexdigest()[:16],
    }
    result["next"] = {key: value for key, value in result["next"].items() if value}
    return result


def apply_state_writeback(envelope: dict[str, Any], writeback: dict[str, Any]) -> None:
    next_state = writeback.get("next") if isinstance(writeback.get("next"), dict) else {}
    compact_state = dict(envelope.get("compact_state")) if isinstance(envelope.get("compact_state"), dict) else {}
    if next_state.get("coverage") and not compact_state.get("coverage") and not envelope.get("coverage"):
        compact_state["coverage"] = {"level": clipped(str(next_state.get("coverage")), 40)}
    if next_state.get("state_mode") and not compact_state.get("state_mode") and not envelope.get("state_mode"):
        compact_state["state_mode"] = clipped(str(next_state.get("state_mode")), 60)
    anchor = clipped(str(next_state.get("suggested_anchor") or ""), 160)
    if anchor and not (envelope.get("anchors") or compact_state.get("anchors")):
        compact_state["anchors"] = [anchor]
    for key in ("repo_object_context", "quest_state"):
        value = next_state.get(key) if isinstance(next_state.get(key), dict) else {}
        if value and not compact_state.get(key):
            compact_state[key] = redact(value)
    if compact_state:
        envelope["compact_state"] = redact(compact_state)
    envelope["last_feedback"] = {
        "status": clipped(str(writeback.get("last_feedback") or "accepted"), 40),
        "last_action": clipped(str(writeback.get("last_action") or ""), 80),
        "reply_sha16": clipped(str(writeback.get("reply_sha16") or ""), 32),
    }


def semantic_text(envelope: dict[str, Any]) -> str:
    if cyphers_v3.is_v3(envelope):
        return cyphers_v3.bootstrap(envelope)
    refs = envelope.get("evidence_refs") or envelope.get("evidence")
    route_contract = envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else {}
    compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    continuity = compact_state.get("continuity") if isinstance(compact_state.get("continuity"), dict) else {}
    quest_state = compact_state.get("quest_state") if isinstance(compact_state.get("quest_state"), dict) else {}
    quest_line = str(quest_state.get("line") or "")
    lines = [
        "ENV agent-envelope-v1",
        f"OBJ {inline(envelope.get('objective'), 1600)}",
        f"OBJ_KIND {inline(envelope.get('objective_kind'), 120)}",
        f"ROUTE {inline(envelope.get('route_id') or envelope.get('route'), 300)}",
        f"SURFACE {inline(envelope.get('surface'), 160)}",
        f"HEAD {inline(envelope.get('head_identity'), 800)}",
        f"A {inline(affect_projection(envelope), 80)}",
        f"STATE_MODE {inline(state_mode_projection(envelope), 80)}",
        f"LAST_FEEDBACK {inline(last_feedback_projection(envelope), 300)}",
        f"RECENT {inline(recent_transcript_projection(envelope), 1400)}",
        f"CONT {inline(continuity.get('csc'), 1800)}",
        f"QS {inline(quest_line, 500)}",
        f"SRC {inline(envelope.get('repo_object_evidence_line'), 500)}",
        f"ROOT {inline(route_contract.get('workspace_root'), 500)}",
        f"STATE {inline(state_projection(envelope) or envelope.get('state_summary') or envelope.get('compact_state'), 1600)}",
        f"ANCHORS {inline(anchors_projection(envelope), 800)}",
        f"CAPS {names(envelope.get('capabilities'))}",
        f"CAPS_VERIFIED {inline(caps_verified_projection(envelope), 500)}",
        f"REFS {names(refs, key='ref')}",
        f"RUNTIME_ROUTES {inline(envelope.get('runtime_entity_routes'), 1600)}",
        f"KERNEL {inline(kernel_projection(envelope), 900)}",
        f"PLAN {inline(task_contract_projection(envelope), 800)}",
        f"REFLECT {inline(reflection_contract_projection(envelope), 400)}",
        f"EVID {inline(evidence_projection(envelope), 1200)}",
        f"LOCAL_KERNEL_EVIDENCE {inline(envelope.get('local_kernel_evidence'), 5000)}",
        f"ACT {names(envelope.get('allowed_actions'))}",
        f"RULES {inline(envelope.get('constraints'), 1800)}",
        f"PROOF {inline(envelope.get('proof_requests'), 900)}",
        f"BUDGET {inline(envelope.get('budget'), 500)}",
        "STREAM true" if envelope.get("stream") is True else "STREAM false",
        f"OUT {inline(output_schema_projection(envelope.get('output_schema')), 1000)}",
    ]
    return "\n".join(line for line in lines if line.split(" ", 1)[-1].strip())


def action_name(action: dict[str, Any]) -> str:
    return clipped(str(action.get("act") or action.get("action") or action.get("id") or action.get("type") or ""), 120).lower()


def action_args(action: dict[str, Any]) -> dict[str, Any]:
    raw = action.get("args") or action.get("arguments") or action.get("input") or action.get("body")
    return raw if isinstance(raw, dict) else {}


def canonical_action_name(action: dict[str, Any]) -> str:
    name = action_name(action)
    args = action_args(action)
    route_id = str(args.get("route_id") or args.get("route") or action.get("route_id") or action.get("route") or "").strip()
    node_id = str(
        args.get("node_id")
        or args.get("node")
        or args.get("target_node")
        or action.get("node_id")
        or action.get("node")
        or action.get("target_node")
        or ""
    ).strip()
    if name == "kernel.capabilities" and (node_id or route_id.startswith("hermes-node.")):
        return "node.capabilities"
    return name


def hermes_dispatch_action(parsed: Any) -> dict[str, Any] | None:
    if not isinstance(parsed, dict):
        return None
    actions = parsed.get("actions") if isinstance(parsed.get("actions"), list) else []
    for action in actions:
        if isinstance(action, dict) and canonical_action_name(action) == "dispatch.hermes":
            return action
    return None


def local_tool_actions(parsed: Any) -> list[dict[str, Any]]:
    if not isinstance(parsed, dict):
        return []
    actions = parsed.get("actions") if isinstance(parsed.get("actions"), list) else []
    return [
        action
        for action in actions[:12]
        if isinstance(action, dict) and canonical_action_name(action) in LOCAL_TOOL_PATHS
    ]


def declared_needs(parsed: Any) -> list[str]:
    if not isinstance(parsed, dict):
        return []
    needs = parsed.get("needs") if isinstance(parsed.get("needs"), list) else []
    return [clipped(str(item or "").strip(), 240) for item in needs[:12] if str(item or "").strip()]


def has_executable_action(parsed: Any) -> bool:
    return bool(local_tool_actions(parsed) or hermes_dispatch_action(parsed))


def tool_intent_text(parsed: Any, reply: str) -> str:
    parts: list[str] = []
    if isinstance(parsed, dict):
        for key in ("decision", "answer"):
            value = str(parsed.get(key) or "").strip()
            if value:
                parts.append(value)
        actions = parsed.get("actions") if isinstance(parsed.get("actions"), list) else []
        for action in actions[:12]:
            if isinstance(action, dict):
                parts.append(canonical_action_name(action))
                parts.append(dispatch.action_text(action, {}))
    if reply:
        parts.append(str(reply))
    return "\n".join(part for part in parts if part)


def reply_looks_like_action_json(reply: str) -> bool:
    text = str(reply or "").strip()
    if not text:
        return False
    fenced = re.search(r"```(?:json)?\s*(.*)$", text, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1).strip() if fenced else text
    if not candidate.startswith(("{", "[")):
        return False
    return bool(re.search(r'"(?:actions?|tool|name)"\s*:', candidate, re.IGNORECASE))


def requires_structured_action(parsed: Any, reply: str) -> bool:
    if has_executable_action(parsed):
        return False
    text = tool_intent_text(parsed, reply)
    if not text:
        return False
    if (not isinstance(parsed, dict) or not parsed) and reply_looks_like_action_json(reply):
        return True
    if isinstance(parsed, dict):
        decision = str(parsed.get("decision") or "").strip().lower()
        if decision in {
            "dispatch",
            "dispatch.hermes",
            "kernel.inspect",
            "kernel.resolve",
            "kernel.act",
            "kernel.prove",
            "transcript.read",
            "messages.read",
        }:
            return True
        if decision and BARE_INSPECTION_DECISION_RE.search(decision):
            return True
        if decision and KERNEL_ACTION_DECISION_RE.search(decision):
            return True
    if TOOL_INTENT_RE.search(text) and EXECUTIVE_INTENT_RE.search(text):
        return True
    if KERNEL_ACTION_DECISION_RE.search(text):
        return True
    if FUTURE_INSPECTION_CLAIM_RE.search(text):
        return True
    if MISSING_REPO_CONTEXT_RE.search(text) and REPO_OBJECT_TERM_RE.search(text) and not RUNTIME_PROOF_CAVEAT_RE.search(text):
        return True
    fenced = re.search(r"```(?:json)?\s*(.*)$", str(reply or ""), re.DOTALL | re.IGNORECASE)
    if fenced and TOOL_INTENT_RE.search(fenced.group(1)):
        return True
    return False


def requires_repo_object_lookup(parsed: Any, reply: str) -> bool:
    text = tool_intent_text(parsed, reply)
    return bool(MISSING_REPO_CONTEXT_RE.search(text) and REPO_OBJECT_TERM_RE.search(text))


FUTURE_ACTION_OFFER_SENTENCE_RE = re.compile(
    r"(?:(?:if|when)\s+you(?:'d| would)?\s+like[^.!?\n]*[, ]\s*)?"
    r"(?:i\s+can|i'll|i\s+will)\s+"
    r"(?:dispatch|run|inspect|look up|query|execute|check|verify)[^.!?\n]*[.!?]",
    re.IGNORECASE,
)
CONVERSATION_ACTION_CLAIM_SENTENCE_RE = re.compile(
    r"(?:^|(?<=[.!?])\s+)"
    r"(?:let me|i(?:'m| am| will|'ll| need to| have to))\s+"
    r"(?:dispatch|run|inspect|look up|query|execute|check|verify|read|search|scan)[^.!?\n]*[.!?]",
    re.IGNORECASE,
)


def objective_kind(envelope: dict[str, Any] | None) -> str:
    if not isinstance(envelope, dict):
        return ""
    return clipped(str(envelope.get("objective_kind") or "").strip().lower(), 80)


def conversation_structured_action_can_salvage(envelope: dict[str, Any] | None, parsed: Any, reply: str) -> bool:
    contract = envelope.get("task_contract") if isinstance(envelope, dict) and isinstance(envelope.get("task_contract"), dict) else {}
    if objective_kind(envelope) != "conversation" and contract.get("evidence_floor") != "conceptual":
        return False
    if has_executable_action(parsed) or reply_looks_like_action_json(reply):
        return False
    if isinstance(parsed, dict):
        decision = str(parsed.get("decision") or "").strip().lower()
        if decision in {
            "dispatch",
            "dispatch.hermes",
            "kernel.inspect",
            "kernel.resolve",
            "kernel.act",
            "kernel.prove",
            "transcript.read",
            "messages.read",
        }:
            return False
    return bool(str(reply or "").strip())


def salvage_conversation_answer(envelope: dict[str, Any] | None, parsed: Any, reply: str) -> str:
    if not conversation_structured_action_can_salvage(envelope, parsed, reply):
        return ""
    answer = str(parsed.get("answer") or "").strip() if isinstance(parsed, dict) else ""
    text = answer or str(reply or "").strip()
    text = FUTURE_ACTION_OFFER_SENTENCE_RE.sub("", text)
    text = CONVERSATION_ACTION_CLAIM_SENTENCE_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def downgraded_conceptual_answer(envelope: dict[str, Any] | None, parsed: Any, reply: str) -> dict[str, Any] | None:
    if not isinstance(envelope, dict):
        return None
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    if contract.get("evidence_floor") != "conceptual":
        return None
    parsed = parsed if isinstance(parsed, dict) else {}
    answer = str(parsed.get("answer") or reply or "").strip()
    if not answer or reply_looks_like_action_json(reply):
        return None
    actions = parsed.get("actions") if isinstance(parsed.get("actions"), list) else []
    if actions:
        return None
    sanitized = salvage_conversation_answer({**envelope, "objective_kind": "conversation"}, parsed, answer)
    if not sanitized:
        sanitized = FUTURE_ACTION_OFFER_SENTENCE_RE.sub("", answer).strip()
    if not sanitized:
        return None
    return {
        "answer": sanitized,
        "decision": "answer",
        "actions": [],
        "state_delta": {},
        "state_feedback": parsed.get("state_feedback") if isinstance(parsed.get("state_feedback"), dict) else {},
        "model_reflection": parsed.get("model_reflection") if isinstance(parsed.get("model_reflection"), dict) else {},
        "needs": parsed.get("needs") if isinstance(parsed.get("needs"), list) else [],
        "confidence": parsed.get("confidence"),
        "downgraded_from": clipped(str(parsed.get("decision") or ""), 120),
    }


def salvage_continued_answer_after_tool_evidence(parsed: Any, reply: str) -> str:
    """Keep useful post-tool prose while removing unexecuted future action offers."""
    if not requires_structured_action(parsed, reply):
        return ""
    if reply_looks_like_action_json(reply):
        return ""
    if isinstance(parsed, dict):
        decision = str(parsed.get("decision") or "").strip().lower()
        if decision in {
            "dispatch",
            "dispatch.hermes",
            "kernel.inspect",
            "kernel.resolve",
            "kernel.act",
            "kernel.prove",
            "transcript.read",
            "messages.read",
        }:
            return ""
        answer = str(parsed.get("answer") or "").strip()
    else:
        answer = ""
    text = answer or str(reply or "").strip()
    if len(text) < 80:
        return ""
    sanitized = FUTURE_ACTION_OFFER_SENTENCE_RE.sub("", text)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized).strip()
    if len(sanitized) < 80:
        return ""
    return (
        sanitized
        + "\n\nI have not executed any additional action beyond the recorded local tool evidence in this turn."
    )


def suppress_duplicate_answer_blocks(reply: str) -> str:
    text = str(reply or "").strip()
    if not text:
        return ""
    marker_match = re.search(r"(?m)^(?:Here is|Here's) the honest critique from inside\b", text)
    if marker_match and marker_match.start() > 0:
        first = text[:marker_match.start()].strip()
        second = text[marker_match.start():].strip()
        if first and SequenceMatcher(None, first.lower(), second.lower()).ratio() >= 0.55:
            return second
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    if len(paragraphs) < 4:
        return text
    half = len(paragraphs) // 2
    first = "\n\n".join(paragraphs[:half])
    second = "\n\n".join(paragraphs[half:])
    if SequenceMatcher(None, first.lower(), second.lower()).ratio() >= 0.72:
        return second
    return text


def repo_object_lookup_action(envelope: dict[str, Any], reply: str = "") -> dict[str, Any]:
    objective = clipped(str(envelope.get("objective") or "").strip(), 500)
    query = objective or clipped(str(reply or "").strip(), 500) or "repo object"
    return {
        "answer": "",
        "decision": "code.memory.search",
        "actions": [{
            "action": "code.memory.search",
            "args": {
                "route_id": envelope.get("route_id") or envelope.get("route"),
                "query": query,
                "limit": 8,
            },
        }],
        "state_delta": {},
        "state_feedback": {},
        "model_reflection": {},
        "needs": [],
        "confidence": 0.7,
    }


def action_repair_body(body: dict[str, Any], bad_reply: str) -> dict[str, Any]:
    repaired = json_clone(body)
    prior = clipped(str(repaired.get("instructions") or "").strip(), 3000)
    repair = (
        "STRICT ACTION REPAIR: your previous response claimed tool/dispatch work but did not "
        "provide a complete executable action. Return ONLY minified JSON. The first character "
        "must be `{` and the last character must be `}`. No markdown, no prose, no recap. "
        "If work is needed, include actions with exact action ids from ACT, for example "
        "{\"action\":\"kernel.inspect\",\"args\":{\"kind\":\"continuity\"}} or "
        "{\"action\":\"code.memory.search\",\"args\":{\"query\":\"named repo object\"}} or "
        "{\"action\":\"dispatch.hermes\",\"objective\":\"...\",\"caps\":[\"repo.read\",\"proof.report\"],"
        "\"escalation_reason\":\"...\",\"refs\":[],\"proof\":[\"summary\"]}. "
        "If no work is needed, answer plainly without claiming execution. "
        f"Rejected output excerpt: {clipped(str(bad_reply or ''), 900)}"
    )
    repaired["instructions"] = " ".join(part for part in (prior, repair) if part)
    repaired["max_output_tokens"] = max(1200, int(repaired.get("max_output_tokens") or repaired.get("max_tokens") or 0))
    return repaired
