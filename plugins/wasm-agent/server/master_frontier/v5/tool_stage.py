"""Derive currently useful tools from deterministic workflow receipts."""

from __future__ import annotations

from typing import Any

from . import progress, task_policy


def post_mutation_verification_calls(
    route: dict[str, Any],
    ledger: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return the deterministic verification conveyor for one owned check."""
    root = str(route.get("workspace_root") or "").strip().rstrip("/")

    def canonical(value: Any) -> str:
        path = str(value or "").strip().replace("\\", "/")
        if root and path.startswith(root + "/"):
            path = path[len(root) + 1:]
        while path.startswith("./"):
            path = path[2:]
        return path.lstrip("/")

    changed = {
        canonical(path)
        for path in (ledger.get("changed_files") or [])
        if canonical(path)
    }
    if not changed:
        return []
    matches: list[str] = []
    declared_checks: list[str] = []
    for check in (route.get("checks") or [])[:24]:
        if not isinstance(check, dict):
            continue
        evidence = {
            canonical(path)
            for path in (check.get("evidence_paths") or [])[:12]
            if canonical(path)
        }
        check_id = str(check.get("id") or check.get("check_id") or "").strip()
        if check_id:
            declared_checks.append(check_id)
        if check_id and changed.intersection(evidence):
            matches.append(check_id)
    if not matches and len(set(declared_checks)) == 1:
        matches = declared_checks
    if len(set(matches)) != 1:
        return []
    return [
        {"name": "test", "arguments": {"check_id": matches[0]}},
        {"name": "diff", "arguments": {}},
        {"name": "prove", "arguments": {}},
    ]


def _successful_step(state: dict[str, Any], tool: str) -> bool:
    if any(
        isinstance(item, dict)
        and item.get("tool") == tool
        and item.get("status") == "completed"
        and isinstance(item.get("result"), dict)
        and item["result"].get("ok") is True
        for item in (state.get("steps") or [])
    ):
        return True
    for value in (state.get("completed_actions") or {}).values():
        if not isinstance(value, dict) or value.get("tool") != tool:
            continue
        observation = value.get("observation") if isinstance(value.get("observation"), dict) else value
        if observation.get("ok") is True:
            return True
    return False


def _open_requirement(state: dict[str, Any], tool: str) -> bool:
    executive = state.get("executive") if isinstance(state.get("executive"), dict) else {}
    return any(
        isinstance(item, dict)
        and item.get("state") == "open"
        and item.get("requires") == tool
        for item in (executive.get("outcomes") or [])
    )


def _consecutive_completed(state: dict[str, Any], tool: str) -> int:
    count = 0
    for item in reversed(state.get("steps") or []):
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "system":
            continue
        if item.get("tool") == tool and item.get("status") == "completed":
            count += 1
            continue
        break
    return count


def owner_reads_after_latest_mutation(
    state: dict[str, Any], paths: set[str], changed_paths: set[str] | None = None,
) -> set[str]:
    """Return complete required-owner reads that follow the latest mutation."""
    observed: set[str] = set()
    for item in reversed(state.get("steps") or []):
        if not isinstance(item, dict) or item.get("status") != "completed":
            continue
        if item.get("tool") == "edit":
            break
        if item.get("tool") != "read":
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        path = str(result.get("path") or "").strip()
        if (
            result.get("ok") is True
            and path in paths
            and int(result.get("line_count") or 0) > 0
            and int(result.get("end_line") or 0) >= int(result.get("line_count") or 0)
        ):
            content = str(result.get("content") or "")
            linked = not changed_paths or any(
                changed in content or changed.rsplit("/", 1)[-1] in content
                for changed in changed_paths
            )
            if linked:
                observed.add(path)
    return observed


def existing_target_repair_paths(state: dict[str, Any]) -> set[str]:
    """Keep a preimage collision scoped through its exact confirming read."""
    reads: set[str] = set()
    for item in reversed(state.get("steps") or []):
        if not isinstance(item, dict):
            continue
        if item.get("tool") == "edit" and item.get("status") == "completed":
            break
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        if item.get("tool") == "read" and item.get("status") == "completed" and result.get("ok") is True:
            reads.add(str(result.get("path") or "").strip())
            continue
        if item.get("tool") == "edit" and result.get("code") == "patch_preimage_exists":
            summary = str(result.get("summary") or item.get("summary") or "").strip()
            return {path for path in reads if path and summary.endswith(f": {path}")}
    return set()


def unresolved_focus_owner_paths(state: dict[str, Any]) -> set[str]:
    """Return discovered owner paths that still lack one complete read."""
    reads: set[str] = set()
    for item in state.get("steps") or []:
        if not isinstance(item, dict) or item.get("status") != "completed":
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        if (
            item.get("tool") == "read" and result.get("ok") is True
            and int(result.get("line_count") or 0) > 0
            and int(result.get("end_line") or 0) >= int(result.get("line_count") or 0)
        ):
            reads.add(str(result.get("path") or "").strip())
    for item in reversed(state.get("steps") or []):
        if not isinstance(item, dict) or item.get("tool") != "search" or item.get("status") != "completed":
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        focus = result.get("focus") if isinstance(result.get("focus"), dict) else {}
        owner = str(focus.get("owner_file") or "").strip()
        return {owner} if owner and owner not in reads else set()
    return set()


def _search_sufficient(state: dict[str, Any]) -> bool:
    return (
        _successful_step(state, "search") or _successful_step(state, "read")
    ) and not _open_requirement(state, "search")


def _read_sufficient(state: dict[str, Any]) -> bool:
    if progress.owner_fully_read(state):
        return True
    if any(
        isinstance(item, dict)
        and item.get("tool") == "search"
        and isinstance((item.get("result") or {}).get("focus"), dict)
        and str((item.get("result") or {})["focus"].get("owner_file") or "").strip()
        for item in (state.get("steps") or [])
    ):
        return False
    if not _open_requirement(state, "read") and any(
        isinstance(item, dict)
        and item.get("tool") == "read"
        and item.get("status") == "completed"
        and isinstance(item.get("result"), dict)
        and item["result"].get("ok") is True
        and int(item["result"].get("line_count") or 0) > 0
        and int(item["result"].get("end_line") or 0) >= int(item["result"].get("line_count") or 0)
        for item in (state.get("steps") or [])
    ):
        return True
    ledger = state.get("operation_ledger") if isinstance(state.get("operation_ledger"), dict) else {}
    revision = int(ledger.get("revision") or 0)
    check = ledger.get("check") if isinstance(ledger.get("check"), dict) else {}
    executive = state.get("executive") if isinstance(state.get("executive"), dict) else {}
    decision = executive.get("decision") if isinstance(executive.get("decision"), dict) else {}
    return (
        revision == 0
        and check.get("rev") == 0
        and check.get("ok") is True
        and decision.get("state") in {"selected", "blocked", "rejected", "overscoped"}
        and not _open_requirement(state, "read")
    )


def missing_declared_evidence(route: dict[str, Any], state: dict[str, Any]) -> list[str]:
    declared = {
        str(path).strip()
        for check in (route.get("checks") or [])[:24]
        if isinstance(check, dict)
        for path in (check.get("evidence_paths") or [])[:12]
        if str(path).strip()
    }
    if not declared:
        return [] if _read_sufficient(state) else ["owner:uncovered"]
    reads = [
        item["result"]
        for item in (state.get("steps") or [])
        if isinstance(item, dict)
        and item.get("tool") == "read"
        and item.get("status") == "completed"
        and isinstance(item.get("result"), dict)
        and item["result"].get("ok") is True
    ]
    missing: list[str] = []
    for path in sorted(declared):
        matching = [item for item in reads if str(item.get("path") or "").strip() == path]
        line_count = max((int(item.get("line_count") or 0) for item in matching), default=0)
        if line_count <= 0:
            missing.append(f"{path}:1-end")
            continue
        ranges = sorted(
            (max(1, int(item.get("start_line") or 1)), int(item.get("end_line") or 0))
            for item in matching
        )
        covered_to = 0
        for start, end in ranges:
            if start > covered_to + 1:
                break
            covered_to = max(covered_to, end)
        if covered_to < line_count:
            missing.append(f"{path}:{covered_to + 1}-{line_count}")
    return missing


def _declared_evidence_read(route: dict[str, Any], state: dict[str, Any]) -> bool:
    return not missing_declared_evidence(route, state)


def active_names(route: dict[str, Any], state: dict[str, Any], names: list[str]) -> list[str]:
    if task_policy.requires_decision(route):
        if state.get("decision_finalization") is True:
            return [name for name in names if name == "checkpoint"]
        return [name for name in names if name in {"checkpoint", "search", "read", "inspect"}]
    request_class = task_policy.request_class(route)
    resolved_entity = route.get("resolved_entity") if isinstance(route.get("resolved_entity"), dict) else {}
    if (
        request_class not in {"implementation", "implementation_planning", "verification"}
        and str(resolved_entity.get("kind") or "").endswith("session-memory")
    ):
        return [name for name in names if name == "memory"]
    if request_class not in {"verification", "implementation"}:
        return names
    active = list(names)
    if request_class == "implementation":
        # Execution continuity already persists the objective, tool receipts,
        # mutation ledger, and proof state. An executive-only checkpoint adds a
        # paid lifecycle turn without advancing an implementation.
        active = [name for name in active if name != "checkpoint"]
    steps = [item for item in (state.get("steps") or []) if isinstance(item, dict)]
    counters = state.get("loop_counters") if isinstance(state.get("loop_counters"), dict) else {}
    discovery_stalled = (
        task_policy.llm_autonomous(route)
        and request_class == "implementation"
        and _successful_step(state, "read")
        and int(counters.get("no_progress") or 0) >= 3
        and _declared_evidence_read(route, state)
    )
    if discovery_stalled:
        active = [name for name in active if name not in {"search", "read"}]
    if task_policy.llm_autonomous(route) and _search_sufficient(state):
        active = [name for name in active if name != "search"]
    if (
        task_policy.llm_autonomous(route) and _read_sufficient(state)
    ) or (
        not task_policy.llm_autonomous(route)
        and any(item.get("tool") == "read" and item.get("status") == "completed" for item in steps)
    ):
        active = [name for name in active if name != "read"]
        if not task_policy.llm_autonomous(route):
            active = [name for name in active if name != "search"]
    ledger = state.get("operation_ledger") if isinstance(state.get("operation_ledger"), dict) else {}
    revision = int(ledger.get("revision") or 0)
    required_owners = {
        str(path).strip() for path in (route.get("required_owner_paths") or []) if str(path).strip()
    }
    changed_paths = {str(path).strip() for path in (ledger.get("changed_files") or []) if str(path).strip()}
    proven_owners = owner_reads_after_latest_mutation(state, required_owners, changed_paths)
    missing_required_owner = bool(required_owners - changed_paths - proven_owners)
    if (
        request_class == "implementation"
        and task_policy.llm_autonomous(route)
        and task_policy.requires_mutation(route)
        and revision == 0
    ):
        if _declared_evidence_read(route, state):
            active = [name for name in active if name in {"checkpoint", "edit"}]
        else:
            active = [
                name for name in active
                if name not in {"edit", "test", "diff", "prove"}
            ]
    if request_class == "implementation" and revision > 0:
        active = [name for name in active if name not in {"search", "read"}]
    check = ledger.get("check") if isinstance(ledger.get("check"), dict) else {}
    current_error = state.get("last_error") if isinstance(state.get("last_error"), dict) else {}
    if check.get("rev") == revision and check.get("ok") is False:
        active = [name for name in names if name == "edit"]
    if (
        request_class == "implementation"
        and revision > 0
        and not missing_required_owner
        and not (check.get("rev") == revision and check.get("ok") is False)
        and current_error.get("code") != "patch_precondition_required"
    ):
        active = [name for name in active if name != "edit"]
    if check.get("rev") == revision and check.get("ok") is True:
        active = [name for name in active if name != "test"]
        if revision > 0 and not missing_required_owner:
            active = [name for name in active if name != "edit"]
    diff = ledger.get("diff") if isinstance(ledger.get("diff"), dict) else {}
    if diff.get("rev") == revision:
        active = [name for name in active if name != "diff"]
    proof = ledger.get("proof") if isinstance(ledger.get("proof"), dict) else {}
    if proof.get("rev") == revision and proof.get("ok") is True:
        active = [name for name in active if name != "prove"]
    last_error = state.get("last_error") if isinstance(state.get("last_error"), dict) else {}
    if (
        request_class == "implementation"
        and task_policy.llm_autonomous(route)
        and revision == 0
        and last_error.get("tool") == "edit"
    ):
        active = [name for name in active if name != "checkpoint"]
    if last_error.get("code") in {"patch_precondition_required", "patch_preimage_exists"} and "read" in names and "read" not in active:
        active.append("read")
        active.sort(key=names.index)
    if last_error.get("code") == "patch_preimage_exists":
        active = [name for name in active if name == "read"]
    if (
        request_class == "implementation"
        and task_policy.llm_autonomous(route)
        and revision > 0
        and missing_required_owner
        and not (check.get("rev") == revision and check.get("ok") is False)
    ):
        active = [name for name in names if name == "read"]
    return active
