from __future__ import annotations

import hashlib
from typing import Any

from .v5 import context as v5_context, loop, policy, tools, trajectory
from .v5.errors import V5Error


def execute_owned(server: Any, body: dict[str, Any], *, user: dict[str, Any] | None, run_record: dict[str, Any], context: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    envelope = context["envelope"]
    route = dict(runtime["require_direct_envelope_route_contract"](envelope))
    declared_task = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    route["task_contract"] = {
        "objective_kind": str(envelope.get("objective_kind") or declared_task.get("objective_kind") or ""),
        "request_class": str(declared_task.get("request_class") or ""),
    }
    run_id = str(run_record.get("run_id") or ""); turn_id = str(run_record.get("turn_id") or run_id)
    objective = str(envelope.get("objective") or body.get("message") or "")
    receiver = str(context.get("receiver") or "provider")
    state = trajectory.restore(body.get("resume_checkpoint"), run_id=run_id, turn_id=turn_id, objective=objective, route_id=str(route.get("route_id") or ""))
    runtime["append_agent_run_event"](server, run_id, "envelope.created", summary=objective[:180], payload={"protocol": "v5", "trajectory": {"schema": state["schema"], "status": state["status"]}})
    runtime["append_agent_run_event"](server, run_id, "route.resolved", summary=str(route.get("route_id") or ""), payload={"protocol": "v5", "route_contract": route})

    def complete(messages: list[dict[str, str]], index: int) -> dict[str, Any]:
        inference_id = hashlib.sha256(f"{run_id}:{index}".encode()).hexdigest()
        runtime["append_agent_run_event"](server, run_id, "llm.inference.started", summary=f"decision {index}", payload={"protocol": "v5", "inference_id": inference_id})
        proxy_body = {**body, "provider_config": runtime["provider_config_for_proxy_body"](body), "messages": messages}
        if not v5_context.completion_only(state, route):
            proxy_body.update({"tools": policy.provider_tools(), "tool_choice": "auto"})
        proxy_body.pop("max_output_tokens", None); proxy_body.pop("max_tokens", None)
        result = runtime["provider_proxy_completion"](server, proxy_body, user=user)
        runtime["append_envelope_v2_inference_usage"](server, run_id, result=result, turn_id=turn_id, inference_id=inference_id, stage="v5.loop")
        runtime["record_agent_run_token_usage_event"](server, run_id, {"route_id": route.get("route_id"), "usage": result.get("usage")})
        return result

    def invoke(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        runtime["append_agent_run_event"](server, run_id, "command.started", summary=name, payload={"protocol": "v5", "arguments": runtime["direct_envelope_redact"](arguments)})
        if name == "kernel.inspect":
            result = runtime["kernel_inspect_tool"](server, {**arguments, "route_id": route.get("route_id"), "route_contract": route}, user)
        else:
            result = {"ok": False, "code": "tool_adapter_missing", "summary": name}
        return result

    def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = tools.execute(name, arguments, route, invoke=invoke)
        runtime["append_agent_run_event"](server, run_id, "evidence.received" if result.get("ok") else "command.failed", summary=str(result.get("summary") or result.get("code") or name), payload={"protocol": "v5", "tool": name, "result": runtime["direct_envelope_redact"](result)})
        return result

    try:
        outcome = loop.run(objective, route, state, complete=complete, execute=execute_tool)
    except V5Error as exc:
        runtime["append_agent_run_event"](server, run_id, "gate.decision", summary=exc.code, payload={"protocol": "v5", "status": "resumable", "checkpoint": exc.checkpoint})
        runtime["finish_agent_run"](server, run_id, status="interrupted", error={"code": exc.code, "message": str(exc), "resume_checkpoint": exc.checkpoint})
        runtime["direct_envelope_error"](exc.code, str(exc), runtime["HTTPStatus"].CONFLICT)
        raise
    files_read = sorted({str(item.get("path")) for item in outcome.tools if item.get("path")})
    final = {"schema": "hermes.wasm_agent.master_frontier.final.v5", "protocol": "v5", "run_id": run_id, "turn_id": turn_id, "route_id": route.get("route_id"), "reply": outcome.answer, "trajectory": outcome.trajectory, "diagnostics": {"verification_level": "source" if files_read else "route", "provider_calls": outcome.calls, "files_read": files_read, "token_usage": outcome.usages}, "changed_files": [], "local_tools": outcome.tools}
    runtime["append_agent_run_event"](server, run_id, "gate.decision", summary="accepted", payload={"protocol": "v5", "verification_level": final["diagnostics"]["verification_level"]})
    runtime["finish_agent_run"](server, run_id, status="completed", final=final)
    return {**final, "run": run_record}
