"""Searchable V6 capability catalog with pull-on-demand schemas."""
from __future__ import annotations

import re
from typing import Any

from . import contracts


TOKENS = re.compile(r"[a-z0-9]+")


class Catalog:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def register(self, value: dict[str, Any]) -> dict[str, Any]:
        item = contracts.capability(value)
        existing = self._items.get(item["id"])
        if existing is not None and contracts.canonical(existing) != contracts.canonical(item):
            raise contracts.ContractError("capability_redefinition")
        self._items[item["id"]] = item
        return dict(item)

    def get(self, capability_id: str) -> dict[str, Any] | None:
        item = self._items.get(str(capability_id))
        return dict(item) if item else None

    def all(self) -> dict[str, dict[str, Any]]:
        return {key: dict(value) for key, value in self._items.items()}

    def search(self, query: str, *, limit: int = 12) -> list[dict[str, Any]]:
        terms = set(TOKENS.findall(str(query).lower()))
        scored = []
        for item in self._items.values():
            identifier = set(TOKENS.findall(item["id"].lower()))
            summary = set(TOKENS.findall(str(item.get("summary") or "").lower()))
            authority = set(TOKENS.findall(str(item.get("authority") or "").lower()))
            score = 4 * len(terms & identifier) + 2 * len(terms & summary) + len(terms & authority)
            if not terms or score:
                scored.append((score, item["id"], item))
        scored.sort(key=lambda row: (-row[0], row[1]))
        return [
            {key: item.get(key) for key in ("id", "kind", "authority", "mode", "summary", "detail")}
            for _score, _identifier, item in scored[:max(1, min(int(limit), 64))]
        ]
