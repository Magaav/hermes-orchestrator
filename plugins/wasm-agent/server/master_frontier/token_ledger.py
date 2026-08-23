from __future__ import annotations

from typing import Any, Callable


STATUS_KEYS = ("model", "context_window_tokens", "rate_limits", "status_telemetry")
CONTEXT_REUSE_KEYS = (
    "provider_thread_id", "provider_thread_turn", "provider_thread_resumed", "provider_thread_fork_reason",
    "provider_compaction_generation", "provider_compaction_status", "stable_context_mode", "stable_context_reused",
)


def with_usage_metadata(normalized: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """Retain bounded provider metadata after numeric token normalization."""
    keys = ("usage_scope", "usage_accuracy", "billable", *STATUS_KEYS, *CONTEXT_REUSE_KEYS)
    return {**normalized, **{key: raw[key] for key in keys if raw.get(key) is not None}}


def with_status_metadata(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
    total = diagnostics.get("token_usage_total") if isinstance(diagnostics.get("token_usage_total"), dict) else {}
    calls = diagnostics.get("token_usage") if isinstance(diagnostics.get("token_usage"), list) else []
    latest = calls[-1] if calls and isinstance(calls[-1], dict) else {}
    metadata = {
        key: total.get(key, latest.get(key))
        for key in (*STATUS_KEYS, *CONTEXT_REUSE_KEYS)
        if total.get(key, latest.get(key)) is not None
    }
    if not metadata:
        return payload
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    components = payload.get("components") if isinstance(payload.get("components"), dict) else {}
    return {
        **payload,
        "usage": {**usage, **metadata},
        "components": {name: {**component, **metadata} for name, component in components.items()},
    }


def _token_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, int(value))


def _first_token_int(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = _token_int(usage.get(key))
        if value is not None:
            return value
    return None


def aggregate_provider_usages(usages: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]]]:
    """Aggregate explicit provider-call usages without recursively guessing payloads."""
    components: dict[str, dict[str, Any]] = {}
    models: set[str] = set()
    transports: set[str] = set()
    provider_threads: set[str] = set()
    for index, raw in enumerate(usages[:64], start=1):
        if not isinstance(raw, dict):
            continue
        input_tokens = _first_token_int(raw, "prompt_tokens", "input_tokens")
        output_tokens = _first_token_int(raw, "completion_tokens", "output_tokens")
        total_tokens = _first_token_int(raw, "total_tokens", "total")
        if total_tokens is None and (input_tokens is not None or output_tokens is not None):
            total_tokens = int(input_tokens or 0) + int(output_tokens or 0)
        if total_tokens is None:
            continue
        component = {
            "prompt_tokens": int(input_tokens or 0),
            "completion_tokens": int(output_tokens or 0),
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "total_tokens": total_tokens,
        }
        for key in ("cached_input_tokens", "reasoning_tokens"):
            value = _token_int(raw.get(key))
            if value is not None:
                component[key] = value
        for key in (
            "model", "source", "usage_scope", "usage_accuracy", "billable", "transport",
            *CONTEXT_REUSE_KEYS, "context_window_tokens", "rate_limits", "status_telemetry",
        ):
            if key in raw:
                component[key] = raw[key]
        model = str(raw.get("model") or "").strip()
        if model:
            models.add(model)
        transport = str(raw.get("transport") or "").strip()
        if transport:
            transports.add(transport)
        provider_thread = str(raw.get("provider_thread_id") or "").strip()
        if provider_thread:
            provider_threads.add(provider_thread)
        components[f"provider_{index}"] = component
    if not components:
        return None, {}
    rows = list(components.values())
    aggregate = {
        "prompt_tokens": sum(int(row.get("prompt_tokens") or 0) for row in rows),
        "completion_tokens": sum(int(row.get("completion_tokens") or 0) for row in rows),
        "input_tokens": sum(int(row.get("input_tokens") or 0) for row in rows),
        "output_tokens": sum(int(row.get("output_tokens") or 0) for row in rows),
        "total_tokens": sum(int(row.get("total_tokens") or 0) for row in rows),
        "api_calls": len(rows),
        "source": "agent_run_total",
    }
    for key in ("cached_input_tokens", "reasoning_tokens"):
        aggregate[key] = sum(int(row.get(key) or 0) for row in rows)
    if len(models) == 1:
        aggregate["model"] = next(iter(models))
    if len(transports) == 1 and all(row.get("transport") for row in rows):
        aggregate["transport"] = next(iter(transports))
    if len(provider_threads) == 1 and all(row.get("provider_thread_id") for row in rows):
        aggregate["provider_thread_id"] = next(iter(provider_threads))
    latest = rows[-1]
    for key in (*STATUS_KEYS, *CONTEXT_REUSE_KEYS):
        if latest.get(key) is not None:
            aggregate[key] = latest[key]
    if all(row.get("usage_scope") == "llm_api_call" for row in rows):
        aggregate["usage_scope"] = "llm_api_call"
    if all(row.get("usage_accuracy") == "provider_exact" for row in rows):
        aggregate["usage_accuracy"] = "provider_exact"
    if all(row.get("billable") is True for row in rows):
        aggregate["billable"] = True
    return aggregate, components


def _typed_total(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("exact"), bool):
        return None
    projected: dict[str, Any] = {"exact": value["exact"]}
    for key in ("total_tokens", "calls", "metered_calls"):
        item = _token_int(value.get(key))
        if item is None:
            return None
        projected[key] = item
    return projected


