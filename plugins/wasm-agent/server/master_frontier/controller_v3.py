from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import cyphers_v3
from . import envelope_v2
from . import proof_gate
from . import trace


@dataclass
class LoopOutcome:
    answer: str
    result: dict[str, Any]
    usages: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)


class V3LoopError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        usages: list[dict[str, Any]],
        history: list[dict[str, Any]],
        checkpoint: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.usages = usages
        self.history = history
        self.checkpoint = checkpoint or {}


def usage_components(result: dict[str, Any]) -> list[dict[str, Any]]:
    components = result.get("usage_components") if isinstance(result.get("usage_components"), list) else []
    if components:
        return [item for item in components if isinstance(item, dict)]
    return [result["usage"]] if isinstance(result.get("usage"), dict) else []


def action_signature(action: dict[str, Any]) -> str:
    args = action.get("args") if isinstance(action.get("args"), dict) else {}
    return json.dumps({"a": action.get("action"), "x": args}, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def normalize_scoped_action(action: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    normalized = {**action, "args": dict(action.get("args") or {})}
    args = normalized["args"]
    route = envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else {}
    root_text = str(route.get("workspace_root") or "").strip()
    root = Path(root_text).resolve() if root_text else None

    def relative_path(value: Any) -> Any:
        text = str(value or "").strip()
        if not text or not root:
            return value
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            return value
        try:
            return str(candidate.resolve().relative_to(root)).replace("\\", "/")
        except ValueError:
            return value

    if "path" in args:
        args["path"] = relative_path(args.get("path"))
    operations = args.get("operations") if isinstance(args.get("operations"), list) else []
    if operations:
        args["operations"] = [
            {**item, "path": relative_path(item.get("path"))}
            if isinstance(item, dict) and item.get("path")
            else item
            for item in operations
        ]
    return normalized


def run_loop(
    envelope: dict[str, Any],
    *,
    receiver: str,
    complete: Callable[[dict[str, Any], int], dict[str, Any]],
    execute: Callable[[dict[str, Any]], dict[str, Any]],
    on_inference: Callable[[int, dict[str, Any], str], None] | None = None,
    on_decision: Callable[[int, dict[str, Any]], None] | None = None,
    on_observation: Callable[[int, dict[str, Any], dict[str, Any]], None] | None = None,
) -> LoopOutcome:
    route = envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else {}
    route_id = str(envelope.get("route_id") or route.get("route_id") or "")
    usages: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    prompts: list[str] = []
    seen: set[str] = set()
    repaired_duplicates: set[str] = set()
    rejected_finals: set[str] = set()
    disabled_tools: dict[str, str] = {}
    disabled_attempts: dict[str, int] = {}
    failure_counts: dict[str, int] = {}
    invalid_repairs = 0

    def loop_error(code: str, message: str) -> V3LoopError:
        return V3LoopError(
            code,
            message,
            usages=usages,
            history=history,
            checkpoint=cyphers_v3.resume_checkpoint(envelope, history, code=code, calls_used=len(prompts)),
        )

    while True:
        step_envelope = cyphers_v3.with_history(envelope, history)
        prompt = cyphers_v3.bootstrap(step_envelope, receiver=receiver)
        admission = cyphers_v3.admission(envelope, usages, prompt, calls_used=len(prompts))
        if not admission["ok"]:
            raise loop_error(
                str(admission["code"]),
                f"C3 admission blocked call {len(prompts) + 1}: code={admission['code']} calls={len(prompts)}/{admission['absolute_calls']} used={admission['used']} input~={admission['estimated_input']} reserve={admission['reserve']} token_target={admission['total']}",
            )
        prompts.append(prompt)
        result = complete(step_envelope, len(prompts))
        call_usage = usage_components(result)
        usages.extend(call_usage)
        choice = cyphers_v3.decision(result, route_id=route_id)
        if on_inference:
            on_inference(len(prompts), result, prompt)
        if on_decision:
            on_decision(len(prompts), choice)
        if choice["kind"] == "final":
            answer = str(choice.get("answer") or "").strip()
            if not answer:
                raise loop_error("empty_answer", "C3 head returned neither an answer nor a semantic operation.")
            gate = proof_gate.evaluate_answer(envelope, history, answer)
            if not gate["ok"]:
                signature = json.dumps({"answer": answer, "missing": gate["missing"]}, sort_keys=True)
                if signature in rejected_finals:
                    raise loop_error(
                        "proof_gate_unsatisfied",
                        f"C3 head repeated a terminal answer without required proof: {','.join(gate['missing'])}",
                    )
                rejected_finals.add(signature)
                feedback = proof_gate.completion_feedback(gate)
                history.append(feedback)
                if on_observation:
                    on_observation(len(prompts), {"operation": "gate", "action": ""}, feedback)
                continue
            return LoopOutcome(answer=answer, result=result, usages=usages, tools=tools, history=history, prompts=prompts)
        if choice["kind"] == "invalid":
            if invalid_repairs >= 1:
                raise loop_error(
                    str(choice.get("code") or "cypher_action_invalid"),
                    "C3 head repeated tool-shaped output that does not resolve through the declared semantic operation registry.",
                )
            invalid_repairs += 1
            feedback = proof_gate.invalid_action_feedback()
            history.append(feedback)
            if on_observation:
                on_observation(len(prompts), {"operation": "gate", "action": ""}, feedback)
            continue
        action = normalize_scoped_action(
            choice.get("action") if isinstance(choice.get("action"), dict) else {},
            envelope,
        )
        signature = action_signature(action)
        if not action.get("action"):
            raise loop_error("cypher_action_invalid", "C3 head returned an unknown tool cypher.")
        if str(action.get("operation") or "") in proof_gate.MUTATION_OPERATIONS and not proof_gate.mutation_allowed(envelope):
            raise loop_error("mutation_not_authorized", "C3 rejected a mutating operation outside a declared implementation/proof objective.")
        tool_name = str(action.get("action") or "")
        if tool_name in disabled_tools:
            disabled_attempts[tool_name] = disabled_attempts.get(tool_name, 0) + 1
            if disabled_attempts[tool_name] > 1:
                raise loop_error("no_progress", f"C3 head repeated unavailable operation {action.get('operation') or tool_name}.")
            feedback = proof_gate.unavailable_tool_feedback(
                str(action.get("operation") or tool_name),
                disabled_tools[tool_name],
            )
            history.append(feedback)
            if on_observation:
                on_observation(len(prompts), action, feedback)
            continue
        if signature in seen:
            if signature in repaired_duplicates:
                raise loop_error("no_progress", "C3 head repeated an identical operation after typed no-progress feedback.")
            repaired_duplicates.add(signature)
            feedback = proof_gate.duplicate_feedback(str(action.get("operation") or action.get("action") or ""))
            history.append(feedback)
            if on_observation:
                on_observation(len(prompts), action, feedback)
            continue
        seen.add(signature)
        tool_result = execute(action)
        observed = cyphers_v3.observation(tool_result)
        tools.append(tool_result)
        history.append(cyphers_v3.history_item(action, observed))
        if on_observation:
            on_observation(len(prompts), action, observed)
        failure_code = str(observed.get("failure_code") or "")
        if failure_code in {"code_memory_stale", "code_memory_unavailable", "capability_missing"}:
            disabled_tools[tool_name] = failure_code
        if not observed.get("satisfying") and failure_code:
            failure_key = f"{tool_name}:{failure_code}"
            failure_counts[failure_key] = failure_counts.get(failure_key, 0) + 1
            if failure_counts[failure_key] >= 2:
                disabled_tools[tool_name] = failure_code


def _aggregate_usage(runtime: dict[str, Any], usages: list[dict[str, Any]], receiver: str, model: str = "") -> dict[str, Any] | None:
    normalize = runtime["normalize_token_usage"]
    token_int = runtime["token_int_value"]
    normalized = [normalize(item, source=str(item.get("source") or receiver)) for item in usages if isinstance(item, dict)]
    normalized = [item for item in normalized if item]
    if not normalized:
        return None
    return {
        "prompt_tokens": sum(int(token_int(item.get("prompt_tokens") or item.get("input_tokens")) or 0) for item in normalized),
        "completion_tokens": sum(int(token_int(item.get("completion_tokens") or item.get("output_tokens")) or 0) for item in normalized),
        "total_tokens": sum(int(token_int(item.get("total_tokens")) or 0) for item in normalized),
        "cached_input_tokens": sum(int(token_int(item.get("cached_input_tokens") or item.get("cache_read_tokens")) or 0) for item in normalized),
        "reasoning_tokens": sum(int(token_int(item.get("reasoning_output_tokens") or item.get("reasoning_tokens")) or 0) for item in normalized),
        "api_calls": len(normalized),
        "source": receiver,
        "model": model,
        "usage_scope": "llm_api_call",
        "usage_accuracy": "provider_exact",
        "billable": True,
    }


def execute_owned(
    server: Any,
    body: dict[str, Any],
    *,
    user: dict[str, Any] | None,
    run: dict[str, Any],
    context: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    envelope = context["envelope"]
    receiver = str(context.get("receiver") or "provider")
    run_id = str(run.get("run_id") or "")
    turn_id = str(run.get("turn_id") or envelope.get("trace_id") or run_id)[:160]
    route_contract = runtime["require_direct_envelope_route_contract"](envelope)
    before_tree = runtime["safe_worktree_tree_sha"](server)
    objective = str(envelope.get("objective") or body.get("message") or "direct envelope")
    space_id = runtime["safe_state_id"](str(body.get("space_id") or "home"), "home")
    first_prompt = cyphers_v3.bootstrap(envelope, receiver=receiver)
    first_measurement = runtime["compact_context_measurement"]("master-frontier-c3", first_prompt, baseline_text=runtime["direct_envelope_json"](envelope))
    runtime["append_agent_run_event"](server, run_id, "envelope.created", summary=runtime["clipped"](objective, 180), payload={
        "envelope": {"schema": cyphers_v3.SCHEMA, "cypher": "c3", "digest": cyphers_v3.registry_digest(), "objective": runtime["clipped"](objective, 500)},
        "context_measurement": first_measurement,
    })
    runtime["append_agent_run_event"](server, run_id, "route.resolved", summary=f"{route_contract.get('route_id')} -> {route_contract.get('owner')}", payload={
        "route_contract": route_contract,
        "map_summary": runtime["route_contract_summary"](route_contract),
    })
    runtime["append_agent_run_event"](server, run_id, "head.started", summary="C3 model-led execution started", payload={"context_measurement": first_measurement})

    def emit_provider_event(progress: dict[str, Any]) -> None:
        if progress.get("type") != "head.delta":
            runtime["record_agent_run_action"](server, run_id, progress)

    def complete(step_envelope: dict[str, Any], index: int) -> dict[str, Any]:
        step_body = dict(body)
        step_body["envelope"] = step_envelope
        step_body["max_output_tokens"] = cyphers_v3.budget_limits(envelope)["output"]
        runtime["append_envelope_v2_events"](server, run_id, envelope_v2.inference_started_events(
            turn_id=turn_id,
            inference_id=f"c3-{index}",
            stage="head" if index == 1 else "head.continued",
        ))
        if receiver in {"openai-responses", "openai-codex"}:
            return runtime["openai_responses_completion"](server, step_body, step_envelope, run_id=run_id, user=user, action_callback=emit_provider_event)
        return runtime["provider_envelope_completion"](server, step_body, user=user, action_callback=emit_provider_event)

    def execute(action: dict[str, Any]) -> dict[str, Any]:
        scoped_action = {**action, "args": dict(action.get("args") or {})}
        if str(scoped_action.get("operation") or "") == "cost":
            scoped_action["args"].setdefault("quest_id", str(body.get("session_id") or ""))
            scoped_action["args"].pop("run_id", None)
        try:
            results = runtime["execute_direct_head_local_tool_actions"](server, [scoped_action], envelope, user=user, run_id=run_id)
        except Exception as exc:
            return {
                "tool": scoped_action.get("action"),
                "ok": False,
                "code": str(getattr(exc, "code", "tool_execution_failed")),
                "error": {
                    "code": str(getattr(exc, "code", "tool_execution_failed")),
                    "message": str(getattr(exc, "message", exc)),
                },
            }
        if not results:
            return {"tool": action.get("action"), "ok": False, "error": {"code": "tool_result_missing"}}
        return results[0]

    persisted_usages: list[dict[str, Any]] = []

    def on_inference(index: int, result: dict[str, Any], _prompt: str) -> None:
        runtime["append_envelope_v2_inference_usage"](server, run_id, result=result, turn_id=turn_id, inference_id=f"c3-{index}", stage="head" if index == 1 else "head.continued")
        persisted_usages.extend(usage_components(result))
        runtime["record_agent_run_token_usage_event"](server, run_id, {
            "route_id": route_contract.get("route_id"),
            "diagnostics": {"token_usage_head_components": list(persisted_usages)},
        })
        choice = cyphers_v3.decision(result, route_id=str(route_contract.get("route_id") or ""))
        runtime["append_agent_run_event"](server, run_id, "llm.reason.summary", summary=f"inference {index} buffered", payload={
            "action": trace.inference_action(index, result, choice),
        })

    def on_decision(index: int, choice: dict[str, Any]) -> None:
        action = choice.get("action") if isinstance(choice.get("action"), dict) else {}
        kind = str(choice.get("kind") or "invalid")
        summary = f"tool:{action.get('operation') or action.get('action')}" if kind == "tool" else "answer" if kind == "final" else str(choice.get("code") or "invalid")
        payload = {
            "protocol": "c3", "index": index, "kind": kind, "operation": action.get("operation"), "tool": action.get("action"), "cypher": action.get("cypher"),
        }
        if kind == "tool":
            payload["action"] = trace.tool_action(index, action)
        runtime["append_agent_run_event"](server, run_id, "head.decision", summary=summary, payload=payload)

    def on_observation(index: int, action: dict[str, Any], observed: dict[str, Any]) -> None:
        event_type = "evidence.received" if observed.get("satisfying") else "evidence.missing"
        event_payload = {
            "protocol": "c3",
            "index": index,
            "operation": action.get("operation"),
            "tool": action.get("action"),
            "observation": {
                **{key: observed.get(key) for key in ("operation", "code", "status", "satisfying", "conclusive", "evidence_class", "count", "handle", "line", "model_line")},
                "detail": str(observed.get("detail") or "")[:4000],
            },
        }
        event_payload["action"] = (
            trace.tool_action(index, action, observed)
            if action.get("action")
            else trace.feedback_action(index, observed)
        )
        runtime["append_agent_run_event"](server, run_id, event_type, summary=str(observed.get("model_line") or observed.get("line") or "C3 observation"), payload=event_payload)

    try:
        outcome = run_loop(envelope, receiver=receiver, complete=complete, execute=execute, on_inference=on_inference, on_decision=on_decision, on_observation=on_observation)
    except V3LoopError as exc:
        aggregate = _aggregate_usage(runtime, exc.usages, receiver)
        checkpoint = {
            **exc.checkpoint,
            "previous_run_id": run_id,
            "previous_turn_id": turn_id,
            "resume_key": str(exc.checkpoint.get("resume_key") or f"{run_id}:{turn_id}"),
        }
        if aggregate:
            runtime["record_agent_run_token_usage_event"](server, run_id, {
                "route_id": route_contract.get("route_id"),
                "diagnostics": {"token_usage_head": aggregate, "token_usage_head_components": exc.usages},
            })
        runtime["append_agent_run_event"](server, run_id, "gate.decision", summary=exc.code, payload={
            "protocol": "c3",
            "status": "interrupted",
            "code": exc.code,
            "resume_checkpoint": checkpoint,
        })
        runtime["finish_agent_run"](server, run_id, status="interrupted", error={
            "code": exc.code,
            "message": str(exc),
            "resume_checkpoint": checkpoint,
        })
        runtime["direct_envelope_error"](exc.code, str(exc), runtime["HTTPStatus"].CONFLICT)
        raise

    aggregate = _aggregate_usage(runtime, outcome.usages, receiver, str(outcome.result.get("model") or ""))
    completion_gate = proof_gate.evaluate(envelope, outcome.history)
    change_proof = runtime["direct_head_change_proof"](
        server,
        user=user,
        before_tree=before_tree,
        after_tree=runtime["safe_worktree_tree_sha"](server),
        target_node="direct-head",
        objective=objective,
        space_id=space_id,
    )
    final = {
        "schema": "hermes.wasm_agent.master_frontier.final.v3",
        "run_id": run_id,
        "turn_id": run.get("turn_id"),
        "route_id": route_contract.get("route_id"),
        "route_contract": route_contract,
        "reply": outcome.answer,
        "provider": {**{key: value for key, value in outcome.result.items() if key not in {"envelope_text", "parsed", "usage_components"}}, "usage": aggregate},
        "local_tools": outcome.tools,
        "hermes_dispatch": None,
        "diagnostics": {
            "source": f"{receiver.replace('-', '_')}_c3",
            "mode": "model-led",
            "protocol": "c3",
            "cypher_digest": cyphers_v3.registry_digest(),
            "route_id": route_contract.get("route_id"),
            "route_contract": route_contract,
            "context_measurement": first_measurement,
            "context_measurements": [runtime["compact_context_measurement"](f"c3-{index}", prompt) for index, prompt in enumerate(outcome.prompts, start=1)],
            "cypher_history": outcome.history,
            "completion_gate": completion_gate,
            "runtime_verification_level": proof_gate.verification_level(completion_gate),
            "token_usage": aggregate,
            "token_usage_head": aggregate,
            "token_usage_head_components": outcome.usages,
            "changed_files_complete": True,
            "before_checkpoint": change_proof.get("before_checkpoint"),
            "auto_checkpoint": change_proof.get("auto_checkpoint"),
        },
        "changed_files": change_proof.get("changed_files") or [],
        "context_preview": [{"tool": "c3", "preview": first_prompt[:1200]}],
        "actions": runtime["direct_head_change_actions"](change_proof),
        "proof": [
            "protocol:c3",
            f"cypher:{cyphers_v3.registry_digest()}",
            f"route:{route_contract.get('route_id')}",
            f"head-calls:{len(outcome.usages)}",
            f"tools:{len(outcome.tools)}",
            f"verification:{proof_gate.verification_level(completion_gate)}",
        ],
    }
    runtime["append_agent_run_event"](server, run_id, "frontier.proof", summary=proof_gate.verification_level(completion_gate), payload={
        "protocol": "c3",
        "completion_gate": completion_gate,
        "proof_handles": [item.get("handle") for item in outcome.history if item.get("satisfying") and item.get("handle")],
        "changed_files": final["changed_files"],
    })
    runtime["append_envelope_v2_events"](server, run_id, [
        *envelope_v2.final_gate_events(turn_id=turn_id, status="finished", reason="c3_model_final", proof_refs=[item.get("handle") for item in outcome.history if item.get("handle")]),
        *envelope_v2.answer_events(turn_id=turn_id, answer=outcome.answer),
    ])
    runtime["record_agent_run_final_proof_events"](server, run_id, final)
    runtime["finish_agent_run"](server, run_id, status="completed", final=final)
    return {
        **outcome.result,
        "parsed": {"answer": outcome.answer, "decision": "answer", "actions": []},
        "reply": outcome.answer,
        "usage": aggregate,
        "usage_components": outcome.usages,
        "envelope_text": first_prompt,
        "hermes_dispatch": None,
        "run": run,
        "run_id": run_id,
        "turn_id": run.get("turn_id"),
    }
