"""Fail-closed final-answer checks against current operation evidence."""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


_POSITIVE_RUNTIME_CLAIM = re.compile(
    r"\b(?:verified|observed|confirmed|conclusive)\b[^.!?\n]{0,40}\bruntime\b"
    r"|\bruntime\s+observations?\b",
    re.IGNORECASE,
)
_NEGATED_RUNTIME_CLAIM = re.compile(
    r"\b(?:no|not|without|lack(?:s|ing|ed)?|unavailable|missing)\b[^.!?\n]{0,50}\bruntime\b"
    r"|\bruntime\b[^.!?\n]{0,50}\b(?:not|unavailable|missing)\b",
    re.IGNORECASE,
)
_MUTATION_DENIAL = re.compile(
    r"\b(?:unable to implement|(?:i(?:'m| am)\s+)?blocked|no (?:repository )?tools?|"
    r"tool namespace (?:is )?(?:not |un)?available|can(?:not|'t)\s+(?:inspect|edit|patch)|"
    r"changed files?\s*:\s*(?:none|\[\])|checks?\s*:\s*not run)\b",
    re.IGNORECASE,
)


def _has_runtime_evidence(steps: list[dict[str, Any]] | None) -> bool:
    return any(
        isinstance(step, dict)
        and step.get("tool") == "inspect"
        and step.get("status") == "completed"
        and isinstance(step.get("result"), dict)
        and step["result"].get("ok") is True
        for step in (steps or [])
    )


def _unsupported_runtime_claim(answer: str, steps: list[dict[str, Any]] | None) -> bool:
    if _has_runtime_evidence(steps):
        return False
    sentences = re.split(r"(?<=[.!?])\s+|\n+", str(answer or ""))
    return any(
        _POSITIVE_RUNTIME_CLAIM.search(sentence)
        and not _NEGATED_RUNTIME_CLAIM.search(sentence)
        for sentence in sentences
    )


def normalize(answer: str, ledger: dict[str, Any] | None) -> str:
    """Make the final text agree with authoritative mutation receipts."""
    text = str(answer or "").strip()
    operations = ledger if isinstance(ledger, dict) else {}
    changed = [str(path) for path in (operations.get("changed_files") or []) if str(path)]
    if changed and _MUTATION_DENIAL.search(text):
        route_id = str(operations.get("route_id") or "").strip()
        receipts = operations.get("receipts") if isinstance(operations.get("receipts"), dict) else {}
        verified = [name for name in ("check", "diff", "proof") if isinstance(receipts.get(name), dict) and receipts[name].get("ok") is True]
        route_line = f"Route: {route_id}. " if route_id else ""
        proof_line = f" Verification receipts: {', '.join(verified)}." if verified else ""
        return f"Implementation completed. {route_line}Changed files: {', '.join(changed)}.{proof_line}".strip()
    lowered = text.lower()
    missing = [
        path for path in changed
        if path.lower() not in lowered and PurePosixPath(path).name.lower() not in lowered
    ]
    if not missing or "```" in text:
        return text
    suffix = "Changed files: " + ", ".join(missing) + "."
    return f"{text}\n\n{suffix}" if text else suffix


def validate(
    answer: str,
    ledger: dict[str, Any] | None,
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if _unsupported_runtime_claim(answer, steps):
        return {
            "ok": False,
            "code": "final_claim_runtime_evidence_missing",
            "missing": ["runtime.inspect"],
            "message": (
                "Describe bounded reads as source evidence. Do not call them runtime "
                "observations unless a successful inspect receipt exists."
            ),
        }
    operations = ledger if isinstance(ledger, dict) else {}
    changed = [str(path) for path in (operations.get("changed_files") or []) if str(path)]
    if not changed:
        return {"ok": True, "code": "ok", "missing": []}
    text = str(answer or "").strip()
    lowered = text.lower()
    missing = [
        path for path in changed
        if path.lower() not in lowered and PurePosixPath(path).name.lower() not in lowered
    ]
    if missing:
        return {
            "ok": False,
            "code": "final_claim_files_missing",
            "missing": missing[:12],
            "message": "Name every file actually changed by the applied mutation receipt.",
        }
    if "```" in text:
        return {
            "ok": False,
            "code": "final_claim_unapplied_patch_risk",
            "missing": [],
            "message": "Summarize the applied change and proof; do not present another code block as though it were the committed patch.",
        }
    return {"ok": True, "code": "ok", "missing": []}
