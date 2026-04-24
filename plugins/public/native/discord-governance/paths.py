"""Path helpers for the native Discord governance plugin."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_private_discord_root() -> Path:
    configured = str(os.getenv("HERMES_DISCORD_PRIVATE_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path("/local/plugins/private/discord")


def resolve_acl_path(node_name: str | None = None) -> Path:
    node = str(node_name or os.getenv("NODE_NAME", "") or "orchestrator").strip().lower()
    if node.endswith(".json"):
        node = node[:-5]
    node = node or "orchestrator"
    return resolve_private_discord_root() / "acl" / f"{node}_acl.json"


def resolve_channel_acl_config_path() -> Path:
    return resolve_private_discord_root() / "hooks" / "channel_acl" / "config.yaml"


def resolve_models_path(node_name: str | None = None) -> Path:
    node = str(node_name or os.getenv("NODE_NAME", "") or "orchestrator").strip().lower()
    if node.endswith(".json"):
        node = node[:-5]
    node = node or "orchestrator"
    return resolve_private_discord_root() / "models" / f"{node}_models.json"


def resolve_legacy_role_acl_path() -> Path:
    return Path("/local/plugins/public/discord/hooks/discord_slash_bridge/role_acl.py")


def resolve_legacy_slash_handlers_path() -> Path:
    return Path("/local/plugins/public/discord/hooks/discord_slash_bridge/handlers.py")


def resolve_legacy_channel_acl_path() -> Path:
    return Path("/local/plugins/public/discord/hooks/channel_acl/handler.py")
