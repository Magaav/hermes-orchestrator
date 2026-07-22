from __future__ import annotations

import hashlib
import re
from typing import Any

from .. import budget as route_budget
from . import completion, decision_record, epistemics, executive, learned_patterns, operation_ledger, policy, progress, reliability, task_policy, wire


MAX_EVIDENCE_CONTENT_CHARS = 32_000
MAX_EVIDENCE_BLOCK_CHARS = 16_000


SYSTEM = """You are Master:frontier V5. Solve the user's objective through one natural tool loop.
The user message uses the compact MF5/2 record protocol; native tool schemas remain authoritative.
When an H record is marked parent_spec, it is the grounded specification for the current referential implementation request. Preserve its scope, inspect its named paths first, and implement its actionable findings instead of rediscovering an unrelated task. If the specification contains more independently useful work than one bounded run can safely prove, choose and ship the highest-leverage coherent slice, record the remaining findings as explicit outcomes, and state their disposition in the final answer.
For implementation_planning, do not propose a patch as prose alone: use checkpoint to record one operational decision with candidate, target paths, observable acceptance criterion, blocker when applicable, next action, and confidence. This is operational state, not hidden reasoning.
Read an exact bounded repository path directly when the objective or grounded continuity supplies one. Use search only to locate an unknown path, read to understand exact files, and inspect only for live runtime targets.
Use declared runtime_identity for claims about your active model or harness identity.
Current tool results outrank memory or assumptions. Do not claim runtime or production behavior from source alone.
For source work, use missing_ranges directly, never repeat completed read_ranges, and reserve one advisory call for the final answer.
Use the compact progress record to recognize covered ranges, duplication, workflow stage, and unmet work. Repetition is not progress merely because a tool succeeded.
Use native tool calls for actions; several independent calls may be returned and will execute sequentially. When you decide the objective is complete, return useful plain text.
An implementation objective is complete only after the native edit tool reports an applied repository mutation; describing a proposed patch is not completion.
When useful, maintain optional outcomes in checkpoint. Resolve each as done, dropped, or blocked; do not finish while an actionable outcome remains open.
In autonomous mode, use checkpoint when persisting or revising your goal, situation, plan, hypotheses, open questions, next action, or definition of done will improve continuity.
Do not emit receipt hashes, internal proof schemas, or JSON-wrapped final answers. When sufficient evidence exists, answer the objective directly."""

FINAL_SYSTEM = """You are Master:frontier V5. The declared task now has conclusive bounded evidence.
Answer the user's objective now in useful plain text. Do not call tools. Do not return JSON or internal receipts.
Ground claims in the observed evidence and distinguish source findings from verified runtime observations."""

FORCED_FINAL_SYSTEM = """You are Master:frontier V5. The last requested operation was already completed and its result is included below.
Synthesize the best useful answer now from the accumulated evidence. Do not call tools. Do not return JSON or internal receipts.
State any remaining uncertainty briefly instead of repeating an operation."""

DIRECT_SYSTEM = """You are Master:frontier V5. This task is declared as a self-contained conversation.
Answer the user's objective directly and concisely. Do not call tools, inspect source, or invent external evidence.
Return useful plain text, not JSON or internal receipts."""


def _evidence_status(state: dict[str, Any], route: dict[str, Any] | None = None) -> dict[str, Any]:
    return completion.evidence_status(state)


def completion_only(state: dict[str, Any], route: dict[str, Any] | None = None) -> bool:
    declared_route = route or {}
    if task_policy.llm_autonomous(declared_route):
        return state.get("pending") == "frontier_completion"
    return (
        task_policy.direct_completion(declared_route)
        or completion.ready(state, declared_route)
        or state.get("pending") == "frontier_completion"
    )


