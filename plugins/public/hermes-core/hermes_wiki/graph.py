from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import WikiSettings
from .markdown import RELATION_FIELDS, WikiPage, discover_pages, normalize_reference
from .utils import atomic_write_json, normalize_text, utc_now


TRUST_WEIGHT = {
    "provisional": 1,
    "validated": 2,
    "canonical": 3,
}


def _page_reference_keys(page: WikiPage) -> list[str]:
    keys = [
        normalize_text(page.title),
        normalize_text(page.node_id),
        normalize_text(page.relative_path.replace(".md", "")),
        normalize_text(Path(page.relative_path).stem),
    ]
    keys.extend(normalize_text(alias) for alias in page.aliases)
    return [key for key in keys if key]


def _best_page_for_key(existing: WikiPage | None, candidate: WikiPage) -> WikiPage:
    if existing is None:
        return candidate
    current_weight = TRUST_WEIGHT.get(existing.trust_tier, 0)
    candidate_weight = TRUST_WEIGHT.get(candidate.trust_tier, 0)
    if candidate_weight != current_weight:
        return candidate if candidate_weight > current_weight else existing
    if candidate.confidence != existing.confidence:
        return candidate if candidate.confidence > existing.confidence else existing
    return candidate if candidate.relative_path < existing.relative_path else existing


def build_lookup_maps(
    pages: list[WikiPage],
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, WikiPage]]:
    page_by_id = {page.node_id: page for page in pages}
    primary: dict[str, WikiPage] = {}
    collisions: dict[str, list[str]] = defaultdict(list)

    for page in pages:
        for key in _page_reference_keys(page):
            winner = _best_page_for_key(primary.get(key), page)
            primary[key] = winner
            collisions[key].append(page.node_id)

    alias_map = {key: page.node_id for key, page in primary.items()}
    duplicate_aliases = {
        key: sorted(set(values))
        for key, values in collisions.items()
        if len(set(values)) > 1
    }
    return alias_map, duplicate_aliases, page_by_id


def resolve_reference(reference: str, alias_map: dict[str, str], page_by_id: dict[str, WikiPage]) -> str | None:
    normalized = normalize_text(normalize_reference(reference))
    if not normalized:
        return None
    if normalized in alias_map:
        return alias_map[normalized]
    if normalized in page_by_id:
        return normalized
    return None


def _add_edge(edges: list[dict[str, Any]], seen: set[tuple[str, str, str]], source: str, target: str, edge_type: str, *, origin: str) -> None:
    key = (source, target, edge_type)
    if source == target or key in seen:
        return
    seen.add(key)
    edges.append(
        {
            "source": source,
            "target": target,
            "type": edge_type,
            "origin": origin,
        }
    )


def _build_edges(
    pages: list[WikiPage],
    alias_map: dict[str, str],
    page_by_id: dict[str, WikiPage],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    edges: list[dict[str, Any]] = []
    broken_refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for page in pages:
        for field in RELATION_FIELDS:
            raw_values: list[str]
            if field == "parent":
                raw_parent = str(page.metadata.get("parent") or "").strip()
                raw_values = [raw_parent] if raw_parent else []
            else:
                raw_values = [str(value).strip() for value in page.metadata.get(field, []) or [] if str(value).strip()]

            for raw_value in raw_values:
                if "://" in raw_value and field == "sources":
                    broken_refs.append(
                        {
                            "page": page.node_id,
                            "reference": raw_value,
                            "field": field,
                            "reason": "external_source_reference",
                        }
                    )
                    continue
                target = resolve_reference(raw_value, alias_map, page_by_id)
                if target is None:
                    broken_refs.append(
                        {
                            "page": page.node_id,
                            "reference": raw_value,
                            "field": field,
                            "reason": "unresolved_reference",
                        }
                    )
                    continue
                _add_edge(edges, seen, page.node_id, target, field, origin="frontmatter")

        for raw_link in [*page.wikilinks, *page.internal_links]:
            target = resolve_reference(raw_link, alias_map, page_by_id)
            if target is None:
                broken_refs.append(
                    {
                        "page": page.node_id,
                        "reference": raw_link,
                        "field": "wikilink",
                        "reason": "unresolved_reference",
                    }
                )
                continue
            _add_edge(edges, seen, page.node_id, target, "link", origin="markdown")

    return edges, broken_refs


def _build_adjacency(
    pages: list[WikiPage],
    edges: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, list[str]]], dict[str, list[str]]]:
    adjacency: dict[str, dict[str, list[str]]] = {page.node_id: defaultdict(list) for page in pages}
    backlinks: dict[str, list[str]] = {page.node_id: [] for page in pages}

    for edge in edges:
        adjacency.setdefault(edge["source"], defaultdict(list))[edge["type"]].append(edge["target"])
        backlinks.setdefault(edge["target"], []).append(edge["source"])

    normalized_adjacency: dict[str, dict[str, list[str]]] = {}
    for node_id, edge_map in adjacency.items():
        normalized_adjacency[node_id] = {
            edge_type: sorted(set(targets))
            for edge_type, targets in edge_map.items()
        }
    normalized_backlinks = {node_id: sorted(set(sources)) for node_id, sources in backlinks.items()}
    return normalized_adjacency, normalized_backlinks


