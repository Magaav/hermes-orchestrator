#!/usr/bin/env python3
"""Static contract checks for the genuine OpenCode safe-lab adapter."""

from __future__ import annotations

import json
from pathlib import Path


SOURCE = Path(__file__).resolve().parent / "opencode-live-runner.py"


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    required = {
        "realCli": '"/adapter/lib/node_modules/opencode-linux-arm64/bin/opencode"',
        "headless": '"--pure", "run"',
        "exactModel": '"--model", "lab/glm-5.2"',
        "chatProvider": '"npm": "@ai-sdk/openai-compatible"',
        "gateway": '"baseURL": endpoint',
        "brokerCredential": '"apiKey": "{env:OPENAI_API_KEY}"',
        "structuredOutput": '"--format", "json"',
        "answerShaping": 'event.get("type") == "text"',
        "ephemeralState": '"XDG_DATA_HOME": str(home / "data")',
        "pure": '"--pure"',
        "noPlugins": '"OPENCODE_DISABLE_DEFAULT_PLUGINS": "true"',
        "noModelsFetch": '"OPENCODE_DISABLE_MODELS_FETCH": "true"',
        "noClaudeState": '"OPENCODE_DISABLE_CLAUDE_CODE": "true"',
        "noLspDownload": '"OPENCODE_DISABLE_LSP_DOWNLOAD": "true"',
        "noShare": '"OPENCODE_AUTO_SHARE": "false"',
    }
    checks = {name: needle in source for name, needle in required.items()}
    errors = [f"runner contract missing: {name}" for name, passed in checks.items() if not passed]
    for forbidden in ("/home/ubuntu/.local/share/opencode", "auth.json", "OPENCODE_SERVER_PASSWORD"):
        if forbidden in source:
            errors.append(f"runner references forbidden host state: {forbidden}")
    result = {"schema": "wasm-agent.safe-lab.opencode-adapter-check.v1", "ok": not errors, "checks": checks, "errors": errors}
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
