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

def _candidate_agent_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    if _ENV_AGENT_ROOT:
        roots.append(Path(_ENV_AGENT_ROOT).expanduser())
    if HERMES_HOME.name == ".hermes":
        roots.append(HERMES_HOME.parent / "hermes-agent")
    roots.append(Path("/local/hermes-agent"))

    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        out.append(root)
    return tuple(out)


DISCORD_PATH_CANDIDATES = tuple(root / "gateway" / "platforms" / "discord.py" for root in _candidate_agent_roots())


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


def _patch_handle_message(section: str) -> tuple[str, bool]:
    changed = False

    if "DISCORD_AUTO_THREAD_IGNORE_CHANNELS" not in section:
        anchors = (
            "            free_channels = self._discord_free_response_channels()\n",
            '            free_channels = {ch.strip() for ch in free_channels_raw.split(",") if ch.strip()}\n',
        )
        for anchor in anchors:
            if anchor in section:
                inject = (
                    anchor
                    + '            auto_thread_ignore_channels_raw = os.getenv("DISCORD_AUTO_THREAD_IGNORE_CHANNELS", "")\n'
                    + "            auto_thread_ignore_channels = {\n"
                    + '                ch.strip() for ch in auto_thread_ignore_channels_raw.split(",") if ch.strip()\n'
                    + "            }\n"
                )
                section = section.replace(anchor, inject, 1)
                changed = True
                break
        else:
            raise RuntimeError("_handle_message free-channel anchor not found")

    old_free = (
        "            is_free_channel = bool(channel_ids & free_channels) or is_voice_linked_channel\n"
    )
    new_free = (
        "            is_auto_thread_ignore_channel = bool(channel_ids & auto_thread_ignore_channels)\n"
        "            is_free_channel = (\n"
        "                bool(channel_ids & free_channels)\n"
        "                or is_voice_linked_channel\n"
        "                or is_auto_thread_ignore_channel\n"
        "            )\n"
    )
    if old_free in section:
        section = section.replace(old_free, new_free, 1)
        changed = True

    old_mention = (
        "            if require_mention and not is_free_channel and not in_bot_thread:\n"
        "                if self._client.user not in message.mentions:\n"
        "                    return\n"
        "\n"
        "            if self._client.user and self._client.user in message.mentions:\n"
    )
    new_mention = (
        "            bot_mentioned = bool(self._client.user and self._client.user in message.mentions)\n"
        "\n"
        "            if require_mention and not is_free_channel and not in_bot_thread:\n"
        "                if not bot_mentioned:\n"
        "                    return\n"
        "\n"
        "            if bot_mentioned:\n"
    )
    if old_mention in section:
        section = section.replace(old_mention, new_mention, 1)
        changed = True

    old_thread = (
        '            no_thread_channels_raw = os.getenv("DISCORD_NO_THREAD_CHANNELS", "")\n'
        '            no_thread_channels = {ch.strip() for ch in no_thread_channels_raw.split(",") if ch.strip()}\n'
        "            skip_thread = bool(channel_ids & no_thread_channels)\n"
    )
    old_thread_current = (
        '            no_thread_channels_raw = os.getenv("DISCORD_NO_THREAD_CHANNELS", "")\n'
        '            no_thread_channels = {ch.strip() for ch in no_thread_channels_raw.split(",") if ch.strip()}\n'
        "            skip_thread = bool(channel_ids & no_thread_channels) or is_free_channel\n"
    )
    new_thread = (
        '            no_thread_channels_raw = os.getenv("DISCORD_NO_THREAD_CHANNELS", "")\n'
        '            no_thread_channels = {ch.strip() for ch in no_thread_channels_raw.split(",") if ch.strip()}\n'
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
    if old_thread in section:
        section = section.replace(old_thread, new_thread, 1)
        changed = True
    elif old_thread_current in section:
        section = section.replace(old_thread_current, new_thread, 1)
        changed = True

    if "skip_thread_for_auto_thread_ignore" not in section:
        raise RuntimeError("_handle_message auto-thread-ignore block anchor not found")

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
