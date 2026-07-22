#!/usr/bin/env python3
"""Master:frontier V5 adapter for the canonical safe-lab fixture task."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ADAPTER_SERVER = Path("/adapter/plugins/wasm-agent/server")
SOURCE = Path("/source")


class ProviderFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def provider_result(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    calls = []
    for index, item in enumerate(message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []):
        if not isinstance(item, dict):
            continue
        function = item.get("function") if isinstance(item.get("function"), dict) else item
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        name = str(function.get("name") or item.get("name") or "").strip()
        if name:
            calls.append({"id": str(item.get("id") or f"call_{index + 1}"), "name": name, "arguments": arguments if isinstance(arguments, dict) else {}})
    return {
        "reply": str(message.get("content") or "").strip(),
        "tool_calls": calls,
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
        "finish_reason": str(choice.get("finish_reason") or ""),
    }


def route_contract(task: dict[str, Any]) -> dict[str, Any]:
    if task.get("schema") == "wasm-agent.safe-lab.implementation-task.v1":
        route = task.get("route")
        if not isinstance(route, dict) or route.get("workspace_root") != "/workspace/repo":
            raise RuntimeError("implementation task lacks its bounded workspace route")
        return route
    variant_path = Path("/adapter/variant-contract.json")
    variant = json.loads(variant_path.read_text(encoding="utf-8")) if variant_path.is_file() else {}
    request_class = str((task.get("fixture") or {}).get("requestClass") or "")
    task_contract = {
        "request_class": request_class,
        "objective_kind": request_class,
        "strategy": str(variant.get("strategy") or "minimal_class_allowlist"),
        "declared_classes": [request_class],
        "completion_mode": "direct" if request_class in {"conversation", "general_conversation"} else "tool_loop",
        "proof_policy": "none" if request_class in {"conversation", "general_conversation"} else "grounded",
        "required_capabilities": [] if request_class in {"conversation", "general_conversation"} else ["inspect"],
        "evidence_requirements": [] if request_class in {"conversation", "general_conversation"} else ["grounded"],
        "execution_profile": "answer_only" if request_class in {"conversation", "general_conversation"} else "grounded",
        "authority_source": "declared_task_contract",
        "context_profile": "direct" if request_class in {"conversation", "general_conversation"} else "natural_tool_loop",
    }
    return {
        "route_id": "safe-lab.fixture.replay",
        "owner": "safe-lab",
        "workspace_root": str(SOURCE),
        "allowed_read_roots": [str(SOURCE)],
        "allowed_write_roots": ["/workspace"],
        "source_index": {
            "include_roots": ["."],
            "exclude_globs": ["**/.git/**", "**/node_modules/**", "**/__pycache__/**", "**/*.sqlite*", "**/*.db"],
            "max_file_bytes": 262144,
            "max_total_bytes": 8000000,
        },
        "caps": ["repo.read", "runtime.inspect.unavailable"],
        "task_digest": str(task.get("taskDigest") or ""),
        "task_contract": task_contract,
        "runtime_identity": {"model": os.environ.get("FRONTIER_MODEL", "")},
    }


def validate_environment(task: dict[str, Any]) -> tuple[str, str, int, int]:
    endpoint = os.environ.get("FRONTIER_ENDPOINT", "").strip().rstrip("/")
    token = os.environ.get("OPENAI_API_KEY", "")
    if task.get("schema") not in {
        "wasm-agent.safe-lab.fixture-task.v1", "wasm-agent.safe-lab.implementation-task.v1",
    } or not task.get("taskDigest"):
        raise RuntimeError("invalid digest-bound fixture task")
    if os.environ.get("FRONTIER_MODEL") != "frank/GLM-5.2":
        raise RuntimeError("exact model contract missing")
    if not endpoint or not token:
        raise RuntimeError("run-scoped broker endpoint or token missing")
    budgets = task.get("budgets") if isinstance(task.get("budgets"), dict) else {}
    maximum = min(8192, max(256, int(budgets.get("maxOutputTokensPerCall") or 1024)))
    timeout = min(180, max(1, int(budgets.get("providerCallTimeoutSeconds") or budgets.get("wallClockSeconds") or 180)))
    return endpoint, token, maximum, timeout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    task = json.loads(Path(args.task).read_text(encoding="utf-8"))
    endpoint, token, maximum, timeout = validate_environment(task)
    sys.path.insert(0, str(ADAPTER_SERVER))
    from master_frontier import repository_state  # noqa: PLC0415
    from master_frontier.v5 import context, loop, policy, tools, trajectory  # noqa: PLC0415
    from master_frontier.v5.errors import V5Error  # noqa: PLC0415

    objective = str(task.get("prompt") or task.get("objective") or "").strip()
    if not objective:
        raise SystemExit("fixture prompt missing")
    route = route_contract(task)
    state = trajectory.new(
        f"lab-{task['taskDigest'][:20]}", f"turn-{task['taskDigest'][:20]}", objective, str(route["route_id"]),
    )

    def complete(messages: list[dict[str, str]], _index: int) -> dict[str, Any]:
        queued = state.get("queued_tool_calls") if isinstance(state.get("queued_tool_calls"), list) else []
        if queued:
            call, state["queued_tool_calls"] = queued[0], queued[1:]
            return {"reply": "", "tool_calls": [call], "usage": {}, "_mf5_replayed_tool_call": True}
        payload: dict[str, Any] = {
            "model": "glm-5.2", "messages": messages, "max_tokens": maximum, "stream": False,
        }
        if not context.completion_only(state, route):
            payload.update({"tools": policy.active_provider_tools(route, state), "tool_choice": "auto", "parallel_tool_calls": False})
        request = urllib.request.Request(
            endpoint + "/chat/completions", data=json.dumps(payload, separators=(",", ":")).encode(), method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ProviderFailure("provider_response_too_large", "Broker response exceeded the adapter bound.")
                payload_out = json.loads(raw)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8", "replace"))
            except (ValueError, OSError):
                detail = {}
            code = str(detail.get("error") or f"provider_http_{exc.code}") if isinstance(detail, dict) else f"provider_http_{exc.code}"
            raise ProviderFailure(code, f"Broker rejected the V5 inference: {code}.") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderFailure("network-timeout", "Broker inference timed out.") from exc
        if not isinstance(payload_out, dict):
            raise ProviderFailure("provider_output_invalid", "Broker response was not an object.")
        return provider_result(payload_out)

    implementation_actions = None
    if task.get("schema") == "wasm-agent.safe-lab.implementation-task.v1":
        os.environ["HERMES_WASM_AGENT_REPOSITORY_TRANSACTION_DIR"] = "/workspace/.mf5-transactions"
        sys.path.insert(0, "/adapter/labs/wasm-agent")
        from implementation_lab_actions import ImplementationLabActions  # noqa: PLC0415
        implementation_actions = ImplementationLabActions(route)

    events_path = Path(os.environ.get("WASM_AGENT_EVENTS_PATH", ""))

    def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if implementation_actions is not None:
            observed = tools.execute(name, arguments, route, invoke=implementation_actions.invoke)
            if events_path.is_absolute():
                event = {
                    "kind": name, "status": "ok" if observed.get("ok") else "failed", "tool": name,
                    "path": arguments.get("path"),
                    "argumentsDigest": hashlib.sha256(json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                    "summary": observed.get("summary"), "changedFiles": observed.get("changed_files"),
                }
                with events_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, separators=(",", ":")) + "\n")
            return observed
        return tools.execute(
            name, arguments, route,
            invoke=lambda _tool, _arguments: {
                "ok": False,
                "code": "capability_unavailable",
                "summary": "Live runtime inspection is not available in the immutable replay lab.",
            },
        )

    try:
        outcome = loop.run(
            objective, route, state, complete=complete, execute=execute,
            verify_worktree=lambda ledger: repository_state.verify(route, ledger.get("postimages") or {}),
        )
    except V5Error as exc:
        print(json.dumps({"code": exc.code, "message": str(exc)}, separators=(",", ":")), file=sys.stderr)
        return 1
    print(outcome.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
