from __future__ import annotations

import hashlib
from typing import Any

from . import authority, budget, provider_step, repository_state, route_contracts, run_control, session_context, tool_runtime
from .v5 import context_accounting, continuity, context as v5_context, decision_record, loop, operation_ledger, policy, proof, task_lineage, task_policy, trajectory, verification_answer
from .v5.errors import V5Error

def _provider_complete(
    runtime: dict[str, Any], server: Any, body: dict[str, Any], envelope: dict[str, Any],
    proxy_body: dict[str, Any], *, receiver: str, run_id: str, user: dict[str, Any] | None,
) -> dict[str, Any]:
    return provider_step.complete(
        runtime, server, body, envelope, proxy_body, protocol="v5",
        receiver=receiver, run_id=run_id, user=user,
    )


def _typed_tool_failure(exc: Exception) -> dict[str, Any] | None:
    code = str(getattr(exc, "code", "") or "").strip()
    if not code:
        return None
    message = str(getattr(exc, "message", "") or str(exc) or code).strip()
    return {"ok": False, "code": code, "summary": message}


def _provider_timeout_sec(route: dict[str, Any], state: dict[str, Any]) -> float:
    return budget.provider_call_ms(route) / 1000


def _apply_default_decision_mode(route: dict[str, Any]) -> dict[str, Any]:
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    if task_policy.request_class(route) == "implementation" and not str(contract.get("decision_mode") or "").strip():
        contract["decision_mode"] = "llm_autonomous"
        route["task_contract"] = contract
    return route


def _resume_requested(checkpoint: Any, continuation: dict[str, Any]) -> bool:
    return bool(checkpoint) or str(continuation.get("previous_status") or "") in {"interrupted", "cancelled"}


def _token_usage_total(usages: list[dict[str, Any]], *, attempts: int) -> dict[str, Any]:
    metered = [item for item in usages if isinstance(item, dict)]
    return {
        "exact": (
            attempts == len(metered)
            and all(budget.usage_tokens(item) is not None for item in metered)
        ),
        "total_tokens": budget.provider_tokens_used(metered),
        "calls": max(0, int(attempts)),
        "metered_calls": len(metered),
    }


