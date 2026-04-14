from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from .config import WikiSettings
from .graph import compile_graph
from .markdown import WikiPage, discover_pages
from .utils import atomic_write_json, normalize_text, utc_now


def _parse_iso(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            loaded = json.loads(raw_line)
        except Exception:
            continue
        if isinstance(loaded, dict):
            events.append(loaded)
    return events


def build_lint_report(
    settings: WikiSettings,
    *,
    pages: list[WikiPage] | None = None,
    graph_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not settings.enabled or not settings.wiki_root.exists():
        return {
            "generated_at": utc_now(),
            "duplicate_concepts": {},
            "orphan_pages": [],
            "broken_links": [],
            "oversized_pages": [],
            "missing_summaries": [],
            "outdated_pages": [],
            "pages_without_evidence": [],
            "invalid_pages": [],
            "enabled": False,
        }

    page_list = pages or discover_pages(settings.wiki_root)
    graph_data = graph_payload or compile_graph(settings)
    graph_report = graph_data.get("report", {})
    graph_metrics = graph_data.get("metrics", {})

    title_groups: dict[str, list[str]] = {}
    for page in page_list:
        key = normalize_text(page.title)
        title_groups.setdefault(key, []).append(page.relative_path)

    duplicate_concepts = {
        key: paths
        for key, paths in title_groups.items()
        if key and len(paths) > 1
    }

    oversized_pages = [
        {
            "path": page.relative_path,
            "lines": len(page.path.read_text(encoding="utf-8").splitlines()),
            "bytes": page.path.stat().st_size,
        }
        for page in page_list
        if len(page.path.read_text(encoding="utf-8").splitlines()) > settings.page_split_line_threshold
        or page.path.stat().st_size > settings.max_page_bytes
    ]

    missing_summaries = [
        page.relative_path
        for page in page_list
        if not page.one_line_summary or not page.short_summary
    ]

    outdated_pages = []
    outdated_threshold = datetime.now(timezone.utc) - timedelta(days=settings.outdated_after_days)
    for page in page_list:
        parsed = _parse_iso(page.updated)
        if parsed is not None and parsed < outdated_threshold:
            outdated_pages.append(page.relative_path)

    pages_without_evidence = [
        page.relative_path
        for page in page_list
        if not str(page.sections.get("evidence", "") or "").strip()
    ]

    report = {
        "generated_at": utc_now(),
        "duplicate_concepts": duplicate_concepts,
        "orphan_pages": graph_metrics.get("orphan_pages", []),
        "broken_links": graph_report.get("broken_references", []),
        "oversized_pages": oversized_pages,
        "missing_summaries": missing_summaries,
        "outdated_pages": outdated_pages,
        "pages_without_evidence": pages_without_evidence,
        "invalid_pages": graph_report.get("invalid_pages", []),
    }

    latest_path = settings.health_reports_root / "latest.json"
    dated_path = settings.health_reports_root / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    atomic_write_json(latest_path, report)
    atomic_write_json(dated_path, report)
    return report


def _query_metrics(settings: WikiSettings) -> dict[str, Any]:
    events = _read_jsonl(settings.observability_root / "query_events.jsonl")
    if not events:
        return {
            "average_pages_loaded_per_query": 0.0,
            "average_graph_hops_used": 0.0,
            "average_summary_depth_used": 0.0,
            "raw_evidence_escalation_rate": 0.0,
            "estimated_tokens_per_query": 0.0,
            "query_count": 0,
        }

    count = len(events)
    return {
        "average_pages_loaded_per_query": round(sum(float(item.get("pages_loaded", 0) or 0) for item in events) / count, 3),
        "average_graph_hops_used": round(sum(float(item.get("graph_hops_used", 0) or 0) for item in events) / count, 3),
        "average_summary_depth_used": round(sum(float(item.get("summary_depth_used", 0) or 0) for item in events) / count, 3),
        "raw_evidence_escalation_rate": round(sum(1 for item in events if int(item.get("raw_evidence_reads", 0) or 0) > 0) / count, 3),
        "estimated_tokens_per_query": round(sum(float(item.get("estimated_tokens", 0) or 0) for item in events) / count, 3),
        "query_count": count,
    }


def _maintenance_metrics(settings: WikiSettings) -> dict[str, Any]:
    governance_events = _read_jsonl(settings.observability_root / "governance_events.jsonl")
    self_heal_actions = _read_jsonl(settings.self_heal_root / "actions.jsonl")

    return {
        "consolidation_gate_actions": len(governance_events),
        "self_healing_interventions": len(self_heal_actions),
        "pending_proposals": len(list((settings.proposals_root / "pending").glob("*.json"))),
        "review_needed_proposals": len(list((settings.proposals_root / "review_needed").glob("*.json"))),
    }


def _health_score(metrics: dict[str, Any], lint_report: dict[str, Any]) -> int:
    score = 100
    score -= min(20, len(lint_report.get("broken_links", [])) * 2)
    score -= min(20, len(lint_report.get("orphan_pages", [])) * 2)
    score -= min(15, len(lint_report.get("oversized_pages", [])) * 3)
    score -= min(15, len(lint_report.get("missing_summaries", [])) * 2)
    score -= min(10, len(lint_report.get("outdated_pages", [])) * 2)
    score -= min(10, len(lint_report.get("pages_without_evidence", [])))
    score -= min(10, metrics["maintenance"]["review_needed_proposals"] * 2)
    return max(0, min(100, score))


def build_observability_snapshot(
    settings: WikiSettings,
    *,
    pages: list[WikiPage] | None = None,
    graph_payload: dict[str, Any] | None = None,
    lint_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not settings.enabled or not settings.wiki_root.exists():
        return {
            "generated_at": utc_now(),
            "knowledge_size": {"total_pages": 0},
            "graph": {},
            "routing_efficiency": _query_metrics(settings),
            "knowledge_quality": {},
            "maintenance": _maintenance_metrics(settings),
            "lint": lint_report or {},
            "health_score": 0,
            "enabled": False,
        }

    page_list = pages or discover_pages(settings.wiki_root)
    graph_data = graph_payload or compile_graph(settings)
    lint = lint_report or build_lint_report(settings, pages=page_list, graph_payload=graph_data)

    type_counts = Counter(page.page_type for page in page_list)
    trust_counts = Counter(page.trust_tier for page in page_list)
    confidence_distribution = Counter(
        "high" if page.confidence >= 0.8 else "medium" if page.confidence >= 0.5 else "low"
        for page in page_list
    )
    page_sizes = [page.path.stat().st_size for page in page_list if page.path.exists()]
    previous = None
    today_path = settings.observability_root / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    if today_path.exists():
        try:
            previous = json.loads(today_path.read_text(encoding="utf-8"))
        except Exception:
            previous = None

    snapshot = {
        "generated_at": utc_now(),
        "knowledge_size": {
            "total_pages": len(page_list),
            "page_distribution_by_type": dict(type_counts),
            "growth_rate_of_pages": len(page_list) - int(((previous or {}).get("knowledge_size", {}) or {}).get("total_pages", len(page_list))),
            "average_page_size": round((sum(page_sizes) / len(page_sizes)) if page_sizes else 0.0, 3),
            "pages_exceeding_size_threshold": len(lint.get("oversized_pages", [])),
        },
        "graph": graph_data.get("metrics", {}),
        "routing_efficiency": _query_metrics(settings),
        "knowledge_quality": {
            "trust_tier_distribution": dict(trust_counts),
            "confidence_distribution": dict(confidence_distribution),
            "outdated_pages": len(lint.get("outdated_pages", [])),
            "pages_without_summaries": len(lint.get("missing_summaries", [])),
            "pages_missing_evidence": len(lint.get("pages_without_evidence", [])),
        },
        "maintenance": _maintenance_metrics(settings),
        "lint": lint,
    }
    snapshot["health_score"] = _health_score(snapshot, lint)

    latest_path = settings.observability_root / "latest.json"
    atomic_write_json(latest_path, snapshot)
    atomic_write_json(today_path, snapshot)
    return snapshot
