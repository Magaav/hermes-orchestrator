from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .utils import normalize_text, slugify

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional fallback
    yaml = None


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
INLINE_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+\.md(?:#[^)]+)?)\)")

RELATION_FIELDS = (
    "related",
    "parent",
    "children",
    "depends_on",
    "used_by",
    "sources",
    "caused_by",
    "owned_by",
    "decision_for",
    "incident_of",
)

METADATA_ORDER = (
    "type",
    "title",
    "node_id",
    "aliases",
    "tags",
    "related",
    "parent",
    "children",
    "depends_on",
    "used_by",
    "caused_by",
    "owned_by",
    "decision_for",
    "incident_of",
    "sources",
    "trust_tier",
    "confidence",
    "validation_status",
    "last_validated_at",
    "validated_by",
    "source_count",
    "updated",
)

SECTION_TITLES = {
    "one line summary": "one_line_summary",
    "short summary": "short_summary",
    "details": "details",
    "related pages": "related_pages",
    "evidence": "evidence",
    "open questions": "open_questions",
}

SECTION_ORDER = (
    "one_line_summary",
    "short_summary",
    "details",
    "related_pages",
    "evidence",
    "open_questions",
)


@dataclass
class WikiPage:
    path: Path
    relative_path: str
    node_id: str
    page_type: str
    title: str
    metadata: dict[str, Any]
    sections: dict[str, str]
    wikilinks: list[str]
    internal_links: list[str]
    aliases: list[str]
    tags: list[str]
    trust_tier: str
    confidence: float
    updated: str
    errors: list[str]

    @property
    def one_line_summary(self) -> str:
        return str(self.sections.get("one_line_summary", "") or "").strip()

    @property
    def short_summary(self) -> str:
        return str(self.sections.get("short_summary", "") or "").strip()


def _fallback_parse_frontmatter(raw: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value in {"[]", ""}:
            data[key] = [] if value == "[]" else ""
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                data[key] = []
            else:
                data[key] = [part.strip().strip("'\"") for part in inner.split(",") if part.strip()]
            continue
        lowered = value.lower()
        if lowered in {"true", "false"}:
            data[key] = lowered == "true"
            continue
        try:
            data[key] = int(value)
            continue
        except ValueError:
            pass
        try:
            data[key] = float(value)
            continue
        except ValueError:
            pass
        data[key] = value.strip("'\"")
    return data


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    body = text[match.end() :]
    if yaml is not None:
        try:
            parsed = yaml.safe_load(raw) or {}
            if isinstance(parsed, dict):
                return parsed, body
        except Exception:
            pass
    return _fallback_parse_frontmatter(raw), body


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_float(value: Any, default: float = 0.5) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_key = ""
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer, current_key
        if current_key:
            sections[current_key] = "\n".join(buffer).strip()
        buffer = []

    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            flush()
            heading = normalize_text(line[3:])
            current_key = SECTION_TITLES.get(heading, slugify(heading).replace("-", "_"))
            continue
        if current_key:
            buffer.append(line)

    flush()
    return sections


def _first_paragraph(body: str) -> str:
    current: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                break
            continue
        if line.startswith("#"):
            continue
        current.append(line)
    return " ".join(current).strip()


def normalize_reference(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("[[") and raw.endswith("]]"):
        raw = raw[2:-2]
    if "|" in raw:
        raw = raw.split("|", 1)[0]
    if "#" in raw:
        raw = raw.split("#", 1)[0]
    raw = raw.strip()
    if raw.endswith(".md"):
        raw = raw[:-3]
    raw = raw.lstrip("./")
    return raw.strip()


def parse_page(path: Path, wiki_root: Path) -> WikiPage:
    text = path.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(text)
    if not isinstance(metadata, dict):
        metadata = {}

    relative_path = str(path.relative_to(wiki_root))
    title = _as_str(metadata.get("title")) or path.stem.replace("-", " ").replace("_", " ").title()
    node_id = _as_str(metadata.get("node_id")) or slugify(relative_path.replace(".md", "").replace("/", "-"))
    page_type = _as_str(metadata.get("type")) or ("index" if "indexes/" in relative_path or relative_path == "index.md" else "concept")
    aliases = _as_list(metadata.get("aliases"))
    tags = _as_list(metadata.get("tags"))
    trust_tier = _as_str(metadata.get("trust_tier")) or "provisional"
    confidence = _as_float(metadata.get("confidence"), 0.5)
    updated = _as_str(metadata.get("updated"))
    sections = _extract_sections(body)

    first_paragraph = _first_paragraph(body)
    if not sections.get("one_line_summary"):
        sections["one_line_summary"] = first_paragraph.split(". ", 1)[0].strip()
    if not sections.get("short_summary"):
        sections["short_summary"] = first_paragraph

    wikilinks = [normalize_reference(match) for match in WIKILINK_RE.findall(body)]
    internal_links = [normalize_reference(match) for match in INLINE_LINK_RE.findall(body)]

    errors: list[str] = []
    if not metadata:
        errors.append("missing_frontmatter")
    for required in ("type", "title", "trust_tier", "confidence", "validation_status", "updated"):
        if required not in metadata:
            errors.append(f"missing_metadata:{required}")

    normalized: dict[str, Any] = dict(metadata)
    normalized["type"] = page_type
    normalized["title"] = title
    normalized["node_id"] = node_id
    normalized["aliases"] = aliases
    normalized["tags"] = tags
    normalized["trust_tier"] = trust_tier
    normalized["confidence"] = confidence
    normalized["updated"] = updated
    normalized["parent"] = _as_str(metadata.get("parent"))
    normalized["validated_by"] = _as_list(metadata.get("validated_by"))
    normalized["source_count"] = int(metadata.get("source_count", 0) or 0)
    for field in RELATION_FIELDS:
        if field == "parent":
            continue
        normalized[field] = _as_list(metadata.get(field))

    return WikiPage(
        path=path,
        relative_path=relative_path,
        node_id=node_id,
        page_type=page_type,
        title=title,
        metadata=normalized,
        sections=sections,
        wikilinks=[item for item in wikilinks if item],
        internal_links=[item for item in internal_links if item],
        aliases=aliases,
        tags=tags,
        trust_tier=trust_tier,
        confidence=confidence,
        updated=updated,
        errors=errors,
    )


def discover_pages(wiki_root: Path, *, include_archive: bool = False) -> list[WikiPage]:
    pages: list[WikiPage] = []
    candidates: list[Path] = []
    root_index = wiki_root / "index.md"
    if root_index.exists():
        candidates.append(root_index)

    for name in ("indexes", "global", "projects", "agents"):
        root = wiki_root / name
        if root.exists():
            candidates.extend(sorted(root.rglob("*.md")))

    if include_archive:
        archive_root = wiki_root / "archive"
        if archive_root.exists():
            candidates.extend(sorted(archive_root.rglob("*.md")))

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen or "templates" in candidate.parts or "meta" in candidate.parts:
            continue
        seen.add(key)
        pages.append(parse_page(candidate, wiki_root))
    return pages


def _dump_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value or "")
    if not text:
        return '""'
    if any(char in text for char in ('"', ":", "#", "[", "]", "{", "}", ",")):
        return json.dumps(text)
    return text


def dump_frontmatter(metadata: dict[str, Any]) -> str:
    lines = ["---"]
    seen: set[str] = set()
    ordered_keys = list(METADATA_ORDER) + sorted(key for key in metadata if key not in METADATA_ORDER)

    for key in ordered_keys:
        if key in seen or key not in metadata:
            continue
        seen.add(key)
        value = metadata[key]
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {_dump_scalar(item)}")
            continue
        lines.append(f"{key}: {_dump_scalar(value)}")

    lines.append("---")
    return "\n".join(lines)


def render_page(metadata: dict[str, Any], sections: dict[str, str]) -> str:
    lines = [dump_frontmatter(metadata), ""]
    for key in SECTION_ORDER:
        heading = key.replace("_", " ").title()
        lines.append(f"## {heading}")
        lines.append("")
        content = str(sections.get(key, "") or "").rstrip()
        if content:
            lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def merge_unique(existing: list[str], new_values: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for value in [*existing, *new_values]:
        normalized = normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(str(value).strip())
    return merged
