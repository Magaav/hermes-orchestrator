#!/usr/bin/env python3
"""Emit compact WAPROOF rows from existing Windows proof reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_ROOT = REPO_ROOT / "reports" / "windows" / "latest"
DEFAULT_OUTPUT = DEFAULT_REPORTS_ROOT / "waproof-receipts.hbp"
SCHEMA = "hermes.wasm_agent.receipt.v1"
CANONICAL_STATUSES = {
    "verified",
    "implemented-unverified",
    "proposal",
    "future",
    "stale",
    "unknown",
}
PROOF_RESULTS = {"pass", "fail", "missing", "not_run"}
SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9._:/=@,+-]*$")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tuple_hash(parts: dict[str, Any]) -> str:
    canonical = json.dumps(parts, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def token(value: Any) -> str:
    text = str(value or "")
    text = text.strip().replace(" ", "_")
    text = re.sub(r"[^A-Za-z0-9._:/=@,+-]", "_", text)
    text = re.sub(r"_+", "_", text)
    if "|" in text or "\n" in text or "\r" in text or not SAFE_VALUE_RE.match(text):
        raise ValueError(f"Unsafe WAPROOF token value: {value!r}")
    return text


def next_id(value: Any) -> str:
    text = token(value)
    return text[:96] if text else "none"


def row(fields: dict[str, Any]) -> str:
    required = {
        "schema",
        "kind",
        "claim_status",
        "proof_result",
        "subject",
        "proof",
        "sha256",
        "next",
        "json",
    }
    missing = sorted(required - set(fields))
    if missing:
        raise ValueError(f"Missing WAPROOF fields: {missing}")
    claim_status = str(fields["claim_status"])
    proof_result = str(fields["proof_result"])
    if claim_status not in CANONICAL_STATUSES:
        raise ValueError(f"Non-canonical claim_status: {claim_status}")
    if proof_result not in PROOF_RESULTS:
        raise ValueError(f"Invalid proof_result: {proof_result}")
    ordered = [
        "schema",
        "kind",
        "claim_status",
        "proof_result",
        "subject",
        "proof",
        "sha256",
        "next",
        "json",
    ]
    body = "WAPROOF|" + "|".join(f"{key}={token(fields[key])}" for key in ordered)
    if not body.endswith("|json=0"):
        raise ValueError("WAPROOF row must end with json=0")
    return body


def package_receipt(reports_root: Path) -> str:
    path = reports_root / "windows-release-feed-check.json"
    report = read_json(path)
    ok = report.get("ok") is True
    proof_result = "pass" if ok else ("fail" if report else "missing")
    claim_status = "verified" if ok else "implemented-unverified"
    verified = report.get("verified") if isinstance(report.get("verified"), dict) else {}
    feed = report.get("feed") if isinstance(report.get("feed"), dict) else {}
    subject = tuple_hash(
        {
            "kind": "package",
            "schema": report.get("schema") or "hermes.wasm_agent.windows_release_feed_check.v1",
            "verifiedBuildId": verified.get("buildId") or "",
            "feedBuildId": feed.get("buildId") or "",
            "verifiedSha": verified.get("sha256") or "",
            "feedSha": feed.get("sha256") or "",
        }
    )
    failure = report.get("failureClassification") or ""
    return row(
        {
            "schema": SCHEMA,
            "kind": "package",
            "claim_status": claim_status,
            "proof_result": proof_result,
            "subject": subject,
            "proof": "windows_release_feed_check",
            "sha256": sha256_file(path),
            "next": "none" if ok else next_id(failure or "rerun_windows_release_feed_check"),
            "json": "0",
        }
    )


def hot_shell_receipt(reports_root: Path) -> str:
    path = reports_root / "hot-shell-proof-result.json"
    report = read_json(path)
    ok = report.get("ok") is True and report.get("bridgeAlive") is True
    proof_result = "pass" if ok else ("fail" if report else "missing")
    claim_status = "verified" if ok else "implemented-unverified"
    subject = tuple_hash(
        {
            "kind": "hot_op",
            "schema": report.get("schema") or "hermes.wasm_agent.windows_hot_shell_proof.v1",
            "runId": report.get("runId") or "",
            "origin": report.get("origin") or "",
            "bridgeAlive": report.get("bridgeAlive") is True,
            "hotOpsProtocolVersion": report.get("hotOpsProtocolVersion") or 0,
            "activeDownloadedRuntimeId": report.get("activeDownloadedRuntimeId") or "",
            "activeDownloadedRuntimeSha": report.get("activeDownloadedRuntimeSha") or "",
            "activeHotOpsRoot": report.get("activeHotOpsRoot") or "",
        }
    )
    failure = report.get("failureClassification") or ""
    return row(
        {
            "schema": SCHEMA,
            "kind": "hot_op",
            "claim_status": claim_status,
            "proof_result": proof_result,
            "subject": subject,
            "proof": "windows_hot_shell_proof",
            "sha256": sha256_file(path),
            "next": "none" if ok else next_id(failure or "run_prove_hot_shell"),
            "json": "0",
        }
    )


def downloaded_runtime_receipt(reports_root: Path) -> str:
    path = reports_root / "hot-shell-proof-result.json"
    report = read_json(path)
    shell_ok = report.get("ok") is True and report.get("bridgeAlive") is True
    runtime_id = str(report.get("activeDownloadedRuntimeId") or "")
    runtime_sha = str(report.get("activeDownloadedRuntimeSha") or "")
    runtime_present = bool(runtime_id and runtime_sha)
    ok = shell_ok and runtime_present
    proof_result = "pass" if ok else ("missing" if not runtime_present else "fail")
    claim_status = "verified" if ok else "implemented-unverified"
    subject = tuple_hash(
        {
            "kind": "runtime",
            "runId": report.get("runId") or "",
            "activeDownloadedRuntimeId": runtime_id,
            "activeDownloadedRuntimeSha": runtime_sha,
            "shellProofOk": shell_ok,
        }
    )
    return row(
        {
            "schema": SCHEMA,
            "kind": "runtime",
            "claim_status": claim_status,
            "proof_result": proof_result,
            "subject": subject,
            "proof": "windows_hot_shell_proof",
            "sha256": sha256_file(path),
            "next": "none" if ok else "run_prove_hot_shell",
            "json": "0",
        }
    )


def emit(reports_root: Path) -> str:
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    header = row(
        {
            "schema": SCHEMA,
            "kind": "runtime",
            "claim_status": "proposal",
            "proof_result": "not_run",
            "subject": tuple_hash({"kind": "receipt_batch", "generatedAt": generated, "reportsRoot": str(reports_root)}),
            "proof": "waproof_receipt_generator",
            "sha256": "",
            "next": "read_receipt_rows",
            "json": "0",
        }
    )
    rows = [
        header,
        package_receipt(reports_root),
        hot_shell_receipt(reports_root),
        downloaded_runtime_receipt(reports_root),
    ]
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--stdout", action="store_true", help="Also print rows to stdout.")
    args = parser.parse_args()

    reports_root = Path(args.reports_root)
    output = Path(args.output)
    text = emit(reports_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    if args.stdout:
        sys.stdout.write(text)
    else:
        print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
