from __future__ import annotations

import re


_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([A-Za-z0-9._\-+/=]+)"),
        r"\1***REDACTED***",
    ),
    (
        re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)([^\s,;]+)"),
        r"\1***REDACTED***",
    ),
    (
        re.compile(r"(?i)(token\s*[:=]\s*)([A-Za-z0-9._\-]{16,})"),
        r"\1***REDACTED***",
    ),
    (
        re.compile(r"\b(sk-[A-Za-z0-9]{12,})\b"),
        "sk-***REDACTED***",
    ),
    (
        re.compile(r"\b(ghp_[A-Za-z0-9]{20,})\b"),
        "ghp_***REDACTED***",
    ),
]


def redact_text(text: str) -> str:
    redacted = text
    for pattern, replacement in _REPLACEMENTS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
