from __future__ import annotations

import asyncio
import re
from typing import Any, Dict

from discord import ThreadChannel


async def _send_ephemeral(interaction: Any, content: str) -> None:
    msg = str(content or "").strip()
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


async def _edit_or_followup(interaction: Any, content: str) -> None:
    msg = str(content or "").strip()
    try:
        await interaction.edit_original_response(content=msg)
    except Exception:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


def _sanitize_name(name: str) -> str:
    """Sanitize thread name to be Discord-compliant."""
    name = str(name or "").strip()
    # Discord thread name limits: 1-100 chars
    if len(name) > 100:
        name = name[:97] + "..."
    if len(name) < 1:
        name = "thread"
    # Remove problematic chars but keep spaces
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    return name


async def handle(
    *,
    adapter: Any,
    interaction: Any,
    command_name: str,
    option_values: Dict[str, Any],
    command_config: Dict[str, Any],
) -> bool:
    del adapter, command_name, command_config  # Unused.

    # Get thread name from options, default based on context
    raw_name = str(option_values.get("name") or "").strip()
    
    # Get channel
    channel = getattr(interaction, "channel", None)
    if not channel:
        await _send_ephemeral(interaction, "❌ Não consegui acessar o canal.")
        return True

    # Get the message if available (for creating thread from message)
    message = getattr(interaction, "message", None)

    # Determine thread name
    if raw_name:
        thread_name = _sanitize_name(raw_name)
    elif message:
        # Use first part of message content as name
        msg_content = str(getattr(message, "content", "") or "").strip()
        if msg_content:
            thread_name = _sanitize_name(msg_content[:80])
        else:
            thread_name = "thread"
    else:
        thread_name = "thread"

    # Determine auto archive duration (in minutes)
    # 60, 1440, 4320, 10080 are valid values
    auto_archive_minutes = 1440  # 24 hours default

    try:
        # Defer first to give time for thread creation
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        # Create the thread
        if isinstance(channel, ThreadChannel):
            # Already in a thread, can't create nested thread from thread
            await _edit_or_followup(
                interaction,
                "❌ Já estou dentro de um thread. Não posso criar thread dentro de thread.",
            )
            return True

        if message and hasattr(channel, "create_thread"):
            # Create thread from message
            thread = await channel.create_thread(
                name=thread_name,
                message=message,
                auto_archive_duration=auto_archive_minutes,
            )
        elif hasattr(channel, "create_thread"):
            # Create thread without message
            thread = await channel.create_thread(
                name=thread_name,
                auto_archive_duration=auto_archive_minutes,
            )
        else:
            await _edit_or_followup(
                interaction,
                "❌ Este tipo de canal não suporta criação de threads.",
            )
            return True

        # Success - return thread link
        thread_url = f"https://discord.com/channels/{thread.guild.id}/{thread.id}"
        
        await _edit_or_followup(
            interaction,
            f"✅ Thread criado: **{thread.name}**\n{thread_url}",
        )

    except Exception as exc:
        await _edit_or_followup(
            interaction,
            f"❌ Falha ao criar thread: {exc}",
        )

    return True
