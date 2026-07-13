#!/usr/bin/env python3
"""Static behavioral checks for the Master:frontier V5 safe-lab adapter."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

LAB = Path(__file__).resolve().parent
RUNNER = LAB / "master-frontier-v5-live-runner.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("master_frontier_v5_live_runner", RUNNER)
    if spec is None or spec.loader is None:
        raise SystemExit("runner import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    errors: list[str] = []
    final = module.provider_result({
        "choices": [{"message": {"content": "Hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    })
    if final["reply"] != "Hello" or final["usage"].get("total_tokens") != 12:
        errors.append("plain answer or exact usage projection failed")
    native = module.provider_result({"choices": [{"message": {"content": None, "tool_calls": [{
        "id": "c1", "type": "function", "function": {"name": "read", "arguments": '{"path":"x.py"}'},
    }]}}]})
    if native["tool_calls"] != [{"id": "c1", "name": "read", "arguments": {"path": "x.py"}}]:
        errors.append("native tool-call projection failed")
    route = module.route_contract({"taskDigest": "a" * 64})
    if route["workspace_root"] != "/source" or route["allowed_read_roots"] != ["/source"] or route["allowed_write_roots"] != ["/workspace"]:
        errors.append("route authority projection failed")
    source = RUNNER.read_text(encoding="utf-8")
    for required in ('"model": "glm-5.2"', 'FRONTIER_MODEL") != "frank/GLM-5.2"', "context.completion_only(state)"):
        if required not in source:
            errors.append(f"runner contract missing: {required}")
    packager = (LAB / "package-master-frontier-v5-adapter.py").read_text(encoding="utf-8")
    if "def preflight_import()" not in packager or "preflight_import()" not in packager:
        errors.append("package import preflight is missing")
    result = {
        "schema": "wasm-agent.safe-lab.master-frontier-v5-adapter-check.v1",
        "ok": not errors,
        "checks": {
            "plainAnswerAndUsage": final["reply"] == "Hello",
            "nativeToolCall": bool(native["tool_calls"]),
            "sourceReadOnlyRoute": route["allowed_read_roots"] == ["/source"],
            "workspaceAuthorityDeclared": route["allowed_write_roots"] == ["/workspace"],
            "exactModelPinned": '"model": "glm-5.2"' in source,
            "packageImportPreflight": "def preflight_import()" in packager,
        },
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
