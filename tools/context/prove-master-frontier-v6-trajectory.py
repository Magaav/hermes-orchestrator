#!/usr/bin/env python3
"""Prove the V6 append-only trajectory and model-context dataflow."""
from __future__ import annotations

import copy
import json
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "plugins/wasm-agent/server"
REPORT = ROOT / "reports/context/latest/master-frontier-v6-trajectory-result.json"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import controller, execution_profiles, kernel, persistence, tool_compat, trajectory  # noqa: E402


def tool(name, arguments):
    return {"reply": "", "tool_calls": [{"id": "call-1", "name": name, "arguments": arguments}], "usage": {"input_tokens": 4, "output_tokens": 2}}


def prove() -> dict:
    started = time.monotonic()
    emitted = []
    decisions = [tool("discover", {"search": "unavailable fixture capability"}), {"reply": "No route capability matched."}]
    agent = kernel.Kernel(authorities=set())
    result = controller.run(
        "Inspect the fixture", agent, lambda *_args: decisions.pop(0),
        emit=emitted.append, execution_profile="minimal",
    )
    stream = trajectory.create(run_id="proof-run", route_id="proof.route")
    trajectory.append(stream, kind="run.started", source="proof", payload={"profile": "minimal"})
    for event in emitted:
        if event["type"] == "trajectory.context":
            trajectory.append(stream, kind="context.projected", source="v6.context", payload=trajectory.context_payload(
                event["messages"], event["tools"], decision=event["decision"], profile=event["profile"],
            ))
        elif event["type"] == "trajectory.model":
            trajectory.append(stream, kind="model.completed", source="provider", payload={"decision": event["decision"], "result": event["result"]})
        elif event["type"] == "decision.completed":
            trajectory.append(stream, kind="decision.completed", source="v6.controller", payload={key: value for key, value in event.items() if key != "type"})
            trajectory.append(stream, kind="tool.completed", source=f"tool:{event['tool']}", payload={key: value for key, value in event.items() if key != "type"})
    trajectory.append(stream, kind="run.completed", source="proof", payload={"answer": result["answer"]})
    verified = trajectory.verify(stream)
    replayed = trajectory.replay(stream)

    tampered = copy.deepcopy(stream)
    tampered["events"][1]["payload"]["profile"] = "semantic"
    tamper_rejected = False
    try:
        trajectory.verify(tampered)
    except trajectory.TrajectoryError:
        tamper_rejected = True

    with tempfile.TemporaryDirectory(prefix="mf6-trajectory-proof-") as temporary:
        database = Path(temporary) / "state.sqlite3"

        def connect():
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            return connection

        route = {"route_id": "proof.route", "owner": "proof", "workspace_root": "/proof", "allowed_read_roots": ["/proof"], "caps": []}
        snapshot = {"schema": persistence.SNAPSHOT_SCHEMA, "kernel": {}, "discovered": [], "trajectory": trajectory.checkpoint(stream)}
        reference = persistence.save(connect, user_id="proof-user", session_id="proof-session", route=route, run_id="proof-run", turn_id="proof-turn", snapshot=snapshot)
        loaded = persistence.load(connect, user_id="proof-user", session_id="proof-session", route=route, source_run_id="proof-run", expected_sha256=reference["sha256"])
        child = trajectory.create(run_id="proof-child", route_id="proof.route", parent=loaded["trajectory"])

    contexts = replayed["contexts"]
    decision_events = [event for event in emitted if event["type"] == "decision.completed"]
    checks = {
        "chainVerifies": verified["count"] == len(stream["events"]),
        "contextReconstructs": bool(contexts and contexts[0]["messages"][1]["content"].startswith("MF6/1") and contexts[0]["tool_contracts"]),
        "contextHasProvenanceAndCost": bool(contexts and all(block["source"] and block["sha256"] and block["chars"] >= 0 for block in contexts[0]["blocks"])),
        "structuredToolFailure": bool(decision_events and decision_events[0]["error"] == {"code": "capability_match", "recoverable": True}),
        "legacyArgumentsNormalized": tool_compat.normalize("discover", {"search": "x", "max_results": 2}) == {"query": "x", "limit": 2},
        "routeProfileApplied": execution_profiles.resolve({"execution_profile": "minimal"})["history_turns"] == 0,
        "tamperRejected": tamper_rejected,
        "checkpointRoundTrip": loaded["trajectory"]["head"] == stream["head"],
        "forkBindsParentHead": child["parent"]["head"] == stream["head"],
        "terminalReplays": replayed["terminal"] == {"answer": "No route capability matched."},
    }
    return {
        "schema": "master.frontier.v6.trajectory.proof.v1",
        "status": "pass" if all(checks.values()) else "fail",
        "promiseId": "master-frontier-v6-trajectory-dataflow",
        "claim": "V6 model-visible dataflow is reconstructable, hash-linked, replayable, profile-owned, and compatibility-normalized.",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "durationMs": round((time.monotonic() - started) * 1000),
        "checks": checks,
        "metrics": {"events": stream["count"], "contexts": len(contexts), "decisions": len(decision_events), "head": stream["head"]},
        "evidence": [str(REPORT.relative_to(ROOT))],
        "summary": "All V6 trajectory and dataflow checks passed." if all(checks.values()) else "One or more V6 trajectory checks failed.",
        "failureClass": None if all(checks.values()) else "trajectory_dataflow_regression",
        "nextSuggestedSteps": [] if all(checks.values()) else ["Inspect the first false check and repair its owning V6 contract."],
    }


def main() -> int:
    report = prove()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
