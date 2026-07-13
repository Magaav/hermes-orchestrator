#!/usr/bin/env python3
"""Prove Loop 3/5 nine-lane topology and clean only proof-owned volumes."""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = Path(__file__).resolve().parent
REPORT = ROOT / "reports/context/latest/nine-lane-topology-result.json"


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)


def main() -> int:
    stamp = f"promise-{int(time.time())}"
    run_ids = {"benchmark": f"loop3-{stamp}", "improve": f"loop5-{stamp}"}
    reports: list[Path] = []
    errors: list[str] = []
    volumes: list[str] = []
    started = time.monotonic()
    try:
        for mode, run_id in run_ids.items():
            completed = run([
                "python3", str(LAB / "nine-lane-orchestrator.py"),
                "--mode", mode, "--execution", "topology-proof", "--run-id", run_id,
            ])
            if completed.returncode != 0:
                errors.append(f"{mode} orchestration failed: {completed.stderr[-1000:] or completed.stdout[-1000:]}")
                continue
            path = LAB / "staging" / f"{run_id}-{mode}-nine-lane.json"
            reports.append(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            for item in payload.get("results", []):
                volumes.extend([str(item.get("workspaceVolume") or ""), str(item.get("resultVolume") or "")])
        if len(reports) == 2:
            checked = run(["python3", str(LAB / "check-nine-lane-results.py"), *(str(path) for path in reports)])
            if checked.returncode != 0:
                errors.append(f"result validation failed: {checked.stdout[-2000:]}")
        else:
            errors.append("both benchmark and improve reports are required")
    finally:
        for volume in sorted(set(filter(None, volumes))):
            removed = run(["docker", "volume", "rm", volume])
            if removed.returncode != 0:
                errors.append(f"failed to remove proof volume {volume}: {removed.stderr.strip()}")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "ok": not errors,
        "classification": "nine_lane_topology_pass" if not errors else "nine_lane_topology_fail",
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "durationMs": round((time.monotonic() - started) * 1000),
        "model": "frank/GLM-5.2",
        "laneCountPerMode": 9,
        "modes": ["benchmark", "improve"],
        "liveComparable": False,
        "rankingAllowed": False,
        "reports": [str(path.relative_to(ROOT)) for path in reports],
        "errors": errors,
    }
    REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
