#!/usr/bin/env python3
"""Reconcile native Discord plugin commands without destructive overwrites.

This script only patches or creates the plugin-owned commands in the active
scope. It intentionally avoids bulk overwrites and cross-scope deletes so
gateway restarts do not burn Discord's app-command mutation budget.
"""

from __future__ import annotations

import argparse
import json
import time
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict


DEFAULT_ENV_FILE = Path("/local/agents/nodes/colmeio/.hermes/.env")


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


def _clamp_description(raw: str, fallback: str) -> str:
    text = str(raw or "").strip() or fallback
    return text[:100]


def _load_payload_map(commands_file: Path) -> Dict[str, Dict[str, Any]]:
    if not commands_file.exists():
        return {}
    try:
        payload = json.loads(commands_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, list):
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip().lower()
        if name:
            result[name] = entry
    return result


def _default_metricas_payload() -> Dict[str, Any]:
    return {
        "name": "metricas",
        "type": 1,
        "description": "Dashboard de métricas Colmeio (somente admin)",
        "default_member_permissions": "8",
        "dm_permission": False,
        "options": [
            {
                "type": 3,
                "name": "formato",
                "description": "Formato do dashboard",
                "required": False,
                "choices": [
                    {"name": "texto", "value": "text"},
                    {"name": "json", "value": "json"},
                    {"name": "csv", "value": "csv"},
                ],
            },
            {
                "type": 4,
                "name": "dias",
                "description": "Janela em dias (ex.: 7, 30, 90)",
                "required": False,
                "min_value": 1,
                "max_value": 365,
            },
            {
                "type": 3,
                "name": "skill",
                "description": "Filtrar por nome da skill (ex.: colmeio-lista-de-faltas)",
                "required": False,
            },
        ],
    }


def _default_faltas_payload() -> Dict[str, Any]:
    return {
        "name": "faltas",
        "type": 1,
        "description": "Gerenciar lista de faltas das lojas",
        "options": [
            {
                "type": 3,
                "name": "action",
                "description": "Acao do comando",
                "required": True,
                "choices": [
                    {"name": "listar", "value": "listar"},
                    {"name": "adicionar", "value": "adicionar"},
                    {"name": "remover", "value": "remover"},
                    {"name": "limpar", "value": "limpar"},
                    {"name": "help", "value": "help"},
                ],
            },
            {
                "type": 3,
                "name": "loja",
                "description": "loja1, loja2 ou ambas",
                "required": False,
                "choices": [
                    {"name": "loja1", "value": "loja1"},
                    {"name": "loja2", "value": "loja2"},
                    {"name": "ambas", "value": "ambas"},
                ],
            },
            {
                "type": 3,
                "name": "itens",
                "description": "Itens separados por virgula (adicionar/remover)",
                "required": False,
            },
            {
                "type": 3,
                "name": "formato",
                "description": "Formato para listar: links, excel ou texto",
                "required": False,
                "choices": [
                    {"name": "links", "value": "links"},
                    {"name": "excel", "value": "excel"},
                    {"name": "texto", "value": "texto"},
                ],
            },
        ],
    }


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


def _sanitize_command_payload(raw: Any, fallback: Dict[str, Any]) -> Dict[str, Any]:
    source = raw if isinstance(raw, dict) else fallback
    fallback_name = str(fallback.get("name") or "").strip()
    fallback_description = str(fallback.get("description") or "").strip()

    clean: Dict[str, Any] = {
        "name": str(source.get("name") or fallback_name).strip() or fallback_name,
        "type": int(source.get("type") or fallback.get("type") or 1),
        "description": _clamp_description(source.get("description"), fallback_description),
    }

    if "default_member_permissions" in source or "default_member_permissions" in fallback:
        value = source.get("default_member_permissions", fallback.get("default_member_permissions"))
        if value not in (None, ""):
            clean["default_member_permissions"] = str(value)

    if "dm_permission" in source or "dm_permission" in fallback:
        clean["dm_permission"] = bool(source.get("dm_permission", fallback.get("dm_permission", True)))

    options = []
    for item in source.get("options") or fallback.get("options") or []:
        option = _sanitize_option_payload(item)
        if option is not None:
            options.append(option)
    if options:
        clean["options"] = options

    return clean


def _build_command_payloads(commands_file: Path) -> list[Dict[str, Any]]:
    payload_map = _load_payload_map(commands_file)
    return [
        _sanitize_command_payload(payload_map.get("metricas"), _default_metricas_payload()),
        _sanitize_command_payload(payload_map.get("faltas"), _default_faltas_payload()),
        {
            "name": "discord-slash-status",
            "type": 1,
            "description": _clamp_description(
                "Show Discord slash registration diagnostics for this node",
                "Show Discord slash registration diagnostics",
            ),
        },
    ]


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
            "User-Agent": "colmeio-discord-slash-commands/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            return {
                "ok": True,
                "status": int(getattr(response, "status", 200) or 200),
                "data": data,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {"raw": raw}
        return {
            "ok": False,
            "status": int(exc.code),
            "data": data,
        }


