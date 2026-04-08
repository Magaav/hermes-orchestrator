#!/usr/bin/env python3
"""
Verify that Colmeio Discord customizations are applied to hermes-agent.
"""

from __future__ import annotations

import os
import py_compile
import sys
import json
from pathlib import Path
import yaml

def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


WORKSPACE = Path(os.getenv("HERMES_DISCORD_PLUGIN_DIR", "/local/plugins/discord")).resolve()
if not WORKSPACE.exists():
    legacy_workspace = Path("/local/workspace/discord")
    if legacy_workspace.exists():
        WORKSPACE = legacy_workspace.resolve()
HERMES_HOME = _resolve_hermes_home()
RUN_PATH = HERMES_HOME / "hermes-agent" / "gateway" / "run.py"
DISCORD_PATH = HERMES_HOME / "hermes-agent" / "gateway" / "platforms" / "discord.py"
BASE_PATH = HERMES_HOME / "hermes-agent" / "gateway" / "platforms" / "base.py"

CHANNEL_ACL_SRC = WORKSPACE / "hooks" / "channel_acl"
CHANNEL_ACL_DST = HERMES_HOME / "hooks" / "channel_acl"

SESSION_INFO_SRC = WORKSPACE / "hooks" / "session_info_hook" / "handler.py"
SESSION_INFO_DST = HERMES_HOME / "hooks" / "session_info_hook"
SLASH_BRIDGE_SRC_DIR = WORKSPACE / "hooks" / "discord_slash_bridge"
SLASH_BRIDGE_DST_DIR = HERMES_HOME / "hooks" / "discord_slash_bridge"
SLASH_BRIDGE_CFG_SRC = SLASH_BRIDGE_SRC_DIR / "config.yaml"
SLASH_BRIDGE_CFG_DST = SLASH_BRIDGE_DST_DIR / "config.yaml"
SLASH_BRIDGE_REGISTRY_SRC = SLASH_BRIDGE_SRC_DIR / "registry.yaml"
SLASH_BRIDGE_REGISTRY_DST = SLASH_BRIDGE_DST_DIR / "registry.yaml"
SLASH_BRIDGE_HANDLERS_SRC = SLASH_BRIDGE_SRC_DIR / "handlers.py"
SLASH_BRIDGE_HANDLERS_DST = SLASH_BRIDGE_DST_DIR / "handlers.py"
SLASH_BRIDGE_RUNTIME_SRC = SLASH_BRIDGE_SRC_DIR / "runtime.py"
SLASH_BRIDGE_RUNTIME_DST = SLASH_BRIDGE_DST_DIR / "runtime.py"
DISCORD_COMMANDS_JSON = WORKSPACE / "discord_commands.json"


