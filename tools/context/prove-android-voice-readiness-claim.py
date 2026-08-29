#!/usr/bin/env python3
"""Project Android voice readiness evidence into the generic claim-risk-proof gate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "docs/context/CLAIM_RISK_PROOF_MATRIX.json"
READINESS_PATH = ROOT / "reports/context/latest/wasm-agent-product-readiness-result.json"
RECEIPT_PATH = ROOT / "reports/context/latest/android-voice-claim-receipt.json"
REPORT_PATH = ROOT / "reports/context/latest/android-voice-claim-gate-result.json"
GATE_PATH = ROOT / "tools/context/prove-claim-risk-proof.py"

SPEC = importlib.util.spec_from_file_location("claim_risk_proof_gate", GATE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("claim-risk-proof gate import unavailable")
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def numeric_bool(value: Any) -> int | None:
    return int(value) if isinstance(value, bool) else None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_artifact(root: Path, reference: str) -> Path | None:
    candidate = (root / reference).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def artifact_time(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def build_receipt(readiness: dict[str, Any], root: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    journey = readiness.get("journeys", {}).get("android-voice-agent")
    if not isinstance(journey, dict):
        return {"claimId": "android-voice-production-ready", "evidence": [], "metrics": {}}, ["android_voice_journey_missing"]

    evidence = []
    for item in journey.get("evidence", []):
        if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
            errors.append("android_evidence_reference_invalid")
            continue
        artifact = resolve_artifact(root, item["ref"])
        if artifact is None:
            errors.append("android_evidence_artifact_missing")
            continue
        evidence_class = item.get("class")
        if item.get("promiseId") == "android-shell-v2-wake-loop":
            evidence_class = "runtime"
        evidence.append({
            "id": item.get("promiseId"),
            "class": evidence_class,
            "independentGroup": item.get("promiseId"),
            "artifact": str(artifact.relative_to(root)),
            "sha256": sha256(artifact),
            "observedAt": item.get("observedAt") or artifact_time(artifact),
        })

    metrics = journey.get("metrics") if isinstance(journey.get("metrics"), dict) else {}
    voice = metrics.get("voice") if isinstance(metrics.get("voice"), dict) else {}
    completeness = metrics.get("evidenceCompleteness") if isinstance(metrics.get("evidenceCompleteness"), dict) else {}
    evidence_items = journey.get("evidence") if isinstance(journey.get("evidence"), list) else []
    all_evidence_pass = bool(evidence_items) and all(
        item.get("status") == "pass" and item.get("freshness") == "fresh"
        for item in evidence_items if isinstance(item, dict)
    )
    normalized_metrics = {
        "journey_pass": int(journey.get("status") == "pass"),
        "evidence_all_pass": int(all_evidence_pass),
        "required_metric_coverage": completeness.get("ratio"),
        "positive_trial_count": voice.get("positiveTrialCount"),
        "negative_trial_count": voice.get("negativeTrialCount"),
        "duplicate_wake_count": voice.get("duplicateWakeCount"),
        "false_wake_count": voice.get("falseWakeCount"),
        "effective_wake_threshold": voice.get("effectiveWakeThreshold"),
        "responsiveness_healthy": numeric_bool(voice.get("responsivenessHealthy")),
        "wake_to_avatar_ms": voice.get("wakeToAvatarMs"),
        "wake_to_listening_ms": voice.get("wakeToListeningMs"),
        "transcription_ms": voice.get("transcriptionMs"),
        "routing_ms": voice.get("routingMs"),
        "acknowledgement_ms": voice.get("acknowledgementMs"),
        "unauthorized_actions": metrics.get("unauthorizedActionCount"),
    }
    return {"claimId": "android-voice-production-ready", "evidence": evidence, "metrics": normalized_metrics}, errors


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--matrix", type=Path, default=MATRIX_PATH)
    parser.add_argument("--readiness", type=Path, default=READINESS_PATH)
    parser.add_argument("--receipt", type=Path, default=RECEIPT_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    started = time.monotonic()

    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    matrix_errors = gate.validate_matrix(matrix)
    claims = {item.get("id"): item for item in matrix.get("claims", []) if isinstance(item, dict)}
    claim = claims.get("android-voice-production-ready")
    readiness = json.loads(args.readiness.read_text(encoding="utf-8"))
    receipt, adapter_errors = build_receipt(readiness, args.root)
    write_json(args.receipt, receipt)
    evaluation = gate.evaluate_claim(claim, receipt, gate.utc_now(), args.root) if claim and not matrix_errors else {
        "status": "fail", "failureClasses": ["android_claim_contract_invalid"], "checks": {}
    }
    errors = matrix_errors + adapter_errors
    status = evaluation["status"] if not errors else "fail"
    failure_classes = sorted(set(errors + evaluation.get("failureClasses", [])))
    report = {
        "status": status,
        "promiseId": "android-voice-claim-risk-proof-gate",
        "claim": claim["statement"] if claim else "android-voice-production-ready",
        "durationMs": round((time.monotonic() - started) * 1000),
        "evidence": [str(args.readiness), str(args.receipt)] + [item["artifact"] for item in receipt["evidence"]],
        "summary": "Android voice production-readiness claim passed" if status == "pass" else "Android voice production-readiness claim rejected",
        "failureClass": failure_classes[0] if failure_classes else None,
        "failureClasses": failure_classes,
        "gate": evaluation,
        "sourceJourney": {
            "runId": readiness.get("runId"),
            "status": readiness.get("journeys", {}).get("android-voice-agent", {}).get("status"),
            "failureClass": readiness.get("journeys", {}).get("android-voice-agent", {}).get("failureClass"),
        },
        "nextSuggestedSteps": [] if status == "pass" else [
            "Refresh the Android voice journey through the authorized Windows bridge; do not weaken thresholds or infer missing metrics."
        ],
    }
    write_json(args.report, report)
    print(f"Android voice claim gate: {status.upper()}")
    print(f"Report JSON: {args.report}")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