def _guild_commands_url(app_id: str, guild_id: str) -> str:
    return f"https://discord.com/api/v10/applications/{app_id}/guilds/{guild_id}/commands"


def _guild_command_url(app_id: str, guild_id: str, command_id: str) -> str:
    return f"{_guild_commands_url(app_id, guild_id)}/{command_id}"


def _global_commands_url(app_id: str) -> str:
    return f"https://discord.com/api/v10/applications/{app_id}/commands"


def _global_command_url(app_id: str, command_id: str) -> str:
    return f"{_global_commands_url(app_id)}/{command_id}"


def _get_existing_commands(app_id: str, guild_id: str, bot_token: str) -> Dict[str, Any]:
    return _api_request(
        method="GET",
        url=_guild_commands_url(app_id, guild_id),
        bot_token=bot_token,
    )


def _get_existing_global_commands(app_id: str, bot_token: str) -> Dict[str, Any]:
    return _api_request(
        method="GET",
        url=_global_commands_url(app_id),
        bot_token=bot_token,
    )


def _normalize_for_compare(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {
        "name": str(payload.get("name") or "").strip().lower(),
        "type": int(payload.get("type") or 1),
        "description": str(payload.get("description") or "").strip(),
    }
    default_member_permissions = payload.get("default_member_permissions")
    if default_member_permissions not in (None, ""):
        normalized["default_member_permissions"] = str(default_member_permissions).strip()

    # Discord often omits falsey permission flags from fetch responses even when
    # the submitted payload included them. Normalize away empty/falsey values so
    # safe-mode comparisons do not force no-op patches on every restart.
    if payload.get("dm_permission") is True:
        normalized["dm_permission"] = True

    options = payload.get("options") or []
    clean_options = []
    for item in options:
        if not isinstance(item, dict):
            continue
        option = {
            "type": int(item.get("type") or 0),
            "name": str(item.get("name") or "").strip(),
            "description": str(item.get("description") or "").strip(),
            "required": bool(item.get("required", False)),
        }
        choices = item.get("choices") or []
        clean_choices = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            clean_choices.append(
                {
                    "name": str(choice.get("name") or "").strip(),
                    "value": choice.get("value"),
                }
            )
        if clean_choices:
            option["choices"] = clean_choices
        for field in ("min_value", "max_value", "min_length", "max_length"):
            if field in item:
                option[field] = item.get(field)
        if "autocomplete" in item:
            option["autocomplete"] = bool(item.get("autocomplete"))
        clean_options.append(option)
    normalized["options"] = clean_options
    return normalized


def _build_deploy_plan(
    desired_payloads: list[Dict[str, Any]],
    existing_payloads: list[Dict[str, Any]],
) -> tuple[list[Dict[str, Any]], list[tuple[Dict[str, Any], Dict[str, Any]]], list[Dict[str, Any]]]:
    existing_by_name = {}
    for entry in existing_payloads:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip().lower()
        if name:
            existing_by_name[name] = entry

    unchanged: list[Dict[str, Any]] = []
    to_patch: list[tuple[Dict[str, Any], Dict[str, Any]]] = []
    to_create: list[Dict[str, Any]] = []
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
    return unchanged, to_patch, to_create


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


def _patch_command(
    *,
    app_id: str,
    guild_id: str,
    command_id: str,
    bot_token: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    return _api_request(
        method="PATCH",
        url=_guild_command_url(app_id, guild_id, command_id),
        bot_token=bot_token,
        payload=payload,
    )


def _create_command(
    *,
    app_id: str,
    guild_id: str,
    bot_token: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    return _api_request(
        method="POST",
        url=_guild_commands_url(app_id, guild_id),
        bot_token=bot_token,
        payload=payload,
    )


def _delete_guild_command(
    *,
    app_id: str,
    guild_id: str,
    command_id: str,
    bot_token: str,
) -> Dict[str, Any]:
    return _api_request(
        method="DELETE",
        url=_guild_command_url(app_id, guild_id, command_id),
        bot_token=bot_token,
    )


def _delete_global_command(
    *,
    app_id: str,
    command_id: str,
    bot_token: str,
) -> Dict[str, Any]:
    return _api_request(
        method="DELETE",
        url=_global_command_url(app_id, command_id),
        bot_token=bot_token,
    )


def _normalize_command_name(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _command_name_set(entries: list[Dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = _normalize_command_name(entry.get("name"))
        if name:
            names.add(name)
    return names


def _resolve_scope(sync_policy: str, requested_scope: str) -> str:
    clean_requested = str(requested_scope or "").strip().lower() or "auto"
    if clean_requested in {"global", "guild"}:
        return clean_requested
    return "guild" if str(sync_policy or "").strip().lower() == "off" else "global"


def _collect_overlaps(
    primary_entries: list[Dict[str, Any]],
    secondary_entries: list[Dict[str, Any]],
) -> tuple[list[str], list[Dict[str, Any]]]:
    primary_names = _command_name_set(primary_entries)
    overlapping_entries: list[Dict[str, Any]] = []
    overlap_names: set[str] = set()
    for entry in secondary_entries:
        if not isinstance(entry, dict):
            continue
        name = _normalize_command_name(entry.get("name"))
        if not name or name not in primary_names:
            continue
        overlap_names.add(name)
        overlapping_entries.append(entry)
    return sorted(overlap_names), overlapping_entries


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register only the discord-slash-commands plugin commands for a guild.",
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--app-id", default="")
    parser.add_argument("--guild-id", default="")
    parser.add_argument("--bot-token", default="")
    parser.add_argument("--commands-file", default="")
    parser.add_argument("--mode", choices=("safe", "post", "put"), default="safe")
    parser.add_argument("--scope", choices=("auto", "global", "guild"), default="auto")
    parser.add_argument("--prune-global-overlaps", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser()
    env = _read_env(env_file)

    app_id = str(args.app_id or env.get("DISCORD_APP_ID") or "").strip()
    guild_id = str(args.guild_id or env.get("DISCORD_SERVER_ID") or "").strip()
    bot_token = str(args.bot_token or env.get("DISCORD_BOT_TOKEN") or "").strip()
    commands_file_raw = str(args.commands_file or env.get("DISCORD_COMMANDS_FILE") or "").strip()
    commands_file = Path(commands_file_raw).expanduser() if commands_file_raw else Path(
        "/local/plugins/private/discord/commands/colmeio.json"
    )
    sync_policy = str(env.get("DISCORD_COMMAND_SYNC_POLICY") or "safe").strip().lower() or "safe"
    active_scope = _resolve_scope(sync_policy, args.scope)

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

    payloads = _build_command_payloads(commands_file)
    mode = str(args.mode or "post").strip().lower()
    guild_result = _get_existing_commands(app_id, guild_id, bot_token)
    guild_list = guild_result.get("data") if guild_result.get("ok") else []
    if not isinstance(guild_list, list):
        guild_list = []

    global_result = _get_existing_global_commands(app_id, bot_token)
    global_list = global_result.get("data") if global_result.get("ok") else []
    if not isinstance(global_list, list):
        global_list = []

    if active_scope == "global":
        overlap_names, conflicting_entries = _collect_overlaps(global_list, guild_list)
    else:
        overlap_names, conflicting_entries = _collect_overlaps(guild_list, global_list)

    unchanged: list[Dict[str, Any]] = []
    to_patch: list[tuple[Dict[str, Any], Dict[str, Any]]] = []
    to_create: list[Dict[str, Any]] = []
    global_to_delete: list[Dict[str, Any]] = []
    if active_scope == "guild":
        unchanged, to_patch, to_create = _build_deploy_plan(payloads, guild_list)
        if args.prune_global_overlaps:
            global_to_delete = [
                entry
                for entry in conflicting_entries
                if str(entry.get("id") or "").strip()
            ]

    if args.dry_run:
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": True,
                    "mode": mode,
                    "scope": active_scope,
                    "sync_policy": sync_policy,
                    "global_names": sorted(
                        str(item.get("name") or "").strip().lower()
                        for item in global_list
                        if isinstance(item, dict) and str(item.get("name") or "").strip()
                    ),
                    "guild_names": sorted(
                        str(item.get("name") or "").strip().lower()
                        for item in guild_list
                        if isinstance(item, dict) and str(item.get("name") or "").strip()
                    ),
                    "overlap_names": overlap_names,
                    "unchanged": [item["name"] for item in unchanged],
                    "to_patch": [desired["name"] for _current, desired in to_patch],
                    "to_create": [item["name"] for item in to_create],
                    "global_to_delete": [
                        _normalize_command_name(item.get("name"))
                        for item in global_to_delete
                    ],
                    "commands": payloads,
                },
                indent=2,
            )
        )
        return 0

    if not guild_result.get("ok"):
        print(json.dumps({"ok": False, "mode": mode, "scope": active_scope, "result": guild_result}, indent=2))
        return 1

    any_failure = False
    results: list[Dict[str, Any]] = []

    if active_scope == "global":
        print(
            json.dumps(
                {
                    "ok": not any_failure,
                    "mode": mode,
                    "scope": active_scope,
                    "sync_policy": sync_policy,
                    "summary": {
                        "skipped_guild_upserts": [item["name"] for item in payloads],
                        "overlap_names": overlap_names,
                    },
                    "results": [],
                },
                indent=2,
            )
        )
        return 1 if any_failure else 0

    if mode == "put":
        result = _run_with_retry(
            lambda: _api_request(
                method="PUT",
                url=_guild_commands_url(app_id, guild_id),
                bot_token=bot_token,
                payload=payloads,
            )
        )
        results.append(
            {
                **result,
                "operation": "put",
                "commands": [item["name"] for item in payloads],
            }
        )
        if not result.get("ok"):
            any_failure = True

        for entry in global_to_delete:
            command_id = str(entry.get("id") or "").strip()
            command_name = _normalize_command_name(entry.get("name"))
            result = _run_with_retry(
                lambda command_id=command_id: _delete_global_command(
                    app_id=app_id,
                    command_id=command_id,
                    bot_token=bot_token,
                )
            )
            result["command"] = command_name
            result["operation"] = "delete_global_overlap"
            results.append(result)
            if not result.get("ok"):
                any_failure = True

        print(
            json.dumps(
                {
                    "ok": not any_failure,
                    "mode": mode,
                    "scope": active_scope,
                    "sync_policy": sync_policy,
                    "summary": {
                        "overlap_names": overlap_names,
                        "deleted_global": [
                            _normalize_command_name(item.get("name"))
                            for item in global_to_delete
                        ],
                    },
                    "results": results,
                },
                indent=2,
            )
        )
        return 1 if any_failure else 0

    if mode == "post":
        for payload in payloads:
            result = _run_with_retry(
                lambda payload=payload: _create_command(
                    app_id=app_id,
                    guild_id=guild_id,
                    bot_token=bot_token,
                    payload=payload,
                )
            )
            result["command"] = payload["name"]
            results.append(result)
            if not result.get("ok"):
                any_failure = True

        for entry in global_to_delete:
            command_id = str(entry.get("id") or "").strip()
            command_name = _normalize_command_name(entry.get("name"))
            result = _run_with_retry(
                lambda command_id=command_id: _delete_global_command(
                    app_id=app_id,
                    command_id=command_id,
                    bot_token=bot_token,
                )
            )
            result["command"] = command_name
            result["operation"] = "delete_global_overlap"
            results.append(result)
            if not result.get("ok"):
                any_failure = True

        print(
            json.dumps(
                {
                    "ok": not any_failure,
                    "mode": mode,
                    "scope": active_scope,
                    "sync_policy": sync_policy,
                    "summary": {
                        "overlap_names": overlap_names,
                        "deleted_global": [
                            _normalize_command_name(item.get("name"))
                            for item in global_to_delete
                        ],
                    },
                    "results": results,
                },
                indent=2,
            )
        )
        return 1 if any_failure else 0

    for current, desired in to_patch:
        command_id = str(current.get("id") or "").strip()
        result = _run_with_retry(
            lambda command_id=command_id, desired=desired: _patch_command(
                app_id=app_id,
                guild_id=guild_id,
                command_id=command_id,
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
            lambda payload=payload: _create_command(
                app_id=app_id,
                guild_id=guild_id,
                bot_token=bot_token,
                payload=payload,
            )
        )
        result["command"] = payload["name"]
        result["operation"] = "create"
        results.append(result)
        if not result.get("ok"):
            any_failure = True

    for entry in global_to_delete:
        command_id = str(entry.get("id") or "").strip()
        command_name = _normalize_command_name(entry.get("name"))
        result = _run_with_retry(
            lambda command_id=command_id: _delete_global_command(
                app_id=app_id,
                command_id=command_id,
                bot_token=bot_token,
            )
        )
        result["command"] = command_name
        result["operation"] = "delete_global_overlap"
        results.append(result)
        if not result.get("ok"):
            any_failure = True

    print(
        json.dumps(
            {
                "ok": not any_failure,
                "mode": mode,
                "scope": active_scope,
                "sync_policy": sync_policy,
                "summary": {
                    "overlap_names": overlap_names,
                    "unchanged": [item["name"] for item in unchanged],
                    "patched": [desired["name"] for _current, desired in to_patch],
                    "created": [item["name"] for item in to_create],
                    "deleted_global": [
                        _normalize_command_name(item.get("name"))
                        for item in global_to_delete
                    ],
                },
                "results": results,
            },
            indent=2,
        )
    )
    return 1 if any_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
