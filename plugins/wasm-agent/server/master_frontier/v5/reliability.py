"""Bounded, resumable provider-reliability policy for Master:frontier V5."""
from __future__ import annotations

from typing import Any


RETRYABLE_PROVIDER_CODES = frozenset({"network-timeout", "upstream_unavailable", "provider-empty-response"})
CONSECUTIVE_RETRY_LIMIT = 1
TRANSIENT_RETRY_LIMIT = 3


def initial_state() -> dict[str, Any]:
    return {
        "transient_retries": 0,
        "retry_limit": TRANSIENT_RETRY_LIMIT,
        "consecutive_retries": 0,
        "consecutive_limit": CONSECUTIVE_RETRY_LIMIT,
        "last_code": None,
        "retry_active": False,
    }


def normalize_state(value: Any) -> dict[str, Any]:
    result = initial_state()
    if not isinstance(value, dict):
        return result
    try:
        retries = int(value.get("transient_retries") or 0)
    except (TypeError, ValueError):
        retries = 0
    result["transient_retries"] = max(0, min(retries, TRANSIENT_RETRY_LIMIT))
    code = str(value.get("last_code") or "").strip()
    result["last_code"] = code or None
    if "retry_active" in value:
        result["retry_active"] = bool(value.get("retry_active"))
    else:
        # Legacy checkpoints used the retry counter as both durable budget and
        # active projection state. Preserve an interrupted retry on upgrade.
        result["retry_active"] = bool(result["transient_retries"] and result["last_code"])
    try:
        consecutive = int(value.get("consecutive_retries") or 0)
    except (TypeError, ValueError):
        consecutive = 0
    if "consecutive_retries" not in value and result["retry_active"]:
        consecutive = 1
    result["consecutive_retries"] = max(0, min(consecutive, CONSECUTIVE_RETRY_LIMIT))
    return result


def can_retry(state: dict[str, Any], code: str) -> bool:
    summary = normalize_state(state.get("provider_reliability"))
    return (
        code in RETRYABLE_PROVIDER_CODES
        and summary["transient_retries"] < TRANSIENT_RETRY_LIMIT
        and summary["consecutive_retries"] < CONSECUTIVE_RETRY_LIMIT
    )


def record_retry(state: dict[str, Any], code: str) -> dict[str, Any]:
    summary = normalize_state(state.get("provider_reliability"))
    summary["transient_retries"] += 1
    summary["consecutive_retries"] += 1
    summary["last_code"] = code
    summary["retry_active"] = True
    state["provider_reliability"] = summary
    return summary


def record_success(state: dict[str, Any]) -> dict[str, Any]:
    """End one outage incident without replenishing the durable total budget."""
    summary = normalize_state(state.get("provider_reliability"))
    summary["retry_active"] = False
    summary["consecutive_retries"] = 0
    state["provider_reliability"] = summary
    return summary


def retry_active(state: dict[str, Any]) -> bool:
    return bool(normalize_state(state.get("provider_reliability"))["retry_active"])
