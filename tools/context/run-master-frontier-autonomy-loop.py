#!/usr/bin/env python3
"""Run Master:frontier usefulness proofs in cheap-to-expensive order."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "reports/context/latest/master-frontier-autonomy-loop.json"
WATCH_REPORT = ROOT / "reports/context/latest/master-frontier-watch.json"
AVATAR_REPORT = ROOT / "reports/sim/avatar-quest/latest/result.json"
NODE_REPORT = ROOT / "reports/context/latest/wasm-agent-node-bridge-proof.json"
PRODUCTION_REPORT = ROOT / "reports/context/latest/master-frontier-production-proof.json"

Runner = Callable[[list[str], int], tuple[int | None, str, str, int]]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def default_runner(argv: list[str], timeout_sec: int) -> tuple[int | None, str, str, int]:
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
        return proc.returncode, proc.stdout[-4000:], proc.stderr[-4000:], int((time.monotonic() - started) * 1000)
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "timeout"
        return None, stdout, stderr or "timeout", int((time.monotonic() - started) * 1000)


def run_step(name: str, argv: list[str], *, timeout_sec: int, runner: Runner) -> dict[str, Any]:
    returncode, stdout, stderr, duration_ms = runner(argv, timeout_sec)
    return {
        "name": name,
        "command": argv,
        "status": "pass" if returncode == 0 else "fail",
        "returncode": returncode,
        "durationMs": duration_ms,
        "stdoutTail": stdout,
        "stderrTail": stderr,
    }


def compact_watch_summary() -> dict[str, Any]:
    payload = load_json(WATCH_REPORT)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    capability = summary.get("capability") if isinstance(summary.get("capability"), dict) else {}
    outcome = summary.get("engineeringOutcome") if isinstance(summary.get("engineeringOutcome"), dict) else {}
    return {
        "ok": bool(payload.get("ok")),
        "capability": capability.get("current"),
        "engineeringOutcome": {
            "status": outcome.get("status"),
            "acceptedMetricCount": outcome.get("acceptedMetricCount", 0),
            "requiredMetricCount": outcome.get("requiredMetricCount", 0),
            "realEngineeringProblemSolved": outcome.get("realEngineeringProblemSolved", ""),
        },
        "missingQuestIds": capability.get("missingQuestIds", []),
        "missingProofArtifactIds": capability.get("missingProofArtifactIds", []),
        "proofArtifactsPassed": summary.get("proofArtifactsPassed", 0),
    }


def report_ok(path: Path) -> bool:
    return bool(load_json(path).get("ok") or load_json(path).get("status") == "passed")


def run(
    *,
    report_path: Path = REPORT_PATH,
    include_avatar: bool = False,
    include_node: bool = False,
    include_production: bool = True,
    timeout_sec: int = 240,
    runner: Runner = default_runner,
) -> dict[str, Any]:
    started = time.monotonic()
    steps: list[dict[str, Any]] = []

    if include_avatar:
        steps.append(run_step("avatar-quest", ["horc", "simulate", "web", "--avatar-quest"], timeout_sec=timeout_sec, runner=runner))
        if steps[-1]["status"] != "pass":
            include_node = False
            include_production = False

    if include_node:
        steps.append(run_step("node-bridge-proof", ["python3", "tools/context/prove-wasm-agent-node-bridge.py"], timeout_sec=timeout_sec, runner=runner))
        if steps[-1]["status"] != "pass":
            include_production = False

    watch_args = ["python3", "tools/context/watch-master-frontier-loop.py", "--require-proof-artifacts"]
    steps.append(run_step("watch-loop", watch_args, timeout_sec=60, runner=runner))
    if steps[-1]["status"] != "pass":
        include_production = False

    if include_production:
        steps.append(run_step("production-gate", ["python3", "tools/context/prove-master-frontier-production.py"], timeout_sec=timeout_sec, runner=runner))

    failed = [step for step in steps if step.get("status") != "pass"]
    watch = compact_watch_summary()
    report = {
        "schema": "hermes.context.master_frontier.autonomy_loop.v1",
        "ok": not failed and watch.get("ok"),
        "checkedAt": utc_now(),
        "durationMs": int((time.monotonic() - started) * 1000),
        "builder": {
            "intent": "run Master:frontier contract checks in cheap-to-expensive order",
            "strategy": "compact watcher first unless fresh avatar/node proofs are explicitly requested; production gate last",
        },
        "watcher": {
            "steps": steps,
            "watchSummary": watch,
            "artifacts": {
                "watch": str(WATCH_REPORT),
                "avatar": str(AVATAR_REPORT),
                "node": str(NODE_REPORT),
                "production": str(PRODUCTION_REPORT),
            },
        },
        "gatekeeper": {
            "decision": "promote" if not failed and watch.get("ok") and watch.get("engineeringOutcome", {}).get("status") == "useful" else "repair",
            "failed": [step["name"] for step in failed],
            "nextSuggestedStep": "Fix the first failed owning contract before adding a reviewed regression quest." if failed else "Run fresh avatar/node proof before raising the observed capability level.",
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-avatar", action="store_true", help="Run horc simulate web --avatar-quest before scoring.")
    parser.add_argument("--include-node", action="store_true", help="Run node bridge runtime proof before scoring.")
    parser.add_argument("--skip-production", action="store_true", help="Skip the composed production gate.")
    parser.add_argument("--timeout-sec", type=int, default=240)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = run(
        report_path=args.report.resolve(),
        include_avatar=args.include_avatar,
        include_node=args.include_node,
        include_production=not args.skip_production,
        timeout_sec=args.timeout_sec,
    )
    watch = report["watcher"]["watchSummary"]
    print(
        "Master:frontier usefulness loop: "
        f"{'PASS' if report['ok'] else 'FAIL'} "
        f"({watch.get('engineeringOutcome', {}).get('status') or watch.get('capability') or 'unknown'})"
    )
    print(f"Report JSON: {args.report}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
