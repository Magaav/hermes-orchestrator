"""Versioned normalization for replayed V6 provider-tool arguments."""
from __future__ import annotations

from typing import Any

from . import contracts


VERSION = 1
ALIASES = {
    "discover": {"search": "query", "max_results": "limit"},
    "detail": {"evidence_id": "id", "json_pointer": "pointer"},
    "execute": {"ops": "operations"},
    "checkpoint": {"state_delta": "delta"},
}


def normalize(name: str, arguments: Any) -> dict[str, Any]:
    if name not in ALIASES:
        raise contracts.ContractError("tool_unknown")
    if not isinstance(arguments, dict):
        raise contracts.ContractError("tool_arguments_invalid")
    result = dict(arguments)
    for legacy, current in ALIASES[name].items():
        if legacy in result:
            if current in result and result[current] != result[legacy]:
                raise contracts.ContractError("tool_argument_alias_conflict")
            result[current] = result.pop(legacy)
    return result
