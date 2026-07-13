#!/usr/bin/env python3
"""Static contract checks for the genuine Claude Code safe-lab adapter."""

from __future__ import annotations

import json
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "claude-code-live-runner.py"


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    required = {
        "realBinary": '"/adapter/claude", "--print"',
        "bare": '"--bare"',
        "safeMode": '"--safe-mode"',
        "noPersistence": '"--no-session-persistence"',
        "externalSandbox": '"--dangerously-skip-permissions"',
        "messagesGateway": '"ANTHROPIC_BASE_URL": base_url',
        "brokerCredential": '"ANTHROPIC_API_KEY": token',
        "exactModel": '"--model", "glm-5.2"',
        "telemetryDisabled": '"DISABLE_TELEMETRY": "1"',
    }
    checks = {name: needle in source for name, needle in required.items()}
    errors = [f"runner contract missing: {name}" for name, passed in checks.items() if not passed]
    for forbidden in (".credentials.json", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN"):
        if forbidden in source:
            errors.append(f"runner references forbidden host auth surface: {forbidden}")
    result = {"schema": "wasm-agent.safe-lab.claude-code-adapter-check.v1", "ok": not errors, "checks": checks, "errors": errors}
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
