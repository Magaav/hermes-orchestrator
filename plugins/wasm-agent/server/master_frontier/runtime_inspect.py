"""Owned kernel.inspect adapter for bounded runtime actions and summaries."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import runtime_actions


def action_registration(contract: dict[str, Any]) -> list[dict[str, Any]]:
    capabilities = set(contract.get("caps") or [])
    return runtime_actions.action_schemas() if "runtime.inspect" in capabilities else []


def execute_requested_action(
    request: Any,
    *,
    contract: dict[str, Any],
    user_id: str,
    db_path: Path,
    now_ms: int,
) -> dict[str, Any] | None:
    if request is None:
        return None
    if not isinstance(request, dict) or set(request) != {"name", "arguments"}:
        return {"ok": False, "code": "runtime_action_request_invalid"}
    authority = {
        "user_id": user_id,
        "route_id": str(contract.get("route_id") or ""),
        "capabilities": contract.get("caps") if isinstance(contract.get("caps"), list) else [],
        "entities": contract.get("entities") if isinstance(contract.get("entities"), list) else [],
        "max_age_ms": 30_000,
    }
    try:
        return runtime_actions.execute(
            str(request.get("name") or ""),
            request.get("arguments"),
            authority=authority,
            db_path=db_path,
            now_ms=now_ms,
        )
    except runtime_actions.ActionError as exc:
        return {"ok": False, "code": exc.code}


def compact_summary(result: dict[str, Any]) -> dict[str, Any]:
    investigation = result.get("investigation") if isinstance(result.get("investigation"), dict) else {}
    return {
        "route_id": result.get("route_id"),
        "entity": result.get("entity"),
        "route_identity": result.get("route_identity") if isinstance(result.get("route_identity"), dict) else {},
        "entity_match_count": result.get("entity_match_count"),
        "investigation": {
            "inferred_identity": investigation.get("inferred_identity") if isinstance(investigation.get("inferred_identity"), list) else [],
            "roots": [
                {
                    "root": root.get("root"),
                    "file_count": root.get("file_count"),
                    "kind_counts": root.get("kind_counts") if isinstance(root.get("kind_counts"), dict) else {},
                    "top_dirs": root.get("top_dirs") if isinstance(root.get("top_dirs"), dict) else {},
                }
                for root in (investigation.get("roots") if isinstance(investigation.get("roots"), list) else [])[:4]
                if isinstance(root, dict)
            ],
            "conversations": investigation.get("conversations") if isinstance(investigation.get("conversations"), dict) else {},
            "data_assets": investigation.get("data_assets") if isinstance(investigation.get("data_assets"), dict) else {},
            "documents": [
                {"path": doc.get("path"), "excerpt": str(doc.get("excerpt") or "")[:220]}
                for doc in (investigation.get("documents") if isinstance(investigation.get("documents"), list) else [])[:6]
                if isinstance(doc, dict)
            ],
            "databases": [
                {
                    "path": db.get("path"),
                    "tables": db.get("tables") if isinstance(db.get("tables"), dict) else {},
                    "semantic_tables": [
                        {
                            "table": table.get("table"),
                            "count": table.get("count"),
                            "samples": table.get("samples") if isinstance(table.get("samples"), list) else [],
                        }
                        for table in (db.get("semantic_tables") if isinstance(db.get("semantic_tables"), list) else [])[:4]
                        if isinstance(table, dict)
                    ],
                }
                for db in (investigation.get("databases") if isinstance(investigation.get("databases"), list) else [])[:5]
                if isinstance(db, dict)
            ],
        },
        "metadata_files": [
            {
                "path": meta.get("path"),
                "bytes": meta.get("bytes"),
                "json": {
                    key: meta.get("json", {}).get(key)
                    for key in ("bootstrapped_at", "reseeded_at", "state_code", "node_role", "timezone")
                    if isinstance(meta.get("json"), dict) and meta.get("json", {}).get(key) not in (None, "")
                },
            }
            for meta in (result.get("metadata_files") if isinstance(result.get("metadata_files"), list) else [])[:6]
            if isinstance(meta, dict)
        ],
        "data_roots": [
            {
                "root": root.get("root"),
                "file_count": root.get("file_count"),
                "files": [
                    {
                        "path": item.get("path"),
                        "bytes": item.get("bytes"),
                        "sqlite_tables": item.get("sqlite_tables") if isinstance(item.get("sqlite_tables"), dict) else {},
                    }
                    for item in (root.get("files") if isinstance(root.get("files"), list) else [])[:8]
                    if isinstance(item, dict)
                ],
            }
            for root in (result.get("data_roots") if isinstance(result.get("data_roots"), list) else [])[:4]
            if isinstance(root, dict)
        ],
    }
