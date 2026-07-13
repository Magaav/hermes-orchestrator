#!/usr/bin/env python3
"""Validate fixture-bank coverage, privacy, structure, and replay projections."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

RAW_ID = re.compile(r"\b(?:wa_run_[a-z0-9]{12,}|agent_[a-z0-9]{6,}_[a-z0-9]{4,})\b", re.I)
SECRET = re.compile(r"(?i)\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bank")
    parser.add_argument("--expected-runs", type=int, required=True)
    args = parser.parse_args()
    path = Path(args.bank)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    errors: list[str] = []
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        errors.append(f"integrity_check={integrity}")
    fixtures = conn.execute("SELECT * FROM fixture_candidate ORDER BY created_at_ms, fixture_id").fetchall()
    columns = [item[0] for item in conn.execute("SELECT * FROM fixture_candidate LIMIT 0").description]
    rows = [dict(zip(columns, fixture)) for fixture in fixtures]
    if len(rows) != args.expected_runs:
        errors.append(f"expected {args.expected_runs} fixtures, found {len(rows)}")
    if len({row["fixture_id"] for row in rows}) != len(rows):
        errors.append("fixture ids are not unique")
    if len({row["source_run_ref"] for row in rows}) != len(rows):
        errors.append("source run references are not unique")
    allowed_status = {"completed", "failed", "interrupted"}
    if any(row["observed_status"] not in allowed_status for row in rows):
        errors.append("unknown observed status")
    if any(row["adjudication_status"] != "pending" for row in rows):
        errors.append("generated candidates must start pending adjudication")
    projection_text = "\n".join(
        str(value) for row in rows for value in row.values() if isinstance(value, str)
    )
    projection_text += "\n" + "\n".join(
        value for (value,) in conn.execute("SELECT summary_redacted || payload_projection_json FROM fixture_event")
    )
    if RAW_ID.search(projection_text):
        errors.append("raw run/session identifier leaked")
    if SECRET.search(projection_text):
        errors.append("secret-like token leaked")
    metadata = {key: json.loads(value) for key, value in conn.execute("SELECT key,value_json FROM bank_meta")}
    if metadata.get("runCount") != args.expected_runs:
        errors.append("metadata runCount mismatch")
    if metadata.get("rawIdentifiersStored") is not False or metadata.get("rawPayloadsStored") is not False:
        errors.append("metadata does not assert compact redacted storage")
    event_orphans = conn.execute("SELECT COUNT(*) FROM fixture_event e LEFT JOIN fixture_candidate f USING(fixture_id) WHERE f.fixture_id IS NULL").fetchone()[0]
    if event_orphans:
        errors.append(f"orphan fixture events: {event_orphans}")
    counts = {
        "fixtures": len(rows),
        "sessions": conn.execute("SELECT COUNT(DISTINCT session_ref) FROM fixture_candidate").fetchone()[0],
        "events": conn.execute("SELECT COUNT(*) FROM fixture_event").fetchone()[0],
        "objectivesAvailable": conn.execute("SELECT SUM(objective_available) FROM fixture_candidate").fetchone()[0],
        "pendingAdjudication": conn.execute("SELECT COUNT(*) FROM fixture_candidate WHERE adjudication_status='pending'").fetchone()[0],
    }
    print(json.dumps({"ok": not errors, "integrity": integrity, "counts": counts, "errors": errors}, indent=2))
    conn.close()
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
