from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

_ENV_KEY = "DISCORD_ALLOWED_USERS"


def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


_HERMES_HOME = _resolve_hermes_home()

_ENV_PATHS = (
    _HERMES_HOME / ".env",
    Path("/local/.env"),
    Path("/local/workspace/.env"),
    Path("/local/workspace/colmeio/.env"),
)


def _normalize_discord_user_id(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""

    if text.startswith("<@") and text.endswith(">"):
        text = text[2:-1].strip()
        if text.startswith("!"):
            text = text[1:].strip()

    if text.lower().startswith("user:"):
        text = text[5:].strip()

    match = re.search(r"\d{5,}", text)
    if match:
        text = match.group(0)

    return text if text.isdigit() else ""


def _collect_runtime_allowed_ids(adapter: Any) -> set[str]:
    allowed: set[str] = set()

    current = getattr(adapter, "_allowed_user_ids", None)
    if isinstance(current, set):
        for entry in current:
            uid = _normalize_discord_user_id(entry)
            if uid:
                allowed.add(uid)

    env_raw = str(os.getenv(_ENV_KEY, "") or "")
    for entry in env_raw.split(","):
        uid = _normalize_discord_user_id(entry)
        if uid:
            allowed.add(uid)

    return allowed


def _append_user_to_env_file(path: Path, user_id: str) -> bool:
    if not path.exists():
        return False

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    out_lines: list[str] = []
    found = False
    changed = False

    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith(f"{_ENV_KEY}="):
            out_lines.append(line)
            continue

        found = True
        key, _, value = line.partition("=")
        entries = [part.strip() for part in value.split(",") if part.strip()]
        normalized = {_normalize_discord_user_id(part) for part in entries}
        if user_id not in normalized and user_id not in entries:
            entries.append(user_id)
            changed = True
        out_lines.append(f"{key}={','.join(entries)}")

    if not found:
        out_lines.append(f"{_ENV_KEY}={user_id}")
        changed = True

    if not changed:
        return False

    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return True


def _persist_allowed_user(user_id: str) -> list[str]:
    updated: list[str] = []
    for path in _ENV_PATHS:
        try:
            if _append_user_to_env_file(path, user_id):
                updated.append(str(path))
        except Exception as exc:
            logger.warning("Failed to persist paired user in %s: %s", path, exc)
    return updated


def _is_invoker_authorized(adapter: Any, interaction: Any) -> bool:
    user = getattr(interaction, "user", None)
    invoker_id = _normalize_discord_user_id(getattr(user, "id", ""))
    if not invoker_id:
        return False

    runner = getattr(adapter, "gateway_runner", None)
    checker = getattr(runner, "_is_user_authorized", None)
    build_event = getattr(adapter, "_build_slash_event", None)
    if callable(checker) and callable(build_event):
        try:
            event = build_event(interaction, "/status")
            source = getattr(event, "source", None)
            if source is not None:
                return bool(checker(source))
        except Exception as exc:
            logger.debug("pair auth via gateway runner failed: %s", exc)

    adapter_checker = getattr(adapter, "_is_allowed_user", None)
    if callable(adapter_checker):
        try:
            return bool(adapter_checker(invoker_id))
        except Exception as exc:
            logger.debug("pair auth fallback via adapter failed: %s", exc)

    allowed = getattr(adapter, "_allowed_user_ids", None)
    if isinstance(allowed, set):
        return (not allowed) or (invoker_id in allowed)

    return False


async def _resolve_user_label(adapter: Any, interaction: Any, user_id: str) -> str:
    guild = getattr(interaction, "guild", None)
    if guild is not None:
        try:
            member = guild.get_member(int(user_id))
            if member is None:
                member = await guild.fetch_member(int(user_id))
            if member is not None:
                return str(getattr(member, "display_name", "") or getattr(member, "name", "") or user_id)
        except Exception:
            pass

    client = getattr(adapter, "_client", None)
    if client is not None:
        try:
            user = await client.fetch_user(int(user_id))
            if user is not None:
                return str(getattr(user, "global_name", "") or getattr(user, "name", "") or user_id)
        except Exception:
            pass

    return user_id


def _approve_in_pairing_store(adapter: Any, user_id: str, user_name: str) -> bool:
    runner = getattr(adapter, "gateway_runner", None)
    store = getattr(runner, "pairing_store", None) if runner is not None else None
    approve = getattr(store, "_approve_user", None)
    if not callable(approve):
        return False
    try:
        approve("discord", user_id, user_name or "")
        return True
    except Exception as exc:
        logger.warning("Failed to update pairing store for discord user %s: %s", user_id, exc)
        return False


async def _send_ephemeral(interaction: Any, content: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


async def _edit_or_followup(interaction: Any, content: str) -> None:
    try:
        await interaction.edit_original_response(content=content)
    except Exception:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)


async def handle(
    *,
    adapter: Any,
    interaction: Any,
    command_name: str,
    option_values: Dict[str, Any],
    command_config: Dict[str, Any],
) -> bool:
    if not _is_invoker_authorized(adapter, interaction):
        await _send_ephemeral(
            interaction,
            "🚫 Você não tem permissão para usar `/pair`.",
        )
        return True

    raw_target = (
        option_values.get("discord_user_id")
        or option_values.get("user_id")
        or option_values.get("user")
        or ""
    )
    target_id = _normalize_discord_user_id(raw_target)
    if not target_id:
        await _send_ephemeral(
            interaction,
            "❌ Informe um `discord_user_id` válido (apenas números, ou menção `<@id>`).",
        )
        return True

    bot_user = getattr(getattr(adapter, "_client", None), "user", None)
    bot_id = _normalize_discord_user_id(getattr(bot_user, "id", ""))
    if bot_id and target_id == bot_id:
        await _send_ephemeral(interaction, "❌ Não é possível parear o próprio bot.")
        return True

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    allowed_ids = _collect_runtime_allowed_ids(adapter)
    already_allowed = target_id in allowed_ids
    allowed_ids.add(target_id)

    setattr(adapter, "_allowed_user_ids", allowed_ids)
    csv = ",".join(sorted(allowed_ids))
    os.environ[_ENV_KEY] = csv

    target_label = await _resolve_user_label(adapter, interaction, target_id)
    pairing_ok = _approve_in_pairing_store(adapter, target_id, target_label)
    updated_files = _persist_allowed_user(target_id)

    await _edit_or_followup(
        interaction,
        (
            "✅ Usuário pareado com sucesso.\n"
            f"user_id: `{target_id}`\n"
            f"user_name: `{target_label}`\n"
            f"já_autorizado: `{str(already_allowed).lower()}`\n"
            f"pairing_store: `{'updated' if pairing_ok else 'unavailable'}`\n"
            f"env_runtime: `{_ENV_KEY}` atualizado\n"
            f"persisted_files: `{len(updated_files)}`"
        ),
    )
    return True
