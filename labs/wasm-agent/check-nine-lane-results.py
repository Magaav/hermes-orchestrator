#!/usr/bin/env python3
"""Validate nine-lane topology proofs without treating them as live benchmarks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+")
    args = parser.parse_args()
    errors: list[str] = []
    modes: set[str] = set()
    for name in args.reports:
        path = Path(name)
        report = json.loads(path.read_text(encoding="utf-8"))
        prefix = path.name
        modes.add(str(report.get("mode")))
        results = report.get("results") if isinstance(report.get("results"), list) else []
        if report.get("laneCount") != 9 or len(results) != 9:
            errors.append(f"{prefix}: expected nine lanes")
            continue
        if report.get("parallelOverlapProven") is not True:
            errors.append(f"{prefix}: parallel overlap not proven")
        if int(report.get("maxConcurrentLanes") or 0) < 2:
            errors.append(f"{prefix}: fewer than two lanes overlapped")
        if report.get("execution") == "topology-proof":
            if report.get("comparable") is not False or report.get("rankingAllowed") is not False:
                errors.append(f"{prefix}: topology proof must remain non-comparable and unranked")
        elif report.get("execution") == "live":
            if report.get("comparable") is not True or report.get("rankingAllowed") is not True:
                errors.append(f"{prefix}: live benchmark must be comparable and rankable")
            if report.get("semanticAllPassed") is not True:
                errors.append(f"{prefix}: not every lane passed private semantic scoring")
            if report.get("cleanupComplete") is not True:
                errors.append(f"{prefix}: live benchmark cleanup incomplete")
            evidence = report.get("networkEvidence") or {}
            if evidence.get("gatewayReachable") is not True or evidence.get("directUpstreamBlocked") is not True:
                errors.append(f"{prefix}: live network isolation proof missing")
            lanes = [item.get("lane") or {} for item in results]
            digests = {(item.get("task") or {}).get("taskDigest") for item in lanes}
            if len(digests) != 1 or None in digests:
                errors.append(f"{prefix}: live task digests differ")
        slots = [item.get("slot") for item in results]
        workspaces = [item.get("workspaceVolume") for item in results]
        outputs = [item.get("resultVolume") for item in results]
        if len(set(slots)) != 9 or len(set(workspaces)) != 9 or len(set(outputs)) != 9:
            errors.append(f"{prefix}: lane slots/workspaces/results are not unique")
        lanes = [item.get("lane") or {} for item in results]
        if len({item.get("sourceDigest") for item in lanes}) != 1:
            errors.append(f"{prefix}: source digests differ")
        if any((item.get("fixtures") or {}).get("fixtures") != 400 for item in lanes):
            errors.append(f"{prefix}: fixture coverage differs")
        if report.get("mode") == "improve" and len({item.get("strategy") for item in lanes}) != 9:
            errors.append(f"{prefix}: Loop 5 strategies are not distinct")
    if modes != {"benchmark", "improve"}:
        errors.append("reports must cover benchmark and improve modes")
    print(json.dumps({"ok": not errors, "modes": sorted(modes), "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
