#!/usr/bin/env python3
"""Validate immutable, redacted multi-turn session fixture contracts."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "wasm-agent.safe-lab.session-fixture-suite.v1"
TASK_SCHEMA = "wasm-agent.safe-lab.session-task.v1"
EVENT_KINDS = frozenset({
    "user", "assistant", "tool_call", "tool_result", "checkpoint",
    "interrupt", "restart", "compact", "fork",
})
REQUIRED_CASES = frozenset({
    "adjacent_followup", "process_restart", "context_compaction", "older_recall",
    "interruption_resume", "new_topic", "user_correction", "fix_all",
    "fix_second", "continue_interrupted", "no_repeat", "ambiguous_recall",
})
RAW_ID = re.compile(r"\b(?:wa_run_[a-z0-9]{12,}|agent_[a-z0-9]{6,}_[a-z0-9]{4,})\b", re.I)
SECRET = re.compile(r"(?i)\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b")


def canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def task_projection(fixture: dict[str, Any], suite: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": TASK_SCHEMA,
        "fixtureId": fixture["id"],
        "case": fixture["case"],
        "model": suite["model"],
        "routeContractSha256": suite["routeContractSha256"],
        "toolAuthoritySha256": suite["toolAuthoritySha256"],
        "session": fixture["session"],
        "events": fixture["events"],
        "expectations": fixture["expectations"],
        "budgets": suite["budgets"],
    }


def validate(suite: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if suite.get("schema") != SCHEMA: errors.append("suite schema mismatch")
    if suite.get("model") != "frank/GLM-5.2": errors.append("exact model mismatch")
    fixtures = suite.get("fixtures") if isinstance(suite.get("fixtures"), list) else []
    if {item.get("case") for item in fixtures if isinstance(item, dict)} != REQUIRED_CASES:
        errors.append("required twelve-case matrix mismatch")
    if len({item.get("id") for item in fixtures if isinstance(item, dict)}) != len(fixtures):
        errors.append("fixture ids are not unique")
    for fixture in fixtures:
        if not isinstance(fixture, dict): errors.append("fixture is not an object"); continue
        events = fixture.get("events") if isinstance(fixture.get("events"), list) else []
        sequence = [int(item.get("seq") or 0) for item in events if isinstance(item, dict)]
        if sequence != list(range(1, len(events) + 1)): errors.append(f"{fixture.get('id')}: event order invalid")
        if any(item.get("kind") not in EVENT_KINDS for item in events if isinstance(item, dict)):
            errors.append(f"{fixture.get('id')}: unsupported event kind")
        users = [item for item in events if isinstance(item, dict) and item.get("kind") == "user"]
        if len(users) < 2: errors.append(f"{fixture.get('id')}: fewer than two user turns")
        identities = fixture.get("session") if isinstance(fixture.get("session"), dict) else {}
        if not all(identities.get(key) for key in ("sessionRef", "initialProcessRef", "branchRef")):
            errors.append(f"{fixture.get('id')}: session identity incomplete")
        expectations = fixture.get("expectations") if isinstance(fixture.get("expectations"), dict) else {}
        if len(expectations.get("perTurn") or []) != len(users): errors.append(f"{fixture.get('id')}: per-turn expectation mismatch")
        if not expectations.get("terminal"): errors.append(f"{fixture.get('id')}: terminal expectation missing")
        expected = canonical_digest(task_projection(fixture, suite))
        if fixture.get("taskDigest") != expected: errors.append(f"{fixture.get('id')}: task digest mismatch")
    serialized = json.dumps(suite, sort_keys=True)
    if RAW_ID.search(serialized): errors.append("raw run/session identifier leaked")
    if SECRET.search(serialized): errors.append("secret-like value leaked")
    if suite.get("privateHoldoutExpectationsExposed") is not False: errors.append("private holdout policy is not fail-closed")
    return errors


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ValueError("suite must be an object")
    return value
