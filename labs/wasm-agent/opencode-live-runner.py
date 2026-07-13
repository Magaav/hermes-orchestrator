#!/usr/bin/env python3
"""OpenCode adapter for the canonical safe-lab fixture task."""

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
    home = Path("/workspace/home")
    for path in (home, home / "config", home / "data", home / "cache"):
        path.mkdir(parents=True, exist_ok=True)
    maximum = int((task.get("budgets") or {}).get("maxOutputTokensPerCall") or 1024)
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": "lab/glm-5.2",
        "small_model": "lab/glm-5.2",
        "share": "disabled",
        "autoupdate": False,
        "provider": {
            "lab": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "WASM Agent Safe Lab",
                "options": {"baseURL": endpoint, "apiKey": "{env:OPENAI_API_KEY}"},
                "models": {"glm-5.2": {"name": "GLM-5.2", "limit": {"context": 131072, "output": maximum}}},
            }
        },
        "tools": {"webfetch": False, "websearch": False, "codesearch": False},
    }
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_DATA_HOME": str(home / "data"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "OPENCODE_CONFIG_DIR": str(home / "config"),
        "OPENCODE_CONFIG_CONTENT": json.dumps(config, separators=(",", ":")),
        "OPENCODE_DISABLE_AUTOUPDATE": "true",
        "OPENCODE_DISABLE_PRUNE": "true",
        "OPENCODE_DISABLE_TERMINAL_TITLE": "true",
        "OPENCODE_DISABLE_DEFAULT_PLUGINS": "true",
        "OPENCODE_DISABLE_LSP_DOWNLOAD": "true",
        "OPENCODE_DISABLE_CLAUDE_CODE": "true",
        "OPENCODE_DISABLE_MODELS_FETCH": "true",
        "OPENCODE_ENABLE_EXA": "false",
        "OPENCODE_AUTO_SHARE": "false",
        "NO_COLOR": "1",
    })
    command = [
        "/adapter/lib/node_modules/opencode-linux-arm64/bin/opencode",
        "--pure", "run", "--model", "lab/glm-5.2", "--format", "json",
        "--auto", "--dir", "/workspace", str(task.get("prompt") or ""),
    ]
    completed = subprocess.run(command, cwd="/workspace", env=env, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.replace(token, "[redacted]")[-2000:]
        print(stderr or "OpenCode did not produce a final response.", file=sys.stderr)
        return completed.returncode
    answers: list[str] = []
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = event.get("part") if isinstance(event, dict) and isinstance(event.get("part"), dict) else {}
        if event.get("type") == "text" and part.get("type") == "text" and part.get("text"):
            answers.append(str(part["text"]).strip())
    answer = answers[-1] if answers else ""
    if not answer:
        print("OpenCode final text event was absent from structured output.", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
