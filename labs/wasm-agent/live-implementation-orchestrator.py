#!/usr/bin/env python3
"""Run one brokered MF5 coding task in an isolated disposable repository."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from safe_lab_host import IMAGE, ROOT, SafeLabHost, run

LAB = Path(__file__).resolve().parent
DEFAULT_REPORT = ROOT / "reports/context/latest/master-frontier-v5-live-implementation-result.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter-volume", required=True)
    parser.add_argument("--fixture-id", choices=("retry-window-v1", "challenge-evolution-v1", "widget-evolution-v1"), default="retry-window-v1")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()
    report_path = Path(args.report).resolve()
    host = SafeLabHost("mf5-implementation")
    errors: list[str] = []
    task: dict = {}
    answer = ""
    started = time.monotonic()
    receipts: list[dict] = []
    trajectory_events: list[dict] = []
    verification: dict = {}
    try:
        task_volume = host.create_volume("task")
        workspace_volume = host.create_volume("work")
        result_volume = host.create_volume("result")
        materialized = run([
            "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", "10000:10000", "--pids-limit", "64",
            "--memory", "256m", "--cpus", "0.25", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=32m",
            "-v", f"{ROOT}:/source:ro", "-v", f"{task_volume}:/task", "-v", f"{workspace_volume}:/workspace",
            "--entrypoint", "python3", IMAGE, "/source/labs/wasm-agent/materialize-implementation-task.py",
            "--fixture-id", args.fixture_id, "--workspace", "/workspace/repo", "--output", "/task/task.json",
        ], timeout=30)
        if materialized.returncode:
            raise RuntimeError((materialized.stderr or materialized.stdout)[-1200:])
        task = json.loads(host.read_volume_file(task_volume, "task.json"))
        budgets = task["budgets"]
        host.start_gateway(max_output_tokens=budgets["maxOutputTokensPerCall"], max_provider_calls=budgets["maxProviderCalls"])
        network_evidence = host.network_evidence()
        lane_env = host.env_file("lane", {
            "OPENAI_API_KEY": host.broker_token,
            "FRONTIER_ENDPOINT": host.endpoint(),
            "FRONTIER_MODEL": task["model"],
            "WASM_AGENT_EVENTS_PATH": "/result/events.jsonl",
        })
        completed = run([
            "docker", "run", "--rm", "--network", host.network, "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", "10000:10000", "--pids-limit", "128",
            "--memory", "2g", "--cpus", "1", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=128m",
            "--env-file", str(lane_env), "-v", f"{args.adapter_volume}:/adapter:ro",
            "-v", f"{task_volume}:/task:ro", "-v", f"{workspace_volume}:/workspace",
            "-v", f"{result_volume}:/result", "--workdir", "/workspace/repo",
            "--entrypoint", "python3", IMAGE, "/adapter/master-frontier-v5-live-runner.py", "--task", "/task/task.json",
        ], timeout=budgets["wallClockSeconds"] + 30)
        answer = completed.stdout
        if completed.returncode:
            errors.append(f"adapter exited {completed.returncode}: {completed.stderr[-1200:]}")
        try:
            trajectory_events = [
                value for line in host.read_volume_file(result_volume, "events.jsonl").splitlines()
                if line.strip() and isinstance((value := json.loads(line)), dict)
            ][-128:]
        except (RuntimeError, json.JSONDecodeError):
            trajectory_events = []
        checked = run([
            "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", "10000:10000",
            "-v", f"{workspace_volume}:/workspace:ro", "--workdir", "/workspace/repo",
            "--entrypoint", "python3", IMAGE, "-c",
            "import json,subprocess; "
            f"cmd={['node', '--check', 'meta-analysis-widget.js'] if args.fixture_id == 'widget-evolution-v1' else ['python3','-m','unittest','discover','-s','tests','-v']!r}; "
            "t=subprocess.run(cmd,capture_output=True,text=True); "
            "d=subprocess.run(['git','diff','--name-only'],capture_output=True,text=True); "
            "p=subprocess.run(['git','diff','--no-ext-diff','--'],capture_output=True,text=True); "
            "print(json.dumps({'testsPassed':t.returncode==0,'changedFiles':d.stdout.splitlines(),'patch':p.stdout[:120000]})); "
            "raise SystemExit(0 if t.returncode==0 else 3)",
        ], timeout=30)
        if checked.stdout.strip():
            verification = json.loads(checked.stdout.strip().splitlines()[-1])
        expected_file = {"retry-window-v1": "retry_window.py", "challenge-evolution-v1": "challenge_cases.py", "widget-evolution-v1": "meta-analysis-widget.js"}[args.fixture_id]
        if checked.returncode or verification.get("changedFiles") != [expected_file]:
            errors.append("independent test/diff verification failed")
        receipts = host.receipts()
        successful_receipts = [
            item for item in receipts
            if item.get("upstreamCalled") and item.get("status") == 200 and item.get("contractMatch") is True
        ]
        if not successful_receipts:
            errors.append("broker receipts did not prove successful provider calls")
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        network_evidence = {}
    finally:
        if not receipts:
            receipts = host.receipts()
        host.cleanup()
        errors.extend(host.cleanup_errors)
    result = {
        "schema": "wasm-agent.safe-lab.live-implementation-result.v1", "ok": not errors,
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "durationMs": round((time.monotonic() - started) * 1000), "taskDigest": task.get("taskDigest"),
        "adapterVolume": args.adapter_volume, "answer": answer[:4000], "verification": verification,
        "trajectoryEvents": trajectory_events,
        "gatewayReceipts": receipts, "networkEvidence": network_evidence, "errors": errors,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
