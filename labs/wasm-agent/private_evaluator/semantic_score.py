#!/usr/bin/env python3
"""Trusted host-only scorer for an answer and a private semantic contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import re
from pathlib import Path


def _model_aliases(value: str) -> set[str]:
    raw = str(value or "").casefold().strip()
    terminal = raw.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    return {
        item for candidate in {raw, terminal}
        for item in {candidate, candidate.replace("-", " "), re.sub(r"[^a-z0-9]", "", candidate)}
        if item
    }


def _contains_identity(answer: str, aliases: set[str]) -> bool:
    folded = answer.casefold()
    compact = re.sub(r"[^a-z0-9]", "", folded)
    return any(alias in folded or re.sub(r"[^a-z0-9]", "", alias) in compact for alias in aliases)


def score_answer(
    overlay: Path,
    fixture_id: str,
    answer: str,
    *,
    baseline_model: str = "",
    runtime_model: str = "",
) -> dict:
    conn = sqlite3.connect(f"file:{overlay.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM fixture_adjudication WHERE fixture_id=?", (fixture_id,)).fetchone()
    conn.close()
    if row is None:
        raise RuntimeError("fixture is not present in private adjudication overlay")
    contract = json.loads(row["expected_contract_json"])
    folded = answer.casefold().strip()
    checks: list[dict] = []

    def record(name: str, passed: bool) -> None:
        checks.append({"property": name, "passed": bool(passed)})

    if contract.get("nonempty"):
        record("nonempty", bool(folded))
    if "maxChars" in contract:
        record("maxChars", len(answer) <= int(contract["maxChars"]))
    baseline_aliases = _model_aliases(baseline_model)
    runtime_aliases = _model_aliases(runtime_model)
    runtime_bound = False
    for index, group in enumerate(contract.get("containsAnyGroups") or []):
        expected = {str(term).casefold().strip() for term in group if str(term).strip()}
        if baseline_aliases and runtime_aliases and expected & baseline_aliases:
            runtime_bound = True
            record(f"runtimeModelIdentity:{index}", _contains_identity(answer, runtime_aliases))
        else:
            record(f"containsAnyGroup:{index}", any(term in folded for term in expected))
    if contract.get("excludesAny"):
        record("excludesAny", not any(str(term).casefold() in folded for term in contract["excludesAny"]))
    passed = bool(checks) and all(item["passed"] for item in checks)
    return {
        "schema": "wasm-agent.semantic-score.v1",
        "fixtureId": fixture_id,
        "split": row["split"],
        "contractSha256": row["expected_contract_sha256"],
        "answerSha256": hashlib.sha256(answer.encode()).hexdigest(),
        "answerChars": len(answer),
        "passed": passed,
        "checks": checks,
        "runtimeModelBound": runtime_bound,
        "expectedPropertiesExposedToAdapter": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay", required=True)
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--answer", required=True)
    args = parser.parse_args()
    result = score_answer(Path(args.overlay), args.fixture_id, Path(args.answer).read_text(encoding="utf-8"))
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
