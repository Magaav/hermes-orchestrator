#!/usr/bin/env python3
"""Compose structural session fixtures with the fail-closed adapter classifier."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run(argv: list[str]) -> int:
    completed = subprocess.run(argv, cwd=ROOT, check=False)
    return int(completed.returncode)


def main() -> int:
    suite = "labs/wasm-agent/fixtures/master-frontier-session-suite-v1.json"
    first = run([
        sys.executable, "labs/wasm-agent/check-session-fixtures.py", suite,
        "--report", "reports/context/latest/session-fixture-proof.json",
    ])
    if first:
        return first
    return run([
        sys.executable, "labs/wasm-agent/check-session-comparability.py",
        "labs/wasm-agent/session-adapter-capabilities.json",
        "--registry", "labs/wasm-agent/harness-adapters.json", "--suite", suite,
        "--report", "reports/context/latest/session-comparability-proof.json",
    ])


if __name__ == "__main__": raise SystemExit(main())
