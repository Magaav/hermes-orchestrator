#!/usr/bin/env python3
"""Sync node Discord role ACL (fail-closed slash authorization map)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

import yaml


SCRIPT_PATH = Path(__file__).resolve()
PLUGIN_ROOT = SCRIPT_PATH.parents[1]
ROLE_ACL_PATH = PLUGIN_ROOT / "hooks" / "discord_slash_bridge" / "role_acl.py"


def _load_role_acl_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("colmeio_discord_role_acl", ROLE_ACL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load role_acl module from {ROLE_ACL_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


role_acl = _load_role_acl_module()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_command_set(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cmd = role_acl.normalize_command_name(value)
        if not cmd or cmd in seen:
            continue
        seen.add(cmd)
        out.append(cmd)
    return sorted(out)


def _normalize_node_name(value: str) -> str:
    return role_acl.normalize_node_name(value)


def _default_private_root() -> Path:
    configured = str(os.getenv("HERMES_DISCORD_PRIVATE_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path("/local/plugins/private/discord")


def _default_guild_id() -> str:
    return str(os.getenv("DISCORD_SERVER_ID", "") or os.getenv("DISCORD_GUILD_ID", "")).strip()


def _resolve_node_commands_path(private_root: Path, node_name: str) -> Path:
    configured = str(os.getenv("DISCORD_COMMANDS_FILE", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return private_root / "commands" / f"{node_name}.json"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return parsed if isinstance(parsed, dict) else {}


def _discover_gateway_registry_commands() -> list[str]:
    agent_root = Path(str(os.getenv("HERMES_AGENT_ROOT", "") or "/local/hermes-agent")).expanduser()
    if not (agent_root / "hermes_cli" / "commands.py").exists():
        return []

    if str(agent_root) not in sys.path:
        sys.path.insert(0, str(agent_root))

    try:
        from hermes_cli.commands import COMMAND_REGISTRY  # type: ignore

        names: list[str] = []
        for cmd_def in COMMAND_REGISTRY:
            name = role_acl.normalize_command_name(getattr(cmd_def, "name", ""))
            if name:
                names.append(name)
        return _normalize_command_set(names)
    except Exception:
        return []


def discover_command_inventory(private_root: Path, node_name: str) -> list[str]:
    commands: list[str] = []
    commands.extend(role_acl.DEFAULT_CORE_SLASH_COMMANDS)

    commands.append("skill")

    payload_path = _resolve_node_commands_path(private_root, node_name)
    if payload_path.exists():
        try:
            payload = _load_json(payload_path)
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        commands.append(item.get("name"))
        except Exception:
            pass

    registry_path = private_root / "hooks" / "discord_slash_bridge" / "registry.yaml"
    registry = _load_yaml(registry_path)

    slash_bridge = registry.get("slash_bridge") if isinstance(registry.get("slash_bridge"), dict) else {}
    bridge_commands = slash_bridge.get("commands") if isinstance(slash_bridge.get("commands"), dict) else {}
    commands.extend(list(bridge_commands.keys()))

    native = registry.get("native_overrides") if isinstance(registry.get("native_overrides"), dict) else {}
    for key, cfg in native.items():
        block = cfg if isinstance(cfg, dict) else {}
        if block.get("enabled", True) is False:
            continue
        if key == "backup":
            commands.append(block.get("group_name") or block.get("command_name") or "backup")
        else:
            commands.append(key)

    commands.extend(_discover_gateway_registry_commands())
    return _normalize_command_set(commands)


def _fetch_discord_roles(token: str, guild_id: str, timeout_sec: float = 8.0) -> list[Dict[str, Any]]:
    import urllib.request

    req = urllib.request.Request(
        f"https://discord.com/api/v10/guilds/{guild_id}/roles",
        headers={"Authorization": f"Bot {token}", "User-Agent": "hermes-discord-role-acl-sync/1.0"},
        method="GET",
    )

    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        body = resp.read().decode("utf-8", errors="ignore")

    parsed = json.loads(body)
    if not isinstance(parsed, list):
        raise ValueError("unexpected Discord roles response shape")

    out: list[Dict[str, Any]] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        role_id = str(entry.get("id") or "").strip()
        role_name = str(entry.get("name") or "").strip()
        if not role_id:
            continue
        try:
            position = int(entry.get("position") or 0)
        except Exception:
            position = 0
        out.append({"role_id": role_id, "role_name": role_name, "position": position})

    out.sort(key=lambda item: int(item.get("position", 0)), reverse=True)
    return out


def _fallback_hierarchy_from_env() -> list[Dict[str, Any]]:
    raw = str(os.getenv("DISCORD_ROLE_ACL_FALLBACK_HIERARCHY", "") or "").strip()
    names = [part.strip() for part in raw.split(",") if part.strip()] if raw else list(role_acl.DEFAULT_FALLBACK_HIERARCHY)
    out: list[Dict[str, Any]] = []
    for name in names:
        out.append({"role_id": "", "role_name": str(name).strip()})
    out.append({"role_id": "@everyone", "role_name": "@everyone"})
    return out


def _existing_hierarchy(acl: Dict[str, Any]) -> list[Dict[str, Any]]:
    hierarchy = acl.get("hierarchy") if isinstance(acl.get("hierarchy"), list) else []
    if not hierarchy:
        return []
    normalized = role_acl.normalize_acl({"hierarchy": hierarchy}).get("hierarchy") or []
    return [dict(item) for item in normalized if isinstance(item, dict)]


def _merge_hierarchy(
    *,
    fetched: list[Dict[str, Any]],
    existing: list[Dict[str, Any]],
    fallback: list[Dict[str, Any]],
) -> tuple[list[Dict[str, Any]], str]:
    has_existing_roles = any(
        role_acl.normalize_role_token(entry.get("role_id") or "") != "@everyone"
        or str(entry.get("role_name") or "").strip().lower() not in {"", "@everyone"}
        for entry in existing
        if isinstance(entry, dict)
    )

    if fetched:
        seed = [dict(item) for item in fetched]
        source = "discord_role_position"
    elif existing and has_existing_roles:
        seed = [dict(item) for item in existing]
        source = "existing_acl"
    else:
        seed = [dict(item) for item in fallback]
        source = "fallback_defaults"

    seen: set[str] = set()
    merged: list[Dict[str, Any]] = []

    def _append(entry: Dict[str, Any]) -> None:
        rid = role_acl.normalize_role_token(entry.get("role_id") or "")
        rname = str(entry.get("role_name") or "").strip().lower()
        key = rid or ("name:" + rname if rname else "")
        if not key or key in seen:
            return
        seen.add(key)
        merged.append(
            {
                "role_id": "@everyone" if rid == "@everyone" else (rid if rid and not rid.startswith("name:") else ""),
                "role_name": "@everyone" if rid == "@everyone" or rname == "@everyone" else str(entry.get("role_name") or "").strip(),
            }
        )

    for item in seed:
        if isinstance(item, dict):
            _append(item)
    for item in existing:
        if isinstance(item, dict):
            _append(item)

    if "@everyone" not in seen:
        merged.append({"role_id": "@everyone", "role_name": "@everyone"})

    return merged, source


def _discover_safe_commands() -> list[str]:
    raw = str(os.getenv("DISCORD_ROLE_ACL_SAFE_COMMANDS", "") or "").strip()
    if raw:
        return _normalize_command_set(raw.split(","))
    return _normalize_command_set(role_acl.DEFAULT_SAFE_COMMANDS)


def _merge_commands(
    *,
    existing: Dict[str, Any],
    discovered: list[str],
    safe_commands: list[str],
    acl_admin_role: str,
) -> tuple[Dict[str, Dict[str, Any]], list[str]]:
    existing_map = existing if isinstance(existing, dict) else {}
    commands: Dict[str, Dict[str, Any]] = {}

    for key, cfg in existing_map.items():
        cmd = role_acl.normalize_command_name(key)
        if not cmd:
            continue
        block = cfg if isinstance(cfg, dict) else {}
        commands[cmd] = dict(block)

    added_unmapped: list[str] = []

    for cmd in discovered:
        if cmd not in commands:
            commands[cmd] = {}
            added_unmapped.append(cmd)

        block = commands[cmd]
        min_role = role_acl.normalize_role_token(block.get("min_role") or "")
        if not min_role and cmd in safe_commands:
            block["min_role"] = "@everyone"
            block.setdefault("notes", "auto-seeded safe command")
        if cmd == "acl" and (not min_role or min_role == "@everyone"):
            block["min_role"] = acl_admin_role
            block.setdefault("notes", "auto-seeded ACL management command")

    # keep any custom/manual commands already present even if not currently discovered
    ordered = sorted(commands.items(), key=lambda item: item[0])
    return {k: v for k, v in ordered}, sorted(added_unmapped)


def _resolve_acl_admin_role(hierarchy: list[Dict[str, Any]]) -> str:
    for entry in hierarchy:
        role_name = str(entry.get("role_name") or "").strip().lower()
        if role_name != "admin":
            continue
        token = role_acl.normalize_role_token(entry.get("role_id") or "")
        if token and token != "@everyone":
            return token
        if role_name:
            return f"name:{role_name}"

    for entry in hierarchy:
        token = role_acl.normalize_role_token(entry.get("role_id") or "")
        if token and token != "@everyone":
            return token
        role_name = str(entry.get("role_name") or "").strip().lower()
        if role_name and role_name != "@everyone":
            return f"name:{role_name}"

    return "@everyone"


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _build_payload(
    *,
    node_name: str,
    guild_id: str,
    hierarchy: list[Dict[str, Any]],
    commands: Dict[str, Dict[str, Any]],
    safe_commands: list[str],
    user_overrides: Dict[str, Any],
    seed_source: str,
) -> Dict[str, Any]:
    return role_acl.normalize_acl(
        {
            "version": 1,
            "node": node_name,
            "guild_id": guild_id,
            "updated_at": _utc_now_iso(),
            "seed_source": seed_source,
            "safe_commands": safe_commands,
            "policy": {
                "unmapped_command": "deny",
            },
            "hierarchy": hierarchy,
            "commands": commands,
            "user_overrides": user_overrides,
        },
        node_name=node_name,
        guild_id=guild_id,
    )


def sync_acl(
    *,
    node_name: str,
    guild_id: str,
    private_root: Path,
    acl_path: Path,
    check_only: bool,
    strict_live_roles: bool,
) -> Dict[str, Any]:
    existing = role_acl.load_acl(acl_path) if acl_path.exists() else {}

    discovered_commands = discover_command_inventory(private_root, node_name)
    safe_commands = _discover_safe_commands()

    bot_token = str(os.getenv("DISCORD_BOT_TOKEN", "") or "").strip()
    fetched_roles: list[Dict[str, Any]] = []
    fetch_error = ""

    if bot_token:
        try:
            fetched_roles = _fetch_discord_roles(bot_token, guild_id)
        except Exception as exc:
            fetch_error = str(exc)
    else:
        fetch_error = "DISCORD_BOT_TOKEN is empty"

    if strict_live_roles and not fetched_roles and not _existing_hierarchy(existing):
        raise SystemExit(f"[error] failed to fetch Discord roles in strict mode: {fetch_error or 'unknown error'}")

    hierarchy, seed_source = _merge_hierarchy(
        fetched=fetched_roles,
        existing=_existing_hierarchy(existing),
        fallback=_fallback_hierarchy_from_env(),
    )
    acl_admin_role = _resolve_acl_admin_role(hierarchy)

    merged_commands, added_unmapped = _merge_commands(
        existing=existing.get("commands") if isinstance(existing, dict) else {},
        discovered=discovered_commands,
        safe_commands=safe_commands,
        acl_admin_role=acl_admin_role,
    )

    user_overrides = existing.get("user_overrides") if isinstance(existing.get("user_overrides"), dict) else {}

    payload = _build_payload(
        node_name=node_name,
        guild_id=guild_id,
        hierarchy=hierarchy,
        commands=merged_commands,
        safe_commands=safe_commands,
        user_overrides=user_overrides,
        seed_source=seed_source,
    )

    changed = True
    if acl_path.exists():
        try:
            current = role_acl.normalize_acl(_load_json(acl_path), node_name=node_name, guild_id=guild_id)
            changed = current != payload
        except Exception:
            changed = True

    wrote = False
    if not check_only and (changed or not acl_path.exists()):
        _atomic_write_json(acl_path, payload)
        wrote = True

    unmapped = sorted(
        cmd
        for cmd, cfg in payload.get("commands", {}).items()
        if not role_acl.normalize_role_token((cfg or {}).get("min_role") if isinstance(cfg, dict) else "")
    )

    return {
        "ok": True,
        "action": "discord-role-acl-sync",
        "node": node_name,
        "guild_id": guild_id,
        "acl_path": str(acl_path),
        "private_root": str(private_root),
        "check_only": check_only,
        "changed": bool(changed),
        "wrote": wrote,
        "seed_source": seed_source,
        "roles_fetched": len(fetched_roles),
        "roles_fetch_error": fetch_error,
        "commands_discovered": discovered_commands,
        "commands_total": len(payload.get("commands") or {}),
        "added_unmapped_commands": added_unmapped,
        "unmapped_commands": unmapped,
        "safe_commands": safe_commands,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Discord role ACL for slash commands")
    parser.add_argument("--node-name", default=os.getenv("NODE_NAME", ""))
    parser.add_argument("--guild-id", default=_default_guild_id())
    parser.add_argument("--private-root", default=str(_default_private_root()))
    parser.add_argument("--acl-path", default="")
    parser.add_argument("--check", action="store_true", help="Validate/report only; do not write")
    parser.add_argument(
        "--strict-live-roles",
        action="store_true",
        help="Fail when live Discord role fetch is unavailable and no existing hierarchy is present",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    node_name = _normalize_node_name(args.node_name)
    guild_id = str(args.guild_id or "").strip()
    if not guild_id:
        raise SystemExit("[error] missing guild id: set DISCORD_SERVER_ID or DISCORD_GUILD_ID")

    private_root = Path(str(args.private_root)).expanduser()
    if str(args.acl_path or "").strip():
        acl_path = Path(str(args.acl_path)).expanduser()
    else:
        acl_path = role_acl.resolve_acl_path(node_name=node_name, private_root=private_root)

    payload = sync_acl(
        node_name=node_name,
        guild_id=guild_id,
        private_root=private_root,
        acl_path=acl_path,
        check_only=bool(args.check),
        strict_live_roles=bool(args.strict_live_roles),
    )

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
