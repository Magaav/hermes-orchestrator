"""Shared catalog and cache helpers for the canonical Discord slash plugin."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

import yaml

try:
    from .paths import (
        plugin_root,
        resolve_app_scope_file,
        resolve_custom_catalog_file,
        resolve_governance_acl_file,
        resolve_governance_channel_acl_file,
        resolve_governance_compat_acl_file,
        resolve_governance_compat_channel_acl_file,
        resolve_governance_compat_models_file,
        resolve_governance_models_file,
        resolve_governance_root,
        resolve_governance_users_file,
        resolve_migration_file,
        resolve_node_activation_file,
        resolve_status_active_model_file,
        runtime_node_name,
    )
except ImportError:  # pragma: no cover - script entrypoints import this module standalone
    from paths import (  # type: ignore
        plugin_root,
        resolve_app_scope_file,
        resolve_custom_catalog_file,
        resolve_governance_acl_file,
        resolve_governance_channel_acl_file,
        resolve_governance_compat_acl_file,
        resolve_governance_compat_channel_acl_file,
        resolve_governance_compat_models_file,
        resolve_governance_models_file,
        resolve_governance_root,
        resolve_governance_users_file,
        resolve_migration_file,
        resolve_node_activation_file,
        resolve_status_active_model_file,
        runtime_node_name,
    )


SUPPORTED_CUSTOM_COMMANDS = {"faltas", "metricas"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or default
    except Exception:
        return default


def _write_yaml(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _manifest_path(*parts: str) -> Path:
    return plugin_root() / "manifests" / Path(*parts)


def load_global_commands() -> list[dict[str, Any]]:
    payload = _read_yaml(_manifest_path("global_commands.yaml"), {}) or {}
    commands = payload.get("commands") if isinstance(payload, dict) else []
    if not isinstance(commands, list):
        return []
    return [dict(item) for item in commands if isinstance(item, dict)]


def load_custom_seed_commands() -> list[dict[str, Any]]:
    payload = _read_json(_manifest_path("custom_commands.json"), [])
    if not isinstance(payload, list):
        return []
    commands = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        if name and name in SUPPORTED_CUSTOM_COMMANDS:
            commands.append(dict(item))
    return commands


def _command_map(commands: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in commands:
        name = str(item.get("name") or "").strip().lower()
        if name:
            result[name] = dict(item)
    return result


def seed_custom_catalog(*, legacy_payload: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    seed_map = _command_map(load_custom_seed_commands())
    legacy_map = _command_map(legacy_payload or [])
    result: list[dict[str, Any]] = []
    for name, entry in seed_map.items():
        merged = dict(entry)
        legacy = legacy_map.get(name)
        if isinstance(legacy, dict):
            for key in (
                "description",
                "default_member_permissions",
                "dm_permission",
                "options",
            ):
                if legacy.get(key) is not None:
                    merged[key] = legacy.get(key)
        result.append(merged)
    return result


def _hydrate_existing_custom_catalog(commands: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    seed_map = _command_map(load_custom_seed_commands())
    hydrated: list[dict[str, Any]] = []
    changed = False
    seen: set[str] = set()

    for item in commands:
        if not isinstance(item, dict):
            changed = True
            continue
        name = str(item.get("name") or "").strip().lower()
        if not name:
            changed = True
            continue
        merged = dict(seed_map.get(name, {}))
        merged.update(dict(item))
        if not str(merged.get("namespace") or "").strip():
            merged["namespace"] = "custom"
        hydrated.append(merged)
        seen.add(name)
        if merged != item:
            changed = True

    for command in load_custom_seed_commands():
        name = str(command.get("name") or "").strip().lower()
        if name and name not in seen:
            hydrated.append(dict(command))
            changed = True

    return hydrated, changed


def ensure_custom_catalog(*, legacy_payload: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    path = resolve_custom_catalog_file()
    payload = _read_json(path, None)
    if isinstance(payload, list) and payload:
        hydrated, changed = _hydrate_existing_custom_catalog([dict(item) for item in payload if isinstance(item, dict)])
        if changed:
            _write_json(path, hydrated)
        return hydrated
    seeded = seed_custom_catalog(legacy_payload=legacy_payload)
    _write_json(path, seeded)
    return seeded


def load_custom_commands() -> list[dict[str, Any]]:
    return ensure_custom_catalog()


def load_all_commands() -> list[dict[str, Any]]:
    return load_global_commands() + load_custom_commands()


def get_command_definition(name: str) -> dict[str, Any]:
    clean = str(name or "").strip().lower().lstrip("/")
    for item in load_all_commands():
        if str(item.get("name") or "").strip().lower() == clean:
            return dict(item)
    return {}


def load_node_activation() -> dict[str, Any]:
    payload = _read_json(resolve_node_activation_file(), {})
    return payload if isinstance(payload, dict) else {}


def write_node_activation(payload: dict[str, Any]) -> None:
    _write_json(resolve_node_activation_file(), payload)


def load_active_model_state() -> dict[str, Any]:
    payload = _read_json(resolve_status_active_model_file(), {})
    if not isinstance(payload, dict):
        return {}

    model = str(payload.get("model") or "").strip()
    provider = str(payload.get("provider") or "").strip()
    if not model or not provider:
        return {}

    result: dict[str, Any] = {
        "model": model,
        "provider": provider,
    }
    for key in ("base_url", "api_mode", "updated_at", "updated_by_node", "node"):
        value = str(payload.get(key) or "").strip()
        if value:
            result[key] = value
    return result


def write_active_model_state(
    *,
    model: str,
    provider: str,
    base_url: str = "",
    api_mode: str = "",
    updated_by_node: str | None = None,
) -> dict[str, Any]:
    payload = {
        "version": 1,
        "node": runtime_node_name(),
        "model": str(model or "").strip(),
        "provider": str(provider or "").strip(),
        "base_url": str(base_url or "").strip(),
        "api_mode": str(api_mode or "").strip(),
        "updated_at": utc_now(),
        "updated_by_node": str(updated_by_node or runtime_node_name() or "").strip() or runtime_node_name(),
    }
    _write_json(resolve_status_active_model_file(), payload)
    return payload


def _default_scope_payload() -> dict[str, Any]:
    enabled = _default_enabled_global_commands()
    enabled.add("slash")
    return {
        "version": 1,
        "app_id": str(os.getenv("DISCORD_APP_ID", "") or "").strip(),
        "guild_id": str(os.getenv("DISCORD_SERVER_ID", "") or os.getenv("DISCORD_GUILD_ID", "") or "").strip(),
        "enabled_commands": sorted(enabled),
        "updated_at": utc_now(),
        "updated_by_node": runtime_node_name(),
    }


def _default_enabled_global_commands() -> set[str]:
    return {
        str(item.get("name") or "").strip().lower()
        for item in load_global_commands()
        if str(item.get("name") or "").strip() and bool(item.get("default_enabled", True))
    }


def _governance_required_commands() -> set[str]:
    payload = _read_yaml(resolve_governance_channel_acl_file(), {}) or {}
    channels = payload.get("channels") if isinstance(payload, dict) else {}
    if not isinstance(channels, dict) or not channels:
        return set()

    known_commands = {
        str(item.get("name") or "").strip().lower()
        for item in load_all_commands()
        if str(item.get("name") or "").strip()
    }
    required: set[str] = set()

    for cfg in channels.values():
        if not isinstance(cfg, dict):
            continue
        for item in cfg.get("allowed_commands") or []:
            name = str(item or "").strip().lower().lstrip("/")
            if name and name in known_commands:
                required.add(name)
        default_action = str(cfg.get("default_action") or "").strip().lower()
        if default_action.startswith("command:"):
            name = default_action.split(":", 1)[1].strip().lstrip("/")
            if name and name in known_commands:
                required.add(name)

    return required


def _node_activation_custom_commands() -> set[str]:
    payload = load_node_activation()
    if not isinstance(payload, dict):
        return set()
    return {
        str(item).strip().lower()
        for item in payload.get("custom_enabled") or []
        if str(item).strip().lower() in SUPPORTED_CUSTOM_COMMANDS
    }


def _hydrate_scope_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    scope = dict(payload or {})
    current = {
        str(item).strip().lower()
        for item in scope.get("enabled_commands") or []
        if str(item).strip()
    }
    disabled = {
        str(item).strip().lower()
        for item in scope.get("disabled_commands") or []
        if str(item).strip()
    }
    required = (
        current
        | (_default_enabled_global_commands() - disabled)
        | _governance_required_commands()
        | _node_activation_custom_commands()
        | {"slash"}
    )
    normalized = sorted(required)
    changed = normalized != list(scope.get("enabled_commands") or [])
    if changed:
        scope["enabled_commands"] = normalized
        scope["updated_at"] = utc_now()
        scope["updated_by_node"] = str(scope.get("updated_by_node") or runtime_node_name()).strip() or runtime_node_name()
    return scope, changed


def load_app_scope() -> dict[str, Any]:
    payload = _read_json(resolve_app_scope_file(), None)
    if isinstance(payload, dict) and payload:
        hydrated, changed = _hydrate_scope_payload(payload)
        if changed:
            _write_json(resolve_app_scope_file(), hydrated)
        return hydrated
    payload = _default_scope_payload()
    hydrated, _changed = _hydrate_scope_payload(payload)
    _write_json(resolve_app_scope_file(), hydrated)
    return hydrated


def write_app_scope(payload: dict[str, Any]) -> None:
    _write_json(resolve_app_scope_file(), payload)


def is_command_enabled(name: str) -> bool:
    clean = str(name or "").strip().lower().lstrip("/")
    if clean == "slash":
        return True
    enabled = {
        str(item).strip().lower()
        for item in load_app_scope().get("enabled_commands") or []
        if str(item).strip()
    }
    return clean in enabled


def set_command_enabled(name: str, enabled: bool, *, node_name: str | None = None) -> dict[str, Any]:
    clean = str(name or "").strip().lower().lstrip("/")
    if clean == "slash":
        return load_app_scope()

    scope = load_app_scope()
    current = {
        str(item).strip().lower()
        for item in scope.get("enabled_commands") or []
        if str(item).strip()
    }
    if enabled:
        current.add(clean)
        disabled = {
            str(item).strip().lower()
            for item in scope.get("disabled_commands") or []
            if str(item).strip().lower() != clean
        }
    else:
        current.discard(clean)
        disabled = {
            str(item).strip().lower()
            for item in scope.get("disabled_commands") or []
            if str(item).strip()
        }
        disabled.add(clean)
    current.add("slash")
    scope["enabled_commands"] = sorted(current)
    scope["disabled_commands"] = sorted(disabled)
    scope["updated_at"] = utc_now()
    scope["updated_by_node"] = str(node_name or runtime_node_name() or "").strip() or runtime_node_name()
    write_app_scope(scope)
    return scope


def list_commands_for_display() -> list[dict[str, Any]]:
    enabled = {
        str(item).strip().lower()
        for item in load_app_scope().get("enabled_commands") or []
        if str(item).strip()
    }
    rows: list[dict[str, Any]] = []
    for command in load_all_commands():
        row = dict(command)
        name = str(command.get("name") or "").strip().lower()
        row["enabled"] = True if name == "slash" else name in enabled
        row["installed"] = row["enabled"]
        rows.append(row)
    rows.sort(key=lambda item: (str(item.get("namespace") or ""), str(item.get("name") or "")))
    return rows


def ensure_governance_compat_layout() -> None:
    governance_root = resolve_governance_root()
    governance_root.mkdir(parents=True, exist_ok=True)

    compat_links = {
        resolve_governance_compat_acl_file(): Path("..") / "acl.json",
        resolve_governance_compat_models_file(): Path("..") / "models.json",
        resolve_governance_compat_channel_acl_file(): Path("..") / ".." / "channel_acl.yaml",
    }
    for link_path, target in compat_links.items():
        link_path.parent.mkdir(parents=True, exist_ok=True)
        if link_path.exists() or link_path.is_symlink():
            if link_path.is_symlink():
                try:
                    if Path(os.readlink(link_path)) == target:
                        continue
                except OSError:
                    pass
            else:
                link_path.unlink()
        try:
            os.symlink(target, link_path)
        except FileExistsError:
            pass


def ensure_governance_files(
    *,
    acl_payload: dict[str, Any],
    models_payload: dict[str, Any],
    channel_acl_payload: dict[str, Any],
    users_payload: dict[str, Any],
) -> None:
    if not resolve_governance_acl_file().exists():
        _write_json(resolve_governance_acl_file(), acl_payload)
    if not resolve_governance_models_file().exists():
        _write_json(resolve_governance_models_file(), models_payload)
    if not resolve_governance_channel_acl_file().exists():
        _write_yaml(resolve_governance_channel_acl_file(), channel_acl_payload)
    if not resolve_governance_users_file().exists():
        _write_json(resolve_governance_users_file(), users_payload)
    ensure_governance_compat_layout()


def write_migration(payload: dict[str, Any]) -> None:
    _write_json(resolve_migration_file(), payload)


def load_migration() -> dict[str, Any]:
    payload = _read_json(resolve_migration_file(), {})
    return payload if isinstance(payload, dict) else {}


def mark_migrated(*, node_name: str, source_paths: dict[str, str], enabled_custom: list[str]) -> dict[str, Any]:
    payload = {
        "version": 1,
        "migrated_at": utc_now(),
        "migrated_node": node_name,
        "source_paths": source_paths,
        "enabled_custom": sorted(
            {
                str(name).strip().lower()
                for name in enabled_custom
                if str(name).strip().lower() in SUPPORTED_CUSTOM_COMMANDS
            }
        ),
    }
    write_migration(payload)
    return payload
