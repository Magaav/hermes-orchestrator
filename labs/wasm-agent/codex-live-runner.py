#!/usr/bin/env python3
"""Codex CLI adapter for the canonical safe-lab fixture task."""

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
    home = Path("/workspace/codex-home")
    home.mkdir(parents=True, exist_ok=True)
    final_path = Path("/workspace/codex-final.txt")
    provider = (
        '{ name="Safe-lab GLM", base_url="' + endpoint.replace('"', '')
        + '", env_key="OPENAI_API_KEY", wire_api="responses", request_max_retries=0, stream_max_retries=0 }'
    )
    env = dict(os.environ)
    env.update({"CODEX_HOME": str(home), "PATH": "/adapter/codex-path:" + env.get("PATH", "")})
    command = [
        "/adapter/codex", "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules",
        "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox", "--color", "never",
        "-C", "/workspace", "-m", "glm-5.2", "-c", 'model_provider="safe_lab"',
        "-c", f"model_providers.safe_lab={provider}", "-c", "model_context_window=131072",
        "-c", "model_supports_reasoning_summaries=false", "-o", str(final_path), str(task.get("prompt") or ""),
    ]
    completed = subprocess.run(command, cwd="/workspace", env=env, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not final_path.is_file():
        stderr = completed.stderr.replace(token, "[redacted]")[-2000:]
        print(stderr or "Codex did not produce a final message.", file=sys.stderr)
        return completed.returncode or 1
    answer = final_path.read_text(encoding="utf-8").strip()
    if not answer:
        print("Codex final message was empty.", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
