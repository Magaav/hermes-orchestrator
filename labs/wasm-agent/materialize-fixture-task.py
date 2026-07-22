#!/usr/bin/env python3
"""Materialize one bounded benchmark task from the read-only SQL fixture bank."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path

BANK = Path("/fixtures/avatar-chat-fixtures-v2.sqlite3")
OVERLAY = Path("/adjudication/avatar-chat-adjudication-v3.sqlite3")
ROUTE_SUMMARY = re.compile(r"^(?P<route>[a-z0-9._-]+)\s+->\s+(?P<root>[^\s]+)$", re.I)
SOURCE = Path("/source")


def digest(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def find_first(value: object, key: str) -> object | None:
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


def route_projection(events: list[sqlite3.Row], payloads: list[object]) -> tuple[str, str]:
    route_id = str(next((find_first(item, "route_id") for item in payloads if find_first(item, "route_id")), ""))
    workspace_root = str(next((find_first(item, "workspace_root") for item in payloads if find_first(item, "workspace_root")), ""))
    if route_id and workspace_root:
        return route_id, workspace_root
    for event in events:
        if event["type"] != "route.resolved":
            continue
        match = ROUTE_SUMMARY.fullmatch(str(event["summary_redacted"] or "").strip())
        if match:
            return route_id or match.group("route"), workspace_root or match.group("root")
    return route_id, workspace_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--output", default="/task/task.json")
    args = parser.parse_args()
    conn = sqlite3.connect(f"file:{BANK}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM fixture_candidate WHERE fixture_id=?", (args.fixture_id,)).fetchone()
    if row is None:
        raise SystemExit("fixture not found")
    events = conn.execute(
        "SELECT source_seq,type,summary_redacted,payload_projection_json FROM fixture_event WHERE fixture_id=? ORDER BY source_seq",
        (args.fixture_id,),
    ).fetchall()
    conn.close()
    bank_sha256 = hashlib.sha256(BANK.read_bytes()).hexdigest()
    overlay_row = None
    overlay_sha256 = ""
    if OVERLAY.is_file():
        overlay = sqlite3.connect(f"file:{OVERLAY}?mode=ro", uri=True)
        overlay.row_factory = sqlite3.Row
        metadata = {key: json.loads(value) for key, value in overlay.execute("SELECT key,value_json FROM adjudication_meta")}
        if metadata.get("bankSha256") != bank_sha256:
            raise SystemExit("adjudication overlay does not match fixture bank")
        overlay_row = overlay.execute("SELECT * FROM fixture_adjudication WHERE fixture_id=?", (args.fixture_id,)).fetchone()
        overlay.close()
        overlay_sha256 = hashlib.sha256(OVERLAY.read_bytes()).hexdigest()
    warnings = json.loads(row["warning_classes_json"] or "[]")
    event_types = [str(event["type"]) for event in events]
    event_payloads = [json.loads(event["payload_projection_json"] or "{}") for event in events]
    route_id, historical_root = route_projection(events, event_payloads)
    if historical_root == "/local":
        replay_root = SOURCE
    elif historical_root.startswith("/local/"):
        replay_root = SOURCE / historical_root.removeprefix("/local/")
    else:
        replay_root = SOURCE / historical_root.lstrip("/") if historical_root else Path()
    route_required = row["request_class"] in {"source_investigation", "runtime_inspection"}
    route_surface_available = (
        bool(route_id)
        if row["request_class"] == "runtime_inspection"
        else bool(historical_root) and replay_root.exists()
    )
    tool_evidence_sufficient = (
        int(row["tool_started_count"]) == int(row["tool_finished_count"])
        and (int(row["tool_started_count"]) > 0 if route_required else True)
    )
    process_baseline = all((
        row["observed_status"] == "completed",
        not row["error_class"],
        not warnings,
        tool_evidence_sufficient,
        bool(row["final_reply_available"]),
        "route.resolved" in event_types if route_required else True,
        "run.final" in event_types,
    ))
    sql_status = str(row["adjudication_status"] or "pending")
    overlay_admitted = bool(overlay_row and overlay_row["decision"] == "admit" and overlay_row["ranking_allowed"] == 1)
    ranking_allowed = overlay_admitted or sql_status in {"golden", "regression"}
    execution_allowed = bool(row["objective_available"]) and (not route_required or route_surface_available)
    adjudication = {
        "sqlStatus": sql_status,
        "overlayStatus": str(overlay_row["decision"]) if overlay_row else "absent",
        "split": str(overlay_row["split"]) if overlay_row else "",
        "expectedContractSha256": str(overlay_row["expected_contract_sha256"]) if overlay_row else "",
        "overlaySha256": overlay_sha256,
        "classification": (
            "replay_environment_incomplete" if route_required and not route_surface_available
            else ("semantic_fixture" if overlay_admitted else ("process_baseline_only" if process_baseline else "insufficient_context"))
        ),
        "processEvidenceSufficient": process_baseline,
        "semanticCorrectness": "contract_adjudicated" if overlay_admitted else "unresolved",
        "executionAllowed": execution_allowed,
        "rankingAllowed": ranking_allowed,
        "reason": (
            "Current route surface is missing from the immutable replay snapshot."
            if route_required and not route_surface_available
            else (
                "Two independent adjudication records admitted a private, digest-bound semantic contract."
                if overlay_admitted else (
                    "Completed route/tool/final evidence supports runner validation, but no private semantic contract admitted this fixture."
                    if process_baseline else "Compact evidence is insufficient for a process baseline."
                )
            )
        ),
    }
    objective = str(row["objective_redacted"] or "").strip()
    if overlay_admitted or row["request_class"] in {"conversation", "general_conversation"}:
        instruction = "Respond directly and concisely. Do not inspect source or call tools unless the objective explicitly requires it."
    else:
        instruction = (
            "Resolve the objective from /source/docs/context/MAP.md first, then inspect only bounded declared paths. "
            + (f"The historical route maps to {replay_root}. " if route_surface_available else "")
            + "Do not change /source or /fixtures. Return a grounded answer that cites the source paths or runtime artifacts used."
        )
    prompt = (
        "Complete the following replay fixture using only evidence available in the isolated lab.\n\n"
        f"Objective: {objective}\n\n{instruction} Do not assume the historical answer was correct."
    )
    task = {
        "schema": "wasm-agent.safe-lab.fixture-task.v1",
        "fixture": {
            "id": str(row["fixture_id"]),
            "bankSha256": bank_sha256,
            "objectiveSha256": str(row["objective_sha256"]),
            "requestClass": str(row["request_class"]),
            "observedStatus": str(row["observed_status"]),
            "observedEventTypes": sorted(set(event_types)),
            "observedToolStarted": int(row["tool_started_count"]),
            "observedToolFinished": int(row["tool_finished_count"]),
            "observedFinalReplyAvailable": bool(row["final_reply_available"]),
            "routeId": route_id,
            "historicalWorkspaceRoot": historical_root,
            "replayWorkspaceRoot": str(replay_root) if historical_root else "",
            "routeSurfaceAvailable": route_surface_available,
        },
        "adjudication": adjudication,
        "model": "frank/GLM-5.2",
        "prompt": prompt,
        "budgets": {
            "maxOutputTokensPerCall": 1024,
            "maxProviderCalls": 4,
            "maxToolIterations": 4,
            "maxIdenticalUpstreamCalls": 2,
            "wallClockSeconds": 180,
            "maxAnswerBytes": 65536
        },
        "authority": {
            "source": "/source:ro",
            "fixtures": "/fixtures:ro",
            "workspace": "/workspace:rw-private",
            "directInternet": False
        }
    }
    task["taskDigest"] = digest(task)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "fixtureId": task["fixture"]["id"],
        "taskDigest": task["taskDigest"],
        "adjudication": adjudication,
    }, separators=(",", ":")))
    return 0 if adjudication["executionAllowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
