#!/usr/bin/env python3
"""Static contract checks for the genuine Gemini CLI safe-lab adapter."""

from __future__ import annotations

import json
from pathlib import Path


SOURCE = Path(__file__).resolve().parent / "gemini-cli-live-runner.py"


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    required = {
        "realCli": '"/adapter/lib/node_modules/@google/gemini-cli/bundle/gemini.js"',
        "headless": '"--prompt"',
        "exactModel": '"--model", "glm-5.2"',
        "structuredOutput": '"--output-format", "json"',
        "externalSandbox": '"--approval-mode", "yolo"',
        "ephemeralHome": '"HOME": str(home)',
        "ephemeralConfig": '"XDG_CONFIG_HOME": str(config)',
        "gateway": '"GOOGLE_GEMINI_BASE_URL": base_url',
        "brokerCredential": '"GEMINI_API_KEY": token',
        "ephemeralAuthSelection": '"selectedType": "gemini-api-key"',
        "telemetryDisabled": '"GEMINI_TELEMETRY_ENABLED": "false"',
    }
    checks = {name: needle in source for name, needle in required.items()}
    errors = [f"runner contract missing: {name}" for name, passed in checks.items() if not passed]
    for forbidden in ("/home/ubuntu/.gemini", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_API_KEY"):
        if forbidden in source:
            errors.append(f"runner references forbidden host auth surface: {forbidden}")
    result = {
        "schema": "wasm-agent.safe-lab.gemini-cli-adapter-check.v1",
        "ok": not errors,
        "checks": checks,
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
