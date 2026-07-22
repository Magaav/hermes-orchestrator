from __future__ import annotations

from typing import Any

from . import decision_record, operation_ledger, task_policy


SOURCE_CLASSES = frozenset({"source_investigation"})
RUNTIME_CLASSES = frozenset({"runtime_inspection"})
WORKFLOW_CLASSES = frozenset({"implementation", "verification"})
RUNTIME_ACTIONS = frozenset({"runtime.snapshot.get", "runtime.proof.get"})


def _result(step: dict[str, Any]) -> dict[str, Any]:
    value = step.get("result")
    return value if isinstance(value, dict) else {}


def _completed(step: dict[str, Any]) -> bool:
    result = _result(step)
    return step.get("status") == "completed" and result.get("ok") is True


def _positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def _range(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, dict):
        return None
    start = _positive_int(value.get("start_line"))
    end = _positive_int(value.get("end_line"))
    return (start, end) if start and end >= start else None


def _merge(ranges: list[tuple[int, int]]) -> list[list[int]]:
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _covered(ranges: list[list[int]], start: int, end: int) -> bool:
    return any(existing_start <= start and existing_end >= end for existing_start, existing_end in ranges)


def _uncovered(ranges: list[list[int]], desired: list[tuple[int, int]]) -> list[list[int]]:
    gaps: list[list[int]] = []
    for desired_start, desired_end in desired:
        cursor = desired_start
        for covered_start, covered_end in ranges:
            if covered_end < cursor or covered_start > desired_end:
                continue
            if cursor < covered_start:
                gaps.append([cursor, min(desired_end, covered_start - 1)])
            cursor = max(cursor, covered_end + 1)
            if cursor > desired_end:
                break
        if cursor <= desired_end:
            gaps.append([cursor, desired_end])
    return _merge([(start, end) for start, end in gaps])


def _source_focus(state: dict[str, Any]) -> tuple[str, int, list[tuple[int, int]]]:
    owner = ""
    line_count = 0
    suggestions: list[tuple[int, int]] = []
    for step in state.get("steps", []):
        if not isinstance(step, dict) or not _completed(step):
            continue
        focus = _result(step).get("focus")
        if not isinstance(focus, dict) or not focus.get("owner_file"):
            continue
        owner = str(focus["owner_file"])
        line_count = _positive_int(focus.get("line_count"))
        suggestions = [item for value in (focus.get("suggested_ranges") or []) if (item := _range(value))]
    return owner, line_count, suggestions


def evidence_status(state: dict[str, Any]) -> dict[str, Any]:
    """Summarize conclusive source coverage, not merely the presence of a read."""
    owner, line_count, suggested_ranges = _source_focus(state)
    reads: list[dict[str, Any]] = []
    for step in state.get("steps", []):
        if not isinstance(step, dict) or step.get("tool") != "read" or not _completed(step):
            continue
        result = _result(step)
        if not str(result.get("content") or "").strip():
            continue
        reads.append(result)

    if not owner and reads:
        owner = str(reads[-1].get("path") or "")
    owner_reads = [result for result in reads if owner and str(result.get("path") or "") == owner]
    for result in reversed(owner_reads):
        observed_line_count = _positive_int(result.get("line_count"))
        if observed_line_count:
            line_count = observed_line_count
            break

    trusted_ranges = []
    for result in owner_reads:
        current = _range(result)
        if current is not None and result.get("truncated") is not True:
            trusted_ranges.append(current)
    merged = _merge(trusted_ranges)
    desired_ranges = suggested_ranges or ([(1, line_count)] if line_count else [])
    missing_ranges = _uncovered(merged, desired_ranges)
    owner_fully_read = bool(line_count and _covered(merged, 1, line_count))
    focused_ranges_read = bool(
        suggested_ranges
        and all(_covered(merged, start, end) for start, end in suggested_ranges)
    )
    sufficient = owner_fully_read or focused_ranges_read
    if owner_fully_read:
        instruction = "The owning source is fully read. Answer now, unless one precise unresolved question requires different evidence."
        coverage_kind = "owner_file"
    elif focused_ranges_read:
        instruction = "The declared owning-source focus is covered. Answer now, unless one precise unresolved question requires different evidence."
        coverage_kind = "focused_ranges"
    else:
        instruction = "Read only missing_ranges; do not repeat completed read_ranges."
        coverage_kind = "incomplete"
    return {
        "owner_file": owner,
        "line_count": line_count,
        "read_ranges": merged,
        "suggested_ranges": [[start, end] for start, end in suggested_ranges],
        "missing_ranges": missing_ranges,
        "owner_fully_read": owner_fully_read,
        "focused_ranges_read": focused_ranges_read,
        "source_evidence_sufficient": sufficient,
        "coverage_kind": coverage_kind,
        "instruction": instruction,
    }


