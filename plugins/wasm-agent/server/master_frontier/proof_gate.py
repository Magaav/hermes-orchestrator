from __future__ import annotations

import hashlib
import json
import re
from typing import Any


SOURCE_OPERATIONS = frozenset({"search", "read", "symbol", "impact"})
RUNTIME_OPERATIONS = frozenset({"inspect", "node_caps", "node_chat", "resume", "skill"})
MUTATION_OPERATIONS = frozenset({"edit"})
DIFF_OPERATIONS = frozenset({"diff"})
CHECK_OPERATIONS = frozenset({"test"})
PROOF_OPERATIONS = frozenset({"prove"})
PENDING_ANSWER_RE = re.compile(
    r"\b(?:i\s+(?:will|need\s+to|am\s+going\s+to)|let\s+me)\s+(?:inspect|read|search|check|edit|patch|test|fix|investigate)\b",
    re.IGNORECASE,
)


def _task(envelope: dict[str, Any]) -> dict[str, Any]:
    value = envelope.get("task_contract")
    return value if isinstance(value, dict) else {}


def evidence_floor(envelope: dict[str, Any]) -> str:
    task = _task(envelope)
    declared_kinds = {
        str(task.get("intent") or "").strip().lower(),
        str(envelope.get("objective_kind") or "").strip().lower(),
    }
    if "source-investigation" in declared_kinds:
        return "source"
    requested = str(
        envelope.get("evidence_floor")
        or envelope.get("evidenceFloor")
        or task.get("evidence_floor")
        or "route"
    ).strip().lower()
    return requested if requested in {"conceptual", "route", "source", "proof", "runtime"} else "route"


def intent(envelope: dict[str, Any]) -> str:
    return str(_task(envelope).get("intent") or envelope.get("objective_kind") or "").strip().lower()


def mutation_allowed(envelope: dict[str, Any]) -> bool:
    return evidence_floor(envelope) == "proof" or intent(envelope) == "implementation"


def _operation(item: dict[str, Any]) -> str:
    return str(item.get("operation") or "").strip()


def satisfying_operations(history: list[dict[str, Any]]) -> set[str]:
    return {
        operation
        for item in history
        if isinstance(item, dict) and item.get("satisfying") and (operation := _operation(item))
    }


def conclusive_source_evidence(history: list[dict[str, Any]]) -> list[str]:
    accepted = {"found", "not_found_trusted", "ambiguous"}
    return [
        str(item.get("evidence_class") or "")
        for item in history
        if isinstance(item, dict)
        and item.get("conclusive")
        and _operation(item) in SOURCE_OPERATIONS
        and str(item.get("evidence_class") or "") in accepted
    ]


def evaluate(envelope: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    operations = satisfying_operations(history)
    source_evidence = conclusive_source_evidence(history)
    floor = evidence_floor(envelope)
    route = envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else {}
    route_resolved = bool(route.get("route_id") and route.get("workspace_root"))
    if operations & MUTATION_OPERATIONS:
        floor = "proof"

    satisfied = {
        "evidence": route_resolved or bool(operations & (SOURCE_OPERATIONS | RUNTIME_OPERATIONS | PROOF_OPERATIONS)),
        "investigation": bool(source_evidence),
        "runtime": bool(operations & RUNTIME_OPERATIONS),
        "mutation": bool(operations & MUTATION_OPERATIONS),
        "diff": bool(operations & DIFF_OPERATIONS),
        "check": bool(operations & CHECK_OPERATIONS),
        "proof": bool(operations & PROOF_OPERATIONS),
    }
    required = {
        "conceptual": (),
        "route": ("evidence",),
        "source": ("investigation",),
        "runtime": ("runtime",),
        "proof": ("mutation", "diff", "check", "proof"),
    }[floor]
    missing = [name for name in required if not satisfied[name]]
    return {
        "ok": not missing,
        "floor": floor,
        "required": list(required),
        "missing": missing,
        "satisfying_operations": sorted(operations),
        "conclusive_source_evidence": source_evidence,
    }


def evaluate_answer(envelope: dict[str, Any], history: list[dict[str, Any]], answer: str) -> dict[str, Any]:
    gate = evaluate(envelope, history)
    if PENDING_ANSWER_RE.search(str(answer or "")):
        missing = list(gate.get("missing") or [])
        if "completed_answer" not in missing:
            missing.append("completed_answer")
        return {**gate, "ok": False, "missing": missing}
    return gate


def verification_level(gate: dict[str, Any]) -> str:
    floor = str(gate.get("floor") or "")
    if not gate.get("ok"):
        return "incomplete"
    return {
        "conceptual": "model_only",
        "route": "source_or_route_evidence",
        "source": "bounded_source_investigation",
        "runtime": "bounded_runtime_evidence",
        "proof": "local_change_test_diff_proof",
    }.get(floor, "unknown")


def feedback_item(code: str, summary: str, detail: str) -> dict[str, Any]:
    bounded_detail = str(detail or "").strip()[:4000]
    material = json.dumps({"code": code, "summary": summary, "detail": bounded_detail}, sort_keys=True)
    return {
        "line": f"gate:{code}",
        "model_line": summary,
        "detail": bounded_detail,
        "status": "m",
        "operation": "gate",
        "tool": "",
        "satisfying": False,
        "handle": hashlib.sha256(material.encode("utf-8")).hexdigest()[:12],
    }


def completion_feedback(gate: dict[str, Any]) -> dict[str, Any]:
    missing = ",".join(str(item) for item in gate.get("missing") or [])
    return feedback_item(
        "proof_gate_unsatisfied",
        f"completion blocked missing={missing}",
        (
            "The proposed final answer does not satisfy the declared completion contract. "
            f"Use different declared semantic operations to collect: {missing}. "
            "Return a final answer only after those receipts are satisfying."
        ),
    )


def duplicate_feedback(operation: str) -> dict[str, Any]:
    return feedback_item(
        "no_progress",
        f"duplicate blocked operation={operation or 'unknown'}",
        (
            "The identical operation and arguments were already executed and were not re-run. "
            "Choose a different declared operation, change the arguments using existing evidence, or finish with a supported answer."
        ),
    )


def invalid_action_feedback() -> dict[str, Any]:
    return feedback_item(
        "action_invalid",
        "action syntax rejected; repair once",
        (
            "The previous output looked like a function call but did not match one declared semantic operation. "
            "Return exactly one operation line using the published signature, or return a complete plain-text answer. "
            "Empty parentheses are accepted for argumentless operations."
        ),
    )


def unavailable_tool_feedback(operation: str, code: str) -> dict[str, Any]:
    return feedback_item(
        "capability_unavailable",
        f"blocked unavailable operation={operation or 'unknown'} code={code or 'unavailable'}",
        (
            "This capability already returned a deterministic unavailable/stale result and was not called again. "
            "Choose a different declared operation such as files, symbol, or a bounded read from returned route paths."
        ),
    )
