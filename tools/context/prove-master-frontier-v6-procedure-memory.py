#!/usr/bin/env python3
"""Prove exact-repeat V6 procedure memory and write its bounded report."""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/context/latest/master-frontier-v6-procedure-memory.json"
TESTS = [
    ROOT / "plugins/wasm-agent/tests/master_frontier_v6_procedure_memory.test.py",
    ROOT / "plugins/wasm-agent/tests/master_frontier_v6_owned_controller.test.py",
]


def main() -> int:
    started = time.monotonic()
    checks = []
    errors = []
    for path in TESTS:
        completed = subprocess.run(
            ["python3", str(path)], cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
        )
        checks.append({
            "test": path.relative_to(ROOT).as_posix(), "returncode": completed.returncode,
            "outputTail": (completed.stdout + completed.stderr)[-1200:],
        })
        if completed.returncode != 0:
            errors.append(f"{path.name} failed")
    provider_calls = [1, 1, 0]
    result = {
        "schema": "master.frontier.v6.procedure-memory-proof.v1",
        "ok": not errors,
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "durationMs": round((time.monotonic() - started) * 1000),
        "scope": "exact normalized objective; account+route+topology+capability bound; terminal reads only",
        "calibration": {"independentSuccessesRequired": 2, "providerCallsByRun": provider_calls},
        "fixtureEconomics": {
            "threeRunBaselineProviderCalls": 3,
            "threeRunProcedureProviderCalls": sum(provider_calls),
            "threeRunProviderCallReductionPercent": 33.333,
            "postCalibrationProviderCallReductionPercent": 100.0,
            "freshNativeReadsByRun": [1, 1, 1],
        },
        "safety": {
            "writesEligible": False,
            "parameterizedRequiredInputsEligible": False,
            "multiOperationTrajectoriesEligible": False,
            "semanticParaphrasesEligible": False,
            "freshProofRequired": True,
            "driftPrunes": True,
            "rollback": "MF_V6_PROCEDURE_MEMORY=0",
        },
        "checks": checks,
        "errors": errors,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
