from __future__ import annotations

import json
from typing import Any

from . import completion, policy, task_policy


SYSTEM = """You are Master:frontier V5. Solve the user's objective through one natural tool loop.
Use search to locate source, read to understand exact files, and inspect only for live runtime targets.
Use declared runtime_identity for claims about your active model or harness identity.
Current tool results outrank memory or assumptions. Do not claim runtime or production behavior from source alone.
Return exactly one JSON object: {\"tool\":name,\"arguments\":{...}} or {\"final\":\"useful answer\"}.
Do not emit receipt hashes or internal proof schemas. When sufficient evidence exists, answer the objective directly."""

FINAL_SYSTEM = """You are Master:frontier V5. The required owning source has been fully read.
Answer the user's objective now in useful plain text. Do not call tools. Do not return JSON or internal receipts.
Ground claims in the observed source and distinguish source findings from unverified runtime behavior."""

FORCED_FINAL_SYSTEM = """You are Master:frontier V5. The last requested operation was already completed and its result is included below.
Synthesize the best useful answer now from the accumulated evidence. Do not call tools. Do not return JSON or internal receipts.
State any remaining uncertainty briefly instead of repeating an operation."""

DIRECT_SYSTEM = """You are Master:frontier V5. This task is declared as a self-contained conversation.
Answer the user's objective directly and concisely. Do not call tools, inspect source, or invent external evidence.
Return useful plain text, not JSON or internal receipts."""


def _evidence_status(state: dict[str, Any]) -> dict[str, Any]:
    return completion.evidence_status(state)


def completion_only(state: dict[str, Any], route: dict[str, Any] | None = None) -> bool:
    return task_policy.direct_completion(route or {}) or _evidence_status(state)["owner_fully_read"] or state.get("pending") == "frontier_completion"


def messages(objective: str, route: dict[str, Any], state: dict[str, Any]) -> list[dict[str, str]]:
    evidence_status = _evidence_status(state)
    direct = task_policy.direct_completion(route)
    force_completion = completion_only(state, route)
    observations = []
    for step in state.get("steps", [])[-10:]:
        observations.append({key: step.get(key) for key in ("tool", "status", "summary", "result") if step.get(key) not in (None, "")})
    payload = {
        "objective": objective,
        "route": {"id": route.get("route_id"), "root": route.get("workspace_root")},
        "runtime_identity": route.get("runtime_identity") if isinstance(route.get("runtime_identity"), dict) else {},
        "tools": [] if force_completion else policy.tool_descriptors(),
        "completed": observations,
        "evidence_status": evidence_status,
        "last_error": state.get("last_error"),
        "completion_assessment": state.get("completion_assessment"),
        "rule": "Every decision must add relevant evidence, reduce uncertainty, name an exact blocker, or finish.",
    }
    system = DIRECT_SYSTEM if direct else FINAL_SYSTEM if evidence_status["owner_fully_read"] else FORCED_FINAL_SYSTEM if force_completion else SYSTEM
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=True, separators=(",", ":"))}]
