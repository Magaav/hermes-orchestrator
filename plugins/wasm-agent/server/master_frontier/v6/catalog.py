"""Searchable V6 capability catalog with pull-on-demand schemas."""
from __future__ import annotations

import re
from typing import Any

from . import contracts


TOKENS = re.compile(r"[a-z0-9]+")


def _field_hint(field: dict[str, Any], *, depth: int = 0) -> str:
    if "default" in field:
        return contracts.canonical(field.get("default"))
    enum = field.get("enum") if isinstance(field.get("enum"), list) else []
    if enum and len(enum) <= 8:
        return "|".join(str(item) for item in enum)
    kind = str(field.get("type") or "value")
    if depth < 2 and kind == "object":
        properties = field.get("properties") if isinstance(field.get("properties"), dict) else {}
        required = {str(item) for item in (field.get("required") or [])}
        inner = ",".join(
            f"{name}{'!' if name in required else '?'}:{_field_hint(raw if isinstance(raw, dict) else {}, depth=depth + 1)}"
            for name, raw in list(properties.items())[:6]
        )
        return "{" + inner + "}"
    if depth < 1 and kind == "array" and isinstance(field.get("items"), dict):
        return "[" + _field_hint(field["items"], depth=depth + 1) + "]"
    return kind


def compact_capability(item: dict[str, Any]) -> dict[str, Any]:
    """Project an executable argument hint without replaying the full schema."""
    schema = item.get("input") if isinstance(item.get("input"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = {str(key) for key in (schema.get("required") or [])}
    arguments = []
    for name, raw in list(properties.items())[:8]:
        field = raw if isinstance(raw, dict) else {}
        value = _field_hint(field)
        arguments.append(f"{name}={value}{'!' if name in required else '?'}")
    summary = str(item.get("summary") or "")
    if arguments:
        summary = f"{summary} args{{{';'.join(arguments)}}}"[:500]
    return {
        **{key: item.get(key) for key in ("id", "kind", "authority", "mode", "detail")},
        "summary": summary,
    }


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
            compact_capability(item)
            for _score, _identifier, item in scored[:max(1, min(int(limit), 64))]
        ]