def _project_result(value: Any, *, retrying: bool, content_budget: int) -> tuple[Any, int]:
    if not isinstance(value, dict):
        return value, 0
    result = dict(value)
    content = result.get("content")
    if not isinstance(content, str):
        return result, 0
    limit = min(max(0, int(content_budget)), 1_200 if retrying else MAX_EVIDENCE_BLOCK_CHARS)
    if limit <= 0:
        result.pop("content", None)
        result["content_omitted"] = True
        result["content_original_chars"] = len(content)
        return result, 0
    if len(content) > limit:
        head = max(1, (limit * 2) // 3)
        tail = max(1, limit - head - 31)
        label = "retry projection" if retrying else "evidence projection"
        result["content"] = content[:head] + f"\n...[{label} clipped]...\n" + content[-tail:]
        result["content_original_chars"] = len(content)
    return result, min(len(content), limit)


def _budget_projection(route: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    resolved = route_budget.from_envelope(route)
    counters = state.get("loop_counters") if isinstance(state.get("loop_counters"), dict) else {}
    totals = state.get("usage_totals") if isinstance(state.get("usage_totals"), dict) else {}
    usages = totals if int(totals.get("metered_calls") or 0) else state.get("usages") if isinstance(state.get("usages"), list) else []
    elapsed_ms = max(0, int(counters.get("elapsed_ms") or 0))
    task_lease_ms = route_budget.task_lease_ms(route)
    projected: dict[str, Any] = {
        "hard": resolved.get("enforcement") == route_budget.HARD_ENFORCEMENT,
        "provider_call_ms": route_budget.provider_call_ms(route),
        "task_lease_ms": task_lease_ms,
        "task_elapsed_ms": elapsed_ms,
        "task_remaining_ms": max(0, task_lease_ms - elapsed_ms),
    }
    calls_target = resolved.get("api_calls_max")
    if isinstance(calls_target, int):
        calls_used = max(0, int(counters.get("provider_attempts") or 0))
        projected.update({
            "calls_used": calls_used,
            "calls_target": calls_target,
            "calls_remaining": max(0, calls_target - calls_used),
        })
    tokens_target = resolved.get("provider_tokens_max")
    if isinstance(tokens_target, int):
        tokens_used = route_budget.provider_tokens_used(usages)
        projected.update({
            "tokens_used": tokens_used,
            "tokens_target": tokens_target,
            "tokens_remaining": max(0, tokens_target - tokens_used),
        })
    return projected if len(projected) > 1 else {}


def _semantic_steps(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Retain representative evidence identities plus recent failures."""
    steps = [item for item in (state.get("steps") or []) if isinstance(item, dict)]
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    recent_failures: list[dict[str, Any]] = []
    for step in steps:
        tool = str(step.get("tool") or "")
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        if step.get("status") == "completed" and result.get("ok") is True:
            identity = str(result.get("path") or result.get("check_id") or tool)
            if tool == "read" and result.get("path"):
                identity = f"{identity}:{result.get('start_line', '')}-{result.get('end_line', '')}"
            selected[(tool, identity)] = step
        elif step.get("status") in {"failed", "rejected", "redundant", "duplicate"}:
            recent_failures.append(step)
    combined = list(selected.values()) + recent_failures[-4:]
    sequence = lambda item: int(item.get("sequence") or 0)
    return sorted(combined, key=sequence)[-12:]


def payload(objective: str, route: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    evidence_status = _evidence_status(state, route)
    live_assessment = completion.assess(state, route)
    force_completion = completion_only(state, route)
    retrying = reliability.retry_active(state)
    source_planning = (
        task_policy.request_class(route) == "source_investigation"
        and not force_completion
        and not retrying
    )
    observations_reversed = []
    content_budget = MAX_EVIDENCE_CONTENT_CHARS
    semantic_steps = _semantic_steps(state)
    for step in reversed(semantic_steps):
        observation = {key: step.get(key) for key in ("tool", "status", "summary", "result") if step.get(key) not in (None, "")}
        if "result" in observation:
            observation["result"], used = _project_result(
                observation["result"], retrying=retrying,
                content_budget=0 if source_planning else content_budget,
            )
            content_budget -= used
        observations_reversed.append(observation)
    observations = list(reversed(observations_reversed))
    session_turns = route.get("session_context") if isinstance(route.get("session_context"), list) else []
    task_contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    lineage = task_contract.get("lineage") if isinstance(task_contract.get("lineage"), dict) else {}
    continuity = _continuity_capsule(
        session_turns,
        active_parent_run_id=str(lineage.get("parent_run_id") or ""),
    )
    resume = route.get("resume_context") if isinstance(route.get("resume_context"), dict) else {}
    if resume:
        continuity["resume"] = resume
    runtime_entities = []
    if task_policy.request_class(route) == "runtime_inspection":
        runtime_entities = [
            {
                "id": str(item.get("id") or "")[:120],
                "kind": str(item.get("kind") or "runtime-entity")[:80],
            }
            for item in (route.get("entities") if isinstance(route.get("entities"), list) else [])[:8]
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        ]
    return {
        "objective": objective,
        "continuity": continuity,
        "route": {"id": route.get("route_id"), "root": route.get("workspace_root")},
        "runtime_identity": route.get("runtime_identity") if isinstance(route.get("runtime_identity"), dict) else {},
        "runtime_entities": runtime_entities,
        "tools": [] if force_completion else [item["name"] for item in policy.active_descriptors(route, state)],
        "checks": [str(item.get("id") or "") for item in (route.get("checks") or [])[:12] if isinstance(item, dict) and item.get("id")],
        "learned_patterns": learned_patterns.project(route),
        "completed": observations,
        "epistemics": epistemics.project(semantic_steps),
        "evidence_status": evidence_status,
        "budget": _budget_projection(route, state),
        "last_error": state.get("last_error"),
        "completion_assessment": live_assessment,
        "provider_reliability": state.get("provider_reliability"),
        "operations": operation_ledger.project(state.get("operation_ledger") or {}),
        "progress": progress.project(state, route),
        "pending_action": state.get("pending_action"),
        "executive": executive.project(state.get("executive")),
        "rule": "Every decision must add relevant evidence, reduce uncertainty, name an exact blocker, or finish.",
    }


def messages(objective: str, route: dict[str, Any], state: dict[str, Any]) -> list[dict[str, str]]:
    projected = payload(objective, route, state)
    evidence_status = projected["evidence_status"]
    direct = task_policy.direct_completion(route)
    force_completion = completion_only(state, route)
    evidence_ready = completion.ready(state, route)
    system = DIRECT_SYSTEM if direct else FINAL_SYSTEM if evidence_ready else FORCED_FINAL_SYSTEM if force_completion else SYSTEM
    return [{"role": "system", "content": system}, {"role": "user", "content": wire.encode(projected)}]


def _clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    head = max(1, (limit * 2) // 3)
    tail = max(1, limit - head - 15)
    return text[:head] + "\n...[clipped]...\n" + text[-tail:]


def _answer_outline(value: Any) -> list[str]:
    """Retain a prose answer's declared structure without interpreting it."""
    text = str(value or "")
    headings = [
        re.sub(r"\s+", " ", match.group(1)).strip()[:180]
        for match in re.finditer(r"(?m)^#{1,4}\s+(.+?)\s*$", text)
    ]
    return headings[:12]


def _continuity_capsule(
    turns: list[dict[str, Any]],
    *,
    max_chars: int = 5600,
    active_parent_run_id: str = "",
) -> dict[str, Any]:
    """Project recent turns as bounded anchors instead of replaying full answers."""
    projected: list[dict[str, Any]] = []
    remaining = max(800, min(int(max_chars), 12000))
    for item in reversed(turns[-8:]):
        if not isinstance(item, dict) or remaining < 240:
            break
        objective = _clip(item.get("objective"), min(700, max(120, remaining // 4)))
        answer = _clip(item.get("answer"), min(4800, max(120, remaining - len(objective) - 180)))
        turn_id = str(item.get("turn_id") or "")
        anchor = hashlib.sha256(f"{turn_id}\n{objective}\n{answer}".encode("utf-8", errors="ignore")).hexdigest()[:12]
        row = {
            "anchor": anchor,
            "objective": objective,
            "answer": answer,
            "verification": str(item.get("verification_level") or ""),
            "changed": [str(value) for value in (item.get("changed_files") or [])[:12]],
            "outline": _answer_outline(item.get("answer")),
            "decision": decision_record.project(item.get("decision")),
        }
        if active_parent_run_id and str(item.get("run_id") or "") == active_parent_run_id:
            row["relation"] = "parent_spec"
        projected.append(row)
        remaining -= len(objective) + len(answer) + sum(len(value) for value in row["changed"]) + 100
    projected.reverse()
    return {
        "schema": "c1",
        "covers": len(projected),
        "truncated": len(projected) < len(turns),
        "turns": projected,
    }