def _successful_steps(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in state.get("steps", []) if isinstance(step, dict) and _completed(step)]


def _runtime_steps(state: dict[str, Any]) -> list[dict[str, Any]]:
    conclusive: list[dict[str, Any]] = []
    for step in _successful_steps(state):
        if step.get("tool") != "inspect":
            continue
        runtime = _result(step).get("runtime")
        if not isinstance(runtime, dict) or runtime.get("action") not in RUNTIME_ACTIONS:
            continue
        observed = runtime.get("result")
        if isinstance(observed, dict) and observed:
            conclusive.append(step)
    return conclusive


def _missing_source_reads(status: dict[str, Any]) -> list[dict[str, Any]]:
    owner = str(status.get("owner_file") or "")
    if not owner:
        return []
    actions = []
    for start, end in (status.get("missing_ranges") or [])[:2]:
        actions.append({
            "tool": "read",
            "arguments": {"path": owner, "start_line": int(start), "end_line": min(int(end), int(start) + 999)},
        })
    return actions


def _declared_modality(route: dict[str, Any] | None) -> str:
    if not isinstance(route, dict):
        return ""
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    declared = {
        str(value).strip().lower()
        for value in (contract.get("declared_classes") or [contract.get("request_class") or contract.get("objective_kind")])
        if str(value or "").strip()
    }
    if declared & WORKFLOW_CLASSES:
        return "workflow"
    if declared & RUNTIME_CLASSES:
        return "runtime"
    if declared & SOURCE_CLASSES:
        return "source"
    return ""


def verified_noop(state: dict[str, Any], route: dict[str, Any] | None = None) -> bool:
    if not task_policy.llm_autonomous(route or {}) or not task_policy.requires_mutation(route or {}):
        return False
    ledger = state.get("operation_ledger") if isinstance(state.get("operation_ledger"), dict) else {}
    if ledger.get("mutations"):
        return False
    check = ledger.get("check") if isinstance(ledger.get("check"), dict) else {}
    if check.get("rev") != 0 or check.get("ok") is not True:
        return False
    executive = state.get("executive") if isinstance(state.get("executive"), dict) else {}
    decision = executive.get("decision") if isinstance(executive.get("decision"), dict) else {}
    if decision.get("state") not in {"blocked", "rejected"}:
        return False
    if any(
        isinstance(item, dict) and item.get("state") == "open"
        for item in (executive.get("outcomes") or [])
    ):
        return False
    return any(step.get("tool") == "read" and _completed(step) for step in _successful_steps(state))


