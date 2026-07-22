from __future__ import annotations

import json
import time
from typing import Any


LIMIT_KEYS = (
    "head_tokens_max", "input_tokens_max", "provider_tokens_max", "api_calls_max",
    "wall_ms_max", "provider_call_ms_max", "heartbeat_ms_max", "task_lease_ms_max",
)
OUTPUT_EMERGENCY_MAX = 65536
HARD_ENFORCEMENT = "hard"
INPUT_FRAMING_TOKEN_RESERVE = 1024
MAX_PROVIDER_CALL_MS = 30 * 60_000
MAX_TASK_LEASE_MS = 7 * 24 * 60 * 60_000
DEFAULT_PROVIDER_CALL_MS = 90_000
DEFAULT_TASK_LEASES_MS = {
    "conversation": 2 * 60_000,
    "source_investigation": 30 * 60_000,
    "diagnosis": 30 * 60_000,
    "runtime_inspection": 30 * 60_000,
    "verification": 2 * 60 * 60_000,
    "implementation": 12 * 60 * 60_000,
}


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _requests_hard_enforcement(value: dict[str, Any]) -> bool:
    return str(value.get("enforcement") or "").strip().lower() == HARD_ENFORCEMENT


def resolve(route_budget: dict[str, Any] | None, override: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve caller hints without allowing them to expand route-owned targets."""
    route_budget = route_budget if isinstance(route_budget, dict) else {}
    override = override if isinstance(override, dict) else {}
    result: dict[str, Any] = {}
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
    # Route-owned token/call values are targets. Only an explicit request
    # budget can opt this objective into hard cumulative enforcement.
    if _requests_hard_enforcement(override):
        result["enforcement"] = HARD_ENFORCEMENT
    return result


def from_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    contract_budget = contract.get("budget") if isinstance(contract.get("budget"), dict) else {}
    envelope_budget = envelope.get("budget") if isinstance(envelope.get("budget"), dict) else {}
    result = resolve(contract_budget, envelope_budget)
    # A normalized task contract may already carry the explicit request's
    # enforcement bit. Preserve it across later route projection.
    if _requests_hard_enforcement(contract_budget):
        result["enforcement"] = HARD_ENFORCEMENT
    return result


def hard_enforced(envelope: dict[str, Any]) -> bool:
    return from_envelope(envelope).get("enforcement") == HARD_ENFORCEMENT


def provider_call_ms(envelope: dict[str, Any]) -> int:
    """Return one provider-call deadline; wall_ms_max remains its legacy alias."""
    resolved = from_envelope(envelope)
    declared = [
        max(1, int(value))
        for value in (resolved.get("provider_call_ms_max"), resolved.get("wall_ms_max"))
        if value is not None
    ]
    value = min(declared) if declared else DEFAULT_PROVIDER_CALL_MS
    return min(MAX_PROVIDER_CALL_MS, value)


def task_lease_ms(envelope: dict[str, Any]) -> int:
    """Return the durable objective lease, independent from interactive calls."""
    resolved = from_envelope(envelope)
    raw = resolved.get("task_lease_ms_max")
    if raw is not None:
        return min(MAX_TASK_LEASE_MS, max(0, int(raw)))
    contract = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    request_class = str(contract.get("request_class") or contract.get("objective_kind") or "").strip().lower()
    return DEFAULT_TASK_LEASES_MS.get(request_class, 15 * 60_000)


def hard_input_reservation(envelope: dict[str, Any]) -> int | None:
    """Return only a positive route-owned reservation for strict mode."""
    route_budget = envelope.get("budget") if isinstance(envelope.get("budget"), dict) else {}
    value = _non_negative_int(route_budget.get("input_tokens_max"))
    return value if isinstance(value, int) and value > 0 else None


def request_input_token_upper_bound(payload: dict[str, Any] | None) -> int:
    """Conservatively bound visible provider input by UTF-8 bytes plus framing.

    Byte-level model tokenization cannot consume more visible tokens than the
    serialized request bytes. The reserve covers provider message/tool framing.
    """
    if not isinstance(payload, dict):
        return 0
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return len(encoded) + INPUT_FRAMING_TOKEN_RESERVE


def provider_calls_used(usages: list[dict[str, Any]] | None) -> int:
    return len([item for item in (usages or []) if isinstance(item, dict)])


def usage_tokens(usage: dict[str, Any] | None) -> int | None:
    """Return one provider-reported total without estimating missing usage."""
    if not isinstance(usage, dict):
        return None
    for key in ("total_tokens", "totalTokens"):
        value = _non_negative_int(usage.get(key))
        if value is not None:
            return value
    prompt = next((value for key in ("prompt_tokens", "input_tokens", "inputTokens")
                   if (value := _non_negative_int(usage.get(key))) is not None), None)
    completion = next((value for key in ("completion_tokens", "output_tokens", "outputTokens")
                       if (value := _non_negative_int(usage.get(key))) is not None), None)
    if prompt is None and completion is None:
        return None
    return int(prompt or 0) + int(completion or 0)


def provider_tokens_used(usages: list[dict[str, Any]] | dict[str, Any] | None) -> int:
    if isinstance(usages, dict):
        value = _non_negative_int(usages.get("total_tokens"))
        return int(value or 0)
    return sum(value for item in (usages or []) if (value := usage_tokens(item)) is not None)


def provider_token_diagnostics(
    envelope: dict[str, Any], usages: list[dict[str, Any]] | dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Report exact cumulative use against the advisory provider target."""
    resolved = from_envelope(envelope)
    target = resolved.get("provider_tokens_max")
    if not isinstance(target, int) or target < 0:
        return None
    used = provider_tokens_used(usages)
    return {
        "used": used,
        "target": target,
        "over_target": used > target,
        "hard": resolved.get("enforcement") == HARD_ENFORCEMENT,
    }


def provider_token_status(
    envelope: dict[str, Any], usages: list[dict[str, Any]] | dict[str, Any] | None,
) -> dict[str, int] | None:
    """Return a cumulative provider cap only when hard enforcement is explicit."""
    diagnostics = provider_token_diagnostics(envelope, usages)
    if diagnostics is None or diagnostics["hard"] is not True:
        return None
    return {"used": int(diagnostics["used"]), "limit": int(diagnostics["target"])}


def output_tokens_remaining(
    envelope: dict[str, Any], usages: list[dict[str, Any]] | None,
    *, request_payload: dict[str, Any] | None = None,
) -> int | None:
    """Return the per-call output ceiling, plus hard cumulative remainder."""
    resolved = from_envelope(envelope)
    candidates = [
        value
        for value in (resolved.get("head_tokens_max"), resolved.get("max_output_tokens"))
        if isinstance(value, int) and value >= 0
    ]
    status = provider_token_status(envelope, usages)
    if status is not None:
        declared_reservation = hard_input_reservation(envelope)
        if declared_reservation is None:
            candidates.append(0)
        else:
            input_reservation = max(
                declared_reservation,
                request_input_token_upper_bound(request_payload),
            )
            candidates.append(max(0, status["limit"] - status["used"] - input_reservation))
    return min(candidates) if candidates else None


def api_call_diagnostics(
    envelope: dict[str, Any], usages: list[dict[str, Any]] | None,
    *, calls_used: int | None = None,
) -> dict[str, Any] | None:
    """Report provider attempts against the advisory route target.

    The usage-list fallback preserves callers that only have metered replies;
    V5 supplies its durable attempt counter so transient failures are visible.
    """
    resolved = from_envelope(envelope)
    target = resolved.get("api_calls_max")
    if not isinstance(target, int) or target < 0:
        return None
    used = max(0, calls_used) if isinstance(calls_used, int) and not isinstance(calls_used, bool) else provider_calls_used(usages)
    return {
        "used": used,
        "target": target,
        "over_target": used > target,
        "hard": resolved.get("enforcement") == HARD_ENFORCEMENT,
    }


def continuation_limit(envelope: dict[str, Any], *, calls_used: int = 0, hard_max: int = 6) -> int:
    budget = from_envelope(envelope)
    allowed = budget.get("api_calls_max")
    if allowed is None or budget.get("enforcement") != HARD_ENFORCEMENT:
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
    call_status = api_call_diagnostics(envelope, usages)
    if call_status is not None and call_status["hard"] and call_status["over_target"]:
        return {
            "code": "api_call_budget_exhausted",
            "used": call_status["used"],
            "limit": call_status["target"],
        }
    token_status = provider_token_status(envelope, usages)
    if token_status is not None and token_status["used"] > token_status["limit"]:
        return {"code": "provider_token_budget_exhausted", **token_status}
    if started_monotonic is not None:
        remaining = wall_remaining_ms(envelope, started_monotonic)
        if remaining == 0:
            return {"code": "wall_budget_exhausted", "used": budget.get("wall_ms_max"), "limit": budget.get("wall_ms_max")}
    return None
