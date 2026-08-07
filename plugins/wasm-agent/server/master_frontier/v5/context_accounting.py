"""Deterministic, non-enforcing accounting for model-visible V5 requests."""
from __future__ import annotations

import hashlib
import json
from typing import Any


SCHEMA = "master.frontier.context.accounting.v1"
GROUPS = {
    "O": "objective",
    "R": "route",
    "I": "route",
    "O!": "route",
    "E": "route",
    "T": "capabilities",
    "K": "capabilities",
    "I!": "policy",
    "G": "policy",
    "C": "continuity",
    "H": "continuity",
    "h": "continuity",
    "d": "continuity",
    "J": "continuity",
    "S": "evidence",
    "D": "evidence",
    "B": "evidence",
    "V": "control",
    "Y": "control",
    "X": "control",
    "N": "control",
    "A": "control",
    "Q": "control",
    "P": "control",
    "L": "control",
    "W": "control",
    "M": "control",
    "U": "control",
    "F": "control",
    "Z": "policy",
}


def _encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:24]


def _record(line: str, index: int) -> dict[str, Any]:
    tag = line.split("\t", 1)[0] if "\t" in line else "schema" if index == 0 else "other"
    return {"tag": tag, "group": GROUPS.get(tag, "other"), "chars": len(line), "digest": _digest(line)}


def measure(request: dict[str, Any], previous: set[str] | None = None) -> tuple[dict[str, Any], set[str]]:
    """Return a compact request breakdown and exact record fingerprints.

    This intentionally applies no budget, clipping, admission, or behavior
    policy. It measures the request already selected by the controller.
    """
    previous = previous or set()
    messages = request.get("messages") if isinstance(request.get("messages"), list) else []
    tools = request.get("tools") if isinstance(request.get("tools"), list) else []
    records: list[dict[str, Any]] = []
    message_chars = 0
    role_chars: dict[str, int] = {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "unknown")[:40]
        content = str(message.get("content") or "")
        message_chars += len(content)
        role_chars[role] = role_chars.get(role, 0) + len(content)
        if role == "user" and content.startswith("MF5/"):
            records.extend(_record(line, index) for index, line in enumerate(content.splitlines()))
    tool_text = _encoded(tools) if tools else ""
    tool_digest = _digest(tool_text) if tool_text else ""
    group_chars: dict[str, int] = {}
    group_records: dict[str, int] = {}
    repeated_chars = 0
    new_chars = 0
    fingerprints: set[str] = set()
    for item in records:
        group = str(item["group"])
        chars = int(item["chars"])
        fingerprint = f"record:{item['digest']}"
        fingerprints.add(fingerprint)
        group_chars[group] = group_chars.get(group, 0) + chars
        group_records[group] = group_records.get(group, 0) + 1
        if fingerprint in previous:
            repeated_chars += chars
        else:
            new_chars += chars
    if tool_digest:
        fingerprint = f"tools:{tool_digest}"
        fingerprints.add(fingerprint)
        if fingerprint in previous:
            repeated_chars += len(tool_text)
        else:
            new_chars += len(tool_text)
    system_chars = role_chars.get("system", 0)
    system_digest = _digest("\n".join(
        str(item.get("content") or "") for item in messages if isinstance(item, dict) and item.get("role") == "system"
    )) if system_chars else ""
    if system_digest:
        fingerprint = f"system:{system_digest}"
        fingerprints.add(fingerprint)
        if fingerprint in previous:
            repeated_chars += system_chars
        else:
            new_chars += system_chars
    serialized_chars = len(_encoded({
        "messages": messages,
        "tools": tools,
        "tool_choice": request.get("tool_choice") or request.get("toolChoice") or "",
        "response_format": request.get("response_format") or request.get("responseFormat") or {},
    }))
    classified_chars = system_chars + sum(group_chars.values()) + len(tool_text)
    return ({
        "schema": SCHEMA,
        "serialized_chars": serialized_chars,
        "classified_chars": classified_chars,
        "message_chars": message_chars,
        "tool_schema_chars": len(tool_text),
        "tool_count": len(tools),
        "record_count": len(records),
        "role_chars": dict(sorted(role_chars.items())),
        "group_chars": dict(sorted(group_chars.items())),
        "group_records": dict(sorted(group_records.items())),
        "repeated_chars": repeated_chars,
        "new_chars": new_chars,
        "unclassified_chars": max(0, serialized_chars - classified_chars),
        "enforced": False,
    }, fingerprints)


def attach_usage(measurement: dict[str, Any], usage: Any) -> dict[str, Any]:
    observed = usage if isinstance(usage, dict) else {}
    return {
        **measurement,
        "provider_usage": {
            key: observed.get(key)
            for key in ("prompt_tokens", "input_tokens", "completion_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "reasoning_tokens")
            if observed.get(key) is not None
        },
    }
