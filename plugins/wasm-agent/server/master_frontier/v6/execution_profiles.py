"""Route-owned V6 execution profiles over the stable four-tool provider API."""
from __future__ import annotations

from typing import Any


DEFAULT = "semantic"
PROFILES = {
    "minimal": {"max_decisions": 12, "history_turns": 0, "description": "Small isolated benchmark/runtime context."},
    "semantic": {"max_decisions": 32, "history_turns": 6, "description": "Demand-shaped production semantic loop."},
    "code_orchestrated": {"max_decisions": 32, "history_turns": 6, "description": "Batch independent operations through one execute DAG."},
}


class ProfileError(ValueError):
    pass


def resolve(route: dict[str, Any]) -> dict[str, Any]:
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    requested = str(contract.get("execution_profile") or route.get("execution_profile") or DEFAULT)
    if requested not in PROFILES:
        raise ProfileError("v6_execution_profile_invalid")
    return {"id": requested, **PROFILES[requested]}
