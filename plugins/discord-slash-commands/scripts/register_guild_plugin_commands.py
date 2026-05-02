#!/usr/bin/env python3
"""Reconcile canonical Discord slash commands using PATCH/POST/DELETE only."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

import yaml


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from state import SUPPORTED_CUSTOM_COMMANDS, load_custom_seed_commands


DEFAULT_ENV_FILE = Path("/local/agents/nodes/colmeio/.hermes/.env")
STALE_MANAGED_COMMANDS = {"discord-slash-status"}
BUILTIN_OVERLAY_COMMANDS = {"status", "model"}


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
        value = value.strip()
        if len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]
        env[key] = value
    return env


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


def _host_cache_root(node_name: str) -> Path:
    return Path("/local/agents/nodes") / node_name / "workspace" / "plugins" / "discord-slash-commands" / "cache"


def _clamp_description(raw: str, fallback: str) -> str:
    text = str(raw or "").strip() or fallback
    return text[:100]


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


def _load_global_commands() -> list[dict[str, Any]]:
    payload = _load_yaml(PLUGIN_ROOT / "manifests" / "global_commands.yaml")
    if not isinstance(payload, dict):
        return []
    commands = payload.get("commands")
    if not isinstance(commands, list):
        return []
    return [dict(item) for item in commands if isinstance(item, dict)]


def _default_enabled_global_commands() -> set[str]:
    return {
        str(item.get("name") or "").strip().lower()
        for item in _load_global_commands()
        if str(item.get("name") or "").strip() and bool(item.get("default_enabled", True))
    }


def _load_custom_commands(cache_root: Path) -> list[dict[str, Any]]:
    payload = _load_json(cache_root / "catalogs" / "custom_commands.json")
    if isinstance(payload, list) and payload:
        return [dict(item) for item in payload if isinstance(item, dict)]
    return [dict(item) for item in load_custom_seed_commands() if isinstance(item, dict)]


def _load_node_activation(cache_root: Path) -> dict[str, Any]:
    payload = _load_json(cache_root / "state" / "node_activation.json")
    return payload if isinstance(payload, dict) else {}


def _load_scope(cache_root: Path, *, app_id: str, guild_id: str) -> dict[str, Any]:
    payload = _load_json(cache_root / "state" / "app_scope.json")
    if isinstance(payload, dict) and payload:
        scope = dict(payload)
    else:
        scope = {
            "version": 1,
            "app_id": app_id,
            "guild_id": guild_id,
            "enabled_commands": sorted(_default_enabled_global_commands() | {"slash"}),
            "updated_at": "",
            "updated_by_node": "",
        }
    disabled = {
        str(item).strip().lower()
        for item in scope.get("disabled_commands") or []
        if str(item).strip()
    }
    custom_enabled = {
        str(item).strip().lower()
        for item in _load_node_activation(cache_root).get("custom_enabled") or []
        if str(item).strip().lower() in SUPPORTED_CUSTOM_COMMANDS
    }
    scope["app_id"] = str(scope.get("app_id") or app_id)
    scope["guild_id"] = str(scope.get("guild_id") or guild_id)
    scope["enabled_commands"] = sorted(
        {
            str(item).strip().lower()
            for item in scope.get("enabled_commands") or []
            if str(item).strip()
        }
        | (_default_enabled_global_commands() - disabled)
        | custom_enabled
        | {"slash"}
    )
    return scope


def _sanitize_choice_payload(raw: Any) -> Dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    value = raw.get("value")
    if not name or value in (None, ""):
        return None
    return {"name": name, "value": value}


def _sanitize_option_payload(raw: Any) -> Dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    description = str(raw.get("description") or "").strip()
    option_type = int(raw.get("type") or 0)
    if not name or not description or option_type <= 0:
        return None

    clean: Dict[str, Any] = {
        "type": option_type,
        "name": name,
        "description": _clamp_description(description, description),
        "required": bool(raw.get("required", False)),
    }
    choices = []
    for item in raw.get("choices") or []:
        choice = _sanitize_choice_payload(item)
        if choice is not None:
            choices.append(choice)
    if choices:
        clean["choices"] = choices
    for field in ("min_value", "max_value", "min_length", "max_length"):
        if field in raw and raw.get(field) is not None:
            clean[field] = raw.get(field)
    if "autocomplete" in raw:
        clean["autocomplete"] = bool(raw.get("autocomplete"))
    return clean


def _sanitize_command_payload(raw: dict[str, Any]) -> Dict[str, Any]:
    description = _clamp_description(str(raw.get("description") or ""), raw.get("name") or "")
    clean: Dict[str, Any] = {
        "name": str(raw.get("name") or "").strip(),
        "type": int(raw.get("type") or 1),
        "description": description,
    }
    if raw.get("default_member_permissions") not in (None, ""):
        clean["default_member_permissions"] = str(raw.get("default_member_permissions"))
    if "dm_permission" in raw:
        clean["dm_permission"] = bool(raw.get("dm_permission"))

    options = []
    for item in raw.get("options") or []:
        option = _sanitize_option_payload(item)
        if option is not None:
            options.append(option)
    if options:
        clean["options"] = options
    return clean


def _build_managed_definitions(cache_root: Path) -> list[dict[str, Any]]:
    return _load_global_commands() + _load_custom_commands(cache_root)


def _enabled_command_names(scope_payload: dict[str, Any]) -> set[str]:
    names = {
        str(item).strip().lower()
        for item in scope_payload.get("enabled_commands") or []
        if str(item).strip()
    }
    names.add("slash")
    return names


def _build_desired_payloads(
    cache_root: Path,
    *,
    app_id: str,
    guild_id: str,
    sync_policy: str = "safe",
) -> tuple[list[Dict[str, Any]], set[str]]:
    scope_payload = _load_scope(cache_root, app_id=app_id, guild_id=guild_id)
    enabled_names = _enabled_command_names(scope_payload)
    desired: list[Dict[str, Any]] = []
    for command in _build_managed_definitions(cache_root):
        name = str(command.get("name") or "").strip().lower()
        if not name or name not in enabled_names:
            continue
        if name in BUILTIN_OVERLAY_COMMANDS and str(sync_policy or "").strip().lower() != "off":
            continue
        desired.append(_sanitize_command_payload(command))
    return desired, enabled_names


def _api_request(
    *,
    method: str,
    url: str,
    bot_token: str,
    payload: Dict[str, Any] | list[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "canonical-discord-slash-commands/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            return {"ok": True, "status": int(getattr(response, "status", 200) or 200), "data": data}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {"raw": raw}
        return {"ok": False, "status": int(exc.code), "data": data}


def _guild_commands_url(app_id: str, guild_id: str) -> str:
    return f"https://discord.com/api/v10/applications/{app_id}/guilds/{guild_id}/commands"


def _guild_command_url(app_id: str, guild_id: str, command_id: str) -> str:
    return f"{_guild_commands_url(app_id, guild_id)}/{command_id}"


def _global_commands_url(app_id: str) -> str:
    return f"https://discord.com/api/v10/applications/{app_id}/commands"


def _global_command_url(app_id: str, command_id: str) -> str:
    return f"{_global_commands_url(app_id)}/{command_id}"


def _load_existing_global_commands(app_id: str, bot_token: str) -> list[Dict[str, Any]]:
    result = _api_request(method="GET", url=_global_commands_url(app_id), bot_token=bot_token)
    data = result.get("data") if result.get("ok") else []
    return data if isinstance(data, list) else []


def _collect_global_overlaps(existing_payloads: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    managed_names = {"status", "model", "acl", "slash", "clean", *SUPPORTED_CUSTOM_COMMANDS, *STALE_MANAGED_COMMANDS}
    overlaps: list[Dict[str, Any]] = []
    for entry in existing_payloads:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip().lower()
        command_id = str(entry.get("id") or "").strip()
        if name in managed_names and command_id:
            overlaps.append(entry)
    return overlaps


def _delete_global_command(*, app_id: str, command_id: str, bot_token: str) -> Dict[str, Any]:
    return _api_request(method="DELETE", url=_global_command_url(app_id, command_id), bot_token=bot_token)


def _normalize_for_compare(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {
        "name": str(payload.get("name") or "").strip().lower(),
        "type": int(payload.get("type") or 1),
        "description": str(payload.get("description") or "").strip(),
    }
    if payload.get("default_member_permissions") not in (None, ""):
        normalized["default_member_permissions"] = str(payload.get("default_member_permissions")).strip()
    if payload.get("dm_permission") is True:
        normalized["dm_permission"] = True
    options = []
    for item in payload.get("options") or []:
        if not isinstance(item, dict):
            continue
        option = {
            "type": int(item.get("type") or 0),
            "name": str(item.get("name") or "").strip(),
            "description": str(item.get("description") or "").strip(),
            "required": bool(item.get("required", False)),
        }
        choices = []
        for choice in item.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            choices.append({"name": str(choice.get("name") or "").strip(), "value": choice.get("value")})
        if choices:
            option["choices"] = choices
        for field in ("min_value", "max_value", "min_length", "max_length"):
            if field in item:
                option[field] = item.get(field)
        if "autocomplete" in item:
            option["autocomplete"] = bool(item.get("autocomplete"))
        options.append(option)
    normalized["options"] = options
    return normalized


def _build_deploy_plan(
    desired_payloads: list[Dict[str, Any]],
    existing_payloads: list[Dict[str, Any]],
) -> tuple[list[Dict[str, Any]], list[tuple[Dict[str, Any], Dict[str, Any]]], list[Dict[str, Any]], list[Dict[str, Any]]]:
    existing_by_name: dict[str, dict[str, Any]] = {}
    for entry in existing_payloads:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip().lower()
        if name:
            existing_by_name[name] = entry

    desired_names = {
        str(item.get("name") or "").strip().lower()
        for item in desired_payloads
        if str(item.get("name") or "").strip()
    }
    managed_names = {
        str(item.get("name") or "").strip().lower()
        for item in existing_payloads
        if str(item.get("name") or "").strip().lower()
        in {"status", "model", "acl", "slash", "clean", *SUPPORTED_CUSTOM_COMMANDS, *STALE_MANAGED_COMMANDS}
    }

    unchanged: list[Dict[str, Any]] = []
    to_patch: list[tuple[Dict[str, Any], Dict[str, Any]]] = []
    to_create: list[Dict[str, Any]] = []
    to_delete: list[Dict[str, Any]] = []

    for desired in desired_payloads:
        name = str(desired.get("name") or "").strip().lower()
        current = existing_by_name.get(name)
        if current is None:
            to_create.append(desired)
            continue
        if _normalize_for_compare(desired) == _normalize_for_compare(current):
            unchanged.append(desired)
            continue
        to_patch.append((current, desired))

    for name, entry in existing_by_name.items():
        if name in managed_names and name not in desired_names:
            to_delete.append(entry)

    return unchanged, to_patch, to_create, to_delete


def _sleep_for_retry(result: Dict[str, Any]) -> float:
    data = result.get("data") or {}
    try:
        retry_after = float((data or {}).get("retry_after") or 0.0)
    except Exception:
        retry_after = 0.0
    if retry_after <= 0:
        return 0.0
    wait_seconds = min(retry_after + 1.0, 30.0)
    time.sleep(wait_seconds)
    return wait_seconds


def _run_with_retry(operation, *, max_attempts: int = 4) -> Dict[str, Any]:
    last_result: Dict[str, Any] = {}
    total_sleep = 0.0
    for attempt in range(1, max_attempts + 1):
        result = operation()
        result["attempt"] = attempt
        if result.get("ok"):
            if total_sleep > 0:
                result["slept_seconds"] = round(total_sleep, 3)
            return result
        if int(result.get("status") or 0) != 429 or attempt >= max_attempts:
            if total_sleep > 0:
                result["slept_seconds"] = round(total_sleep, 3)
            return result
        total_sleep += _sleep_for_retry(result)
        last_result = result
    if total_sleep > 0 and last_result:
        last_result["slept_seconds"] = round(total_sleep, 3)
    return last_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Register canonical discord-slash-commands for a guild.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--cache-root", default="")
    parser.add_argument("--app-id", default="")
    parser.add_argument("--guild-id", default="")
    parser.add_argument("--bot-token", default="")
    parser.add_argument("--commands-file", default="")
    parser.add_argument("--mode", choices=("safe", "post", "put"), default="safe")
    parser.add_argument("--scope", choices=("auto", "global", "guild"), default="guild")
    parser.add_argument("--prune-global-overlaps", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser()
    env = _read_env(env_file)
    node_name = _infer_node_name(env_file)
    cache_root = Path(args.cache_root).expanduser() if str(args.cache_root or "").strip() else _host_cache_root(node_name)

    app_id = str(args.app_id or env.get("DISCORD_APP_ID") or "").strip()
    guild_id = str(args.guild_id or env.get("DISCORD_SERVER_ID") or env.get("DISCORD_GUILD_ID") or "").strip()
    bot_token = str(args.bot_token or env.get("DISCORD_BOT_TOKEN") or "").strip()
    sync_policy = str(env.get("DISCORD_COMMAND_SYNC_POLICY") or "safe").strip().lower() or "safe"

    missing = [
        name
        for name, value in {
            "DISCORD_APP_ID": app_id,
            "DISCORD_SERVER_ID": guild_id,
            "DISCORD_BOT_TOKEN": bot_token,
        }.items()
        if not value
    ]
    if missing:
        print(json.dumps({"ok": False, "missing_env": missing}))
        return 1

    desired_payloads, enabled_names = _build_desired_payloads(
        cache_root,
        app_id=app_id,
        guild_id=guild_id,
        sync_policy=sync_policy,
    )
    managed_names = sorted({"status", "model", "acl", "slash", "clean", *SUPPORTED_CUSTOM_COMMANDS})
    global_to_delete: list[Dict[str, Any]] = []
    if args.prune_global_overlaps or sync_policy == "off":
        global_to_delete = _collect_global_overlaps(_load_existing_global_commands(app_id, bot_token))

    guild_result = _api_request(method="GET", url=_guild_commands_url(app_id, guild_id), bot_token=bot_token)
    guild_list = guild_result.get("data") if guild_result.get("ok") else []
    if not isinstance(guild_list, list):
        guild_list = []

    unchanged, to_patch, to_create, to_delete = _build_deploy_plan(desired_payloads, guild_list)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": True,
                    "mode": "safe",
                    "scope": "guild",
                    "node_name": node_name,
                    "cache_root": str(cache_root),
                    "managed_names": managed_names,
                    "enabled_names": sorted(enabled_names),
                    "unchanged": [item["name"] for item in unchanged],
                    "to_patch": [desired["name"] for _current, desired in to_patch],
                    "to_create": [item["name"] for item in to_create],
                    "to_delete": [str(item.get("name") or "").strip().lower() for item in to_delete],
                    "to_delete_global": [str(item.get("name") or "").strip().lower() for item in global_to_delete],
                    "commands": desired_payloads,
                },
                indent=2,
            )
        )
        return 0

    if not guild_result.get("ok"):
        print(json.dumps({"ok": False, "mode": "safe", "scope": "guild", "result": guild_result}, indent=2))
        return 1

    any_failure = False
    results: list[Dict[str, Any]] = []

    for current, desired in to_patch:
        command_id = str(current.get("id") or "").strip()
        result = _run_with_retry(
            lambda command_id=command_id, desired=desired: _api_request(
                method="PATCH",
                url=_guild_command_url(app_id, guild_id, command_id),
                bot_token=bot_token,
                payload=desired,
            )
        )
        result["command"] = desired["name"]
        result["operation"] = "patch"
        results.append(result)
        if not result.get("ok"):
            any_failure = True

    for payload in to_create:
        result = _run_with_retry(
            lambda payload=payload: _api_request(
                method="POST",
                url=_guild_commands_url(app_id, guild_id),
                bot_token=bot_token,
                payload=payload,
            )
        )
        result["command"] = payload["name"]
        result["operation"] = "create"
        results.append(result)
        if not result.get("ok"):
            any_failure = True

    for entry in to_delete:
        command_id = str(entry.get("id") or "").strip()
        result = _run_with_retry(
            lambda command_id=command_id: _api_request(
                method="DELETE",
                url=_guild_command_url(app_id, guild_id, command_id),
                bot_token=bot_token,
            )
        )
        result["command"] = str(entry.get("name") or "").strip().lower()
        result["operation"] = "delete"
        results.append(result)
        if not result.get("ok"):
            any_failure = True

    for entry in global_to_delete:
        command_id = str(entry.get("id") or "").strip()
        result = _run_with_retry(
            lambda command_id=command_id: _delete_global_command(
                app_id=app_id,
                command_id=command_id,
                bot_token=bot_token,
            )
        )
        result["command"] = str(entry.get("name") or "").strip().lower()
        result["operation"] = "delete_global"
        results.append(result)
        if not result.get("ok"):
            any_failure = True

    print(
        json.dumps(
            {
                "ok": not any_failure,
                "mode": "safe",
                "scope": "guild",
                "node_name": node_name,
                "cache_root": str(cache_root),
                "summary": {
                    "unchanged": [item["name"] for item in unchanged],
                    "patched": [desired["name"] for _current, desired in to_patch],
                    "created": [item["name"] for item in to_create],
                    "deleted": [str(item.get("name") or "").strip().lower() for item in to_delete],
                    "deleted_global": [str(item.get("name") or "").strip().lower() for item in global_to_delete],
                    "enabled": sorted(enabled_names),
                },
                "results": results,
            },
            indent=2,
        )
    )
    return 1 if any_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
