#!/usr/bin/env python3
"""Aider adapter for the canonical safe-lab fixture task."""

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
    home.mkdir(parents=True, exist_ok=True)
    config = home / "aider.conf.yml"
    env_file = home / "empty.env"
    config.write_text("{}\n", encoding="utf-8")
    env_file.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "OPENAI_API_BASE": endpoint,
        "OPENAI_API_KEY": token,
        "AIDER_ANALYTICS": "false",
        "AIDER_CHECK_UPDATE": "false",
        "AIDER_SHOW_RELEASE_NOTES": "false",
        "NO_COLOR": "1",
    })
    command = [
        "/adapter/venv/bin/aider",
        "--model", "openai/glm-5.2",
        "--openai-api-base", endpoint,
        "--message", str(task.get("prompt") or ""),
        "--yes-always",
        "--no-stream",
        "--no-pretty",
        "--no-fancy-input",
        "--no-git",
        "--no-gitignore",
        "--no-auto-commits",
        "--no-dirty-commits",
        "--no-restore-chat-history",
        "--no-suggest-shell-commands",
        "--disable-playwright",
        "--no-show-model-warnings",
        "--no-check-model-accepts-settings",
        "--no-analytics",
        "--no-check-update",
        "--no-show-release-notes",
        "--config", str(config),
        "--env-file", str(env_file),
        "--input-history-file", str(home / "input.history"),
        "--chat-history-file", str(home / "chat.history.md"),
        "--llm-history-file", str(home / "llm.history.md"),
    ]
    completed = subprocess.run(command, cwd="/workspace", env=env, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.replace(token, "[redacted]")[-2000:]
        print(stderr or "Aider did not produce a final response.", file=sys.stderr)
        return completed.returncode
    history = home / "chat.history.md"
    answer = ""
    if history.is_file():
        extractor = subprocess.run([
            "/adapter/venv/bin/python", "-c",
            "import pathlib,sys; from aider.utils import split_chat_history_markdown; "
            "messages=split_chat_history_markdown(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')); "
            "answers=[str(item.get('content') or '').strip() for item in messages if item.get('role')=='assistant']; "
            "print(answers[-1] if answers else '')",
            str(history),
        ], cwd="/workspace", env=env, capture_output=True, text=True, check=False)
        if extractor.returncode == 0:
            answer = extractor.stdout.strip()
    if not answer:
        print("Aider final assistant response was absent from its bounded chat history.", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