def _metrics(
    pages: list[WikiPage],
    edges: list[dict[str, Any]],
    broken_refs: list[dict[str, Any]],
    backlinks: dict[str, list[str]],
) -> dict[str, Any]:
    node_count = len(pages)
    edge_count = len(edges)
    possible_edges = node_count * (node_count - 1) if node_count > 1 else 0
    density = (edge_count / possible_edges) if possible_edges else 0.0
    avg_degree = (edge_count * 2 / node_count) if node_count else 0.0
    orphan_pages = sorted(
        page.node_id
        for page in pages
        if not backlinks.get(page.node_id) and edge_count >= 0 and page.node_id not in {edge["source"] for edge in edges}
    )
    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "average_node_degree": round(avg_degree, 3),
        "graph_density": round(density, 6),
        "orphan_pages": orphan_pages,
        "broken_reference_count": len(broken_refs),
    }


def regenerate_indexes(settings: WikiSettings, pages: list[WikiPage]) -> list[str]:
    created: list[str] = []
    by_type: dict[str, list[WikiPage]] = defaultdict(list)
    by_tag: dict[str, list[WikiPage]] = defaultdict(list)
    by_trust: dict[str, list[WikiPage]] = defaultdict(list)

    for page in pages:
        by_type[page.page_type].append(page)
        by_trust[page.trust_tier].append(page)
        for tag in page.tags:
            by_tag[tag].append(page)

    def _write(path: Path, title: str, groups: dict[str, list[WikiPage]]) -> None:
        lines = [
            "---",
            "type: index",
            f"title: {title}",
            f"node_id: {normalize_text(title).replace(' ', '-')}",
            "aliases: []",
            "tags: []",
            "related: []",
            'parent: ""',
            "children: []",
            "depends_on: []",
            "used_by: []",
            "sources: []",
            "trust_tier: validated",
            "confidence: 1.0",
            "validation_status: current",
            'last_validated_at: ""',
            "validated_by: []",
            "source_count: 0",
            f"updated: {utc_now()}",
            "---",
            "",
            "## One-Line Summary",
            "",
            "Generated routing index derived from canonical wiki metadata.",
            "",
            "## Short Summary",
            "",
            "Use this index to jump to canonical pages without scanning the entire wiki.",
            "",
            "## Details",
            "",
        ]

        for group_name in sorted(groups):
            lines.append(f"### {group_name}")
            lines.append("")
            for page in sorted(groups[group_name], key=lambda item: item.title.lower()):
                rel = page.relative_path
                one_line = page.one_line_summary or page.short_summary or page.title
                lines.append(f"- [{page.title}](../{rel})")
                lines.append(f"  - {one_line}")
            lines.append("")

        lines.extend(
            [
                "## Related Pages",
                "",
                "- [Overview Router](overview.md)",
                "",
                "## Evidence",
                "",
                "- Generated from canonical page metadata.",
                "",
                "## Open Questions",
                "",
                "- None.",
                "",
            ]
        )
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    by_type_path = settings.indexes_root / "by-type.md"
    by_tag_path = settings.indexes_root / "by-tag.md"
    by_trust_path = settings.indexes_root / "by-trust-tier.md"

    _write(by_type_path, "Pages By Type", by_type)
    _write(by_tag_path, "Pages By Tag", by_tag)
    _write(by_trust_path, "Pages By Trust Tier", by_trust)

    created.extend([
        str(by_type_path.relative_to(settings.wiki_root)),
        str(by_tag_path.relative_to(settings.wiki_root)),
        str(by_trust_path.relative_to(settings.wiki_root)),
    ])
    return created


