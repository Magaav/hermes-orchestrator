from __future__ import annotations

from itertools import combinations
from typing import Any

from .config import WikiSettings
from .governance import submit_proposal
from .graph import compile_graph
from .markdown import WikiPage, discover_pages
from .utils import atomic_write_json, normalize_text, utc_now


def _title_similarity(left: str, right: str) -> float:
    left_tokens = {token for token in normalize_text(left).split() if token}
    right_tokens = {token for token in normalize_text(right).split() if token}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def analyse_refactor_candidates(
    settings: WikiSettings,
    *,
    stage_proposals: bool = False,
) -> dict[str, Any]:
    if not settings.enabled:
        return {
            "report_path": "",
            "action_count": 0,
            "staged_proposals": [],
            "enabled": False,
        }

    pages = discover_pages(settings.wiki_root)
    graph_payload = compile_graph(settings)
    actions: list[dict[str, Any]] = []
    staged: list[str] = []

    for page in pages:
        line_count = len(page.path.read_text(encoding="utf-8").splitlines())
        if line_count > settings.page_split_line_threshold:
            actions.append(
                {
                    "action_type": "page_split",
                    "affected_pages": [page.relative_path],
                    "reasoning_summary": f"Page has {line_count} lines and exceeds the split threshold of {settings.page_split_line_threshold}.",
                    "risk_level": "medium",
                }
            )

    for left, right in combinations(pages, 2):
        if left.relative_path == right.relative_path:
            continue
        if _title_similarity(left.title, right.title) >= 0.8:
            actions.append(
                {
                    "action_type": "page_merge",
                    "affected_pages": [left.relative_path, right.relative_path],
                    "reasoning_summary": "Titles are highly similar and likely represent overlapping durable concepts.",
                    "risk_level": "high",
                }
            )

    orphan_pages = graph_payload.get("metrics", {}).get("orphan_pages", [])
    for orphan in orphan_pages:
        actions.append(
            {
                "action_type": "archive_recommendation",
                "affected_pages": [orphan],
                "reasoning_summary": "Page is structurally orphaned and may need reparenting, indexing, or archival review.",
                "risk_level": "low",
            }
        )

    report = {
        "generated_at": utc_now(),
        "action_count": len(actions),
        "actions": actions,
    }
    report_path = settings.refactor_root / f"{utc_now().replace(':', '').replace('-', '')}.json"
    atomic_write_json(report_path, report)

    if stage_proposals:
        for action in actions:
            proposal = submit_proposal(
                settings,
                {
                    "proposal_type": action["action_type"],
                    "page_type": "index",
                    "title": f"Refactor: {action['action_type']} {' '.join(action['affected_pages'])}",
                    "short_summary": action["reasoning_summary"],
                    "details": action["reasoning_summary"],
                    "confidence": 0.7,
                    "frequency": 2,
                    "durability_days": 90,
                    "detection_source": "akr",
                    "risk_level": action["risk_level"],
                    "target_page": action["affected_pages"][0],
                    "affected_pages": action["affected_pages"],
                },
            )
            staged.append(str(proposal["proposal_id"]))

    return {
        "report_path": str(report_path.relative_to(settings.wiki_root)),
        "action_count": len(actions),
        "staged_proposals": staged,
    }
