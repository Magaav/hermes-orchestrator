#!/usr/bin/env python3
"""Compose existing wasm-agent proof promises into one readiness evaluation.

The evaluator deliberately keeps product behavior in the owning proof scripts.
By default it only inspects their artifacts.  ``--run`` opt-ins serialize the
registered child commands before the same normalization pass.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "docs/context/HARNESS_PROMISES.json"
SCHEMA_PATH = ROOT / "docs/context/PRODUCT_READINESS_RESULT_SCHEMA.json"
LATEST_REPORT = ROOT / "reports/context/latest/wasm-agent-product-readiness-result.json"
LATEST_SUMMARY = ROOT / "reports/context/latest/wasm-agent-product-readiness-summary.md"
RUNS_ROOT = ROOT / "reports/context/product-readiness"

SCHEMA_ID = "wasm-agent.product-readiness.result.v1"
CANONICAL_STATUSES = {
    "pass", "fail", "running", "blocked", "stale", "inconclusive",
    "invalid-environment", "needs-human-proof",
}


@dataclass(frozen=True)
class EvidenceSpec:
    promise_id: str
    artifact: str
    required: bool = True


@dataclass(frozen=True)
class JourneySpec:
    journey_id: str
    owner: str
    claim: str
    verification_level: str
    evidence: tuple[EvidenceSpec, ...]
    run_promises: tuple[str, ...]
    required_metrics: tuple[str, ...]


ACTION_METRICS = (
    "incorrectActionCount", "unauthorizedActionCount", "humanInterventionCount",
    "durationMs", "providerCalls", "exactTokenUsage",
)

JOURNEYS = (
    JourneySpec(
        journey_id="repository-agent",
        owner="plugins/wasm-agent/server/master_frontier/v6",
        claim="A real V6 head completes bounded repository read, preconditioned edit, registered check, diff, and revision-bound proof.",
        verification_level="local-runtime",
        evidence=(EvidenceSpec(
            "master-frontier-v6-live-model-self-host",
            "reports/context/latest/master-frontier-v6-live-model-result.json",
        ),),
        run_promises=("master-frontier-v6-live-model-self-host",),
        required_metrics=ACTION_METRICS,
    ),
    JourneySpec(
        journey_id="android-voice-agent",
        owner="plugins/wasm-agent; native/android; native/windows",
        claim="One Alexa stimulus wakes exactly once, gives immediate avatar feedback, captures and routes speech, and acknowledges the resulting action.",
        verification_level="installed-device-runtime",
        evidence=(
            EvidenceSpec(
                "production-native-control-authority",
                "reports/context/latest/production-native-control-authority.json",
            ),
            EvidenceSpec(
                "windows-hot-shell-proof",
                "reports/windows/latest/hot-shell-proof-result.json",
            ),
            EvidenceSpec(
                "android-shell-v2-wake-loop",
                "reports/android/wake-shell-v2/latest-shell-v2-wake-loop.json",
            ),
        ),
        # The shell-v2 wrapper already runs its Windows hot-shell prerequisite.
        run_promises=("production-native-control-authority", "android-shell-v2-wake-loop"),
        required_metrics=("durationMs", "stageLatenciesMs") + (
            "positiveTrialCount", "negativeTrialCount", "duplicateWakeCount",
            "falseWakeCount", "requestedWakeThreshold", "effectiveWakeThreshold",
            "responsivenessHealthy", "wakeToAvatarMs", "wakeToListeningMs",
            "transcriptionMs", "routingMs", "acknowledgementMs",
        ),
    ),
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root is not an object")
    return value


def pointer(value: Any, path: str, default: Any = None) -> Any:
    current = value
    for raw_part in path.strip("/").split("/") if path.strip("/") else []:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return default
    return current


def first(value: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        found = pointer(value, path)
        if found is not None:
            return found
    return None


def registry() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    document = read_json(REGISTRY_PATH)
    indexed = {
        str(item.get("id")): item
        for item in document.get("promises", [])
        if isinstance(item, dict) and item.get("id")
    }
    return document, indexed


def artifact_status(payload: dict[str, Any]) -> str:
    status = payload.get("status")
    if status in CANONICAL_STATUSES:
        return str(status)
    if payload.get("ok") is True:
        return "pass"
    if payload.get("ok") is False:
        return "fail"
    classification = str(payload.get("classification") or "")
    if classification.endswith("_pass"):
        return "pass"
    if classification.endswith("_fail"):
        return "fail"
    return "inconclusive"


def artifact_checked_at(path: Path, payload: dict[str, Any]) -> datetime:
    raw = first(payload, "/checkedAt", "/finishedAt")
    if raw:
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def concrete_invalidation_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        if not pattern or pattern.startswith("/") or any(char.isspace() for char in pattern):
            continue
        try:
            matches = ROOT.glob(pattern)
        except (ValueError, OSError):
            continue
        for path in matches:
            if path.is_file():
                paths.append(path)
    return paths


def evidence_result(spec: EvidenceSpec, promises: dict[str, dict[str, Any]]) -> dict[str, Any]:
    path = ROOT / spec.artifact
    promise = promises.get(spec.promise_id, {})
    base: dict[str, Any] = {
        "promiseId": spec.promise_id,
        "artifact": spec.artifact,
        "required": spec.required,
        "status": "blocked",
        "observedStatus": "blocked",
        "sha256": None,
        "observedAt": None,
        "fresh": False,
        "invalidatedByPaths": [],
        "failureClass": None,
        "summary": None,
    }
    if not path.exists():
        base.update({
            "failureClass": "evidence_artifact_missing",
            "summary": f"Missing registered artifact {spec.artifact}",
        })
        return base
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("JSON root is not an object")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        base.update({
            "status": "fail", "observedStatus": "fail",
            "failureClass": "evidence_artifact_invalid",
            "summary": str(error)[:240],
        })
        return base

    observed = artifact_status(payload)
    checked_at = artifact_checked_at(path, payload)
    invalidators = concrete_invalidation_paths(list(promise.get("invalidatedBy") or []))
    newer = sorted(
        (item for item in invalidators if item.stat().st_mtime > path.stat().st_mtime + 0.001),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    status = "stale" if newer else observed
    failure_class = first(payload, "/failureClass", "/error/code", "/error/type")
    if newer:
        failure_class = "evidence_invalidated"
    base.update({
        "status": status,
        "observedStatus": observed,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "observedAt": iso(checked_at),
        "fresh": not newer,
        "invalidatedByPaths": [relative(item) for item in newer[:16]],
        "failureClass": str(failure_class) if failure_class else None,
        "summary": str(payload.get("summary") or payload.get("classification") or "")[:320] or None,
        "_payload": payload,
    })
    return base


def empty_metrics() -> dict[str, Any]:
    return {
        "incorrectActionCount": None,
        "unauthorizedActionCount": None,
        "humanInterventionCount": None,
        "durationMs": None,
        "stageLatenciesMs": {},
        "providerCalls": None,
        "exactTokenUsage": None,
        "retryCount": None,
        "restartRecoverySucceeded": None,
        "clientAcknowledged": None,
        "commandReceiptVerified": None,
        "positiveTrialCount": None,
        "negativeTrialCount": None,
        "duplicateWakeCount": None,
        "falseWakeCount": None,
        "requestedWakeThreshold": None,
        "effectiveWakeThreshold": None,
        "responsivenessHealthy": None,
        "wakeToAvatarMs": None,
        "wakeToListeningMs": None,
        "transcriptionMs": None,
        "routingMs": None,
        "acknowledgementMs": None,
    }


def repository_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    metrics = empty_metrics()
    token_usage = payload.get("tokenUsage") if isinstance(payload.get("tokenUsage"), dict) else {}
    exact_usage = None
    if token_usage.get("exact") is True and isinstance(token_usage.get("total_tokens"), int):
        exact_usage = {
            "exact": True,
            "inputTokens": token_usage.get("input_tokens"),
            "outputTokens": token_usage.get("output_tokens"),
            "totalTokens": token_usage["total_tokens"],
        }
    metrics.update({
        "incorrectActionCount": 0 if payload.get("changedFiles") == ["a.py"] else None,
        "unauthorizedActionCount": 0 if payload.get("changedFiles") == ["a.py"] else None,
        "humanInterventionCount": 0 if payload.get("ok") is True else None,
        "durationMs": payload.get("durationMs"),
        "providerCalls": first(payload, "/providerCalls", "/tokenUsage/calls"),
        "exactTokenUsage": exact_usage,
    })
    return metrics


def electron_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    metrics = empty_metrics()
    token_usage = payload.get("tokenUsage") if isinstance(payload.get("tokenUsage"), dict) else {}
    exact_usage = None
    if token_usage.get("exact") is True and isinstance(token_usage.get("total_tokens"), int):
        exact_usage = {
            "exact": True,
            "inputTokens": token_usage.get("input_tokens"),
            "outputTokens": token_usage.get("output_tokens"),
            "totalTokens": token_usage["total_tokens"],
        }
    performance = payload.get("performance") if isinstance(payload.get("performance"), dict) else {}
    phases = performance.get("phases") if isinstance(performance.get("phases"), dict) else {}
    metrics.update({
        "incorrectActionCount": 0 if payload.get("changedFiles") == [] else None,
        "unauthorizedActionCount": 0 if payload.get("changedFiles") == [] else None,
        "humanInterventionCount": 0 if payload.get("ok") is True else None,
        "durationMs": payload.get("durationMs"),
        "stageLatenciesMs": phases,
        "providerCalls": payload.get("providerCalls"),
        "exactTokenUsage": exact_usage,
        "clientAcknowledged": payload.get("clientWidgetAcknowledged"),
        "commandReceiptVerified": payload.get("clientCommandArtifactVerified"),
    })
    return metrics


def android_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    metrics = empty_metrics()
    phases = payload.get("phases") if isinstance(payload.get("phases"), list) else []
    stage_latencies = {
        str(item.get("label")): item.get("durationMs")
        for item in phases
        if isinstance(item, dict) and item.get("label") and isinstance(item.get("durationMs"), (int, float))
    }
    policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
    metrics.update({
        "durationMs": payload.get("durationMs"),
        "stageLatenciesMs": stage_latencies,
        "requestedWakeThreshold": policy.get("wakeThreshold"),
    })
    return metrics


def combine_status(evidence: list[dict[str, Any]]) -> str:
    statuses = [item["status"] for item in evidence if item.get("required")]
    for candidate in (
        "fail", "stale", "invalid-environment", "needs-human-proof",
        "blocked", "running", "inconclusive",
    ):
        if candidate in statuses:
            return candidate
    return "pass" if statuses and all(item == "pass" for item in statuses) else "inconclusive"


def measured_metric(metrics: dict[str, Any], name: str) -> bool:
    value = metrics.get(name)
    if name == "stageLatenciesMs":
        return isinstance(value, dict) and bool(value)
    return value is not None


def evidence_class(promise: dict[str, Any]) -> str:
    classes = list(promise.get("evidenceClasses") or [])
    for candidate in ("production", "behavioral", "runtime", "package", "static", "human"):
        if candidate in classes:
            return candidate
    return "static"


def public_evidence(item: dict[str, Any], promise: dict[str, Any]) -> dict[str, Any]:
    return {
        "ref": item["artifact"],
        "sha256": item.get("sha256"),
        "class": evidence_class(promise),
        "freshness": "fresh" if item.get("fresh") else ("stale" if item.get("status") == "stale" else "unknown"),
        "observedAt": item.get("observedAt"),
        "promiseId": item.get("promiseId"),
        "required": item.get("required") is True,
        "status": item.get("status"),
        "observedStatus": item.get("observedStatus"),
        "failureClass": item.get("failureClass"),
        "invalidatedByPaths": item.get("invalidatedByPaths") or [],
        "summary": item.get("summary"),
    }


def blocker_kind(status: str, failure_class: str | None) -> str:
    if status == "stale":
        return "stale-evidence"
    if status == "invalid-environment":
        return "invalid-environment"
    if status == "needs-human-proof":
        return "needs-human-proof"
    if failure_class in {
        "android_device_missing", "bridge_unreachable", "device_disconnected",
        "device_unreachable", "windows_client_missing",
    }:
        return "missing-access"
    if failure_class in {"evidence_artifact_missing", "required_metrics_missing"}:
        return "missing-observability"
    return "missing-primitive"


def blocker_guidance(status: str, failure_class: str | None, failure_stage: str | None) -> tuple[str, str]:
    if status == "stale":
        return (
            failure_stage or "fresh registered evidence",
            "Rerun the invalidated registered promise before making a current readiness claim.",
        )
    if failure_class == "android_device_missing":
        return (
            "An authorized Android device visible to ADB through the installed Windows bridge.",
            "Restore Android ADB visibility on the installed Windows bridge, then rerun the registered shell-v2 wake promise.",
        )
    return (
        failure_stage or "complete readiness evidence",
        "Collect the missing registered proof and metrics without weakening the acceptance contract.",
    )


def journey_result(spec: JourneySpec, promises: dict[str, dict[str, Any]]) -> dict[str, Any]:
    normalized = [evidence_result(item, promises) for item in spec.evidence]
    primary_payload = normalized[-1].pop("_payload", {}) if normalized else {}
    for item in normalized[:-1]:
        item.pop("_payload", None)
    if spec.journey_id == "repository-agent":
        metrics = repository_metrics(primary_payload)
    else:
        metrics = android_metrics(primary_payload)
    status = combine_status(normalized)
    missing = [name for name in spec.required_metrics if not measured_metric(metrics, name)]
    measured = len(spec.required_metrics) - len(missing)
    coverage = round(measured / len(spec.required_metrics), 4) if spec.required_metrics else 1.0
    if status == "pass" and missing:
        status = "inconclusive"
    failing = next((item for item in reversed(normalized) if item["status"] != "pass"), None)
    failure_class = (failing or {}).get("failureClass")
    failure_stage = (failing or {}).get("promiseId")
    if status == "inconclusive" and missing and not failure_class:
        failure_class = "required_metrics_missing"
        failure_stage = "readiness-metrics"
    blocker = None
    if status != "pass":
        prerequisite, next_action = blocker_guidance(status, failure_class, failure_stage)
        blocker = {
            "kind": blocker_kind(status, failure_class),
            "failureClass": failure_class or f"journey_{status}",
            "stage": failure_stage or "readiness-gate",
            "prerequisite": prerequisite,
            "nextAction": next_action,
        }
    verification = "historical" if status == "stale" else spec.verification_level
    public = [public_evidence(item, promises.get(str(item.get("promiseId")), {})) for item in normalized]
    voice_names = {
        "positiveTrialCount", "negativeTrialCount", "duplicateWakeCount", "falseWakeCount",
        "requestedWakeThreshold", "effectiveWakeThreshold", "responsivenessHealthy",
        "wakeToAvatarMs", "wakeToListeningMs", "transcriptionMs", "routingMs", "acknowledgementMs",
    }
    voice = {name: metrics.get(name) for name in sorted(voice_names)} if spec.journey_id == "android-voice-agent" else None
    schema_metrics = {
        "durationMs": metrics.get("durationMs"),
        "stageLatenciesMs": metrics.get("stageLatenciesMs") or {},
        "providerCalls": metrics.get("providerCalls"),
        "exactTokenUsage": metrics.get("exactTokenUsage"),
        "retryCount": metrics.get("retryCount"),
        "restartRecoverySucceeded": metrics.get("restartRecoverySucceeded"),
        "incorrectActionCount": metrics.get("incorrectActionCount"),
        "unauthorizedActionCount": metrics.get("unauthorizedActionCount"),
        "humanInterventionCount": metrics.get("humanInterventionCount"),
        "clientAcknowledged": metrics.get("clientAcknowledged"),
        "commandReceiptVerified": metrics.get("commandReceiptVerified"),
        "evidenceCompleteness": {
            "requiredCount": len(spec.required_metrics),
            "measuredCount": measured,
            "ratio": coverage,
            "complete": not missing,
        },
        "voice": voice,
        "missingMetrics": missing,
        "notApplicableMetrics": sorted(voice_names) if voice is None else [],
    }
    return {
        "id": spec.journey_id,
        "owner": spec.owner,
        "status": status,
        "verificationLevel": verification,
        "failureStage": failure_stage,
        "failureClass": failure_class,
        "blocker": blocker,
        "metrics": schema_metrics,
        "requiredMetrics": list(spec.required_metrics),
        "measuredMetrics": [name for name in spec.required_metrics if name not in missing],
        "evidence": public,
        "summary": spec.claim,
    }


def source_fingerprint() -> dict[str, Any]:
    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, check=False, capture_output=True, text=True, timeout=15,
        )
        return result.stdout

    head = git("rev-parse", "HEAD").strip()
    porcelain = git("status", "--porcelain=v1", "-z")
    changed = [item for item in porcelain.split("\0") if item]
    return {
        "revision": head or "unknown",
        "dirty": bool(changed),
        "fingerprint": hashlib.sha256(porcelain.encode()).hexdigest(),
        "capturedAt": iso(utc_now()),
    }


def execute_promises(selected: set[str], promises: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    plan: list[str] = []
    seen: set[str] = set()
    for journey in JOURNEYS:
        if journey.journey_id not in selected:
            continue
        for promise_id in journey.run_promises:
            if promise_id not in seen:
                seen.add(promise_id)
                plan.append(promise_id)
    print("Stateful/production promise plan (serialized):")
    for promise_id in plan:
        command = promises.get(promise_id, {}).get("command") or []
        print(f"- {promise_id}: {' '.join(command)}")
    results: list[dict[str, Any]] = []
    for promise_id in plan:
        promise = promises.get(promise_id)
        if not promise:
            results.append({"promiseId": promise_id, "exitCode": None, "status": "blocked", "failureClass": "promise_not_registered"})
            continue
        command = [str(part) for part in promise.get("command") or []]
        timeout = int(promise.get("timeoutSec") or 60)
        started = time.monotonic()
        try:
            completed = subprocess.run(command, cwd=ROOT, check=False, timeout=timeout)
            results.append({
                "promiseId": promise_id,
                "exitCode": completed.returncode,
                "status": "pass" if completed.returncode == 0 else "fail",
                "durationMs": round((time.monotonic() - started) * 1000),
            })
        except subprocess.TimeoutExpired:
            results.append({
                "promiseId": promise_id, "exitCode": None, "status": "blocked",
                "failureClass": "promise_timeout", "durationMs": round((time.monotonic() - started) * 1000),
            })
    return results


def comparison(current: dict[str, Any], baseline_path: Path | None) -> dict[str, Any] | None:
    if baseline_path is None:
        return None
    baseline = read_json(baseline_path)
    prior = baseline.get("journeys") if isinstance(baseline.get("journeys"), dict) else {}
    rows = []
    for item in current["journeys"].values():
        before = prior.get(item["id"], {}) if isinstance(prior, dict) else {}
        before_coverage = pointer(before, "/metrics/evidenceCompleteness/ratio")
        after_coverage = pointer(item, "/metrics/evidenceCompleteness/ratio")
        rows.append({
            "id": item["id"],
            "statusBefore": before.get("status"),
            "statusAfter": item.get("status"),
            "coverageBefore": before_coverage,
            "coverageAfter": after_coverage,
            "coverageDelta": (
                round(after_coverage - before_coverage, 4)
                if isinstance(before_coverage, (int, float)) and isinstance(after_coverage, (int, float)) else None
            ),
        })
    return {"baseline": relative(baseline_path), "journeys": rows}


def build_report(*, execution: list[dict[str, Any]] | None = None, compare: Path | None = None) -> dict[str, Any]:
    started = time.monotonic()
    checked_at = utc_now()
    document, promises = registry()
    journey_list = [journey_result(spec, promises) for spec in JOURNEYS]
    journeys = {item["id"]: item for item in journey_list}
    counts = {status: sum(item["status"] == status for item in journey_list) for status in sorted(CANONICAL_STATUSES)}
    ranked = sorted(
        (item for item in journey_list if item["status"] != "pass"),
        key=lambda item: (
            {"fail": 0, "stale": 1, "blocked": 2, "invalid-environment": 3, "inconclusive": 4}.get(item["status"], 5),
            pointer(item, "/metrics/evidenceCompleteness/ratio", 0),
        ),
    )
    bottleneck = None
    if ranked:
        item = ranked[0]
        blocker_kind_value = pointer(item, "/blocker/kind")
        contract_class = (
            "runtime-access"
            if blocker_kind_value in {"missing-access", "authority-boundary"}
            else "runtime-evidence"
            if item["status"] in {"stale", "blocked", "invalid-environment", "needs-human-proof"}
            else "implementation-or-proof"
        )
        bottleneck = {
            "journeyId": item["id"],
            "contractClass": contract_class,
            "failureClass": item["failureClass"] or "required_metrics_missing",
            "reason": (
                f"{item['status']} evidence with {len(item['metrics']['missingMetrics'])} required metric(s) missing"
            ),
            "nextAction": item["blocker"]["nextAction"] if item.get("blocker") else "Rerun the focused journey proof.",
        }
    statuses = [item["status"] for item in journey_list]
    overall_status = "pass"
    for candidate in ("fail", "stale", "invalid-environment", "needs-human-proof", "blocked", "running", "inconclusive"):
        if candidate in statuses:
            overall_status = candidate
            break
    completed = all(status != "running" for status in statuses)
    ready = all(status == "pass" for status in statuses)
    flat_evidence: list[dict[str, Any]] = []
    seen_refs: set[tuple[str, str | None]] = set()
    for item in journey_list:
        for evidence in item["evidence"]:
            key = (evidence["ref"], evidence.get("sha256"))
            if key not in seen_refs:
                seen_refs.add(key)
                flat_evidence.append(evidence)
    finished_at = utc_now()
    report: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "runId": f"readiness-{checked_at.strftime('%Y%m%dT%H%M%SZ')}",
        "status": overall_status,
        "evaluationCompleted": completed,
        "ready": ready,
        "redacted": True,
        "startedAt": iso(checked_at),
        "finishedAt": iso(finished_at),
        "durationMs": round((time.monotonic() - started) * 1000),
        "source": source_fingerprint(),
        "journeys": journeys,
        "evidence": flat_evidence,
        "summary": (
            f"Evaluation completed={str(completed).lower()}, ready={str(ready).lower()}; "
            f"statuses " + ", ".join(f"{item['id']}={item['status']}" for item in journey_list) + "."
        ),
        "registry": {
            "path": relative(REGISTRY_PATH),
            "updatedAt": document.get("updatedAt"),
            "sha256": hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest(),
        },
        "counts": counts,
        "execution": execution or [],
        "highestPriorityBottleneck": bottleneck,
        "comparison": None,
    }
    report["comparison"] = comparison(report, compare)
    return report


def markdown_summary(report: dict[str, Any]) -> str:
    lines = [
        "# WASM Agent Product Readiness",
        "",
        f"Checked: `{report['finishedAt']}`",
        f"Evaluation complete: **{'yes' if report['evaluationCompleted'] else 'no'}**",
        f"Ready: **{'yes' if report['ready'] else 'no'}**",
        "",
        "| Journey | Status | Coverage | Missing metrics |",
        "| --- | --- | ---: | ---: |",
    ]
    for item in report["journeys"].values():
        coverage = pointer(item, "/metrics/evidenceCompleteness/ratio", 0)
        missing = item["metrics"]["missingMetrics"]
        lines.append(
            f"| `{item['id']}` | `{item['status']}` | {coverage:.0%} | {len(missing)} |"
        )
    bottleneck = report.get("highestPriorityBottleneck")
    if bottleneck:
        lines.extend([
            "", "## Highest-priority bottleneck", "",
            f"`{bottleneck['journeyId']}` / `{bottleneck['failureClass']}`: {bottleneck['reason']}.",
            "", f"Next: {bottleneck['nextAction']}",
        ])
    lines.extend(["", "The JSON report is authoritative; absent measurements remain `null` and are listed in `missingMetrics`.", ""])
    return "\n".join(lines)


def validate_contract() -> list[str]:
    errors: list[str] = []
    try:
        schema = read_json(SCHEMA_PATH)
    except Exception as error:  # noqa: BLE001 - validation reports the exact contract read failure.
        return [f"schema read failed: {error}"]
    if schema.get("$id") != SCHEMA_ID:
        errors.append(f"schema $id must be {SCHEMA_ID}")
    if [item.journey_id for item in JOURNEYS] != ["repository-agent", "android-voice-agent"]:
        errors.append("journey ids are not the canonical ordered set")
    _, promises = registry()
    for journey in JOURNEYS:
        for evidence in journey.evidence:
            if evidence.promise_id not in promises:
                errors.append(f"unregistered promise: {evidence.promise_id}")
    report = build_report()
    if report.get("schema") != SCHEMA_ID or report.get("redacted") is not True:
        errors.append("sample result lacks schema or redaction invariant")
    for item in report.get("journeys", {}).values():
        if item.get("status") not in CANONICAL_STATUSES:
            errors.append(f"noncanonical status for {item.get('id')}")
        for name in item["metrics"].get("missingMetrics", []):
            value = item["metrics"].get(name)
            if value is None and item["metrics"].get("voice") is not None:
                value = item["metrics"]["voice"].get(name)
            if value not in (None, {}):
                errors.append(f"missing metric is not null for {item.get('id')}: {name}")
    try:
        from jsonschema import Draft202012Validator
        Draft202012Validator.check_schema(schema)
        errors.extend(error.message for error in Draft202012Validator(schema).iter_errors(report))
    except ImportError:
        errors.append("jsonschema is required for product-readiness contract validation")
    return errors


def write_reports(report: dict[str, Any], report_path: Path | None = None) -> tuple[Path, Path]:
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    timestamped = RUNS_ROOT / f"{stamp}.json"
    summary = RUNS_ROOT / f"{stamp}.md"
    json_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    md_text = markdown_summary(report)
    for path, content in (
        (timestamped, json_text), (summary, md_text),
        (LATEST_REPORT, json_text), (LATEST_SUMMARY, md_text),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json_text, encoding="utf-8")
    return timestamped, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", action="append", default=[],
        choices=[item.journey_id for item in JOURNEYS] + ["all"],
        help="Explicitly run a journey's registered promises before evaluation; repeatable.",
    )
    parser.add_argument("--compare", type=Path, help="Compare coverage/status with a prior readiness JSON report.")
    parser.add_argument("--report", type=Path, help="Also write the final JSON to this path.")
    parser.add_argument("--validate-only", action="store_true", help="Validate schema/registry/result invariants without child promises.")
    args = parser.parse_args()

    errors = validate_contract()
    if errors:
        for error in errors:
            print(f"product-readiness contract: {error}", file=sys.stderr)
        return 1
    if args.validate_only:
        print("WASM Agent product-readiness contract: PASS")
        return 0

    _, promises = registry()
    selected = set(args.run)
    if "all" in selected:
        selected = {item.journey_id for item in JOURNEYS}
    execution = execute_promises(selected, promises) if selected else []
    report = build_report(execution=execution, compare=args.compare)
    timestamped, summary = write_reports(report, args.report)
    print(f"WASM Agent product readiness: {'PASS' if report['ready'] else 'NOT READY'}")
    print(f"Evaluation complete: {report['evaluationCompleted']}")
    for item in report["journeys"].values():
        coverage = pointer(item, "/metrics/evidenceCompleteness/ratio", 0)
        print(f"- {item['id']}: {item['status']} ({coverage:.0%} metrics)")
    print(f"Report JSON: {relative(timestamped)}")
    print(f"Summary: {relative(summary)}")
    # Honest evaluation completion is the command contract. Readiness is a field,
    # not the process exit status, so CI can retain typed blockers as evidence.
    return 0 if report["evaluationCompleted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
