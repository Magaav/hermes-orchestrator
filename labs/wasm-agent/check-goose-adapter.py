#!/usr/bin/env python3
"""Static contract checks for the genuine Goose safe-lab adapter."""
import json
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "goose-live-runner.py"

def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    required = {
        "realCli": '"/adapter/goose"', "exactModel": '"--model", "glm-5.2"',
        "brokerEndpoint": '"OPENAI_BASE_URL": endpoint', "brokerCredential": 'token = os.environ.get("OPENAI_API_KEY"',
        "noProfile": '"--no-profile"', "noSession": '"--no-session"',
        "nativeAnswerOutput": '"--output-format", "text"', "quiet": '"--quiet"',
        "ephemeralState": '"GOOSE_PATH_ROOT": str(state)',
        "noNamingCall": '"GOOSE_DISABLE_SESSION_NAMING": "true"',
        "noSummaryCall": '"GOOSE_DISABLE_TOOL_CALL_SUMMARY": "true"',
    }
    checks = {name: needle in source for name, needle in required.items()}
    errors = [f"runner contract missing: {name}" for name, ok in checks.items() if not ok]
    for forbidden in ("/home/ubuntu/.config/goose", "GOOSE_API_KEY", "OPENAI_HOST"):
        if forbidden in source: errors.append(f"runner references forbidden state: {forbidden}")
    result = {"schema":"wasm-agent.safe-lab.goose-adapter-check.v1","ok":not errors,"checks":checks,"errors":errors}
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1

if __name__ == "__main__": raise SystemExit(main())