def with_canonical_usage(result: dict[str, Any] | None, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Finalize usage while preserving an owned exact multi-call projection."""
    if not isinstance(result, dict):
        return result
    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
    raw_calls = diagnostics.get("token_usage") if isinstance(diagnostics.get("token_usage"), list) else []
    usage, components = aggregate_provider_usages(raw_calls)
    if usage is None:
        usage = payload.get("usage") if isinstance(payload, dict) and isinstance(payload.get("usage"), dict) else None
        components = payload.get("components") if isinstance(payload, dict) and isinstance(payload.get("components"), dict) else {}
    typed_total = _typed_total(diagnostics.get("token_usage_total"))
    if usage is None:
        return result
    total_projection: dict[str, Any] = usage
    if typed_total is not None:
        total_projection = {**usage, **typed_total}
        if raw_calls:
            component_count = len(components)
            aggregate_total = int(usage.get("total_tokens") or 0)
            total_projection["exact"] = bool(
                typed_total["exact"]
                and typed_total["total_tokens"] == aggregate_total
                and typed_total["metered_calls"] == component_count
                and typed_total["calls"] == component_count
            )
            total_projection["total_tokens"] = aggregate_total
            total_projection["metered_calls"] = component_count
    updated = {**result, "token_usage": usage}
    updated["diagnostics"] = {
        **diagnostics,
        "token_usage": usage,
        "token_usage_total": total_projection,
        "token_usage_components": components,
    }
    return updated


def _without_redundant_run_aggregates(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exclude a run aggregate only when its exact sibling calls prove duplication."""
    retained = list(calls)
    for candidate in calls:
        raw = candidate.get("raw_usage") if isinstance(candidate.get("raw_usage"), dict) else {}
        declared_calls = _token_int(raw.get("api_calls"))
        run_id = str(candidate.get("run_id") or "")
        if not run_id or declared_calls is None or declared_calls <= 1:
            continue
        siblings = [
            call for call in calls
            if call is not candidate and str(call.get("run_id") or "") == run_id
        ]
        if len(siblings) != declared_calls or not all(call.get("exact") for call in siblings):
            continue
        keys = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens", "total_tokens")
        if all(
            _token_int(candidate.get(key)) == sum(int(_token_int(call.get(key)) or 0) for call in siblings)
            for key in keys
        ):
            retained.remove(candidate)
    return retained


def provider_call_components(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Project only individual provider calls for persistence, never run aggregates."""
    components = payload.get("components") if isinstance(payload.get("components"), dict) else {}
    return {
        str(name): usage for name, usage in components.items()
        if name != "total" and isinstance(usage, dict) and int(_token_int(usage.get("api_calls")) or 1) == 1
    }


def summary_from_calls(
    calls: list[dict[str, Any]],
    *,
    run_id: str = "",
    quest_id: str = "",
    turn_id: str = "",
    include_turns: bool = True,
    sanitize: Callable[[Any, str], str] | None = None,
) -> dict[str, Any]:
    clean = sanitize or (lambda value, fallback="": str(value or fallback))
    calls = _without_redundant_run_aggregates(calls)
    exact_calls = [call for call in calls if call.get("exact")]
    estimated_calls = [call for call in calls if not call.get("exact")]
    sum_key = lambda items, key: sum(int(call.get(key) or 0) for call in items)
    summary = {
        "schema": "hermes.wasm_agent.token_ledger.summary.v1",
        "run_id": clean(run_id, ""),
        "quest_id": clean(quest_id, ""),
        "turn_id": clean(turn_id, ""),
        "exact": bool(calls) and len(exact_calls) == len(calls),
        "status": "ready" if calls else "empty",
        "provider_call_count": len(calls),
        "exact_provider_call_count": len(exact_calls),
        "input_tokens": sum_key(exact_calls, "input_tokens"),
        "output_tokens": sum_key(exact_calls, "output_tokens"),
        "cached_input_tokens": sum_key(exact_calls, "cached_input_tokens"),
        "fresh_input_tokens": max(0, sum_key(exact_calls, "input_tokens") - sum_key(exact_calls, "cached_input_tokens")),
        "reasoning_tokens": sum_key(exact_calls, "reasoning_tokens"),
        "total_tokens": sum_key(exact_calls, "total_tokens"),
        "estimated_input_tokens": sum_key(estimated_calls, "estimated_input_tokens") or None,
        "estimated_output_tokens": sum_key(estimated_calls, "estimated_output_tokens") or None,
        "estimated_total_tokens": sum_key(estimated_calls, "estimated_total_tokens") or None,
        "calls": calls,
    }
    for call in reversed(calls):
        active_context_tokens = _token_int(call.get("input_tokens"))
        if active_context_tokens is not None:
            summary["active_context_tokens"] = active_context_tokens
            break
    for call in reversed(calls):
        raw = call.get("raw_usage") if isinstance(call.get("raw_usage"), dict) else {}
        found = {key: raw[key] for key in (*STATUS_KEYS, *CONTEXT_REUSE_KEYS) if raw.get(key) is not None}
        if found:
            summary.update(found)
            break
    if not include_turns:
        return summary
    turn_groups: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        turn_groups.setdefault(str(call.get("turn_id") or ""), []).append(call)
    turns: list[dict[str, Any]] = []
    for key, provider_calls in turn_groups.items():
        run_ids = sorted({str(call.get("run_id") or "") for call in provider_calls if call.get("run_id")})
        turn_summary = summary_from_calls(
            provider_calls,
            run_id=run_ids[0] if len(run_ids) == 1 else "",
            quest_id=quest_id or str(provider_calls[0].get("quest_id") or ""),
            turn_id=key,
            include_turns=False,
            sanitize=clean,
        )
        turn_summary.update({
            "schema": "hermes.wasm_agent.token_ledger.turn.v1",
            "run_ids": run_ids,
            "provider_calls": provider_calls,
        })
        turn_summary.pop("calls", None)
        turns.append(turn_summary)
    summary["turn_count"] = len(turns)
    summary["turns"] = turns
    return summary
