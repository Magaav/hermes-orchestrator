#!/usr/bin/env python3
"""Rank proven outcomes; expose strategy candidates only with trajectory proof."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from efficiency_policy import warnings_for
from golden_pattern_extractor import extract


SLOTS = {f"harness-{index:02d}" for index in range(1, 10)}


def inverse(values: list[int], value: int) -> float:
    low, high = min(values), max(values)
    return 1.0 if high == low else 1.0 - (value - low) / (high - low)


def rank(report: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if (
        report.get("status") != "benchmark_complete"
        or report.get("semanticAllPassed") is not True
        or report.get("rankingAllowed") is not True
    ):
        errors.append("benchmark is not admitted for ranking")
    results = report.get("results") if isinstance(report.get("results"), list) else []
    receipts = report.get("gatewayReceipts") if isinstance(report.get("gatewayReceipts"), list) else []
    task = report.get("task") if isinstance(report.get("task"), dict) else {}
    slots = {item.get("slot") for item in results if isinstance(item, dict)}
    attributed = {item.get("laneId") for item in receipts if isinstance(item, dict)}
    if len(results) != 9 or slots != SLOTS:
        errors.append("nine unique lanes required")
    if not attributed.issubset(slots) or not slots.issubset(attributed):
        errors.append("every receipt must have an exact registered lane attribution")

    rows: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        lane = item.get("lane") if isinstance(item.get("lane"), dict) else {}
        slot = item.get("slot")
        own = [
            receipt for receipt in receipts
            if isinstance(receipt, dict) and receipt.get("laneId") == slot
            and receipt.get("status") == 200 and receipt.get("upstreamCalled") is True
        ]
        if not own or any(
            isinstance(receipt.get("toolCallCount"), bool)
            or not isinstance(receipt.get("toolCallCount"), (int, float))
            for receipt in own
        ):
            errors.append(f"tool visibility is unknown for {slot}")
        semantic = (item.get("answer") or {}).get("semantic") if isinstance(item.get("answer"), dict) else {}
        semantic = semantic if isinstance(semantic, dict) else {}
        rows.append({
            "slot": slot, "adapter": lane.get("adapter"),
            "semanticPassed": semantic.get("passed") is True,
            "latencyMs": int(lane.get("durationMs") or 0),
            "promptTokens": sum(int(receipt.get("promptTokens") or 0) for receipt in own),
            "completionTokens": sum(int(receipt.get("completionTokens") or 0) for receipt in own),
            "providerCalls": len(own),
            "toolCalls": sum(int(receipt.get("toolCallCount") or 0) for receipt in own),
            "warnings": warnings_for(task, own),
        })
    if any(not row["semanticPassed"] for row in rows):
        errors.append("semantic failure forbids ranking")
    if errors:
        return {"schema": "wasm-agent.safe-lab.nine-lane-ranking.v1", "ok": False, "errors": errors}

    latency = [row["latencyMs"] for row in rows]
    prompts = [row["promptTokens"] for row in rows]
    calls = [row["providerCalls"] for row in rows]
    tools = [row["toolCalls"] for row in rows]
    warning_counts = [len(row["warnings"]) for row in rows]
    for row in rows:
        parts = {
            "latency": 35 * inverse(latency, row["latencyMs"]),
            "promptEfficiency": 30 * inverse(prompts, row["promptTokens"]),
            "callEfficiency": 15 * inverse(calls, row["providerCalls"]),
            "toolEfficiency": 10 * inverse(tools, row["toolCalls"]),
            "warningCleanliness": 10 * inverse(warning_counts, len(row["warnings"])),
        }
        row["scoreParts"] = {key: round(value, 3) for key, value in parts.items()}
        row["efficiencyScore"] = round(sum(parts.values()), 3)
    rows.sort(key=lambda row: (-row["efficiencyScore"], row["latencyMs"], str(row["adapter"])))
    for position, row in enumerate(rows, 1):
        row["rank"] = position

    pattern_evidence = extract([report])
    strategy_comparable = pattern_evidence["eligibleTrajectories"] == len(results)
    candidates = pattern_evidence["patterns"]
    return {
        "schema": "wasm-agent.safe-lab.nine-lane-ranking.v1", "ok": True,
        "classification": "nine_lane_ranking_pass", "sourceRunId": report.get("runId"),
        "semanticGate": "all_passed",
        "comparability": {"efficiency": True, "strategy": strategy_comparable},
        "weights": {"latency": 35, "promptEfficiency": 30, "callEfficiency": 15, "toolEfficiency": 10, "warningCleanliness": 10},
        "ranking": rows, "patternEvidence": pattern_evidence, "goldenPatternCandidates": candidates,
        "promotionDecision": "candidate_patterns_only_loop4_regression_required" if candidates else "cross_fixture_strategy_evidence_required",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--output", default="reports/context/latest/nine-lane-ranking-result.json")
    args = parser.parse_args()
    result = rank(json.loads(Path(args.report).read_text(encoding="utf-8")))
    if result["ok"]:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
