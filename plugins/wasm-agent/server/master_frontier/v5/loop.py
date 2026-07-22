from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .. import budget as route_budget
from . import completion, context, executive, novelty, operation_ledger, policy, reliability, task_policy, trajectory, usage as usage_accounting
from .errors import V5Error


@dataclass
class Outcome:
    answer: str
    trajectory: dict[str, Any]
    calls: int
    attempts: int
    tools: list[dict[str, Any]]
    usages: list[dict[str, Any]]
    usage_totals: dict[str, int]


def bind_observed_preimages(arguments: dict[str, Any], state: dict[str, Any], route: dict[str, Any] | None = None) -> dict[str, Any]:
    operations = arguments.get("operations") if isinstance(arguments.get("operations"), list) else None
    if operations is None:
        return arguments
    root_value = str((route or {}).get("workspace_root") or "").strip()
    root = Path(root_value).resolve() if root_value else None

    def canonical(value: Any) -> str:
        raw = Path(str(value or ""))
        if not str(value or "").strip():
            return ""
        if raw.is_absolute() and root is not None:
            try:
                return raw.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                return raw.as_posix()
        relative = raw.as_posix().lstrip("./")
        if root is not None:
            spelled_root = root.as_posix().lstrip("/").rstrip("/")
            if relative == spelled_root:
                return ""
            if relative.startswith(spelled_root + "/"):
                return relative[len(spelled_root) + 1:]
        return relative

    observed: dict[str, str] = {}
    for step in reversed(state.get("steps") or []):
        if not isinstance(step, dict):
            continue
        if step.get("tool") == "edit" and step.get("status") == "completed":
            break
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        digest = str(result.get("sha256") or "")
        path = canonical(result.get("path"))
        if step.get("tool") == "read" and step.get("status") == "completed" and len(digest) == 64 and path:
            observed.setdefault(path, digest)
    bound = []
    for item in operations:
        operation = dict(item) if isinstance(item, dict) else item
        if isinstance(operation, dict):
            operation["path"] = canonical(operation.get("path"))
            if str(operation.get("op") or "").strip().lower() == "move":
                destination_key = "destination" if "destination" in operation else "to"
                if operation.get(destination_key):
                    operation[destination_key] = canonical(operation.get(destination_key))
            op = str(operation.get("op") or "replace")
            if op == "create":
                operation.setdefault("expected_absent", True)
            else:
                path = canonical(operation.get("path"))
                if not operation.get("expected_sha256") and path in observed:
                    operation["expected_sha256"] = observed[path]
        bound.append(operation)
    return {**arguments, "operations": bound}


def normalize(result: dict[str, Any]) -> dict[str, Any]:
    calls = result.get("tool_calls") if isinstance(result.get("tool_calls"), list) else []
    if calls and isinstance(calls[0], dict):
        call = calls[0]
        name = str(call.get("name") or "")
        arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
        if name and policy.allowed(name):
            remaining = [
                {"id": str(item.get("id") or ""), "name": str(item.get("name") or ""),
                 "arguments": item.get("arguments") if isinstance(item.get("arguments"), dict) else {}}
                for item in calls[1:] if isinstance(item, dict) and policy.allowed(str(item.get("name") or ""))
            ]
            decision = {"kind": "tool", "tool": name, "arguments": arguments}
            if remaining:
                decision["remaining_tool_calls"] = remaining
            return decision
    value = result.get("parsed") if isinstance(result.get("parsed"), dict) else None
    if value is None:
        text = str(result.get("reply") or "").strip()
        if text.startswith("```json") and text.endswith("```"):
            text = text[7:-3].strip()
        try: value = json.loads(text)
        except (TypeError, json.JSONDecodeError): value = None
        if value is None and text and not text.startswith(("{", "[", "```")):
            return {"kind": "final", "answer": text}
    if not isinstance(value, dict): return {"kind": "invalid", "code": "model_output_invalid"}
    if isinstance(value.get("final"), str) and value["final"].strip(): return {"kind": "final", "answer": value["final"].strip()}
    for key in ("answer", "response", "content"):
        if isinstance(value.get(key), str) and value[key].strip(): return {"kind": "final", "answer": value[key].strip()}
    name = str(value.get("tool") or "")
    arguments = value.get("arguments") if isinstance(value.get("arguments"), dict) else {
        key: item for key, item in value.items() if key not in {"tool", "final"}
    }
    if name and policy.allowed(name): return {"kind": "tool", "tool": name, "arguments": arguments}
    return {"kind": "invalid", "code": "model_output_invalid"}


