from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def _send_ephemeral(interaction: Any, content: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


async def _edit_ephemeral(interaction: Any, content: str) -> None:
    try:
        await interaction.edit_original_response(content=content)
    except Exception:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)


def _is_confirmed(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in {"true", "1", "yes", "y", "sim", "s"}


def _user_can_clean(interaction: Any) -> bool:
    user = getattr(interaction, "user", None)
    perms = getattr(user, "guild_permissions", None)
    if perms is None:
        # DMs or edge cases: rely on global DISCORD_ALLOWED_USERS guard.
        return True
    return bool(getattr(perms, "administrator", False) or getattr(perms, "manage_messages", False))


async def _bot_can_clean(adapter: Any, interaction: Any, channel: Any) -> tuple[bool, str]:
    guild = getattr(interaction, "guild", None)
    if guild is None:
        return True, ""

    bot = getattr(adapter, "_client", None)
    if bot is None or getattr(bot, "user", None) is None:
        return False, "cliente do bot indisponível"

    me = getattr(guild, "me", None)
    if me is None:
        try:
            me = guild.get_member(bot.user.id)
        except Exception:
            me = None
    if me is None:
        try:
            me = await guild.fetch_member(bot.user.id)
        except Exception:
            me = None

    if me is None or not hasattr(channel, "permissions_for"):
        return False, "não consegui resolver permissões do bot no canal/thread"

    perms = channel.permissions_for(me)
    ok = bool(getattr(perms, "administrator", False) or getattr(perms, "manage_messages", False))
    if not ok:
        return False, "faltando permissão `Manage Messages` para o bot"
    return True, ""


def _classify_delete_error(exc: Exception) -> str:
    text = str(exc or "").lower()
    if "system message" in text or "cannot delete" in text:
        return "undeletable"
    if "missing permissions" in text or "403" in text or "50013" in text:
        return "permission"
    return "other"


async def handle(
    *,
    adapter: Any,
    interaction: Any,
    command_name: str,
    option_values: Dict[str, Any],
    command_config: Dict[str, Any],
) -> bool:
    confirmed = _is_confirmed(option_values.get("confirm"))
    if not confirmed:
        await _send_ephemeral(
            interaction,
            "⚠️ Ação destrutiva bloqueada. Use `/clean confirm:true` para confirmar a limpeza total.",
        )
        return True

    channel = getattr(interaction, "channel", None)
    if channel is None:
        await _send_ephemeral(interaction, "❌ Não consegui identificar o canal para limpar.")
        return True

    if not _user_can_clean(interaction):
        await _send_ephemeral(
            interaction,
            "🚫 Você precisa de permissão de administrador ou `Manage Messages` para usar `/clean`.",
        )
        return True

    bot_ok, bot_reason = await _bot_can_clean(adapter, interaction, channel)
    if not bot_ok:
        await _send_ephemeral(
            interaction,
            "❌ Eu preciso da permissão `Manage Messages` neste canal/thread para executar `/clean`.\n"
            f"detalhe: {bot_reason}",
        )
        return True

    if not hasattr(channel, "history"):
        await _send_ephemeral(interaction, "❌ Este tipo de canal não suporta limpeza de histórico.")
        return True

    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        started = time.monotonic()
        deleted = 0
        failed = 0
        skipped_undeletable = 0
        first_error = ""

        async for msg in channel.history(limit=None, oldest_first=True):
            try:
                await msg.delete()
                deleted += 1
                if deleted % 25 == 0:
                    await asyncio.sleep(0)
            except Exception as exc:
                kind = _classify_delete_error(exc)
                if kind == "undeletable":
                    skipped_undeletable += 1
                else:
                    failed += 1
                    if not first_error:
                        first_error = str(exc)
                # Keep logs short to avoid spam for large channels.
                if failed + skipped_undeletable <= 5:
                    logger.debug("/clean failed to delete message %s: %s", getattr(msg, "id", "?"), exc)

        elapsed = time.monotonic() - started

        channel_name = str(getattr(channel, "name", "canal") or "canal")
        channel_id = str(getattr(channel, "id", "") or "")
        kind = "thread" if hasattr(channel, "parent_id") and getattr(channel, "parent_id", None) else "canal"

        summary = (
            f"✅ Limpeza concluída no {kind} `{channel_name}`.\n"
            f"channel_id: `{channel_id}`\n"
            f"apagadas: `{deleted}`\n"
            f"falhas: `{failed}`\n"
            f"não-apagáveis: `{skipped_undeletable}`\n"
            f"tempo: `{elapsed:.1f}s`"
        )
        if first_error:
            summary += f"\nprimeiro erro: `{first_error[:220]}`"
        if skipped_undeletable:
            summary += (
                "\nnota: saídas efêmeras de slash (`Only you can see this`) e alguns "
                "itens de sistema não podem ser apagados por bot."
            )
        await _edit_ephemeral(interaction, summary)
        return True
    except Exception as exc:
        logger.warning("/clean handler failed: %s", exc, exc_info=True)
        await _edit_ephemeral(interaction, f"❌ Falha ao executar `/clean`: {exc}")
        return True
