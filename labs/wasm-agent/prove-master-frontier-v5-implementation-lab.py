#!/usr/bin/env python3
"""Deterministically prove the isolated MF5 implementation action surface."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = Path(__file__).resolve().parent
SERVER = ROOT / "plugins" / "wasm-agent" / "server"
sys.path.insert(0, str(SERVER)); sys.path.insert(0, str(LAB))

from implementation_lab_actions import ImplementationLabActions  # noqa: E402
from master_frontier import repository_state  # noqa: E402
from master_frontier.v5 import operation_ledger, tools  # noqa: E402


def _load_materializer():
    path = LAB / "materialize-implementation-task.py"
    spec = importlib.util.spec_from_file_location("implementation_materializer", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    failures: list[str] = []
    events: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="mf5-implementation-lab-") as raw:
        workspace = Path(raw) / "repo"
        task = _load_materializer().materialize("retry-window-v1", workspace)
        route = task["route"]
        adapter = ImplementationLabActions(route)
        tests_sha = _sha(workspace / "tests/test_retry_window.py")
        baseline = adapter.invoke("kernel.act", {"local_action": "test.run_focused", "args": {"check_id": "retry-window"}})
        if baseline.get("status") != "failed": failures.append("defective baseline did not fail")

        read = tools.execute("read", {"path": "retry_window.py"}, route, invoke=adapter.invoke)
        events.append({"tool": "read", "ok": read.get("ok")})
        expected = str(read.get("sha256") or "")
        edit = tools.execute("edit", {"operations": [{
            "op": "replace", "path": "retry_window.py", "expected_sha256": expected,
            "find": "if event >= cutoff", "replace": "if event > cutoff",
        }]}, route, invoke=adapter.invoke)
        events.append({"tool": "edit", "ok": edit.get("ok")})
        ledger = operation_ledger.record({}, "edit", edit, action_id="fixture-edit")
        verification = repository_state.verify(route, ledger.get("postimages") or {})
        worktree = str(verification.get("digest") or "")
        if verification.get("ok") is not True: failures.append("postimage verification failed")

        for name, arguments in (("test", {"check_id": "retry-window"}), ("diff", {}), ("prove", {})):
            observed = tools.execute(name, arguments, route, invoke=adapter.invoke)
            observed["worktree_sha256"] = worktree
            ledger = operation_ledger.record(ledger, name, observed, action_id=f"fixture-{name}")
            events.append({"tool": name, "ok": observed.get("ok")})
        gaps = operation_ledger.missing(ledger, worktree=worktree)
        if gaps: failures.append("workflow gaps: " + ",".join(gaps))
        if _sha(workspace / "tests/test_retry_window.py") != tests_sha: failures.append("fixture tests changed")
        if [item["tool"] for item in events] != ["read", "edit", "test", "diff", "prove"]:
            failures.append("workflow event order changed")
        if not all(item["ok"] for item in events): failures.append("one or more workflow actions failed")

        # Private behavioral edge checks, independent of the fixture's visible tests.
        sys.path.insert(0, str(workspace))
        try:
            from retry_window import RetryWindow  # type: ignore  # noqa: PLC0415
            edge = RetryWindow(2, 10)
            hidden_ok = edge.allow(-5) and edge.allow(0) and edge.allow(5) and not edge.allow(5.001)
        finally:
            sys.path.pop(0)
        if not hidden_ok: failures.append("private boundary behavior failed")
        result = {
            "schema": "wasm-agent.safe-lab.implementation-proof.v1", "ok": not failures,
            "fixture": "retry-window-v1", "taskDigest": task["taskDigest"],
            "baselineFailed": baseline.get("status") == "failed", "events": events,
            "changedFiles": ledger.get("changed_files"), "revision": ledger.get("revision"),
            "proofGaps": gaps, "testsImmutable": _sha(workspace / "tests/test_retry_window.py") == tests_sha,
            "privateBehaviorPassed": hidden_ok, "failures": failures,
        }
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
