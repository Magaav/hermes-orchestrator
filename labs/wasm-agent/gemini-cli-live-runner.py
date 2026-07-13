#!/usr/bin/env python3
"""Gemini CLI adapter for the canonical safe-lab fixture task."""

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
    config = Path("/workspace/config")
    home.mkdir(parents=True, exist_ok=True)
    config.mkdir(parents=True, exist_ok=True)
    gemini_config = home / ".gemini"
    gemini_config.mkdir(parents=True, exist_ok=True)
    (gemini_config / "settings.json").write_text(json.dumps({
        "security": {"auth": {"selectedType": "gemini-api-key"}},
        "telemetry": {"enabled": False},
        "privacy": {"usageStatisticsEnabled": False},
        "general": {"disableAutoUpdate": True},
    }, separators=(",", ":")) + "\n", encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(config),
        "GEMINI_API_KEY": token,
        "GOOGLE_GEMINI_BASE_URL": base_url,
        "GOOGLE_GENAI_API_VERSION": "v1beta",
        "GEMINI_MODEL": "glm-5.2",
        "GEMINI_CLI_TRUST_WORKSPACE": "true",
        "GEMINI_TELEMETRY_ENABLED": "false",
        "GEMINI_TELEMETRY_TRACES_ENABLED": "false",
        "NO_COLOR": "1",
    })
    command = [
        "/adapter/node",
        "/adapter/lib/node_modules/@google/gemini-cli/bundle/gemini.js",
        "--prompt", str(task.get("prompt") or ""),
        "--model", "glm-5.2",
        "--skip-trust",
        "--approval-mode", "yolo",
        "--output-format", "json",
    ]
    completed = subprocess.run(command, cwd="/workspace", env=env, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.replace(token, "[redacted]")[-2000:]
        print(stderr or "Gemini CLI did not produce a final response.", file=sys.stderr)
        return completed.returncode
    try:
        payload = json.loads(completed.stdout)
        answer = str(payload.get("response") or "").strip()
    except (json.JSONDecodeError, AttributeError):
        print("Gemini CLI returned invalid structured output.", file=sys.stderr)
        return 1
    if not answer:
        print("Gemini CLI final response was empty.", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
