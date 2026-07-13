#!/usr/bin/env python3
"""Static contract checks for the real Codex CLI safe-lab adapter."""

from __future__ import annotations

import json
from pathlib import Path

LAB = Path(__file__).resolve().parent
RUNNER = LAB / "codex-live-runner.py"


def main() -> int:
    source = RUNNER.read_text(encoding="utf-8")
    errors = []
    required = {
        "realCodexBinary": '"/adapter/codex", "exec"',
        "ephemeral": '"--ephemeral"',
        "externalSandbox": '"--dangerously-bypass-approvals-and-sandbox"',
        "ignoreHostConfig": '"--ignore-user-config"',
        "responsesProvider": 'wire_api="responses"',
        "exactModel": '"-m", "glm-5.2"',
        "brokerCredential": 'env_key="OPENAI_API_KEY"',
        "finalMessageFile": '"-o", str(final_path)',
    }
    checks = {}
    for name, needle in required.items():
        checks[name] = needle in source
        if not checks[name]:
            errors.append(f"runner contract missing: {name}")
    if "auth.json" in source or ".codex/config.toml" in source:
        errors.append("runner references host Codex auth or config")
    result = {"schema": "wasm-agent.safe-lab.codex-adapter-check.v1", "ok": not errors, "checks": checks, "errors": errors}
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
