#!/usr/bin/env python3
"""Run the composed Master:frontier production-readiness gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "reports/context/latest/master-frontier-production-proof.json"
CLI_OUTPUT_MAX_BYTES = 2048
CLI_FAILURE_MAX_ITEMS = 3
CLI_FAILURE_TAIL_CHARS = 240
PROOF_TEST_PATH = "plugins/wasm-agent/tests/master_frontier_production_proof.test.py"


COMMANDS: tuple[tuple[str, list[str], str], ...] = (
    ("harness-registry", ["python3", "tools/context/check-harness-promises.py"], "static"),
    ("context-sync", ["python3", "tools/context/check-context-sync.py"], "static"),
    ("monolith-growth", ["python3", "tools/context/check-monolith-growth.py"], "static"),
    ("c3-registry", ["python3", "plugins/wasm-agent/tests/master_frontier_cyphers_v3.test.py"], "static"),
    ("c3-loop", ["python3", "plugins/wasm-agent/tests/master_frontier_controller_v3.test.py"], "behavioral"),
    ("c3-browser", ["node", "plugins/wasm-agent/tests/master_frontier_cyphers_v3.test.js"], "behavioral"),
    ("c3-server", ["python3", "plugins/wasm-agent/tests/master_frontier_v3_integration.test.py"], "behavioral"),
    ("session-replay", ["python3", "plugins/wasm-agent/tests/master_frontier_session_replay.test.py"], "behavioral"),
    ("autonomy-loop", ["python3", "plugins/wasm-agent/tests/master_frontier_autonomy_loop.test.py"], "behavioral"),
    ("planner", ["python3", "plugins/wasm-agent/tests/master_frontier_planner.test.py"], "static"),
    ("budget", ["python3", "plugins/wasm-agent/tests/master_frontier_budget.test.py"], "static"),
    ("dispatch", ["python3", "plugins/wasm-agent/tests/master_frontier_dispatch.test.py"], "static"),
    ("protocol", ["python3", "plugins/wasm-agent/tests/master_frontier_protocol.test.py"], "static"),
    ("envelope", ["python3", "plugins/wasm-agent/tests/master_frontier_envelope.test.py"], "static"),
    ("envelope-v2", ["python3", "plugins/wasm-agent/tests/master_frontier_envelope_v2.test.py"], "static"),
    ("prompt-audit", ["python3", "plugins/wasm-agent/tests/master_frontier_prompt_audit.test.py"], "static"),
    ("contract-fixes", ["python3", "plugins/wasm-agent/tests/master_frontier_contract_fixes.test.py"], "behavioral"),
    ("runtime-snapshot", ["python3", "plugins/wasm-agent/tests/master_frontier_runtime_snapshot.test.py"], "static"),
    ("runtime-collector", ["python3", "plugins/wasm-agent/tests/master_frontier_runtime_snapshot_collector.test.py"], "behavioral"),
    ("runtime-proof", ["python3", "plugins/wasm-agent/tests/master_frontier_runtime_proof.test.py"], "behavioral"),
    ("runtime-actions", ["python3", "plugins/wasm-agent/tests/master_frontier_runtime_actions.test.py"], "behavioral"),
    ("runtime-inspect", ["python3", "plugins/wasm-agent/tests/master_frontier_runtime_inspect.test.py"], "behavioral"),
    ("source-investigation-browser", ["node", "plugins/wasm-agent/tests/master_frontier_source_investigation.test.js"], "behavioral"),
    ("source-investigation-v4", ["python3", "plugins/wasm-agent/tests/master_frontier_v4_source_investigation.test.py"], "behavioral"),
    ("frontier-v5", ["python3", "plugins/wasm-agent/tests/master_frontier_v5.test.py"], "behavioral"),
    ("frontier-v5-budget", ["python3", "plugins/wasm-agent/tests/master_frontier_v5_budget.test.py"], "behavioral"),
    ("frontier-v5-resilience", ["python3", "plugins/wasm-agent/tests/master_frontier_v5_resilience.test.py"], "behavioral"),
    ("frontier-v5-campaign-contract", ["python3", "plugins/wasm-agent/tests/master_frontier_v5_campaign.test.py"], "behavioral"),
    ("frontier-v5-production-campaign", ["python3", "tools/context/evaluate-master-frontier-v5-production.py"], "behavioral"),
    ("frontier-cloud-canary-contract", ["python3", "plugins/wasm-agent/tests/master_frontier_cloud_canary.test.py"], "behavioral"),
    ("wasm-agent-app-config", ["python3", "plugins/wasm-agent/tests/wasm_agent_app_config.test.py"], "behavioral"),
    ("wasm-agent-deployment-env", ["bash", "plugins/wasm-agent/tests/wasm_agent_deployment_env.test.sh"], "behavioral"),
    ("synthetic-canary-grant", ["python3", "plugins/wasm-agent/tests/synthetic_canary.test.py"], "behavioral"),
    ("frontier-v5-authority", ["python3", "plugins/wasm-agent/tests/master_frontier_v5_authority.test.py"], "static"),
    ("frontier-v5-compact-context", ["python3", "plugins/wasm-agent/tests/master_frontier_v5_compact_context.test.py"], "behavioral"),
    ("frontier-v5-progress", ["python3", "plugins/wasm-agent/tests/master_frontier_v5_progress.test.py"], "behavioral"),
    ("frontier-v5-novelty", ["python3", "plugins/wasm-agent/tests/master_frontier_v5_novelty.test.py"], "behavioral"),
    ("frontier-v5-epistemics", ["python3", "plugins/wasm-agent/tests/master_frontier_v5_epistemics.test.py"], "behavioral"),
    ("frontier-v5-tool-stage", ["python3", "plugins/wasm-agent/tests/master_frontier_v5_tool_stage.test.py"], "behavioral"),
    ("frontier-v5-implementation-lab", ["python3", "labs/wasm-agent/test_implementation_lab.py"], "behavioral"),
    ("frontier-golden-pattern-extractor", ["python3", "labs/wasm-agent/test_golden_pattern_extractor.py"], "behavioral"),
    ("frontier-v5-operation-ledger", ["python3", "plugins/wasm-agent/tests/master_frontier_v5_operation_ledger.test.py"], "behavioral"),
    ("frontier-provider-transport", ["python3", "plugins/wasm-agent/tests/master_frontier_provider_transport.test.py"], "behavioral"),
    ("frontier-repository-actions", ["python3", "plugins/wasm-agent/tests/master_frontier_repository_actions.test.py"], "behavioral"),
    ("frontier-repository-checks", ["python3", "plugins/wasm-agent/tests/master_frontier_repository_checks.test.py"], "behavioral"),
    ("frontier-repository-diff", ["python3", "plugins/wasm-agent/tests/master_frontier_repository_diff.test.py"], "behavioral"),
    ("frontier-repository-reads", ["python3", "plugins/wasm-agent/tests/master_frontier_repository_reads.test.py"], "behavioral"),
    ("frontier-repository-state", ["python3", "plugins/wasm-agent/tests/master_frontier_repository_state.test.py"], "behavioral"),
    ("route-contracts", ["python3", "plugins/wasm-agent/tests/master_frontier_route_contracts.test.py"], "static"),
    ("entity-resolution", ["python3", "plugins/wasm-agent/tests/master_frontier_entity_resolution.test.py"], "static"),
    ("intent", ["python3", "plugins/wasm-agent/tests/master_frontier_intent.test.py"], "static"),
    ("loop", ["python3", "plugins/wasm-agent/tests/master_frontier_loop.test.py"], "behavioral"),
    ("node-skills", ["python3", "plugins/wasm-agent/tests/master_frontier_node_skills.test.py"], "static"),
    ("proof-packet", ["python3", "plugins/wasm-agent/tests/master_frontier_proof_packet.test.py"], "static"),
    ("repair", ["python3", "plugins/wasm-agent/tests/master_frontier_repair.test.py"], "static"),
    ("code-memory", ["python3", "plugins/wasm-agent/tests/master_frontier_code_memory.test.py"], "static"),
    ("code-memory-helper", ["python3", "plugins/wasm-agent/tests/code_memory_agent_contract.test.py"], "behavioral"),
    ("agent-run-store", ["python3", "plugins/wasm-agent/tests/agent_run_store.test.py"], "behavioral"),
    ("watch-loop", ["python3", "plugins/wasm-agent/tests/master_frontier_watch_loop.test.py"], "behavioral"),
    ("continuation", ["node", "plugins/wasm-agent/tests/master_frontier_continuation.test.js"], "behavioral"),
    ("timeline", ["node", "plugins/wasm-agent/tests/master_frontier_timeline.test.js"], "behavioral"),
    ("useful-fallback", ["node", "plugins/wasm-agent/tests/master_frontier_useful_fallback.test.js"], "behavioral"),
    ("provider-proxy", ["python3", "plugins/wasm-agent/tests/provider_proxy.test.py"], "behavioral"),
    ("wasm-agent-smoke", ["node", "plugins/wasm-agent/tests/wasm_agent_smoke.test.js"], "behavioral"),
)


FINGERPRINT_DIRECTORIES = (
    "plugins/wasm-agent/public/modules/master-frontier",
    "plugins/wasm-agent/server/master_frontier",
    "plugins/wasm-agent/tests/fixtures",
)
FINGERPRINT_FILES = (
    "docs/context/HARNESS_PROMISES.json",
    "plugins/wasm-agent/public/modules/master-frontier/cyphers-v3.json",
    "plugins/wasm-agent/server/agent_route_contracts.json",
    "tools/context/prove-master-frontier-production.py",
)
FINGERPRINT_GLOBS = (
    "plugins/wasm-agent/tests/master_frontier*.test.*",
)
C3_COST_FIXTURE_PATH = "plugins/wasm-agent/tests/fixtures/master_frontier_c3_cost_metrics.json"


RUNTIME_COMMANDS: tuple[tuple[str, list[str], str], ...] = (
    ("node-bridge-proof", ["python3", "tools/context/prove-wasm-agent-node-bridge.py"], "runtime"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _fingerprintable(path: Path) -> bool:
    return path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}


def command_target_paths(commands: tuple[tuple[str, list[str], str], ...] = COMMANDS) -> set[str]:
    return {
        argument
        for _name, argv, _evidence_class in commands
        for argument in argv[1:]
        if argument.startswith(("plugins/", "tools/", "docs/"))
    }


def relevant_master_frontier_tests(root: Path = ROOT) -> set[str]:
    tests_root = root / "plugins/wasm-agent/tests"
    return {
        _relative(path, root)
        for path in tests_root.glob("master_frontier*.test.*")
        if path.is_file() and _relative(path, root) != PROOF_TEST_PATH
    }


def command_coverage_result(root: Path = ROOT) -> dict[str, Any]:
    targets = command_target_paths()
    required = relevant_master_frontier_tests(root) | {
        "plugins/wasm-agent/tests/agent_run_store.test.py",
        "tools/context/check-context-sync.py",
    }
    missing = sorted(required - targets)
    recursive = PROOF_TEST_PATH in targets or "tools/context/prove-master-frontier-production.py" in targets
    ok = not missing and not recursive
    return {
        "name": "command-coverage",
        "status": "pass" if ok else "fail",
        "evidenceClass": "static",
        "command": ["internal", "command-coverage"],
        "durationMs": 0,
        "returncode": 0 if ok else 1,
        "errorType": None if ok else "production_command_coverage_incomplete",
        "missingPaths": missing,
        "recursiveProofCommand": recursive,
        "stdoutTail": "",
        "stderrTail": "" if ok else "production command coverage is incomplete or recursive",
    }


def fingerprint_paths(root: Path = ROOT) -> list[str]:
    paths = set(FINGERPRINT_FILES)
    paths.update(command_target_paths(COMMANDS + RUNTIME_COMMANDS))
    for pattern in FINGERPRINT_GLOBS:
        paths.update(_relative(path, root) for path in root.glob(pattern) if _fingerprintable(path))
    for relative in FINGERPRINT_DIRECTORIES:
        directory = root / relative
        if directory.exists():
            paths.update(_relative(path, root) for path in directory.rglob("*") if _fingerprintable(path))
    return sorted(paths)


def source_snapshot(root: Path = ROOT) -> dict[str, Any]:
    digest = hashlib.sha256()
    files: dict[str, str | None] = {}
    for relative in fingerprint_paths(root):
        path = root / relative
        content = path.read_bytes() if path.is_file() else None
        files[relative] = hashlib.sha256(content).hexdigest() if content is not None else None
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content if content is not None else b"[missing]")
        digest.update(b"\0")
    return {"fingerprint": digest.hexdigest(), "files": files}


def source_fingerprint(root: Path = ROOT) -> str:
    return str(source_snapshot(root)["fingerprint"])


def source_integrity_result(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_files = before.get("files") if isinstance(before.get("files"), dict) else {}
    after_files = after.get("files") if isinstance(after.get("files"), dict) else {}
    changed = sorted(
        path
        for path in set(before_files) | set(after_files)
        if before_files.get(path) != after_files.get(path)
    )
    matches = before.get("fingerprint") == after.get("fingerprint") and not changed
    return {
        "name": "source-integrity",
        "status": "pass" if matches else "fail",
        "evidenceClass": "static",
        "command": ["internal", "source-fingerprint"],
        "durationMs": 0,
        "returncode": 0 if matches else 1,
        "errorType": None if matches else "source_changed_during_proof",
        "beforeFingerprint": before.get("fingerprint"),
        "afterFingerprint": after.get("fingerprint"),
        "coveredPathCount": {"before": len(before_files), "after": len(after_files)},
        "changedPaths": changed,
        "stdoutTail": "",
        "stderrTail": "" if matches else "fingerprinted production sources changed while proof commands were running",
    }


def cost_metrics(root: Path = ROOT) -> dict[str, Any]:
    fixture = json.loads((root / C3_COST_FIXTURE_PATH).read_text(encoding="utf-8"))
    usages = fixture.get("providerUsages")
    if fixture.get("schema") != "hermes.wasm_agent.master_frontier.c3_cost_fixture.v1":
        raise ValueError("unsupported C3 cost fixture schema")
    if fixture.get("live") is not False:
        raise ValueError("deterministic C3 cost fixture must set live to false")
    if not isinstance(fixture.get("measurement"), str) or not fixture["measurement"].strip():
        raise ValueError("C3 cost fixture measurement must be a non-empty string")
    if not isinstance(usages, list) or not usages or not all(isinstance(item, dict) for item in usages):
        raise ValueError("C3 cost fixture providerUsages must be a non-empty list of objects")
    if not all(isinstance(item.get("total_tokens"), int) and item["total_tokens"] >= 0 for item in usages):
        raise ValueError("C3 cost fixture total_tokens values must be non-negative integers")
    return {
        "current": {
            "measurement": fixture.get("measurement"),
            "live": fixture["live"],
            "source": C3_COST_FIXTURE_PATH,
            "calls": len(usages),
            "tokens": sum(item["total_tokens"] for item in usages),
        },
        "lastKnownGood": {
            "status": "unavailable",
            "source": None,
            "calls": None,
            "tokens": None,
        },
        "comparison": {
            "status": "unknown",
            "callsDelta": None,
            "tokensDelta": None,
            "reason": "authoritative_last_known_good_baseline_unavailable",
        },
    }


def run_command(name: str, argv: list[str], evidence_class: str, timeout_sec: int) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            check=False,
        )
        status = "pass" if proc.returncode == 0 else "fail"
        stdout = proc.stdout[-4000:]
        stderr = proc.stderr[-4000:]
        returncode: int | None = proc.returncode
    except subprocess.TimeoutExpired as exc:
        status = "fail"
        stdout = (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "timeout"
        returncode = None
    return {
        "name": name,
        "status": status,
        "evidenceClass": evidence_class,
        "command": argv,
        "durationMs": int((time.monotonic() - started) * 1000),
        "returncode": returncode,
        "stdoutTail": stdout,
        "stderrTail": stderr,
    }


def write_report(
    results: list[dict[str, Any]],
    *,
    include_runtime: bool,
    source_before: dict[str, Any],
    source_after: dict[str, Any],
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    integrity = source_integrity_result(source_before, source_after)
    checked_results = [*results, integrity]
    failed = [item for item in checked_results if item.get("status") != "pass"]
    report = {
        "ok": not failed,
        "schema": "hermes.context.master_frontier.production_proof.v2",
        "checkedAt": utc_now(),
        "claim": "Master:frontier C3 model-led execution and compatibility gates pass.",
        "sourceFingerprint": source_after.get("fingerprint"),
        "sourceIntegrity": {
            key: integrity[key]
            for key in (
                "status",
                "errorType",
                "beforeFingerprint",
                "afterFingerprint",
                "coveredPathCount",
                "changedPaths",
            )
        },
        "costMetrics": cost_metrics(),
        "includeRuntime": include_runtime,
        "builder": {
            "intent": "prove C3 semantic-operation model-led execution with internal cypher receipts, then retained compatibility contracts",
            "changedSurface": "Master:frontier V3 registry, codec, controller, browser envelope, and proof harness",
        },
        "watcher": {
            "evidenceClasses": sorted({str(item.get("evidenceClass")) for item in checked_results}),
            "results": checked_results,
        },
        "gatekeeper": {
            "decision": "pass" if not failed else "fail",
            "failed": [item.get("name") for item in failed],
            "runtimeCaveat": (
                "node bridge runtime proof was included"
                if include_runtime
                else "node bridge runtime proof is separate; run with --include-runtime before claiming live node-brain availability"
            ),
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _compact_failure(item: dict[str, Any], *, tail_chars: int) -> dict[str, Any]:
    tail = str(item.get("stderrTail") or item.get("stdoutTail") or "").strip()
    compact = {
        "name": str(item.get("name") or "unknown"),
        "code": str(item.get("errorType") or f"exit_{item.get('returncode')}"),
    }
    if tail and tail_chars:
        compact["tail"] = tail[-tail_chars:]
    return compact


def cli_summary(report: dict[str, Any], *, report_path: Path = REPORT_PATH, tail_chars: int = CLI_FAILURE_TAIL_CHARS) -> dict[str, Any]:
    results = report.get("watcher", {}).get("results", [])
    checked = [item for item in results if isinstance(item, dict)]
    failed = [item for item in checked if item.get("status") != "pass"]
    shown = failed[:CLI_FAILURE_MAX_ITEMS]
    fingerprint = str(report.get("sourceFingerprint") or "")
    return {
        "schema": "MF_PROOF/1",
        "ok": bool(report.get("ok")),
        "checked": len(checked),
        "passed": len(checked) - len(failed),
        "failed": [_compact_failure(item, tail_chars=tail_chars) for item in shown],
        "failedOmitted": max(0, len(failed) - len(shown)),
        "runtime": bool(report.get("includeRuntime")),
        "source": fingerprint[:16],
        "artifact": report_path.relative_to(ROOT).as_posix() if report_path.is_relative_to(ROOT) else str(report_path),
    }


def render_cli_summary(report: dict[str, Any], *, report_path: Path = REPORT_PATH) -> str:
    tail_chars = CLI_FAILURE_TAIL_CHARS
    while True:
        rendered = json.dumps(cli_summary(report, report_path=report_path, tail_chars=tail_chars), separators=(",", ":"))
        if len(rendered.encode("utf-8")) <= CLI_OUTPUT_MAX_BYTES:
            return rendered
        if tail_chars == 0:
            raise ValueError("compact proof summary exceeds CLI output budget without diagnostic tails")
        tail_chars //= 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-runtime", action="store_true", help="Also run live node bridge runtime proof.")
    parser.add_argument("--timeout-sec", type=int, default=180)
    args = parser.parse_args()

    commands = list(COMMANDS)
    if args.include_runtime:
        commands.extend(RUNTIME_COMMANDS)
    source_before = source_snapshot()
    results = [command_coverage_result()]
    results.extend(run_command(name, argv, evidence_class, args.timeout_sec) for name, argv, evidence_class in commands)
    source_after = source_snapshot()
    report = write_report(
        results,
        include_runtime=args.include_runtime,
        source_before=source_before,
        source_after=source_after,
    )
    print(render_cli_summary(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
