#!/usr/bin/env python3
"""Run the admitted V5 fixture suite and always emit an iterable outcome."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fixture_outcomes import suite_outcome

ROOT = Path(__file__).resolve().parents[2]
LAB = Path(__file__).resolve().parent
OVERLAY = LAB / "staging/avatar-chat-adjudication-v3.sqlite3"
REGISTRY = LAB / "harness-adapters.json"
OUT = ROOT / "reports/context/latest/promoted-v5-fixture-suite-proof.json"


def admitted_fixtures() -> list[tuple[str, str]]:
    with sqlite3.connect(OVERLAY) as connection:
        return connection.execute(
            "select fixture_id,split from fixture_adjudication "
            "where decision='admit' and ranking_allowed=1 order by split,fixture_id"
        ).fetchall()


def load_payload(report: Path) -> tuple[dict[str, Any], list[str]]:
    if not report.is_file():
        return {}, ["fixture orchestrator did not emit a report"]
    try:
        return json.loads(report.read_text(encoding="utf-8")), []
    except (OSError, ValueError) as exc:
        return {}, [f"fixture report is unreadable: {type(exc).__name__}"]


def run_fixture(
    fixture_id: str,
    split: str,
    digest: str,
    candidate_adapter: str | None,
) -> dict[str, Any]:
    report = ROOT / f"reports/context/suites/promoted-v5-{fixture_id}.json"
    command = [
        "python3",
        str(LAB / "live-fixture-orchestrator.py"),
        "--slot",
        "harness-01",
        "--fixture-id",
        fixture_id,
        "--report",
        str(report.relative_to(ROOT)),
    ]
    if candidate_adapter:
        command.extend(["--candidate-adapter", candidate_adapter])
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    payload, blockers = load_payload(report)
    task = payload.get("task") or {}
    lane = payload.get("lane") or {}
    receipts = [item for item in payload.get("gatewayReceipts", []) if item.get("status") == 200]
    blockers.extend(str(item) for item in payload.get("blockers") or [])
    if completed.returncode != 0:
        blockers.append(f"fixture orchestrator exited {completed.returncode}")
    if payload.get("adapterArtifactSha256") != digest:
        blockers.append("candidate artifact digest mismatch")
    satisfactory = payload.get("answerSatisfaction") == "satisfactory"
    promotion_eligible = satisfactory and payload.get("promotionEligible") is True and not blockers
    return {
        "fixtureId": fixture_id,
        "split": split,
        "ok": True,
        "harnessStatus": "completed",
        "operational": payload.get("executionStatus") == "ready",
        "answerSatisfaction": "satisfactory" if promotion_eligible else "unsatisfactory",
        "classification": payload.get("classification") or "live_fixture_answer_unsatisfactory",
        "promotionEligible": promotion_eligible,
        "improvementRequired": not promotion_eligible,
        "executionAllowed": (task.get("adjudication") or {}).get("executionAllowed"),
        "semanticPassed": payload.get("semanticEvaluationPassed"),
        "providerCalls": len(receipts) or int(lane.get("providerCalls") or 0),
        "toolCalls": sum(int(item.get("toolCallCount") or 0) for item in receipts) or int(lane.get("toolCallCount") or 0),
        "promptTokens": sum(int(item.get("promptTokens") or 0) for item in receipts) or int((lane.get("usageTotals") or {}).get("prompt_tokens") or 0),
        "warnings": payload.get("warnings") or [],
        "blockers": blockers,
        "taskDigest": task.get("taskDigest"),
        "artifactDigest": payload.get("adapterArtifactSha256"),
        "report": str(report.relative_to(ROOT)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-adapter")
    args = parser.parse_args()
    started = time.monotonic()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    adapter = registry["adapters"][0]
    if args.candidate_adapter:
        adapter = json.loads((ROOT / args.candidate_adapter).read_text(encoding="utf-8"))
    digest = str(adapter["adapterArtifactSha256"])
    results = [
        run_fixture(fixture_id, split, digest, args.candidate_adapter)
        for fixture_id, split in admitted_fixtures()
    ]
    golden = [row for row in results if row["split"] == "golden"]
    holdout = [row for row in results if row["split"] == "holdout"]
    outcome = suite_outcome(results)
    result = {
        "schema": "wasm-agent.safe-lab.promoted-v5-suite-proof.v2",
        **outcome,
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "durationMs": round((time.monotonic() - started) * 1000),
        "adapterVersion": adapter["adapterVersion"],
        "artifactDigest": digest,
        "fixtureCount": len(results),
        "golden": {"passed": sum(row["promotionEligible"] for row in golden), "total": len(golden)},
        "holdout": {"passed": sum(row["promotionEligible"] for row in holdout), "total": len(holdout)},
        "semanticPassRate": (
            sum(row["semanticPassed"] is True for row in results) / len(results) if results else 0
        ),
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
