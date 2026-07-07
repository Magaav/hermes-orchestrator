from __future__ import annotations

import json
import re
from typing import Any

from . import intent
from . import route_contracts


ALLOWED_CAPS = {
    "repo.read",
    "repo.edit",
    "test.run",
    "command.run",
    "runtime.inspect",
    "docs.update",
    "proof.report",
}

EXPLICIT_HERMES_RE = re.compile(
    r"\b(?:use|run|call|ask|dispatch|invoke)\s+(?:bounded\s+|the\s+)?hermes\b"
    r"|\bhermes\b.{0,40}\b(?:use|run|call|dispatch|invoke)\b",
    re.IGNORECASE,
)


def dispatch_caps(action: dict[str, Any]) -> list[str]:
    raw = action.get("caps") or action.get("capabilities") or action.get("CAPS") or []
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",")]
    if not isinstance(raw, list):
        return []
    caps: list[str] = []
    for item in raw[:24]:
        cap = route_contracts.clipped(str(item or "").strip(), 80)
        if cap:
            caps.append(cap)
    return caps


def unknown_caps(action: dict[str, Any], allowed_caps: set[str] = ALLOWED_CAPS) -> list[str]:
    return [cap for cap in dispatch_caps(action) if cap not in allowed_caps]


def escalation_reason(action: dict[str, Any]) -> str:
    return route_contracts.clipped(str(
        action.get("escalation_reason")
        or action.get("escalationReason")
        or action.get("fallback_reason")
        or action.get("reason")
        or ""
    ).strip(), 500)


def action_text(action: dict[str, Any], envelope: dict[str, Any]) -> str:
    values = [
        action.get("objective") or action.get("obj") or envelope.get("objective"),
        action.get("reason") or action.get("escalation_reason") or action.get("escalationReason"),
        action.get("needs") or envelope.get("needs"),
        action.get("scope"),
        action.get("refs") or envelope.get("evidence_refs"),
        action.get("proof") or action.get("proof_requests"),
        action.get("entity") or action.get("node") or action.get("target"),
    ]
    parts: list[str] = []
    for value in values:
        if value in (None, "", [], {}):
            continue
        try:
            parts.append(json.dumps(value, ensure_ascii=True, sort_keys=True))
        except (TypeError, ValueError):
            parts.append(str(value))
    return " ".join(parts)


def is_runtime_entity_dispatch(action: dict[str, Any], envelope: dict[str, Any]) -> bool:
    caps = set(dispatch_caps(action))
    if "repo.edit" in caps and intent.objective_is_implementation_intent(envelope):
        return False
    if "runtime.inspect" in caps:
        return True
    text = action_text(action, envelope).lower()
    return any(token in text for token in ("runtime", "entity", "node", "timeline", "creation event", "created_at"))


def is_harness_subagent_dispatch(action: dict[str, Any]) -> bool:
    role = str(action.get("role") or action.get("subagent_role") or action.get("kind") or "").strip().lower()
    mode = str(action.get("mode") or action.get("dispatch_mode") or "").strip().lower()
    return bool(
        action.get("harness")
        or action.get("is_harness")
        or role in {"harness", "subagent_harness", "bounded_harness"}
        or mode in {"harness", "subagent_harness", "bounded_harness"}
    )


def explicit_hermes_requested(envelope: dict[str, Any]) -> bool:
    if any(bool(envelope.get(key)) for key in ("use_hermes", "allow_hermes", "hermes_explicit", "explicit_hermes")):
        return True
    values: list[Any] = [
        envelope.get("objective"),
        envelope.get("user_objective"),
        envelope.get("constraints"),
        envelope.get("proof_requests"),
    ]
    compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    values.extend([compact_state.get("objective"), compact_state.get("user_request")])
    for value in values:
        try:
            text = json.dumps(value, ensure_ascii=True) if not isinstance(value, str) else value
        except (TypeError, ValueError):
            text = str(value)
        if EXPLICIT_HERMES_RE.search(text or ""):
            return True
    return False

