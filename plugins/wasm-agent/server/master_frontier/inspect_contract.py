from __future__ import annotations

import re
from typing import Any


CANONICAL_KINDS = (
    "route", "files", "symbols", "proof", "cost", "transcript",
    "diff", "capabilities", "runtime_entity",
)

ALIASES = {
    "route": "route", "contract": "route", "map": "route",
    "files": "files", "file": "files", "receipts": "files",
    "symbol": "symbols", "symbols": "symbols", "code": "symbols",
    "proof": "proof", "timeline": "proof", "run": "proof",
    "cost": "cost", "tokens": "cost", "ledger": "cost",
    "transcript": "transcript", "messages": "transcript", "history": "transcript", "continuity": "transcript",
    "diff": "diff", "changes": "diff",
    "capabilities": "capabilities", "capability": "capabilities",
    "runtime": "runtime_entity", "entity": "runtime_entity", "entities": "runtime_entity", "workspace": "runtime_entity",
}


def kinds(body: dict[str, Any], *, limit: int = 12) -> list[str]:
    raw = body.get("inspect") or body.get("kinds") or body.get("kind") or body.get("need") or []
    if isinstance(raw, str):
        raw = [item.strip() for item in re.split(r"[, ]+", raw) if item.strip()]
    if not isinstance(raw, list):
        raw = []
    items = [str(item or "").strip().lower()[:80] for item in raw[:limit] if str(item or "").strip()]
    return items or ["route"]


def canonical(kind: str) -> str | None:
    return ALIASES.get(str(kind or "").strip().lower())


def unsupported(kind: str) -> dict[str, Any]:
    return {
        "kind": str(kind or "")[:80],
        "code": "inspect_kind_unsupported",
        "message": "kernel.inspect supports runtime/route/proof state, not arbitrary source-object kinds.",
        "supported_kinds": list(CANONICAL_KINDS),
        "suggested_primitive": "compound.source.discovery",
    }


def capability_health(observations: list[dict[str, Any]], unknowns: list[dict[str, Any]]) -> str:
    if unknowns and not observations:
        return "capability_blocked"
    if unknowns:
        return "partial"
    return "healthy"
