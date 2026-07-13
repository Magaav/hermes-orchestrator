#!/usr/bin/env python3
"""Static contract checks for the genuine Aider safe-lab adapter."""

from __future__ import annotations

import json
from pathlib import Path


SOURCE = Path(__file__).resolve().parent / "aider-live-runner.py"


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    required = {
        "realCli": '"/adapter/venv/bin/aider"',
        "headless": '"--message"',
        "exactModel": '"--model", "openai/glm-5.2"',
        "gateway": '"--openai-api-base", endpoint',
        "brokerCredential": '"OPENAI_API_KEY": token',
        "ephemeralHome": '"HOME": str(home)',
        "noGit": '"--no-git"',
        "noCommits": '"--no-auto-commits"',
        "noAnalytics": '"--no-analytics"',
        "noUpdates": '"--no-check-update"',
        "noBrowser": '"--disable-playwright"',
        "nonInteractive": '"--yes-always"',
        "answerShaping": "split_chat_history_markdown",
    }
    checks = {name: needle in source for name, needle in required.items()}
    errors = [f"runner contract missing: {name}" for name, passed in checks.items() if not passed]
    for forbidden in ("/home/ubuntu/.aider", "ANTHROPIC_API_KEY", "OPENAI_ORGANIZATION"):
        if forbidden in source:
            errors.append(f"runner references forbidden host auth surface: {forbidden}")
    result = {"schema": "wasm-agent.safe-lab.aider-adapter-check.v1", "ok": not errors, "checks": checks, "errors": errors}
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
