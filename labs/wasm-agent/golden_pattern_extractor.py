"""Pure extraction of supported action motifs from proven lane trajectories.

The extractor sees only the compact normalized event projection. It never sees
prompts, model reasoning, raw tool arguments, or raw tool results.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


SCHEMA = "wasm-agent.safe-lab.golden-pattern-evidence.v1"
ACTION_KINDS = frozenset({
    "search", "read", "inspect", "edit", "command", "test", "diff",
    "proof", "checkpoint", "resume", "tool", "final", "terminal",
})
TRUSTED_PROVENANCE = frozenset({"adapter", "gateway", "host", "lane"})


def _instance_id(report: dict[str, Any]) -> str:
    task = report.get("task") if isinstance(report.get("task"), dict) else {}
    fixture = task.get("fixture") if isinstance(task.get("fixture"), dict) else {}
    return str(fixture.get("id") or task.get("taskDigest") or report.get("runId") or "")


def _motifs(events: list[dict[str, Any]]) -> set[tuple[str, ...]]:
    sequence = [
        str(event["k"])
        for event in events
        if isinstance(event, dict)
        and event.get("k") in ACTION_KINDS
        and event.get("s", "ok") == "ok"
        and event.get("o") in TRUSTED_PROVENANCE
    ]
    observed: set[tuple[str, ...]] = set()
    for size in range(2, min(5, len(sequence) + 1)):
        observed.update(tuple(sequence[index:index + size]) for index in range(len(sequence) - size + 1))
    return observed


def extract(
    reports: list[dict[str, Any]], *, min_agents: int = 2, min_instances: int = 3,
) -> dict[str, Any]:
    """Return action motifs supported by distinct agents and task instances."""

    support: dict[tuple[str, ...], dict[str, set[str]]] = defaultdict(
        lambda: {"agents": set(), "instances": set(), "runs": set()}
    )
    eligible = 0
    rejected: dict[str, int] = defaultdict(int)
    for report in reports:
        instance = _instance_id(report)
        run_id = str(report.get("runId") or instance)
        results = report.get("results") if isinstance(report.get("results"), list) else []
        for result in results:
            if not isinstance(result, dict):
                rejected["result_not_object"] += 1
                continue
            semantic = (result.get("answer") or {}).get("semantic") if isinstance(result.get("answer"), dict) else {}
            lane = result.get("lane") if isinstance(result.get("lane"), dict) else {}
            trajectory = lane.get("trajectory") if isinstance(lane.get("trajectory"), dict) else {}
            provenance = trajectory.get("provenance") if isinstance(trajectory.get("provenance"), list) else []
            if not instance:
                rejected["instance_identity_missing"] += 1
                continue
            if not isinstance(semantic, dict) or semantic.get("passed") is not True:
                rejected["semantic_not_passed"] += 1
                continue
            if trajectory.get("completeness") != "complete" or trajectory.get("admissibleForStrategyMining") is not True:
                rejected["trajectory_incomplete"] += 1
                continue
            if not {"adapter", "lane"}.issubset(provenance) or not set(provenance).issubset(TRUSTED_PROVENANCE):
                rejected["provenance_untrusted"] += 1
                continue
            events = trajectory.get("events") if isinstance(trajectory.get("events"), list) else []
            adapter = str(lane.get("adapter") or "")
            if not adapter or not events:
                rejected["trajectory_identity_missing"] += 1
                continue
            eligible += 1
            for motif in _motifs(events):
                support[motif]["agents"].add(adapter)
                support[motif]["instances"].add(instance)
                support[motif]["runs"].add(run_id)

    patterns = []
    for motif, evidence in support.items():
        if len(evidence["agents"]) < min_agents or len(evidence["instances"]) < min_instances:
            continue
        patterns.append({
            "sequence": list(motif),
            "agentSupport": len(evidence["agents"]),
            "instanceSupport": len(evidence["instances"]),
            "runSupport": len(evidence["runs"]),
            "agents": sorted(evidence["agents"]),
        })
    patterns.sort(key=lambda row: (-row["instanceSupport"], -row["agentSupport"], len(row["sequence"]), row["sequence"]))
    return {
        "schema": SCHEMA,
        "eligibleTrajectories": eligible,
        "thresholds": {"agents": min_agents, "instances": min_instances},
        "rejected": dict(sorted(rejected.items())),
        "patterns": patterns,
        "promotionEligible": bool(patterns),
    }
