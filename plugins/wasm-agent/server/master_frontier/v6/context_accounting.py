"""Exact, non-enforcing accounting for model-visible V6 requests."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


SCHEMA = "master.frontier.v6.context.accounting.v1"
GROUPS = {"G": "goal", "C": "capabilities", "S": "state", "E": "evidence", "R": "receipts", "M": "missing"}


def _encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:24]


def measure(messages: list[dict[str, str]], tools: list[dict[str, Any]], previous: set[str] | None = None) -> tuple[dict[str, Any], set[str]]:
    previous = previous or set()
    records: list[tuple[str, int, str]] = []
    role_chars: dict[str, int] = {}
    for message in messages:
        role = str(message.get("role") or "unknown")[:40]
        content = str(message.get("content") or "")
        role_chars[role] = role_chars.get(role, 0) + len(content)
        if role == "user" and content.startswith("MF6/"):
            for index, line in enumerate(content.splitlines()):
                tag = line.split("\t", 1)[0] if index else "schema"
                records.append((GROUPS.get(tag, "other"), len(line), _digest(line)))
    tool_text = _encoded(tools)
    fingerprints: set[str] = set()
    repeated_chars = 0
    new_chars = 0
    group_chars: dict[str, int] = {}
    for group, chars, record_digest in records:
        group_chars[group] = group_chars.get(group, 0) + chars
        fingerprint = f"record:{record_digest}"
        fingerprints.add(fingerprint)
        if fingerprint in previous:
            repeated_chars += chars
        else:
            new_chars += chars
    for name, text_value in (
        ("system", "\n".join(str(item.get("content") or "") for item in messages if item.get("role") == "system")),
        ("tools", tool_text),
    ):
        fingerprint = f"{name}:{_digest(text_value)}"
        fingerprints.add(fingerprint)
        if fingerprint in previous:
            repeated_chars += len(text_value)
        else:
            new_chars += len(text_value)
    serialized_chars = len(_encoded({"messages": messages, "tools": tools, "tool_choice": "auto"}))
    return ({
        "schema": SCHEMA, "serialized_chars": serialized_chars,
        "message_chars": sum(role_chars.values()), "role_chars": dict(sorted(role_chars.items())),
        "tool_schema_chars": len(tool_text), "tool_count": len(tools),
        "record_count": len(records), "group_chars": dict(sorted(group_chars.items())),
        "repeated_chars": repeated_chars, "new_chars": new_chars,
        "enforced": False,
    }, fingerprints)


def attach_usage(measurement: dict[str, Any], usage: Any) -> dict[str, Any]:
    observed = usage if isinstance(usage, dict) else {}
    provider_usage = {
        key: observed[key]
        for key in ("prompt_tokens", "input_tokens", "completion_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "reasoning_tokens")
        if observed.get(key) is not None
    }
    provider_input = int(provider_usage.get("input_tokens") or provider_usage.get("prompt_tokens") or 0)
    projection_estimate = math.ceil(int(measurement.get("serialized_chars") or 0) / 4)
    return {
        **measurement,
        "provider_usage": provider_usage,
        "transport_accounting": {
            "provider_input_tokens": provider_input,
            "visible_projection_tokens_estimate": projection_estimate,
            "transport_overhead_tokens_estimate": max(0, provider_input - projection_estimate),
            "estimate_method": "utf8_chars_div_4_ceiling",
            "exact": False,
        },
    }
