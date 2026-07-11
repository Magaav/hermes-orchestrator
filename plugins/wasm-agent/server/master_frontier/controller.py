from __future__ import annotations

import json
from typing import Any, Callable

from . import budget
from . import controller_v3
from . import cyphers_v3
from . import envelope
from . import envelope_v2


Port = Callable[..., Any]


def usage_components(result: dict[str, Any]) -> list[dict[str, Any]]:
    components = result.get("usage_components") if isinstance(result.get("usage_components"), list) else []
    normalized = [item for item in components if isinstance(item, dict)]
    if normalized:
        return normalized
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else None
    return [usage] if usage else []


def aggregate_token_usage(
    usages: list[dict[str, Any]],
    *,
    source: str,
    model: str = "",
    normalize: Port,
    token_int: Port,
) -> dict[str, Any] | None:
    normalized = [normalize(usage, source=str(usage.get("source") or source)) for usage in usages if isinstance(usage, dict)]
    normalized = [usage for usage in normalized if usage]
    if not normalized:
        return None
    result = {
        "prompt_tokens": sum(int(token_int(usage.get("prompt_tokens")) or 0) for usage in normalized),
        "completion_tokens": sum(int(token_int(usage.get("completion_tokens")) or 0) for usage in normalized),
        "total_tokens": sum(int(token_int(usage.get("total_tokens")) or 0) for usage in normalized),
        "cached_input_tokens": sum(int(token_int(usage.get("cached_input_tokens") or usage.get("cache_read_tokens")) or 0) for usage in normalized),
        "reasoning_tokens": sum(int(token_int(usage.get("reasoning_output_tokens") or usage.get("reasoning_tokens")) or 0) for usage in normalized),
        "api_calls": len(normalized),
        "source": source,
        "usage_scope": "llm_api_call",
        "usage_accuracy": "provider_exact",
        "billable": True,
    }
    if model:
        result["model"] = model
    return result


