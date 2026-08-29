#!/usr/bin/env python3
"""Evaluate claim-risk-proof receipts and prove that unsafe mutants are rejected."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "docs/context/CLAIM_RISK_PROOF_MATRIX.json"
REPORT_PATH = ROOT / "reports/context/latest/claim-risk-proof-result.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OPERATORS = {
    ">=": lambda actual, expected: actual >= expected,
    "<=": lambda actual, expected: actual <= expected,
    "==": lambda actual, expected: actual == expected,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def validate_matrix(document: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        return ["matrix_schema_invalid"]
    claims = document.get("claims")
    if not isinstance(claims, list) or not claims:
        return ["matrix_claims_missing"]
    seen: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            errors.append("matrix_claim_invalid")
            continue
        claim_id = claim.get("id")
        if not isinstance(claim_id, str) or not claim_id or claim_id in seen:
            errors.append("matrix_claim_id_invalid")
        else:
            seen.add(claim_id)
        if not all(isinstance(claim.get(key), value_type) for key, value_type in (
            ("owner", str), ("statement", str), ("risk", dict), ("controls", list),
            ("acceptance", dict), ("invalidation", list),
        )):
            errors.append(f"{claim_id or 'unknown'}:matrix_contract_incomplete")
            continue
        acceptance = claim["acceptance"]
        if not isinstance(acceptance.get("requiredEvidenceClasses"), list) or not acceptance["requiredEvidenceClasses"]:
            errors.append(f"{claim_id}:required_evidence_classes_missing")
        if not isinstance(acceptance.get("minimumIndependentGroups"), int) or acceptance["minimumIndependentGroups"] < 1:
            errors.append(f"{claim_id}:minimum_independent_groups_invalid")
        if not isinstance(acceptance.get("maximumEvidenceAgeSec"), int) or acceptance["maximumEvidenceAgeSec"] < 1:
            errors.append(f"{claim_id}:freshness_window_invalid")
        thresholds = acceptance.get("thresholds")
        if not isinstance(thresholds, list) or not thresholds:
            errors.append(f"{claim_id}:thresholds_missing")
        else:
            for threshold in thresholds:
                if not isinstance(threshold, dict) or threshold.get("operator") not in OPERATORS or not isinstance(threshold.get("metric"), str) or not isinstance(threshold.get("value"), (int, float)):
                    errors.append(f"{claim_id}:threshold_invalid")
    return errors


def evaluate_claim(claim: dict[str, Any], receipt: Any, now: datetime, artifact_root: Path) -> dict[str, Any]:
    failures: list[str] = []
    acceptance = claim["acceptance"]
    if not isinstance(receipt, dict) or receipt.get("claimId") != claim["id"]:
        return {"status": "fail", "failureClasses": ["claim_receipt_mismatch"], "checks": {}}

    sources = receipt.get("evidence")
    if not isinstance(sources, list) or not sources:
        sources = []
        failures.append("evidence_missing")
    classes: set[str] = set()
    groups: set[str] = set()
    source_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            failures.append("evidence_source_invalid")
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id or source_id in source_ids:
            failures.append("evidence_source_id_invalid")
        else:
            source_ids.add(source_id)
        evidence_class = source.get("class")
        if isinstance(evidence_class, str):
            classes.add(evidence_class)
        group = source.get("independentGroup")
        if isinstance(group, str) and group:
            groups.add(group)
        artifact = source.get("artifact")
        if not isinstance(artifact, str) or not artifact:
            failures.append("evidence_artifact_missing")
        else:
            candidate = (artifact_root / artifact).resolve()
            try:
                candidate.relative_to(artifact_root.resolve())
            except ValueError:
                failures.append("evidence_artifact_out_of_scope")
            else:
                if not candidate.is_file():
                    failures.append("evidence_artifact_missing")
                elif isinstance(source.get("sha256"), str) and SHA256_RE.fullmatch(source["sha256"]):
                    actual_digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
                    if actual_digest != source["sha256"]:
                        failures.append("evidence_digest_mismatch")
        if not isinstance(source.get("sha256"), str) or not SHA256_RE.fullmatch(source["sha256"]):
            failures.append("evidence_digest_invalid")
        observed_at = parse_time(source.get("observedAt"))
        if observed_at is None:
            failures.append("evidence_timestamp_invalid")
        else:
            age = (now - observed_at).total_seconds()
            if age < 0 or age > acceptance["maximumEvidenceAgeSec"]:
                failures.append("evidence_stale")

    missing_classes = sorted(set(acceptance["requiredEvidenceClasses"]) - classes)
    if missing_classes:
        failures.append("evidence_class_missing")
    if len(groups) < acceptance["minimumIndependentGroups"]:
        failures.append("evidence_independence_insufficient")

    metrics = receipt.get("metrics") if isinstance(receipt.get("metrics"), dict) else {}
    threshold_checks: list[dict[str, Any]] = []
    for threshold in acceptance["thresholds"]:
        metric = threshold["metric"]
        actual = metrics.get(metric)
        passed = isinstance(actual, (int, float)) and not isinstance(actual, bool) and OPERATORS[threshold["operator"]](actual, threshold["value"])
        threshold_checks.append({**threshold, "actual": actual, "passed": passed})
        if not passed:
            failures.append("acceptance_threshold_failed")

    failure_classes = sorted(set(failures))
    return {
        "status": "pass" if not failure_classes else "fail",
        "failureClasses": failure_classes,
        "checks": {
            "evidenceClasses": sorted(classes),
            "missingEvidenceClasses": missing_classes,
            "independentGroups": len(groups),
            "thresholds": threshold_checks,
        },
    }


def reference_receipt(now: datetime, artifact_root: Path) -> dict[str, Any]:
    observed = now.isoformat().replace("+00:00", "Z")
    artifacts = {
        "contract.json": b'{"contract":"v1"}\n',
        "runtime.json": b'{"runtime":"pass"}\n',
        "behavior.json": b'{"behavior":"pass"}\n',
    }
    for name, content in artifacts.items():
        (artifact_root / name).write_bytes(content)
    return {
        "claimId": "production-claim-gate-enforced",
        "evidence": [
            {"id": "source-contract", "class": "static", "independentGroup": "contract", "artifact": "contract.json", "sha256": hashlib.sha256(artifacts["contract.json"]).hexdigest(), "observedAt": observed},
            {"id": "runtime-receipt", "class": "runtime", "independentGroup": "runtime", "artifact": "runtime.json", "sha256": hashlib.sha256(artifacts["runtime.json"]).hexdigest(), "observedAt": observed},
            {"id": "behavior-probe", "class": "behavioral", "independentGroup": "watcher", "artifact": "behavior.json", "sha256": hashlib.sha256(artifacts["behavior.json"]).hexdigest(), "observedAt": observed},
        ],
        "metrics": {"required_metric_coverage": 1.0, "unauthorized_actions": 0, "false_passes": 0},
    }


def run_self_test(claim: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory() as temporary:
        artifact_root = Path(temporary)
        base = reference_receipt(now, artifact_root)
        cases: list[tuple[str, dict[str, Any], str | None]] = [("healthy", base, None)]
        stale = copy.deepcopy(base)
        stale["evidence"][1]["observedAt"] = "2000-01-01T00:00:00Z"
        cases.append(("stale-evidence", stale, "evidence_stale"))
        missing = copy.deepcopy(base)
        missing["evidence"] = missing["evidence"][:2]
        cases.append(("missing-class", missing, "evidence_class_missing"))
        regression = copy.deepcopy(base)
        regression["metrics"]["unauthorized_actions"] = 1
        cases.append(("threshold-regression", regression, "acceptance_threshold_failed"))
        digest = copy.deepcopy(base)
        digest["evidence"][0]["sha256"] = "0" * 64
        cases.append(("artifact-tamper", digest, "evidence_digest_mismatch"))

        results = []
        for case_id, receipt, expected_failure in cases:
            evaluation = evaluate_claim(claim, receipt, now, artifact_root)
            detected = evaluation["status"] == "pass" if expected_failure is None else expected_failure in evaluation["failureClasses"]
            results.append({"id": case_id, "expectedFailure": expected_failure, "detected": detected, "evaluation": evaluation})
        return results


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, default=MATRIX_PATH)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--claim-id", default="production-claim-gate-enforced")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    started = time.monotonic()
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    errors = validate_matrix(matrix)
    claims = {claim.get("id"): claim for claim in matrix.get("claims", []) if isinstance(claim, dict)} if not errors else {}
    claim = claims.get(args.claim_id)
    cases: list[dict[str, Any]] = []
    if claim is None:
        errors.append("claim_not_found")
    elif args.self_test:
        cases = run_self_test(claim, utc_now())
        if not all(case["detected"] for case in cases):
            errors.append("fault_injection_not_detected")
    elif args.receipt:
        evaluation = evaluate_claim(claim, json.loads(args.receipt.read_text(encoding="utf-8")), utc_now(), args.receipt.parent)
        cases = [{"id": "receipt", "expectedFailure": None, "detected": evaluation["status"] == "pass", "evaluation": evaluation}]
        if evaluation["status"] != "pass":
            errors.extend(evaluation["failureClasses"])
    else:
        errors.append("receipt_or_self_test_required")

    report = {
        "status": "pass" if not errors else "fail",
        "promiseId": "claim-risk-proof-gate-e2e",
        "claim": claim["statement"] if claim else args.claim_id,
        "durationMs": round((time.monotonic() - started) * 1000),
        "evidence": [str(args.matrix), str(args.report)],
        "summary": "Claim-risk-proof gate and injected-failure detection passed" if not errors else "Claim-risk-proof gate failed",
        "failureClass": errors[0] if errors else None,
        "errors": sorted(set(errors)),
        "cases": cases,
        "nextSuggestedSteps": [] if not errors else ["Inspect the first failed contract or fault-injection case."],
    }
    write_report(args.report, report)
    print(f"Claim-risk-proof gate: {report['status'].upper()}")
    print(f"Report JSON: {args.report}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
