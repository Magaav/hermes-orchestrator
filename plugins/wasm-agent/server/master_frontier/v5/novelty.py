"""Generic evidence-novelty admission for the model-led V5 loop."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _observations(state: dict[str, Any], tool: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in (state.get("completed_actions") or {}).values():
        if not isinstance(value, dict) or str(value.get("tool") or "") != tool:
            continue
        observation = value.get("observation")
        if isinstance(observation, dict) and observation.get("ok") is True:
            rows.append(observation)
    return rows


def _canonical_path(path: str, route: dict[str, Any] | None) -> str:
    workspace = str((route or {}).get("workspace_root") or "").strip()
    if not workspace:
        return str(Path(path))
    root = Path(workspace).resolve(strict=False)
    candidate = Path(path)
    resolved = candidate.resolve(strict=False) if candidate.is_absolute() else (root / candidate).resolve(strict=False)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


def _merged_ranges(
    state: dict[str, Any], path: str, route: dict[str, Any] | None,
) -> tuple[list[list[int]], int]:
    ranges: list[tuple[int, int]] = []
    line_count = 0
    for row in _observations(state, "read"):
        if _canonical_path(str(row.get("path") or ""), route) != path:
            continue
        start, end = row.get("start_line"), row.get("end_line")
        if isinstance(start, int) and isinstance(end, int) and start >= 1 and end >= start:
            ranges.append((start, end))
        if isinstance(row.get("line_count"), int):
            line_count = max(line_count, int(row["line_count"]))
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged, line_count


def _uncovered(start: int, end: int, covered: list[list[int]]) -> list[list[int]]:
    result: list[list[int]] = []
    cursor = start
    for prior_start, prior_end in covered:
        if prior_end < cursor:
            continue
        if prior_start > end:
            break
        if prior_start > cursor:
            result.append([cursor, min(end, prior_start - 1)])
        cursor = max(cursor, prior_end + 1)
        if cursor > end:
            break
    if cursor <= end:
        result.append([cursor, end])
    return result


def admit(
    state: dict[str, Any], tool: str, arguments: dict[str, Any],
    route: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reject only actions that can be proven to add no primary evidence."""
    if tool != "read":
        return {"ok": True}
    requested_path = str(arguments.get("path") or "")
    if not requested_path:
        return {"ok": True}
    path = _canonical_path(requested_path, route)
    covered, known_line_count = _merged_ranges(state, path, route)
    if not covered:
        return {"ok": True}
    start = arguments.get("start_line", 1)
    end = arguments.get("end_line", known_line_count or None)
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
        return {"ok": True}
    novel = _uncovered(start, end, covered)
    if novel:
        return {"ok": True, "uncovered": novel[:8]}
    return {
        "ok": False,
        "code": "evidence_already_covered",
        "message": f"Read {requested_path} lines {start}-{end} adds no new evidence; that route-scoped file range is already covered.",
        "covered": covered[:8],
        "next_actions": [
            {"action": "choose_an_uncovered_range_or_different_file"},
            {"action": "edit_test_diff_or_prove_if_understanding_is_sufficient"},
            {"action": "finish_or_name_a_concrete_blocker"},
        ],
    }


def _search_locations(observation: dict[str, Any]) -> set[tuple[str, int]]:
    result: set[tuple[str, int]] = set()
    matches = observation.get("matches") if isinstance(observation.get("matches"), list) else []
    for item in matches:
        if not isinstance(item, dict):
            continue
        path, line = str(item.get("path") or ""), item.get("line")
        if path and isinstance(line, int):
            result.add((path, line))
    return result


def classify_observation(state: dict[str, Any], tool: str, observed: dict[str, Any]) -> dict[str, Any]:
    """Classify successful evidence after execution against durable receipts."""
    if tool != "search" or observed.get("ok") is not True:
        return {"novel": True}
    current = _search_locations(observed)
    if not current:
        return {"novel": True}
    prior: set[tuple[str, int]] = set()
    for row in _observations(state, "search"):
        prior.update(_search_locations(row))
    added = current - prior
    if added or not prior:
        return {"novel": True, "new_locations": len(added or current)}
    return {
        "novel": False,
        "code": "search_evidence_repeated",
        "message": "Search returned no source locations beyond evidence already collected.",
        "next_actions": [
            {"action": "read_an_uncovered_result_or_different_file"},
            {"action": "edit_test_diff_or_prove_if_understanding_is_sufficient"},
            {"action": "finish_or_name_a_concrete_blocker"},
        ],
    }
