from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any

from .bootstrap import ensure_layout
from .compression import build_compression_artifacts
from .config import WikiSettings
from .governance import ensure_proposal_layout
from .graph import compile_graph
from .observability import build_lint_report, build_observability_snapshot
from .utils import append_jsonl, utc_now


DERIVED_JSON_PATHS = (
    ("graph", "nodes.json"),
    ("graph", "edges.json"),
    ("graph", "adjacency.json"),
    ("graph", "aliases.json"),
    ("graph", "topic_routing.json"),
    ("compression", "one_line_summaries.json"),
    ("compression", "short_summaries.json"),
    ("compression", "routing_cards.json"),
    ("observability", "latest.json"),
)


def _quarantine(settings: WikiSettings, path: Path) -> str:
    quarantine_root = settings.self_heal_root / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)
    target = quarantine_root / f"{utc_now().replace(':', '').replace('-', '')}__{path.name}"
    shutil.move(str(path), str(target))
    return str(target.relative_to(settings.wiki_root))


def _detect_invalid_json(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return False
    except Exception:
        return True


def run_self_heal(settings: WikiSettings, *, node_root: Path | None = None) -> dict[str, Any]:
    result = {
        "started_at": utc_now(),
        "enabled": settings.enabled,
        "repairs": [],
        "failures": [],
        "quarantined": [],
    }

    try:
        layout = ensure_layout(settings, node_root=node_root, repair=True)
        ensure_proposal_layout(settings)
        result["repairs"].append({"action": "ensure_layout", "detail": layout})
    except Exception as exc:  # pragma: no cover - defensive
        result["failures"].append({"action": "ensure_layout", "error": str(exc)})
        return result

    if not settings.enabled:
        return result

    for folder, name in DERIVED_JSON_PATHS:
        path = settings.meta_root / folder / name
        if _detect_invalid_json(path):
            quarantined = _quarantine(settings, path)
            result["quarantined"].append(quarantined)
            result["repairs"].append({"action": "quarantine_invalid_json", "path": str(path.relative_to(settings.wiki_root))})

    try:
        graph_payload = compile_graph(settings)
        result["repairs"].append({"action": "rebuild_graph", "nodes": graph_payload["metrics"]["node_count"]})
    except Exception as exc:
        result["failures"].append({"action": "rebuild_graph", "error": str(exc)})
        graph_payload = {}

    try:
        build_compression_artifacts(settings, graph_payload=graph_payload if graph_payload else None)
        result["repairs"].append({"action": "rebuild_compression"})
    except Exception as exc:
        result["failures"].append({"action": "rebuild_compression", "error": str(exc)})

    try:
        lint = build_lint_report(settings, graph_payload=graph_payload if graph_payload else None)
        build_observability_snapshot(settings, graph_payload=graph_payload if graph_payload else None, lint_report=lint)
        result["repairs"].append({"action": "rebuild_observability"})
    except Exception as exc:
        result["failures"].append({"action": "rebuild_observability", "error": str(exc)})

    result["finished_at"] = utc_now()
    append_jsonl(settings.self_heal_root / "actions.jsonl", result)
    return result