def execute_owned(server: Any, body: dict[str, Any], *, user: dict[str, Any] | None, run_record: dict[str, Any], context: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    envelope = context["envelope"]
    receiver = str(context.get("receiver") or "provider")
    route = dict(runtime["require_direct_envelope_route_contract"](envelope))
    run_id = str(run_record.get("run_id") or ""); turn_id = str(run_record.get("turn_id") or run_id)
    objective = str(envelope.get("objective") or body.get("message") or "")
    session_id = str(body.get("session_id") or "")
    principal = str(runtime["user_id"](user))
    route_id = str(route.get("route_id") or "")
    resolved_entity = route_contracts.resolve_entity(objective, route)
    if resolved_entity:
        route["resolved_entity"] = resolved_entity
    memory_manifest = session_context.load_memory_manifest(
        runtime["auth_connect"], user_id=principal, active_session_id=session_id,
    )
    if memory_manifest:
        route["session_memory"] = memory_manifest
        route["caps"] = list(dict.fromkeys([*(route.get("caps") or []), authority.SESSION_MEMORY_READ]))
    continuation_context = continuity.continuation_context(envelope)
    recent_context = session_context.load_recent(
        runtime["auth_connect"],
        session_id=session_id,
        turn_id=turn_id,
        user_id=principal,
    )
    previous_run_id = str(continuation_context.get("previous_run_id") or "")
    lineage_parent = session_context.load_lineage_parent(
        runtime["auth_connect"], previous_run_id=previous_run_id,
        session_id=session_id, user_id=principal,
    )
    if lineage_parent and not any(item.get("run_id") == previous_run_id for item in recent_context):
        recent_context.append(lineage_parent)
    projected_contract = authority.project_task_contract(envelope, route)
    if memory_manifest and isinstance(projected_contract.get("authority"), list):
        projected_contract["authority"] = list(dict.fromkeys([
            *projected_contract["authority"], authority.SESSION_MEMORY_READ,
        ]))
    route["task_contract"] = task_lineage.project(
        projected_contract,
        objective=objective,
        session_context=recent_context,
        route_caps=route.get("caps") if isinstance(route.get("caps"), list) else [],
        route_id=route_id,
        continuation_context=continuation_context,
    )
    _apply_default_decision_mode(route)
    authority_status = authority.coherence(route)
    if authority_status.get("ok") is not True:
        code = str(authority_status.get("code") or "task_contract_incoherent")
        message = f"V5 task authority is incoherent: {code}."
        runtime["direct_envelope_error"](code, message, runtime["HTTPStatus"].CONFLICT)
        raise V5Error(code, message)
    route_digest = continuity.contract_digest(route)
    route["session_context"] = recent_context
    requested_checkpoint = continuity.request_checkpoint(body, envelope)
    resume_requested = _resume_requested(requested_checkpoint, continuation_context)
    resume = session_context.load_resume(
        runtime["auth_connect"], previous_run_id=previous_run_id,
        session_id=session_id, user_id=principal,
    ) if previous_run_id and resume_requested else {}
    server_checkpoint = resume.get("checkpoint") if isinstance(resume.get("checkpoint"), dict) else None
    if requested_checkpoint and not previous_run_id:
        message = "A V5 checkpoint must name its server-owned source run."
        runtime["direct_envelope_error"]("resume_checkpoint_source_required", message, runtime["HTTPStatus"].CONFLICT)
        raise continuity.ContinuityError("resume_checkpoint_source_required", message)
    if resume_requested and previous_run_id and server_checkpoint is None:
        message = "No server-owned V5 checkpoint exists for that prior run."
        runtime["direct_envelope_error"]("resume_checkpoint_not_found", message, runtime["HTTPStatus"].CONFLICT)
        raise continuity.ContinuityError("resume_checkpoint_not_found", message)
    if isinstance(requested_checkpoint, dict) and requested_checkpoint.get("schema") == continuity.SCHEMA:
        if str(requested_checkpoint.get("sha256") or "") != str((server_checkpoint or {}).get("sha256") or ""):
            message = "The browser checkpoint does not match the server-owned run lineage."
            runtime["direct_envelope_error"]("resume_checkpoint_lineage_mismatch", message, runtime["HTTPStatus"].CONFLICT)
            raise continuity.ContinuityError("resume_checkpoint_lineage_mismatch", message)
    stale_checkpoint_replaced = False
    if server_checkpoint is not None:
        expected_scope = continuity.binding(user_id=principal, session_id=session_id, route_id=route_id, route_digest=route_digest)
        try:
            state = continuity.restore(
                server_checkpoint, expected_scope=expected_scope, previous_run_id=previous_run_id,
                run_id=run_id, turn_id=turn_id, objective=objective, route_id=route_id,
                allow_legacy=server_checkpoint.get("schema") == trajectory.SCHEMA,
            )
        except continuity.ContinuityError as exc:
            if exc.code != "resume_checkpoint_scope_mismatch":
                runtime["direct_envelope_error"](exc.code, str(exc), runtime["HTTPStatus"].CONFLICT)
                raise
            try:
                state = continuity.replace_stale_route_checkpoint(
                    server_checkpoint, expected_scope=expected_scope, previous_run_id=previous_run_id,
                    run_id=run_id, turn_id=turn_id, objective=objective, route_id=route_id,
                )
            except continuity.ContinuityError as replacement_error:
                runtime["direct_envelope_error"](
                    replacement_error.code, str(replacement_error), runtime["HTTPStatus"].CONFLICT,
                )
                raise
            stale_checkpoint_replaced = True
            route["task_contract"] = task_lineage.project(
                projected_contract,
                objective=str(state.get("root_objective") or objective),
                session_context=recent_context,
                route_caps=route.get("caps") if isinstance(route.get("caps"), list) else [],
                route_id=route_id,
                continuation_context=continuation_context,
            )
            _apply_default_decision_mode(route)
            replacement_authority = authority.coherence(route)
            if replacement_authority.get("ok") is not True:
                code = str(replacement_authority.get("code") or "task_contract_incoherent")
                message = f"V5 replacement task authority is incoherent: {code}."
                runtime["direct_envelope_error"](code, message, runtime["HTTPStatus"].CONFLICT)
                raise V5Error(code, message)
            route_digest = continuity.contract_digest(route)
        for evidence_step in [] if stale_checkpoint_replaced else resume.get("evidence_steps") or []:
            if isinstance(evidence_step, dict):
                evidence_step = {**evidence_step, "result": trajectory.compact_observation(evidence_step.get("result"))}
                trajectory.append(state, evidence_step)
                action_id = str(evidence_step.get("action_id") or "")
                already_completed = bool(action_id and action_id in state["completed_actions"])
                if not already_completed:
                    state["operation_ledger"] = operation_ledger.record(
                        state.get("operation_ledger") or {},
                        str(evidence_step.get("tool") or ""),
                        evidence_step.get("result") if isinstance(evidence_step.get("result"), dict) else {},
                        action_id=action_id,
                    )
                if action_id:
                    state["completed_actions"][action_id] = {
                        "tool": str(evidence_step.get("tool") or ""),
                        "observation": trajectory.receipt(evidence_step.get("result")),
                    }
                    pending = state.get("pending_action") if isinstance(state.get("pending_action"), dict) else {}
                    if pending.get("action_id") == action_id:
                        state["pending_action"] = None
    else:
        task_contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
        lineage = task_contract.get("lineage") if isinstance(task_contract.get("lineage"), dict) else {}
        root_objective = str(lineage.get("root_objective") or objective)
        state = trajectory.new(run_id, turn_id, root_objective, route_id)
    route["resume_context"] = continuity.model_projection(state, {
        **continuation_context,
        "previous_status": resume.get("previous_status") or continuation_context.get("previous_status"),
    })
    runtime["append_agent_run_event"](server, run_id, "envelope.created", summary=objective[:180], payload={"protocol": "v5", "trajectory": {"schema": state["schema"], "status": state["status"]}})
    runtime["append_agent_run_event"](server, run_id, "route.resolved", summary=str(route.get("route_id") or ""), payload={"protocol": "v5", "route_contract": route})

    def persist_state(current: dict[str, Any], reason: str) -> dict[str, Any]:
        checkpoint = continuity.create(current, scope=continuity.binding(
            user_id=principal, session_id=session_id, route_id=route_id, route_digest=route_digest,
            source_run_id=run_id, source_turn_id=turn_id,
        ))
        runtime["append_agent_run_event"](
            server, run_id, "state.writeback", summary=reason[:180],
            payload={"protocol": "v5", "reason": reason[:80], "checkpoint": checkpoint},
        )
        return checkpoint

    if stale_checkpoint_replaced:
        persist_state(state, "stale_checkpoint_replaced")

    persist_state(state, "run_started")

    context_fingerprints: set[str] = set()

    def complete(messages: list[dict[str, str]], index: int) -> dict[str, Any]:
        nonlocal context_fingerprints
        queued = state.get("queued_tool_calls") if isinstance(state.get("queued_tool_calls"), list) else []
        if queued:
            call, state["queued_tool_calls"] = queued[0], queued[1:]
            return {"reply": "", "tool_calls": [call], "usage": {}, "_mf5_replayed_tool_call": True}
        inference_id = hashlib.sha256(f"{run_id}:{index}".encode()).hexdigest()
        runtime["append_agent_run_event"](server, run_id, "llm.inference.started", summary=f"decision {index}", payload={"protocol": "v5", "inference_id": inference_id})
        proxy_body = {**body, "provider_config": runtime["provider_config_for_proxy_body"](body), "messages": messages}
        proxy_body["_timeout_sec"] = _provider_timeout_sec(route, state)
        if not v5_context.completion_only(state, route):
            proxy_body.update({"tools": policy.active_provider_tools(route, state), "tool_choice": policy.provider_tool_choice(state), "parallel_tool_calls": False})
        proxy_body.pop("max_output_tokens", None); proxy_body.pop("max_tokens", None)
        context_measurement, context_fingerprints = context_accounting.measure(proxy_body, context_fingerprints)
        output_remaining = budget.output_tokens_remaining(
            route, state.get("usage_totals") if isinstance(state.get("usage_totals"), dict) else state.get("usages"),
            request_payload={
                "messages": proxy_body.get("messages") or [],
                "tools": proxy_body.get("tools") or [],
                "tool_choice": proxy_body.get("tool_choice") or proxy_body.get("toolChoice") or "",
                "response_format": proxy_body.get("response_format") or proxy_body.get("responseFormat") or {},
            },
        )
        if output_remaining is not None:
            if output_remaining <= 0:
                raise V5Error("provider_token_budget_exhausted", "No routed provider-token budget remains.")
            proxy_body["max_tokens"] = output_remaining
        result = _provider_complete(
            runtime, server, body, envelope, proxy_body,
            receiver=receiver, run_id=run_id, user=user,
        )
        runtime["append_agent_run_event"](
            server, run_id, "llm.context.measured", summary=f"decision {index} context",
            payload={"protocol": "v5", "inference_id": inference_id, **context_accounting.attach_usage(context_measurement, result.get("usage"))},
        )
        runtime["append_envelope_v2_inference_usage"](server, run_id, result=result, turn_id=turn_id, inference_id=inference_id, stage="v5.loop")
        runtime["record_agent_run_token_usage_event"](server, run_id, {"route_id": route.get("route_id"), "usage": result.get("usage")})
        return result

    def invoke(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        runtime["append_agent_run_event"](server, run_id, "command.started", summary=name, payload={"protocol": "v5", "action_id": arguments.get("action_id"), "arguments": runtime["direct_envelope_redact"](arguments)})
        if name == "kernel.inspect":
            result = runtime["kernel_inspect_tool"](server, {**arguments, "route_id": route.get("route_id"), "route_contract": route}, user)
        elif name == "kernel.act":
            result = runtime["kernel_act_tool"](server, {**arguments, "run_id": run_id, "route_id": route.get("route_id"), "route_contract": route}, user)
        elif name == "kernel.prove":
            result = runtime["kernel_prove_tool"](server, {**arguments, "run_id": run_id, "session_id": body.get("session_id"), "turn_id": turn_id, "route_id": route.get("route_id"), "route_contract": route}, user)
        else:
            result = {"ok": False, "code": "tool_adapter_missing", "summary": name}
        return result

    def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        pending = state.get("pending_action") if isinstance(state.get("pending_action"), dict) else {}
        action_id = str(pending.get("action_id") or trajectory.action_id(name, arguments, route_id))
        try:
            result = tool_runtime.execute_v5(
                name, arguments, route, server=server, user=user, runtime=runtime,
                principal=principal, action_id=action_id, invoke_kernel=invoke,
            )
        except Exception as exc:
            result = _typed_tool_failure(exc)
            if result is None:
                raise
        durable_result = trajectory.compact_observation(
            runtime["direct_envelope_redact"](result), content_limit=12_000, max_chars=18_000,
        )
        event_payload = {"protocol": "v5", "action_id": action_id, "tool": name, "result": durable_result}
        if result.get("ok") is not True:
            event_payload["arguments"] = trajectory.compact_observation(
                runtime["direct_envelope_redact"](arguments), content_limit=1200, max_chars=1800,
            )
        runtime["append_agent_run_event"](server, run_id, "evidence.received" if result.get("ok") else "command.failed", summary=str(result.get("summary") or result.get("code") or name), payload=event_payload)
        return result

    try:
        outcome = loop.run(
            objective, route, state, complete=complete, execute=execute_tool, persist=persist_state,
            verify_worktree=lambda ledger: repository_state.verify(route, ledger.get("postimages") or {}),
            cancelled=lambda: run_control.requested(run_id),
        )
    except V5Error as exc:
        checkpoint = persist_state(exc.checkpoint, "interrupted")
        runtime["append_agent_run_event"](server, run_id, "gate.decision", summary=exc.code, payload={"protocol": "v5", "status": "resumable", "checkpoint_sha256": checkpoint["sha256"]})
        terminal_status = "cancelled" if exc.code == "agent_run_cancelled" else "interrupted"
        runtime["finish_agent_run"](server, run_id, status=terminal_status, error={"code": exc.code, "message": str(exc), "resume_checkpoint": checkpoint})
        runtime["direct_envelope_error"](exc.code, str(exc), runtime["HTTPStatus"].CONFLICT)
        raise
    operations = operation_ledger.normalize(outcome.trajectory.get("operation_ledger"), route_id=route_id)
    proof_summary = proof.summarize(outcome.trajectory.get("steps") or [], operations)
    answer = (
        verification_answer.build(proof_summary, outcome.tools)
        if task_policy.request_class(route) == "verification"
        and proof_summary.get("verification_level") == "proof"
        else outcome.answer
    )
    final = {
        "schema": "hermes.wasm_agent.master_frontier.final.v5",
        "protocol": "v5",
        "run_id": run_id,
        "turn_id": turn_id,
        "route_id": route.get("route_id"),
        "reply": answer,
        "decision": decision_record.project((outcome.trajectory.get("executive") or {}).get("decision")),
        "trajectory": trajectory.summary(outcome.trajectory),
        "diagnostics": {
            **proof_summary,
            "answer_satisfaction": outcome.trajectory.get("answer_satisfaction"),
            "provider_calls": outcome.calls,
            "provider_attempts": outcome.attempts,
            "token_usage": outcome.usages,
            "token_usage_total": {
                "exact": outcome.usage_totals["metered_calls"] == outcome.calls,
                "total_tokens": outcome.usage_totals["total_tokens"],
                "calls": outcome.attempts,
                "metered_calls": outcome.usage_totals["metered_calls"],
            },
            "budget": {
                "provider": budget.provider_token_diagnostics(route, outcome.usage_totals),
                "calls": budget.api_call_diagnostics(
                    route, outcome.usages, calls_used=outcome.attempts,
                ),
            },
        },
        "changed_files": proof_summary["changed_files"],
        "local_tools": outcome.tools,
    }
    satisfaction = outcome.trajectory.get("answer_satisfaction") if isinstance(outcome.trajectory.get("answer_satisfaction"), dict) else {}
    gate_summary = "accepted" if satisfaction.get("status") != "unsatisfactory" else "completed_unsatisfactory"
    runtime["append_agent_run_event"](server, run_id, "gate.decision", summary=gate_summary, payload={"protocol": "v5", "answer_satisfaction": satisfaction.get("status"), "verification_level": final["diagnostics"]["verification_level"], "changed_file_count": len(final["changed_files"])})
    finished = runtime["finish_agent_run"](server, run_id, status="completed", final=final) or {}
    integrity_proof = finished.get("integrity_proof") if isinstance(finished, dict) else None
    return {
        **final,
        "run": run_record,
        **({"integrity_proof": integrity_proof} if isinstance(integrity_proof, dict) else {}),
    }
