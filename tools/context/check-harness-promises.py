#!/usr/bin/env python3
"""Validate the self-improving harness promise registry."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "docs/context/HARNESS_PROMISES.json"
REPORT_PATH = ROOT / "reports/context/latest/harness-promises-result.json"

REQUIRED_STATUSES = {
    "pass",
    "fail",
    "running",
    "blocked",
    "stale",
    "inconclusive",
    "invalid-environment",
    "needs-human-proof",
}
EVIDENCE_CLASSES = {"static", "runtime", "behavioral", "package", "production", "human"}
TOKEN_COSTS = {"tiny", "small", "medium", "large"}
RUNTIME_COSTS = {"low", "medium", "high"}
REBUILD_COSTS = {"none", "possible", "required"}
CONFIDENCE = {"low", "medium", "high"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def require_string(errors: list[str], item: dict[str, Any], key: str, prefix: str) -> None:
    if not isinstance(item.get(key), str) or not item[key].strip():
        errors.append(f"{prefix}.{key} must be a non-empty string")


def require_string_list(errors: list[str], item: dict[str, Any], key: str, prefix: str) -> None:
    value = item.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(entry, str) and entry.strip() for entry in value):
        errors.append(f"{prefix}.{key} must be a non-empty list of strings")


def validate_promise(errors: list[str], promise: Any, index: int, seen: set[str]) -> None:
    prefix = f"promises[{index}]"
    if not isinstance(promise, dict):
        errors.append(f"{prefix} must be an object")
        return

    promise_id = promise.get("id")
    if not isinstance(promise_id, str) or not ID_RE.match(promise_id):
        errors.append(f"{prefix}.id must match {ID_RE.pattern}")
    elif promise_id in seen:
        errors.append(f"{prefix}.id duplicates {promise_id}")
    else:
        seen.add(promise_id)

    for key in ("owner", "claim", "whenToUse"):
        require_string(errors, promise, key, prefix)
    for key in ("command", "evidenceClasses", "passRequires", "outputArtifacts", "invalidatedBy", "nextSuggestedSteps"):
        require_string_list(errors, promise, key, prefix)

    timeout = promise.get("timeoutSec")
    if not isinstance(timeout, int) or timeout < 1 or timeout > 3600:
        errors.append(f"{prefix}.timeoutSec must be an integer between 1 and 3600")

    evidence = promise.get("evidenceClasses", [])
    if isinstance(evidence, list):
        unknown = sorted(set(evidence) - EVIDENCE_CLASSES)
        if unknown:
            errors.append(f"{prefix}.evidenceClasses contains unknown values: {', '.join(unknown)}")

    cost = promise.get("cost")
    if not isinstance(cost, dict):
        errors.append(f"{prefix}.cost must be an object")
        return

    cost_checks = (
        ("tokenCost", TOKEN_COSTS),
        ("runtimeCost", RUNTIME_COSTS),
        ("rebuildCost", REBUILD_COSTS),
        ("confidence", CONFIDENCE),
    )
    for key, allowed in cost_checks:
        value = cost.get(key)
        if value not in allowed:
            errors.append(f"{prefix}.cost.{key} must be one of: {', '.join(sorted(allowed))}")


def validate_registry(registry: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(registry, dict):
        return ["registry root must be an object"]

    if registry.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    if not isinstance(registry.get("updatedAt"), str) or not registry["updatedAt"].strip():
        errors.append("updatedAt must be a non-empty string")

    statuses = registry.get("resultStatuses")
    if not isinstance(statuses, list) or set(statuses) != REQUIRED_STATUSES:
        errors.append("resultStatuses must exactly match the canonical harness statuses")

    evidence_classes = registry.get("evidenceClasses")
    if not isinstance(evidence_classes, list) or set(evidence_classes) != EVIDENCE_CLASSES:
        errors.append("evidenceClasses must exactly match the canonical evidence classes")

    promotion = registry.get("promotionRule")
    if not isinstance(promotion, dict):
        errors.append("promotionRule must be an object")
    else:
        require_string(errors, promotion, "secondRepeat", "promotionRule")
        require_string(errors, promotion, "thirdRepeat", "promotionRule")

    promises = registry.get("promises")
    if not isinstance(promises, list) or not promises:
        errors.append("promises must be a non-empty list")
    else:
        seen: set[str] = set()
        for index, promise in enumerate(promises):
            validate_promise(errors, promise, index, seen)

    return errors


def write_report(errors: list[str]) -> dict[str, Any]:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "ok": not errors,
        "classification": "harness_promises_pass" if not errors else "harness_promises_invalid",
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "registryPath": rel(REGISTRY_PATH),
        "errors": errors,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        errors = validate_registry(registry)
    except Exception as exc:  # noqa: BLE001 - report parse/read failures compactly.
        errors = [f"failed to read registry: {exc}"]

    report = write_report(errors)
    print(f"Harness promises: {'PASS' if report['ok'] else 'FAIL'} ({report['classification']})")
    print(f"Report JSON: {rel(REPORT_PATH)}")
    for error in errors:
        print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
