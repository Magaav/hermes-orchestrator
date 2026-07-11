from __future__ import annotations

import re
from typing import Any

from . import entity_resolution
from . import intent
from . import route_contracts


SCHEMA = "hermes.wasm_agent.master_frontier.loop.v1"
STATES = ("reason", "action", "observe", "critique", "decide_continue_or_finish")
FINISHED = "finished"
BLOCKED = "blocked"
INCOMPLETE = "incomplete"

RECEIPT_ONLY_RE = re.compile(
    r"\b("
    r"route\s+resolved|file\s+receipts?|no\s+files|objective|final\s*[✓x]?"
    r"|envelope\.created|head\.started|head\.decision|kernel\.inspect"
    r"|dispatch(?:ing|ed)?\s+(?:repo\s+)?inspection"
    r")\b",
    re.IGNORECASE,
)
USER_VALUE_RE = re.compile(
    r"\b("
    r"because|root cause|cause|what happened|degrading|architecture|architectural"
    r"|changed|patched|implemented|fixed|verified|proof|next step|blocked"
    r")\b",
    re.IGNORECASE,
)
SOURCE_TOOL_NAMES = {"code.memory.search", "file.read_bounded", "lookup.symbol"}
FUNCTIONAL_CLAIM_RE = re.compile(
    r"\b("
    r"uses?|calls?|sends?|takes?|keeps?|turns?|loads?|reads?|writes?|stores?|persists?|exports?|imports?"
    r"|identifies?|locates?|maps?"
    r"|renders?|shows?|displays?|queues?|ranks?|sorts?|filters?|flags?|scores?"
    r"|validates?|checks?|detects?|creates?|updates?|removes?|opens?|closes?"
    r"|depends?|requires?|returns?|produces?|generates?"
    r")\b",
    re.IGNORECASE,
)
NON_COGNITIVE_VERBS = {"show", "shows", "queue"}
RECEIPT_SHAPE_RE = re.compile(
    r"\b("
    r"code memory proof|kernel inspection proof|route-scoped result|file receipts?"
    r"|source-backed understanding|evidence\s+from|source\s+[`'\w./-]+\s+shows|returned\s+\d+|proof:"
    r")\b",
    re.IGNORECASE,
)


def _text(value: Any, limit: int = 4000) -> str:
    return route_contracts.clipped(str(value or "").strip(), limit)


def _answer(parsed: Any, reply: str) -> str:
    if str(reply or "").strip():
        return _text(reply, 12000)
    if isinstance(parsed, dict) and str(parsed.get("answer") or "").strip():
        return _text(parsed.get("answer"), 12000)
    return ""


def _actions(parsed: Any) -> list[dict[str, Any]]:
    actions = parsed.get("actions") if isinstance(parsed, dict) and isinstance(parsed.get("actions"), list) else []
    return [item for item in actions[:16] if isinstance(item, dict)]


def _changed_files(
    change_proof: dict[str, Any] | None,
    dispatch_result: dict[str, Any] | None,
    local_tool_results: list[dict[str, Any]] | None,
) -> list[Any]:
    changed = intent.changed_file_artifacts(change_proof or {}, dispatch_result if isinstance(dispatch_result, dict) else None)
    for item in local_tool_results or []:
        if not isinstance(item, dict):
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        for source in (result.get("changed_files"), result.get("changed")):
            if isinstance(source, list):
                changed.extend(source)
    return [item for item in changed if item]


def _local_tool_count(local_tool_results: list[dict[str, Any]] | None) -> int:
    return len([item for item in (local_tool_results or []) if isinstance(item, dict)])


def _tool_names(local_tool_results: list[dict[str, Any]] | None) -> list[str]:
    names: list[str] = []
    for item in (local_tool_results or [])[:12]:
        if not isinstance(item, dict):
            continue
        tool = _text(item.get("tool"), 120)
        if tool and tool not in names:
            names.append(tool)
    return names


def _source_evidence(local_tool_results: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        item
        for item in (local_tool_results or [])
        if isinstance(item, dict) and item.get("ok") and str(item.get("tool") or "") in SOURCE_TOOL_NAMES
    ]


