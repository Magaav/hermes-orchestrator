from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .config import WikiSettings
from .governance import submit_proposal
from .markdown import discover_pages
from .utils import atomic_write_json, normalize_text, utc_now


LINE_NORMALIZE_RE = re.compile(r"\b\d+\b")
KEEP_CHARS_RE = re.compile(r"[^a-z0-9 _:/.-]+")


def _default_sources() -> list[Path]:
    candidates = [
        Path("/local/logs/nodes"),
        Path("/local/logs/self-evolution"),
        Path("/local/state"),
    ]
    return [path for path in candidates if path.exists()]


def _iter_source_records(path: Path) -> Iterable[tuple[Path, str]]:
    if path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_file():
                yield from _iter_source_records(child)
        return

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".jsonl":
        for raw_line in text.splitlines():
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except Exception:
                continue
            if isinstance(payload, dict):
                for key in ("message", "msg", "error", "text"):
                    value = payload.get(key)
                    if isinstance(value, str):
                        yield path, value
                for part in payload.get("parts", []) or []:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        yield path, part["text"]
        return

    for line in text.splitlines():
        yield path, line


def _normalize_line(line: str) -> str:
    lowered = line.strip().lower()
    lowered = LINE_NORMALIZE_RE.sub("<n>", lowered)
    lowered = KEEP_CHARS_RE.sub(" ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def _title_from_pattern(pattern: str, page_type: str) -> str:
    words = [word for word in pattern.replace("<n>", "").split() if word and word not in {"the", "and", "for", "with"}]
    core = " ".join(words[:8]).strip() or "Durable Pattern"
    prefix = {
        "procedure": "Procedure",
        "incident": "Incident Pattern",
        "concept": "Concept",
    }.get(page_type, "Pattern")
    return f"{prefix}: {core.title()}"


def _page_type_for_pattern(pattern: str) -> str:
    if any(token in pattern for token in ("error", "failed", "timeout", "unreachable", "exception")):
        return "incident"
    if any(token in pattern for token in ("restart", "rebuild", "verify", "run ", "set ", "clear ", "bootstrap")):
        return "procedure"
    return "concept"


def extract_doctrine_candidates(
    settings: WikiSettings,
    *,
    source_paths: list[Path] | None = None,
    stage_proposals: bool = False,
) -> dict[str, Any]:
    if not settings.enabled:
        return {
            "generated_at": utc_now(),
            "candidates_created": [],
            "staged_proposals": [],
            "candidate_count": 0,
            "enabled": False,
        }

    sources = source_paths or _default_sources()
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "files": set(), "examples": []})
    existing_pages = discover_pages(settings.wiki_root) if settings.wiki_root.exists() else []

    for source in sources:
        for line_source, line in _iter_source_records(source):
            normalized = _normalize_line(line)
            if len(normalized) < 24 or len(normalized) > 220:
                continue
            if normalized.count(" ") < 3:
                continue
            bucket = grouped[normalized]
            bucket["count"] += 1
            bucket["files"].add(str(line_source))
            if len(bucket["examples"]) < 3:
                bucket["examples"].append(line.strip())

    created: list[str] = []
    staged: list[str] = []
    candidates: list[dict[str, Any]] = []
    for pattern, payload in sorted(grouped.items(), key=lambda item: (-item[1]["count"], item[0])):
        if payload["count"] < settings.doctrine_min_frequency or len(payload["files"]) < 2:
            continue
        page_type = _page_type_for_pattern(pattern)
        title = _title_from_pattern(pattern, page_type)
        related_existing = [
            page.relative_path
            for page in existing_pages
            if any(token in normalize_text(page.title) for token in normalize_text(title).split())
        ][:5]
        candidate = {
            "candidate_type": f"{page_type}_candidate",
            "suggested_page_type": page_type,
            "suggested_title": title,
            "source_signals": sorted(payload["files"]),
            "reasoning_summary": f"Observed {payload['count']} repeated operational signals across {len(payload['files'])} sources.",
            "related_existing_pages": related_existing,
            "confidence_level": round(min(0.95, 0.45 + payload["count"] * 0.08), 2),
            "frequency_of_occurrence": payload["count"],
            "examples": payload["examples"],
            "timestamp": utc_now(),
        }
        filename = f"{utc_now().replace(':', '').replace('-', '')}__{normalize_text(title).replace(' ', '-')}.json"
        path = settings.doctrine_root / filename
        atomic_write_json(path, candidate)
        created.append(str(path.relative_to(settings.wiki_root)))
        candidates.append(candidate)

        if stage_proposals:
            proposal = submit_proposal(
                settings,
                {
                    "proposal_type": "doctrine_extraction",
                    "page_type": page_type,
                    "title": title,
                    "one_line_summary": payload["examples"][0][:120],
                    "short_summary": candidate["reasoning_summary"],
                    "details": "\n".join(payload["examples"]),
                    "confidence": candidate["confidence_level"],
                    "frequency": payload["count"],
                    "durability_days": 90,
                    "detection_source": "doctrine",
                    "source_signals": sorted(payload["files"]),
                    "related": related_existing,
                },
            )
            staged.append(str(proposal["proposal_id"]))

    return {
        "generated_at": utc_now(),
        "candidates_created": created,
        "staged_proposals": staged,
        "candidate_count": len(candidates),
    }
