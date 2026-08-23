#!/usr/bin/env python3
"""Audit the latest exact compound-client V6 production artifact without acting."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/context/latest/master-frontier-v6-compound-client-goals.json"
OBJECTIVE = "open realure space than open browser widget"
REQUIRED_CAPABILITIES = {"client.space.open", "client.widget.open"}


def audit(final: dict[str, Any], *, status: str) -> dict[str, Any]:
    state = final.get("state") if isinstance(final.get("state"), dict) else {}
    diagnostics = final.get("diagnostics") if isinstance(final.get("diagnostics"), dict) else {}
    goals = state.get("goals") if isinstance(state.get("goals"), list) else []
    tools = final.get("local_tools") if isinstance(final.get("local_tools"), list) else []
    evidence = final.get("evidence") if isinstance(final.get("evidence"), list) else []
    tools_by_operation = {
        str(item.get("operation") or ""): item for item in tools
        if isinstance(item, dict) and item.get("operation")
    }
    evidence_by_operation = {
        str(item.get("subject") or "").removeprefix("operation:"): item
        for item in evidence
        if isinstance(item, dict) and str(item.get("subject") or "").startswith("operation:")
    }
    goal_proofs = []
    for goal in goals:
        if not isinstance(goal, dict):
            continue
        operation = str(goal.get("operation") or "")
        capability = str(goal.get("cap") or "")
        tool = tools_by_operation.get(operation, {})
        receipt = evidence_by_operation.get(operation, {})
        proof = set(receipt.get("proof") or [])
        goal_proofs.append({
            "capability": capability,
            "satisfied": goal.get("status") == "satisfied",
            "operationCorrelated": bool(operation and tool and receipt),
            "acknowledged": tool.get("ok") is True and tool.get("status") == "acknowledged"
                and "client.ack" in proof,
            "activeSpaceProof": "client.space.active" in proof,
        })

    capabilities = {item["capability"] for item in goal_proofs}
    checks = {
        "completed": status == "completed" and state.get("status") == "complete",
        "exactObjective": state.get("goal") == OBJECTIVE,
        "goalContractReviewed": (state.get("decision") or {}).get("goal_contract") == "reviewed",
        "twoDistinctGoals": len(goals) == 2 and len({str(g.get("id") or "") for g in goals}) == 2,
        "requiredCapabilities": capabilities == REQUIRED_CAPABILITIES,
        "allGoalsSatisfied": len(goal_proofs) == 2 and all(item["satisfied"] for item in goal_proofs),
        "allOperationsCorrelated": len(goal_proofs) == 2 and all(item["operationCorrelated"] for item in goal_proofs),
        "twoClientAcknowledgements": len(goal_proofs) == 2 and all(item["acknowledged"] for item in goal_proofs),
        "activeSpaceProven": any(
            item["capability"] == "client.space.open" and item["activeSpaceProof"]
            for item in goal_proofs
        ),
        "zeroCompletionGaps": diagnostics.get("completion_gaps") == [],
        "threeProviderCalls": diagnostics.get("provider_calls") == 3,
        "nonemptyReply": bool(str(final.get("reply") or "").strip()),
    }
    return {
        "schema": "MF6_COMPOUND_CLIENT_GOALS_PROOF/1",
        "ok": all(checks.values()),
        "runId": str(final.get("run_id") or ""),
        "objectiveSha256": hashlib.sha256(OBJECTIVE.encode()).hexdigest(),
        "checks": checks,
        "goalProofs": sorted(goal_proofs, key=lambda item: item["capability"]),
        "providerCalls": int(diagnostics.get("provider_calls") or 0),
        "completionGapCount": len(diagnostics.get("completion_gaps") or []),
    }


def latest_matching_run(db_path: Path, run_id: str = "") -> tuple[str, str, dict[str, Any]]:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        if run_id:
            rows = connection.execute(
                "SELECT run_id,status,final_json FROM agent_run_tb WHERE run_id=? AND protocol='v6'", (run_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT run_id,status,final_json FROM agent_run_tb "
                "WHERE protocol='v6' AND status='completed' ORDER BY terminal_at DESC LIMIT 100"
            ).fetchall()
    for row in rows:
        try:
            final = json.loads(row["final_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if (final.get("state") or {}).get("goal") == OBJECTIVE:
            return str(row["run_id"]), str(row["status"]), final
    raise RuntimeError("matching_completed_v6_artifact_missing")


def self_check() -> bool:
    goals = [
        {"id": "g-a", "cap": "client.space.open", "status": "satisfied", "operation": "model-op-a"},
        {"id": "g-b", "cap": "client.widget.open", "status": "satisfied", "operation": "model-op-b"},
    ]
    fixture = {
        "run_id": "synthetic", "reply": "done",
        "state": {"goal": OBJECTIVE, "goals": goals, "status": "complete", "decision": {"goal_contract": "reviewed"}},
        "diagnostics": {"provider_calls": 3, "completion_gaps": []},
        "local_tools": [
            {"operation": "model-op-a", "capability": "client.space.open", "status": "acknowledged", "ok": True},
            {"operation": "model-op-b", "capability": "client.widget.open", "status": "acknowledged", "ok": True},
        ],
        "evidence": [
            {"subject": "operation:model-op-a", "proof": ["client.ack", "client.space.active"]},
            {"subject": "operation:model-op-b", "proof": ["client.ack"]},
        ],
    }
    positive = audit(fixture, status="completed")["ok"] is True
    fixture["evidence"][1]["proof"] = []
    negative = audit(fixture, status="completed")["ok"] is False
    return positive and negative


def main() -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--cloud-root", type=Path, default=Path("/home/ubuntu/.local/share/wasm-agent-cloud"),
    )
    args = parser.parse_args()
    report: dict[str, Any]
    try:
        run_id, status, final = latest_matching_run(
            args.cloud_root / "state/db/sqlite/wa_db.sqlite3", args.run_id,
        )
        report = audit(final, status=status)
        report["runId"] = run_id
        report["selfCheck"] = self_check()
        report["ok"] = report["ok"] and report["selfCheck"]
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        report = {
            "schema": "MF6_COMPOUND_CLIENT_GOALS_PROOF/1", "ok": False,
            "error": {"code": str(exc)}, "selfCheck": self_check(),
        }
    report["durationMs"] = round((time.monotonic() - started) * 1000)
    report["checkedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
