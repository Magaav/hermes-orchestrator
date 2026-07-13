#!/usr/bin/env python3
"""Deterministic checks for shared safe-lab efficiency warning classification."""

from __future__ import annotations

import json
from pathlib import Path

from efficiency_policy import warnings_for


def main() -> int:
    conversation = {"fixture": {"requestClass": "conversation"}, "budgets": {"maxOutputTokensPerCall": 1024}}
    tool_receipts = [{"upstreamCalled": True, "status": 200, "promptTokens": 3787, "toolCallCount": 3, "toolNames": ["Bash", "Read"]}]
    context_receipts = [{"upstreamCalled": True, "status": 200, "promptTokens": 10427, "toolCallCount": 0, "toolNames": []}]
    auxiliary_receipts = [
        {"upstreamCalled": True, "status": 200, "requestSha256": "title", "promptTokens": 571, "toolCallCount": 0},
        {"upstreamCalled": True, "status": 200, "requestSha256": "answer", "promptTokens": 6770, "toolCallCount": 0},
    ]
    grounded = {"fixture": {"requestClass": "repository_change"}, "budgets": {"maxOutputTokensPerCall": 1024}}
    tool = warnings_for(conversation, tool_receipts)
    context = warnings_for(conversation, context_receipts)
    auxiliary = warnings_for(conversation, auxiliary_receipts)
    errors = []
    if [item.get("code") for item in tool] != ["unnecessary_tool_use_for_self_contained_conversation"]:
        errors.append("tool-use warning classification failed")
    if tool[0].get("toolNames") != ["Bash", "Read"]:
        errors.append("bounded tool-name evidence failed")
    if [item.get("code") for item in context] != ["excessive_prompt_context_for_self_contained_conversation"]:
        errors.append("context-cost warning classification failed")
    if context[0].get("warningThresholdTokens") != 8192:
        errors.append("context-cost threshold failed")
    if [item.get("code") for item in auxiliary] != ["unnecessary_auxiliary_provider_call_for_self_contained_conversation"]:
        errors.append("auxiliary provider-call warning classification failed")
    if warnings_for(grounded, tool_receipts + context_receipts):
        errors.append("non-self-contained fixture was warned")
    result = {
        "schema": "wasm-agent.safe-lab.efficiency-policy-check.v1",
        "ok": not errors,
        "checks": {"unnecessaryTools": True, "boundedToolNames": True, "excessiveContext": True, "auxiliaryProviderCall": True, "nonConversationExcluded": True},
        "errors": errors,
    }
    report = Path(__file__).resolve().parents[2] / "reports/context/latest/efficiency-policy-result.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
