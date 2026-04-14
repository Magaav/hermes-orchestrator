#!/usr/bin/env python3
"""
Reapply Discord auto-thread-ignore channel behavior after hermes-agent updates.

Adds support for DISCORD_AUTO_THREAD_IGNORE_CHANNELS in discord.py:
- Channels in the list become mention-free (bot can reply inline without @mention).
- Auto-thread still happens only when the bot is explicitly @mentioned.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


HERMES_HOME = _resolve_hermes_home()
_ENV_AGENT_ROOT = str(os.getenv("HERMES_AGENT_ROOT", "") or "").strip()

DISCORD_PATH_CANDIDATES = (
    *((
        Path(_ENV_AGENT_ROOT).expanduser() / "gateway" / "platforms" / "discord.py",
    ) if _ENV_AGENT_ROOT else ()),
    Path("/local/hermes-agent/gateway/platforms/discord.py"),
    HERMES_HOME / "hermes-agent" / "gateway" / "platforms" / "discord.py",
    Path("/local/.hermes/hermes-agent/gateway/platforms/discord.py"),
    Path("/home/ubuntu/.hermes/hermes-agent/gateway/platforms/discord.py"),
)


def _find_discord_py() -> Path:
    for path in DISCORD_PATH_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(
        "Could not find discord.py in expected locations:\n"
        + "\n".join(f"- {p}" for p in DISCORD_PATH_CANDIDATES)
    )


def _find_function_bounds(content: str, signature: str) -> tuple[int, int]:
    start = content.find(signature)
    if start == -1:
        raise RuntimeError(f"function signature not found: {signature}")

    next_async = content.find("\n    async def ", start + len(signature))
    next_def = content.find("\n    def ", start + len(signature))

    candidates = [p for p in (next_async, next_def) if p != -1]
    end = min(candidates) if candidates else len(content)
    return start, end


OLD_MENTION_BLOCK = """\
            free_channels_raw = os.getenv("DISCORD_FREE_RESPONSE_CHANNELS", "")
            free_channels = {ch.strip() for ch in free_channels_raw.split(",") if ch.strip()}
            if parent_channel_id:
                channel_ids.add(parent_channel_id)

            require_mention = os.getenv("DISCORD_REQUIRE_MENTION", "true").lower() not in ("false", "0", "no")
            is_free_channel = bool(channel_ids & free_channels)

            # Skip the mention check if the message is in a thread where
            # the bot has previously participated (auto-created or replied in).
            in_bot_thread = is_thread and thread_id in self._bot_participated_threads

            if require_mention and not is_free_channel and not in_bot_thread:
                if self._client.user not in message.mentions:
                    return

            if self._client.user and self._client.user in message.mentions:
                message.content = message.content.replace(f"<@{self._client.user.id}>", "").strip()
                message.content = message.content.replace(f"<@!{self._client.user.id}>", "").strip()
"""


NEW_MENTION_BLOCK = """\
            free_channels_raw = os.getenv("DISCORD_FREE_RESPONSE_CHANNELS", "")
            free_channels = {ch.strip() for ch in free_channels_raw.split(",") if ch.strip()}
            auto_thread_ignore_channels_raw = os.getenv("DISCORD_AUTO_THREAD_IGNORE_CHANNELS", "")
            auto_thread_ignore_channels = {
                ch.strip() for ch in auto_thread_ignore_channels_raw.split(",") if ch.strip()
            }
            if parent_channel_id:
                channel_ids.add(parent_channel_id)

            require_mention = os.getenv("DISCORD_REQUIRE_MENTION", "true").lower() not in ("false", "0", "no")
            is_auto_thread_ignore_channel = bool(channel_ids & auto_thread_ignore_channels)
            is_free_channel = bool(channel_ids & free_channels) or is_auto_thread_ignore_channel

            # Skip the mention check if the message is in a thread where
            # the bot has previously participated (auto-created or replied in).
            in_bot_thread = is_thread and thread_id in self._bot_participated_threads
            bot_mentioned = bool(self._client.user and self._client.user in message.mentions)

            if require_mention and not is_free_channel and not in_bot_thread:
                if not bot_mentioned:
                    return

            if bot_mentioned:
                message.content = message.content.replace(f"<@{self._client.user.id}>", "").strip()
                message.content = message.content.replace(f"<@!{self._client.user.id}>", "").strip()