def compile_graph(settings: WikiSettings) -> dict[str, Any]:
    if not settings.enabled or not settings.wiki_root.exists():
        return {
            "generated_at": utc_now(),
            "nodes": [],
            "edges": [],
            "adjacency": {},
            "backlinks": {},
            "aliases": {},
            "topic_routing": {},
            "metrics": {
                "node_count": 0,
                "edge_count": 0,
                "average_node_degree": 0.0,
                "graph_density": 0.0,
                "orphan_pages": [],
                "broken_reference_count": 0,
            },
            "report": {
                "generated_at": utc_now(),
                "nodes": 0,
                "edges": 0,
                "broken_references": [],
                "duplicate_aliases": {},
                "invalid_pages": [],
            },
            "index_files": [],
        }

    pages = discover_pages(settings.wiki_root)
    alias_map, duplicate_aliases, page_by_id = build_lookup_maps(pages)
    edges, broken_refs = _build_edges(pages, alias_map, page_by_id)
    adjacency, backlinks = _build_adjacency(pages, edges)
    nodes = [
        {
            "node_id": page.node_id,
            "title": page.title,
            "type": page.page_type,
            "path": page.relative_path,
            "aliases": page.aliases,
            "tags": page.tags,
            "trust_tier": page.trust_tier,
            "confidence": page.confidence,
            "validation_status": page.metadata.get("validation_status", "pending"),
            "updated": page.updated,
            "one_line_summary": page.one_line_summary,
            "short_summary": page.short_summary,
            "errors": page.errors,
        }
        for page in sorted(pages, key=lambda item: item.node_id)
    ]

    topic_routing = {
        "by_type": {
            page_type: sorted(page.node_id for page in pages if page.page_type == page_type)
            for page_type in sorted({page.page_type for page in pages})
        },
        "by_tag": {
            tag: sorted(page.node_id for page in pages if tag in page.tags)
            for tag in sorted({tag for page in pages for tag in page.tags})
        },
    }

    metrics = _metrics(pages, edges, broken_refs, backlinks)
    report = {
        "generated_at": utc_now(),
        "nodes": len(nodes),
        "edges": len(edges),
        "broken_references": broken_refs,
        "duplicate_aliases": duplicate_aliases,
        "invalid_pages": [page.relative_path for page in pages if page.errors],
    }

    atomic_write_json(settings.graph_root / "nodes.json", nodes)
    atomic_write_json(settings.graph_root / "edges.json", edges)
    atomic_write_json(settings.graph_root / "adjacency.json", adjacency)
    atomic_write_json(settings.graph_root / "backlinks.json", backlinks)
    atomic_write_json(settings.graph_root / "aliases.json", alias_map)
    atomic_write_json(settings.graph_root / "topic_routing.json", topic_routing)
    atomic_write_json(settings.graph_root / "metrics.json", metrics)
    atomic_write_json(settings.graph_root / "compiler_report.json", report)

    index_files = regenerate_indexes(settings, pages)
    return {
        "generated_at": report["generated_at"],
        "nodes": nodes,
        "edges": edges,
        "adjacency": adjacency,
        "backlinks": backlinks,
        "aliases": alias_map,
        "topic_routing": topic_routing,
        "metrics": metrics,
        "report": report,
        "index_files": index_files,
    }
