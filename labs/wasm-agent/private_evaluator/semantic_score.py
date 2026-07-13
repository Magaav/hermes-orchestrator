#!/usr/bin/env python3
"""Trusted host-only scorer for an answer and a private semantic contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def score_answer(overlay: Path, fixture_id: str, answer: str) -> dict:
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
    for index, group in enumerate(contract.get("containsAnyGroups") or []):
        record(f"containsAnyGroup:{index}", any(str(term).casefold() in folded for term in group))
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
