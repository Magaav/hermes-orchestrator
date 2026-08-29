#!/usr/bin/env python3
"""Select the cheapest valid native evolution lane from owned path contracts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROUTES = Path(__file__).with_name("native-evolution-routes.json")
DEFAULT_PROOF = ROOT / "reports/windows/latest/hot-shell-proof-result.json"


def changed_paths(root: Path) -> list[str]:
    commands = (
        ["git", "diff", "--name-only", "--relative", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    )
    paths: set[str] = set()
    for command in commands:
        result = subprocess.run(command, cwd=root, check=True, capture_output=True, text=True)
        paths.update(line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip())
    return sorted(paths)


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def proof_capabilities(proof: dict) -> set[str]:
    result = proof.get("results", {}).get("get_bridge_status", {}).get("result", {})
    kernel = result.get("nativeKernel") or result.get("kernel") or {}
    return set(kernel.get("supportedCapabilities") or [])


def select(paths: list[str], target: str, routes: dict, proof: dict | None) -> dict:
    priority = routes["priority"]
    matches = []
    for raw_path in paths:
        path = raw_path.replace("\\", "/").lstrip("./")
        for route in routes["routes"]:
            if target in route["targets"] and path.startswith(route["prefix"]):
                matches.append({"path": path, **route})
                break
    lane = min((item["lane"] for item in matches), key=priority.index, default="no-build")
    selected = [item for item in matches if item["lane"] == lane]
    required = sorted({cap for item in selected for cap in item.get("requiredCapabilities", [])})
    available = proof_capabilities(proof or {})
    missing = sorted(set(required) - available)
    proof_ok = bool(proof and proof.get("ok") is True)
    allowed = lane == "native-rebuild" or lane in {"cloud-module", "no-build"} or (proof_ok and not missing)
    reason = {
        "native-rebuild": "changed path owns compiled shell, preload, installer, or platform code",
        "hot-bundle": "existing installed primitive can receive an atomic runtime/hot-op bundle",
        "cloud-module": "change is served by the cloud application",
        "no-build": "no native evolution route matched",
    }[lane]
    if lane == "hot-bundle" and not proof_ok:
        reason = "installed native-kernel proof is missing or unsuccessful"
    elif missing:
        reason = "installed native kernel lacks required capabilities"
    return {
        "schema": "hermes.wasm_agent.native_evolution_decision.v1",
        "target": target,
        "lane": lane,
        "nativeBuildAllowed": lane == "native-rebuild",
        "laneActionAllowed": allowed,
        "reason": reason,
        "requiredCapabilities": required,
        "missingCapabilities": missing,
        "matchedPaths": sorted(item["path"] for item in selected),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("windows", "android"), required=True)
    parser.add_argument("--path", action="append", dest="paths")
    parser.add_argument("--routes", type=Path, default=DEFAULT_ROUTES)
    parser.add_argument("--proof", type=Path, default=DEFAULT_PROOF)
    parser.add_argument("--require-native-build", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    routes = load_json(args.routes)
    proof = load_json(args.proof) if args.proof.is_file() else None
    decision = select(args.paths if args.paths is not None else changed_paths(ROOT), args.target, routes, proof)
    if args.json:
        print(json.dumps(decision, sort_keys=True, separators=(",", ":")))
    else:
        print(f"native evolution: target={args.target} lane={decision['lane']} reason={decision['reason']}")
        if decision["missingCapabilities"]:
            print("native evolution: missing=" + ",".join(decision["missingCapabilities"]), file=sys.stderr)
    if args.require_native_build and not decision["nativeBuildAllowed"]:
        print(f"native evolution: blocked installer build; use lane {decision['lane']}", file=sys.stderr)
        return 3
    if not decision["laneActionAllowed"]:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