def assess(state: dict[str, Any], route: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assess whether evidence satisfies the declared modality and coverage."""
    if task_policy.llm_autonomous(route or {}):
        if task_policy.requires_decision(route or {}):
            executive = state.get("executive") if isinstance(state.get("executive"), dict) else {}
            record, missing = decision_record.validate(executive.get("decision"))
            if missing:
                return {
                    "status": "incomplete", "modality": "implementation_planning", "covered": [],
                    "required_gaps": [f"decision.{field}" for field in missing],
                    "next_actions": [{"tool": "checkpoint", "arguments": {"decision": {}}}],
                    "reason": "Planning must end with one complete model-authored operational decision.",
                }
            return {
                "status": "sufficient", "modality": "implementation_planning", "covered": ["decision"],
                "required_gaps": [], "next_actions": [],
                "reason": f"The model recorded a complete {record['state']} operational decision.",
            }
        ledger = state.get("operation_ledger") if isinstance(state.get("operation_ledger"), dict) else {}
        if task_policy.requires_mutation(route or {}) and not ledger.get("mutations") and not verified_noop(state, route):
            return {
                "status": "incomplete", "modality": "llm_autonomous", "covered": [],
                "required_gaps": ["repository mutation"],
                "next_actions": [{"tool": "edit", "arguments": {}}],
                "reason": "Model autonomy owns the workflow, but the declared implementation has no applied mutation yet.",
            }
        return {
            "status": "sufficient", "modality": "llm_autonomous", "covered": [],
            "required_gaps": [], "next_actions": [],
            "reason": "The task contract delegates completion timing and tool choice to the model, including a proof-backed no-op decision when the requested mutation is not justified.",
        }
    successful = _successful_steps(state)
    source = evidence_status(state)
    runtime = _runtime_steps(state)
    modality = _declared_modality(route)
    source_ready = bool(source["source_evidence_sufficient"])
    runtime_ready = bool(runtime)
    if modality == "runtime":
        sufficient = runtime_ready
    elif modality == "source":
        sufficient = source_ready
    elif modality == "workflow":
        sufficient = False
    else:
        sufficient = source_ready or runtime_ready
    if sufficient:
        covered = ["inspect"] if modality == "runtime" or (runtime_ready and not source_ready) else ["read"]
        return {
            "status": "sufficient",
            "modality": modality or ("source" if source_ready else "runtime"),
            "covered": covered,
            "required_gaps": [],
            "next_actions": [],
            "reason": "Task-appropriate bounded primary evidence has conclusive coverage.",
        }

    source_reads = [step for step in successful if step.get("tool") == "read"]
    inspections = [step for step in successful if step.get("tool") == "inspect"]
    if modality == "workflow":
        ledger = state.get("operation_ledger") if isinstance(state.get("operation_ledger"), dict) else {}
        if task_policy.requires_mutation(route or {}):
            mutations = bool(ledger.get("mutations"))
            workflow_gaps = operation_ledger.missing(ledger) if mutations else ["repository mutation"]
        else:
            workflow_gaps = operation_ledger.verification_missing(ledger)
        if not workflow_gaps:
            return {
                "status": "sufficient",
                "modality": "workflow",
                "covered": [step.get("tool") for step in successful],
                "required_gaps": [],
                "next_actions": [],
                "reason": "The declared workflow has current deterministic completion proof.",
            }
        workflow_actions = []
        if any("test" in gap for gap in workflow_gaps):
            workflow_actions.append({"tool": "test", "arguments": {"check_id": "<registered-check-id>"}})
        if any("diff" in gap for gap in workflow_gaps):
            workflow_actions.append({"tool": "diff", "arguments": {}})
        if any("proof" in gap for gap in workflow_gaps):
            workflow_actions.append({"tool": "prove", "arguments": {}})
        return {
            "status": "incomplete",
            "modality": "workflow",
            "covered": [step.get("tool") for step in successful],
            "required_gaps": workflow_gaps,
            "next_actions": workflow_actions,
            "reason": "Evidence gathering does not replace the declared mutation or verification workflow.",
        }
    if modality == "runtime":
        return {
            "status": "incomplete" if inspections else "blocked",
            "modality": "runtime",
            "covered": ["inspect"] if inspections else [],
            "required_gaps": ["conclusive_runtime_evidence"],
            "next_actions": [],
            "reason": "No successful scoped runtime snapshot or proof is available.",
        }

    next_actions = _missing_source_reads(source)
    if modality == "source" or source.get("owner_file") or source_reads:
        gap = "source_coverage" if source_reads else "primary_source_read"
        return {
            "status": "incomplete",
            "modality": "source",
            "covered": [step.get("tool") for step in successful],
            "required_gaps": [gap],
            "next_actions": next_actions,
            "reason": "Owning-source evidence exists but its declared coverage is incomplete." if source_reads else "Search located an owner, but primary source has not been read.",
        }
    if inspections:
        return {
            "status": "incomplete",
            "modality": "runtime",
            "covered": ["inspect"],
            "required_gaps": ["conclusive_runtime_evidence"],
            "next_actions": [],
            "reason": "The inspection result lacks a scoped runtime snapshot or proof.",
        }
    return {
        "status": "blocked",
        "modality": modality,
        "covered": [step.get("tool") for step in successful],
        "required_gaps": ["answer_evidence"],
        "next_actions": [],
        "reason": "No conclusive primary source or runtime evidence is available.",
    }


def ready(state: dict[str, Any], route: dict[str, Any] | None = None) -> bool:
    return assess(state, route)["status"] == "sufficient"
