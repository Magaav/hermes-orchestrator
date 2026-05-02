#!/usr/bin/env python3
"""Bootstrap the canonical discord-slash-commands plugin into a node runtime."""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from state import SUPPORTED_CUSTOM_COMMANDS, load_custom_seed_commands, load_global_commands


VALID_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_LEGACY_PRIVATE_DISCORD_ROOT = Path("/local/plugins/private/discord")
DEFAULT_PLUGIN_SOURCE = Path("/local/plugins/discord-slash-commands")
DEFAULT_RUNTIME_CACHE_ROOT = Path("/local/workspace/plugins/discord-slash-commands/cache")


def _is_truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_env(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not VALID_ENV_KEY_RE.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]
        env[key] = value
    return env


def _upsert_env_value(path: Path, key: str, value: str) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    changed = False
    replaced = False
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if pattern.match(raw):
            new_line = f"{key}={value}"
            if raw != new_line:
                lines[idx] = new_line
                changed = True
            replaced = True
            break
    if not replaced:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{key}={value}")
        changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def _infer_config_file(env_file: Path) -> Path:
    if env_file.name == ".env" and env_file.parent.name == ".hermes":
        return env_file.parent / "config.yaml"
    if env_file.suffix == ".env":
        return Path("/local/agents/nodes") / env_file.stem / ".hermes" / "config.yaml"
    return env_file.parent / "config.yaml"


def _infer_node_name(env_file: Path) -> str:
    if env_file.name == ".env" and env_file.parent.name == ".hermes":
        try:
            idx = env_file.parts.index("nodes")
        except ValueError:
            idx = -1
        if idx >= 0 and idx + 1 < len(env_file.parts):
            return str(env_file.parts[idx + 1]).strip()
        return ""
    if env_file.suffix == ".env":
        return env_file.stem.strip()
    return env_file.parent.name.strip()


def _infer_host_node_root(env_file: Path, node_name: str) -> Path:
    if env_file.name == ".env" and env_file.parent.name == ".hermes":
        return env_file.parent.parent
    return Path("/local/agents/nodes") / node_name


def _host_cache_root(node_name: str) -> Path:
    return Path("/local/agents/nodes") / node_name / "workspace" / "plugins" / "discord-slash-commands" / "cache"


def _runtime_cache_root_str() -> str:
    return str(DEFAULT_RUNTIME_CACHE_ROOT)


