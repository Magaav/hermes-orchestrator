from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import WikiSettings
from .utils import atomic_write_json, copy_if_missing, ensure_directory, ensure_symlink, remove_path, utc_now


REQUIRED_DIRECTORIES = (
    "indexes",
    "global",
    "projects",
    "agents",
    "templates",
    "archive",
    "meta",
    "meta/compression",
    "meta/doctrine_candidates",
    "meta/emergence_reports",
    "meta/graph",
    "meta/health_reports",
    "meta/history",
    "meta/observability",
    "meta/proposals",
    "meta/queues",
    "meta/refactor_reports",
    "meta/self_heal",
)


def _seed_runtime_tree(settings: WikiSettings) -> list[str]:
    seeded: list[str] = []
    if not settings.seed_root.exists():
        return seeded
    for source in sorted(settings.seed_root.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(settings.seed_root)
        target = settings.wiki_root / relative
        if copy_if_missing(source, target):
            seeded.append(str(relative))
    return seeded


def _ensure_runtime_metadata(settings: WikiSettings) -> None:
    state_path = settings.meta_root / "engine_state.json"
    state = {
        "layout_version": 1,
        "plugin_root": str(settings.plugin_root),
        "wiki_root": str(settings.wiki_root),
        "last_bootstrap_at": utc_now(),
    }
    if not state_path.exists():
        state["seeded_at"] = state["last_bootstrap_at"]
    atomic_write_json(state_path, state)


def ensure_node_workspace_link(settings: WikiSettings, node_root: Path) -> bool:
    node_wiki = node_root / "wiki"
    ensure_directory(node_root)
    linked = False
    if node_wiki != settings.wiki_root:
        linked = ensure_symlink(node_wiki, settings.wiki_root)
    # Cleanup legacy location from pre-refactor layouts.
    remove_path(node_root / "workspace" / "wiki")
    return linked


def remove_node_workspace_link(settings: WikiSettings, node_root: Path) -> bool:
    node_wiki = node_root / "wiki"
    removed = False
    if node_wiki != settings.wiki_root:
        removed = remove_path(node_wiki)
    legacy_removed = remove_path(node_root / "workspace" / "wiki")
    return bool(removed or legacy_removed)


def ensure_layout(
    settings: WikiSettings,
    *,
    node_root: Path | None = None,
    repair: bool = False,
) -> dict[str, Any]:
    actions: dict[str, Any] = {
        "enabled": settings.enabled,
        "repair": repair,
        "wiki_root": str(settings.wiki_root),
        "created_directories": [],
        "seeded_files": [],
        "node_wiki_linked": False,
        "node_wiki_unlinked": False,
        "workspace_linked": False,
        "workspace_unlinked": False,
    }

    if not settings.enabled:
        if node_root is not None:
            unlinked = remove_node_workspace_link(settings, node_root)
            actions["node_wiki_unlinked"] = unlinked
            actions["workspace_unlinked"] = unlinked
        return actions

    ensure_directory(settings.wiki_root)
    for relative in REQUIRED_DIRECTORIES:
        path = settings.wiki_root / relative
        if not path.exists():
            actions["created_directories"].append(relative)
        ensure_directory(path)

    actions["seeded_files"] = _seed_runtime_tree(settings)
    _ensure_runtime_metadata(settings)

    if node_root is not None:
        linked = ensure_node_workspace_link(settings, node_root)
        actions["node_wiki_linked"] = linked
        actions["workspace_linked"] = linked

    return actions
