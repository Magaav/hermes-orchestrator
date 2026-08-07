"""Deterministic redaction applied before executor output becomes V6 evidence."""
from __future__ import annotations

import re
from typing import Any


SECRET_KEY = re.compile(r"(?:^|_)(?:authorization|cookie|credential|password|passwd|secret|token|api[_-]?key|private[_-]?key)(?:$|_)", re.I)
BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")
OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")


def apply(value: Any, *, depth: int = 0) -> Any:
    if depth > 16:
        return "[redacted:depth]"
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if SECRET_KEY.search(str(key)) else apply(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [apply(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        text = PRIVATE_KEY.sub("[redacted:private-key]", value)
        text = BEARER.sub("Bearer [redacted]", text)
        return OPENAI_KEY.sub("[redacted:api-key]", text)
    return value
