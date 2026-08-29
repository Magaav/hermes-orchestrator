"""Hosted Master:frontier V6 controller over trusted server-owned ports."""
from __future__ import annotations

import hashlib
from typing import Any

from . import authority, budget, client_ui_actions, provider_step, run_control, tool_runtime
from .v5 import continuity
from .v6 import capability_routing, client_topology, controller, execution_profiles, kernel, mcp_host, performance, persistence, procedure_memory, reasoning, stall_diagnostic, state as working_state, trajectory, v5_bridge


class V6Error(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


STALL_FIXTURE_ID = "v6_no_semantic_progress"


def _debug_stall_error(body: dict[str, Any]) -> controller.ControllerError | None:
    if str(body.get("debug_fixture") or "") != STALL_FIXTURE_ID:
        return None
    return controller.ControllerError(
        STALL_FIXTURE_ID,
        phase="debug_fixture",
        missing=["completion:repo.read"],
    )


def _completion_requirements(envelope: dict[str, Any], route: dict[str, Any]) -> set[str]:
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    declared = envelope.get("completion_capabilities")
    if not isinstance(declared, list):
        declared = contract.get("completion_capabilities") if isinstance(contract.get("completion_capabilities"), list) else None
    if declared is not None:
        return {str(item) for item in declared[:24] if str(item).strip()}
    request_class = authority.request_class(route)
    if request_class == "implementation":
        return {"repo.patch", "repo.test", "repo.diff", "repo.prove"}
    if request_class == "verification":
        return {"repo.test", "repo.diff", "repo.prove"}
    if request_class in {"source_investigation", "implementation_planning"}:
        return {"authority:repo.read"}
    if request_class == "client_action":
        return {"goal_action"}
    if request_class in {"client_state", "runtime_inspection"}:
        return {"authority:client.ui.inspect"}
    return set()


def _usage_total(usages: list[dict[str, Any]], attempts: int) -> dict[str, Any]:
    metered = [item for item in usages if isinstance(item, dict) and budget.usage_tokens(item) is not None]
    result = {
        "exact": len(metered) == attempts, "total_tokens": budget.provider_tokens_used(metered),
        "calls": attempts, "metered_calls": len(metered),
    }
    latest = metered[-1] if metered else {}
    for key in (
        "model", "context_window_tokens", "rate_limits", "status_telemetry",
        "provider_thread_id", "provider_thread_turn", "provider_thread_resumed",
        "provider_thread_fork_reason", "provider_compaction_generation",
        "provider_compaction_status", "stable_context_mode", "stable_context_reused",
    ):
        if latest.get(key) is not None:
            result[key] = latest[key]
    return result


def _changed_files(journal: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []

    def visit(value: Any, depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(value, dict):
            changed = value.get("changed_files")
            if isinstance(changed, list):
                for item in changed[:80]:
                    path = str(item.get("path") if isinstance(item, dict) else item or "").strip()
                    if path and path not in found:
                        found.append(path)
            for item in value.values():
                visit(item, depth + 1)
        elif isinstance(value, list):
            for item in value[:80]:
                visit(item, depth + 1)

    for entry in journal:
        visit((entry.get("receipt") or {}).get("observed"))
    return found[:80]


def execute_owned(
    server: Any, body: dict[str, Any], *, user: dict[str, Any] | None,
    run_record: dict[str, Any], context: dict[str, Any], runtime: dict[str, Any],
) -> dict[str, Any]:
    perf = performance.Trace(started_monotonic=body.get("_master_frontier_started_monotonic"))
    envelope = context["envelope"]
    receiver = str(context.get("receiver") or "provider")
    route = dict(runtime["require_direct_envelope_route_contract"](envelope))
    route["task_contract"] = authority.project_task_contract(envelope, route)
    try:
        execution_profile = execution_profiles.resolve(route)
    except execution_profiles.ProfileError as exc:
        code = str(exc)
        runtime["direct_envelope_error"](code, code, runtime["HTTPStatus"].CONFLICT)
        raise V6Error(code, code) from exc
    completion_requirements = _completion_requirements(envelope, route)
    conceptual_turn = str(route["task_contract"].get("evidence_floor") or "") == "conceptual"
    answer_only = (
        authority.request_class(route) in {"conversation", "general_conversation"}
        and conceptual_turn
        and not completion_requirements
    )
    coherence = authority.coherence(route)
    if coherence.get("ok") is not True:
        code = str(coherence.get("code") or "task_contract_incoherent")
        message = f"V6 task authority is incoherent: {code}."
        runtime["direct_envelope_error"](code, message, runtime["HTTPStatus"].CONFLICT)
        raise V6Error(code, message)
    run_id = str(run_record.get("run_id") or "")
    turn_id = str(run_record.get("turn_id") or run_id)
    principal = str(runtime["user_id"](user))
    session_id = str(body.get("session_id") or "")
    objective = str(envelope.get("objective") or body.get("message") or "")
    compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    raw_history = compact_state.get("transcript") if isinstance(compact_state.get("transcript"), list) else []
    history_limit = int(execution_profile["history_turns"])
    history = [
        {"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")[:600]}
        for item in (raw_history[-history_limit:] if history_limit else []) if isinstance(item, dict)
        and str(item.get("role") or "") in {"user", "assistant"}
        and str(item.get("content") or "").strip()
    ]
    granted = set(authority.effective(route))
    route_caps = {str(item) for item in (route.get("caps") or [])}
    if authority.CLIENT_UI_INSPECT in granted and authority.CLIENT_UI_CONTROL in route_caps:
        granted.add(authority.CLIENT_UI_CONTROL)
    mcp_catalog = runtime.get("master_frontier_mcp_catalog")
    mcp_call = runtime.get("master_frontier_mcp_call")
    mcp_declared = bool((route.get("mcp") or {}).get("servers")) if isinstance(route.get("mcp"), dict) else False
    if mcp_declared and (not callable(mcp_catalog) or not callable(mcp_call)):
        code = "v6_mcp_host_missing"
        runtime["direct_envelope_error"](code, "The route declares MCP tools but no MCP host port is installed.", runtime["HTTPStatus"].CONFLICT)
        raise V6Error(code, code)
    try:
        manifests = mcp_catalog(server, user, route) if callable(mcp_catalog) else []
        mcp_bindings = mcp_host.compile(route, manifests if isinstance(manifests, list) else [])
    except Exception as exc:
        code = str(getattr(exc, "code", "") or "v6_mcp_catalog_failed")
        message = str(exc)[:500] or code
        runtime["direct_envelope_error"](code, message, runtime["HTTPStatus"].CONFLICT)
        raise V6Error(code, message) from exc
    granted.update(str(item["capability"]["authority"]) for item in mcp_bindings)

    def append(event_type: str, summary: str, payload: dict[str, Any]) -> None:
        runtime["append_agent_run_event"](
            server, run_id, event_type, summary=summary[:500], payload={"protocol": "v6", **payload},
        )

    run_trajectory = trajectory.create(
        run_id=run_id, route_id=str(route.get("route_id") or ""),
    )

    def trajectory_sink(event: dict[str, Any]) -> None:
        append("trajectory.event", str(event.get("kind") or "trajectory"), {"trajectory_event": event})

    trajectory.append(
        run_trajectory, kind="run.started", source="host.controller",
        payload={"goal_sha256": trajectory.contracts.digest(objective), "profile": execution_profile["id"]},
        sink=trajectory_sink,
    )

    append("envelope.created", objective[:180], {"route_id": route.get("route_id")})
    append("route.resolved", str(route.get("route_id") or ""), {"route_contract": route})

    def commentary_sink(update: dict[str, Any]) -> None:
        append("llm.reason.summary", str(update.get("message") or ""), {"commentary": update})

    def operation_event(event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type == "operation.started":
            append("command.started", str(event.get("capability") or "operation"), {"operation_event": event})
        else:
            ok = event.get("ok") is True or event_type == "operation.replayed"
            append("evidence.received" if ok else "command.failed", str(event.get("capability") or event_type), {"operation_event": event})

    agent = kernel.Kernel(
        authorities=granted, commentary_sink=commentary_sink, event_sink=operation_event,
        completion_requirements=completion_requirements,
        cancel_event=run_control.event(run_id),
    )

    def invoke_kernel(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "kernel.inspect":
            return runtime["kernel_inspect_tool"](server, {**arguments, "route_id": route.get("route_id"), "route_contract": route}, user)
        if name == "kernel.act":
            return runtime["kernel_act_tool"](server, {**arguments, "run_id": run_id, "route_id": route.get("route_id"), "route_contract": route}, user)
        if name == "kernel.prove":
            return runtime["kernel_prove_tool"](server, {**arguments, "run_id": run_id, "session_id": body.get("session_id"), "turn_id": turn_id, "route_id": route.get("route_id"), "route_contract": route}, user)
        return {"ok": False, "code": "tool_adapter_missing", "summary": name}

    def invoke_v5(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        action_id = "v6:" + hashlib.sha256(f"{name}:{arguments}".encode()).hexdigest()[:24]
        try:
            return tool_runtime.execute_v5(
                name, arguments, route, server=server, user=user, runtime=runtime,
                principal=principal, action_id=action_id, invoke_kernel=invoke_kernel,
            )
        except Exception as exc:
            code = str(getattr(exc, "code", "") or "tool_execution_error")
            return {"ok": False, "code": code, "summary": str(exc)[:500]}

    v5_bridge.register_repository(agent, invoke_v5, route=route)
    clients_payload = runtime["native_control_clients_payload"](server) if authority.CLIENT_UI_INSPECT in granted else {}
    clients = clients_payload.get("clients") if isinstance(clients_payload.get("clients"), list) else []
    live_clients = [item for item in clients if isinstance(item, dict) and item.get("live") is True]
    active_client_manifest: dict[str, Any] = {}
    active_client_topology: dict[str, Any] = {}
    if live_clients:
        client_ui_contract = route.get("client_ui") if isinstance(route.get("client_ui"), dict) else {}
        required_client_caps = {
            client_ui_actions.CAPABILITIES[operation]
            for operation in (client_ui_contract.get("operations") or [])
            if operation in client_ui_actions.CAPABILITIES
        }
        manifests = [client_ui_actions.surface_manifest(item, client_ui_contract) for item in live_clients]
        selected = client_topology.primary(manifests, required_client_caps)
        topology = client_topology.projection(manifests, selected)
        active_client_manifest = selected
        active_client_topology = topology
        ordered = [selected, *(item for item in manifests if item is not selected)]
        v5_bridge.register_clients(agent, ordered, invoke_v5, topology=topology, topology_summary=client_topology.summary(topology))
    if mcp_bindings and callable(mcp_call):
        mcp_host.register(agent, mcp_bindings, lambda server_id, tool, args: mcp_call(server, user, route, server_id, tool, args))

    check_ids = [
        str(item.get("id") or "") for item in (route.get("checks") or [])[:24]
        if isinstance(item, dict) and str(item.get("id") or "")
    ]
    edit_operations = [str(item) for item in (route.get("allowed_edit_operations") or [])[:8]]
    initial_state: dict[str, Any] | None = None
    initial_discovered: set[str] = set()
    continuation_context = continuity.continuation_context(envelope)
    checkpoint_value = continuation_context.get("resume_checkpoint") if isinstance(continuation_context.get("resume_checkpoint"), dict) else {}
    previous_run_id = str(continuation_context.get("previous_run_id") or checkpoint_value.get("source_run_id") or "")
    previous_status = str(continuation_context.get("previous_status") or "")
    should_resume = bool(previous_run_id and (
        checkpoint_value.get("schema") == persistence.REF_SCHEMA
        or previous_status in {"interrupted", "cancelled"}
    ))
    if should_resume:
        try:
            saved = persistence.load(
                runtime["auth_connect"], user_id=principal, session_id=session_id, route=route,
                source_run_id=previous_run_id, expected_sha256=str(checkpoint_value.get("sha256") or ""),
            )
            initial_state = agent.restore(saved.get("kernel") if isinstance(saved.get("kernel"), dict) else {})
            initial_discovered = {str(item) for item in (saved.get("discovered") or [])}
            objective = str(initial_state.get("goal") or objective)
            parent_trajectory = saved.get("trajectory") if isinstance(saved.get("trajectory"), dict) else None
            if parent_trajectory:
                trajectory.verify(parent_trajectory)
                run_trajectory["parent"] = {
                    "run_id": str(parent_trajectory.get("run_id") or previous_run_id),
                    "head": str(parent_trajectory.get("head") or ""),
                    "count": int(parent_trajectory.get("count") or 0),
                }
            trajectory.append(
                run_trajectory, kind="run.resumed", source="checkpoint",
                payload={"source_run_id": previous_run_id, "source_head": str((parent_trajectory or {}).get("head") or "")},
                sink=trajectory_sink,
            )
            append("state.writeback", "resumed V6 checkpoint", {"source_run_id": previous_run_id})
        except persistence.PersistenceError as exc:
            runtime["direct_envelope_error"](exc.code, str(exc), runtime["HTTPStatus"].CONFLICT)
            raise V6Error(exc.code, str(exc)) from exc
    elif authority.request_class(route) in {"client_action", "client_state", "runtime_inspection"}:
        initial_discovered.update(capability_routing.initial_client_capabilities(
            agent.catalog, topology=active_client_topology,
        ))
    if agent.catalog.get("client.environment.inspect") is not None:
        initial_discovered.add("client.environment.inspect")
    if authority.request_class(route) == "model_decision":
        initial_discovered.update(
            str(item.get("id") or "")
            for item in agent.catalog.all().values()
            if str(item.get("authority") or "") == authority.REPO_READ
            and str(item.get("kind") or "") == "observe"
            and str(item.get("mode") or "") == "read"
        )

    route_evidence = agent.evidence.put(
        kind="route.contract", subject=f"route:{route.get('route_id')}",
        summary=(
            f"Route {route.get('route_id')}; registered checks: {','.join(check_ids) or 'none'}; "
            f"allowed edits: {','.join(edit_operations) or 'none'}."
        ),
        detail={"route_id": route.get("route_id"), "checks": check_ids, "allowed_edit_operations": edit_operations},
    )
    prior_terminal = None
    if conceptual_turn:
        assistant_content = next((item["content"] for item in reversed(history) if item["role"] == "assistant"), "")
        prior_terminal = persistence.latest_terminal_evidence(
            runtime["auth_connect"], user_id=principal, session_id=session_id,
            route_id=str(route.get("route_id") or ""), exclude_run_id=run_id,
            assistant_content=assistant_content,
        )
        if prior_terminal:
            proof_summary = ", ".join(prior_terminal["proof"][:8])
            agent.evidence.put(
                kind="prior.terminal_result", subject=f"run:{prior_terminal['run_id']}",
                summary=(
                    f"Verified prior terminal result (historical; proof: {proof_summary}): "
                    f"{prior_terminal['reply']} Display visibility and inspection availability are independent; "
                    "a hidden surface does not invalidate its verified inspection data. This terminal result proves "
                    "the inspection capability was available for that observation. A follow-up may distinguish "
                    "historical from current state, but must not deny the verified prior inspection or its capability."
                ),
                detail=prior_terminal, proof=prior_terminal["proof"],
            )

    usages: list[dict[str, Any]] = []
    provider_attempts = 0
    checkpoint_ref: dict[str, Any] = {}

    def persist(current: dict[str, Any], discovered: set[str], reason: str) -> None:
        nonlocal checkpoint_ref
        checkpoint_started = perf.monotonic()
        trajectory.append(
            run_trajectory, kind="checkpoint.saved", source="host.checkpoint",
            payload={"reason": str(reason)[:80], "state_id": str(current.get("id") or ""), "discovered": len(discovered)},
            sink=trajectory_sink,
        )
        snapshot = {
            "schema": persistence.SNAPSHOT_SCHEMA, "kernel": agent.snapshot(current),
            "discovered": sorted(discovered), "reason": str(reason)[:80],
            "trajectory": trajectory.checkpoint(run_trajectory),
        }
        try:
            checkpoint_ref = persistence.save(
                runtime["auth_connect"], user_id=principal, session_id=session_id, route=route,
                run_id=run_id, turn_id=turn_id, snapshot=snapshot,
            )
        finally:
            perf.checkpoint_finished(checkpoint_started)
        append("state.writeback", str(reason), {"checkpoint": checkpoint_ref})

    initial_state = initial_state or working_state.initial(objective)
    new_evidence_ids = [
        str(item.get("id") or "") for item in agent.evidence.list()
        if str(item.get("id") or "") not in (initial_state.get("known") or [])
    ]
    if new_evidence_ids:
        initial_state = working_state.apply(initial_state, working_state.delta(initial_state, add_known=new_evidence_ids))
    persist(initial_state, initial_discovered, "run_started")

    procedure_status: dict[str, Any] = {}
    procedure_result: dict[str, Any] | None = None
    if procedure_memory.enabled() and not should_resume and authority.request_class(route) in {"client_state", "runtime_inspection"}:
        try:
            recalled = procedure_memory.lookup(
                runtime["auth_connect"], user_id=principal, route=route, objective=objective,
                topology=active_client_topology, catalog=agent.catalog,
            )
            if recalled:
                procedure_result = procedure_memory.replay(
                    runtime["auth_connect"], recalled, agent=agent, objective=objective,
                )
                procedure_status = {
                    "state": "replayed" if procedure_result else "pruned",
                    "objective_sha256": recalled["objective_sha256"],
                    "capability": recalled["capability_id"],
                }
                append("semantic.decision", "exact procedure replay", {"procedure_memory": procedure_status})
                if procedure_result:
                    append("gate.decision", "fresh procedure proof", {
                        "status": "terminal_result", "procedure_memory": procedure_status,
                    })
        except Exception as exc:
            procedure_status = {"state": "unavailable", "code": str(getattr(exc, "code", "") or type(exc).__name__)[:120]}
            append("semantic.decision", "procedure memory unavailable", {"procedure_memory": procedure_status})

    def provider_complete(
        messages: list[dict[str, str]], tools: list[dict[str, Any]], index: int, *,
        stage: str, tool_choice: str = "auto", max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        nonlocal provider_attempts
        provider_attempts += 1
        inference_id = hashlib.sha256(f"{run_id}:{stage}:{provider_attempts}".encode()).hexdigest()
        proxy_body = {
            **body, "provider_config": runtime["provider_config_for_proxy_body"](body),
            "messages": messages, "tools": tools, "tool_choice": tool_choice,
            "reasoning_effort": reasoning.effort(body.get("reasoning_effort") or body.get("reasoningEffort")),
            "parallel_tool_calls": False, "_timeout_sec": budget.provider_call_ms(route) / 1000,
        }
        if max_output_tokens is not None:
            proxy_body["max_tokens"] = max(1, int(max_output_tokens))
            proxy_body["max_output_tokens"] = max(1, int(max_output_tokens))
        provider_call = perf.provider_started(proxy_body, index)
        provider_ok = False
        try:
            result = provider_step.complete(
                runtime, server, body, envelope, proxy_body, protocol="v6",
                receiver=receiver, run_id=run_id, user=user,
            )
            provider_ok = True
        finally:
            perf.provider_finished(provider_call, ok=provider_ok)
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        usages.append(usage)
        runtime["append_envelope_v2_inference_usage"](
            server, run_id, result=result, turn_id=turn_id, inference_id=inference_id, stage=stage,
        )
        runtime["record_agent_run_token_usage_event"](
            server, run_id, {"route_id": route.get("route_id"), "usage": usage},
        )
        return result

    def complete(messages: list[dict[str, str]], tools: list[dict[str, Any]], index: int) -> dict[str, Any]:
        return provider_complete(messages, tools, index, stage="v6.loop")

    def loop_event(event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type == "llm.inference.started":
            append(event_type, f"decision {event.get('decision')}", event)
        elif event_type == "llm.context.measured":
            append("turn.usage.updated", f"decision {event.get('decision')} context measured", {"context": event})
        elif event_type == "trajectory.context":
            trajectory.append(
                run_trajectory, kind="context.projected", source="v6.context",
                payload=trajectory.context_payload(
                    event.get("messages") if isinstance(event.get("messages"), list) else [],
                    event.get("tools") if isinstance(event.get("tools"), list) else [],
                    decision=int(event.get("decision") or 0), profile=str(event.get("profile") or execution_profile["id"]),
                ), sink=trajectory_sink,
            )
        elif event_type == "trajectory.model":
            trajectory.append(
                run_trajectory, kind="model.completed", source="provider",
                payload={"decision": int(event.get("decision") or 0), "result": event.get("result") if isinstance(event.get("result"), dict) else {}},
                sink=trajectory_sink,
            )
        elif event_type == "decision.completed":
            append("semantic.decision", str(event.get("tool") or "decision"), event)
            trajectory.append(
                run_trajectory, kind="decision.completed", source="v6.controller",
                payload={key: value for key, value in event.items() if key != "type"}, sink=trajectory_sink,
            )
            if event.get("tool"):
                trajectory.append(
                    run_trajectory, kind="tool.completed", source=f"tool:{event.get('tool')}",
                    payload={key: value for key, value in event.items() if key != "type"}, sink=trajectory_sink,
                )
        elif event_type == "commentary":
            commentary_sink({
                "schema": "master.frontier.v6.commentary.v1", "authored_by": "model",
                "visibility": "public", "phase": "acting", "operation": str(event.get("tool") or ""),
                "message": str(event.get("message") or "")[:600],
            })
        elif event_type == "gate.decision":
            append("gate.decision", str(event.get("status") or "gate"), event)

    try:
        debug_stall = _debug_stall_error(body)
        if debug_stall is not None:
            append("gate.decision", STALL_FIXTURE_ID, {
                "status": "stalled", "fixture": STALL_FIXTURE_ID,
                "missing": debug_stall.missing,
            })
            raise debug_stall
        result = procedure_result or controller.run(
            objective, agent, complete, emit=loop_event,
            cancelled=lambda: run_control.requested(run_id),
            initial_state=initial_state, initial_discovered=initial_discovered,
            checkpoint=persist, history=history,
            tools=[] if answer_only else controller.TOOLS,
            max_decisions=budget.decision_limit(route, int(execution_profile["max_decisions"])),
            execution_profile=str(execution_profile["id"]),
            diagnostic_context={
                "route_id": route.get("route_id"), "surface": route.get("surface"),
                "active_client": active_client_manifest,
                "client_environment": active_client_topology,
            },
            final_contract_required=(
                str(route["task_contract"].get("finalization_contract") or "") == "claim_bound"
            ),
            evidence_floor=str(route["task_contract"].get("evidence_floor") or "route"),
        )
    except controller.ControllerError as exc:
        code = exc.code
        message = str(exc)
        if code == "v6_no_semantic_progress" and exc.diagnostic and exc.terminal:
            diagnostic_index = provider_attempts + 1
            diagnostic_messages = stall_diagnostic.messages(exc.diagnostic)
            append("llm.inference.started", "stall diagnostic", {
                "decision": diagnostic_index, "phase": "stall_diagnostic",
            })
            trajectory.append(
                run_trajectory, kind="context.projected", source="v6.stall_diagnostic",
                payload=trajectory.context_payload(
                    diagnostic_messages, [], decision=diagnostic_index, profile="stall_diagnostic",
                ), sink=trajectory_sink,
            )
            provider_failure = ""
            raw_diagnostic: dict[str, Any] = {}
            try:
                raw_diagnostic = provider_complete(
                    diagnostic_messages, [], diagnostic_index,
                    stage="v6.stall_diagnostic", tool_choice="none",
                    max_output_tokens=stall_diagnostic.MAX_OUTPUT_TOKENS,
                )
                trajectory.append(
                    run_trajectory, kind="model.completed", source="provider.stall_diagnostic",
                    payload={"decision": diagnostic_index, "result": raw_diagnostic}, sink=trajectory_sink,
                )
            except Exception as diagnostic_exc:
                provider_failure = str(getattr(diagnostic_exc, "code", "") or "stall_diagnostic_provider_failed")[:160]
            synthesized = stall_diagnostic.interpret(
                raw_diagnostic, exc.diagnostic, failure_code=provider_failure,
            )
            diagnostic_event = {
                "decision": diagnostic_index, "phase": exc.phase,
                "missing": exc.missing, "model_valid": synthesized["model_valid"],
                "hypotheses": synthesized["hypotheses"], "next_check": synthesized["next_check"],
                **({"provider_error": provider_failure} if provider_failure else {}),
            }
            append("llm.inference.completed", "stall diagnostic", diagnostic_event)
            append("semantic.decision", "stall diagnostic closeout", diagnostic_event)
            append("gate.decision", "diagnostic closeout", {"status": "blocked", **diagnostic_event})
            trajectory.append(
                run_trajectory, kind="decision.completed", source="v6.stall_diagnostic",
                payload=diagnostic_event, sink=trajectory_sink,
            )
            result = {
                "ok": True, "schema": "master.frontier.v6.controller.v1",
                "answer": synthesized["answer"], "state": exc.terminal["state"],
                "trace": exc.terminal["trace"], "evidence": exc.terminal["evidence"],
                "diagnostic_closeout": {
                    "schema": synthesized["schema"], "phase": exc.phase,
                    "missing": exc.missing, "model_valid": synthesized["model_valid"],
                    "hypotheses": synthesized["hypotheses"], "next_check": synthesized["next_check"],
                    **({"provider_error": provider_failure} if provider_failure else {}),
                },
            }
        else:
            terminal_status = "cancelled" if code == "v6_run_cancelled" else "interrupted"
            trajectory.append(run_trajectory, kind="run.interrupted", source="host.controller", payload={"code": code, "phase": exc.phase, "missing": exc.missing}, sink=trajectory_sink)
            runtime["finish_agent_run"](server, run_id, status=terminal_status, error={
                "code": code, "message": message, "phase": exc.phase,
                "missing": exc.missing, "resume_checkpoint": checkpoint_ref,
            })
            runtime["direct_envelope_error"](code, message, runtime["HTTPStatus"].CONFLICT)
            raise V6Error(code, message) from exc
    except Exception as exc:
        code = str(getattr(exc, "code", "") or "v6_provider_interrupted")
        message = str(getattr(exc, "message", "") or str(exc) or code)[:500]
        trajectory.append(run_trajectory, kind="run.interrupted", source="host.controller", payload={"code": code, "message": message}, sink=trajectory_sink)
        runtime["finish_agent_run"](
            server, run_id, status="interrupted",
            error={"code": code, "message": message, "resume_checkpoint": checkpoint_ref},
        )
        runtime["direct_envelope_error"](code, message, runtime["HTTPStatus"].CONFLICT)
        raise V6Error(code, message) from exc

    journal = agent.journal()
    if procedure_memory.enabled() and provider_attempts > 0 and authority.request_class(route) in {"client_state", "runtime_inspection"}:
        try:
            observed_procedure = procedure_memory.observe_success(
                runtime["auth_connect"], user_id=principal, route=route, objective=objective,
                topology=active_client_topology, run_id=run_id, journal=journal, catalog=agent.catalog,
            )
            if observed_procedure:
                procedure_status = observed_procedure
                append("state.writeback", "procedure memory observed", {"procedure_memory": procedure_status})
        except Exception as exc:
            procedure_status = {"state": "unavailable", "code": str(getattr(exc, "code", "") or type(exc).__name__)[:120]}
            append("state.writeback", "procedure memory unavailable", {"procedure_memory": procedure_status})
    changed_files = _changed_files(journal)
    trajectory.append(run_trajectory, kind="run.completed", source="host.controller", payload={"answer_sha256": trajectory.contracts.digest(result["answer"]), "state_id": result["state"].get("id"), "evidence_count": len(result["evidence"])}, sink=trajectory_sink)
    final = {
        "schema": "hermes.wasm_agent.master_frontier.final.v6", "protocol": "v6",
        "run_id": run_id, "turn_id": turn_id, "route_id": route.get("route_id"),
        "reply": result["answer"], "state": result["state"], "evidence": result["evidence"],
        "diagnostics": {
            "provider_calls": provider_attempts, "provider_successes": len(usages), "token_usage": usages,
            "token_usage_total": _usage_total(usages, provider_attempts),
            "reasoning_effort": reasoning.effort(body.get("reasoning_effort") or body.get("reasoningEffort")),
            "context": [item.get("context") for item in result.get("trace") or []],
            "completion_gaps": [*agent.completion_gaps(), *[f"goal:{item.get('id')}" for item in result["state"].get("goals", []) if item.get("status") != "satisfied"]],
            "resume_checkpoint": checkpoint_ref,
            "performance": perf.snapshot(),
            "execution_profile": execution_profile,
            "procedure_memory": procedure_status,
            **({"final_claims": result["final_claims"]} if result.get("final_claims") else {}),
            "trajectory": {"head": run_trajectory["head"], "count": run_trajectory["count"], "parent": run_trajectory.get("parent")},
            **({"stall_diagnostic": result["diagnostic_closeout"]} if result.get("diagnostic_closeout") else {}),
        },
        "changed_files": changed_files,
        "local_tools": [{
            "operation": (item.get("operation") or {}).get("id"), "capability": item.get("capability"),
            "status": (item.get("receipt") or {}).get("state"), "ok": (item.get("receipt") or {}).get("ok"),
        } for item in journal],
    }
    append("answer.final", "answer complete", {
        "evidence_count": len(result["evidence"]),
        "claim_count": len((result.get("final_claims") or {}).get("claims") or []),
    })
    finished = runtime["finish_agent_run"](server, run_id, status="completed", final=final) or {}
    integrity = finished.get("integrity_proof") if isinstance(finished, dict) else None
    return {**final, "run": run_record, **({"integrity_proof": integrity} if isinstance(integrity, dict) else {})}
