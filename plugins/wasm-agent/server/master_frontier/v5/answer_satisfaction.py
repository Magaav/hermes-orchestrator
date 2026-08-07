"""Deterministic final-answer usefulness contract for Master:frontier V5."""
from __future__ import annotations

import re
from typing import Any


MAX_REPAIRS = 2
_TOOL_DIRECTIVE = re.compile(
    r"^\s*@(?:search|read|memory|inspect|browser|edit|test|diff|prove|checkpoint)\b",
    re.IGNORECASE | re.MULTILINE,
)
_STRUCTURED_TOOL = re.compile(
    r'^\s*\{\s*"(?:tool|name)"\s*:\s*"(?:search|read|memory|inspect|browser|edit|test|diff|prove|checkpoint)"',
    re.IGNORECASE,
)


def assess(answer: Any) -> dict[str, Any]:
    """Classify answer usability without judging product-specific correctness."""
    text = str(answer or "").strip()
    if not text:
        return _unsatisfactory("answer_empty", "The final answer is empty.")
    if _TOOL_DIRECTIVE.search(text) or _STRUCTURED_TOOL.match(text):
        return _unsatisfactory(
            "answer_is_tool_request",
            "The final answer is an unevaluated tool request, not a user-facing answer.",
        )
    return {
        "status": "satisfactory",
        "code": "ok",
        "message": "The response is a non-empty user-facing answer.",
    }


def _unsatisfactory(code: str, message: str) -> dict[str, str]:
    return {"status": "unsatisfactory", "code": code, "message": message}


def fallback(assessment: dict[str, Any]) -> str:
    """Return an honest user-visible result when bounded synthesis cannot recover."""
    reason = str(assessment.get("message") or "The answer could not be made useful.").strip()
    return (
        "I collected the requested evidence, but I could not synthesize a satisfactory "
        f"answer from it in this run. {reason}"
    )
