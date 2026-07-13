from __future__ import annotations

from typing import Any


def evidence_status(state: dict[str, Any]) -> dict[str, Any]:
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


def _successful_steps(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in state.get("steps", []) if step.get("status") == "completed" and isinstance(step.get("result"), dict) and step["result"].get("ok") is True]


def _suggested_reads(state: dict[str, Any]) -> list[dict[str, Any]]:
    status = evidence_status(state); owner = status["owner_file"]
    read_ranges = [tuple(item) for item in status["read_ranges"]]
    for step in reversed(state.get("steps", [])):
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        focus = result.get("focus") if isinstance(result.get("focus"), dict) else {}
        if not owner or focus.get("owner_file") != owner:
            continue
        suggestions = []
        for item in focus.get("suggested_ranges") or []:
            if not isinstance(item, dict): continue
            start, end = int(item.get("start_line") or 1), int(item.get("end_line") or 1)
            if any(existing_start <= start and existing_end >= end for existing_start, existing_end in read_ranges): continue
            suggestions.append({"tool": "read", "arguments": {"path": owner, "start_line": start, "end_line": end}})
        if suggestions: return suggestions[:2]
    return []


def assess(state: dict[str, Any]) -> dict[str, Any]:
    successful = _successful_steps(state)
    source_reads = [step for step in successful if step.get("tool") == "read" and str(step["result"].get("content") or "").strip()]
    inspections = [step for step in successful if step.get("tool") == "inspect"]
    if source_reads or inspections:
        return {"status": "sufficient", "covered": [step.get("tool") for step in source_reads + inspections], "required_gaps": [], "next_actions": [], "reason": "Bounded primary evidence is available for answer synthesis."}
    next_actions = _suggested_reads(state)
    if next_actions:
        return {"status": "incomplete", "covered": [step.get("tool") for step in successful], "required_gaps": ["primary_source_read"], "next_actions": next_actions, "reason": "Search located an owner, but primary source has not been read."}
    return {"status": "blocked", "covered": [step.get("tool") for step in successful], "required_gaps": ["answer_evidence"], "next_actions": [], "reason": "No primary source or runtime evidence is available."}
