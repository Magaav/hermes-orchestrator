#!/usr/bin/env python3
"""Run the composed Master:frontier production-readiness gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "reports/context/latest/master-frontier-production-proof.json"


COMMANDS: tuple[tuple[str, list[str], str], ...] = (
    ("harness-registry", ["python3", "tools/context/check-harness-promises.py"], "static"),
    ("planner", ["python3", "plugins/wasm-agent/tests/master_frontier_planner.test.py"], "static"),
    ("dispatch", ["python3", "plugins/wasm-agent/tests/master_frontier_dispatch.test.py"], "static"),
    ("protocol", ["python3", "plugins/wasm-agent/tests/master_frontier_protocol.test.py"], "static"),
    ("envelope", ["python3", "plugins/wasm-agent/tests/master_frontier_envelope.test.py"], "static"),
    ("prompt-audit", ["python3", "plugins/wasm-agent/tests/master_frontier_prompt_audit.test.py"], "static"),
    ("route-contracts", ["python3", "plugins/wasm-agent/tests/master_frontier_route_contracts.test.py"], "static"),
    ("intent", ["python3", "plugins/wasm-agent/tests/master_frontier_intent.test.py"], "static"),
    ("code-memory", ["python3", "plugins/wasm-agent/tests/master_frontier_code_memory.test.py"], "static"),
    ("code-memory-helper", ["python3", "plugins/wasm-agent/tests/code_memory_agent_contract.test.py"], "behavioral"),
    ("provider-proxy", ["python3", "plugins/wasm-agent/tests/provider_proxy.test.py"], "behavioral"),
    ("wasm-agent-smoke", ["node", "plugins/wasm-agent/tests/wasm_agent_smoke.test.js"], "behavioral"),
)


RUNTIME_COMMANDS: tuple[tuple[str, list[str], str], ...] = (
    ("node-bridge-proof", ["python3", "tools/context/prove-wasm-agent-node-bridge.py"], "runtime"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def write_report(results: list[dict[str, Any]], *, include_runtime: bool) -> dict[str, Any]:
    failed = [item for item in results if item.get("status") != "pass"]
    report = {
        "ok": not failed,
        "schema": "hermes.context.master_frontier.production_proof.v1",
        "checkedAt": utc_now(),
        "claim": "Master:frontier production gates for route-first, tool-first, budgeted, bounded-harness operation pass.",
        "includeRuntime": include_runtime,
        "builder": {
            "intent": "compose existing focused tests and harness validators into a single deterministic production gate",
            "changedSurface": "Master:frontier planner contract and proof harness",
        },
        "watcher": {
            "evidenceClasses": sorted({str(item.get("evidenceClass")) for item in results}),
            "results": results,
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
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-runtime", action="store_true", help="Also run live node bridge runtime proof.")
    parser.add_argument("--timeout-sec", type=int, default=180)
    args = parser.parse_args()

    commands = list(COMMANDS)
    if args.include_runtime:
        commands.extend(RUNTIME_COMMANDS)
    results = [run_command(name, argv, evidence_class, args.timeout_sec) for name, argv, evidence_class in commands]
    report = write_report(results, include_runtime=args.include_runtime)
    print(f"Master:frontier production proof: {'PASS' if report['ok'] else 'FAIL'}")
    print(f"Report JSON: {REPORT_PATH.relative_to(ROOT)}")
    if not report["ok"]:
        print("Failed gates:")
        for name in report["gatekeeper"]["failed"]:
            print(f"- {name}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
