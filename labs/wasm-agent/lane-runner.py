#!/usr/bin/env python3
"""Execute one isolated benchmark/improvement lane inside a safe-lab container."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

from agent_trajectory import EVENT_PATH_ENV, write_trajectory

SOURCE = Path("/source")
WORKSPACE = Path("/workspace")
RESULT = Path("/result")
FIXTURE_BANK = Path("/fixtures/avatar-chat-fixtures-v2.sqlite3")
ADAPTER_EVENTS = WORKSPACE / ".wasm-agent-adapter-events.jsonl"


def adapter_environment(
    base: dict[str, str] | None = None, events_path: Path = ADAPTER_EVENTS,
) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env[EVENT_PATH_ENV] = str(events_path)
    return env


def trajectory_projection(trajectory: dict) -> dict:
    """Keep the normalized bounded events attached to the lane receipt."""

    return {
        "schema": trajectory["schema"],
        **trajectory["metadata"],
        "events": trajectory["events"],
    }


def load_adapter(registry: Path, slot: str) -> tuple[dict, dict]:
    data = json.loads(registry.read_text(encoding="utf-8"))
    adapters = [item for item in data.get("adapters", []) if item.get("slot") == slot]
    if len(adapters) != 1:
        raise RuntimeError(f"adapter slot must resolve exactly once: {slot}")
    return data["modelContract"], adapters[0]


def load_live_adapter(slot: str) -> tuple[dict, dict]:
    try:
        model = json.loads(os.environ["MODEL_CONTRACT_JSON"])
        adapter = json.loads(os.environ["ADAPTER_CONFIG_JSON"])
    except (KeyError, ValueError) as exc:
        raise RuntimeError("trusted live adapter projection missing") from exc
    if adapter.get("slot") != slot:
        raise RuntimeError("live adapter projection does not match lane slot")
    return model, adapter


def fixture_summary() -> dict:
    conn = sqlite3.connect(f"file:{FIXTURE_BANK}?mode=ro", uri=True)
    summary = {
        "fixtures": conn.execute("SELECT COUNT(*) FROM fixture_candidate").fetchone()[0],
        "sessions": conn.execute("SELECT COUNT(DISTINCT session_ref) FROM fixture_candidate").fetchone()[0],
        "pending": conn.execute("SELECT COUNT(*) FROM fixture_candidate WHERE adjudication_status='pending'").fetchone()[0],
    }
    conn.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", required=True)
    parser.add_argument("--mode", choices=("benchmark", "improve"), required=True)
    parser.add_argument("--execution", choices=("topology-proof", "live-proof", "live"), required=True)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--registry", default="/source/labs/wasm-agent/harness-adapters.json")
    parser.add_argument("--task", default="/task/task.json")
    args = parser.parse_args()
    started = time.monotonic()
    started_ns = time.time_ns()
    if args.execution in {"live-proof", "live"}:
        model, adapter = load_live_adapter(args.slot)
    else:
        model, adapter = load_adapter(Path(args.registry), args.slot)
    RESULT.mkdir(parents=True, exist_ok=True)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    task_preview = json.loads(Path(args.task).read_text(encoding="utf-8")) if Path(args.task).is_file() else {}
    implementation_task = task_preview.get("schema") == "wasm-agent.safe-lab.implementation-task.v1"
    allowed_workspace_entries = {"repo"} if implementation_task else set()
    if {item.name for item in WORKSPACE.iterdir()} - allowed_workspace_entries or any(RESULT.iterdir()):
        raise SystemExit("lane volumes must be empty")
    marker = WORKSPACE / "lane-authority.json"
    marker.write_text(json.dumps({"slot": args.slot, "strategy": args.strategy}) + "\n", encoding="utf-8")
    if args.execution == "topology-proof":
        time.sleep(0.2)
    source_digest = hashlib.sha256((SOURCE / "docs/context/HARNESS_LOOPS.json").read_bytes()).hexdigest()
    fixtures = fixture_summary()
    status = "topology_proven"
    comparable = False
    reason = "simulated adapter; topology proof cannot be ranked"
    command_result: dict = {}
    readiness_candidate = False
    task_summary: dict = {}
    if args.execution in {"live-proof", "live"}:
        if adapter.get("modelContractStatus") != "verified" or adapter.get("toolAuthorityStatus") != "verified":
            raise SystemExit(f"live adapter not verified: {adapter['id']}")
        if args.execution == "live" and adapter.get("liveReady") is not True:
            raise SystemExit(f"live adapter not ready: {adapter['id']}")
        executable = shutil.which(str(adapter.get("executable") or ""))
        if not executable:
            raise SystemExit(f"live adapter executable missing: {adapter['id']}")
        if os.environ.get("FRONTIER_MODEL") != model["model"] or not os.environ.get("FRONTIER_ENDPOINT"):
            raise SystemExit("live model identity or endpoint missing")
        task = task_preview
        if task.get("schema") not in {
            "wasm-agent.safe-lab.fixture-task.v1", "wasm-agent.safe-lab.implementation-task.v1",
        } or task.get("model") != model["model"]:
            raise SystemExit("fixture task model or schema mismatch")
        if not (task.get("adjudication") or {}).get("executionAllowed"):
            raise SystemExit("fixture task is not approved for execution")
        command = adapter.get("liveCommand")
        if not isinstance(command, list) or not command:
            raise SystemExit("verified adapter command missing")
        replacements = {"{task}": args.task, "{model}": model["model"]}
        resolved = [replacements.get(str(item), str(item)) for item in command]
        timeout = min(300, max(1, int((task.get("budgets") or {}).get("wallClockSeconds") or 180)))
        timed_out = False
        try:
            adapter_env = adapter_environment()
            completed = subprocess.run(resolved, cwd=WORKSPACE, env=adapter_env, capture_output=True, text=True, timeout=timeout, check=False)
            returncode = completed.returncode
            raw_stdout = completed.stdout
            raw_stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = 124
            raw_stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            raw_stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        token = os.environ.get("OPENAI_API_KEY", "")
        stdout = raw_stdout.replace(token, "[redacted]") if token else raw_stdout
        stderr = raw_stderr.replace(token, "[redacted]") if token else raw_stderr
        maximum_answer = int((task.get("budgets") or {}).get("maxAnswerBytes") or 65536)
        encoded = stdout.encode("utf-8")
        answer_within_budget = len(encoded) <= maximum_answer
        if answer_within_budget:
            (RESULT / "answer.txt").write_text(stdout, encoding="utf-8")
        readiness_candidate = returncode == 0 and bool(stdout.strip()) and answer_within_budget
        ranking_allowed = bool((task.get("adjudication") or {}).get("rankingAllowed"))
        comparable = readiness_candidate and ranking_allowed and adapter.get("liveReady") is True
        status = "completed" if readiness_candidate else "failed"
        reason = "live fixture task completed" if readiness_candidate else "live fixture task failed"
        task_summary = {
            "fixtureId": (task.get("fixture") or {}).get("id"),
            "taskDigest": task.get("taskDigest"),
            "adjudication": task.get("adjudication"),
            "rankingAllowed": ranking_allowed,
        }
        command_result = {
            "returncode": returncode,
            "timedOut": timed_out,
            "stdoutChars": len(stdout),
            "stdoutSha256": hashlib.sha256(encoded).hexdigest(),
            "stderrChars": len(stderr),
            "stderrTail": stderr[-1000:] if returncode else "",
            "answerWithinBudget": answer_within_budget,
        }
    ended_ns = time.time_ns()
    trajectory = write_trajectory(
        RESULT / "events.jsonl", ADAPTER_EVENTS,
        terminal_status=status, slot=args.slot, terminal_summary=reason,
    )
    strategy_comparable = comparable and trajectory["metadata"]["admissibleForStrategyMining"] is True
    report = {
        "schema": "wasm-agent.safe-lab.lane-result.v1",
        "slot": args.slot,
        "adapter": adapter["id"],
        "mode": args.mode,
        "execution": args.execution,
        "strategy": args.strategy,
        "model": model["model"],
        "sourceDigest": source_digest,
        "fixtures": fixtures,
        "status": status,
        "comparable": comparable,
        "rankingEligible": comparable,
        "strategyComparable": strategy_comparable,
        "reason": reason,
        "startedAtNs": started_ns,
        "endedAtNs": ended_ns,
        "command": command_result,
        "task": task_summary,
        "readinessCandidatePassed": readiness_candidate,
        "durationMs": round((time.monotonic() - started) * 1000),
        "trajectory": trajectory_projection(trajectory),
    }
    (RESULT / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, separators=(",", ":")))
    return 0 if status in {"topology_proven", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
