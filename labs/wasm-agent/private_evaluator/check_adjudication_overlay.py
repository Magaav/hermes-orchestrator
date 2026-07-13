#!/usr/bin/env python3
"""Validate semantic overlay provenance, privacy, independence, and splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path

RAW_ID = re.compile(r"\b(?:wa_run_[a-z0-9]{12,}|agent_[a-z0-9]{6,}_[a-z0-9]{4,})\b", re.I)
SECRET = re.compile(r"(?i)\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("overlay")
    parser.add_argument("--bank", required=True)
    parser.add_argument("--report")
    args = parser.parse_args()
    overlay = Path(args.overlay).resolve()
    bank = Path(args.bank).resolve()
    conn = sqlite3.connect(f"file:{overlay}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    source = sqlite3.connect(f"file:{bank}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    errors: list[str] = []
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        errors.append(f"integrity_check={integrity}")
    metadata = {key: json.loads(value) for key, value in conn.execute("SELECT key,value_json FROM adjudication_meta")}
    rows = conn.execute("SELECT * FROM fixture_adjudication ORDER BY fixture_id").fetchall()
    if metadata.get("schema") != "wasm-agent.fixture-adjudication.v1":
        errors.append("overlay schema mismatch")
    if metadata.get("bankSha256") != digest(bank):
        errors.append("source bank digest mismatch")
    if len(rows) != 7 or metadata.get("fixtureCount") != 7:
        errors.append("expected seven independently adjudicated fixtures")
    if sum(row["split"] == "golden" for row in rows) != 5 or sum(row["split"] == "holdout" for row in rows) != 2:
        errors.append("expected five golden and two holdout fixtures")
    if len({row["duplicate_group_sha256"] for row in rows}) != len(rows):
        errors.append("duplicate objective group entered the semantic slice")
    allowed_keys = {"nonempty", "maxChars", "containsAnyGroups", "excludesAny"}
    for row in rows:
        candidate = source.execute("SELECT * FROM fixture_candidate WHERE fixture_id=?", (row["fixture_id"],)).fetchone()
        if candidate is None:
            errors.append(f"missing candidate: {row['fixture_id']}")
            continue
        if candidate["adjudication_status"] != "pending":
            errors.append(f"source bank was mutated: {row['fixture_id']}")
        contract = json.loads(row["expected_contract_json"])
        canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(canonical.encode()).hexdigest() != row["expected_contract_sha256"]:
            errors.append(f"contract digest mismatch: {row['fixture_id']}")
        if not set(contract).issubset(allowed_keys):
            errors.append(f"unsupported contract operator: {row['fixture_id']}")
        records = conn.execute("SELECT * FROM adjudication_record WHERE fixture_id=?", (row["fixture_id"],)).fetchall()
        if len(records) != 2 or len({item["judge_role"] for item in records}) != 2:
            errors.append(f"independent judge coverage missing: {row['fixture_id']}")
        if any(item["independent_of_preliminary"] != 1 or item["decision"] != "admit" for item in records):
            errors.append(f"judge disagreement or classifier coupling: {row['fixture_id']}")
        if row["decision"] != "admit" or row["semantic_status"] != "contract_adjudicated" or row["ranking_allowed"] != 1:
            errors.append(f"fixture is not admitted: {row['fixture_id']}")
    serialized = "\n".join(str(value) for row in rows for value in row if isinstance(value, str))
    if RAW_ID.search(serialized):
        errors.append("raw runtime identifier leaked")
    if SECRET.search(serialized):
        errors.append("secret-like token leaked")
    if metadata.get("expectedContractsExposedToLane") is not False or metadata.get("historicalRepliesStored") is not False:
        errors.append("privacy metadata is not fail-closed")
    counts = {
        "fixtures": len(rows),
        "golden": sum(row["split"] == "golden" for row in rows),
        "holdout": sum(row["split"] == "holdout" for row in rows),
        "judgeRecords": conn.execute("SELECT COUNT(*) FROM adjudication_record").fetchone()[0],
        "sourcePending": source.execute("SELECT COUNT(*) FROM fixture_candidate WHERE adjudication_status='pending'").fetchone()[0],
    }
    result = {
        "schema": "wasm-agent.fixture-adjudication-proof.v1",
        "ok": not errors,
        "overlaySha256": digest(overlay),
        "bankSha256": digest(bank),
        "integrity": integrity,
        "counts": counts,
        "expectedPropertiesExposedToAdapters": False,
        "sourceCandidateBankMutated": False,
        "errors": errors,
    }
    if args.report:
        report = Path(args.report)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    conn.close()
    source.close()
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
