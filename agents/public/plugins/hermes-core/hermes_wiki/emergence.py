from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .config import WikiSettings
from .governance import submit_proposal
from .markdown import discover_pages
from .utils import atomic_write_json, normalize_text, utc_now


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "when",
    "page",
    "pages",
    "wiki",
    "router",
    "overview",
}


def discover_emergent_concepts(
    settings: WikiSettings,
    *,
    stage_proposals: bool = False,
) -> dict[str, Any]:
    if not settings.enabled:
        return {
            "generated_at": utc_now(),
            "candidate_count": 0,
            "candidate_paths": [],
            "staged_proposals": [],
            "enabled": False,
        }

    pages = discover_pages(settings.wiki_root)
    existing_titles = {normalize_text(page.title) for page in pages}
    term_counts: Counter[str] = Counter()
    term_pages: dict[str, set[str]] = defaultdict(set)
    tag_counts: Counter[str] = Counter()

    for page in pages:
        tokens = set(normalize_text(page.title).split())
        tokens.update(normalize_text(page.one_line_summary).split())
        for token in tokens:
            if len(token) < 4 or token in STOPWORDS or token in existing_titles:
                continue
            term_counts[token] += 1
            term_pages[token].add(page.relative_path)
        for tag in page.tags:
            normalized = normalize_text(tag)
            if normalized:
                tag_counts[normalized] += 1
                term_pages[normalized].add(page.relative_path)

    candidates: list[dict[str, Any]] = []
    staged: list[str] = []

    for term, count in sorted(term_counts.items(), key=lambda item: (-item[1], item[0])):
        if count < settings.ecd_min_frequency or len(term_pages[term]) < 2:
            continue
        candidate_type = "new_concept_candidate"
        candidate = {
            "candidate_type": candidate_type,
            "suggested_title": f"Concept: {term.title()}",
            "reasoning_summary": f"Term '{term}' appears across {count} durable page summaries but has no canonical page title yet.",
            "related_existing_pages": sorted(term_pages[term]),
            "confidence_level": round(min(0.9, 0.4 + count * 0.1), 2),
            "frequency_of_occurrence": count,
            "timestamp": utc_now(),
        }
        candidates.append(candidate)

    for tag, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0])):
        if count < settings.ecd_min_frequency:
            continue
        candidates.append(
            {
                "candidate_type": "new_topical_index_candidate",
                "suggested_title": f"Index: {tag.title()}",
                "reasoning_summary": f"Tag '{tag}' spans {count} pages and may deserve its own compact topical router.",
                "related_existing_pages": sorted(term_pages[tag]),
                "confidence_level": round(min(0.9, 0.45 + count * 0.08), 2),
                "frequency_of_occurrence": count,
                "timestamp": utc_now(),
            }
        )

    created: list[str] = []
    for candidate in candidates:
        filename = f"{utc_now().replace(':', '').replace('-', '')}__{normalize_text(candidate['suggested_title']).replace(' ', '-')}.json"
        path = settings.emergence_root / filename
        atomic_write_json(path, candidate)
        created.append(str(path.relative_to(settings.wiki_root)))

        if stage_proposals:
            proposal = submit_proposal(
                settings,
                {
                    "proposal_type": candidate["candidate_type"],
                    "page_type": "concept" if "concept" in candidate["candidate_type"] else "index",
                    "title": candidate["suggested_title"].split(": ", 1)[-1],
                    "short_summary": candidate["reasoning_summary"],
                    "details": candidate["reasoning_summary"],
                    "confidence": candidate["confidence_level"],
                    "frequency": candidate["frequency_of_occurrence"],
                    "durability_days": 90,
                    "detection_source": "ecd",
                    "related": candidate["related_existing_pages"],
                },
            )
            staged.append(str(proposal["proposal_id"]))

    return {
        "generated_at": utc_now(),
        "candidate_count": len(candidates),
        "candidate_paths": created,
        "staged_proposals": staged,
    }
