"""Shared provider-call port for model-led Master:frontier controllers."""
from __future__ import annotations

import os
from typing import Any


DIRECT_RECEIVERS = frozenset({"openai-responses", "openai-codex"})
V6_PROVIDER_SCHEMA = "hermes.wasm_agent.master_frontier.v6.provider.v1"
V6_MAX_ENVELOPE_CHARS = 128_000


def direct_envelope_limit(envelope: dict[str, Any], legacy_limit: int) -> int:
    """Size the provider projection by protocol, never by a token-spend quota."""
    if str(envelope.get("schema") or "") == V6_PROVIDER_SCHEMA:
        return V6_MAX_ENVELOPE_CHARS
    return max(1, int(legacy_limit))


def complete(
    runtime: dict[str, Any], server: Any, body: dict[str, Any], envelope: dict[str, Any],
    proxy_body: dict[str, Any], *, protocol: str, receiver: str, run_id: str,
    user: dict[str, Any] | None,
) -> dict[str, Any]:
    if os.environ.get("HERMES_WASM_AGENT_FRONTIER_PROVIDER", "").strip() == "codex_subscription":
        from codex_subscription_provider import complete as codex_subscription_complete

        declared_tools = proxy_body.get("tools") if isinstance(proxy_body.get("tools"), list) else []
        return codex_subscription_complete(
            proxy_body.get("messages") if isinstance(proxy_body.get("messages"), list) else [],
            declared_tools,
            completion_only=not declared_tools,
            require_tool=str(proxy_body.get("tool_choice") or "").strip().lower() == "required",
            timeout=max(1, round(float(proxy_body.get("_timeout_sec") or 90))),
            model=(
                os.environ.get("MASTER_FRONTIER_CODEX_MODEL", "").strip()
                or os.environ.get("MF5_CODEX_MODEL", "").strip()
                or os.environ.get("WASM_AGENT_CODEX_MODEL", "").strip()
                or "gpt-5.6-luna"
            ),
            session_key=str(body.get("session_id") or run_id),
            route_id=str(envelope.get("route_id") or ""),
        )
    if receiver not in DIRECT_RECEIVERS:
        return runtime["provider_proxy_completion"](server, proxy_body, user=user)
    common = {
        "schema": f"hermes.wasm_agent.master_frontier.{protocol}.provider.v1",
        "objective": str(envelope.get("objective") or body.get("message") or ""),
        "route_id": envelope.get("route_id"),
    }
    if protocol == "v6":
        step_envelope = {
            "schema": common["schema"],
            "compact_state": {"messages": proxy_body.get("messages") or []},
            "objective": common["objective"], "route_id": common["route_id"],
        }
    else:
        step_envelope = {
            **common, "route_contract": envelope.get("route_contract"),
            "compact_state": {
                "messages": proxy_body.get("messages") or [], "tools": proxy_body.get("tools") or [],
                "tool_choice": proxy_body.get("tool_choice") or "",
            },
        }
    step_envelope["constraints"] = [
        f"Follow the compact {protocol.upper()} messages exactly.",
        "Return a direct answer or the requested structured tool decision; do not invent tool results.",
    ]
    step_body = {
        **body, "envelope": step_envelope, "llm_envelope": step_envelope,
        "tools": proxy_body.get("tools") or [], "tool_choice": proxy_body.get("tool_choice") or "auto",
        "parallel_tool_calls": False,
    }
    if proxy_body.get("max_tokens") is not None:
        step_body["max_output_tokens"] = proxy_body["max_tokens"]
    return runtime["openai_responses_completion"](
        server, step_body, step_envelope, run_id=run_id, user=user,
    )
