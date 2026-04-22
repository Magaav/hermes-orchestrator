"""Plugin-owned Discord governance compatibility sync."""

from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict

import yaml


_PUBLIC_SLASH_BRIDGE_ROOT = Path("/local/plugins/public/discord/hooks/discord_slash_bridge")
_PRIVATE_SLASH_BRIDGE_ROOT = Path("/local/plugins/private/discord/hooks/discord_slash_bridge")
_PUBLIC_CHANNEL_ACL_ROOT = Path("/local/plugins/public/discord/hooks/channel_acl")
_PRIVATE_CHANNEL_ACL_ROOT = Path("/local/plugins/private/discord/hooks/channel_acl")
_PUBLIC_DISCORD_CUSTOM_ROOT = Path("/local/plugins/public/discord/custom_handlers")

_BRIDGE_FILES = ("runtime.py", "handlers.py", "role_acl.py")
_BRIDGE_CUSTOM_HANDLER_FILES = ("clean.py", "clone.py", "faltas.py", "pair.py", "thread.py")
_EXTRA_CUSTOM_HANDLER_FILES = ("falta_confirmation_store.py", "falta_confirmation_view.py")


def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


def _load_yaml_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _write_text_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _write_yaml_if_changed(path: Path, payload: Dict[str, Any]) -> bool:
    serialized = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    return _write_text_if_changed(path, serialized)


def _copy_file_if_needed(src: Path, dst: Path) -> bool:
    if not src.exists():
        raise FileNotFoundError(f"missing compatibility source file: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and src.read_bytes() == dst.read_bytes():
        return False
    shutil.copy2(src, dst)
    return True


def _ensure_list_contains(payload: Dict[str, Any], keys: list[str], values: list[str]) -> None:
    current: Any = payload
    for key in keys[:-1]:
        next_value = current.get(key)
        if not isinstance(next_value, dict):
            next_value = {}
            current[key] = next_value
        current = next_value

    leaf_key = keys[-1]
    leaf_value = current.get(leaf_key)
    if not isinstance(leaf_value, list):
        leaf_value = []
        current[leaf_key] = leaf_value

    for value in values:
        if value not in leaf_value:
            leaf_value.append(value)


def _governance_registry_overlay() -> Dict[str, Any]:
    return {
        "slash_bridge": {
            "enabled": True,
        },
        "native_overrides": {
            "acl": {
                "enabled": True,
                "description": "Gerenciar ACL de comandos e canais",
                "acl_command": "acl",
                "command_description": "Slash command alvo (ex.: metricas)",
                "role_description": "Role minima (ex.: gerente, admin ou @everyone)",
                "channel_description": "Canal alvo (channel_id numerico)",
                "mode_description": "Modo: default (livre) ou specific (condicionado)",
                "model_key_description": "Obrigatorio em mode:specific",
                "instructions_description": "Instrucoes extras do canal (opcional)",
                "allowed_commands_description": "CSV de comandos permitidos (opcional)",
                "allowed_skills_description": "CSV de skills permitidas (opcional)",
                "always_allowed_description": "CSV de comandos sempre permitidos (opcional)",
                "default_action_description": "Acao padrao para texto livre (opcional)",
                "free_text_policy_description": "Politica de texto livre (opcional)",
                "store_description": "Loja fixa do canal: loja1/loja2 (opcional)",
            }
        },
    }


def ensure_governance_runtime() -> Dict[str, Any]:
    hermes_home = _resolve_hermes_home()
    hooks_root = hermes_home / "hooks"
    slash_dst = hooks_root / "discord_slash_bridge"
    slash_custom_dst = slash_dst / "custom_handlers"
    channel_acl_dst = hooks_root / "channel_acl"

    changed_paths: list[str] = []

    for name in _BRIDGE_FILES:
        src = _PUBLIC_SLASH_BRIDGE_ROOT / name
        dst = slash_dst / name
        if _copy_file_if_needed(src, dst):
            changed_paths.append(str(dst))

    for name in _BRIDGE_CUSTOM_HANDLER_FILES:
        src = _PUBLIC_SLASH_BRIDGE_ROOT / "custom_handlers" / name
        dst = slash_custom_dst / name
        if _copy_file_if_needed(src, dst):
            changed_paths.append(str(dst))

    for name in _EXTRA_CUSTOM_HANDLER_FILES:
        src = _PUBLIC_DISCORD_CUSTOM_ROOT / name
        if not src.exists():
            continue
        dst = slash_custom_dst / name
        if _copy_file_if_needed(src, dst):
            changed_paths.append(str(dst))

    base_config = _load_yaml_dict(_PRIVATE_SLASH_BRIDGE_ROOT / "config.yaml")
    existing_config = _load_yaml_dict(slash_dst / "config.yaml")
    merged_config = _deep_merge(base_config, existing_config)
    if _write_yaml_if_changed(slash_dst / "config.yaml", merged_config):
        changed_paths.append(str(slash_dst / "config.yaml"))

    base_registry = _load_yaml_dict(_PRIVATE_SLASH_BRIDGE_ROOT / "registry.yaml")
    existing_registry = _load_yaml_dict(slash_dst / "registry.yaml")
    merged_registry = _deep_merge(base_registry, existing_registry)
    merged_registry = _deep_merge(merged_registry, _governance_registry_overlay())
    if _write_yaml_if_changed(slash_dst / "registry.yaml", merged_registry):
        changed_paths.append(str(slash_dst / "registry.yaml"))

    if _copy_file_if_needed(_PUBLIC_CHANNEL_ACL_ROOT / "handler.py", channel_acl_dst / "handler.py"):
        changed_paths.append(str(channel_acl_dst / "handler.py"))

    private_channel_acl_config = _PRIVATE_CHANNEL_ACL_ROOT / "config.yaml"
    if private_channel_acl_config.exists():
        if _copy_file_if_needed(private_channel_acl_config, channel_acl_dst / "config.yaml"):
            changed_paths.append(str(channel_acl_dst / "config.yaml"))

    return {
        "ok": True,
        "changed": bool(changed_paths),
        "changed_paths": changed_paths,
        "hermes_home": str(hermes_home),
        "slash_bridge_dir": str(slash_dst),
        "channel_acl_dir": str(channel_acl_dst),
    }


def main() -> int:
    print(json.dumps(ensure_governance_runtime(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
