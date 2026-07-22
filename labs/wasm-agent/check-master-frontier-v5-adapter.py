#!/usr/bin/env python3
"""Static behavioral checks for the Master:frontier V5 safe-lab adapter."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
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
    for required in ('"model": "glm-5.2"', 'FRONTIER_MODEL") != "frank/GLM-5.2"', "context.completion_only(state, route)"):
        if required not in source:
            errors.append(f"runner contract missing: {required}")
    packager = (LAB / "package-master-frontier-v5-adapter.py").read_text(encoding="utf-8")
    if "def preflight_import(volume:" not in packager or "preflight_import(volume)" not in packager:
        errors.append("package import preflight is missing")
    package_spec = importlib.util.spec_from_file_location("master_frontier_v5_packager", LAB / "package-master-frontier-v5-adapter.py")
    assert package_spec and package_spec.loader
    package_module = importlib.util.module_from_spec(package_spec); package_spec.loader.exec_module(package_module)
    with tempfile.TemporaryDirectory(prefix="mf5-adapter-closure-") as raw_temp:
        root = Path(raw_temp)
        for source_path, relative_path in package_module.source_files():
            target = root / relative_path; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target)
        imported = subprocess.run([
            sys.executable, "-I", "-c",
            f"import sys;sys.path.insert(0,{str(root / 'plugins/wasm-agent/server')!r});"
            "from master_frontier import controller_v5;from master_frontier.v5 import loop,trajectory",
        ], capture_output=True, text=True, check=False)
    if imported.returncode != 0:
        errors.append("packaged import closure failed: " + imported.stderr.strip()[:400])
    result = {
        "schema": "wasm-agent.safe-lab.master-frontier-v5-adapter-check.v1",
        "ok": not errors,
        "checks": {
            "plainAnswerAndUsage": final["reply"] == "Hello",
            "nativeToolCall": bool(native["tool_calls"]),
            "sourceReadOnlyRoute": route["allowed_read_roots"] == ["/source"],
            "workspaceAuthorityDeclared": route["allowed_write_roots"] == ["/workspace"],
            "exactModelPinned": '"model": "glm-5.2"' in source,
            "packageImportPreflight": "def preflight_import(volume:" in packager,
            "packageImportClosure": imported.returncode == 0,
        },
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
