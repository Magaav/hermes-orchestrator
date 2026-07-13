#!/usr/bin/env python3
"""Claude Code adapter for the canonical safe-lab fixture task."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    task = json.loads(Path(args.task).read_text(encoding="utf-8"))
    endpoint = os.environ.get("FRONTIER_ENDPOINT", "").strip().rstrip("/")
    token = os.environ.get("OPENAI_API_KEY", "")
    if task.get("schema") != "wasm-agent.safe-lab.fixture-task.v1" or not task.get("taskDigest"):
        raise SystemExit("invalid digest-bound fixture task")
    if os.environ.get("FRONTIER_MODEL") != "frank/GLM-5.2" or not endpoint or not token:
        raise SystemExit("exact brokered model contract missing")
    base_url = endpoint[:-3] if endpoint.endswith("/v1") else endpoint
    home = Path("/workspace/home")
    config = Path("/workspace/claude-config")
    home.mkdir(parents=True, exist_ok=True)
    config.mkdir(parents=True, exist_ok=True)
    budgets = task.get("budgets") if isinstance(task.get("budgets"), dict) else {}
    env = dict(os.environ)
    env.update({
        "HOME": str(home), "CLAUDE_CONFIG_DIR": str(config),
        "ANTHROPIC_BASE_URL": base_url, "ANTHROPIC_API_KEY": token,
        "ANTHROPIC_MODEL": "glm-5.2", "ANTHROPIC_SMALL_FAST_MODEL": "glm-5.2",
        "API_TIMEOUT_MS": str(min(180000, max(1000, int(budgets.get("wallClockSeconds") or 180) * 1000))),
        "DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1", "CLAUDE_CODE_ENABLE_TELEMETRY": "0",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
    })
    command = [
        "/adapter/claude", "--print", "--bare", "--safe-mode", "--no-session-persistence",
        "--disable-slash-commands", "--no-chrome", "--prompt-suggestions", "false",
        "--output-format", "text", "--model", "glm-5.2", "--permission-mode", "bypassPermissions",
        "--dangerously-skip-permissions", str(task.get("prompt") or ""),
    ]
    completed = subprocess.run(command, cwd="/workspace", env=env, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.replace(token, "[redacted]")[-2000:]
        print(stderr or "Claude Code did not produce a final response.", file=sys.stderr)
        return completed.returncode
    answer = completed.stdout.strip()
    if not answer:
        print("Claude Code final response was empty.", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
