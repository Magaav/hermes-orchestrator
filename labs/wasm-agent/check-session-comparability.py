#!/usr/bin/env python3
"""Fail closed unless session lifecycle claims match the adapter registry."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REQUIRED = {"master-frontier-v5", "codex", "claude-code", "gemini-cli"}
ALLOWED = {"implementation_pending", "verified_native_session", "session_capability_unavailable"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capabilities"); parser.add_argument("--registry", required=True); parser.add_argument("--suite", required=True); parser.add_argument("--report")
    args = parser.parse_args()
    cap_path, registry_path, suite_path = map(Path, (args.capabilities, args.registry, args.suite))
    caps = json.loads(cap_path.read_text()); registry = json.loads(registry_path.read_text()); suite = json.loads(suite_path.read_text())
    errors: list[str] = []
    rows = caps.get("adapters") if isinstance(caps.get("adapters"), list) else []
    registered = {(item.get("id"), item.get("slot")) for item in registry.get("adapters") or []}
    if caps.get("schema") != "wasm-agent.safe-lab.session-adapter-capabilities.v1": errors.append("capability schema mismatch")
    suite_model = suite.get("model")
    if suite_model != "frank/GLM-5.2" or caps.get("model") != suite_model or (registry.get("modelContract") or {}).get("model") != suite_model:
        errors.append("model contract mismatch")
    if len(rows) != 9 or len({row.get("id") for row in rows}) != 9: errors.append("expected nine unique adapters")
    for row in rows:
        if (row.get("id"), row.get("slot")) not in registered: errors.append(f"unregistered adapter identity: {row.get('id')}")
        if row.get("status") not in ALLOWED: errors.append(f"invalid status: {row.get('id')}")
        if row.get("status") == "verified_native_session" and not row.get("proofArtifact"): errors.append(f"verified adapter lacks proof: {row.get('id')}")
        if row.get("status") == "session_capability_unavailable" and row.get("nativeLifecycle"): errors.append(f"unavailable adapter declares lifecycle: {row.get('id')}")
        if not row.get("isolation") or not row.get("reason"): errors.append(f"adapter explanation incomplete: {row.get('id')}")
    required = {row.get("id"): row.get("status") for row in rows if row.get("id") in REQUIRED}
    comparable = set(required) == REQUIRED and all(value == "verified_native_session" for value in required.values())
    result = {
        "schema": "wasm-agent.safe-lab.session-comparability-proof.v1", "ok": not errors,
        "liveBenchmarkAdmissible": not errors and comparable,
        "classification": "session_comparable" if not errors and comparable else "session_comparability_pending",
        "capabilitiesSha256": hashlib.sha256(cap_path.read_bytes()).hexdigest(),
        "suiteSha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
        "requiredStatuses": required, "errors": errors,
    }
    if args.report:
        report = Path(args.report); report.parent.mkdir(parents=True, exist_ok=True); report.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2)); return 0 if not errors else 1


if __name__ == "__main__": raise SystemExit(main())
