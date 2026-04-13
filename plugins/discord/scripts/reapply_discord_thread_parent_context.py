#!/usr/bin/env python3
"""
Reapply Discord thread parent context propagation after hermes-agent updates.

Ensures SessionSource includes chat_id_alt (parent channel id) for thread messages
and slash commands, so channel ACL routing and /status channel info work in threads.

Also enforces DISCORD_AUTO_THREAD_IGNORE_CHANNELS behavior:
- listed channels become mention-free for inline replies
- those channels only auto-thread on explicit @mention
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


def _patch_build_slash_event(section: str) -> tuple[str, bool]:
    changed = False

    parent_line = "        parent_channel_id = self._get_parent_channel_id(interaction.channel) if is_thread else None\n"
    if parent_line not in section:
        anchor = "        thread_id = None\n\n        if is_dm:\n"
        if anchor not in section:
            raise RuntimeError("_build_slash_event anchor not found for parent_channel_id insertion")
        section = section.replace(
            anchor,
            "        thread_id = None\n" + parent_line + "\n        if is_dm:\n",
            1,
        )
        changed = True

    if "chat_id_alt=parent_channel_id," not in section:
        anchor = "            thread_id=thread_id,\n            chat_topic=chat_topic,\n        )"
        if anchor not in section:
            raise RuntimeError("_build_slash_event build_source anchor not found for chat_id_alt insertion")
        section = section.replace(
            anchor,
            "            thread_id=thread_id,\n            chat_topic=chat_topic,\n            chat_id_alt=parent_channel_id,\n        )",
            1,
        )
        changed = True

    return section, changed


def _patch_dispatch_thread_session(section: str) -> tuple[str, bool]:
    changed = False

    parent_var = '        _parent_channel_id = str(getattr(interaction, "channel_id", "") or "")\n'
    if parent_var not in section:
        anchor = '        chat_name = f"{guild_name} / {thread_name}" if guild_name else thread_name\n\n'
        if anchor not in section:
            raise RuntimeError("_dispatch_thread_session anchor not found for _parent_channel_id insertion")
        section = section.replace(
            anchor,
            '        chat_name = f"{guild_name} / {thread_name}" if guild_name else thread_name\n'
            + parent_var
            + "\n",
            1,
        )
        changed = True

    if "chat_id_alt=_parent_channel_id or None," not in section:
        anchor = "            thread_id=thread_id,\n        )"
        if anchor not in section:
            raise RuntimeError("_dispatch_thread_session build_source anchor not found for chat_id_alt insertion")
        section = section.replace(
            anchor,
            "            thread_id=thread_id,\n            chat_id_alt=_parent_channel_id or None,\n        )",
            1,
        )
        changed = True

    return section, changed


def _patch_handle_message(section: str) -> tuple[str, bool]:
    changed = False

    parent_assign = "                    parent_channel_id = self._get_parent_channel_id(thread) or str(message.channel.id)\n"
    if parent_assign not in section:
        anchor = (
            "                    auto_threaded_channel = thread\n"
            "                    self._track_thread(thread_id)\n"
        )
        if anchor not in section:
            raise RuntimeError("_handle_message auto-thread anchor not found for parent_channel_id insertion")
        section = section.replace(
            anchor,
            "                    auto_threaded_channel = thread\n"
            + parent_assign
            + "                    self._track_thread(thread_id)\n",
            1,
        )
        changed = True

    # Hybrid auto-thread behavior:
    # - messages in listed channels can be inline without @mention
    # - only explicit @mentions should auto-thread
    if "DISCORD_AUTO_THREAD_IGNORE_CHANNELS" not in section:
        old_mention_block = (
            '            free_channels_raw = os.getenv("DISCORD_FREE_RESPONSE_CHANNELS", "")\n'
            '            free_channels = {ch.strip() for ch in free_channels_raw.split(",") if ch.strip()}\n'
            "            if parent_channel_id:\n"
            "                channel_ids.add(parent_channel_id)\n"
            "\n"
            '            require_mention = os.getenv("DISCORD_REQUIRE_MENTION", "true").lower() not in ("false", "0", "no")\n'
            "            is_free_channel = bool(channel_ids & free_channels)\n"
            "\n"
            "            # Skip the mention check if the message is in a thread where\n"
            "            # the bot has previously participated (auto-created or replied in).\n"
            "            in_bot_thread = is_thread and thread_id in self._bot_participated_threads\n"
            "\n"
            "            if require_mention and not is_free_channel and not in_bot_thread:\n"
            "                if self._client.user not in message.mentions:\n"
            "                    return\n"
            "\n"
            "            if self._client.user and self._client.user in message.mentions:\n"
            '                message.content = message.content.replace(f"<@{self._client.user.id}>", "").strip()\n'
            '                message.content = message.content.replace(f"<@!{self._client.user.id}>", "").strip()\n'
        )
        new_mention_block = (
            '            free_channels_raw = os.getenv("DISCORD_FREE_RESPONSE_CHANNELS", "")\n'
            '            free_channels = {ch.strip() for ch in free_channels_raw.split(",") if ch.strip()}\n'
            '            auto_thread_ignore_channels_raw = os.getenv("DISCORD_AUTO_THREAD_IGNORE_CHANNELS", "")\n'
            "            auto_thread_ignore_channels = {\n"
            '                ch.strip() for ch in auto_thread_ignore_channels_raw.split(",") if ch.strip()\n'
            "            }\n"
            "            if parent_channel_id:\n"
            "                channel_ids.add(parent_channel_id)\n"
            "\n"
            '            require_mention = os.getenv("DISCORD_REQUIRE_MENTION", "true").lower() not in ("false", "0", "no")\n'
            "            is_auto_thread_ignore_channel = bool(channel_ids & auto_thread_ignore_channels)\n"
            "            is_free_channel = bool(channel_ids & free_channels) or is_auto_thread_ignore_channel\n"
            "\n"
            "            # Skip the mention check if the message is in a thread where\n"
            "            # the bot has previously participated (auto-created or replied in).\n"
            "            in_bot_thread = is_thread and thread_id in self._bot_participated_threads\n"
            "            bot_mentioned = bool(self._client.user and self._client.user in message.mentions)\n"
            "\n"
            "            if require_mention and not is_free_channel and not in_bot_thread:\n"
            "                if not bot_mentioned:\n"
            "                    return\n"
            "\n"
            "            if bot_mentioned:\n"
            '                message.content = message.content.replace(f"<@{self._client.user.id}>", "").strip()\n'
            '                message.content = message.content.replace(f"<@!{self._client.user.id}>", "").strip()\n'
        )
        if old_mention_block not in section:
            raise RuntimeError("_handle_message mention/free-response block anchor not found for auto-thread-ignore patch")
        section = section.replace(old_mention_block, new_mention_block, 1)
        changed = True

    if "skip_thread_for_auto_thread_ignore" not in section:
        old_thread_block = (
            '            no_thread_channels_raw = os.getenv("DISCORD_NO_THREAD_CHANNELS", "")\n'
            '            no_thread_channels = {ch.strip() for ch in no_thread_channels_raw.split(",") if ch.strip()}\n'
            "            skip_thread = bool(channel_ids & no_thread_channels)\n"
        )
        new_thread_block = (
            '            no_thread_channels_raw = os.getenv("DISCORD_NO_THREAD_CHANNELS", "")\n'
            '            no_thread_channels = {ch.strip() for ch in no_thread_channels_raw.split(",") if ch.strip()}\n'
            '            auto_thread_ignore_channels_raw = os.getenv("DISCORD_AUTO_THREAD_IGNORE_CHANNELS", "")\n'
            "            auto_thread_ignore_channels = {\n"
            '                ch.strip() for ch in auto_thread_ignore_channels_raw.split(",") if ch.strip()\n'
            "            }\n"
            "            explicit_bot_mention = bool(\n"
            "                self._client.user\n"
            "                and (\n"
            '                    f"<@{self._client.user.id}>" in (message.content or "")\n'
            '                    or f"<@!{self._client.user.id}>" in (message.content or "")\n'
            "                )\n"
            "            )\n"
            "            skip_thread_for_auto_thread_ignore = (\n"
            "                bool(channel_ids & auto_thread_ignore_channels) and not explicit_bot_mention\n"
            "            )\n"
            "            skip_thread = bool(channel_ids & no_thread_channels) or skip_thread_for_auto_thread_ignore\n"
        )
        if old_thread_block not in section:
            raise RuntimeError("_handle_message no-thread block anchor not found for auto-thread-ignore patch")
        section = section.replace(old_thread_block, new_thread_block, 1)
        changed = True
    elif "explicit_bot_mention" not in section:
        old_patched_thread_block = (
            '            auto_thread_ignore_channels_raw = os.getenv("DISCORD_AUTO_THREAD_IGNORE_CHANNELS", "")\n'
            "            auto_thread_ignore_channels = {\n"
            '                ch.strip() for ch in auto_thread_ignore_channels_raw.split(",") if ch.strip()\n'
            "            }\n"
            "            bot_mentioned = bool(self._client.user and self._client.user in message.mentions)\n"
            "            skip_thread_for_auto_thread_ignore = (\n"
            "                bool(channel_ids & auto_thread_ignore_channels) and not bot_mentioned\n"
            "            )\n"
        )
        if old_patched_thread_block not in section:
            raise RuntimeError("_handle_message old auto-thread-ignore block not found for explicit-mention upgrade")
        new_patched_thread_block = (
            '            auto_thread_ignore_channels_raw = os.getenv("DISCORD_AUTO_THREAD_IGNORE_CHANNELS", "")\n'
            "            auto_thread_ignore_channels = {\n"
            '                ch.strip() for ch in auto_thread_ignore_channels_raw.split(",") if ch.strip()\n'
            "            }\n"
            "            explicit_bot_mention = bool(\n"
            "                self._client.user\n"
            "                and (\n"
            '                    f"<@{self._client.user.id}>" in (message.content or "")\n'
            '                    or f"<@!{self._client.user.id}>" in (message.content or "")\n'
            "                )\n"
            "            )\n"
            "            skip_thread_for_auto_thread_ignore = (\n"
            "                bool(channel_ids & auto_thread_ignore_channels) and not explicit_bot_mention\n"
            "            )\n"
        )
        section = section.replace(old_patched_thread_block, new_patched_thread_block, 1)
        changed = True

    if "chat_id_alt=parent_channel_id," not in section:
        anchor = "            thread_id=thread_id,\n            chat_topic=chat_topic,\n        )"
        if anchor not in section:
            raise RuntimeError("_handle_message build_source anchor not found for chat_id_alt insertion")

        section = section.replace(
            anchor,
            "            thread_id=thread_id,\n            chat_topic=chat_topic,\n            chat_id_alt=parent_channel_id,\n        )",
            1,
        )
        changed = True

    return section, changed


def reapply() -> int:
    try:
        discord_path = _find_discord_py()
    except Exception as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    content = discord_path.read_text(encoding="utf-8")
    original = content
    changed_any = False

    try:
        # Patch _build_slash_event
        sig = "    def _build_slash_event(self, interaction: discord.Interaction, text: str) -> MessageEvent:\n"
        start, end = _find_function_bounds(content, sig)
        section, changed = _patch_build_slash_event(content[start:end])
        if changed:
            content = content[:start] + section + content[end:]
            changed_any = True

        # Patch _dispatch_thread_session
        sig = (
            "    async def _dispatch_thread_session(\n"
            "        self,\n"
            "        interaction: discord.Interaction,\n"
            "        thread_id: str,\n"
            "        thread_name: str,\n"
            "        text: str,\n"
            "    ) -> None:\n"
        )
        start, end = _find_function_bounds(content, sig)
        section, changed = _patch_dispatch_thread_session(content[start:end])
        if changed:
            content = content[:start] + section + content[end:]
            changed_any = True

        # Patch _handle_message
        sig = "    async def _handle_message(self, message: DiscordMessage) -> None:\n"
        start, end = _find_function_bounds(content, sig)
        section, changed = _patch_handle_message(content[start:end])
        if changed:
            content = content[:start] + section + content[end:]
            changed_any = True

    except Exception as exc:
        print(f"❌ Failed to patch discord.py (thread parent context): {exc}", file=sys.stderr)
        return 1

    if not changed_any:
        print("✅ Discord thread parent context already applied.")
        return 0

    backup_dir = HERMES_HOME / "logs" / "patch-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"discord.py.thread_parent_context.{stamp}.bak"
    backup.write_text(original, encoding="utf-8")

    discord_path.write_text(content, encoding="utf-8")
    print(f"✅ Applied Discord thread parent context patch to: {discord_path}")
    print(f"   Backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(reapply())
