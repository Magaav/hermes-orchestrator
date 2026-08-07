"""Exact, small expectation matcher for V6 operation receipts."""
from __future__ import annotations

from typing import Any


def _matches(expected: Any, observed: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(observed, dict) and all(key in observed and _matches(value, observed[key]) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(observed, list) and all(any(_matches(item, candidate) for candidate in observed) for item in expected)
    return expected == observed


def satisfied(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    return _matches(expected, observed)
