#!/usr/bin/env python3
"""Replay compact Master:frontier quests and score engineering leverage."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = ROOT / "plugins" / "wasm-agent"
SERVER_ROOT = PLUGIN_ROOT / "server"
DEFAULT_QUEST_SUITE = PLUGIN_ROOT / "tests" / "fixtures" / "master_frontier_quests.json"
DEFAULT_REPORT = ROOT / "reports" / "context" / "latest" / "master-frontier-watch.json"
DEFAULT_AVATAR_REPORT = ROOT / "reports" / "sim" / "avatar-quest" / "latest" / "result.json"
DEFAULT_NODE_REPORT = ROOT / "reports" / "context" / "latest" / "wasm-agent-node-bridge-proof.json"
DEFAULT_HARVESTED_QUESTS = PLUGIN_ROOT / "tests" / "fixtures" / "master_frontier_harvested_quests.json"

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from master_frontier import dispatch, envelope, planner, route_contracts  # noqa: E402


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def contracts_by_id() -> dict[str, dict[str, Any]]:
    contracts = route_contracts.load_contracts(SERVER_ROOT / "agent_route_contracts.json", PLUGIN_ROOT.resolve())
    return {
        str(contract.get("route_id") or ""): contract
        for contract in contracts
        if str(contract.get("route_id") or "")
    }


def build_envelope(quest: dict[str, Any], contracts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    route_id = str(quest.get("route_id") or "").strip()
    body: dict[str, Any] = {
        "objective": quest.get("objective") or "",
        "surface": quest.get("surface") or "",
    }
    if route_id:
        body["route_id"] = route_id
    contract = contracts.get(route_id)
    if contract and not quest.get("omit_route_contract"):
        body["route_contract"] = contract
        body["capabilities"] = contract.get("caps", [])
    elif isinstance(quest.get("capabilities"), list):
        body["capabilities"] = quest["capabilities"]
    return body


def includes_in_order(actual: list[Any], expected: list[Any]) -> bool:
    index = 0
    for item in actual:
        if index < len(expected) and item == expected[index]:
            index += 1
    return index == len(expected)


def hermes_dispatch_status(parsed: Any, run_envelope: dict[str, Any], contracts: list[dict[str, Any]]) -> dict[str, Any]:
    action = envelope.hermes_dispatch_action(parsed)
    if not action:
        return {"status": "absent", "ok": True, "reasons": []}
    reasons: list[str] = []
    if not dispatch.is_harness_subagent_dispatch(action):
        reasons.append("missing_subagent_harness_role")
    if not dispatch.escalation_reason(action):
        reasons.append("missing_escalation_reason")
    if dispatch.unknown_caps(action):
        reasons.append("unknown_caps")
    if route_contracts.dispatch_workspace_contract(action, run_envelope, contracts) is None:
        reasons.append("route_contract_missing")
    return {
        "status": "bounded" if not reasons else "blocked",
        "ok": not reasons,
        "reasons": reasons,
    }


def check_contains(label: str, actual: list[Any], expected: list[Any], failures: list[str]) -> None:
    missing = [item for item in expected if item not in actual]
    if missing:
        failures.append(f"{label}_missing:{','.join(str(item) for item in missing)}")


def score_quest(quest: dict[str, Any], contracts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    run_envelope = build_envelope(quest, contracts)
    task_contract = planner.task_contract(run_envelope)
    parsed = quest.get("parsed") if isinstance(quest.get("parsed"), dict) else {}
    reply = str(quest.get("reply") or parsed.get("answer") or "")
    expected = quest.get("expect") if isinstance(quest.get("expect"), dict) else {}
    failures: list[str] = []

    for key in ("intent", "executor"):
        if key in expected and task_contract.get(key) != expected[key]:
            failures.append(f"{key}:expected={expected[key]} actual={task_contract.get(key)}")

    if "block_codes" in expected:
        if expected["block_codes"] != task_contract.get("block_codes"):
            failures.append(f"block_codes:expected={expected['block_codes']} actual={task_contract.get('block_codes')}")

    if "proof_required" in expected:
        check_contains("proof_required", task_contract.get("proof_required") or [], expected["proof_required"], failures)

    if "tools_first" in expected and not includes_in_order(task_contract.get("tools_first") or [], expected["tools_first"]):
        failures.append(f"tools_first_order:expected={expected['tools_first']} actual={task_contract.get('tools_first')}")

    structured_required = envelope.requires_structured_action(parsed, reply)
    if "structured_action_required" in expected and structured_required != expected["structured_action_required"]:
        failures.append(f"structured_action_required:expected={expected['structured_action_required']} actual={structured_required}")

    all_contracts = list(contracts.values())
    hermes_status = hermes_dispatch_status(parsed, run_envelope, all_contracts)
    if "hermes_dispatch" in expected and hermes_status["status"] != expected["hermes_dispatch"]:
        failures.append(f"hermes_dispatch:expected={expected['hermes_dispatch']} actual={hermes_status['status']}")
    if hermes_status["status"] == "blocked":
        failures.extend(hermes_status["reasons"])

    passed_checks = 7 - len(failures)
    return {
        "id": quest.get("id") or "unnamed",
        "ok": not failures,
        "score": max(0, passed_checks),
        "maxScore": 7,
        "failures": failures,
        "task_contract": {
            "intent": task_contract.get("intent"),
            "executor": task_contract.get("executor"),
            "route_id": task_contract.get("route_id"),
            "tools_first": task_contract.get("tools_first"),
            "proof_required": task_contract.get("proof_required"),
            "block_codes": task_contract.get("block_codes"),
            "hermes": task_contract.get("hermes"),
        },
        "structured_action_required": structured_required,
        "hermes_dispatch": hermes_status,
    }


def artifact_ok(artifact: dict[str, Any]) -> bool:
    return bool(artifact.get("ok"))


def capability_level(results: list[dict[str, Any]], proof_artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    passed = {str(item["id"]) for item in results if item.get("ok")}
    artifact_passed = {str(item["id"]) for item in (proof_artifacts or []) if artifact_ok(item)}
    levels = [
        ("L1_route_answer", {"capability-widget-local-first", "missing-route-hard-stop"}),
        ("L2_local_diagnosis", {"capability-widget-local-first", "fake-dispatch-prose-caught"}),
        ("L3_scoped_edit_plan", {"implementation-widget-local-kernel"}),
        ("L4_bounded_subagent", {"bounded-hermes-only-with-proof"}),
    ]
    current = "L0_observed"
    for name, required in levels:
        if required <= passed:
            current = name
    live_levels = [
        ("L5_avatar_behavioral", {"avatar-quest-route-token-proof"}),
        ("L6_node_runtime", {"avatar-quest-route-token-proof", "node-bridge-capability-chat-proof"}),
    ]
    if current == "L4_bounded_subagent":
        for name, required in live_levels:
            if required <= artifact_passed:
                current = name
    missing = sorted({quest for _name, required in levels for quest in required} - passed)
    missing_artifacts = sorted({artifact for _name, required in live_levels for artifact in required} - artifact_passed)
    return {"current": current, "missingQuestIds": missing, "missingProofArtifactIds": missing_artifacts}


def engineering_outcome(results: list[dict[str, Any]], proof_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    passed_quests = {str(item["id"]) for item in results if item.get("ok")}
    passed_artifacts = {str(item["id"]) for item in proof_artifacts if artifact_ok(item)}
    metrics = {
        "routeUncertaintyReduced": {"capability-widget-local-first", "missing-route-hard-stop"} <= passed_quests,
        "boundedDispatchProven": "bounded-hermes-only-with-proof" in passed_quests,
        "riskReduced": bool(
            "missing-route-hard-stop" in passed_quests
            and "bounded-hermes-only-with-proof" in passed_quests
        ),
        "liveBehaviorObserved": "avatar-quest-route-token-proof" in passed_artifacts,
        "liveNodeObserved": "node-bridge-capability-chat-proof" in passed_artifacts,
    }
    accepted = [name for name, value in metrics.items() if value]
    return {
        "primaryObjective": "report only independently observed Master:frontier capability",
        "realEngineeringProblemSolved": (
            "replays bounded route/tool contracts and keeps live browser/node claims separate from static fixtures."
        ),
        "metrics": metrics,
        "acceptedMetricCount": len(accepted),
        "requiredMetricCount": len(metrics),
        "status": "useful" if len(accepted) >= 3 else "partial",
        "humanExpertiseHarvested": False,
        "evidence": {
            "passedQuestIds": sorted(passed_quests),
            "passedProofArtifactIds": sorted(passed_artifacts),
        },
    }


def avatar_quest_artifact(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"id": "avatar-quest-route-token-proof", "ok": False, "status": "missing", "path": str(path)}
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return {"id": "avatar-quest-route-token-proof", "ok": False, "status": "unreadable", "path": str(path), "error": str(exc)}
    assertions = payload.get("assertions") if isinstance(payload.get("assertions"), list) else []
    by_name = {str(item.get("name") or ""): item for item in assertions if isinstance(item, dict)}
    required = [
        "Master:frontier selected",
        "route.resolved before provider dispatch on every turn",
        "no Hermes broad fallback",
        "exact quest token ledger persisted",
        "quest aggregate equals sum of turns",
        "objective-only route fails",
    ]
    missing = [name for name in required if by_name.get(name, {}).get("status") != "passed"]
    ok = payload.get("status") == "passed" and int(payload.get("score") or 0) >= 100 and not missing
    return {
        "id": "avatar-quest-route-token-proof",
        "ok": ok,
        "status": "pass" if ok else "fail",
        "path": str(path),
        "runId": payload.get("runId"),
        "score": payload.get("score"),
        "missingAssertions": missing,
        "summary": "avatar quest proves route-before-provider, no Hermes fallback, exact token ledger, and objective-only route failure",
    }


def node_bridge_artifact(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"id": "node-bridge-capability-chat-proof", "ok": False, "status": "missing", "path": str(path)}
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return {"id": "node-bridge-capability-chat-proof", "ok": False, "status": "unreadable", "path": str(path), "error": str(exc)}
    caps = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
    chat = payload.get("chat") if isinstance(payload.get("chat"), dict) else {}
    ok = bool(payload.get("ok") and caps.get("ok") and chat.get("ok") and chat.get("source") == "bridge_runs")
    return {
        "id": "node-bridge-capability-chat-proof",
        "ok": ok,
        "status": "pass" if ok else "fail",
        "path": str(path),
        "nodeId": payload.get("nodeId"),
        "usageModel": chat.get("usageModel"),
        "usageTotalTokens": chat.get("usageTotalTokens"),
        "summary": "node bridge proves node.capabilities and node.chat through bridge_runs",
    }



def proof_artifacts(avatar_report: Path | None, node_report: Path | None, *, require: bool) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    if avatar_report is not None and (require or avatar_report.exists()):
        artifacts.append(avatar_quest_artifact(avatar_report))
    if node_report is not None and (require or node_report.exists()):
        artifacts.append(node_bridge_artifact(node_report))
    return artifacts


def run(
    quest_suite: Path,
    report_path: Path,
    *,
    avatar_report: Path | None = DEFAULT_AVATAR_REPORT,
    node_report: Path | None = DEFAULT_NODE_REPORT,
    require_proof_artifacts: bool = False,
) -> dict[str, Any]:
    started = time.time()
    suite = load_json(quest_suite)
    contracts = contracts_by_id()
    quests = suite.get("quests") if isinstance(suite.get("quests"), list) else []
    results = [score_quest(quest, contracts) for quest in quests if isinstance(quest, dict)]
    artifacts = proof_artifacts(avatar_report, node_report, require=require_proof_artifacts)
    failed_artifacts = [item for item in artifacts if not artifact_ok(item)]
    outcome = engineering_outcome(results, artifacts)
    ok = bool(results) and all(item.get("ok") for item in results) and not (require_proof_artifacts and failed_artifacts)
    report = {
        "schema": "hermes.context.master_frontier.watch_loop.v1",
        "ok": ok,
        "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "durationMs": int((time.time() - started) * 1000),
        "questSuite": str(quest_suite),
        "summary": {
            "passed": sum(1 for item in results if item.get("ok")),
            "failed": sum(1 for item in results if not item.get("ok")),
            "total": len(results),
            "proofArtifactsPassed": sum(1 for item in artifacts if artifact_ok(item)),
            "proofArtifactsFailed": len(failed_artifacts),
            "capability": capability_level(results, artifacts),
            "engineeringOutcome": outcome,
        },
        "builder": {
            "intent": "prove Master:frontier reduces repeated engineering uncertainty without provider calls",
        },
        "watcher": {
            "evidenceClasses": ["static", "behavioral", "runtime"] if artifacts else ["static", "behavioral"],
            "results": results,
            "proofArtifacts": artifacts,
        },
        "gatekeeper": {
            "decision": "promote" if ok and outcome["status"] == "useful" else "repair",
            "nextSuggestedStep": (
                "Run live avatar quest or include runtime node proof."
                if ok
                else "Fix the first failed quest at the owning Master:frontier contract layer."
            ),
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch Master:frontier contract autonomy against compact quests.")
    parser.add_argument("--quest-suite", type=Path, default=DEFAULT_QUEST_SUITE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--avatar-report", type=Path, default=DEFAULT_AVATAR_REPORT)
    parser.add_argument("--node-report", type=Path, default=DEFAULT_NODE_REPORT)
    parser.add_argument("--require-proof-artifacts", action="store_true")
    args = parser.parse_args()
    report = run(
        args.quest_suite.resolve(),
        args.report.resolve(),
        avatar_report=args.avatar_report.resolve() if args.avatar_report else None,
        node_report=args.node_report.resolve() if args.node_report else None,
        require_proof_artifacts=args.require_proof_artifacts,
    )
    summary = report["summary"]
    print(
        "Master:frontier watch loop: "
        f"{'PASS' if report['ok'] else 'FAIL'} "
        f"({summary['passed']}/{summary['total']} quests, {summary['capability']['current']})"
    )
    print(f"Report JSON: {args.report}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
