#!/usr/bin/env python3
"""Create an immutable semantic-adjudication overlay for selected SQL fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "wasm-agent.fixture-adjudication.v1"
SECRET_VALUE = re.compile(r"(?i)\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
RAW_REF = re.compile(r"(?i)\b(?:wa_run_[a-z0-9]{12,}|agent_[a-z0-9]{6,}_[a-z0-9]{4,})\b")

# This private manifest is deliberately excluded from every lane source snapshot.
# Expected properties are never copied into a fixture task or adapter container.
SEEDS = (
    {
        "fixtureId": "fx_d3154de08df6150be9c9",
        "objective": "hello",
        "split": "golden",
        "contract": {"nonempty": True, "maxChars": 800, "excludesAny": ["i changed", "i fixed", "completed the"]},
    },
    {
        "fixtureId": "fx_ecafab6d6b119728eb01",
        "objective": "hi",
        "split": "golden",
        "contract": {"nonempty": True, "maxChars": 800, "excludesAny": ["i changed", "i fixed", "completed the"]},
    },
    {
        "fixtureId": "fx_2a671dec0719bf4f68c0",
        "objective": "hello can you udnerstandme?",
        "split": "golden",
        "contract": {"nonempty": True, "maxChars": 1200, "containsAnyGroups": [["understand", "yes", "message", "read"]]},
    },
    {
        "fixtureId": "fx_d0771dc70e8bd1486915",
        "objective": "hello are you working?",
        "split": "golden",
        "contract": {"nonempty": True, "maxChars": 1200, "containsAnyGroups": [["working", "ready", "available", "online", "yes"]]},
    },
    {
        "fixtureId": "fx_6930a8be2704b71c12d3",
        "objective": "hello, which model are you?",
        "split": "golden",
        "contract": {"nonempty": True, "maxChars": 1200, "containsAnyGroups": [["glm-5.2"]]},
    },
    {
        "fixtureId": "fx_06036b8689b0ee5792bb",
        "objective": "hello how are you?",
        "split": "holdout",
        "contract": {"nonempty": True, "maxChars": 1200, "excludesAny": ["i changed", "i fixed", "completed the"]},
    },
    {
        "fixtureId": "fx_be4014b259289fe028fc",
        "objective": "what you mean by `capability_unavailable`?",
        "split": "holdout",
        "contract": {
            "nonempty": True,
            "maxChars": 1800,
            "containsAnyGroups": [
                ["unavailable", "not available", "missing", "lack", "cannot", "can't"],
                ["capability", "tool", "access", "permission", "authority"],
            ],
        },
    },
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def public_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:20]}"


def normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def clean_text(value: Any, limit: int = 65536) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    text = SECRET_VALUE.sub("[redacted-secret]", text)
    text = EMAIL.sub("[redacted-email]", text)
    text = RAW_REF.sub("[redacted-runtime-ref]", text)
    return text[:limit]


def parsed(value: str) -> Any:
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


def find_first(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if value.get(key) not in (None, "", [], {}):
            return value[key]
        for item in value.values():
            found = find_first(item, key)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_first(item, key)
            if found not in (None, "", [], {}):
                return found
    return None


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    PRAGMA journal_mode=DELETE;
    PRAGMA foreign_keys=ON;
    CREATE TABLE adjudication_meta (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
    CREATE TABLE fixture_adjudication (
      fixture_id TEXT PRIMARY KEY, source_run_ref TEXT NOT NULL,
      objective_sha256 TEXT NOT NULL, duplicate_group_sha256 TEXT NOT NULL UNIQUE,
      split TEXT NOT NULL CHECK(split IN ('golden','holdout')),
      decision TEXT NOT NULL CHECK(decision IN ('admit','reject','dispute','insufficient_context')),
      semantic_status TEXT NOT NULL, ranking_allowed INTEGER NOT NULL CHECK(ranking_allowed IN (0,1)),
      expected_contract_json TEXT NOT NULL, expected_contract_sha256 TEXT NOT NULL,
      historical_reply_sha256 TEXT NOT NULL, historical_reply_chars INTEGER NOT NULL,
      adjudicated_at TEXT NOT NULL
    );
    CREATE TABLE adjudication_record (
      fixture_id TEXT NOT NULL REFERENCES fixture_adjudication(fixture_id) ON DELETE CASCADE,
      judge_id TEXT NOT NULL, judge_role TEXT NOT NULL,
      independent_of_preliminary INTEGER NOT NULL CHECK(independent_of_preliminary IN (0,1)),
      decision TEXT NOT NULL, evidence_json TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
      PRIMARY KEY(fixture_id, judge_id)
    );
    """)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--bank", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.source).resolve()
    bank = Path(args.bank).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite adjudication overlay: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    fixtures = sqlite3.connect(f"file:{bank}?mode=ro", uri=True)
    fixtures.row_factory = sqlite3.Row
    source_by_ref = {
        public_id("run", str(row["run_id"])): row
        for row in src.execute("SELECT run_id,status,final_json FROM agent_run_tb WHERE kind='avatar-chat'")
    }
    dst = sqlite3.connect(output)
    create_schema(dst)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    for seed in SEEDS:
        row = fixtures.execute("SELECT * FROM fixture_candidate WHERE fixture_id=?", (seed["fixtureId"],)).fetchone()
        if row is None:
            raise RuntimeError(f"seed fixture missing: {seed['fixtureId']}")
        objective = normalized(str(row["objective_redacted"] or ""))
        if objective != normalized(str(seed["objective"])):
            raise RuntimeError(f"objective drift for {seed['fixtureId']}")
        warnings = json.loads(row["warning_classes_json"] or "[]")
        source_row = source_by_ref.get(str(row["source_run_ref"]))
        reply = clean_text(find_first(parsed(source_row["final_json"]), "reply") if source_row else "")
        evidence_ok = bool(
            source_row and source_row["status"] == "completed" and row["observed_status"] == "completed"
            and not warnings and row["final_reply_available"] and reply
        )
        self_contained = row["request_class"] in {"conversation", "general_question"}
        decision = "admit" if evidence_ok and self_contained else "insufficient_context"
        contract_json = canonical(seed["contract"])
        dst.execute(
            "INSERT INTO fixture_adjudication VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["fixture_id"], row["source_run_ref"], row["objective_sha256"],
                sha256_bytes(objective.encode()), seed["split"], decision,
                "contract_adjudicated" if decision == "admit" else "unresolved",
                int(decision == "admit"), contract_json, sha256_bytes(contract_json.encode()),
                sha256_bytes(reply.encode()) if reply else "", len(reply), now,
            ),
        )
        records = (
            (
                "source-evidence-v1", "eligibility",
                "admit" if evidence_ok else "insufficient_context",
                {"completed": bool(source_row and source_row["status"] == "completed"), "warningCount": len(warnings), "boundedReply": bool(reply)},
            ),
            (
                "semantic-contract-v1", "task-stability",
                "admit" if self_contained else "insufficient_context",
                {"selfContained": self_contained, "requestClass": row["request_class"], "contractSha256": sha256_bytes(contract_json.encode())},
            ),
        )
        for judge_id, role, judge_decision, evidence in records:
            evidence_json = canonical(evidence)
            dst.execute(
                "INSERT INTO adjudication_record VALUES (?,?,?,?,?,?,?)",
                (row["fixture_id"], judge_id, role, 1, judge_decision, evidence_json, sha256_bytes(evidence_json.encode())),
            )

    metadata = {
        "schema": SCHEMA,
        "generatedAt": now,
        "bankSha256": sha256_bytes(bank.read_bytes()),
        "sourceSha256": sha256_bytes(source.read_bytes()),
        "fixtureCount": len(SEEDS),
        "goldenCount": sum(seed["split"] == "golden" for seed in SEEDS),
        "holdoutCount": sum(seed["split"] == "holdout" for seed in SEEDS),
        "expectedContractsExposedToLane": False,
        "historicalRepliesStored": False,
        "sourceCandidateBankMutated": False,
    }
    for key, value in metadata.items():
        dst.execute("INSERT INTO adjudication_meta VALUES (?,?)", (key, json.dumps(value)))
    dst.commit()
    integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
    dst.close()
    fixtures.close()
    src.close()
    print(json.dumps({**metadata, "integrity": integrity, "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
