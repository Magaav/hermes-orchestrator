"""Resolve bounded action authority for grounded conversational follow-ups."""
from __future__ import annotations

import re
from typing import Any


_ACTION = r"(?:apply|build|change|edit|fix|implement|patch|refactor|remove|repair|ship|update|wire)\w*"
_REFERENT = (
    r"(?:it|that|this|them|those|these|all|everything|them\s+all|"
    r"(?:the\s+)?(?:bugs?|changes?|code|defects?|files?|fixes?|implementation|issues?|patches?|problems?))"
)
_ACTION_REQUEST = re.compile(
    rf"^(?:please\s+)?(?:"
    rf"(?:(?:can|could|will|would)\s+you\s+(?:please\s+)?)?{_ACTION}\s+{_REFERENT}"
    rf"|go\s+ahead\s+and\s+{_ACTION}\s+{_REFERENT}"
    rf"|do\s+(?:it|that|them|those|all)"
    rf")(?:\s+please)?[.!?]*$",
    re.IGNORECASE,
)
_GROUNDED_LEVELS = frozenset({"source", "runtime", "behavioral", "proof"})
_CONVERSATION_CLASSES = frozenset({"conversation", "general_conversation"})


def _clean(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _grounded_parent(turns: list[dict[str, Any]], route_id: str) -> dict[str, Any] | None:
    """Return only the immediate completed parent on the same owned route."""
    if not turns or not route_id:
        return None
    turn = turns[-1]
    status = _clean(turn.get("status"))
    if status and status != "completed":
        return None
    if str(turn.get("route_id") or "").strip() != route_id:
        return None
    if _clean(turn.get("verification_level")) not in _GROUNDED_LEVELS:
        return None
    return turn


def project(
    contract: dict[str, Any] | None,
    *,
    objective: str,
    session_context: list[dict[str, Any]] | None,
    route_caps: list[str] | None,
    route_id: str,
    continuation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Promote only a grounded, same-session action request to implementation.

    Client conversation labels remain authoritative for self-contained chat.
    A promotion requires three independent facts: a completed source/runtime
    parent in the user-scoped session ledger, a current generic action request,
    and route-owned edit authority.  Prior prose alone never grants mutation.
    """
    result = dict(contract) if isinstance(contract, dict) else {}
    declared_class = _clean(result.get("request_class") or result.get("objective_kind"))
    turns = [item for item in (session_context or []) if isinstance(item, dict)]
    parent = _grounded_parent(turns, str(route_id or "").strip())
    caps = {_clean(item) for item in (route_caps or [])}
    continuation = continuation_context if isinstance(continuation_context, dict) else {}
    bound_continuation = bool(
        continuation.get("requested") is True
        and parent is not None
        and str(continuation.get("previous_run_id") or "").strip() == str(parent.get("run_id") or "").strip()
    )
    if (
        declared_class not in _CONVERSATION_CLASSES
        or parent is None
        or "repo.edit" not in caps
        or not (bound_continuation or _ACTION_REQUEST.search(str(objective or "").strip()))
    ):
        return result

    declared = [
        _clean(item)
        for item in (result.get("declared_classes") or [])
        if _clean(item)
    ]
    if "implementation" not in declared:
        declared.append("implementation")
    result.update({
        "intent": "implementation",
        "objective_kind": "implementation",
        "request_class": "implementation",
        "evidence_floor": "proof",
        "route_intent": "implementation",
        "declared_classes": declared,
        "completion_mode": "tool_loop",
        "proof_policy": "grounded_change",
        "execution_profile": "implementation",
        "authority_source": "grounded_task_lineage",
        "context_profile": "natural_tool_loop",
        "lineage": {
            "kind": "bound_continuation" if bound_continuation else "grounded_followup_action",
            "parent_run_id": str(parent.get("run_id") or "")[:160],
            "parent_turn_id": str(parent.get("turn_id") or "")[:160],
            "parent_verification": _clean(parent.get("verification_level")),
        },
    })
    return result
