#!/usr/bin/env bash
set -euo pipefail

python3 - "$@" <<'PY'
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_yaml(path: Path):
    import yaml
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data):
    import yaml
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _validate_command_name(name: str) -> str:
    cmd = str(name or "").strip().lower().lstrip("/")
    if not cmd:
        raise ValueError("command name is required")
    if len(cmd) > 32:
        raise ValueError("command name must be <= 32 chars")
    if not re.fullmatch(r"[a-z0-9_-]+", cmd):
        raise ValueError("command name must match [a-z0-9_-]+")
    return cmd


def _validate_custom_id(name: str) -> str:
    sid = str(name or "").strip()
    if not sid:
        raise ValueError("custom handler id is required")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        raise ValueError("custom handler id must match [A-Za-z0-9_-]+")
    return sid


def _default_description(command: str) -> str:
    return f"Comando /{command} (configure a descrição)"


def _handler_template(custom_id: str, command_name: str) -> str:
    return f'''from __future__ import annotations

from typing import Any, Dict


async def handle(
    *,
    adapter: Any,
    interaction: Any,
    command_name: str,
    option_values: Dict[str, Any],
    command_config: Dict[str, Any],
) -> bool:
    """Custom slash handler scaffold.

    Replace this implementation with your deterministic command logic.
    Return True when the interaction is fully handled.
    """

    # Example: read typed options
    # value = option_values.get("campo")

    msg = (
        "⚠️ Handler customizado ainda não implementado.\\n"
        f"handler_id: `{custom_id}`\\n"
        f"command: `/{command_name}`"
    )

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)

    return True
'''


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="new_command_scaffold.sh",
        description="Scaffold a new Discord slash command route for Colmeio runtime",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--name", required=True, help="Slash command name (without /)")
    parser.add_argument("--description", default="", help="Discord command description")
    parser.add_argument(
        "--mode",
        choices=("dispatch", "handler"),
        default="dispatch",
        help="dispatch = generic '/target --opts'; handler = custom Python handler",
    )
    parser.add_argument(
        "--dispatch-target",
        default="",
        help="Target command for dispatch mode (defaults to same command name)",
    )
    parser.add_argument(
        "--acl-command",
        default="",
        help="ACL command key for restricted channels (defaults to command name)",
    )
    parser.add_argument(
        "--handler-id",
        default="",
        help="Custom handler ID for handler mode (maps to custom_handlers/<id>.py)",
    )
    parser.add_argument(
        "--skip-discord-payload",
        action="store_true",
        help="Do not append command entry into commands/<node>.json",
    )
    parser.add_argument(
        "--node",
        default=str(__import__("os").getenv("NODE_NAME", "") or "").strip(),
        help="Node name for payload file commands/<node>.json (defaults to NODE_NAME env)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing registry route and handler file if they already exist",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing files")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run prestart reapply + verify after writing files",
    )

    args = parser.parse_args()

    os_mod = __import__("os")
    root = Path(os_mod.getenv("HERMES_DISCORD_PLUGIN_DIR", "/local/plugins/discord")).resolve()
    if not root.exists():
        legacy_root = Path("/local/workspace/discord")
        if legacy_root.exists():
            root = legacy_root.resolve()
    core_prestart = Path(
        os_mod.getenv("HERMES_CORE_PLUGIN_DIR", "/local/plugins/hermes-core")
    ).resolve() / "scripts" / "prestart_reapply.sh"
    if not core_prestart.exists():
        core_prestart = root / "scripts" / "prestart_reapply.sh"
    commands_dir = root / "commands"
    node_name = str(args.node or "").strip().lower()
    if node_name.endswith(".json"):
        node_name = node_name[:-5]
    commands_path = commands_dir / f"{node_name}.json" if node_name else None
    registry_path = root / "hooks" / "discord_slash_bridge" / "registry.yaml"
    custom_dir = root / "hooks" / "discord_slash_bridge" / "custom_handlers"

    command_name = _validate_command_name(args.name)
    description = str(args.description or "").strip() or _default_description(command_name)
    acl_command = _validate_command_name(args.acl_command or command_name)

    mode = args.mode
    dispatch_target = _validate_command_name(args.dispatch_target or command_name)
    handler_id = _validate_custom_id(args.handler_id or command_name)

    if not registry_path.exists():
        raise FileNotFoundError(f"registry.yaml not found: {registry_path}")
    if not args.skip_discord_payload and not node_name:
        raise RuntimeError("node name is required when editing payload (set --node or NODE_NAME)")

    commands = []
    if not args.skip_discord_payload:
        assert commands_path is not None
        commands_dir.mkdir(parents=True, exist_ok=True)
        if commands_path.exists():
            commands = _read_json(commands_path)
            if not isinstance(commands, list):
                raise RuntimeError(f"Invalid JSON payload format in {commands_path}: expected list")

    registry = _read_yaml(registry_path)
    if not isinstance(registry, dict):
        registry = {}

    slash_bridge = registry.setdefault("slash_bridge", {})
    if not isinstance(slash_bridge, dict):
        slash_bridge = {}
        registry["slash_bridge"] = slash_bridge

    commands_map = slash_bridge.setdefault("commands", {})
    if not isinstance(commands_map, dict):
        commands_map = {}
        slash_bridge["commands"] = commands_map

    existing_payload = next(
        (c for c in commands if isinstance(c, dict) and str(c.get("name") or "").strip() == command_name),
        None,
    )

    if existing_payload and not args.skip_discord_payload and not args.force:
        raise RuntimeError(
            f"Command '/{command_name}' already exists in {commands_path}. "
            "Use --skip-discord-payload or --force."
        )

    existing_route = commands_map.get(command_name)
    if existing_route is not None and not args.force:
        raise RuntimeError(
            f"Route '/{command_name}' already exists in registry.yaml. Use --force to overwrite."
        )

    route = {"acl_command": acl_command}
    if mode == "dispatch":
        route["dispatch"] = dispatch_target
    else:
        route["handler"] = f"custom:{handler_id}"

    handler_path = custom_dir / f"{handler_id}.py"

    # Build command payload entry.
    payload_entry = {
        "name": command_name,
        "description": description,
        "type": 1,
    }

    print("[plan] scaffold summary")
    print(f"  command_name: /{command_name}")
    print(f"  mode: {mode}")
    print(f"  route: {route}")
    print(f"  payload_edit: {'no' if args.skip_discord_payload else 'yes'}")
    if not args.skip_discord_payload:
        print(f"  payload_file: {commands_path}")
    if mode == "handler":
        print(f"  handler_file: {handler_path}")
    print(f"  dry_run: {'yes' if args.dry_run else 'no'}")

    if args.dry_run:
        print("\n[dry-run] no files were changed")
        return 0

    # Write payload entry.
    if not args.skip_discord_payload:
        assert commands_path is not None
        if existing_payload is not None and args.force:
            idx = commands.index(existing_payload)
            commands[idx] = payload_entry
        elif existing_payload is None:
            commands.append(payload_entry)
        _write_json(commands_path, commands)

    # Write route.
    commands_map[command_name] = route
    _write_yaml(registry_path, registry)

    # Write handler scaffold if needed.
    if mode == "handler":
        custom_dir.mkdir(parents=True, exist_ok=True)
        if handler_path.exists() and not args.force:
            print(f"[warn] handler file already exists, kept as-is: {handler_path}")
        else:
            handler_path.write_text(_handler_template(handler_id, command_name), encoding="utf-8")
            print(f"[ok] created handler scaffold: {handler_path}")

    print("\n[ok] scaffold written")
    print(f"  - {registry_path}")
    if not args.skip_discord_payload:
        print(f"  - {commands_path}")
    if mode == "handler" and handler_path.exists():
        print(f"  - {handler_path}")

    if args.apply:
        steps = [
            ["bash", str(core_prestart), "--strict"],
            ["python3", str(root / "scripts" / "verify_discord_customizations.py")],
        ]
        for step in steps:
            print(f"\n[run] {' '.join(step)}")
            proc = subprocess.run(step, check=False)
            if proc.returncode != 0:
                raise SystemExit(proc.returncode)

    print("\n[next]")
    print("  1) Register slash payload in Discord:")
    print(
        f"     bash {root / 'scripts' / 'register_discord_commands.sh'} {commands_path or '<commands/<node>.json>'}"
    )
    print("  2) Reapply + verify:")
    print(f"     bash {core_prestart} --strict")
    print(f"     python3 {root / 'scripts' / 'verify_discord_customizations.py'}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(1)
PY
