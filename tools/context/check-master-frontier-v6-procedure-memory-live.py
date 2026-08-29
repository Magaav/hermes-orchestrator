#!/usr/bin/env python3
"""Validate three serialized live exact-read procedure-memory reports."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "reports/context/latest/master-frontier-v6-procedure-memory-live.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs=3)
    args = parser.parse_args()
    reports = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.reports]
    states = [str((item.get("procedure_memory") or {}).get("state") or "") for item in reports]
    calls = [int(item.get("provider_calls") or 0) for item in reports]
    tokens = [int((item.get("token_usage") or {}).get("total_tokens") or 0) for item in reports]
    objective_digests = {
        str((item.get("procedure_memory") or {}).get("objective_sha256") or "") for item in reports
    }
    checks = {
        "allRunsPassed": all(item.get("ok") is True for item in reports),
        "crossSession": len({str(item.get("session_id") or "") for item in reports}) == 3,
        "distinctRuns": len({str(item.get("run_id") or "") for item in reports}) == 3,
        "sameObjectiveDigest": len(objective_digests) == 1 and "" not in objective_digests,
        "calibrationSequence": states == ["candidate", "promoted", "replayed"],
        "providerCallSequence": calls == [1, 1, 0],
        "warmTokensZero": tokens[2] == 0,
        "freshCapabilityEachRun": all(item.get("capability_ok") is True for item in reports),
        "freshProofEachRun": all(item.get("proof_verified") is True for item in reports),
        "correctNonemptyAnswerEachRun": all(bool(str(item.get("reply") or "").strip()) for item in reports),
        "noFilesChanged": all(not (item.get("changed_files") or []) for item in reports),
    }
    result = {
        "schema": "master.frontier.v6.procedure-memory-live-proof.v1",
        "ok": all(checks.values()),
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "runIds": [item["run_id"] for item in reports],
        "states": states, "providerCalls": calls, "totalTokens": tokens,
        "durationsMs": [int(item.get("duration_ms") or 0) for item in reports],
        "objectiveSha256": next(iter(objective_digests), ""),
        "checks": checks,
        "sourceReports": [str(Path(path).resolve()) for path in args.reports],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