def run(
    objective: str,
    route: dict[str, Any],
    state: dict[str, Any],
    *,
    complete: Callable[[list[dict[str, str]], int], dict[str, Any]],
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    persist: Callable[[dict[str, Any], str], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    verify_worktree: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Outcome:
    counters = trajectory.normalize_counters(state.get("loop_counters"))
    budget = route_budget.from_envelope(route)
    if route_budget.hard_enforced(route) and route_budget.hard_input_reservation(route) is None:
        message = "Hard provider-token enforcement requires a positive route-owned per-call input-token reservation."
        checkpoint = trajectory.checkpoint(state, "provider_input_budget_unbounded", message)
        raise V5Error("provider_input_budget_unbounded", message, checkpoint=checkpoint)
    provider_target: int | None = None
    try:
        if budget.get("api_calls_max") is not None:
            provider_target = max(0, int(budget["api_calls_max"]))
    except (TypeError, ValueError):
        provider_target = 0
    provider_limit: int | None = None
    if route_budget.hard_enforced(route):
        provider_limit = provider_target or 0
    decision_stagnation_limit = (
        provider_target + 2
        if provider_target and not route_budget.hard_enforced(route)
        and task_policy.requires_decision(route)
        else None
    )
    task_lease_ms = route_budget.task_lease_ms(route)
    started = monotonic()
    base_elapsed_ms = int(counters.get("elapsed_ms") or 0)
    state["loop_counters"] = counters
    state["operation_ledger"] = operation_ledger.normalize(
        state.get("operation_ledger"), route_id=str(route.get("route_id") or ""),
    )
    tools = [trajectory.receipt(item) for item in trajectory.prior_tool_results(state)]
    usages = [item for item in state.get("usages", []) if isinstance(item, dict)][-16:]
    usage_totals = usage_accounting.normalize(state.get("usage_totals"))
    if not usage_totals["metered_calls"] and usages:
        for item in usages:
            usage_totals = usage_accounting.record(usage_totals, item)

    def save(reason: str) -> None:
        counters["elapsed_ms"] = base_elapsed_ms + max(0, int((monotonic() - started) * 1000))
        state["loop_counters"] = counters
        state["usages"] = usages[-16:]
        state["usage_totals"] = usage_totals
        if persist is not None:
            persist(state, reason)

    while True:
        if cancelled is not None and cancelled():
            message = "The agent run was cancelled before its next operation."
            checkpoint = trajectory.checkpoint(state, "agent_run_cancelled", message)
            save("agent_run_cancelled")
            raise V5Error("agent_run_cancelled", message, checkpoint=checkpoint)
        elapsed_ms = base_elapsed_ms + max(0, int((monotonic() - started) * 1000))
        if elapsed_ms >= task_lease_ms and not context.completion_only(state, route):
            message = f"V5 reached its durable {task_lease_ms}ms task lease before proof was sufficient."
            checkpoint = trajectory.checkpoint(state, "task_lease_exhausted", message)
            save("task_lease_exhausted")
            raise V5Error("task_lease_exhausted", message, checkpoint=checkpoint)
        unresolved_action = state.get("pending_action") if isinstance(state.get("pending_action"), dict) else {}
        if unresolved_action.get("status") == "started":
            name = str(unresolved_action.get("tool") or "operation")
            if name in {"search", "read", "inspect", "diff", "prove"}:
                state["pending_action"] = None
                state["last_error"] = {
                    "code": "idempotent_action_interrupted",
                    "message": f"The prior {name} has no durable receipt; it may be safely requested again.",
                }
                trajectory.append(state, {
                    "kind": "system", "tool": name, "status": "retryable",
                    "summary": "Interrupted idempotent action had no durable receipt and was released for retry.",
                })
                save("idempotent_action_released")
                continue
            message = f"The prior {name} outcome is unknown after interruption; inspect its server-side proof before continuing."
            checkpoint = trajectory.checkpoint(state, "action_outcome_unknown", message)
            save("unknown_action_requires_reconciliation")
            raise V5Error("action_outcome_unknown", message, checkpoint=checkpoint)
        has_queued_calls = bool(state.get("queued_tool_calls"))
        if not has_queued_calls and provider_limit is not None and counters["provider_attempts"] >= provider_limit:
            message = f"V5 reached its routed {provider_limit}-decision continuity budget."
            code = "provider_call_budget_exhausted"
            checkpoint = trajectory.checkpoint(state, code, message)
            save(code)
            raise V5Error(code, message, checkpoint=checkpoint)
        if not has_queued_calls and decision_stagnation_limit and not completion.ready(state, route):
            if counters["provider_attempts"] >= decision_stagnation_limit:
                message = "Planning exhausted its bounded decision-finalization window without a complete operational decision."
                checkpoint = trajectory.checkpoint(state, "decision_planning_stalled", message)
                save("decision_planning_stalled")
                raise V5Error("decision_planning_stalled", message, checkpoint=checkpoint)
            if counters["provider_attempts"] == provider_target:
                state["decision_finalization"] = True
                state["last_error"] = {
                    "code": "decision_finalization_required",
                    "message": "The advisory investigation target is complete. Use checkpoint now to record selected, blocked, rejected, or overscoped operational decision fields; do not gather more evidence.",
                }
                save("decision_finalization_required")
        token_status = route_budget.provider_token_status(route, usage_totals)
        if not has_queued_calls and token_status is not None and token_status["used"] >= token_status["limit"]:
            message = (
                "V5 reached its routed provider-token budget "
                f"({token_status['used']}/{token_status['limit']})."
            )
            code = "provider_token_budget_exhausted"
            checkpoint = trajectory.checkpoint(state, code, message)
            save(code)
            raise V5Error(code, message, checkpoint=checkpoint)
        counters["provider_attempts"] += 1
        save("provider_attempt_started")
        try: result = complete(context.messages(objective, route, state), counters["provider_attempts"])
        except Exception as exc:
            code = str(getattr(exc, "code", "provider_failed"))
            if reliability.can_retry(state, code):
                retry = reliability.record_retry(state, code)
                assessment = completion.assess(state, route)
                state["completion_assessment"] = assessment
                if assessment["status"] == "sufficient":
                    state["pending"] = "frontier_completion"
                state["last_error"] = {"code": code, "message": "Provider timed out; retrying once without discarding accumulated evidence."}
                trajectory.append(state, {"kind": "system", "status": "retry", "summary": "Transient provider failure; retrying within the durable budget.", "result": {"assessment": assessment, "provider_reliability": retry}})
                save("provider_retry_recorded")
                continue
            checkpoint = trajectory.checkpoint(state, code, str(exc))
            save("provider_interrupted")
            raise V5Error(code, str(exc), checkpoint=checkpoint) from exc
        replayed_call = result.get("_mf5_replayed_tool_call") is True
        if replayed_call:
            counters["provider_attempts"] = max(0, counters["provider_attempts"] - 1)
        else:
            reliability.record_success(state)
            counters["provider_calls"] += 1
            usage = result.get("usage") if isinstance(result.get("usage"), dict) else None
            if token_status is not None and route_budget.usage_tokens(usage) is None:
                message = "Provider omitted measurable token usage required by the routed budget."
                code = "provider_usage_unavailable"
                checkpoint = trajectory.checkpoint(state, code, message)
                save(code)
                raise V5Error(code, message, checkpoint=checkpoint)
            if usage is not None:
                usage_totals = usage_accounting.record(usage_totals, usage)
                usages.append(usage)
                usages[:] = usages[-16:]
            token_status = route_budget.provider_token_status(route, usage_totals)
            if token_status is not None and token_status["used"] > token_status["limit"]:
                message = (
                    "Provider usage exceeded the routed token budget "
                    f"({token_status['used']}/{token_status['limit']})."
                )
                code = "provider_token_budget_exhausted"
                checkpoint = trajectory.checkpoint(state, code, message)
                save(code)
                raise V5Error(code, message, checkpoint=checkpoint)
        decision = normalize(result)
        remaining_calls = decision.pop("remaining_tool_calls", [])
        if remaining_calls:
            state["queued_tool_calls"] = [*remaining_calls, *(state.get("queued_tool_calls") or [])][:16]
        if decision["kind"] == "final":
            open_outcomes = [] if task_policy.requires_decision(route) else executive.open_outcomes(state.get("executive"))
            if task_policy.requires_decision(route) and not completion.ready(state, route):
                counters["outcome_repairs"] += 1
                assessment = completion.assess(state, route)
                if counters["outcome_repairs"] >= 2:
                    message = assessment["reason"]
                    checkpoint = trajectory.checkpoint(state, "decision_record_incomplete", message)
                    save("decision_record_incomplete")
                    raise V5Error("decision_record_incomplete", message, checkpoint=checkpoint)
                state["last_error"] = {
                    "code": "decision_record_required", "message": assessment["reason"],
                    "next_actions": assessment["next_actions"],
                }
                save("decision_record_requested")
                continue
            if open_outcomes:
                counters["outcome_repairs"] += 1
                labels = ", ".join(str(item.get("id") or "outcome") for item in open_outcomes[:6])
                message = f"Actionable model-owned outcomes remain open: {labels}."
                if counters["outcome_repairs"] >= 3:
                    checkpoint = trajectory.checkpoint(state, "outcomes_unresolved", message)
                    save("outcomes_unresolved")
                    raise V5Error("outcomes_unresolved", message, checkpoint=checkpoint)
                state["pending"] = None
                state["last_error"] = {
                    "code": "outcome_resolution_required",
                    "message": message + " Use checkpoint now to revise each outcome to done, dropped, or blocked before finishing.",
                }
                save("outcome_resolution_requested")
                continue
            if task_policy.requires_mutation(route) and not state["operation_ledger"].get("mutations") and not completion.verified_noop(state, route):
                counters["implementation_repairs"] += 1
                if counters["implementation_repairs"] >= 2:
                    message = "Implementation task returned no applied repository mutation."
                    checkpoint = trajectory.checkpoint(state, "implementation_incomplete", message)
                    save("implementation_incomplete")
                    raise V5Error("implementation_incomplete", message, checkpoint=checkpoint)
                state["last_error"] = {
                    "code": "implementation_action_required",
                    "message": "Apply one authorized repository mutation before completing this implementation task.",
                }
                state["pending"] = None
                save("implementation_repair_requested")
                continue
            if state["operation_ledger"].get("mutations"):
                verification = verify_worktree(state["operation_ledger"]) if verify_worktree else {"ok": False, "code": "worktree_verification_unavailable"}
                if verification.get("ok") is not True:
                    counters["proof_repairs"] += 1
                    if counters["proof_repairs"] > 4:
                        message = "Repository postimages changed or could not be verified before completion."
                        checkpoint = trajectory.checkpoint(state, "worktree_proof_incomplete", message)
                        save("worktree_proof_incomplete")
                        raise V5Error("worktree_proof_incomplete", message, checkpoint=checkpoint)
                    state["last_error"] = {"code": str(verification.get("code") or "worktree_postimage_mismatch"), "message": "Re-inspect the mutation and obtain proof for the current postimages."}
                    save("worktree_repair_requested")
                    continue
            if task_policy.requires_verification(route):
                verification_gaps = operation_ledger.verification_missing(state["operation_ledger"])
                if verification_gaps:
                    counters["proof_repairs"] += 1
                    if counters["proof_repairs"] > 3:
                        message = "Verification lacks required proof: " + ", ".join(verification_gaps) + "."
                        checkpoint = trajectory.checkpoint(state, "verification_incomplete", message)
                        save("verification_incomplete")
                        raise V5Error("verification_incomplete", message, checkpoint=checkpoint)
                    state["last_error"] = {
                        "code": "verification_proof_required",
                        "message": "Before completing verification, obtain: " + ", ".join(verification_gaps) + ".",
                    }
                    save("verification_repair_requested")
                    continue
            missing_proof = [] if task_policy.llm_autonomous(route) else operation_ledger.missing(
                state["operation_ledger"],
                worktree=str(verification.get("digest") or "") if state["operation_ledger"].get("mutations") else None,
            )
            if missing_proof:
                counters["proof_repairs"] += 1
                if counters["proof_repairs"] > 4:
                    message = "Changed files lack required proof: " + ", ".join(missing_proof) + "."
                    checkpoint = trajectory.checkpoint(state, "proof_incomplete", message)
                    save("proof_incomplete")
                    raise V5Error("proof_incomplete", message, checkpoint=checkpoint)
                state["last_error"] = {"code": "operation_proof_required", "message": "Before completing, obtain: " + ", ".join(missing_proof) + "."}
                save("proof_repair_requested")
                continue
            typed_runtime_negative = task_policy.request_class(route) == "runtime_inspection" and any(
                item.get("ok") is not True and task_policy.accepts_tool_evidence(route, item)
                for item in tools
            )
            grounded_without_evidence = (
                task_policy.requires_tool_evidence(route)
                and not completion.ready(state, route)
                and not typed_runtime_negative
            )
            if grounded_without_evidence:
                counters["evidence_repairs"] += 1
                if counters["evidence_repairs"] >= 2:
                    message = "Grounded task returned a final answer without fresh tool evidence."
                    checkpoint = trajectory.checkpoint(state, "evidence_incomplete", message)
                    save("evidence_incomplete")
                    raise V5Error("evidence_incomplete", message, checkpoint=checkpoint)
                state["last_error"] = {
                    "code": "fresh_tool_evidence_required",
                    "message": "Use one declared tool to inspect current evidence before answering this grounded task.",
                }
                save("evidence_repair_requested")
                continue
            state.update({"status": "completed", "pending": None, "last_error": None, "final_answer": decision["answer"]})
            state["pending_action"] = None
            save("completed")
            return Outcome(
                decision["answer"], state, counters["provider_calls"],
                counters["provider_attempts"], tools, usages,
                usage_totals,
            )
        if decision["kind"] == "invalid":
            if str(result.get("finish_reason") or "").lower() in {"length", "max_tokens"}:
                counters["length_continuations"] += 1
                if counters["length_continuations"] <= 3:
                    state["last_error"] = {
                        "code": "provider_output_length",
                        "message": "The prior inference exhausted its output allowance before emitting a decision. Continue from the durable context and emit a native tool call or plain final answer.",
                    }
                    save("provider_length_continuation_requested")
                    continue
            counters["invalid_decisions"] += 1
            if counters["invalid_decisions"] >= 2:
                checkpoint = trajectory.checkpoint(state, "model_output_invalid", "Frontier returned malformed decisions twice.")
                save("model_output_invalid")
                raise V5Error("model_output_invalid", "Frontier returned malformed decisions twice.", checkpoint=checkpoint)
            state["last_error"] = {"code": "model_output_invalid", "message": "Return one declared tool call or final answer JSON object."}
            save("model_output_repair_requested")
            continue
        if context.completion_only(state, route):
            counters["no_progress"] += 1
            assessment = completion.assess(state, route)
            state["completion_assessment"] = assessment
            message = "Completion-only synthesis cannot execute another tool decision. Return the final answer."
            trajectory.append(state, {
                "kind": "system", "tool": str(decision.get("tool") or ""),
                "status": "rejected", "summary": message,
                "result": {"assessment": assessment},
            })
            if counters["no_progress"] >= 2:
                checkpoint = trajectory.checkpoint(state, "no_semantic_progress", message)
                save("completion_tool_rejected")
                raise V5Error("no_semantic_progress", message, checkpoint=checkpoint)
            state["last_error"] = {"code": "completion_tool_forbidden", "message": message}
            save("completion_tool_repair_requested")
            continue
        name, arguments = decision["tool"], decision["arguments"]
        active_names = {item["name"] for item in policy.active_descriptors(route, state)}
        retired_autonomous_stage_tool = (
            task_policy.llm_autonomous(route)
            and task_policy.requires_mutation(route)
            and name in {"checkpoint", "search", "read"}
            and name not in active_names
        )
        if retired_autonomous_stage_tool:
            counters["no_progress"] += 1
            counters["duplicate_actions"] += 1
            state["queued_tool_calls"] = []
            message = f"The {name} tool is no longer active for the current workflow stage."
            state["last_error"] = {
                "code": "workflow_stage_complete",
                "message": message + " Choose one of the currently declared tools or return an explicit blocker.",
                "active_tools": sorted(active_names),
            }
            trajectory.append(state, {
                "kind": "system", "tool": name, "status": "rejected",
                "summary": message, "result": {"active_tools": sorted(active_names)},
            })
            save("workflow_stage_action_rejected")
            continue
        if name == "edit":
            arguments = bind_observed_preimages(arguments, state, route)
        revision = int(state["operation_ledger"].get("revision") or 0)
        action_id = trajectory.action_id(name, arguments, str(route.get("route_id") or ""), revision)
        route_action_id = trajectory.action_id(name, arguments, str(route.get("route_id") or ""))
        legacy_action_id = trajectory.action_id(name, arguments)
        compatible_ids = (action_id, route_action_id, legacy_action_id) if revision == 0 or name == "edit" else (action_id,)
        completed_action_id = next(
            (candidate for candidate in compatible_ids if candidate in state["completed_actions"]),
            action_id,
        )
        refresh_verification = (
            name in {"test", "prove"}
            and not operation_ledger.verification_receipt_satisfied(state["operation_ledger"], name)
        )
        if completed_action_id in state["completed_actions"] and not refresh_verification:
            counters["no_progress"] += 1
            counters["duplicate_actions"] += 1
            prior = state["completed_actions"][completed_action_id]
            prior_observation = prior.get("observation") if isinstance(prior, dict) and isinstance(prior.get("observation"), dict) else prior
            assessment = completion.assess(state, route)
            state["completion_assessment"] = assessment
            trajectory.append(state, {"kind": "system", "tool": name, "status": "duplicate", "summary": "Equivalent completed action reused.", "result": prior_observation})
            if assessment["status"] == "sufficient":
                state["pending"] = "frontier_completion"
                state["last_error"] = {"code": "action_already_completed", "message": f"Do not repeat {name}. Answer now from the accumulated evidence."}
                save("completed_action_reused")
                continue
            if assessment["status"] == "incomplete" and (
                not route_budget.hard_enforced(route) or counters["no_progress"] < 2
            ):
                state["last_error"] = {"code": "evidence_incomplete", "message": assessment["reason"], "next_actions": assessment["next_actions"]}
                save("duplicate_action_repair_requested")
                continue
            checkpoint = trajectory.checkpoint(state, "evidence_incomplete", assessment["reason"])
            save("duplicate_action_incomplete")
            raise V5Error("evidence_incomplete", assessment["reason"], checkpoint=checkpoint)
        admission = novelty.admit(state, name, arguments, route)
        if admission.get("ok") is not True:
            counters["no_progress"] += 1
            counters["duplicate_actions"] += 1
            message = str(admission.get("message") or "The requested action adds no new evidence.")
            state["last_error"] = {
                "code": str(admission.get("code") or "novelty_required"),
                "message": message,
                "next_actions": admission.get("next_actions") or [],
            }
            trajectory.append(state, {
                "kind": "system", "tool": name, "status": "rejected",
                "summary": message, "result": admission,
            })
            save("novelty_action_rejected")
            continue
        if name == "edit":
            operations = arguments.get("operations") if isinstance(arguments.get("operations"), list) else []
            planned_paths: list[str] = []
            for operation in operations:
                if not isinstance(operation, dict):
                    continue
                planned_paths.append(str(operation.get("path") or ""))
                if str(operation.get("op") or "").strip().lower() == "move":
                    planned_paths.append(str(operation.get("destination") or operation.get("to") or ""))
            try:
                operation_ledger.ensure_mutation_capacity(
                    state["operation_ledger"], planned_paths, route_id=str(route.get("route_id") or ""),
                )
            except operation_ledger.OperationLedgerError as exc:
                checkpoint = trajectory.checkpoint(state, exc.code, str(exc))
                save(exc.code)
                raise V5Error(exc.code, str(exc), checkpoint=checkpoint) from exc
        state["pending_action"] = {"action_id": action_id, "tool": name, "status": "started"}
        counters["tool_calls"] += 1
        save("action_started")
        try:
            observed = execute(name, arguments)
        except Exception as exc:
            message = f"The {name} operation was interrupted before a durable result was recorded."
            checkpoint = trajectory.checkpoint(state, "action_outcome_unknown", message)
            save("action_outcome_unknown")
            raise V5Error("action_outcome_unknown", message, checkpoint=checkpoint) from exc
        novelty_result = novelty.classify_observation(state, name, observed)
        if name == "checkpoint" and observed.get("ok") is True:
            state["executive"] = executive.normalize(observed.get("executive"))
        if name in {"test", "diff", "prove"} and state["operation_ledger"].get("mutations"):
            verification = verify_worktree(state["operation_ledger"]) if verify_worktree else {"ok": False, "code": "worktree_verification_unavailable"}
            if verification.get("ok") is not True:
                observed = {"ok": False, "code": str(verification.get("code") or "worktree_postimage_mismatch"), "summary": "Repository postimages no longer match the applied mutation receipt."}
            else:
                observed = {**observed, "worktree_sha256": str(verification.get("digest") or "")}
        state["operation_ledger"] = operation_ledger.record(state["operation_ledger"], name, observed, action_id=action_id)
        if observed.get("ok") is not True:
            # Remaining calls were selected before the model observed this
            # failure and may depend on the failed action's assumptions.
            state["queued_tool_calls"] = []
        tools.append(trajectory.receipt(observed))
        tools[:] = tools[-128:]
        compact = trajectory.compact_observation(observed)
        state["completed_actions"][action_id] = {"tool": name, "observation": trajectory.receipt(observed)}
        state["completed_actions"] = dict(list(state["completed_actions"].items())[-trajectory.MAX_ACTIONS:])
        state["pending_action"] = None
        trajectory.append(state, {"kind": "tool", "action_id": action_id, "tool": name, "status": "completed" if observed.get("ok") else "failed", "summary": observed.get("summary") or observed.get("code") or name, "result": compact})
        if not observed.get("ok") and task_policy.accepts_tool_evidence(route, observed):
            state["pending"] = "frontier_completion"
            state["last_error"] = {
                "code": str(observed.get("code") or "typed_negative_evidence"),
                "message": "The requested runtime capability is unavailable. Answer from this bounded negative evidence without further tools.",
            }
            counters["no_progress"] = 0
            save("typed_negative_evidence_recorded")
            continue
        if observed.get("ok") and novelty_result.get("novel") is False:
            counters["no_progress"] += 1
            counters["duplicate_actions"] += 1
            state["last_error"] = {
                "code": str(novelty_result.get("code") or "novelty_required"),
                "message": str(novelty_result.get("message") or "The action returned no new evidence."),
                "next_actions": novelty_result.get("next_actions") or [],
            }
            trajectory.append(state, {
                "kind": "system", "tool": name, "status": "redundant",
                "summary": state["last_error"]["message"], "result": novelty_result,
            })
            save("action_completed_without_novelty")
            continue
        if observed.get("ok"):
            state["last_error"] = None
            counters["no_progress"] = 0
        else:
            state["last_error"] = {
                "code": str(observed.get("code") or "tool_failed"),
                "message": str(observed.get("summary") or f"The {name} tool failed."),
                "tool": name,
            }
            counters["no_progress"] += 1
        save("action_completed")
        if counters["no_progress"] >= 2 and route_budget.hard_enforced(route):
            checkpoint = trajectory.checkpoint(state, "no_semantic_progress", "Two tool decisions produced no useful progress.")
            save("no_semantic_progress")
            raise V5Error("no_semantic_progress", "Two tool decisions produced no useful progress.", checkpoint=checkpoint)
