"""Compact model-visible novelty and workflow self-observation."""

from __future__ import annotations

from typing import Any

from . import operation_ledger, task_policy


def _observations(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in (state.get("completed_actions") or {}).values():
        if not isinstance(value, dict):
            continue
        observation = value.get("observation") if isinstance(value.get("observation"), dict) else value
        rows.append({"tool": str(value.get("tool") or observation.get("tool") or ""), **observation})
    return rows


def _read_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_path: dict[str, list[tuple[int, int]]] = {}
    requested_lines = 0
    read_requests = 0
    for row in rows:
        if row.get("tool") != "read" or row.get("ok") is not True:
            continue
        path = str(row.get("path") or "")
        start, end = row.get("start_line"), row.get("end_line")
        if not path or not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            continue
        by_path.setdefault(path, []).append((start, end))
        requested_lines += end - start + 1
        read_requests += 1
    unique_lines = 0
    files: list[dict[str, Any]] = []
    for path, ranges in sorted(by_path.items()):
        merged: list[list[int]] = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        covered = sum(end - start + 1 for start, end in merged)
        unique_lines += covered
        line_count = max(
            [int(row.get("line_count") or 0) for row in rows if row.get("tool") == "read" and row.get("path") == path]
            or [0]
        )
        files.append({
            "path": path, "ranges": merged[:8], "unique_lines": covered, "requests": len(ranges),
            "line_count": line_count,
            "fully_covered": bool(line_count and merged and merged[0][0] == 1 and merged[-1][1] >= line_count),
        })
    overlap = max(0, requested_lines - unique_lines)
    return {
        "read_requests": read_requests,
        "files_read": len(by_path),
        "requested_lines": requested_lines,
        "unique_lines": unique_lines,
        "overlap_lines": overlap,
        "overlap_pct": round((overlap * 100) / requested_lines) if requested_lines else 0,
        "coverage": files[:8],
    }


def owner_fully_read(state: dict[str, Any]) -> bool:
    rows = _observations(state)
    owners = {
        str(focus.get("owner_file") or "")
        for row in rows
        if row.get("tool") == "search" and isinstance((focus := row.get("focus")), dict)
        and str(focus.get("owner_file") or "")
    }
    coverage = _read_coverage(rows)["coverage"]
    return any(item.get("fully_covered") is True and item.get("path") in owners for item in coverage)


def project(state: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    rows = _observations(state)
    coverage = _read_coverage(rows)
    counters = state.get("loop_counters") if isinstance(state.get("loop_counters"), dict) else {}
    ledger = operation_ledger.project(state.get("operation_ledger") or {})
    if not rows and not any(int(counters.get(key) or 0) for key in ("provider_attempts", "tool_calls", "duplicate_actions")) and not int(ledger.get("mutations") or 0):
        return {}
    task = task_policy.request_class(route) or "unspecified"
    mutations = int(ledger.get("mutations") or 0)
    stages: list[dict[str, Any]] = []
    if task_policy.requires_mutation(route):
        gaps = set(ledger.get("gaps") or [])
        stages = [
            {"stage": "understand", "done": bool(coverage["unique_lines"])},
            {"stage": "edit", "done": mutations > 0},
            {"stage": "test", "done": mutations > 0 and "test" not in gaps},
            {"stage": "diff", "done": mutations > 0 and "diff" not in gaps},
            {"stage": "prove", "done": mutations > 0 and "prove" not in gaps},
        ]
    duplicate_actions = max(0, int(counters.get("duplicate_actions") or 0))
    choices = ["choose_next_action", "name_concrete_blocker", "finish_when_objective_satisfied"]
    if task_policy.requires_mutation(route) and mutations == 0 and coverage["unique_lines"]:
        choices.insert(0, "edit_or_explain_why_no_edit_is_correct")
    return {
        "task": task,
        "provider_decisions": max(0, int(counters.get("provider_attempts") or 0)),
        "tool_calls": max(0, int(counters.get("tool_calls") or 0)),
        "duplicate_actions": duplicate_actions,
        **coverage,
        "stages": stages,
        "choices": choices,
        "advisory": True,
    }
