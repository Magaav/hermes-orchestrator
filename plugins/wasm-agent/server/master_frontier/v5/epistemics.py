"""Compact claim limits derived from bounded evidence receipts."""

from __future__ import annotations

from typing import Any


def _incomplete(value: Any) -> bool:
    if isinstance(value, list):
        return any(_incomplete(item) for item in value)
    if not isinstance(value, dict):
        return False
    code = str(value.get("code") or "")
    if value.get("truncated") is True or code.endswith("_truncated"):
        return True
    stat = value.get("stat") if isinstance(value.get("stat"), dict) else {}
    if stat.get("complete") is False:
        return True
    truncation = value.get("truncation") if isinstance(value.get("truncation"), dict) else {}
    if any(item is True for item in truncation.values()):
        return True
    return any(_incomplete(item) for item in value.values() if isinstance(item, (dict, list)))


def project(steps: list[dict[str, Any]]) -> dict[str, str]:
    incomplete = any(_incomplete(step.get("result")) for step in steps if isinstance(step, dict))
    if incomplete:
        return {
            "universe": "incomplete",
            "claim_rule": "presence_only_no_absence_claims",
        }
    return {"universe": "bounded", "claim_rule": "claims_only_within_observed_evidence"}
