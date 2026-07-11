from __future__ import annotations

import json
from typing import Any, Callable

from . import envelope


Completion = Callable[..., dict[str, Any]]
EventRecorder = Callable[[str, str, dict[str, Any]], None]


def usage_components(result: dict[str, Any]) -> list[dict[str, Any]]:
    components = result.get("usage_components") if isinstance(result.get("usage_components"), list) else []
    normalized = [item for item in components if isinstance(item, dict)]
    if normalized:
        return normalized
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else None
    if usage:
        normalized.append(usage)
    return normalized


def repair_structured_action(
    *,
    body: dict[str, Any],
    route_envelope: dict[str, Any],
    receiver: str,
    result: dict[str, Any],
    completion: Completion,
    completion_kwargs: dict[str, Any],
    record_event: EventRecorder,
) -> tuple[Any, dict[str, Any]]:
    parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
    downgraded = envelope.downgraded_conceptual_answer(route_envelope, parsed, result.get("reply", ""))
    if downgraded:
        return downgraded, {**result, "parsed": downgraded, "reply": downgraded.get("answer", "")}
    salvaged = envelope.salvage_conversation_answer(route_envelope, parsed, result.get("reply", ""))
    if salvaged:
        parsed = {**parsed, "answer": salvaged, "decision": "answer", "actions": []}
        return parsed, {**result, "parsed": parsed, "reply": salvaged}
    if not envelope.requires_structured_action(parsed, result.get("reply", "")):
        return parsed, result

    bad_reply = str(result.get("reply") or "")
    record_event(
        "Retrying direct head with strict action-only output contract",
        "structured_action_required",
        {"receiver": receiver},
    )
    previous_usage = usage_components(result)
    result = completion(**completion_kwargs, body=envelope.action_repair_body(body, bad_reply))
    if previous_usage:
        result = {**result, "usage_components": [*previous_usage, *usage_components(result)]}
    parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
    salvaged = envelope.salvage_conversation_answer(route_envelope, parsed, result.get("reply", ""))
    if salvaged:
        parsed = {**parsed, "answer": salvaged, "decision": "answer", "actions": []}
        return parsed, {**result, "parsed": parsed, "reply": salvaged}

    if envelope.requires_structured_action(parsed, result.get("reply", "")) and envelope.requires_repo_object_lookup(parsed, result.get("reply", "")):
        record_event(
            "Synthesizing bounded repo-object lookup action",
            "repo_object_missing_context_lookup",
            {"receiver": receiver},
        )
        parsed = envelope.repo_object_lookup_action(route_envelope, result.get("reply", bad_reply))
        result = {**result, "parsed": parsed, "reply": json.dumps(parsed, ensure_ascii=True)}
    return parsed, result