def _runtime_governance_root_str() -> str:
    return str(DEFAULT_RUNTIME_CACHE_ROOT / "governance")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_yaml(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def _save_config(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _remove_from_list(values: list[str], target: str) -> bool:
    before = list(values)
    values[:] = [value for value in values if value != target]
    return before != values


def _ensure_in_list(values: list[str], target: str) -> bool:
    if target in values:
        return False
    values.append(target)
    return True


def _sync_tree(src: Path, dst: Path) -> bool:
    changed = False
    if not src.exists():
        raise FileNotFoundError(f"plugin source not found: {src}")
    if not dst.exists():
        dst.mkdir(parents=True, exist_ok=True)
        changed = True
    src_entries = {child.name: child for child in src.iterdir()}
    dst_entries = {child.name: child for child in dst.iterdir()} if dst.exists() else {}
    for name, dst_child in dst_entries.items():
        if name not in src_entries:
            if dst_child.is_dir() and not dst_child.is_symlink():
                shutil.rmtree(dst_child)
            else:
                dst_child.unlink()
            changed = True
    for name, src_child in src_entries.items():
        dst_child = dst / name
        if src_child.is_dir():
            if dst_child.exists() and not dst_child.is_dir():
                dst_child.unlink()
                changed = True
            changed = _sync_tree(src_child, dst_child) or changed
            continue
        if dst_child.exists() and dst_child.is_dir():
            shutil.rmtree(dst_child)
            changed = True
        if (not dst_child.exists()) or (not filecmp.cmp(src_child, dst_child, shallow=False)):
            shutil.copy2(src_child, dst_child)
            changed = True
    return changed


def _default_acl_payload(node_name: str, guild_id: str) -> Dict[str, Any]:
    return {
        "version": 1,
        "node": node_name,
        "guild_id": guild_id,
        "updated_at": _utc_now(),
        "seed_source": "canonical_discord_slash_bootstrap",
        "safe_commands": ["help", "provider", "status", "usage"],
        "policy": {"unmapped_command": "deny"},
        "hierarchy": [
            {"role_id": "", "role_name": "admin"},
            {"role_id": "@everyone", "role_name": "@everyone"},
        ],
        "commands": {
            "help": {"min_role": "@everyone", "notes": "bootstrap safe command"},
            "provider": {"min_role": "@everyone", "notes": "bootstrap safe command"},
            "status": {"min_role": "@everyone", "notes": "bootstrap safe command"},
            "usage": {"min_role": "@everyone", "notes": "bootstrap safe command"},
            "acl": {"min_role": "admin", "notes": "bootstrap governance command"},
            "clean": {"min_role": "admin", "notes": "destructive Discord channel cleanup"},
        },
        "user_overrides": {},
    }


def _default_enabled_global_commands() -> set[str]:
    return {
        str(item.get("name") or "").strip().lower()
        for item in load_global_commands()
        if str(item.get("name") or "").strip() and bool(item.get("default_enabled", True))
    }


def _default_models_payload(node_name: str) -> Dict[str, Any]:
    return {
        "version": 1,
        "node": node_name,
        "models": [
            {"key": "gpt54", "label": "GPT-5.4 (OpenAI Codex)", "provider": "openai-codex", "model": "gpt-5.4"},
            {"key": "gpt53codex", "label": "GPT-5.3 Codex (OpenAI Codex)", "provider": "openai-codex", "model": "gpt-5.3-codex"},
            {"key": "nemotron120b", "label": "Nemotron 120B (NVIDIA)", "provider": "nvidia", "model": "nvidia/nemotron-3-super-120b-a12b"},
            {"key": "minimaxm27", "label": "MiniMax M2.7", "provider": "minimax", "model": "MiniMax-M2.7"},
            {"key": "kimik25", "label": "Kimi K2.5", "provider": "kimi-coding", "model": "moonshotai/kimi-k2.5"},
        ],
    }


def _default_channel_acl_payload() -> Dict[str, Any]:
    return {"channels": {}}


def _default_users_payload() -> Dict[str, Any]:
    return {}


def _legacy_path(*parts: str) -> Path:
    return DEFAULT_LEGACY_PRIVATE_DISCORD_ROOT / Path(*parts)


def _load_legacy_custom_commands(node_name: str) -> list[dict[str, Any]]:
    payload = _load_json(_legacy_path("commands", f"{node_name}.json"))
    if not isinstance(payload, list):
        return []
    result: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        if name in SUPPORTED_CUSTOM_COMMANDS:
            result.append(dict(item))
    return result


def _normalize_acl_hierarchy(raw: Any) -> list[dict[str, str]]:
    items = raw if isinstance(raw, list) else []
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _append(role_id: str, role_name: str) -> None:
        key = (str(role_id or "").strip(), str(role_name or "").strip().lower())
        if key in seen:
            return
        seen.add(key)
        normalized.append({"role_id": str(role_id or "").strip(), "role_name": str(role_name or "").strip()})

    for item in items:
        if not isinstance(item, dict):
            continue
        role_id = str(item.get("role_id") or item.get("id") or "").strip()
        role_name = str(item.get("role_name") or item.get("name") or "").strip()
        if role_id == "@everyone" or role_name.lower() == "@everyone":
            _append("@everyone", "@everyone")
            continue
        if role_name.lower() == "admin":
            _append("", "admin")
            continue
        if role_id or role_name:
            _append(role_id, role_name)

    if not any(str(item.get("role_name") or "").strip().lower() == "admin" for item in normalized):
        normalized.insert(0, {"role_id": "", "role_name": "admin"})
    if not any(
        str(item.get("role_id") or "").strip() == "@everyone"
        or str(item.get("role_name") or "").strip().lower() == "@everyone"
        for item in normalized
    ):
        normalized.append({"role_id": "@everyone", "role_name": "@everyone"})
    return normalized


def _normalize_acl_payload(payload: Any, node_name: str, guild_id: str) -> dict[str, Any]:
    default = _default_acl_payload(node_name, guild_id)
    if not isinstance(payload, dict):
        return default

    commands = dict(default.get("commands") or {})
    raw_commands = payload.get("commands")
    if isinstance(raw_commands, dict):
        for key, value in raw_commands.items():
            command_name = str(key or "").strip().lower().lstrip("/")
            if not command_name or not isinstance(value, dict):
                continue
            commands[command_name] = dict(value)

    merged = dict(default)
    merged.update({key: value for key, value in payload.items() if key not in {"commands", "hierarchy", "policy"}})
    merged["node"] = str(payload.get("node") or node_name).strip() or node_name
    merged["guild_id"] = str(payload.get("guild_id") or guild_id).strip() or guild_id
    merged["commands"] = {key: commands[key] for key in sorted(commands)}
    merged["hierarchy"] = _normalize_acl_hierarchy(payload.get("hierarchy"))
    policy = dict(default.get("policy") or {})
    if isinstance(payload.get("policy"), dict):
        policy.update(payload.get("policy") or {})
    merged["policy"] = policy
    merged["user_overrides"] = payload.get("user_overrides") if isinstance(payload.get("user_overrides"), dict) else {}
    return merged


def _load_legacy_acl(node_name: str, guild_id: str) -> dict[str, Any]:
    payload = _load_json(_legacy_path("acl", f"{node_name}_acl.json"))
    return _normalize_acl_payload(payload, node_name, guild_id)


def _load_legacy_models(node_name: str) -> dict[str, Any]:
    payload = _load_json(_legacy_path("models", f"{node_name}_models.json"))
    if isinstance(payload, dict):
        return payload
    return _default_models_payload(node_name)


def _load_legacy_channel_acl() -> dict[str, Any]:
    payload = _load_yaml(_legacy_path("hooks", "channel_acl", "config.yaml"))
    if isinstance(payload, dict):
        return payload
    return _default_channel_acl_payload()


def _load_legacy_users() -> dict[str, Any]:
    payload = _load_json(_legacy_path("discord_users.json"))
    if isinstance(payload, dict):
        return payload
    return _default_users_payload()


def _seed_custom_catalog(legacy_payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seed_map = {
        str(item.get("name") or "").strip().lower(): dict(item)
        for item in load_custom_seed_commands()
        if isinstance(item, dict)
    }
    legacy_map = {
        str(item.get("name") or "").strip().lower(): dict(item)
        for item in legacy_payload
        if isinstance(item, dict)
    }
    result: list[dict[str, Any]] = []
    for name, entry in seed_map.items():
        merged = dict(entry)
        legacy = legacy_map.get(name)
        if legacy:
            for key in ("description", "default_member_permissions", "dm_permission", "options"):
                if legacy.get(key) is not None:
                    merged[key] = legacy.get(key)
        result.append(merged)
    return result


def _ensure_symlink(path: Path, target: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        try:
            if Path(os.readlink(path)) == target:
                return
        except OSError:
            pass
        path.unlink()
    elif path.exists():
        path.unlink()
    os.symlink(str(target), str(path))


def _ensure_cache_layout(
    cache_root: Path,
    *,
    node_name: str,
    guild_id: str,
    legacy_custom_commands: list[dict[str, Any]],
) -> Dict[str, Any]:
    catalog_path = cache_root / "catalogs" / "custom_commands.json"
    acl_path = cache_root / "governance" / "acl.json"
    models_path = cache_root / "governance" / "models.json"
    channel_acl_path = cache_root / "governance" / "channel_acl.yaml"
    users_path = cache_root / "governance" / "discord_users.json"
    node_activation_path = cache_root / "state" / "node_activation.json"
    scope_path = cache_root / "state" / "app_scope.json"

    cache_root.mkdir(parents=True, exist_ok=True)

    if not catalog_path.exists():
        _write_json(catalog_path, _seed_custom_catalog(legacy_custom_commands))

    current_acl = _load_json(acl_path) if acl_path.exists() else None
    normalized_acl = _normalize_acl_payload(
        current_acl if isinstance(current_acl, dict) else _load_legacy_acl(node_name, guild_id),
        node_name,
        guild_id,
    )
    if normalized_acl != current_acl:
        _write_json(acl_path, normalized_acl)
    if not models_path.exists():
        _write_json(models_path, _load_legacy_models(node_name))
    if not channel_acl_path.exists():
        _write_yaml(channel_acl_path, _load_legacy_channel_acl())
    if not users_path.exists():
        _write_json(users_path, _load_legacy_users())

    _ensure_symlink(cache_root / "governance" / "acl" / f"{node_name}_acl.json", Path("..") / "acl.json")
    _ensure_symlink(cache_root / "governance" / "models" / f"{node_name}_models.json", Path("..") / "models.json")
    _ensure_symlink(
        cache_root / "governance" / "hooks" / "channel_acl" / "config.yaml",
        Path("..") / ".." / "channel_acl.yaml",
    )

    enabled_custom = sorted(
        {
            str(item.get("name") or "").strip().lower()
            for item in legacy_custom_commands
            if str(item.get("name") or "").strip().lower() in SUPPORTED_CUSTOM_COMMANDS
        }
    )
    if not node_activation_path.exists():
        _write_json(
            node_activation_path,
            {
                "version": 1,
                "node_name": node_name,
                "custom_enabled": enabled_custom,
                "updated_at": _utc_now(),
            },
        )

    current_scope = _load_json(scope_path) if scope_path.exists() else None
    if isinstance(current_scope, dict) and current_scope:
        disabled_commands = {
            str(item).strip().lower()
            for item in current_scope.get("disabled_commands") or []
            if str(item).strip()
        }
        enabled_commands = sorted(
            {
                str(item).strip().lower()
                for item in current_scope.get("enabled_commands") or []
                if str(item).strip()
            }
            | (_default_enabled_global_commands() - disabled_commands)
            | set(enabled_custom)
            | {"slash"}
        )
        next_scope = dict(current_scope)
        next_scope["guild_id"] = str(next_scope.get("guild_id") or guild_id)
        next_scope["enabled_commands"] = enabled_commands
        if next_scope != current_scope:
            next_scope["updated_at"] = _utc_now()
            next_scope["updated_by_node"] = node_name
            _write_json(scope_path, next_scope)
    else:
        _write_json(
            scope_path,
            {
                "version": 1,
                "app_id": "",
                "guild_id": guild_id,
                "enabled_commands": sorted(_default_enabled_global_commands() | set(enabled_custom) | {"slash"}),
                "updated_at": _utc_now(),
                "updated_by_node": node_name,
            },
        )

    migration_path = cache_root / "migration.json"
    if not migration_path.exists():
        _write_json(
            migration_path,
            {
                "version": 1,
                "migrated_at": _utc_now(),
                "migrated_node": node_name,
                "source_paths": {
                    "commands": str(_legacy_path("commands", f"{node_name}.json")),
                    "acl": str(_legacy_path("acl", f"{node_name}_acl.json")),
                    "models": str(_legacy_path("models", f"{node_name}_models.json")),
                    "channel_acl": str(_legacy_path("hooks", "channel_acl", "config.yaml")),
                    "users": str(_legacy_path("discord_users.json")),
                },
                "enabled_custom": enabled_custom,
            },
        )

    return {
        "cache_root": str(cache_root),
        "custom_catalog": str(catalog_path),
        "governance_root": str(cache_root / "governance"),
        "enabled_custom": enabled_custom,
    }


def _merge_scope_payload(current: Any, legacy: Any, *, node_name: str, guild_id: str) -> dict[str, Any]:
    current_payload = dict(current) if isinstance(current, dict) else {}
    legacy_payload = dict(legacy) if isinstance(legacy, dict) else {}
    disabled_commands = {
        str(item).strip().lower()
        for item in current_payload.get("disabled_commands") or []
        if str(item).strip()
    }
    enabled_commands = sorted(
        {
            str(item).strip().lower()
            for payload in (legacy_payload, current_payload)
            for item in payload.get("enabled_commands", []) or []
            if str(item).strip()
        }
        | (_default_enabled_global_commands() - disabled_commands)
        | {"slash"}
    )
    merged = dict(legacy_payload)
    merged.update(current_payload)
    merged["version"] = int(merged.get("version") or 1)
    merged["guild_id"] = str(merged.get("guild_id") or guild_id)
    merged["enabled_commands"] = enabled_commands
    merged["updated_at"] = _utc_now()
    merged["updated_by_node"] = node_name
    return merged


def _merge_node_activation_payload(current: Any, legacy: Any, *, node_name: str) -> dict[str, Any]:
    current_payload = dict(current) if isinstance(current, dict) else {}
    legacy_payload = dict(legacy) if isinstance(legacy, dict) else {}
    custom_enabled = sorted(
        {
            str(item).strip().lower()
            for payload in (legacy_payload, current_payload)
            for item in payload.get("custom_enabled", []) or []
            if str(item).strip().lower() in SUPPORTED_CUSTOM_COMMANDS
        }
    )
    merged = dict(legacy_payload)
    merged.update(current_payload)
    merged["version"] = int(merged.get("version") or 1)
    merged["node_name"] = str(merged.get("node_name") or node_name)
    merged["custom_enabled"] = custom_enabled
    merged["updated_at"] = _utc_now()
    return merged


def _merge_legacy_acl_payload(current: Any, legacy: Any, *, node_name: str, guild_id: str) -> dict[str, Any]:
    base = _normalize_acl_payload(legacy, node_name, guild_id)
    if isinstance(current, dict):
        current_normalized = _normalize_acl_payload(current, node_name, guild_id)
        commands = dict(base.get("commands") or {})
        commands.update(current_normalized.get("commands") or {})
        base["commands"] = {key: commands[key] for key in sorted(commands)}
        base["guild_id"] = str(current_normalized.get("guild_id") or base.get("guild_id") or guild_id)
        base["node"] = str(current_normalized.get("node") or base.get("node") or node_name)
    base["updated_at"] = _utc_now()
    return base


def _migrate_legacy_hermes_cache(old_cache_root: Path, cache_root: Path, *, node_name: str, guild_id: str) -> bool:
    if not old_cache_root.exists():
        return False
    changed = False
    if not cache_root.exists():
        cache_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(old_cache_root, cache_root, symlinks=True)
        return True

    for rel in (
        Path("catalogs") / "custom_commands.json",
        Path("governance") / "models.json",
        Path("governance") / "channel_acl.yaml",
        Path("governance") / "discord_users.json",
        Path("migration.json"),
    ):
        src = old_cache_root / rel
        dst = cache_root / rel
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            changed = True

    merge_specs = (
        (
            Path("state") / "app_scope.json",
            lambda current, legacy: _merge_scope_payload(current, legacy, node_name=node_name, guild_id=guild_id),
        ),
        (
            Path("state") / "node_activation.json",
            lambda current, legacy: _merge_node_activation_payload(current, legacy, node_name=node_name),
        ),
        (
            Path("governance") / "acl.json",
            lambda current, legacy: _merge_legacy_acl_payload(current, legacy, node_name=node_name, guild_id=guild_id),
        ),
    )
    for rel, merge in merge_specs:
        src = old_cache_root / rel
        if not src.exists():
            continue
        dst = cache_root / rel
        merged = merge(_load_json(dst), _load_json(src))
        if merged != _load_json(dst):
            _write_json(dst, merged)
            changed = True

    return changed


def _peer_nodes_for_scope(app_id: str, guild_id: str) -> list[str]:
    if not app_id or not guild_id:
        return []
    env_root = Path("/local/agents/envs")
    peers: list[str] = []
    for env_file in sorted(env_root.glob("*.env")):
        env = _read_env(env_file)
        file_app = str(env.get("DISCORD_APP_ID") or "").strip()
        file_guild = str(env.get("DISCORD_SERVER_ID") or env.get("DISCORD_GUILD_ID") or "").strip()
        if file_app != app_id or file_guild != guild_id:
            continue
        if not (
            _is_truthy(env.get("PLUGIN_DISCORD_SLASH_COMMANDS", ""))
            or _is_truthy(env.get("PLUGIN_DISCORD_GOVERNANCE", ""))
        ):
            continue
        peers.append(env_file.stem)
    return peers


def _scope_payload_for_node(node_name: str) -> dict[str, Any]:
    path = _host_cache_root(node_name) / "state" / "app_scope.json"
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return {}
    disabled_commands = {
        str(item).strip().lower()
        for item in payload.get("disabled_commands") or []
        if str(item).strip()
    }
    activation = _node_activation_payload_for_node(node_name)
    custom_enabled = {
        str(item).strip().lower()
        for item in activation.get("custom_enabled") or []
        if str(item).strip().lower() in SUPPORTED_CUSTOM_COMMANDS
    }
    enabled_commands = sorted(
        {
            str(item).strip().lower()
            for item in payload.get("enabled_commands") or []
            if str(item).strip()
        }
        | (_default_enabled_global_commands() - disabled_commands)
        | custom_enabled
        | {"slash"}
    )
    if enabled_commands != list(payload.get("enabled_commands") or []):
        payload = dict(payload)
        payload["enabled_commands"] = enabled_commands
        _write_json(path, payload)
    return payload


def _migration_payload_for_node(node_name: str) -> dict[str, Any]:
    path = _host_cache_root(node_name) / "migration.json"
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else {}


def _node_activation_payload_for_node(node_name: str) -> dict[str, Any]:
    path = _host_cache_root(node_name) / "state" / "node_activation.json"
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else {}


def _scope_sort_key(node_name: str, payload: dict[str, Any], migration: dict[str, Any]) -> tuple[int, int, str, str]:
    enabled = {
        str(item).strip().lower()
        for item in payload.get("enabled_commands") or []
        if str(item).strip()
    }
    custom_count = len(enabled & SUPPORTED_CUSTOM_COMMANDS)
    is_non_orchestrator = node_name != "orchestrator"
    updated_at = str(payload.get("updated_at") or "")
    return (
        custom_count,
        1 if is_non_orchestrator else 0,
        updated_at,
        node_name,
    )


def _mirror_scope_state(*, app_id: str, guild_id: str, current_node: str) -> list[str]:
    peers = _peer_nodes_for_scope(app_id, guild_id)
    if current_node and current_node not in peers:
        peers.append(current_node)
    if not peers:
        return []

    best_node = None
    best_payload = None
    best_key = None
    for node_name in peers:
        payload = _scope_payload_for_node(node_name)
        migration = _migration_payload_for_node(node_name)
        if not payload:
            continue
        payload["app_id"] = app_id
        payload["guild_id"] = guild_id
        key = _scope_sort_key(node_name, payload, migration)
        if best_key is None or key > best_key:
            best_key = key
            best_node = node_name
            best_payload = payload

    if best_payload is None:
        best_node = current_node
        best_payload = {
            "version": 1,
            "app_id": app_id,
            "guild_id": guild_id,
            "enabled_commands": sorted(_default_enabled_global_commands() | {"slash"}),
            "updated_at": _utc_now(),
            "updated_by_node": current_node,
        }

    best_payload["app_id"] = app_id
    best_payload["guild_id"] = guild_id
    disabled_commands = {
        str(item).strip().lower()
        for item in best_payload.get("disabled_commands") or []
        if str(item).strip()
    }
    best_payload["enabled_commands"] = sorted(
        {
            str(item).strip().lower()
            for item in best_payload.get("enabled_commands") or []
            if str(item).strip()
        }
        | (_default_enabled_global_commands() - disabled_commands)
        | {"slash"}
    )

    mirrored: list[str] = []
    for node_name in peers:
        scope_path = _host_cache_root(node_name) / "state" / "app_scope.json"
        scope_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(scope_path, best_payload)
        mirrored.append(node_name)
    return sorted(mirrored)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the canonical discord-slash-commands plugin into Hermes.")
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--config-file", default="")
    parser.add_argument("--plugin-source", default=str(DEFAULT_PLUGIN_SOURCE))
    parser.add_argument("--plugin-name", default="discord-slash-commands")
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser()
    config_file = Path(args.config_file).expanduser() if str(args.config_file).strip() else _infer_config_file(env_file)
    plugin_source = Path(args.plugin_source).expanduser()
    plugin_name = str(args.plugin_name)

    env = _read_env(env_file)
    slash_enabled = _is_truthy(env.get("PLUGIN_DISCORD_SLASH_COMMANDS", ""))
    governance_alias_enabled = _is_truthy(env.get("PLUGIN_DISCORD_GOVERNANCE", ""))
    enabled = slash_enabled or governance_alias_enabled

    config = _load_config(config_file)
    plugins_cfg = config.setdefault("plugins", {})
    enabled_list = plugins_cfg.setdefault("enabled", [])
    if not isinstance(enabled_list, list):
        enabled_list = []
        plugins_cfg["enabled"] = enabled_list

    # Governance is deprecated; the canonical slash plugin owns this runtime now.
    changed = _remove_from_list(enabled_list, "discord-governance")
    plugin_target = config_file.parent / "plugins" / plugin_name
    synced = False
    node_name = (
        _infer_node_name(env_file)
        or str(env.get("NODE_NAME") or "").strip()
        or str(os.getenv("NODE_NAME", "") or "").strip()
    )

    if enabled:
        changed = _upsert_env_value(env_file, "HERMES_ENABLE_PROJECT_PLUGINS", "true") or changed
        if node_name:
            changed = _upsert_env_value(env_file, "NODE_NAME", node_name) or changed
        host_node_root = _infer_host_node_root(env_file, node_name)
        cache_root = host_node_root / "workspace" / "plugins" / "discord-slash-commands" / "cache"
        guild_id = str(env.get("DISCORD_SERVER_ID") or env.get("DISCORD_GUILD_ID") or "").strip()
        migrated_hermes_cache = _migrate_legacy_hermes_cache(
            host_node_root / ".hermes" / "discord-slash-commands" / "cache",
            cache_root,
            node_name=node_name,
            guild_id=guild_id,
        )
        changed = migrated_hermes_cache or changed
        legacy_custom_commands = _load_legacy_custom_commands(node_name)
        cache_info = _ensure_cache_layout(
            cache_root,
            node_name=node_name,
            guild_id=guild_id,
            legacy_custom_commands=legacy_custom_commands,
        )

        app_id = str(env.get("DISCORD_APP_ID") or "").strip()
        mirrored_scope_nodes = _mirror_scope_state(app_id=app_id, guild_id=guild_id, current_node=node_name)

        synced = _sync_tree(plugin_source, plugin_target)
        changed = synced or changed
        changed = _ensure_in_list(enabled_list, plugin_name) or changed
        _save_config(config_file, config)

        print(
            json.dumps(
                {
                    "ok": True,
                    "enabled": True,
                    "enabled_via_deprecated_governance_flag": bool(governance_alias_enabled and not slash_enabled),
                    "changed": changed,
                    "plugin_synced": synced,
                    "plugin_target": str(plugin_target),
                    "config_file": str(config_file),
                    "env_file": str(env_file),
                    "node_name": node_name,
                    "cache": cache_info,
                    "migrated_hermes_cache": migrated_hermes_cache,
                    "mirrored_scope_nodes": mirrored_scope_nodes,
                }
            )
        )
        return 0

    removed = _remove_from_list(enabled_list, plugin_name)
    if removed or changed:
        _save_config(config_file, config)
        changed = True

    print(
        json.dumps(
            {
                "ok": True,
                "enabled": False,
                "changed": changed,
                "plugin_synced": False,
                "plugin_target": str(plugin_target),
                "config_file": str(config_file),
                "env_file": str(env_file),
                "node_name": node_name,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