"""


OLD_THREAD_BLOCK = """\
            no_thread_channels_raw = os.getenv("DISCORD_NO_THREAD_CHANNELS", "")
            no_thread_channels = {ch.strip() for ch in no_thread_channels_raw.split(",") if ch.strip()}
            skip_thread = bool(channel_ids & no_thread_channels)
"""


NEW_THREAD_BLOCK = """\
            no_thread_channels_raw = os.getenv("DISCORD_NO_THREAD_CHANNELS", "")
            no_thread_channels = {ch.strip() for ch in no_thread_channels_raw.split(",") if ch.strip()}
            auto_thread_ignore_channels_raw = os.getenv("DISCORD_AUTO_THREAD_IGNORE_CHANNELS", "")
            auto_thread_ignore_channels = {
                ch.strip() for ch in auto_thread_ignore_channels_raw.split(",") if ch.strip()
            }
            explicit_bot_mention = bool(
                self._client.user
                and (
                    f"<@{self._client.user.id}>" in (message.content or "")
                    or f"<@!{self._client.user.id}>" in (message.content or "")
                )
            )
            skip_thread_for_auto_thread_ignore = (
                bool(channel_ids & auto_thread_ignore_channels) and not explicit_bot_mention
            )
            skip_thread = bool(channel_ids & no_thread_channels) or skip_thread_for_auto_thread_ignore
"""


def _patch_handle_message(section: str) -> tuple[str, bool]:
    changed = False

    if OLD_MENTION_BLOCK in section:
        section = section.replace(OLD_MENTION_BLOCK, NEW_MENTION_BLOCK, 1)
        changed = True
    else:
        raise RuntimeError("_handle_message mention/free-response block anchor not found")

    old_patched_thread_block = """\
            auto_thread_ignore_channels_raw = os.getenv("DISCORD_AUTO_THREAD_IGNORE_CHANNELS", "")
            auto_thread_ignore_channels = {
                ch.strip() for ch in auto_thread_ignore_channels_raw.split(",") if ch.strip()
            }
            bot_mentioned = bool(self._client.user and self._client.user in message.mentions)
            skip_thread_for_auto_thread_ignore = (
                bool(channel_ids & auto_thread_ignore_channels) and not bot_mentioned
            )
"""
    if old_patched_thread_block in section:
        new_patched_thread_block = """\
            auto_thread_ignore_channels_raw = os.getenv("DISCORD_AUTO_THREAD_IGNORE_CHANNELS", "")
            auto_thread_ignore_channels = {
                ch.strip() for ch in auto_thread_ignore_channels_raw.split(",") if ch.strip()
            }
            explicit_bot_mention = bool(
                self._client.user
                and (
                    f"<@{self._client.user.id}>" in (message.content or "")
                    or f"<@!{self._client.user.id}>" in (message.content or "")
                )
            )
            skip_thread_for_auto_thread_ignore = (
                bool(channel_ids & auto_thread_ignore_channels) and not explicit_bot_mention
            )
"""
        section = section.replace(old_patched_thread_block, new_patched_thread_block, 1)
        changed = True
    elif OLD_THREAD_BLOCK in section:
        section = section.replace(OLD_THREAD_BLOCK, NEW_THREAD_BLOCK, 1)
        changed = True
    elif "skip_thread_for_auto_thread_ignore" not in section:
        raise RuntimeError("_handle_message auto-thread block anchor not found")

    return section, changed


def reapply() -> int:
    try:
        discord_path = _find_discord_py()
    except Exception as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    content = discord_path.read_text(encoding="utf-8")
    original = content

    try:
        sig = "    async def _handle_message(self, message: DiscordMessage) -> None:\n"
        start, end = _find_function_bounds(content, sig)
        section, changed = _patch_handle_message(content[start:end])
        if changed:
            content = content[:start] + section + content[end:]
    except Exception as exc:
        print(f"❌ Failed to patch discord.py (auto-thread ignore channels): {exc}", file=sys.stderr)
        return 1

    if content == original:
        print("✅ Discord auto-thread-ignore-channel patch already applied.")
        return 0

    backup_dir = HERMES_HOME / "logs" / "patch-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"discord.py.auto_thread_ignore_channels.{stamp}.bak"
    backup.write_text(original, encoding="utf-8")

    discord_path.write_text(content, encoding="utf-8")
    print(f"✅ Applied Discord auto-thread-ignore-channel patch to: {discord_path}")
    print(f"   Backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(reapply())
