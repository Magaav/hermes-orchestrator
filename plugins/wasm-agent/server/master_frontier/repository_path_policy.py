"""Shared text-source eligibility for route-scoped repository mutations."""
from __future__ import annotations

from pathlib import Path


TEXT_SOURCE_SUFFIXES = frozenset({
    ".cjs", ".css", ".html", ".js", ".json", ".jsx", ".md", ".mjs",
    ".py", ".sh", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml",
})


def writable_text_source(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SOURCE_SUFFIXES
