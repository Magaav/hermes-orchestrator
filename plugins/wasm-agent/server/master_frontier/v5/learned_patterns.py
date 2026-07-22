"""Reviewed generic patterns available to the V5 head.

Patterns are source-owned promotion receipts, not mutable model memory.  A
pattern may be projected only after its evidence has passed the declared gate;
benchmark candidates stay out of the runtime prompt.
"""
from __future__ import annotations

from typing import Any

from . import task_policy


PROMOTED: tuple[dict[str, Any], ...] = (
    {
        "code": "d1",
        "classes": frozenset(task_policy.SELF_CONTAINED_CLASSES),
        "rule": "Declared self-contained work answers directly.",
        "evidence": "loop5-v5-minimal-class-allowlist",
        "candidate_digest": "842ffd7ebc8c0ea824fe5c407077abf51d28a580afd6392a91b3e8c59e870fc1",
    },
    {
        "code": "e1",
        "classes": frozenset(task_policy.GROUNDED_CLASSES),
        "rule": "Current bounded tool evidence outranks memory and assumptions.",
        "evidence": "promoted-v5-golden-holdout-generalization",
        "candidate_digest": "dcf96ef8bd55d66ba7e274055649cbaac6e5f75b2b4f9116fb7ba63f43b40619",
    },
)


def project(route: dict[str, Any], *, limit: int = 3) -> list[dict[str, str]]:
    """Return only promoted patterns applicable to the declared task class."""
    request_class = task_policy.request_class(route)
    result: list[dict[str, str]] = []
    for item in PROMOTED:
        if request_class not in item["classes"]:
            continue
        result.append({
            "code": str(item["code"]),
            "rule": str(item["rule"]),
            "evidence": str(item["evidence"]),
            "digest": str(item["candidate_digest"])[:12],
        })
        if len(result) >= max(1, min(int(limit), 6)):
            break
    return result
