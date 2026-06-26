#!/usr/bin/env python3
"""Emit compact loop-copilot signals for active agent loops.

The loop copilot is intentionally read-only. It watches cheap local evidence
and writes short steering signals that a worker agent can consult before slow
runtime work, rebuilds, or final claims.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "reports/context/latest/loop-copilot-signals.json"
JSONL_PATH = ROOT / "reports/context/latest/loop-copilot-signals.jsonl"

DEV_ORIGIN_RE = re.compile(r"127\.0\.0\.1:8877|localhost:8877|0\.0\.0\.0:8877|10\.0\.2\.2:8877")
WIN_UNPACKED_RE = re.compile(r"\bwin-unpacked\b")
SUCCESS_RE = re.compile(r"\b(fixed|done|complete|works|verified)\b", re.IGNORECASE)
GUARD_RE = re.compile(r"\b(forbidden|dev-only|never|do not|not proof|not runtime proof|guard|demote|unverified)\b", re.IGNORECASE)

PROCESS_HINTS = (
    ("codex-app-server", "codex app-server"),
    ("wasm-static-server", "static_server.py"),
    ("native-bridge", "plugins/wasm-agent/server/bridge.py"),
    ("android-control-loop", "native-control"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def run(args: list[str], timeout: int = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=False)


def add_signal(signals: list[dict[str, Any]], severity: str, checkpoint: str, reason: str, next_action: str, evidence: list[str]) -> None:
    signals.append(
        {
            "severity": severity,
            "checkpoint": checkpoint,
            "reason": reason,
            "nextAction": next_action,
            "evidence": evidence,
        }
    )


def inspect_processes(signals: list[dict[str, Any]]) -> dict[str, Any]:
    proc = run(["ps", "-eo", "pid,ppid,stat,etime,command"], timeout=8)
    text = proc.stdout if proc.returncode == 0 else ""
    matches: dict[str, list[str]] = {name: [] for name, _ in PROCESS_HINTS}
    for line in text.splitlines():
        for name, needle in PROCESS_HINTS:
            if needle in line and "watch-loop-copilot.py" not in line:
                matches[name].append(line.strip())

    if matches["android-control-loop"] and not matches["native-bridge"]:
        add_signal(
            signals,
            "blocker",
            "runtime-control",
            "Android/native-control work is visible but the local native bridge process was not found.",
            "Run the windows-hot-shell-proof promise before treating Android as disconnected.",
            ["process scan"],
        )
    elif matches["android-control-loop"]:
        add_signal(
            signals,
            "info",
            "runtime-control",
            "An Android/native-control loop appears active.",
            "Use compact native-control results or wake-word state before rebuilding or asking for screen state.",
            ["process scan"],
        )

    if matches["codex-app-server"]:
        add_signal(
            signals,
            "info",
            "agent-loop",
            "A Codex app-server process is running in this environment.",
            "Treat this as process evidence only; do not infer the other thread's reasoning state.",
            ["process scan"],
        )

    return {"returncode": proc.returncode, "matches": {key: len(value) for key, value in matches.items()}}


def inspect_git(signals: list[dict[str, Any]]) -> dict[str, Any]:
    status = run(["git", "status", "--short"], timeout=8)
    lines = [line for line in status.stdout.splitlines() if line.strip()] if status.returncode == 0 else []
    if len(lines) >= 20:
        add_signal(
            signals,
            "warn",
            "edit-scope",
            f"Worktree has {len(lines)} changed paths, so unrelated user or loop edits may be present.",
            "Before editing, inspect target files and preserve unrelated changes.",
            ["git status --short"],
        )

    diff = run(["git", "diff", "--", "README.md", "AGENTS.md", "docs/context", "plugins/wasm-agent", "native"], timeout=12)
    diff_text = diff.stdout if diff.returncode == 0 else ""
    added_lines = [
        line[1:].strip()
        for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++") and line[1:].strip()
    ]
    risky_dev = [line for line in added_lines if DEV_ORIGIN_RE.search(line) and "production" in line.lower() and not GUARD_RE.search(line)]
    risky_win = [line for line in added_lines if WIN_UNPACKED_RE.search(line) and SUCCESS_RE.search(line) and not GUARD_RE.search(line)]
    proof_words = [line for line in added_lines if SUCCESS_RE.search(line) and not GUARD_RE.search(line)]
    if risky_dev:
        add_signal(
            signals,
            "blocker",
            "final-claim",
            "Added diff lines appear to mix production claims with dev-only origins.",
            "Rewrite as a guard/dev-only statement or demote the claim before finalizing.",
            ["git diff added lines"],
        )
    if risky_win:
        add_signal(
            signals,
            "blocker",
            "final-claim",
            "Added diff lines may imply win-unpacked is sufficient proof.",
            "Require final NSIS extraction and installed app.asar verification before claiming Windows package proof.",
            ["git diff added lines"],
        )
    if proof_words and not risky_dev and not risky_win:
        add_signal(
            signals,
            "warn",
            "final-claim",
            "Added diff lines include success/proof words that may need verification status review.",
            "Run the context smell scan if these lines affect durable claims.",
            ["git diff added lines"],
        )

    return {"returncode": status.returncode, "changedPathCount": len(lines)}


def inspect_harness(signals: list[dict[str, Any]]) -> dict[str, Any]:
    proc = run(["python3", "tools/context/check-harness-promises.py"], timeout=20)
    ok = proc.returncode == 0
    if not ok:
        add_signal(
            signals,
            "blocker",
            "harness-registry",
            "Harness promise registry validation failed.",
            "Fix the first registry error before relying on promise-based loop steering.",
            ["python3 tools/context/check-harness-promises.py"],
        )
    return {"returncode": proc.returncode, "ok": ok}


def write_reports(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    with JSONL_PATH.open("a", encoding="utf-8") as handle:
        for signal in report["signals"]:
            handle.write(json.dumps({"checkedAt": report["checkedAt"], **signal}, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    args = parser.parse_args()

    signals: list[dict[str, Any]] = []
    observations = {
        "processes": inspect_processes(signals),
        "git": inspect_git(signals),
        "harness": inspect_harness(signals),
    }
    severity_rank = {"info": 0, "warn": 1, "blocker": 2}
    max_severity = max((severity_rank.get(signal["severity"], 0) for signal in signals), default=0)
    classification = "loop_copilot_blocked" if max_severity >= 2 else "loop_copilot_warn" if max_severity == 1 else "loop_copilot_pass"
    report = {
        "ok": max_severity < 2,
        "classification": classification,
        "checkedAt": utc_now(),
        "signals": signals,
        "observations": observations,
        "reportPath": rel(REPORT_PATH),
        "jsonlPath": rel(JSONL_PATH),
    }
    write_reports(report)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Loop copilot: {'PASS' if report['ok'] else 'BLOCKED'} ({classification})")
        print(f"Report JSON: {rel(REPORT_PATH)}")
        for signal in signals:
            print(f"- {signal['severity']}: {signal['checkpoint']}: {signal['reason']}")
            print(f"  next: {signal['nextAction']}")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
