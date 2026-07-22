#!/usr/bin/env python3
"""Launch nine fixed-authority safe-lab containers in parallel."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from private_evaluator.semantic_score import score_answer
from safe_lab_host import SafeLabHost, run

ROOT = Path(__file__).resolve().parents[2]
LAB = Path(__file__).resolve().parent
REGISTRY = LAB / "harness-adapters.json"
TOOL_AUTHORITY = LAB / "tool-authority-contract.json"
IMAGE = "wasm-agent-frontier:latest"
SOURCE_VOLUME = "wasm-agent-safe-lab-local-v11"
FIXTURE_VOLUME = "wasm-agent-safe-lab-output-v1"
ADJUDICATION_VOLUME = "wasm-agent-safe-lab-adjudication-v3"
ADJUDICATION_PATH = LAB / "staging/avatar-chat-adjudication-v3.sqlite3"
SAFE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
STRATEGIES = [
    "evidence-first", "minimal-tool", "recovery-first", "plan-then-act", "counterexample-first",
    "proof-first", "cost-aware", "state-machine", "adversarial-review",
]


def registry(path: Path = REGISTRY) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") == "wasm-agent.safe-lab.loop5-v5-candidates.v1":
        return {"modelContract": data["modelContract"], "adapters": data["candidates"], "candidateMatrix": data}
    return data


def preflight(data: dict, execution: str) -> list[str]:
    errors: list[str] = []
    adapters = data.get("adapters")
    if not isinstance(adapters, list) or len(adapters) != 9:
        errors.append("registry must contain exactly nine adapters")
        return errors
    slots = [item.get("slot") for item in adapters]
    if len(set(slots)) != 9 or slots != [f"harness-{index:02d}" for index in range(1, 10)]:
        errors.append("registry slots must be unique and ordered harness-01..harness-09")
    if (data.get("modelContract") or {}).get("model") != "frank/GLM-5.2":
        errors.append("registry model must be frank/GLM-5.2")
    authority_sha256 = hashlib.sha256(TOOL_AUTHORITY.read_bytes()).hexdigest()
    if (data.get("modelContract") or {}).get("toolAuthoritySha256") != authority_sha256:
        errors.append("registry tool authority digest does not match the owned contract")
    if execution == "live":
        for item in adapters:
            if (
                item.get("liveReady") is not True
                or item.get("benchmarkReady") is not True
                or item.get("modelContractStatus") != "verified"
                or item.get("toolAuthorityStatus") != "verified"
                or item.get("toolAuthoritySha256") != authority_sha256
            ):
                errors.append(f"live adapter not comparable: {item.get('id')}")
    return errors


def docker(*args: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], check=False, capture_output=capture, text=True)


def run_lane(
    run_id: str, slot: str, mode: str, execution: str, strategy: str,
    *, adapter: dict | None = None, model: dict | None = None,
    host: SafeLabHost | None = None, task_volume: str = "", task: dict | None = None,
) -> dict:
    lane = f"{run_id}-{slot}"
    if execution == "live" and host:
        workspace_volume = host.create_volume(f"{slot}-work")
        result_volume = host.create_volume(f"{slot}-result")
    else:
        workspace_volume = f"wa-lane-work-{lane}"
        result_volume = f"wa-lane-result-{lane}"
        for volume in (workspace_volume, result_volume):
            made = docker("volume", "create", volume)
            if made.returncode != 0:
                return {"slot": slot, "ok": False, "error": made.stderr.strip()}
    network = host.network if execution == "live" and host else "none"
    command = [
        "run", "--rm", "--network", network, "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "128", "--memory", "1g", "--cpus", "0.2",
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=64m",
    ]
    if execution == "live":
        assert adapter and model and host and task and task_volume
        env_file = host.env_file(slot, {
            "OPENAI_API_KEY": host.lane_token(slot),
            "FRONTIER_ENDPOINT": host.endpoint(),
            "FRONTIER_MODEL": str(model["model"]),
        })
        command.extend([
            "--env-file", str(env_file),
            "-e", f"MODEL_CONTRACT_JSON={json.dumps(model, separators=(',', ':'))}",
            "-e", f"ADAPTER_CONFIG_JSON={json.dumps(adapter, separators=(',', ':'))}",
            "-v", f"{adapter['adapterVolume']}:/adapter:ro", "-v", f"{task_volume}:/task:ro",
        ])
    command.extend([
        "-v", f"{SOURCE_VOLUME}:/source:ro", "-v", f"{FIXTURE_VOLUME}:/fixtures:ro",
        "-v", f"{workspace_volume}:/workspace", "-v", f"{result_volume}:/result",
        "--workdir", "/workspace", "--entrypoint", "python3", IMAGE, "/usr/local/bin/lane-runner",
        "--slot", slot, "--mode", mode, "--execution", execution, "--strategy", strategy,
    ])
    if execution == "live":
        command.extend(["--task", "/task/task.json"])
    completed = docker(*command)
    result = {"slot": slot, "ok": completed.returncode == 0, "workspaceVolume": workspace_volume, "resultVolume": result_volume}
    if completed.stdout.strip():
        try:
            result["lane"] = json.loads(completed.stdout.strip().splitlines()[-1])
        except ValueError:
            result["stdout"] = completed.stdout[-1000:]
    if completed.returncode != 0:
        result["error"] = completed.stderr[-2000:]
    if execution == "live" and host:
        try:
            answer = host.read_volume_file(result_volume, "answer.txt")
            result["answer"] = {
                "chars": len(answer), "sha256": hashlib.sha256(answer.encode()).hexdigest(),
                "semantic": score_answer(ADJUDICATION_PATH, str((task or {}).get("fixture", {}).get("id")), answer),
            }
        except RuntimeError as exc:
            result["answer"] = {"semantic": {"passed": False}, "error": str(exc)}
    return result


def max_concurrency(intervals: list[dict]) -> int:
    points: list[tuple[int, int]] = []
    for item in intervals:
        start = int(item.get("startedAtNs") or 0)
        end = int(item.get("endedAtNs") or 0)
        if start and end >= start:
            points.extend(((start, 1), (end, -1)))
    active = peak = 0
    for _timestamp, delta in sorted(points, key=lambda item: (item[0], item[1])):
        active += delta
        peak = max(peak, active)
    return peak


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("benchmark", "improve"), required=True)
    parser.add_argument("--execution", choices=("topology-proof", "live"), default="topology-proof")
    parser.add_argument("--run-id", default=f"loop-{int(time.time())}")
    parser.add_argument("--fixture-id", default="fx_d3154de08df6150be9c9")
    parser.add_argument("--candidate-manifest")
    args = parser.parse_args()
    if not SAFE.fullmatch(args.run_id):
        raise SystemExit("run-id must be lowercase alphanumeric/hyphen")
    registry_path = (ROOT / args.candidate_manifest).resolve() if args.candidate_manifest else REGISTRY
    if ROOT not in registry_path.parents or not registry_path.is_file(): raise SystemExit("registry or candidate manifest missing/outside workspace")
    data = registry(registry_path)
    errors = preflight(data, args.execution)
    if errors:
        print(json.dumps({"ok": False, "status": "comparability_failed", "errors": errors}, indent=2))
        return 2
    adapters = data["adapters"]
    host = SafeLabHost(f"nine-{args.run_id}") if args.execution == "live" else None
    task: dict = {}
    network_evidence: dict = {}
    receipts: list[dict] = []
    cleanup_errors: list[str] = []
    try:
        task_volume = ""
        if host:
            if not ADJUDICATION_PATH.is_file():
                raise RuntimeError("private adjudication overlay is missing")
            task_volume = host.create_volume("task")
            materialized = run([
                "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--user", "10000:10000", "--pids-limit", "64",
                "--memory", "256m", "--cpus", "0.25", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=32m",
                "-v", f"{SOURCE_VOLUME}:/source:ro", "-v", f"{FIXTURE_VOLUME}:/fixtures:ro",
                "-v", f"{ADJUDICATION_VOLUME}:/adjudication:ro", "-v", f"{task_volume}:/task",
                "--entrypoint", "python3", IMAGE, "/usr/local/bin/materialize-fixture-task",
                "--fixture-id", args.fixture_id, "--output", "/task/task.json",
            ], timeout=30)
            if materialized.returncode != 0:
                raise RuntimeError(materialized.stderr.strip() or "fixture task materialization failed")
            task = json.loads(host.read_volume_file(task_volume, "task.json"))
            if not (task.get("adjudication") or {}).get("rankingAllowed"):
                raise RuntimeError("fixture is not admitted for ranking")
            budgets = task.get("budgets") or {}
            host.start_gateway(
                max_output_tokens=int(budgets.get("maxOutputTokensPerCall") or 1024),
                max_provider_calls=9 * int(budgets.get("maxProviderCalls") or 4),
                benchmark_scenario=True,
            )
            network_evidence = host.network_evidence()
        with concurrent.futures.ThreadPoolExecutor(max_workers=9) as pool:
            futures = [pool.submit(
                run_lane, args.run_id, item["slot"], args.mode, args.execution, STRATEGIES[index],
                adapter=item, model=data["modelContract"], host=host, task_volume=task_volume, task=task,
            ) for index, item in enumerate(adapters)]
            results = [future.result() for future in futures]
        if host:
            receipts = host.receipts()
    finally:
        if host:
            host.cleanup()
            cleanup_errors = host.cleanup_errors
    all_ok = all(item["ok"] for item in results)
    semantic_pass = all((item.get("answer") or {}).get("semantic", {}).get("passed") is True for item in results) if args.execution == "live" else False
    comparable = all(bool((item.get("lane") or {}).get("comparable")) for item in results) and (semantic_pass if args.execution == "live" else True)
    strategy_comparable = comparable and all(
        (item.get("lane") or {}).get("strategyComparable") is True for item in results
    )
    intervals = [item.get("lane") or {} for item in results]
    peak_concurrency = max_concurrency(intervals)
    overlap = peak_concurrency >= 2
    report = {
        "schema": "wasm-agent.safe-lab.nine-lane-result.v1", "runId": args.run_id,
        "mode": args.mode, "execution": args.execution, "model": data["modelContract"]["model"],
        "laneCount": len(results), "allLanesCompleted": all_ok, "maxConcurrentLanes": peak_concurrency, "parallelOverlapProven": overlap, "comparable": comparable,
        "strategyComparable": strategy_comparable,
        "rankingAllowed": comparable, "status": "benchmark_complete" if comparable else ("topology_proven" if all_ok and overlap else "failed"),
        "results": results,
        "candidateMatrix": data.get("candidateMatrix") or {},
        "task": {key: value for key, value in task.items() if key != "prompt"},
        "networkEvidence": network_evidence,
        "gatewayReceipts": receipts,
        "semanticAllPassed": semantic_pass,
        "cleanupComplete": not cleanup_errors,
        "cleanupErrors": cleanup_errors,
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    out = LAB / "staging" / f"{args.run_id}-{args.mode}-nine-lane.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if all_ok and overlap else 1


if __name__ == "__main__":
    raise SystemExit(main())
