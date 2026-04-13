from __future__ import annotations

from typing import Any

from .config import WikiSettings
from .utils import file_lock


RISK_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


def proposal_sort_key(proposal: dict[str, Any]) -> tuple[Any, ...]:
    return (
        RISK_ORDER.get(str(proposal.get("risk_level", "medium") or "medium").lower(), 9),
        str(proposal.get("created_at") or ""),
        str(proposal.get("proposal_id") or ""),
    )


def dedupe_proposals(
    proposals: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], dict[str, Any]]]]:
    keepers: list[dict[str, Any]] = []
    duplicates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    by_key: dict[str, dict[str, Any]] = {}

    for proposal in sorted(proposals, key=proposal_sort_key):
        dedupe_key = str(proposal.get("dedupe_key") or proposal.get("proposal_id") or "")
        if not dedupe_key:
            keepers.append(proposal)
            continue
        if dedupe_key not in by_key:
            by_key[dedupe_key] = proposal
            keepers.append(proposal)
            continue
        winner = by_key[dedupe_key]
        winner.setdefault("merged_from", []).append(proposal.get("proposal_id"))
        winner.setdefault("source_signals", [])
        for signal in proposal.get("source_signals", []) or []:
            if signal not in winner["source_signals"]:
                winner["source_signals"].append(signal)
        duplicates.append((proposal, winner))
    return keepers, duplicates


def ordered_proposals(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(proposals, key=proposal_sort_key)


def coordinated_commit(settings: WikiSettings):
    return file_lock(settings.queue_lock_path, timeout_sec=settings.proposal_lock_timeout_sec)
