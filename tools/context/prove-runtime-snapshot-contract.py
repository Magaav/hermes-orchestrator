#!/usr/bin/env python3
"""Run every focused runtime snapshot layer and emit one bounded proof."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/context/latest/runtime-snapshot-contract-proof.json"
TESTS = (
    ("plugins/wasm-agent/tests/master_frontier_runtime_snapshot.test.py",),
    ("plugins/wasm-agent/tests/master_frontier_runtime_snapshot_collector.test.py",),
    ("plugins/wasm-agent/tests/master_frontier_runtime_proof.test.py",),
    ("plugins/wasm-agent/tests/master_frontier_runtime_actions.test.py",),
    ("plugins/wasm-agent/tests/master_frontier_runtime_inspect.test.py",),
    ("plugins/wasm-agent/tests/master_frontier_v5.test.py",),
    (
        "plugins/wasm-agent/tests/provider_proxy.test.py",
        "ProviderProxyTests.test_unauthenticated_runtime_inspect_stops_before_tool_and_store",
    ),
    (
        "plugins/wasm-agent/tests/provider_proxy.test.py",
        "ProviderProxyTests.test_agent_kernel_primitives_are_generic_local_first_contract",
    ),
)


def main() -> int:
    results = []
    errors = []
    for command in TESTS:
        label = " ".join(command)
        completed = subprocess.run(["python3", *command], cwd=ROOT, capture_output=True, text=True, check=False, timeout=30)
        output = (completed.stdout + completed.stderr)[-2000:]
        ok = completed.returncode == 0 and "Ran 0 tests" not in output and "NO TESTS RAN" not in output
        results.append({"test": label, "ok": ok, "returncode": completed.returncode, "output_tail": output})
        if not ok:
            errors.append(f"{label} failed or ran zero tests")
    proof = {
        "schema": "wasm-agent.runtime-snapshot-contract-proof.v1",
        "ok": not errors,
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "results": results,
        "errors": errors,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
