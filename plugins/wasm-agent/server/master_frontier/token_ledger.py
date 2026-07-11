from __future__ import annotations

from typing import Any, Callable


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
