from __future__ import annotations

import json
from typing import Any

from . import policy


SYSTEM = """You are Master:frontier V5. Solve the user's objective through one natural tool loop.
Use search to locate source, read to understand exact files, and inspect only for live runtime targets.
Current tool results outrank memory or assumptions. Do not claim runtime or production behavior from source alone.
Return exactly one JSON object: {\"tool\":name,\"arguments\":{...}} or {\"final\":\"useful answer\"}.
Do not emit receipt hashes or internal proof schemas. When sufficient evidence exists, answer the objective directly."""

FINAL_SYSTEM = """You are Master:frontier V5. The required owning source has been fully read.
Answer the user's objective now in useful plain text. Do not call tools. Do not return JSON or internal receipts.
Ground claims in the observed source and distinguish source findings from unverified runtime behavior."""


def _evidence_status(state: dict[str, Any]) -> dict[str, Any]:
    owner = ""; line_count = 0; ranges: list[tuple[int, int]] = []
    for step in state.get("steps", []):
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        focus = result.get("focus") if isinstance(result.get("focus"), dict) else {}
        if focus.get("owner_file"):
            owner = str(focus["owner_file"]); line_count = int(focus.get("line_count") or 0)
        if owner and result.get("path") == owner and result.get("start_line") and result.get("end_line"):
            ranges.append((int(result["start_line"]), int(result["end_line"])))
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1: merged[-1][1] = max(merged[-1][1], end)
        else: merged.append([start, end])
    complete = bool(owner and line_count and merged and merged[0][0] <= 1 and merged[-1][1] >= line_count and all(merged[index][1] + 1 >= merged[index + 1][0] for index in range(len(merged) - 1)))
    return {"owner_file": owner, "line_count": line_count, "read_ranges": merged, "owner_fully_read": complete, "instruction": "The owning source is fully read. Answer now, unless you can name one precise unresolved question requiring different evidence." if complete else "Read the focused owning-source ranges needed to answer."}


def messages(objective: str, route: dict[str, Any], state: dict[str, Any]) -> list[dict[str, str]]:
    evidence_status = _evidence_status(state)
    observations = []
    for step in state.get("steps", [])[-10:]:
        observations.append({key: step.get(key) for key in ("tool", "status", "summary", "result") if step.get(key) not in (None, "")})
    payload = {
        "objective": objective,
        "route": {"id": route.get("route_id"), "root": route.get("workspace_root")},
        "tools": [] if evidence_status["owner_fully_read"] else policy.tool_descriptors(),
        "completed": observations,
        "evidence_status": evidence_status,
        "last_error": state.get("last_error"),
        "rule": "Every decision must add relevant evidence, reduce uncertainty, name an exact blocker, or finish.",
    }
    return [{"role": "system", "content": FINAL_SYSTEM if evidence_status["owner_fully_read"] else SYSTEM}, {"role": "user", "content": json.dumps(payload, ensure_ascii=True, separators=(",", ":"))}]
