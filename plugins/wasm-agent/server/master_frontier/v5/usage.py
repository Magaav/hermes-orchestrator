"""Durable cumulative provider usage with a bounded recent-call ring."""

from __future__ import annotations

from typing import Any


FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "cached_input_tokens", "reasoning_tokens")


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def empty() -> dict[str, int]:
    return {**{key: 0 for key in FIELDS}, "metered_calls": 0}


def normalize(value: Any) -> dict[str, int]:
    result = empty()
    if not isinstance(value, dict):
        return result
    for key in (*FIELDS, "metered_calls"):
        observed = _integer(value.get(key))
        if observed is not None:
            result[key] = observed
    return result


def _first(value: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    return next((item for key in keys if (item := _integer(value.get(key))) is not None), None)


def record(total: dict[str, Any] | None, observed: dict[str, Any]) -> dict[str, int]:
    """Add one measurable provider receipt exactly once."""
    result = normalize(total)
    prompt = _first(observed, ("prompt_tokens", "input_tokens", "inputTokens"))
    completion = _first(observed, ("completion_tokens", "output_tokens", "outputTokens"))
    measured_total = _first(observed, ("total_tokens", "totalTokens"))
    if measured_total is None and prompt is None and completion is None:
        return result
    result["metered_calls"] += 1
    result["prompt_tokens"] += int(prompt or 0)
    result["completion_tokens"] += int(completion or 0)
    result["total_tokens"] += int(measured_total if measured_total is not None else (prompt or 0) + (completion or 0))
    cached = _first(observed, ("cached_input_tokens", "cached_tokens"))
    reasoning = _first(observed, ("reasoning_tokens",))
    result["cached_input_tokens"] += int(cached or 0)
    result["reasoning_tokens"] += int(reasoning or 0)
    return result
