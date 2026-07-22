#!/usr/bin/env python3
"""Prove the local Master:frontier V5 continuity/coding evolution."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "plugins/wasm-agent/server"
REPORT = ROOT / "reports/context/latest/master-frontier-v5-evolution-proof.json"
PROMISES = ROOT / "docs/context/HARNESS_PROMISES.json"
PROMISE_ID = "master-frontier-v5-coding-continuity"
COMMANDS = (
    ("v5-loop", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_v5.test.py"], "behavioral"),
    ("v5-resilience", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_v5_resilience.test.py"], "behavioral"),
    ("v5-budget", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_v5_budget.test.py"], "behavioral"),
    ("shared-budget", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_budget.test.py"], "behavioral"),
    ("authority", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_v5_authority.test.py"], "static"),
    ("planner-intent", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_planner.test.py"], "behavioral"),
    ("provider-transport", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_provider_transport.test.py"], "behavioral"),
    ("terminal-usage", ["python3", "-B", "plugins/wasm-agent/tests/security_loop_policy.test.py"], "behavioral"),
    ("route-contracts", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_route_contracts.test.py"], "behavioral"),
    ("compact-context", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_v5_compact_context.test.py"], "behavioral"),
    ("progress-projection", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_v5_progress.test.py"], "behavioral"),
    ("novelty-admission", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_v5_novelty.test.py"], "behavioral"),
    ("evidence-epistemics", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_v5_epistemics.test.py"], "behavioral"),
    ("workflow-tool-stage", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_v5_tool_stage.test.py"], "behavioral"),
    ("operation-ledger", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_v5_operation_ledger.test.py"], "behavioral"),
    ("repository-reads", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_repository_reads.test.py"], "behavioral"),
    ("repository-actions", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_repository_actions.test.py"], "behavioral"),
    ("repository-checks", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_repository_checks.test.py"], "behavioral"),
    ("repository-diff", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_repository_diff.test.py"], "behavioral"),
    ("repository-state", ["python3", "-B", "plugins/wasm-agent/tests/master_frontier_repository_state.test.py"], "behavioral"),
    ("agent-run-recovery", ["python3", "-B", "plugins/wasm-agent/tests/agent_run_store.test.py"], "behavioral"),
    ("continuation-browser", ["node", "plugins/wasm-agent/tests/master_frontier_continuation.test.js"], "behavioral"),
    ("browser-selection", ["node", "plugins/wasm-agent/tests/master_frontier_source_investigation.test.js"], "behavioral"),
    ("kernel-wiring", ["python3", "-B", "plugins/wasm-agent/tests/provider_proxy.test.py", "ProviderProxyTests.test_agent_kernel_local_tools_are_route_scoped_and_bounded"], "behavioral"),
    ("learning-policy", ["python3", "-B", "labs/wasm-agent/test_learning_harness.py"], "behavioral"),
    ("strategy-ranking", ["python3", "-B", "labs/wasm-agent/test_strategy_ranking.py"], "behavioral"),
    ("trajectory-fixture", ["python3", "-B", "labs/wasm-agent/test_agent_trajectory_fixture.py"], "behavioral"),
    ("golden-pattern-extractor", ["python3", "-B", "labs/wasm-agent/test_golden_pattern_extractor.py"], "behavioral"),
    ("implementation-lab", ["python3", "-B", "labs/wasm-agent/test_implementation_lab.py"], "behavioral"),
    ("decision-isolation", ["python3", "-B", "labs/wasm-agent/test_decision_isolation_matrix.py"], "behavioral"),
    ("adapter-import-closure", ["python3", "-B", "labs/wasm-agent/check-master-frontier-v5-adapter.py"], "static"),
    ("monolith-growth", ["python3", "tools/context/check-monolith-growth.py"], "static"),
)


def _invalidating_inputs() -> list[str]:
    registry = json.loads(PROMISES.read_text(encoding="utf-8"))
    promises = registry.get("promises") if isinstance(registry.get("promises"), list) else []
    promise = next((item for item in promises if isinstance(item, dict) and item.get("id") == PROMISE_ID), None)
    if promise is None:
        raise RuntimeError(f"missing harness promise: {PROMISE_ID}")
    values = [str(item) for item in (promise.get("invalidatedBy") or []) if str(item)]
    for _name, argv, _evidence_class in COMMANDS:
        values.extend(
            argument for argument in argv
            if (ROOT / argument).is_file()
        )
    for owned_root, patterns in (
        (ROOT / "plugins/wasm-agent/server/master_frontier", ("*.py",)),
        (ROOT / "plugins/wasm-agent/public/modules/master-frontier", ("*.js", "*.json")),
        (ROOT / "labs/wasm-agent", ("*.py", "*.json")),
    ):
        for pattern in patterns:
            values.extend(str(path.relative_to(ROOT)) for path in owned_root.rglob(pattern) if path.is_file())
    values.extend([
        "plugins/wasm-agent/server/static_server.py",
        "plugins/wasm-agent/server/routes.py",
        "plugins/wasm-agent/public/app.js",
    ])
    values.append(str(PROMISES.relative_to(ROOT)))
    return sorted(set(values))


def _input_fingerprint(paths: list[str]) -> dict[str, Any]:
    digest = hashlib.sha256()
    missing: list[str] = []
    for relative in paths:
        candidate = (ROOT / relative).resolve()
        try:
            candidate.relative_to(ROOT)
        except ValueError as exc:
            raise RuntimeError(f"invalid proof input outside workspace: {relative}") from exc
        digest.update(relative.encode("utf-8")); digest.update(b"\0")
        if candidate.is_file():
            digest.update(candidate.read_bytes())
        else:
            digest.update(b"[missing]")
            missing.append(relative)
        digest.update(b"\0")
    return {"sha256": digest.hexdigest(), "files": len(paths), "missing": missing}


def _compact_metric() -> dict[str, Any]:
    sys.path.insert(0, str(SERVER))
    from master_frontier.v5 import context, policy, trajectory  # noqa: PLC0415

    objective = "Implement a bounded source patch"
    state = trajectory.new("proof-run", "proof-turn", objective, "fixture.ui")
    route = {
        "route_id": "fixture.ui", "workspace_root": str(ROOT / "plugins/wasm-agent"),
        "allowed_read_roots": [str(ROOT / "plugins/wasm-agent")],
        "allowed_write_roots": [str(ROOT / "plugins/wasm-agent")],
        "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
        "checks": [{"id": "provider-proxy", "command": ["python3", "tests/provider_proxy.test.py"]}],
        "task_contract": {"request_class": "implementation"},
    }
    legacy = json.dumps({
        "objective": objective,
        "route": {"id": route["route_id"], "root": route["workspace_root"]},
        "runtime_identity": {}, "tools": policy.tool_descriptors(), "completed": [],
        "evidence_status": context._evidence_status(state), "last_error": None,
        "completion_assessment": None,
        "rule": "Every decision must add relevant evidence, reduce uncertainty, name an exact blocker, or finish.",
    }, ensure_ascii=True, separators=(",", ":"))
    compact = context.messages(objective, route, state)[1]["content"]
    ratio = len(compact) / max(1, len(legacy))
    return {
        "name": "mf5-2-base-projection", "ok": ratio < (1 / 3),
        "legacyChars": len(legacy), "compactChars": len(compact),
        "savedChars": len(legacy) - len(compact), "ratio": round(ratio, 4),
        "measurement": "deterministic empty-trajectory model-facing projection; native provider schemas remain separate",
    }


def main() -> int:
    input_paths = _invalidating_inputs()
    input_before = _input_fingerprint(input_paths)
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    if input_before["missing"]:
        errors.append("proof_inputs_missing")
    for name, argv, evidence_class in COMMANDS:
        try:
            completed = subprocess.run(
                argv, cwd=ROOT, text=True, capture_output=True, check=False, timeout=60,
            )
            output = (completed.stdout + completed.stderr)[-2400:]
            ok = completed.returncode == 0 and "Ran 0 tests" not in output
            result = {
                "name": name, "evidenceClass": evidence_class, "ok": ok,
                "returncode": completed.returncode, "outputTail": output,
            }
        except subprocess.TimeoutExpired:
            result = {"name": name, "evidenceClass": evidence_class, "ok": False, "returncode": 124, "outputTail": "timed out"}
        results.append(result)
        if not result["ok"]:
            errors.append(f"{name} failed")
    metric = _compact_metric()
    if not metric["ok"]:
        errors.append("compact projection exceeded its declared ratio")
    input_paths_after = _invalidating_inputs()
    input_after = _input_fingerprint(input_paths_after)
    if input_after["missing"] and "proof_inputs_missing" not in errors:
        errors.append("proof_inputs_missing")
    input_set_stable = input_paths == input_paths_after
    inputs_stable = input_set_stable and input_before["sha256"] == input_after["sha256"]
    if not input_set_stable:
        errors.append("input_set_changed_during_proof")
    if not inputs_stable:
        errors.append("inputs_changed_during_proof")
    proof = {
        "schema": "wasm-agent.master-frontier-v5-evolution-proof.v1",
        "ok": not errors,
        "verificationLevel": "local-static-and-behavioral",
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "inputFingerprint": {
            "algorithm": "sha256",
            "before": input_before["sha256"],
            "after": input_after["sha256"],
            "stable": inputs_stable,
            "setStable": input_set_stable,
            "files": input_after["files"],
            "beforeFiles": input_before["files"],
            "afterFiles": input_after["files"],
            "missing": input_after["missing"],
        },
        "compactContext": metric,
        "results": results,
        "errors": errors,
        "notProven": ["deployed runtime", "production provider behavior", "external-agent live trajectory quality"],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, indent=2))
    return 0 if proof["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