def _check(results: list[tuple[str, bool, str]], name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _contains_marker(results: list[tuple[str, bool, str]], text: str, label: str, marker: str) -> None:
    _check(results, label, marker in text, marker)


def _same_file(results: list[tuple[str, bool, str]], label: str, src: Path, dst: Path) -> None:
    if not src.exists():
        _check(results, label, False, f"missing source: {src}")
        return
    if not dst.exists():
        _check(results, label, False, f"missing destination: {dst}")
        return
    ok = src.read_bytes() == dst.read_bytes()
    _check(results, label, ok, f"{src} == {dst}")


def _exists(results: list[tuple[str, bool, str]], label: str, path: Path) -> None:
    _check(results, label, path.exists(), str(path))


def _compile(results: list[tuple[str, bool, str]], path: Path) -> None:
    label = f"python_compiles:{path.name}"
    try:
        py_compile.compile(str(path), doraise=True)
    except Exception as exc:
        _check(results, label, False, str(exc))
        return
    _check(results, label, True, str(path))


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    _exists(results, "run.py exists", RUN_PATH)
    _exists(results, "discord.py exists", DISCORD_PATH)
    _exists(results, "base.py exists", BASE_PATH)

    if BASE_PATH.exists():
        base_text = _read_text(BASE_PATH)
        _contains_marker(
            results,
            base_text,
            "base.py marker: pending_queue_deque",
            "self._pending_messages: Dict[str, Deque[MessageEvent]] = {}",
        )
        _contains_marker(
            results,
            base_text,
            "base.py marker: enqueue_pending_message",
            "def enqueue_pending_message(",
        )
        _contains_marker(
            results,
            base_text,
            "base.py marker: pop_pending_interrupt_message",
            "def pop_pending_interrupt_message(",
        )
        _contains_marker(
            results,
            base_text,
            "base.py marker: voice_audio_queue",
            "Queuing voice/audio follow-up for session",
        )
        _compile(results, BASE_PATH)

    if RUN_PATH.exists():
        run_text = _read_text(RUN_PATH)
        _contains_marker(results, run_text, "run.py marker: acl_normalize_block", "COLMEIO_CHANNEL_ACL_NORMALIZE_BEGIN")
        _contains_marker(results, run_text, "run.py marker: skill_add", "SKILL_ADD")
        _contains_marker(results, run_text, "run.py marker: author_id", "author_id:{source.user_id}")
        _contains_marker(results, run_text, "run.py marker: acl_model_block", "COLMEIO_CHANNEL_ACL_MODEL_BEGIN")
        _contains_marker(results, run_text, "run.py marker: system_prompt_addon", "system_prompt_addon")
        _contains_marker(results, run_text, "run.py marker: acl_status_block", "COLMEIO_CHANNEL_ACL_STATUS_BEGIN")
        _contains_marker(results, run_text, "run.py marker: status_route", "_fake_route = _enforce(source")
        _contains_marker(results, run_text, "run.py marker: status_channel_info", "**Channel Info**")
        _contains_marker(results, run_text, "run.py marker: status_model_routing", "**Model Routing**")
        _contains_marker(results, run_text, "run.py marker: acl_module", "colmeio_channel_acl")
        _contains_marker(
            results,
            run_text,
            "run.py marker: voice_audio_priority_queue",
            "PRIORITY voice/audio follow-up for session",
        )
        _contains_marker(
            results,
            run_text,
            "run.py marker: interrupt_pop_helper",
            "pop_pending_interrupt_message",
        )
        _contains_marker(
            results,
            run_text,
            "run.py marker: preserve_media_pending",
            "prepend_pending_message",
        )
        _compile(results, RUN_PATH)

    if DISCORD_PATH.exists():
        discord_text = _read_text(DISCORD_PATH)
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: guild_sync_hook",
            "COLMEIO_DISCORD_GUILD_SYNC_BEGIN",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: guild_sync_call",
            "tree.sync(guild=_guild)",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: guild_copy_global",
            "tree.copy_global_to(guild=_guild)",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: command_bootstrap_helper",
            "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_BEGIN",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: command_bootstrap_interaction",
            "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_INTERACTION_BEGIN",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: command_bootstrap_error",
            "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_ERROR_BEGIN",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: command_bootstrap_tree",
            "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_TREE_BEGIN",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: command_bootstrap_sync",
            "COLMEIO_DISCORD_COMMAND_BOOTSTRAP_SYNC_BEGIN",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: runtime_loader_method",
            "def _colmeio_load_discord_slash_runtime",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: runtime_interaction_method",
            "def _colmeio_runtime_on_interaction",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: runtime_error_method",
            "def _colmeio_runtime_on_app_command_error",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: runtime_bootstrap_method",
            "def _colmeio_runtime_bootstrap_tree",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: runtime_sync_call",
            "sync_external_payload_commands",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: runtime_tree_bootstrap_call",
            "self._colmeio_runtime_bootstrap_tree(tree)",
        )
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: slash_parent_channel",
            "parent_channel_id = self._get_parent_channel_id(interaction.channel) if is_thread else None",
        )
        _contains_marker(results, discord_text, "discord.py marker: dispatch_parent_channel", "chat_id_alt=_parent_channel_id or None")
        _contains_marker(
            results,
            discord_text,
            "discord.py marker: auto_thread_parent_channel",
            "parent_channel_id = self._get_parent_channel_id(thread) or str(message.channel.id)",
        )
        parent_count = discord_text.count("chat_id_alt=parent_channel_id")
        _check(
            results,
            "discord.py marker: parent_channel_in_sources",
            parent_count >= 2,
            f"chat_id_alt=parent_channel_id count={parent_count} (expected >= 2)",
        )
        _check(
            results,
            "discord.py marker: legacy_unknown_bridge_optional",
            True,
            "present" if "COLMEIO_DISCORD_UNKNOWN_SLASH_BEGIN" in discord_text else "not present",
        )
        _compile(results, DISCORD_PATH)

        # Legacy-only marker: older hermes versions rendered status in discord.py.
        # On newer versions this is expected to be absent, so keep it informational.
        legacy_session_info = "colmeio_session_info_hook" in discord_text
        _check(
            results,
            "discord.py marker: legacy_session_info_hook_optional",
            True,
            "present" if legacy_session_info else "not present (expected on newer upstream)",
        )

    _same_file(
        results,
        "channel_acl handler synced",
        CHANNEL_ACL_SRC / "handler.py",
        CHANNEL_ACL_DST / "handler.py",
    )
    _same_file(
        results,
        "channel_acl config synced",
        CHANNEL_ACL_SRC / "config.yaml",
        CHANNEL_ACL_DST / "config.yaml",
    )
    _same_file(
        results,
        "channel_acl manifest synced",
        CHANNEL_ACL_SRC / "HOOK.yaml",
        CHANNEL_ACL_DST / "HOOK.yaml",
    )

    _exists(results, "session_info handler exists", SESSION_INFO_DST / "handler.py")
    _exists(results, "session_info manifest exists", SESSION_INFO_DST / "HOOK.yaml")
    _same_file(results, "session_info handler synced", SESSION_INFO_SRC, SESSION_INFO_DST / "handler.py")
    _same_file(results, "slash_bridge config synced", SLASH_BRIDGE_CFG_SRC, SLASH_BRIDGE_CFG_DST)
    _same_file(results, "slash_bridge registry synced", SLASH_BRIDGE_REGISTRY_SRC, SLASH_BRIDGE_REGISTRY_DST)
    _same_file(results, "slash_bridge handlers synced", SLASH_BRIDGE_HANDLERS_SRC, SLASH_BRIDGE_HANDLERS_DST)
    _same_file(results, "slash_bridge runtime synced", SLASH_BRIDGE_RUNTIME_SRC, SLASH_BRIDGE_RUNTIME_DST)

    _exists(results, "slash_bridge runtime exists", SLASH_BRIDGE_RUNTIME_DST)
    _exists(results, "slash_bridge handlers exists", SLASH_BRIDGE_HANDLERS_DST)
    _compile(results, SLASH_BRIDGE_RUNTIME_SRC)
    _compile(results, SLASH_BRIDGE_HANDLERS_SRC)
    if SLASH_BRIDGE_RUNTIME_DST.exists():
        _compile(results, SLASH_BRIDGE_RUNTIME_DST)
    if SLASH_BRIDGE_HANDLERS_DST.exists():
        _compile(results, SLASH_BRIDGE_HANDLERS_DST)

    # Command payload assertions (/metricas active, legacy /metrics removed)
    if DISCORD_COMMANDS_JSON.exists():
        try:
            payload = json.loads(DISCORD_COMMANDS_JSON.read_text(encoding="utf-8"))
            names = [str(c.get("name") or "").strip() for c in payload if isinstance(c, dict)]
            _check(results, "discord_commands has /metricas", "metricas" in names, f"names={sorted(names)}")
            _check(results, "discord_commands has no /metrics", "metrics" not in names, f"names={sorted(names)}")
        except Exception as exc:
            _check(results, "discord_commands payload parse", False, str(exc))
    else:
        _check(results, "discord_commands.json exists", False, str(DISCORD_COMMANDS_JSON))

    # Model native override assertions (/model deterministic choices)
    _contains_marker(
        results,
        _read_text(SLASH_BRIDGE_RUNTIME_SRC) if SLASH_BRIDGE_RUNTIME_SRC.exists() else "",
        "slash_bridge runtime marker: bootstrap_model_method",
        "def _bootstrap_model(",
    )
    _contains_marker(
        results,
        _read_text(SLASH_BRIDGE_RUNTIME_SRC) if SLASH_BRIDGE_RUNTIME_SRC.exists() else "",
        "slash_bridge runtime marker: bootstrap_model_call",
        "self._bootstrap_model(tree, native.get(\"model\") or {})",
    )
    _contains_marker(
        results,
        _read_text(SLASH_BRIDGE_HANDLERS_SRC) if SLASH_BRIDGE_HANDLERS_SRC.exists() else "",
        "slash_bridge handlers marker: handle_model_switch",
        "async def handle_model_switch(",
    )

    if SLASH_BRIDGE_REGISTRY_SRC.exists():
        try:
            registry = yaml.safe_load(SLASH_BRIDGE_REGISTRY_SRC.read_text(encoding="utf-8")) or {}
            native = registry.get("native_overrides") if isinstance(registry, dict) else {}
            model_cfg = native.get("model") if isinstance(native, dict) else {}
            choices = model_cfg.get("choices") if isinstance(model_cfg, dict) else []
            choice_keys = {
                str(item.get("key") or "").strip()
                for item in choices
                if isinstance(item, dict)
            }
            required = {"gpt54", "nemotron120b", "minimaxm27", "kimik25"}
            _check(
                results,
                "slash_bridge registry has native /model",
                isinstance(model_cfg, dict),
                f"present={isinstance(model_cfg, dict)}",
            )
            _check(
                results,
                "slash_bridge registry model choices keys",
                required.issubset(choice_keys),
                f"keys={sorted(choice_keys)}",
            )
        except Exception as exc:
            _check(results, "slash_bridge registry model parse", False, str(exc))
    else:
        _check(results, "slash_bridge registry model exists", False, str(SLASH_BRIDGE_REGISTRY_SRC))

    failed = [r for r in results if not r[1]]

    for name, ok, detail in results:
        status = "OK  " if ok else "FAIL"
        print(f"[{status}] {name}")
        if detail:
            print(f"       {detail}")

    print()
    print(f"checks: {len(results)}")
    print(f"failed: {len(failed)}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
