#!/usr/bin/env python3
"""Validate a generic brokered live-fixture readiness report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--fixture-id")
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    errors: list[str] = []
    lane = report.get("lane") if isinstance(report.get("lane"), dict) else {}
    task = report.get("task") if isinstance(report.get("task"), dict) else {}
    receipts = report.get("gatewayReceipts") if isinstance(report.get("gatewayReceipts"), list) else []
    if report.get("schema") != "wasm-agent.safe-lab.live-fixture-result.v1":
        errors.append("unexpected report schema")
    if args.fixture_id and (task.get("fixture") or {}).get("id") != args.fixture_id:
        errors.append("fixture id mismatch")
    if report.get("technicalReadinessPassed") is not True or lane.get("readinessCandidatePassed") is not True:
        errors.append("technical readiness did not pass")
    if report.get("model") != "frank/GLM-5.2":
        errors.append("exact model is not proven")
    if not receipts or any(
        item.get("upstreamCalled") is not True
        or item.get("returnedModel") != "frank/GLM-5.2"
        or item.get("status") != 200
        or item.get("contractMatch") is not True
        for item in receipts
    ):
        errors.append("gateway receipts are missing or non-comparable")
    maximum_calls = int((task.get("budgets") or {}).get("maxProviderCalls") or 0)
    if len(receipts) > maximum_calls:
        errors.append("provider call budget exceeded")
    if any(int(item.get("duplicateOrdinal") or 0) > 2 for item in receipts):
        errors.append("identical request duplicate budget exceeded")
    if not (report.get("networkEvidence") or {}).get("directUpstreamBlocked"):
        errors.append("direct lane egress was not proven blocked")
    if report.get("providerCredentialInLane") is not False:
        errors.append("provider credential entered the lane")
    if report.get("cleanupComplete") is not True:
        errors.append("proof-owned resources were not cleaned")
    adjudication = task.get("adjudication") if isinstance(task.get("adjudication"), dict) else {}
    if adjudication.get("semanticCorrectness") == "unresolved" and report.get("rankingAllowed") is not False:
        errors.append("unresolved fixture must remain non-rankable")
    if adjudication.get("semanticCorrectness") == "contract_adjudicated":
        score = report.get("semanticScore") if isinstance(report.get("semanticScore"), dict) else {}
        if score.get("passed") is not True or report.get("rankingAllowed") is not True:
            errors.append("adjudicated fixture did not pass its private semantic contract")
        if score.get("contractSha256") != adjudication.get("expectedContractSha256"):
            errors.append("semantic score contract digest mismatch")
    print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
