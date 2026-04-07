#!/usr/bin/env python3
"""
Reapply Discord thread parent context propagation after hermes-agent updates.

Ensures SessionSource includes chat_id_alt (parent channel id) for thread messages
and slash commands, so channel ACL routing and /status channel info work in threads.
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
