"""Compact operation-derived proof projection for V5 outcomes."""
from __future__ import annotations

from typing import Any

from . import operation_ledger


def _payload(item: dict[str, Any]) -> dict[str, Any]:
    result = item.get("result") if isinstance(item.get("result"), dict) else item
    nested = result.get("result") if isinstance(result.get("result"), dict) else result
    return nested


def summarize(items: list[dict[str, Any]], ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    changed: set[str] = set()
    checks: list[dict[str, Any]] = []
    diff_seen = proof_seen = False
    files_read: set[str] = set()
    for item in items:
        if item.get("path"): files_read.add(str(item["path"]))
        payload = _payload(item)
        for value in payload.get("changed_files") or []:
            path = value.get("path") if isinstance(value, dict) else value
            if path: changed.add(str(path))
        schema = str(payload.get("schema") or "")
        action = str(item.get("local_action") or payload.get("local_action") or "")
        if "test_run_focused" in schema or action == "test.run_focused":
            checks.append({key: payload.get(key) for key in ("check_id", "returncode", "duration_ms", "code") if payload.get(key) is not None})
        if "git_diff_summary" in schema or action == "git.diff_summary": diff_seen = True
        if "kernel.prove" in schema or item.get("primitive") == "kernel.prove": proof_seen = True
    checks_passed = bool(checks) and all(int(item.get("returncode") or 0) == 0 and item.get("code") in (None, "", "ok") for item in checks)
    level = "proof" if proof_seen and checks_passed and diff_seen else "behavioral" if checks_passed else "source" if files_read else "route"
    summary = {"changed_files": sorted(changed), "checks": checks, "checks_passed": checks_passed, "diff_seen": diff_seen, "proof_seen": proof_seen, "files_read": sorted(files_read), "verification_level": level}
    if ledger is None:
        return summary
    operations = operation_ledger.normalize(ledger)
    gaps = operation_ledger.missing(operations)
    current_check = operations.get("check") or {}
    current_diff = operations.get("diff") or {}
    current_proof = operations.get("proof") or {}
    if operations["mutations"]:
        summary.update({
            "changed_files": operations["changed_files"],
            "checks_passed": current_check.get("rev") == operations["revision"] and current_check.get("ok") is True,
            "diff_seen": current_diff.get("rev") == operations["revision"] and current_diff.get("ok") is True,
            "proof_seen": current_proof.get("rev") == operations["revision"] and current_proof.get("ok") is True,
            "verification_level": "proof" if not gaps else "behavioral" if current_check.get("ok") is True else "source" if files_read else "route",
        })
    summary["operation_revision"] = operations["revision"]
    summary["proof_gaps"] = gaps
    return summary


def missing_for_changed_files(items: list[dict[str, Any]]) -> list[str]:
    summary = summarize(items)
    if not summary["changed_files"]:
        return []
    missing = []
    if not summary["checks_passed"]: missing.append("passing focused test")
    if not summary["diff_seen"]: missing.append("diff inspection")
    if not summary["proof_seen"]: missing.append("scoped proof collection")
    return missing
