"""Reasoning-effort contract for V6 provider calls."""
from __future__ import annotations

from typing import Any


DEFAULT = "low"
SUPPORTED = frozenset({"none", "low", "medium", "high", "xhigh", "max"})


def effort(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in SUPPORTED else DEFAULT
