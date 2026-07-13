#!/usr/bin/env python3
"""Generate a redacted fixture candidate for every historical avatar-chat run."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "wasm-agent.fixture-bank.v1"
EVENT_TYPES = {
    "route.resolved", "head.decision", "tool.started", "tool.finished",
    "evidence.missing", "gate.decision", "loop.critique", "loop.incomplete",
    "run.final", "run.error", "files.changed", "proof.collected",
}
SENSITIVE = re.compile(r"(?i)(api[_-]?key|authorization|bearer|cookie|password|secret|access[_-]?token|refresh[_-]?token)")
SECRET_VALUE = re.compile(r"(?i)\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
RAW_REF = re.compile(r"(?i)\b(?:wa_run_[a-z0-9]{12,}|agent_[a-z0-9]{6,}_[a-z0-9]{4,})\b")

REQUEST_RULES = [
    ("implementation", re.compile(r"(?i)\b(fix|implement|change|add|remove|update|patch|build|create|make)\b")),
    ("diagnosis", re.compile(r"(?i)\b(why|failed|failure|bug|broken|diagnos|root cause|what happened)\b")),
    ("source_investigation", re.compile(r"(?i)\b(code|source|file|function|class|module|route|implementation)\b")),
    ("runtime_inspection", re.compile(r"(?i)\b(runtime|session|run|state|status|device|production|live)\b")),
    ("evaluation_or_critique", re.compile(r"(?i)\b(critic|review|evaluate|how good|compare|benchmark)\b")),
    ("explanation", re.compile(r"(?i)\b(explain|what is|what are|how does|tell me|describe)\b")),
    ("conversation", re.compile(r"(?i)^(hi|hello|hey|thanks|thank you|ok|okay)[.!? ]*$")),
]


def clean_text(value: Any, limit: int = 1200) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    text = SECRET_VALUE.sub("[redacted-secret]", text)
    text = EMAIL.sub("[redacted-email]", text)
    text = RAW_REF.sub("[redacted-runtime-ref]", text)
    return text[:limit]


def redact(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return "[depth-clipped]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:40]:
            name = clean_text(key, 100)
            result[name] = "[redacted]" if SENSITIVE.search(name) else redact(item, depth + 1)
        return result
    if isinstance(value, list):
        return [redact(item, depth + 1) for item in value[:40]]
    if isinstance(value, str):
        return clean_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return clean_text(value)


def parsed(text: str) -> Any:
    try:
        return json.loads(text or "{}")
    except (TypeError, ValueError):
        return {}


def find_first(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        direct = value.get(key)
        if direct not in (None, "", [], {}):
            return direct
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


def public_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:20]}"


def request_class(objective: str, protocol: str) -> str:
    if not objective:
        return "objective_unavailable"
    for name, rule in REQUEST_RULES:
        if rule.search(objective):
            return name
    if protocol == "v4-source-investigation":
        return "source_investigation"
    if re.search(r"(?i)\b(no|wrong|not what|instead|but|however|you (?:did|didn't|should|must|need))\b", objective):
        return "feedback_or_correction"
    if "?" in objective or re.match(r"(?i)^(who|what|when|where|why|how|can|could|do|does|did|is|are|will|would|should)\b", objective):
        return "general_question"
    if re.match(r"(?i)^(please\s+)?[a-z]+\b", objective) and len(objective.split()) >= 2:
        return "general_directive"
    return "general_conversation"


def error_class(row: sqlite3.Row, events: list[sqlite3.Row]) -> str:
    error = parsed(row["error_json"])
    code = find_first(error, "code") or find_first(error, "error_code")
    if code:
        return clean_text(code, 100)
    preview = clean_text(find_first(error, "preview"), 6000)
    for known in ("no_semantic_progress", "network-timeout", "model_output_invalid"):
        if known in preview:
            return known
    for event in reversed(events):
        if event["type"] == "run.error":
            payload = parsed(event["payload_json"])
            return clean_text(find_first(payload, "error_code") or event["summary"] or "untyped_error", 100)
    return ""


def warning_classes(row: sqlite3.Row, events: list[sqlite3.Row], code: str) -> list[str]:
    warnings: set[str] = set()
    mapping = {
        "no_semantic_progress": "redundant_or_nonprogressing_action",
        "network-timeout": "transient_provider_failure",
        "provider-empty-response": "empty_provider_result",
        "structured_action_required": "claimed_action_without_executable_action",
        "file_read_missing": "stale_or_missing_route_evidence",
        "implementation_goal_incomplete": "premature_implementation_completion",
        "master_frontier_loop_incomplete": "premature_terminal_failure",
        "missing_proof:tests": "missing_required_proof",
        "api_call_budget_exhausted": "budget_exhaustion",
        "api_call_safety_ceiling": "budget_exhaustion",
        "provider_token_budget_exhausted": "budget_exhaustion",
        "synthesis_token_budget": "budget_exhaustion",
        "agent_run_interrupted": "infrastructure_interruption",
    }
    if code in mapping:
        warnings.add(mapping[code])
    types = {event["type"] for event in events}
    if "evidence.missing" in types:
        warnings.add("missing_evidence")
    if "loop.incomplete" in types:
        warnings.add("premature_terminal_failure")
    if row["status"] == "completed" and "run.error" in types:
        warnings.add("completed_with_internal_error")
    return sorted(warnings)


def classification(status: str, warnings: list[str], objective: str) -> tuple[str, str]:
    if status == "completed" and not warnings:
        return "baseline_success", "medium"
    if not objective:
        return "insufficient_context", "low"
    if status in {"failed", "interrupted"}:
        return "candidate_agent_or_harness_defect", "medium"
    return "candidate_efficiency_or_quality_warning", "low"


def recovery_expectation(status: str, code: str) -> str:
    if status == "completed":
        return "Preserve grounded completion while reducing any classified warning without weakening proof or safety."
    if code in {"network-timeout", "provider-empty-response", "agent_run_interrupted"}:
        return "Resume from the persisted checkpoint, retry or fail over within budget, and preserve a useful bounded answer."
    if code == "no_semantic_progress":
        return "Reuse completed evidence, suppress unjustified repetition, and converge to a different action or grounded final answer."
    if code == "file_read_missing":
        return "Refresh route evidence, resolve the current owned path, and continue without broad or unsafe search."
    if code == "structured_action_required":
        return "Perform one bounded format repair or answer directly without unsupported execution claims."
    return "Recover using accepted evidence and return completed, completed_with_limits, or a precise safely resumable result."


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    PRAGMA journal_mode=DELETE;
    PRAGMA foreign_keys=ON;
    CREATE TABLE bank_meta (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
    CREATE TABLE fixture_candidate (
      fixture_id TEXT PRIMARY KEY, source_run_ref TEXT NOT NULL UNIQUE,
      session_ref TEXT NOT NULL, ordinal_in_session INTEGER NOT NULL,
      protocol TEXT NOT NULL, observed_status TEXT NOT NULL,
      request_class TEXT NOT NULL, objective_redacted TEXT NOT NULL,
      objective_sha256 TEXT NOT NULL, objective_available INTEGER NOT NULL,
      error_class TEXT NOT NULL, warning_classes_json TEXT NOT NULL,
      preliminary_classification TEXT NOT NULL, classification_confidence TEXT NOT NULL,
      recovery_expectation TEXT NOT NULL, created_at_ms INTEGER NOT NULL,
      duration_ms INTEGER NOT NULL, event_count INTEGER NOT NULL,
      tool_started_count INTEGER NOT NULL, tool_finished_count INTEGER NOT NULL,
      provider_call_count INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
      final_reply_available INTEGER NOT NULL, adjudication_status TEXT NOT NULL DEFAULT 'pending'
    );
    CREATE TABLE fixture_event (
      fixture_id TEXT NOT NULL REFERENCES fixture_candidate(fixture_id) ON DELETE CASCADE,
      source_seq INTEGER NOT NULL, type TEXT NOT NULL, summary_redacted TEXT NOT NULL,
      payload_projection_json TEXT NOT NULL, PRIMARY KEY(fixture_id, source_seq)
    );
    CREATE INDEX fixture_request_class_idx ON fixture_candidate(request_class);
    CREATE INDEX fixture_error_class_idx ON fixture_candidate(error_class);
    CREATE INDEX fixture_status_idx ON fixture_candidate(observed_status);
    """)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite fixture bank: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(output)
    create_schema(dst)
    runs = src.execute("SELECT * FROM agent_run_tb WHERE kind='avatar-chat' ORDER BY created_at, run_id").fetchall()
    session_ordinals: dict[str, int] = {}
    counts: dict[str, int] = {}
    for row in runs:
        raw_session = str(row["session_id"] or "session-missing")
        session_ordinals[raw_session] = session_ordinals.get(raw_session, 0) + 1
        events = src.execute("SELECT seq,type,summary,payload_json,created_at FROM agent_run_event_tb WHERE run_id=? ORDER BY seq", (row["run_id"],)).fetchall()
        documents = [parsed(row["request_summary_json"]), parsed(row["final_json"]), parsed(row["error_json"])]
        documents.extend(parsed(event["payload_json"]) for event in events)
        objective = clean_text(next((find_first(doc, "objective") for doc in documents if find_first(doc, "objective")), ""), 2000)
        code = error_class(row, events)
        warnings = warning_classes(row, events, code)
        preliminary, confidence = classification(row["status"], warnings, objective)
        fixture_id = public_id("fx", str(row["run_id"]))
        request_kind = request_class(objective, row["protocol"])
        token_total = sum(int(find_first(parsed(event["payload_json"]), "total_tokens") or 0) for event in events if event["type"] == "llm.inference.completed")
        provider_calls = sum(1 for event in events if event["type"] == "llm.inference.completed")
        terminal = int(row["terminal_at"] or row["updated_at"] or row["created_at"])
        duration = max(0, terminal - int(row["created_at"]))
        dst.execute("""INSERT INTO fixture_candidate VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            fixture_id, public_id("run", str(row["run_id"])), public_id("session", raw_session), session_ordinals[raw_session],
            row["protocol"], row["status"], request_kind, objective, hashlib.sha256(objective.encode()).hexdigest(), int(bool(objective)),
            code, json.dumps(warnings), preliminary, confidence, recovery_expectation(row["status"], code), int(row["created_at"]),
            duration, len(events), sum(event["type"] == "tool.started" for event in events), sum(event["type"] == "tool.finished" for event in events),
            provider_calls, token_total, int(bool(find_first(parsed(row["final_json"]), "reply") or find_first(parsed(row["final_json"]), "answer"))), "pending",
        ))
        for event in events:
            if event["type"] not in EVENT_TYPES:
                continue
            payload = parsed(event["payload_json"])
            projection = {
                key: find_first(payload, key)
                for key in ("code", "error_code", "tool", "operation", "status", "decision", "reason", "changed_file_count", "reply_chars")
                if find_first(payload, key) not in (None, "", [], {})
            }
            dst.execute("INSERT INTO fixture_event VALUES (?,?,?,?,?)", (
                fixture_id, int(event["seq"]), event["type"], clean_text(event["summary"], 500),
                json.dumps(redact(projection), separators=(",", ":")),
            ))
        counts[preliminary] = counts.get(preliminary, 0) + 1
    metadata = {
        "schema": SCHEMA,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "runCount": len(runs),
        "sessionCount": len(session_ordinals),
        "classificationCounts": counts,
        "rawIdentifiersStored": False,
        "rawPayloadsStored": False,
        "adjudication": "pending",
    }
    for key, value in metadata.items():
        dst.execute("INSERT INTO bank_meta VALUES (?,?)", (key, json.dumps(value)))
    dst.commit()
    integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
    dst.close()
    src.close()
    print(json.dumps({**metadata, "integrity": integrity, "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
