from __future__ import annotations

import time
from typing import Any


LIMIT_KEYS = ("head_tokens_max", "provider_tokens_max", "api_calls_max", "wall_ms_max")
OUTPUT_EMERGENCY_MAX = 65536


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def resolve(route_budget: dict[str, Any] | None, override: dict[str, Any] | None) -> dict[str, int]:
    """Resolve caller hints without allowing them to expand route-owned limits."""
    route_budget = route_budget if isinstance(route_budget, dict) else {}
    override = override if isinstance(override, dict) else {}
    result: dict[str, int] = {}
    for key in LIMIT_KEYS:
        route_value = _non_negative_int(route_budget.get(key))
        requested = _non_negative_int(override.get(key))
        if route_value is not None:
            result[key] = min(route_value, requested) if requested is not None else route_value
        elif requested is not None:
            result[key] = requested
    route_output = _non_negative_int(route_budget.get("max_output_tokens"))
    requested_output = _non_negative_int(override.get("max_output_tokens"))
    max_output = min(route_output, requested_output) if route_output is not None and requested_output is not None else route_output if route_output is not None else requested_output
    if max_output is not None:
        result["max_output_tokens"] = min(max_output, OUTPUT_EMERGENCY_MAX)
    return result


def from_envelope(envelope: dict[str, Any]) -> dict[str, int]:
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    contract_budget = contract.get("budget") if isinstance(contract.get("budget"), dict) else {}
    envelope_budget = envelope.get("budget") if isinstance(envelope.get("budget"), dict) else {}
    return resolve(contract_budget, envelope_budget)


def provider_calls_used(usages: list[dict[str, Any]] | None) -> int:
    return len([item for item in (usages or []) if isinstance(item, dict)])


def continuation_limit(envelope: dict[str, Any], *, calls_used: int = 0, hard_max: int = 6) -> int:
    budget = from_envelope(envelope)
    allowed = budget.get("api_calls_max")
    if allowed is None:
        return hard_max
    return max(0, min(hard_max, allowed - max(0, calls_used)))


def wall_remaining_ms(envelope: dict[str, Any], started_monotonic: float) -> int | None:
    wall_limit = from_envelope(envelope).get("wall_ms_max")
    if wall_limit is None:
        return None
    elapsed = max(0, int((time.monotonic() - started_monotonic) * 1000))
    return max(0, wall_limit - elapsed)


def violation(
    envelope: dict[str, Any],
    usages: list[dict[str, Any]] | None,
    *,
    started_monotonic: float | None = None,
) -> dict[str, Any] | None:
    budget = from_envelope(envelope)
    calls = provider_calls_used(usages)
    call_limit = budget.get("api_calls_max")
    if call_limit is not None and calls > call_limit:
        return {"code": "api_call_budget_exhausted", "used": calls, "limit": call_limit}
    total_tokens = sum(int(item.get("total_tokens") or 0) for item in (usages or []) if isinstance(item, dict))
    token_limits = [
        value
        for value in (budget.get("head_tokens_max"), budget.get("provider_tokens_max"))
        if isinstance(value, int) and value >= 0
    ]
    if token_limits and total_tokens > min(token_limits):
        return {"code": "provider_token_budget_exhausted", "used": total_tokens, "limit": min(token_limits)}
    if started_monotonic is not None:
        remaining = wall_remaining_ms(envelope, started_monotonic)
        if remaining == 0:
            return {"code": "wall_budget_exhausted", "used": budget.get("wall_ms_max"), "limit": budget.get("wall_ms_max")}
    return None
