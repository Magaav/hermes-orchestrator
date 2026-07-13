#!/usr/bin/env python3
"""Hermes adapter mapping for the canonical safe-lab fixture task."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    task = json.loads(Path(args.task).read_text(encoding="utf-8"))
    endpoint = os.environ.get("FRONTIER_ENDPOINT", "").strip().rstrip("/")
    if task.get("schema") != "wasm-agent.safe-lab.fixture-task.v1" or not endpoint:
        raise SystemExit("invalid task or missing broker endpoint")
    if os.environ.get("FRONTIER_MODEL") != "frank/GLM-5.2":
        raise SystemExit("exact model contract missing")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("run-scoped broker token missing")
    maximum = int((task.get("budgets") or {}).get("maxOutputTokensPerCall") or 1024)
    max_turns = min(32, max(1, int((task.get("budgets") or {}).get("maxToolIterations") or 4)))
    home = Path("/workspace/home")
    hermes_home = home / ".hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    config = (
        "model:\n  default: glm-5.2\n  provider: custom:lab\n  context_length: 131072\n"
        f"agent:\n  max_turns: {max_turns}\n"
        "custom_providers:\n  - name: lab\n"
        f"    base_url: {endpoint}\n"
        "    key_env: OPENAI_API_KEY\n    api_mode: chat_completions\n"
        f"    max_output_tokens: {maximum}\n"
    )
    (hermes_home / "config.yaml").write_text(config, encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "HERMES_HOME": str(hermes_home),
        "HERMES_INFERENCE_PROVIDER": "custom:lab",
        "HERMES_INFERENCE_MODEL": "glm-5.2",
        "HERMES_MAX_ITERATIONS": str(max_turns),
        "PYTHONPATH": "/adapter/src",
    })
    completed = subprocess.run([
        "/adapter/venv/bin/python", "-m", "hermes_cli.main", "--safe-mode", "--ignore-rules",
        "-t", "terminal", "-m", "glm-5.2", "--provider", "custom:lab", "-z", str(task["prompt"]),
    ], cwd="/workspace", env=env, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
