from __future__ import annotations

from typing import Any

from .config import WikiSettings
from .markdown import WikiPage, discover_pages
from .utils import atomic_write_json, utc_now


def estimate_tokens(text: str) -> int:
    words = len(str(text or "").split())
    return max(1, int(words * 1.3))


def build_compression_artifacts(
    settings: WikiSettings,
    *,
    pages: list[WikiPage] | None = None,
    graph_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not settings.enabled or not settings.wiki_root.exists():
        return {
            "generated_at": utc_now(),
            "one_line_count": 0,
            "short_count": 0,
            "routing_cards": 0,
            "enabled": False,
        }

    page_list = pages or discover_pages(settings.wiki_root)
    graph_data = graph_payload or {}

    one_line = {
        page.node_id: {
            "title": page.title,
            "path": page.relative_path,
            "trust_tier": page.trust_tier,
            "summary": page.one_line_summary,
            "estimated_tokens": estimate_tokens(page.one_line_summary),
        }
        for page in page_list
    }

    short = {
        page.node_id: {
            "title": page.title,
            "path": page.relative_path,
            "trust_tier": page.trust_tier,
            "summary": page.short_summary,
            "estimated_tokens": estimate_tokens(page.short_summary),
        }
        for page in page_list
    }

    routing_cards = {
        page.node_id: {
            "title": page.title,
            "type": page.page_type,
            "path": page.relative_path,
            "aliases": page.aliases,
            "tags": page.tags,
            "trust_tier": page.trust_tier,
            "confidence": page.confidence,
            "one_line_summary": page.one_line_summary,
            "short_summary": page.short_summary,
            "neighbors": sorted(
                {
                    target
                    for targets in (graph_data.get("adjacency", {}) or {}).get(page.node_id, {}).values()
                    for target in targets
                }
            ),
        }
        for page in page_list
    }

    index_summary_map = {
        "generated_at": utc_now(),
        "index_paths": sorted(str(path) for path in (graph_data.get("index_files") or [])),
        "page_count": len(page_list),
    }

    atomic_write_json(settings.compression_root / "one_line_summaries.json", one_line)
    atomic_write_json(settings.compression_root / "short_summaries.json", short)
    atomic_write_json(settings.compression_root / "routing_cards.json", routing_cards)
    atomic_write_json(settings.compression_root / "index_summary_map.json", index_summary_map)

    return {
        "generated_at": index_summary_map["generated_at"],
        "one_line_count": len(one_line),
        "short_count": len(short),
        "routing_cards": len(routing_cards),
    }
