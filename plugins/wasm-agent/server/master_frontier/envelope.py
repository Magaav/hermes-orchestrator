from __future__ import annotations

import json
import re
from typing import Any

from . import dispatch
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
    "details. Keep normal answers as plain text for humans."
)

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
        "t": contract.get("tools_first"),
        "p": contract.get("proof_required"),
        "b": contract.get("block_codes"),
        "h": contract.get("hermes"),
    }
    return {key: value for key, value in projected.items() if value not in (None, "", [], {})}


def semantic_text(envelope: dict[str, Any]) -> str:
    refs = envelope.get("evidence_refs") or envelope.get("evidence")
    route_contract = envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else {}
    compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    continuity = compact_state.get("continuity") if isinstance(compact_state.get("continuity"), dict) else {}
    lines = [
        "ENV agent-envelope-v1",
        f"OBJ {inline(envelope.get('objective'), 1600)}",
        f"ROUTE {inline(envelope.get('route_id') or envelope.get('route'), 300)}",
        f"SURFACE {inline(envelope.get('surface'), 160)}",
        f"HEAD {inline(envelope.get('head_identity'), 800)}",
        f"CONT {inline(continuity.get('csc'), 1800)}",
        f"ROOT {inline(route_contract.get('workspace_root'), 500)}",
        f"STATE {inline(envelope.get('state_summary') or envelope.get('compact_state'), 1600)}",
        f"CAPS {names(envelope.get('capabilities'))}",
        f"REFS {names(refs, key='ref')}",
        f"RUNTIME_ROUTES {inline(envelope.get('runtime_entity_routes'), 1600)}",
        f"KERNEL {inline(kernel_projection(envelope), 900)}",
        f"PLAN {inline(task_contract_projection(envelope), 800)}",
        f"LOCAL_KERNEL_EVIDENCE {inline(envelope.get('local_kernel_evidence'), 5000)}",
        f"ACT {names(envelope.get('allowed_actions'))}",
        f"PROOF {inline(envelope.get('constraints') or envelope.get('proof_requests'), 900)}",
        f"BUDGET {inline(envelope.get('budget'), 500)}",
        "STREAM true" if envelope.get("stream") is True else "STREAM false",
        f"OUT {inline(envelope.get('output_schema'), 1200)}",
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
    if TOOL_INTENT_RE.search(text) and EXECUTIVE_INTENT_RE.search(text):
        return True
    fenced = re.search(r"```(?:json)?\s*(.*)$", str(reply or ""), re.DOTALL | re.IGNORECASE)
    if fenced and TOOL_INTENT_RE.search(fenced.group(1)):
        return True
    return False


def action_repair_body(body: dict[str, Any], bad_reply: str) -> dict[str, Any]:
    repaired = json_clone(body)
    prior = clipped(str(repaired.get("instructions") or "").strip(), 3000)
    repair = (
        "STRICT ACTION REPAIR: your previous response claimed tool/dispatch work but did not "
        "provide a complete executable action. Return ONLY minified JSON. The first character "
        "must be `{` and the last character must be `}`. No markdown, no prose, no recap. "
        "If work is needed, include actions with exact action ids from ACT, for example "
        "{\"action\":\"kernel.inspect\",\"args\":{\"kind\":\"continuity\"}} or "
        "{\"action\":\"dispatch.hermes\",\"objective\":\"...\",\"caps\":[\"repo.read\",\"proof.report\"],"
        "\"escalation_reason\":\"...\",\"refs\":[],\"proof\":[\"summary\"]}. "
        "If no work is needed, answer plainly without claiming execution. "
        f"Rejected output excerpt: {clipped(str(bad_reply or ''), 900)}"
    )
    repaired["instructions"] = " ".join(part for part in (prior, repair) if part)
    repaired["max_output_tokens"] = max(1200, int(repaired.get("max_output_tokens") or repaired.get("max_tokens") or 0))
    return repaired
