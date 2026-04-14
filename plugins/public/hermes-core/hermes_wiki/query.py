from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .compression import build_compression_artifacts, estimate_tokens
from .config import WikiSettings
from .graph import compile_graph
from .markdown import discover_pages
from .observability import build_observability_snapshot
from .utils import append_jsonl, normalize_text, utc_now


TRUST_WEIGHT = {
    "provisional": 1,
    "validated": 2,
    "canonical": 3,
}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _ensure_artifacts(settings: WikiSettings) -> tuple[dict[str, Any], dict[str, Any]]:
    aliases = settings.graph_root / "aliases.json"
    routing_cards = settings.compression_root / "routing_cards.json"
    if not aliases.exists() or not routing_cards.exists():
        graph_payload = compile_graph(settings)
        build_compression_artifacts(settings, graph_payload=graph_payload)
    return (
        _load_json(settings.graph_root / "aliases.json"),
        _load_json(settings.compression_root / "routing_cards.json"),
    )


def _score_candidate(query_tokens: set[str], query_norm: str, card: dict[str, Any]) -> float:
    score = 0.0
    title = normalize_text(str(card.get("title") or ""))
    aliases = {normalize_text(alias) for alias in card.get("aliases", []) or []}
    tags = {normalize_text(tag) for tag in card.get("tags", []) or []}
    summary_tokens = set(normalize_text(str(card.get("one_line_summary") or "")).split())
    summary_tokens.update(normalize_text(str(card.get("short_summary") or "")).split())

    if query_norm == title or query_norm in aliases:
        score += 10.0
    score += len(query_tokens & set(title.split())) * 2.0
    score += len(query_tokens & aliases) * 2.5
    score += len(query_tokens & tags) * 1.5
    score += len(query_tokens & summary_tokens) * 0.5
    score += TRUST_WEIGHT.get(str(card.get("trust_tier") or "provisional"), 1) * 0.25
    score += float(card.get("confidence", 0.0) or 0.0)
    return score


def query_wiki(
    settings: WikiSettings,
    query_text: str,
    *,
    require_detail: bool = False,
    max_pages_loaded: int | None = None,
    max_graph_hops: int | None = None,
    max_summary_layers: int | None = None,
    max_raw_evidence_reads: int | None = None,
    max_token_target: int | None = None,
) -> dict[str, Any]:
    if not settings.enabled or not settings.wiki_root.exists():
        return {
            "query": query_text,
            "selected_node": None,
            "context": "",
            "pages_loaded": 0,
            "graph_hops_used": 0,
            "summary_depth_used": 0,
            "raw_evidence_reads": 0,
            "estimated_tokens": 0,
            "enabled": False,
        }

    alias_map, routing_cards = _ensure_artifacts(settings)
    graph_payload = compile_graph(settings)
    build_compression_artifacts(settings, graph_payload=graph_payload)

    pages_by_id = {page.node_id: page for page in discover_pages(settings.wiki_root)}
    query_norm = normalize_text(query_text)
    query_tokens = {token for token in query_norm.split() if token}

    pages_budget = max_pages_loaded or settings.max_pages_per_query
    hops_budget = max_graph_hops or settings.max_graph_hops
    summary_budget = max_summary_layers or settings.max_summary_layers
    raw_budget = max_raw_evidence_reads if max_raw_evidence_reads is not None else settings.max_raw_evidence_reads
    token_budget = max_token_target or settings.max_token_target

    selected_id = alias_map.get(query_norm)
    if selected_id is None:
        scored = sorted(
            (
                (node_id, _score_candidate(query_tokens, query_norm, card))
                for node_id, card in routing_cards.items()
            ),
            key=lambda item: (-item[1], item[0]),
        )
        selected_id = scored[0][0] if scored and scored[0][1] > 0 else None

    if selected_id is None:
        return {
            "query": query_text,
            "selected_node": None,
            "context": "",
            "pages_loaded": 0,
            "graph_hops_used": 0,
            "summary_depth_used": 0,
            "raw_evidence_reads": 0,
            "estimated_tokens": 0,
        }

    adjacency = graph_payload.get("adjacency", {})
    visited: list[str] = []
    queue: list[tuple[str, int]] = [(selected_id, 0)]
    seen: set[str] = set()
    while queue and len(visited) < pages_budget:
        node_id, hops = queue.pop(0)
        if node_id in seen:
            continue
        seen.add(node_id)
        visited.append(node_id)
        if hops >= hops_budget:
            continue
        neighbor_groups = adjacency.get(node_id, {})
        neighbors: list[str] = []
        for edge_type in ("related", "depends_on", "used_by", "parent", "children", "link"):
            neighbors.extend(neighbor_groups.get(edge_type, []))
        for neighbor in neighbors:
            if neighbor not in seen:
                queue.append((neighbor, hops + 1))

    summary_depth = 1
    raw_reads = 0
    blocks: list[str] = []
    estimated_tokens = 0

    detail_requested = require_detail or any(token in query_norm for token in ("detail", "full", "why", "how", "evidence", "verify"))
    for index, node_id in enumerate(visited):
        page = pages_by_id.get(node_id)
        if page is None:
            continue
        card = routing_cards.get(node_id, {})
        block_parts = [f"# {page.title}", ""]
        one_line = str(card.get("one_line_summary") or page.one_line_summary or "").strip()
        short = str(card.get("short_summary") or page.short_summary or "").strip()
        details = str(page.sections.get("details", "") or "").strip()
        evidence = str(page.sections.get("evidence", "") or "").strip()

        if one_line:
            block_parts.append(one_line)
            block_parts.append("")
        if summary_budget >= 2 and (index == 0 or detail_requested or page.trust_tier == "provisional") and short:
            block_parts.append(short)
            block_parts.append("")
            summary_depth = max(summary_depth, 2)
        if detail_requested and index == 0 and details:
            block_parts.append(details)
            block_parts.append("")
            summary_depth = max(summary_depth, 3)
        if raw_budget > raw_reads and (detail_requested or page.trust_tier == "provisional") and evidence:
            block_parts.append("Evidence:")
            block_parts.append(evidence)
            block_parts.append("")
            raw_reads += 1

        candidate_block = "\n".join(block_parts).strip()
        candidate_tokens = estimate_tokens(candidate_block)
        if blocks and estimated_tokens + candidate_tokens > token_budget:
            break
        blocks.append(candidate_block)
        estimated_tokens += candidate_tokens

    result = {
        "query": query_text,
        "selected_node": selected_id,
        "context": "\n\n".join(block for block in blocks if block).strip(),
        "pages_loaded": len(blocks),
        "graph_hops_used": min(hops_budget, max(0, len(visited) - 1)),
        "summary_depth_used": summary_depth,
        "raw_evidence_reads": raw_reads,
        "estimated_tokens": estimated_tokens,
        "loaded_nodes": visited[: len(blocks)],
    }

    append_jsonl(
        settings.observability_root / "query_events.jsonl",
        {
            "query": query_text,
            "selected_node": selected_id,
            "pages_loaded": result["pages_loaded"],
            "graph_hops_used": result["graph_hops_used"],
            "summary_depth_used": result["summary_depth_used"],
            "raw_evidence_reads": raw_reads,
            "estimated_tokens": estimated_tokens,
            "queried_at": utc_now(),
        },
    )
    build_observability_snapshot(settings, graph_payload=graph_payload)
    return result