def continue_after_local_tools(
    *,
    ports: dict[str, Port],
    body: dict[str, Any],
    route_envelope: dict[str, Any],
    receiver: str,
    run_id: str,
    parsed: Any,
    result: dict[str, Any],
    local_tool_results: list[dict[str, Any]],
) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    """Run evidence-driven continuation under explicit runtime side-effect ports."""
    usages = usage_components(result)
    started = float(body.get("_master_frontier_started_monotonic") or ports["monotonic"]())

    def enforce_budget() -> None:
        violation = budget.violation(route_envelope, usages, started_monotonic=started)
        if violation:
            ports["error"](
                str(violation["code"]),
                f"Master:frontier budget exhausted ({violation['used']}/{violation['limit']}).",
            )

    enforce_budget()
    max_continuations = budget.continuation_limit(
        route_envelope,
        calls_used=budget.provider_calls_used(usages),
    )
    turn_id = str(body.get("turn_id") or route_envelope.get("trace_id") or run_id)[:160]
    seen_action_keys: set[str] = set()
    no_progress_count = 0
    evidence_after_last_inference = 0

    for continuation_index in range(1, max_continuations + 1):
        if not ports["should_continue"](route_envelope, parsed, result.get("reply", ""), local_tool_results, None):
            return (*ports["repo_answer"](route_envelope, parsed, result, local_tool_results), local_tool_results)

        inference_id = f"head-{continuation_index + 1}"
        violation_event = envelope_v2.loop_violation_event(
            turn_id=turn_id,
            inference_id=inference_id,
            previous_evidence_count=evidence_after_last_inference,
            current_evidence_count=len(local_tool_results),
        )
        if violation_event:
            ports["append_v2"]([violation_event])
            ports["error"](
                "loop_contract_violation",
                "Second LLM decision blocked because no new evidence or structured failure exists after the prior semantic decision.",
            )

        ports["append_event"](
            "head.continued",
            "Continuing direct head with local tool evidence",
            {
                "reason": "local_tool_evidence_available",
                "local_tool_count": len(local_tool_results),
                "receiver": receiver,
                "index": continuation_index,
            },
        )
        ports["append_v2"](envelope_v2.inference_started_events(
            turn_id=turn_id,
            inference_id=inference_id,
            stage="head.continued",
            model=str(result.get("model") or "")[:180],
        ))

        continued_result = ports["complete"](ports["continuation_body"](body, route_envelope, local_tool_results))
        usages.extend(usage_components(continued_result))
        enforce_budget()
        ports["append_usage"](continued_result, turn_id, inference_id)
        continued_parsed = continued_result.get("parsed") if isinstance(continued_result.get("parsed"), dict) else {}
        salvaged = envelope.salvage_continued_answer_after_tool_evidence(continued_parsed, continued_result.get("reply", ""))
        if salvaged:
            continued_parsed = {
                "answer": salvaged,
                "decision": "answer",
                "actions": [],
                "state_delta": {},
                "needs": [],
                "confidence": continued_parsed.get("confidence"),
            }
            continued_result = {**continued_result, "parsed": continued_parsed, "reply": salvaged}
        elif not envelope.local_tool_actions(continued_parsed) and ports["answer_stale"](
            ports["answer_text"](continued_parsed, continued_result.get("reply", "")),
            local_tool_results,
        ):
            final_answer = ports["summary"]("", local_tool_results)
            if final_answer.strip():
                continued_parsed = _answer(final_answer)
                continued_result = {**continued_result, "parsed": continued_parsed, "reply": final_answer}
        else:
            ports["enforce_action"](continued_parsed, continued_result.get("reply", ""), route_envelope)

        aggregate = ports["aggregate_usage"](usages, receiver, continued_result, result)
        if aggregate:
            continued_result = {**continued_result, "usage": aggregate, "usage_components": usages}
        decision = str(continued_parsed.get("decision") or continued_parsed.get("answer") or continued_result.get("reply") or "continued direct head replied")[:240]
        ports["append_event"](
            "head.decision",
            decision,
            {
                "decision": str(continued_parsed.get("decision") or "")[:120],
                "actions": continued_parsed.get("actions") if isinstance(continued_parsed.get("actions"), list) else [],
                "needs": continued_parsed.get("needs") if isinstance(continued_parsed.get("needs"), list) else [],
                "confidence": continued_parsed.get("confidence"),
                "continued": True,
                "index": continuation_index,
            },
        )
        ports["append_v2"](envelope_v2.decision_events(
            continued_parsed,
            continued_result.get("reply", ""),
            route_envelope,
            turn_id=turn_id,
            inference_id=inference_id,
            stage="head.continued",
        ))
        evidence_after_last_inference = len(local_tool_results)
        continued_parsed, continued_result = ports["repo_answer"](
            route_envelope,
            continued_parsed,
            continued_result,
            local_tool_results,
        )
        action_keys = [
            json.dumps(
                {"action": envelope.canonical_action_name(action), "args": envelope.redact(envelope.action_args(action))},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            for action in envelope.local_tool_actions(continued_parsed)
        ]
        duplicate_actions = bool(action_keys) and all(key in seen_action_keys for key in action_keys)
        seen_action_keys.update(action_keys)
        if duplicate_actions:
            no_progress_count += 1
            final_answer = ports["summary"]("", local_tool_results)
            if final_answer.strip():
                return _answer(final_answer), {**continued_result, "parsed": _answer(final_answer), "reply": final_answer}, local_tool_results
            if no_progress_count >= 2:
                return parsed, result, local_tool_results
            continue

        more_results = ports["execute_actions"](envelope.local_tool_actions(continued_parsed))
        parsed, result = continued_parsed, continued_result
        if more_results:
            ports["record_results"](more_results, turn_id, inference_id)
            local_tool_results = [*local_tool_results, *more_results]
            local_tool_results = ports["ensure_probe"](local_tool_results)
            local_tool_results = ports["ensure_source"](local_tool_results)
            local_tool_results = ports["ensure_runtime"](local_tool_results)
            no_progress_count = 0
            continue
        if ports["answer_stale"](ports["answer_text"](parsed, result.get("reply", "")), local_tool_results):
            no_progress_count += 1
            final_answer = ports["summary"]("", local_tool_results)
            if final_answer.strip():
                parsed = _answer(final_answer)
                result = {**result, "parsed": parsed, "reply": final_answer}
            if no_progress_count < 2 and not final_answer.strip():
                continue
        return parsed, result, local_tool_results

    final_answer = ports["summary"]("", local_tool_results)
    if final_answer.strip():
        parsed = _answer(final_answer)
        result = {**result, "parsed": parsed, "reply": final_answer}
    return parsed, result, local_tool_results


def _answer(text: str) -> dict[str, Any]:
    return {
        "answer": text,
        "decision": "answer",
        "actions": [],
        "state_delta": {},
        "needs": [],
        "confidence": 1,
    }


_RUNTIME_PORT_NAMES = frozenset({
    'HTTPStatus',
    'ProviderProxyError',
    'append_agent_run_event',
    'append_envelope_v2_events',
    'append_envelope_v2_inference_usage',
    'append_master_frontier_proof_event',
    'bridge_trace_action_events',
    'clipped',
    'compact_context_measurement',
    'direct_envelope_error',
    'direct_envelope_json',
    'direct_envelope_names',
    'direct_envelope_semantic_text',
    'direct_head_answer_still_requests_local_tools',
    'direct_head_answer_text',
    'direct_head_change_actions',
    'direct_head_change_proof',
    'direct_head_conceptual_evidence_floor',
    'direct_head_continue_after_local_tools',
    'direct_head_empty_response_repair_body',
    'direct_head_has_runtime_entity_routes',
    'direct_head_hermes_dispatch_action',
    'direct_head_local_evidence_projection',
    'direct_head_local_runtime_proof_satisfies_dispatch',
    'direct_head_local_tool_actions',
    'direct_head_local_tool_summary_reply',
    'direct_head_merge_local_change_proof',
    'direct_head_normalize_conceptual_result',
    'direct_head_objective_is_implementation_intent',
    'direct_head_objective_is_repo_object_question',
    'direct_head_provider_error_is_repairable_empty',
    'direct_head_repo_object_answer_from_evidence',
    'direct_head_runtime_entity_objective_needs_local_inspection',
    'direct_head_runtime_entity_transport_fallback',
    'direct_head_server_provider_requested',
    'enforce_direct_head_goal_completion',
    'enforce_direct_head_structured_action',
    'enforce_kernel_before_unknown_answer',
    'enforce_master_frontier_loop_completion',
    'ensure_direct_head_objective_runtime_entity_preflight',
    'ensure_direct_head_repo_object_probe',
    'ensure_direct_head_repo_object_runtime_scope_preflight',
    'ensure_direct_head_repo_object_source_read',
    'ensure_direct_head_runtime_entity_preflight',
    'exact_llm_token_usage',
    'execute_direct_head_hermes_dispatch',
    'execute_direct_head_local_tool_actions',
    'finish_agent_run',
    'master_frontier_entity_resolution',
    'master_frontier_envelope',
    'master_frontier_envelope_v2',
    'master_frontier_repair',
    'maybe_repair_direct_head_completion_dispatch',
    'normalize_token_usage',
    'openai_responses_completion',
    'provider_envelope_completion',
    're',
    'record_agent_run_action',
    'record_agent_run_final_proof_events',
    'record_agent_run_token_usage_event',
    'record_direct_head_local_tool_events',
    'require_direct_envelope_route_contract',
    'route_contract_summary',
    'safe_state_id',
    'safe_worktree_tree_sha',
    'time',
    'token_int_value',
    'token_usage_with_raw_usage',
})


def bind_runtime(runtime: dict[str, Any]) -> None:
    missing = sorted(name for name in _RUNTIME_PORT_NAMES if name not in runtime)
    if missing:
        raise RuntimeError(f"Master:frontier controller runtime ports missing: {','.join(missing)}")
    globals().update({name: runtime[name] for name in _RUNTIME_PORT_NAMES})


def provider_envelope_run_execute_owned(
    server: WasmAgentServer,
    body: dict[str, Any],
    *,
    user: dict[str, Any] | None = None,
    run: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    body.setdefault("_master_frontier_started_monotonic", time.monotonic())
    envelope = context["envelope"]
    if cyphers_v3.is_v3(envelope):
        return controller_v3.execute_owned(server, body, user=user, run=run, context=context, runtime=globals())
    try:
        route_contract = require_direct_envelope_route_contract(envelope)
    except ProviderProxyError as exc:
        finish_agent_run(server, str(run.get("run_id") or ""), status="failed", error={"code": exc.code, "message": exc.message})
        raise
    semantic_envelope = str(context.get("semantic_envelope") or "")
    measurement = context["measurement"]
    receiver = str(context.get("receiver") or "provider")
    proxy_provider_config = context.get("proxy_provider_config") if isinstance(context.get("proxy_provider_config"), dict) else {}
    task_contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    before_tree = safe_worktree_tree_sha(server) if str(task_contract.get("intent") or "") == "implementation" else ""
    objective = str(envelope.get("objective") or body.get("message") or "direct envelope")
    space_id = safe_state_id(str(body.get("space_id") or "home"), "home")
    append_agent_run_event(
        server,
        str(run.get("run_id") or ""),
        "envelope.created",
        summary=clipped(str(envelope.get("objective") or "Direct envelope"), 180),
        payload={
            "envelope": {
                "schema": "agent-envelope-v1",
                "trace_id": envelope.get("trace_id", ""),
                "objective": clipped(str(envelope.get("objective") or ""), 500),
                "caps": direct_envelope_names(envelope.get("capabilities")),
                "refs": direct_envelope_names(envelope.get("evidence_refs") or envelope.get("evidence"), key="ref"),
                "actions": direct_envelope_names(envelope.get("allowed_actions")),
                "stream": bool(envelope.get("stream")),
                "receiver": receiver,
            },
            "context_measurement": measurement,
        },
    )
    append_agent_run_event(
        server,
        str(run.get("run_id") or ""),
        "route.resolved",
        summary=f"{route_contract.get('route_id')} -> {route_contract.get('owner')}",
        payload={
            "route_contract": route_contract,
            "map_summary": route_contract_summary(route_contract),
        },
    )
    append_agent_run_event(
        server,
        str(run.get("run_id") or ""),
        "head.started",
        summary="Direct head request started",
        payload={"context_measurement": measurement},
    )
    append_envelope_v2_events(
        server,
        str(run.get("run_id") or ""),
        master_frontier_envelope_v2.inference_started_events(
            turn_id=clipped(str(run.get("turn_id") or envelope.get("trace_id") or ""), 160),
            inference_id="head-1",
            stage="head",
        ),
    )
    preflight_local_tool_results: list[dict[str, Any]] = []
    if not direct_head_conceptual_evidence_floor(envelope) and direct_head_objective_is_repo_object_question(envelope):
        run_id = str(run.get("run_id") or "")
        append_agent_run_event(
            server,
            run_id,
            "head.decision",
            summary="repo_object_code_memory_preflight",
            payload={
                "decision": "repo_object_code_memory_preflight",
                "reason": "repo-object UI question requires route-scoped code-memory evidence before provider answer",
            },
        )
        preflight_local_tool_results = ensure_direct_head_repo_object_probe(
            server,
            envelope,
            user=user,
            run_id=run_id,
            local_tool_results=preflight_local_tool_results,
        )
        preflight_local_tool_results = ensure_direct_head_repo_object_source_read(
            server,
            envelope,
            user=user,
            run_id=run_id,
            local_tool_results=preflight_local_tool_results,
        )
        preflight_local_tool_results = ensure_direct_head_repo_object_runtime_scope_preflight(
            server,
            envelope,
            user=user,
            run_id=run_id,
            local_tool_results=preflight_local_tool_results,
        )
        packet = master_frontier_entity_resolution.evidence_packet(envelope, preflight_local_tool_results)
        if packet:
            compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
            envelope["compact_state"] = {**compact_state, "quest_state": packet.get("quest_state")}
            envelope["repo_object_evidence_line"] = packet.get("source_line")
            envelope["local_kernel_evidence"] = direct_head_local_evidence_projection(preflight_local_tool_results)
            envelope["state_summary"] = clipped(
                "Answer from available source evidence. Missing runtime scope proof is a caveat, not a reason to withhold an informational answer.",
                400,
            )
            semantic_envelope = direct_envelope_semantic_text(envelope)
            measurement = compact_context_measurement("direct-head-envelope", semantic_envelope, baseline_text=direct_envelope_json(envelope))
            append_master_frontier_proof_event(
                server,
                run_id,
                envelope,
                stage="repo_object_preflight",
                local_tool_results=preflight_local_tool_results,
            )
    if not direct_head_conceptual_evidence_floor(envelope) and direct_head_runtime_entity_objective_needs_local_inspection(envelope):
        run_id = str(run.get("run_id") or "")
        append_agent_run_event(
            server,
            run_id,
            "head.decision",
            summary="local_runtime_route_inspection",
            payload={
                "decision": "local_runtime_route_inspection",
                "reason": "declared runtime entity objective requires bounded local inspection before provider answer",
            },
        )
        preflight_local_tool_results = ensure_direct_head_objective_runtime_entity_preflight(
            server,
            envelope,
            user=user,
            run_id=run_id,
            local_tool_results=[],
        )
        preflight_local_tool_results = ensure_direct_head_repo_object_probe(
            server,
            envelope,
            user=user,
            run_id=run_id,
            local_tool_results=preflight_local_tool_results,
        )
        preflight_local_tool_results = ensure_direct_head_repo_object_source_read(
            server,
            envelope,
            user=user,
            run_id=run_id,
            local_tool_results=preflight_local_tool_results,
        )
        preflight_local_tool_results = ensure_direct_head_repo_object_runtime_scope_preflight(
            server,
            envelope,
            user=user,
            run_id=run_id,
            local_tool_results=preflight_local_tool_results,
        )
        packet = master_frontier_entity_resolution.evidence_packet(envelope, preflight_local_tool_results)
        if packet:
            compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
            envelope["compact_state"] = {**compact_state, "quest_state": packet.get("quest_state")}
            envelope["repo_object_evidence_line"] = packet.get("source_line")
            append_master_frontier_proof_event(
                server,
                run_id,
                envelope,
                stage="runtime_preflight",
                local_tool_results=preflight_local_tool_results,
            )
        append_agent_run_event(
            server,
            run_id,
            "kernel.evidence_ready",
            summary="Local runtime route proof attached for LLM composition",
            payload={
                "reason": "local_runtime_route_proof_for_llm",
                "local_tools": direct_head_local_evidence_projection(preflight_local_tool_results),
            },
        )
        envelope["local_kernel_evidence"] = direct_head_local_evidence_projection(preflight_local_tool_results)
        semantic_envelope = direct_envelope_semantic_text(envelope)
        measurement = compact_context_measurement(
            "direct-head-envelope",
            semantic_envelope,
            baseline_text=direct_envelope_json(envelope),
        )
    try:
        if receiver in {"openai-responses", "openai-codex"}:
            def emit_openai_event(progress: dict[str, Any]) -> None:
                if progress.get("type") == "head.delta":
                    append_agent_run_event(
                        server,
                        str(run.get("run_id") or ""),
                        "head.delta",
                        summary=clipped(str(progress.get("summary") or "OpenAI delta"), 180),
                        payload=progress.get("payload") if isinstance(progress.get("payload"), dict) else {},
                    )
                    return
                record_agent_run_action(server, str(run.get("run_id") or ""), progress)

            try:
                result = openai_responses_completion(
                    server,
                    body,
                    envelope,
                    run_id=str(run.get("run_id") or ""),
                    user=user,
                    action_callback=emit_openai_event,
                )
            except ProviderProxyError as exc:
                if not direct_head_provider_error_is_repairable_empty(exc):
                    raise
                append_agent_run_event(
                    server,
                    str(run.get("run_id") or ""),
                    "head.repair",
                    summary="Retrying direct head after empty provider content",
                    payload={"reason": "provider_empty_response", "receiver": receiver},
                )
                result = openai_responses_completion(
                    server,
                    direct_head_empty_response_repair_body(body),
                    envelope,
                    run_id=str(run.get("run_id") or ""),
                    user=user,
                    action_callback=emit_openai_event,
                )
            parsed, result = master_frontier_repair.repair_structured_action(
                body=body,
                route_envelope=envelope,
                receiver=receiver,
                result=result,
                completion=openai_responses_completion,
                completion_kwargs={
                    "server": server,
                    "envelope": envelope,
                    "run_id": str(run.get("run_id") or ""),
                    "user": user,
                    "action_callback": emit_openai_event,
                },
                record_event=lambda summary, reason, extra: append_agent_run_event(server, str(run.get("run_id") or ""), "head.repair", summary=summary, payload={"reason": reason, **extra}),
            )
            parsed, result = direct_head_normalize_conceptual_result(envelope, parsed, result)
            parsed, result = direct_head_repo_object_answer_from_evidence(
                envelope,
                parsed,
                result,
                preflight_local_tool_results,
            )
            enforce_direct_head_structured_action(parsed, result.get("reply", ""), envelope)
            if not direct_head_has_runtime_entity_routes(envelope):
                enforce_kernel_before_unknown_answer(parsed)
            decision = clipped(str(parsed.get("decision") or parsed.get("answer") or result.get("reply") or "OpenAI receiver replied"), 240)
            append_agent_run_event(
                server,
                str(run.get("run_id") or ""),
                "head.decision",
                summary=decision,
                payload={
                    "receiver": receiver,
                    "decision": clipped(str(parsed.get("decision") or "answer"), 120),
                    "actions": parsed.get("actions") if isinstance(parsed.get("actions"), list) else [],
                    "needs": parsed.get("needs") if isinstance(parsed.get("needs"), list) else [],
                    "confidence": parsed.get("confidence"),
                },
            )
            append_envelope_v2_events(
                server,
                str(run.get("run_id") or ""),
                master_frontier_envelope_v2.decision_events(
                    parsed,
                    result.get("reply", ""),
                    envelope,
                    turn_id=clipped(str(run.get("turn_id") or envelope.get("trace_id") or ""), 160),
                    inference_id="head-1",
                    stage="head",
                ),
            )
            append_envelope_v2_inference_usage(
                server,
                str(run.get("run_id") or ""),
                result=result,
                turn_id=clipped(str(run.get("turn_id") or envelope.get("trace_id") or ""), 160),
                inference_id="head-1",
                stage="head",
            )
            direct_action_tool_results = execute_direct_head_local_tool_actions(
                server,
                direct_head_local_tool_actions(parsed),
                envelope,
                user=user,
                run_id=str(run.get("run_id") or ""),
            )
            record_direct_head_local_tool_events(
                server,
                str(run.get("run_id") or ""),
                direct_action_tool_results,
                turn_id=clipped(str(run.get("turn_id") or envelope.get("trace_id") or ""), 160),
                inference_id="head-1",
            )
            local_tool_results = [
                *preflight_local_tool_results,
                *direct_action_tool_results,
            ]
            local_tool_results = ensure_direct_head_repo_object_probe(
                server,
                envelope,
                user=user,
                run_id=str(run.get("run_id") or ""),
                local_tool_results=local_tool_results,
            )
            local_tool_results = ensure_direct_head_repo_object_source_read(
                server,
                envelope,
                user=user,
                run_id=str(run.get("run_id") or ""),
                local_tool_results=local_tool_results,
            )
            local_tool_results = [] if direct_head_conceptual_evidence_floor(envelope) else ensure_direct_head_objective_runtime_entity_preflight(
                server,
                envelope,
                user=user,
                run_id=str(run.get("run_id") or ""),
                local_tool_results=local_tool_results,
            )
            parsed, result, local_tool_results = direct_head_continue_after_local_tools(
                server,
                body,
                envelope,
                receiver=receiver,
                user=user,
                run_id=str(run.get("run_id") or ""),
                parsed=parsed,
                result=result,
                local_tool_results=local_tool_results,
                action_callback=emit_openai_event,
            )
            dispatch_action = direct_head_hermes_dispatch_action(parsed)
            local_tool_results = ensure_direct_head_runtime_entity_preflight(
                server,
                dispatch_action,
                envelope,
                user=user,
                run_id=str(run.get("run_id") or ""),
                local_tool_results=local_tool_results,
            )
            if direct_head_local_runtime_proof_satisfies_dispatch(dispatch_action, envelope, local_tool_results):
                append_agent_run_event(
                    server,
                    str(run.get("run_id") or ""),
                    "hermes.skipped",
                    summary="Local runtime route proof satisfied dispatch request",
                    payload={"reason": "local_runtime_proof_satisfied"},
                )
                dispatch_action = None
            dispatch_result = (
                execute_direct_head_hermes_dispatch(
                    server,
                    dispatch_action,
                    envelope,
                    user=user,
                    run_id=str(run.get("run_id") or ""),
                    local_tool_results=local_tool_results,
                )
                if dispatch_action
                else None
            )
            dispatch_result = maybe_repair_direct_head_completion_dispatch(
                server,
                envelope=envelope,
                user=user,
                run_id=str(run.get("run_id") or ""),
                dispatch_result=dispatch_result if isinstance(dispatch_result, dict) else None,
                local_tool_results=local_tool_results,
            )
            final_reply = dispatch_result.get("reply") if isinstance(dispatch_result, dict) else direct_head_answer_text(parsed, result.get("reply", ""))
            parsed, result = direct_head_repo_object_answer_from_evidence(
                envelope,
                parsed,
                result,
                local_tool_results,
            )
            if not dispatch_result:
                final_reply = direct_head_answer_text(parsed, result.get("reply", ""))
            final_reply = master_frontier_envelope.suppress_duplicate_answer_blocks(final_reply)
            stale_local_tool_answer = direct_head_answer_still_requests_local_tools(final_reply, local_tool_results)
            if not dispatch_result and (
                not final_reply.strip()
                or re.fullmatch(r"\s*dispatch(?:\.|\s+)hermes\.?\s*", final_reply, flags=re.IGNORECASE)
                or stale_local_tool_answer
            ):
                final_reply = direct_head_local_tool_summary_reply("" if stale_local_tool_answer else final_reply, local_tool_results)
            target_node = (dispatch_result or {}).get("target_node") or "direct-head"
            head_token_usage = token_usage_with_raw_usage(
                exact_llm_token_usage(
                    result.get("usage"),
                    source=f"{receiver.replace('-', '_')}_direct",
                    model=clipped(str(result.get("model") or ""), 180),
                ),
                result.get("raw_usage"),
            )
            bridge_token_usage = (dispatch_result or {}).get("usage") if isinstance(dispatch_result, dict) else None
            change_proof = direct_head_change_proof(
                server,
                user=user,
                before_tree=before_tree,
                after_tree=safe_worktree_tree_sha(server) if before_tree else "",
                target_node=target_node,
                objective=objective,
                space_id=space_id,
            )
            change_proof = direct_head_merge_local_change_proof(change_proof, local_tool_results)
            state_writeback = master_frontier_envelope.state_writeback_projection(
                envelope,
                parsed,
                final_reply,
                local_tool_results=local_tool_results,
                dispatch_result=dispatch_result if isinstance(dispatch_result, dict) else None,
            )
            loop_state = enforce_master_frontier_loop_completion(
                server,
                str(run.get("run_id") or ""),
                envelope,
                parsed,
                final_reply,
                local_tool_results=local_tool_results,
                change_proof=change_proof,
                dispatch_result=dispatch_result if isinstance(dispatch_result, dict) else None,
            )
            final = {
                "schema": "hermes.wasm_agent.direct_head_run.final.v1",
                "run_id": run.get("run_id"),
                "turn_id": run.get("turn_id"),
                "route_id": route_contract.get("route_id"),
                "route_contract": route_contract,
                "reply": final_reply,
                "provider": {k: v for k, v in result.items() if k not in {"envelope_text"}},
                "local_tools": local_tool_results,
                "hermes_dispatch": dispatch_result,
                "diagnostics": {
                    "source": f"{receiver.replace('-', '_')}_hermes_dispatch" if dispatch_result else f"{receiver.replace('-', '_')}_direct",
                    "mode": "direct-head",
                    "receiver": receiver,
                    "target_node": target_node,
                    "route_id": route_contract.get("route_id"),
                    "route_contract": route_contract,
                    "context_measurement": result.get("context_measurement") or measurement,
                    "dispatch_context_measurement": (dispatch_result or {}).get("context_measurement"),
                    "local_tool_results": local_tool_results,
                    "bridge_trace": (dispatch_result or {}).get("bridge_trace"),
                    "token_usage": head_token_usage,
                    "token_usage_head": head_token_usage,
                    "token_usage_head_components": result.get("usage_components") if isinstance(result.get("usage_components"), list) else [],
                    "token_usage_bridge": bridge_token_usage,
                    "openai_response": result.get("openai_response"),
                    "state_feedback": parsed.get("state_feedback") if isinstance(parsed, dict) and isinstance(parsed.get("state_feedback"), dict) else {},
                    "model_reflection": parsed.get("model_reflection") if isinstance(parsed, dict) and isinstance(parsed.get("model_reflection"), dict) else {},
                    "state_writeback": state_writeback,
                    "self_check": master_frontier_envelope.self_check_projection(envelope, parsed, final_reply, local_tool_results=local_tool_results),
                    "changed_files_complete": True,
                    "master_frontier_loop": loop_state,
                    "before_checkpoint": change_proof.get("before_checkpoint"),
                    "auto_checkpoint": change_proof.get("auto_checkpoint"),
                },
                "changed_files": change_proof.get("changed_files") or [],
                "context_preview": [{"tool": f"{receiver.replace('-', '_')}_envelope", "preview": semantic_envelope[:1200]}],
                "actions": [
                    {
                        "id": receiver.replace("-", "_"),
                        "topic": "run-api",
                        "kind": "api",
                        "label": "OpenAI Codex OAuth" if receiver == "openai-codex" else "OpenAI Responses",
                        "status": "done",
                        "detail": decision,
                        "meta": result.get("model") or "openai",
                    }
                ] + bridge_trace_action_events((dispatch_result or {}).get("bridge_trace")) + direct_head_change_actions(change_proof),
                "proof": [
                    "route-used:/agent/provider/envelope/stream",
                    f"receiver:{receiver}",
                    f"target-node:{target_node}",
                    f"local-tools:{len(local_tool_results)}",
                ],
            }
            enforce_direct_head_goal_completion(
                server,
                str(run.get("run_id") or ""),
                envelope,
                change_proof,
                dispatch_result if isinstance(dispatch_result, dict) else None,
            )
            record_agent_run_final_proof_events(server, str(run.get("run_id") or ""), final)
            finish_agent_run(server, str(run.get("run_id") or ""), status="completed", final=final)
            return {
                **result,
                "reply": final_reply,
                "envelope_text": semantic_envelope,
                "hermes_dispatch": dispatch_result,
                "run": run,
                "run_id": run.get("run_id"),
                "turn_id": run.get("turn_id"),
            }
        if direct_head_server_provider_requested(body) and not (proxy_provider_config.get("api_key") or proxy_provider_config.get("apiKey")):
            decision = "Server direct-head provider unavailable; Hermes default fallback is disabled."
            append_agent_run_event(
                server,
                str(run.get("run_id") or ""),
                "head.decision",
                summary=decision,
                payload={
                    "decision": "provider_unavailable",
                    "actions": [],
                    "needs": [],
                    "confidence": 1,
                    "provider_head_unavailable": True,
                    "fallback_reason": "server direct-head provider API key is not configured",
                    "blocked_dispatch": "hermes_default_fallback_disabled",
                },
            )
            direct_envelope_error(
                "provider_head_unavailable",
                "Server direct-head provider key is not configured. Configure the direct-head provider or request an explicit bounded Hermes subagent dispatch; Hermes is not a default fallback.",
                HTTPStatus.BAD_GATEWAY,
            )
        def emit_provider_event(progress: dict[str, Any]) -> None:
            if progress.get("type") == "head.delta":
                append_agent_run_event(
                    server,
                    str(run.get("run_id") or ""),
                    "head.delta",
                    summary=clipped(str(progress.get("summary") or "Provider delta"), 180),
                    payload=progress.get("payload") if isinstance(progress.get("payload"), dict) else {},
                )
                return
            record_agent_run_action(server, str(run.get("run_id") or ""), progress)

        try:
            result = provider_envelope_completion(server, body, user=user, action_callback=emit_provider_event)
        except ProviderProxyError as exc:
            if not direct_head_provider_error_is_repairable_empty(exc):
                raise
            append_agent_run_event(
                server,
                str(run.get("run_id") or ""),
                "head.repair",
                summary="Retrying direct head after empty provider content",
                payload={"reason": "provider_empty_response", "receiver": receiver},
            )
            result = provider_envelope_completion(
                server,
                direct_head_empty_response_repair_body(body),
                user=user,
                action_callback=emit_provider_event,
            )
        parsed, result = master_frontier_repair.repair_structured_action(
            body=body,
            route_envelope=envelope,
            receiver=receiver,
            result=result,
            completion=provider_envelope_completion,
            completion_kwargs={"server": server, "user": user, "action_callback": emit_provider_event},
            record_event=lambda summary, reason, extra: append_agent_run_event(server, str(run.get("run_id") or ""), "head.repair", summary=summary, payload={"reason": reason, **extra}),
        )
        parsed, result = direct_head_normalize_conceptual_result(envelope, parsed, result)
        parsed, result = direct_head_repo_object_answer_from_evidence(
            envelope,
            parsed,
            result,
            preflight_local_tool_results,
        )
        enforce_direct_head_structured_action(parsed, result.get("reply", ""), envelope)
        if not direct_head_has_runtime_entity_routes(envelope):
            enforce_kernel_before_unknown_answer(parsed)
        decision = clipped(str(parsed.get("decision") or parsed.get("answer") or result.get("reply") or "direct head replied"), 240)
        append_agent_run_event(
            server,
            str(run.get("run_id") or ""),
            "head.decision",
            summary=decision,
            payload={
                "decision": clipped(str(parsed.get("decision") or ""), 120),
                "actions": parsed.get("actions") if isinstance(parsed.get("actions"), list) else [],
                "needs": parsed.get("needs") if isinstance(parsed.get("needs"), list) else [],
                "confidence": parsed.get("confidence"),
            },
        )
        append_envelope_v2_events(
            server,
            str(run.get("run_id") or ""),
            master_frontier_envelope_v2.decision_events(
                parsed,
                result.get("reply", ""),
                envelope,
                turn_id=clipped(str(run.get("turn_id") or envelope.get("trace_id") or ""), 160),
                inference_id="head-1",
                stage="head",
            ),
        )
        append_envelope_v2_inference_usage(
            server,
            str(run.get("run_id") or ""),
            result=result,
            turn_id=clipped(str(run.get("turn_id") or envelope.get("trace_id") or ""), 160),
            inference_id="head-1",
            stage="head",
        )
        direct_action_tool_results = execute_direct_head_local_tool_actions(
            server,
            direct_head_local_tool_actions(parsed),
            envelope,
            user=user,
            run_id=str(run.get("run_id") or ""),
        )
        record_direct_head_local_tool_events(
            server,
            str(run.get("run_id") or ""),
            direct_action_tool_results,
            turn_id=clipped(str(run.get("turn_id") or envelope.get("trace_id") or ""), 160),
            inference_id="head-1",
        )
        local_tool_results = [
            *preflight_local_tool_results,
            *direct_action_tool_results,
        ]
        local_tool_results = ensure_direct_head_repo_object_probe(
            server,
            envelope,
            user=user,
            run_id=str(run.get("run_id") or ""),
            local_tool_results=local_tool_results,
        )
        local_tool_results = ensure_direct_head_repo_object_source_read(
            server,
            envelope,
            user=user,
            run_id=str(run.get("run_id") or ""),
            local_tool_results=local_tool_results,
        )
        local_tool_results = ensure_direct_head_repo_object_runtime_scope_preflight(
            server,
            envelope,
            user=user,
            run_id=str(run.get("run_id") or ""),
            local_tool_results=local_tool_results,
        )
        if not direct_head_conceptual_evidence_floor(envelope) and not direct_head_objective_is_implementation_intent(envelope):
            local_tool_results = ensure_direct_head_objective_runtime_entity_preflight(
                server,
                envelope,
                user=user,
                run_id=str(run.get("run_id") or ""),
                local_tool_results=local_tool_results,
            )
        parsed, result, local_tool_results = direct_head_continue_after_local_tools(
            server,
            body,
            envelope,
            receiver=receiver,
            user=user,
            run_id=str(run.get("run_id") or ""),
            parsed=parsed,
            result=result,
            local_tool_results=local_tool_results,
            action_callback=emit_provider_event,
        )
        dispatch_action = direct_head_hermes_dispatch_action(parsed)
        local_tool_results = ensure_direct_head_runtime_entity_preflight(
            server,
            dispatch_action,
            envelope,
            user=user,
            run_id=str(run.get("run_id") or ""),
            local_tool_results=local_tool_results,
        )
        if direct_head_local_runtime_proof_satisfies_dispatch(dispatch_action, envelope, local_tool_results):
            append_agent_run_event(
                server,
                str(run.get("run_id") or ""),
                "hermes.skipped",
                summary="Local runtime route proof satisfied dispatch request",
                payload={"reason": "local_runtime_proof_satisfied"},
            )
            dispatch_action = None
        dispatch_result = (
            execute_direct_head_hermes_dispatch(
                server,
                dispatch_action,
                envelope,
                user=user,
                run_id=str(run.get("run_id") or ""),
                local_tool_results=local_tool_results,
            )
            if dispatch_action
            else None
        )
        dispatch_result = maybe_repair_direct_head_completion_dispatch(
            server,
            envelope=envelope,
            user=user,
            run_id=str(run.get("run_id") or ""),
            dispatch_result=dispatch_result if isinstance(dispatch_result, dict) else None,
            local_tool_results=local_tool_results,
        )
        final_reply = dispatch_result.get("reply") if isinstance(dispatch_result, dict) else direct_head_answer_text(parsed, result.get("reply", ""))
        parsed, result = direct_head_repo_object_answer_from_evidence(
            envelope,
            parsed,
            result,
            local_tool_results,
        )
        if not dispatch_result:
            final_reply = direct_head_answer_text(parsed, result.get("reply", ""))
        final_reply = master_frontier_envelope.suppress_duplicate_answer_blocks(final_reply)
        stale_local_tool_answer = direct_head_answer_still_requests_local_tools(final_reply, local_tool_results)
        if not dispatch_result and (
            not final_reply.strip()
            or re.fullmatch(r"\s*dispatch(?:\.|\s+)hermes\.?\s*", final_reply, flags=re.IGNORECASE)
            or stale_local_tool_answer
        ):
            final_reply = direct_head_local_tool_summary_reply("" if stale_local_tool_answer else final_reply, local_tool_results)
        target_node = (dispatch_result or {}).get("target_node") or "direct-head"
        head_token_usage = token_usage_with_raw_usage(
            exact_llm_token_usage(
                result.get("usage"),
                source="direct_envelope",
                model=clipped(str(result.get("model") or ""), 180),
            ),
            result.get("raw_usage"),
        )
        bridge_token_usage = (dispatch_result or {}).get("usage") if isinstance(dispatch_result, dict) else None
        change_proof = direct_head_change_proof(
            server,
            user=user,
            before_tree=before_tree,
            after_tree=safe_worktree_tree_sha(server) if before_tree else "",
            target_node=target_node,
            objective=objective,
            space_id=space_id,
        )
        change_proof = direct_head_merge_local_change_proof(change_proof, local_tool_results)
        state_writeback = master_frontier_envelope.state_writeback_projection(
            envelope,
            parsed,
            final_reply,
            local_tool_results=local_tool_results,
            dispatch_result=dispatch_result if isinstance(dispatch_result, dict) else None,
        )
        loop_state = enforce_master_frontier_loop_completion(
            server,
            str(run.get("run_id") or ""),
            envelope,
            parsed,
            final_reply,
            local_tool_results=local_tool_results,
            change_proof=change_proof,
            dispatch_result=dispatch_result if isinstance(dispatch_result, dict) else None,
        )
        final = {
            "schema": "hermes.wasm_agent.direct_head_run.final.v1",
            "run_id": run.get("run_id"),
            "turn_id": run.get("turn_id"),
            "route_id": route_contract.get("route_id"),
            "route_contract": route_contract,
            "reply": final_reply,
            "provider": {k: v for k, v in result.items() if k not in {"envelope_text"}},
            "local_tools": local_tool_results,
            "hermes_dispatch": dispatch_result,
            "diagnostics": {
                "source": "direct_head_hermes_dispatch" if dispatch_result else "direct_envelope",
                "mode": "direct-head",
                "target_node": target_node,
                "route_id": route_contract.get("route_id"),
                "route_contract": route_contract,
                "context_measurement": result.get("context_measurement") or measurement,
                "dispatch_context_measurement": (dispatch_result or {}).get("context_measurement"),
                "local_tool_results": local_tool_results,
                "bridge_trace": (dispatch_result or {}).get("bridge_trace"),
                "token_usage": head_token_usage,
                "token_usage_head": head_token_usage,
                "token_usage_head_components": result.get("usage_components") if isinstance(result.get("usage_components"), list) else [],
                "token_usage_bridge": bridge_token_usage,
                "state_feedback": parsed.get("state_feedback") if isinstance(parsed, dict) and isinstance(parsed.get("state_feedback"), dict) else {},
                "model_reflection": parsed.get("model_reflection") if isinstance(parsed, dict) and isinstance(parsed.get("model_reflection"), dict) else {},
                "state_writeback": state_writeback,
                "self_check": master_frontier_envelope.self_check_projection(envelope, parsed, final_reply, local_tool_results=local_tool_results),
                "changed_files_complete": True,
                "master_frontier_loop": loop_state,
                "before_checkpoint": change_proof.get("before_checkpoint"),
                "auto_checkpoint": change_proof.get("auto_checkpoint"),
            },
            "changed_files": change_proof.get("changed_files") or [],
            "context_preview": [{"tool": "direct_envelope", "preview": semantic_envelope[:1200]}],
            "actions": [
                {
                    "id": "direct_envelope",
                    "topic": "run-api",
                    "kind": "api",
                    "label": "Direct envelope",
                    "status": "done",
                    "detail": decision,
                    "meta": "admin direct-head",
                }
            ] + bridge_trace_action_events((dispatch_result or {}).get("bridge_trace")) + direct_head_change_actions(change_proof),
            "proof": [
                "route-used:/agent/provider/envelope/stream",
                f"receiver:{receiver}",
                f"target-node:{target_node}",
                f"local-tools:{len(local_tool_results)}",
            ],
        }
        enforce_direct_head_goal_completion(
            server,
            str(run.get("run_id") or ""),
            envelope,
            change_proof,
            dispatch_result if isinstance(dispatch_result, dict) else None,
        )
        record_agent_run_final_proof_events(server, str(run.get("run_id") or ""), final)
        finish_agent_run(server, str(run.get("run_id") or ""), status="completed", final=final)
        return {
            **result,
            "reply": final_reply,
            "hermes_dispatch": dispatch_result,
            "run": run,
            "run_id": run.get("run_id"),
            "turn_id": run.get("turn_id"),
        }
    except ProviderProxyError as exc:
        fallback = direct_head_runtime_entity_transport_fallback(
            server,
            body=body,
            user=user,
            run=run,
            envelope=envelope,
            route_contract=route_contract,
            semantic_envelope=semantic_envelope,
            measurement=measurement,
            receiver=receiver,
            before_tree=before_tree,
            objective=objective,
            space_id=space_id,
            error=exc,
        )
        if fallback is not None:
            return fallback
        finish_agent_run(server, str(run.get("run_id") or ""), status="failed", error={"code": exc.code, "message": exc.message})
        raise
    except Exception as exc:
        finish_agent_run(server, str(run.get("run_id") or ""), status="failed", error={"code": "direct_envelope_error", "message": str(exc)})
        raise
