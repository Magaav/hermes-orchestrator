#!/usr/bin/env python3
"""Deterministic adapter fixture for the optional learning-event channel."""

from __future__ import annotations

import json
import os
from pathlib import Path


EVENT_PATH_ENV = "WASM_AGENT_EVENTS_PATH"


def main() -> int:
    destination = Path(os.environ[EVENT_PATH_ENV])
    destination.parent.mkdir(parents=True, exist_ok=True)
    events = [
        {
            "kind": "search",
            "status": "completed",
            "actionId": "fixture-search-1",
            "tool": "rg",
            "path": "/source/pkg/owner.py",
            "arguments": {"query": "needle-sk_test_1234567890123456"},
            "summary": (
                "Located the owner for fixture.person@example.com with "
                "Bearer fixture-token-1234567890. " + ("bounded " * 100)
            ),
            "durationMs": 3,
        },
        {
            "kind": "read",
            "status": "completed",
            "actionId": "fixture-read-1",
            "tool": "read_file",
            "path": "/source/pkg/owner.py",
            "arguments": {"start": 1, "end": 40},
            "resultDigest": "1" * 64,
            "bytes": 640,
        },
        {
            "kind": "edit",
            "status": "passed",
            "actionId": "fixture-edit-1",
            "tool": "apply_patch",
            "path": "/workspace/pkg/owner.py",
            "arguments": {"patch": "password=fixture-private-value"},
            "receiptRef": "receipt:fixture-edit-1",
            "changedFiles": ["pkg/owner.py"],
        },
        {
            "kind": "command",
            "status": "completed",
            "actionId": "fixture-command-1",
            "tool": "shell",
            "arguments": ["python3", "-m", "compileall", "pkg"],
            "summary": "command completed; authorization=fixture-private-token",
            "returncode": 0,
        },
        {
            "kind": "test",
            "status": "passed",
            "actionId": "fixture-test-1",
            "tool": "unittest",
            "receiptRef": "proof:fixture-tests",
            "durationMs": 8,
        },
        {
            "kind": "diff",
            "status": "completed",
            "actionId": "fixture-diff-1",
            "tool": "git_diff",
            "changedFiles": ["pkg/owner.py"],
            "resultDigest": "2" * 64,
        },
        {
            "kind": "proof",
            "status": "passed",
            "actionId": "fixture-proof-1",
            "proofRef": "proof:fixture-current-revision",
            "providerCalls": 1,
            "toolCallCount": 6,
        },
    ]
    destination.write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
