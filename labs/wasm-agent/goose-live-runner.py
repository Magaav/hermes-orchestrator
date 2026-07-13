#!/usr/bin/env python3
"""Goose adapter for the canonical safe-lab fixture task."""

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
    home = Path("/workspace/goose-home")
    state = Path("/workspace/goose-state")
    home.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    turns = int((task.get("budgets") or {}).get("maxToolIterations") or 1)
    env = dict(os.environ)
    env.update({
        "HOME": str(home), "GOOSE_PATH_ROOT": str(state),
        "GOOSE_PROVIDER": "openai", "GOOSE_MODEL": "glm-5.2",
        "OPENAI_BASE_URL": endpoint, "GOOSE_MAX_TURNS": str(turns),
        "GOOSE_DISABLE_SESSION_NAMING": "true",
        "GOOSE_DISABLE_TOOL_CALL_SUMMARY": "true",
        "GOOSE_DISABLE_KEYRING": "1", "NO_COLOR": "1",
    })
    command = [
        "/adapter/goose", "run", "--provider", "openai", "--model", "glm-5.2",
        "--no-profile", "--no-session", "--quiet", "--output-format", "text",
        "--text", str(task.get("prompt") or ""),
    ]
    completed = subprocess.run(command, cwd="/workspace", env=env, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        print((completed.stderr or "Goose did not produce a final response.").replace(token, "[redacted]")[-2000:], file=sys.stderr)
        return completed.returncode
    answer = completed.stdout.strip()
    if not answer:
        print("Goose final text was absent from quiet output.", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
