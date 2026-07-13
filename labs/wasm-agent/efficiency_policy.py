#!/usr/bin/env python3
"""Shared non-fatal efficiency warnings for comparable safe-lab fixture runs."""

from __future__ import annotations

from typing import Any


SELF_CONTAINED_CLASSES = {"conversation", "general_conversation"}


def warnings_for(task: dict[str, Any], receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    request_class = str((task.get("fixture") or {}).get("requestClass") or "")
    if request_class not in SELF_CONTAINED_CLASSES:
        return []
    successful = [item for item in receipts if item.get("upstreamCalled") and item.get("status") == 200]
    warnings: list[dict[str, Any]] = []
    tool_calls = sum(int(item.get("toolCallCount") or 0) for item in successful)
    if tool_calls:
        tool_names = sorted({
            str(name)[:80]
            for item in successful
            for name in (item.get("toolNames") if isinstance(item.get("toolNames"), list) else [])
            if str(name)
        })[:20]
        warnings.append({
            "code": "unnecessary_tool_use_for_self_contained_conversation",
            "severity": "warning",
            "toolCallCount": tool_calls,
            "toolNames": tool_names,
            "providerCallCount": len(successful),
            "reason": "The admitted self-contained conversation required a direct answer but the harness requested tools.",
        })
    elif len(successful) > 1:
        warnings.append({
            "code": "unnecessary_auxiliary_provider_call_for_self_contained_conversation",
            "severity": "warning",
            "providerCallCount": len(successful),
            "distinctRequestCount": len({str(item.get("requestSha256") or "") for item in successful}),
            "reason": "The admitted self-contained conversation used multiple distinct provider calls without a tool loop.",
        })
    prompt_tokens = sum(int(item.get("promptTokens") or 0) for item in successful)
    output_allowance = int((task.get("budgets") or {}).get("maxOutputTokensPerCall") or 1024)
    prompt_warning_threshold = max(2048, output_allowance * 8)
    if prompt_tokens > prompt_warning_threshold:
        warnings.append({
            "code": "excessive_prompt_context_for_self_contained_conversation",
            "severity": "warning",
            "promptTokens": prompt_tokens,
            "warningThresholdTokens": prompt_warning_threshold,
            "providerCallCount": len(successful),
            "reason": "The admitted self-contained conversation consumed disproportionate prompt context for a direct answer.",
        })
    return warnings
