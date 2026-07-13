from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from . import completion, context, policy, trajectory
from .errors import V5Error


@dataclass
class Outcome:
    answer: str
    trajectory: dict[str, Any]
    calls: int
    tools: list[dict[str, Any]]
    usages: list[dict[str, Any]]


def normalize(result: dict[str, Any]) -> dict[str, Any]:
    calls = result.get("tool_calls") if isinstance(result.get("tool_calls"), list) else []
    if calls and isinstance(calls[0], dict):
        call = calls[0]
        name = str(call.get("name") or "")
        arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
        if name and policy.allowed(name): return {"kind": "tool", "tool": name, "arguments": arguments}
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


def run(objective: str, route: dict[str, Any], state: dict[str, Any], *, complete: Callable[[list[dict[str, str]], int], dict[str, Any]], execute: Callable[[str, dict[str, Any]], dict[str, Any]]) -> Outcome:
    calls = 0; invalid = 0; no_progress = 0; transient_retries = 0; tools: list[dict[str, Any]] = []; usages: list[dict[str, Any]] = []
    while True:
        try: result = complete(context.messages(objective, route, state), calls + 1)
        except Exception as exc:
            code = str(getattr(exc, "code", "provider_failed"))
            if code == "network-timeout" and transient_retries < 1:
                transient_retries += 1
                assessment = completion.assess(state)
                state["completion_assessment"] = assessment
                if assessment["status"] == "sufficient":
                    state["pending"] = "frontier_completion"
                state["last_error"] = {"code": code, "message": "Provider timed out; retrying once without discarding accumulated evidence."}
                trajectory.append(state, {"kind": "system", "status": "retry", "summary": "Transient provider timeout; retrying once.", "result": assessment})
                continue
            raise V5Error(str(getattr(exc, "code", "provider_failed")), str(exc), checkpoint=trajectory.checkpoint(state, str(getattr(exc, "code", "provider_failed")), str(exc))) from exc
        calls += 1
        if isinstance(result.get("usage"), dict): usages.append(result["usage"])
        decision = normalize(result)
        if decision["kind"] == "final":
            state.update({"status": "completed", "pending": None, "last_error": None, "final_answer": decision["answer"]})
            return Outcome(decision["answer"], state, calls, tools, usages)
        if decision["kind"] == "invalid":
            invalid += 1
            if invalid >= 2: raise V5Error("model_output_invalid", "Frontier returned malformed decisions twice.", checkpoint=trajectory.checkpoint(state, "model_output_invalid", "Frontier returned malformed decisions twice."))
            state["last_error"] = {"code": "model_output_invalid", "message": "Return one declared tool call or final answer JSON object."}
            continue
        name, arguments = decision["tool"], decision["arguments"]
        action_id = trajectory.action_id(name, arguments)
        if action_id in state["completed_actions"]:
            no_progress += 1
            if state.get("pending") == "frontier_completion":
                raise V5Error("no_semantic_progress", "Frontier requested a tool during completion-only synthesis.", checkpoint=trajectory.checkpoint(state, "no_semantic_progress", "Completion-only synthesis requested a tool."))
            prior = state["completed_actions"][action_id]
            assessment = completion.assess(state)
            state["completion_assessment"] = assessment
            trajectory.append(state, {"kind": "system", "tool": name, "status": "duplicate", "summary": "Equivalent completed action reused.", "result": prior})
            if assessment["status"] == "sufficient":
                state["pending"] = "frontier_completion"
                state["last_error"] = {"code": "action_already_completed", "message": f"Do not repeat {name}. Answer now from the accumulated evidence."}
                continue
            if assessment["status"] == "incomplete" and no_progress < 2:
                state["last_error"] = {"code": "evidence_incomplete", "message": assessment["reason"], "next_actions": assessment["next_actions"]}
                continue
            raise V5Error("evidence_incomplete", assessment["reason"], checkpoint=trajectory.checkpoint(state, "evidence_incomplete", assessment["reason"]))
        observed = execute(name, arguments); tools.append(observed)
        compact = {key: observed.get(key) for key in ("ok", "code", "summary", "focus", "path", "start_line", "end_line", "truncated", "content", "limitations") if observed.get(key) not in (None, "")}
        if isinstance(observed.get("matches"), list):
            compact["matches"] = [
                {**{key: item.get(key) for key in ("path", "line", "symbol") if item.get(key) not in (None, "")}, "excerpt": str(item.get("excerpt") or "")[:320]}
                for item in observed["matches"][:8] if isinstance(item, dict)
            ]
        state["completed_actions"][action_id] = compact
        trajectory.append(state, {"kind": "tool", "action_id": action_id, "tool": name, "status": "completed" if observed.get("ok") else "failed", "summary": observed.get("summary") or observed.get("code") or name, "result": compact})
        if observed.get("ok"):
            state["last_error"] = None
            no_progress = 0
        else:
            no_progress += 1
        if no_progress >= 2: raise V5Error("no_semantic_progress", "Two tool decisions produced no useful progress.", checkpoint=trajectory.checkpoint(state, "no_semantic_progress", "Two tool decisions produced no useful progress."))
