#!/usr/bin/env python3
"""Deterministic promise entrypoint for the disposable procedure-memory pilot."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(name: str) -> dict:
    completed = subprocess.run(
        [sys.executable, name], cwd=ROOT, text=True, capture_output=True, timeout=30, check=False,
    )
    return {"command": name, "ok": completed.returncode == 0, "stdout": completed.stdout[-4000:], "stderr": completed.stderr[-4000:]}


def main() -> int:
    results = [run("test_procedure_kernel.py"), run("benchmark.py")]
    benchmark = json.loads((ROOT / "benchmark-result.json").read_text(encoding="utf-8"))
    ok = all(item["ok"] for item in results) and benchmark.get("decision") == "retain-candidate"
    print(json.dumps({
        "schema": "mf-v7.procedure-memory-pilot.promise.v1", "ok": ok,
        "classification": "retain-candidate" if ok else "prune-pilot",
        "results": results, "benchmark": benchmark,
    }, separators=(",", ":")))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