def _strip_proof_sections(answer: str) -> str:
    text = str(answer or "").strip()
    return re.split(r"\n\s*(?:Code memory proof|Kernel inspection proof)\s*:", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()


def _answer_understanding(answer: str, *, local_tool_results: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Build a compact cognition artifact before completion is allowed."""
    body = _strip_proof_sections(answer)
    source_evidence = _source_evidence(local_tool_results)
    claim_verbs = [
        verb
        for verb in dict.fromkeys(match.group(1).lower() for match in FUNCTIONAL_CLAIM_RE.finditer(body))
        if verb not in NON_COGNITIVE_VERBS
    ][:12]
    receipt_shaped = bool(RECEIPT_SHAPE_RE.search(body))
    receipt_intro = bool(re.search(r"^\s*(?:the\s+)?source-backed understanding\b|^\s*evidence\s+from\b", body, re.IGNORECASE))
    word_count = len(re.findall(r"\w+", body))
    claim_count = len(claim_verbs)
    if not body:
        status = "insufficient"
        reason = "answer_missing"
    elif receipt_intro or (receipt_shaped and claim_count < 4):
        status = "insufficient"
        reason = "receipt_shaped_understanding"
    elif source_evidence and claim_count < 2:
        status = "insufficient"
        reason = "functional_claims_missing"
    elif source_evidence and word_count < 28:
        status = "insufficient"
        reason = "answer_plan_too_thin"
    else:
        status = "sufficient"
        reason = "typed_understanding_present"
    return {
        "schema": "hermes.wasm_agent.master_frontier.typed_understanding.v1",
        "status": status,
        "reason": reason,
        "source_evidence": [str(item.get("tool") or "") for item in source_evidence[:8]],
        "claim_verbs": claim_verbs,
        "claim_count": claim_count,
        "answer_words": word_count,
        "receipt_shaped": receipt_shaped,
        "receipt_intro": receipt_intro,
    }


def _answer_has_user_value(answer: str, *, local_tool_results: list[dict[str, Any]] | None) -> bool:
    clean = answer.strip()
    if len(clean) < 40:
        return False
    if "Kernel inspection proof:" in clean:
        return True
    if USER_VALUE_RE.search(clean):
        return True
    if _local_tool_count(local_tool_results) and RECEIPT_ONLY_RE.search(clean) and not USER_VALUE_RE.search(clean):
        return False
    return len(clean.split()) >= 12


def _repo_object_understanding_required(envelope: dict[str, Any], *, local_tool_results: list[dict[str, Any]] | None) -> bool:
    if not _source_evidence(local_tool_results):
        return False
    try:
        return bool(entity_resolution.is_repo_object_question(str(envelope.get("objective") or "")))
    except Exception:
        objective = str(envelope.get("objective") or "").lower()
        return bool(re.search(r"\bwhat\s+(?:does|is|are)|\bhow\s+does\b", objective) and re.search(r"\b(widget|module|component|function|tool|screen|view)\b", objective))


def start(envelope: dict[str, Any]) -> dict[str, Any]:
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    route_contract = envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else {}
    return {
        "schema": SCHEMA,
        "states": list(STATES),
        "state": "reason",
        "objective": _text(envelope.get("objective"), 500),
        "intent": contract.get("intent") or "",
        "route_id": contract.get("route_id") or route_contract.get("route_id") or envelope.get("route_id") or "",
        "workspace_root": contract.get("workspace_root") or route_contract.get("workspace_root") or "",
        "proof_required": contract.get("proof_required") if isinstance(contract.get("proof_required"), list) else [],
        "events": [{
            "state": "reason",
            "status": "ready",
            "summary": "Loop initialized with route-scoped task contract",
        }],
    }


def step_event(state: str, status: str, summary: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "state": state if state in STATES else "observe",
        "status": _text(status, 80),
        "summary": _text(summary, 240),
        "payload": payload or {},
    }


def evaluate_completion(
    envelope: dict[str, Any],
    parsed: Any,
    reply: str,
    *,
    local_tool_results: list[dict[str, Any]] | None = None,
    change_proof: dict[str, Any] | None = None,
    dispatch_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    loop = start(envelope)
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    block_codes = contract.get("block_codes") if isinstance(contract.get("block_codes"), list) else []
    answer = _answer(parsed, reply)
    actions = _actions(parsed)
    changed_files = _changed_files(change_proof, dispatch_result, local_tool_results)
    tool_count = _local_tool_count(local_tool_results)
    tool_names = _tool_names(local_tool_results)
    understanding = _answer_understanding(answer, local_tool_results=local_tool_results)
    contract_intent = str(contract.get("intent") or "").strip().lower()
    proof_required = contract.get("proof_required") if isinstance(contract.get("proof_required"), list) else []
    implementation = intent.goal_requires_change_artifact(envelope)
    diagnosis = contract_intent == "diagnosis" or "cause" in proof_required
    dispatched = isinstance(dispatch_result, dict) and bool(str(dispatch_result.get("reply") or answer).strip())
    status = FINISHED
    reason = "objective_answered"
    missing: list[str] = []

    loop["events"].extend([
        step_event("action", "selected", actions[0].get("action") or actions[0].get("id") if actions else "answer"),
        step_event("observe", "observed", f"{tool_count} local tool result(s)", {"tools": tool_names, "changed_files": changed_files}),
    ])

    if block_codes:
        status = BLOCKED
        reason = "task_contract_blocked"
        missing.extend(str(item) for item in block_codes[:8])
    elif implementation and not changed_files:
        status = INCOMPLETE
        reason = "changed_file_proof_missing"
        missing.append("changed_files")
    elif tool_count and actions and not answer.strip():
        status = INCOMPLETE
        reason = "critique_required_after_action"
        missing.append("post_action_answer")
    elif not answer.strip():
        status = INCOMPLETE
        reason = "answer_missing"
        missing.append("answer")
    elif diagnosis and not dispatched and not _answer_has_user_value(answer, local_tool_results=local_tool_results):
        status = INCOMPLETE
        reason = "diagnosis_answer_missing"
        missing.append("cause")
    elif (
        _repo_object_understanding_required(envelope, local_tool_results=local_tool_results)
        and understanding.get("status") != "sufficient"
    ):
        status = INCOMPLETE
        reason = "typed_understanding_missing"
        missing.append("typed_understanding")

    critique = {
        "status": status,
        "reason": reason,
        "missing": missing,
        "answer_chars": len(answer),
        "local_tools": tool_count,
        "changed_files": [str(item) for item in changed_files[:24]],
        "proof_required": proof_required,
        "typed_understanding": understanding,
    }
    loop["events"].append(step_event("critique", status, reason, critique))
    loop["events"].append(step_event("decide_continue_or_finish", status, "finish" if status == FINISHED else status, {"missing": missing}))
    loop["state"] = "decide_continue_or_finish"
    loop["status"] = status
    loop["critique"] = critique
    return loop


def completion_status(loop: dict[str, Any]) -> str:
    status = str(loop.get("status") or "").strip().lower()
    return status if status in {FINISHED, BLOCKED, INCOMPLETE} else INCOMPLETE
