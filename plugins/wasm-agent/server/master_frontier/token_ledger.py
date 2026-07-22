from __future__ import annotations

from typing import Any, Callable


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
        for key in ("model", "source", "usage_scope", "usage_accuracy", "billable"):
            if key in raw:
                component[key] = raw[key]
        model = str(raw.get("model") or "").strip()
        if model:
            models.add(model)
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
        "reasoning_tokens": sum_key(exact_calls, "reasoning_tokens"),
        "total_tokens": sum_key(exact_calls, "total_tokens"),
        "estimated_input_tokens": sum_key(estimated_calls, "estimated_input_tokens") or None,
        "estimated_output_tokens": sum_key(estimated_calls, "estimated_output_tokens") or None,
        "estimated_total_tokens": sum_key(estimated_calls, "estimated_total_tokens") or None,
        "calls": calls,
    }
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
