"""Native Discord slash command extensions."""

from __future__ import annotations

import asyncio
import contextvars
import importlib.util
import json
import logging
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Dict

from .paths import (
    resolve_discord_commands_file,
    resolve_faltas_pipeline_script,
    resolve_legacy_bridge_handlers_path,
    resolve_metrics_script_path,
    resolve_python_bin,
)

logger = logging.getLogger(__name__)

_LEGACY_HANDLERS_MODULE: Any = None
_CURRENT_GATEWAY_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "discord_slash_commands_gateway_context",
    default=None,
)


def _collect_registration_status() -> Dict[str, Any]:
    payload_path = resolve_discord_commands_file()
    payload_commands = _load_payload_commands()
    payload_names = [
        str(entry.get("name") or "").strip().lower()
        for entry in payload_commands
        if isinstance(entry, dict) and str(entry.get("name") or "").strip()
    ]
    requested = ["metricas", "faltas"]
    missing = [name for name in requested if name not in payload_names]

    metrics_script = resolve_metrics_script_path()
    faltas_script = resolve_faltas_pipeline_script()

    return {
        "node_name": str(Path(payload_path).stem or ""),
        "payload_path": str(payload_path),
        "payload_exists": payload_path.exists(),
        "payload_names": payload_names,
        "requested_commands": requested,
        "missing_payload_commands": missing,
        "metrics_script_path": str(metrics_script),
        "metrics_script_exists": metrics_script.exists(),
        "faltas_pipeline_path": str(faltas_script),
        "faltas_pipeline_exists": faltas_script.exists(),
        "discord_app_id": str(os.getenv("DISCORD_APP_ID", "") or ""),
        "discord_server_id": str(os.getenv("DISCORD_SERVER_ID", "") or ""),
    }


def _format_registration_status(status: Dict[str, Any]) -> str:
    payload_names = ", ".join(status.get("payload_names") or []) or "(none)"
    missing = ", ".join(status.get("missing_payload_commands") or []) or "(none)"
    return "\n".join(
        [
            "Discord slash registration status",
            f"- node: {status.get('node_name') or '(unknown)'}",
            f"- payload: {status.get('payload_path')} exists={bool(status.get('payload_exists'))}",
            f"- payload commands: {payload_names}",
            f"- requested commands: {', '.join(status.get('requested_commands') or [])}",
            f"- missing from payload: {missing}",
            f"- metrics script: {status.get('metrics_script_path')} exists={bool(status.get('metrics_script_exists'))}",
            f"- faltas pipeline: {status.get('faltas_pipeline_path')} exists={bool(status.get('faltas_pipeline_exists'))}",
            f"- discord app id: {status.get('discord_app_id') or '(unset)'}",
            f"- discord server id: {status.get('discord_server_id') or '(unset)'}",
        ]
    )


def _log_registration_status() -> None:
    status = _collect_registration_status()
    logger.info(
        "discord-slash-commands register_plugin: node=%s payload=%s exists=%s payload_names=%s requested=%s missing=%s metrics_script_exists=%s faltas_pipeline_exists=%s app_id=%s guild_id=%s",
        status.get("node_name") or "",
        status.get("payload_path") or "",
        bool(status.get("payload_exists")),
        ",".join(status.get("payload_names") or []),
        ",".join(status.get("requested_commands") or []),
        ",".join(status.get("missing_payload_commands") or []),
        bool(status.get("metrics_script_exists")),
        bool(status.get("faltas_pipeline_exists")),
        status.get("discord_app_id") or "",
        status.get("discord_server_id") or "",
    )
    if status.get("missing_payload_commands"):
        logger.warning(
            "discord-slash-commands payload is missing command specs for: %s",
            ", ".join(status["missing_payload_commands"]),
        )


def _load_module(module_key: str, module_path: Path, cache_name: str) -> Any:
    cached = globals().get(cache_name)
    if cached is not None:
        return cached

    if not module_path.exists():
        raise FileNotFoundError(f"module source not found: {module_path}")

    spec = importlib.util.spec_from_file_location(module_key, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    globals()[cache_name] = module
    return module


def _load_legacy_handlers() -> Any:
    return _load_module(
        "native_discord_slash_commands_legacy_handlers",
        resolve_legacy_bridge_handlers_path(),
        "_LEGACY_HANDLERS_MODULE",
    )


def _load_payload_commands() -> list[dict[str, Any]]:
    payload_path = resolve_discord_commands_file()
    if not payload_path.exists():
        logger.debug("Discord commands payload not found: %s", payload_path)
        return []

    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to parse Discord commands payload %s: %s", payload_path, exc)
        return []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _payload_command_spec(command_name: str) -> dict[str, Any]:
    clean = str(command_name or "").strip().lower()
    for entry in _load_payload_commands():
        if str(entry.get("name") or "").strip().lower() == clean:
            return entry
    return {}


def _split_command_text(message: str) -> tuple[str, str]:
    text = str(message or "").strip()
    if not text.startswith("/"):
        return "", ""
    parts = text.split(maxsplit=1)
    command = parts[0].lower().lstrip("/")
    args = parts[1].strip() if len(parts) > 1 else ""
    return command, args


def _source_platform_value(source: Any) -> str:
    platform = getattr(source, "platform", None)
    return str(getattr(platform, "value", platform) or "").strip().lower()


def handle_pre_gateway_dispatch(
    *,
    event: Any = None,
    gateway: Any = None,
    **_: Any,
) -> None:
    source = getattr(event, "source", None)
    if source is None or _source_platform_value(source) != "discord":
        return None

    _CURRENT_GATEWAY_CONTEXT.set(
        {
            "event": event,
            "gateway": gateway,
            "source": source,
            "interaction": getattr(event, "raw_message", None),
        }
    )
    return None


def _current_gateway_context() -> dict[str, Any]:
    value = _CURRENT_GATEWAY_CONTEXT.get()
    return value if isinstance(value, dict) else {}


def _quote_command_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.search(r"[\s\"']", text):
        return json.dumps(text, ensure_ascii=False)
    return text


def _build_metricas_command_text(*, formato: str = "", dias: Any = None, skill: str = "") -> str:
    parts = ["/metricas"]
    if formato:
        parts.append(f"formato:{_quote_command_value(formato)}")
    if dias not in (None, ""):
        parts.append(f"dias:{dias}")
    if str(skill or "").strip():
        parts.append(f"skill:{_quote_command_value(skill)}")
    return " ".join(parts).strip()


def _build_faltas_command_text(
    *,
    action: str = "",
    loja: str = "",
    itens: str = "",
    formato: str = "",
    confirm: str = "",
) -> str:
    parts = ["/faltas"]
    if action:
        parts.append(f"action:{_quote_command_value(action)}")
    if loja:
        parts.append(f"loja:{_quote_command_value(loja)}")
    if itens:
        parts.append(f"itens:{_quote_command_value(itens)}")
    if formato:
        parts.append(f"formato:{_quote_command_value(formato)}")
    if confirm:
        parts.append(f"confirm:{_quote_command_value(confirm)}")
    return " ".join(parts).strip()


def _interaction_option_map(interaction: Any) -> Dict[str, str]:
    data = getattr(interaction, "data", None)
    if not isinstance(data, dict):
        return {}

    result: Dict[str, str] = {}

    def _walk(options: Any) -> None:
        if not isinstance(options, list):
            return
        for item in options:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip().lower()
            value = item.get("value")
            if name and value not in (None, ""):
                result[name] = str(value)
            _walk(item.get("options"))

    _walk(data.get("options"))
    return result


def _resolve_faltas_raw_args(raw_args: str, interaction: Any = None) -> str:
    text = str(raw_args or "").strip()
    if text:
        return text

    option_map = _interaction_option_map(interaction)
    if not option_map:
        return ""

    parts = []
    for key in ("action", "loja", "itens", "formato", "confirm", "args"):
        value = str(option_map.get(key) or "").strip()
        if not value:
            continue
        if key == "args":
            parts.append(value)
        else:
            parts.append(f"{key}:{_quote_command_value(value)}")
    return " ".join(parts).strip()


def _resolve_metricas_raw_args(raw_args: str, interaction: Any = None) -> str:
    text = str(raw_args or "").strip()
    if text:
        return text

    option_map = _interaction_option_map(interaction)
    if not option_map:
        return ""

    parts = []
    for key in ("dias", "formato", "skill", "args"):
        value = str(option_map.get(key) or "").strip()
        if not value:
            continue
        if key == "args":
            parts.append(value)
        else:
            parts.append(f"{key}:{_quote_command_value(value)}")
    return " ".join(parts).strip()


def parse_metricas_args(raw_args: str) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "dias": 30,
        "formato": "text",
        "skill": "",
    }
    for token in shlex.split(str(raw_args or "").strip()):
        piece = token.strip()
        if not piece:
            continue
        if ":" in piece:
            key, value = piece.split(":", 1)
        elif "=" in piece:
            key, value = piece.split("=", 1)
        else:
            key, value = "dias", piece
        normalized_key = str(key or "").strip().lower().replace("-", "_")
        if normalized_key in {"dia", "dias", "days"}:
            try:
                values["dias"] = int(str(value or "").strip())
            except Exception:
                logger.debug("Ignoring invalid dias value for /metricas: %r", value)
        elif normalized_key in {"formato", "format", "fmt"}:
            values["formato"] = str(value or "").strip().lower() or "text"
        elif normalized_key in {"skill", "habilidade"}:
            values["skill"] = str(value or "").strip()
    return values


async def handle_metricas(raw_args: str) -> str:
    gateway_context = _current_gateway_context()
    interaction = gateway_context.get("interaction")
    options = parse_metricas_args(_resolve_metricas_raw_args(raw_args, interaction))
    handlers = _load_legacy_handlers()
    settings = {
        "script_path": str(resolve_metrics_script_path()),
        "timeout_sec": 45,
    }
    text, _is_error = await handlers.run_metrics_dashboard(
        interaction,
        "metricas",
        options,
        settings=settings,
    )
    return str(text or "Dashboard de métricas executado.")


async def handle_discord_slash_status(_raw_args: str) -> str:
    return _format_registration_status(_collect_registration_status())


def parse_faltas_args(raw_args: str) -> Dict[str, str]:
    values: Dict[str, str] = {
        "action": "",
        "loja": "",
        "itens": "",
        "formato": "",
        "confirm": "",
    }

    for token in shlex.split(str(raw_args or "").strip()):
        piece = token.strip()
        if not piece:
            continue
        if ":" in piece:
            key, value = piece.split(":", 1)
        elif "=" in piece:
            key, value = piece.split("=", 1)
        elif not values["action"]:
            key, value = "action", piece
        else:
            key, value = "itens", piece

        normalized_key = str(key or "").strip().lower().replace("-", "_")
        if normalized_key in values:
            if normalized_key == "itens" and values["itens"]:
                values["itens"] = f"{values['itens']} {value}".strip()
            else:
                values[normalized_key] = str(value or "").strip()
    return values


def _normalize_faltas_action(raw: str) -> str:
    key = str(raw or "").strip().lower()
    mapping = {
        "list": "listar",
        "listar": "listar",
        "sync": "listar",
        "sincronizar": "listar",
        "add": "adicionar",
        "adicionar": "adicionar",
        "remove": "remover",
        "remover": "remover",
        "rm": "remover",
        "clear": "limpar",
        "limpar": "limpar",
        "help": "help",
        "ajuda": "help",
    }
    return mapping.get(key, key)


def _normalize_faltas_store(raw: str) -> str:
    key = str(raw or "").strip().lower()
    mapping = {
        "1": "loja1",
        "l1": "loja1",
        "loja1": "loja1",
        "2": "loja2",
        "l2": "loja2",
        "loja2": "loja2",
        "ambas": "ambas",
        "todas": "ambas",
    }
    return mapping.get(key, "")


def _normalize_faltas_format(raw: str) -> str:
    key = str(raw or "").strip().lower()
    mapping = {
        "links": "links",
        "link": "links",
        "excel": "excel",
        "xlsx": "excel",
        "texto": "texto",
        "text": "texto",
        "txt": "texto",
    }
    return mapping.get(key, "links")


def _format_faltas_usage() -> str:
    return (
        "Uso do `/faltas`:\n"
        "- `/faltas action:listar loja:loja1 formato:links`\n"
        "- `/faltas action:adicionar itens:\"produto\" loja:loja2`\n"
        "- `/faltas action:remover itens:\"produto\" loja:loja1`\n"
        "- `/faltas action:limpar confirm:sim`\n"
        "- ações: `listar`, `adicionar`, `remover`, `limpar`, `help`"
    )


def _truncate(text: str, limit: int = 1900) -> str:
    clean = str(text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)] + "..."


def _render_faltas_list_response(payload: Dict[str, Any], output_format: str) -> str:
    data = payload.get("data") if isinstance(payload, dict) else {}
    stores = data.get("stores") if isinstance(data, dict) else {}
    if not isinstance(stores, dict) or not stores:
        return "Lista consultada sem dados."

    if output_format in {"links", "excel"}:
        lines = ["Faltas por loja"]
        for store in ("loja1", "loja2"):
            summary = stores.get(store) if isinstance(stores.get(store), dict) else {}
            if not summary:
                continue
            url = str(summary.get("sheet_url") or "").strip()
            total = int(summary.get("total_items") or 0)
            if url:
                lines.append(f"- {store}: {url} (itens: {total})")
            else:
                lines.append(f"- {store}: sem link configurado (itens: {total})")
        return "\n".join(lines)

    lines = ["Faltas por loja"]
    for store in ("loja1", "loja2"):
        summary = stores.get(store) if isinstance(stores.get(store), dict) else {}
        if not summary:
            continue
        items = summary.get("items") if isinstance(summary.get("items"), list) else []
        lines.append(f"- {store}: {int(summary.get('total_items') or 0)} item(ns)")
        for row in items[:15]:
            if not isinstance(row, dict):
                continue
            item = str(row.get("item") or "").strip()
            qty = int(row.get("qty") or 0)
            if item:
                lines.append(f"  - {item} ({qty})")
    return "\n".join(lines)


def _render_faltas_mutation_response(payload: Dict[str, Any], action: str) -> str:
    data = payload.get("data") if isinstance(payload, dict) else {}
    stores = data.get("stores") if isinstance(data, dict) else {}
    if not isinstance(stores, dict):
        stores = {}

    title = {
        "adicionar": "Itens adicionados",
        "remover": "Itens removidos",
        "limpar": "Listas limpas",
    }.get(action, "Operação concluída")

    lines = [title]
    for store, row in stores.items():
        if not isinstance(row, dict):
            continue
        if action == "adicionar":
            added = row.get("added") if isinstance(row.get("added"), list) else []
            incremented = row.get("incremented") if isinstance(row.get("incremented"), list) else []
            lines.append(f"- {store}: novos={len(added)} atualizados={len(incremented)}")
        elif action == "remover":
            removed = row.get("removed") if isinstance(row.get("removed"), list) else []
            not_found = row.get("not_found") if isinstance(row.get("not_found"), list) else []
            lines.append(f"- {store}: removidos={len(removed)} nao_encontrados={len(not_found)}")
        elif action == "limpar":
            lines.append(f"- {store}: limpa")
    if len(lines) == 1:
        lines.append("- sem alterações reportadas")
    return "\n".join(lines)


def _render_faltas_response(payload: Dict[str, Any], action: str, output_format: str) -> str:
    if payload.get("confirmation_required"):
        msg = str(payload.get("data", {}).get("message") or payload.get("message") or "").strip()
        return msg or "Confirmação obrigatória."

    if action == "listar":
        return _render_faltas_list_response(payload, output_format)

    if action in {"adicionar", "remover", "limpar"}:
        return _render_faltas_mutation_response(payload, action)

    data = payload.get("data")
    if isinstance(data, dict):
        return _truncate("```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```")
    return "Operação concluída."


def _build_faltas_pipeline_command(values: Dict[str, str], source: Any = None) -> tuple[list[str], str]:
    action = _normalize_faltas_action(values.get("action", ""))
    loja = _normalize_faltas_store(values.get("loja", ""))
    itens = re.sub(r"\s+", " ", str(values.get("itens", "") or "").strip())
    output_format = _normalize_faltas_format(values.get("formato", ""))
    confirm = str(values.get("confirm", "") or "").strip().lower()

    if not action or action == "help":
        return [], _format_faltas_usage()

    action_map = {
        "listar": "list",
        "adicionar": "add",
        "remover": "remove",
        "limpar": "clear",
    }
    pipeline_action = action_map.get(action)
    if not pipeline_action:
        return [], (
            "Ação inválida para `/faltas`.\n"
            "Use uma destas ações: `listar`, `adicionar`, `remover`, `limpar`, `help`."
        )

    cmd = [
        resolve_python_bin(required_modules=("openpyxl",)),
        str(resolve_faltas_pipeline_script()),
        pipeline_action,
        "--trigger-mode",
        "slash_command",
    ]

    if loja:
        cmd.extend(["--loja", loja])

    if source is not None:
        channel_id = str(getattr(source, "chat_id", "") or "").strip()
        parent_id = str(getattr(source, "chat_id_alt", "") or "").strip()
        author_id = str(getattr(source, "user_id", "") or "").strip()
        author_name = str(getattr(source, "user_name", "") or "").strip()
        if channel_id:
            cmd.extend(["--channel-id", channel_id, "--origin-channel-id", channel_id])
        if parent_id:
            cmd.extend(["--chat-id-alt", parent_id])
        if author_id:
            cmd.extend(["--author-id", author_id])
        if author_name:
            cmd.extend(["--author-name", author_name])

    if pipeline_action in {"add", "remove"}:
        if not itens:
            return [], f"Informe `itens` para a ação `{action}`."
        cmd.extend(["--itens", itens])

    if pipeline_action == "clear":
        if confirm not in {"1", "true", "yes", "sim", "s"}:
            return [], "Confirmação obrigatória para limpar. Use `confirm:sim`."
        cmd.extend(["--confirm", "sim"])

    return cmd, ""


async def _execute_faltas(raw_args: str, *, source: Any = None) -> str:
    script_path = resolve_faltas_pipeline_script()
    if not script_path.exists():
        return f"Script do pipeline de faltas não encontrado: `{script_path}`"

    values = parse_faltas_args(raw_args)
    action = _normalize_faltas_action(values.get("action", ""))
    output_format = _normalize_faltas_format(values.get("formato", ""))
    cmd, info = _build_faltas_pipeline_command(values, source=source)
    if not cmd:
        return info

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
    except asyncio.TimeoutError:
        return "Timeout ao executar `/faltas` (180s)."
    except Exception as exc:
        return f"Falha ao iniciar `/faltas`: {exc}"

    out_text = (stdout or b"").decode(errors="ignore").strip()
    err_text = (stderr or b"").decode(errors="ignore").strip()

    payload: Dict[str, Any] = {}
    try:
        payload = json.loads(out_text) if out_text else {}
    except Exception:
        payload = {}

    if proc.returncode != 0:
        if isinstance(payload, dict) and payload:
            return _truncate(_render_faltas_response(payload, action, output_format))
        detail = err_text or out_text or "erro desconhecido."
        return _truncate(f"Falha no `/faltas`: {detail}")

    if isinstance(payload, dict) and payload:
        return _truncate(_render_faltas_response(payload, action, output_format))
    if out_text:
        return _truncate(out_text)
    return "Operação concluída."


async def handle_faltas(raw_args: str) -> str:
    gateway_context = _current_gateway_context()
    interaction = gateway_context.get("interaction")
    source = gateway_context.get("source")
    return await _execute_faltas(
        _resolve_faltas_raw_args(raw_args, interaction),
        source=source,
    )


def _normalize_reload_args(raw_args: str) -> str:
    return str(raw_args or "").strip().lower()


def _parse_reload_request(raw_args: str) -> tuple[bool, bool]:
    normalized = _normalize_reload_args(raw_args)
    if not normalized:
        return False, False

    parts = normalized.replace(",", " ").split()
    if not parts:
        return False, False

    first = parts[0]
    if first.startswith("args:"):
        first = first.split(":", 1)[1].strip()
    if first not in {"reload", "realod"}:
        return False, False

    destructive_tokens = {"clear", "wipe", "force", "force-clear", "force_clear"}
    destructive = any(token in destructive_tokens for token in parts[1:])
    return True, destructive


async def handle_commands_reload(
    *,
    platform: str = "",
    command: str = "",
    args: str = "",
    runner: Any = None,
    **_: Any,
) -> Dict[str, Any] | None:
    if str(platform or "").strip().lower() != "discord":
        return None
    if str(command or "").strip().lower() != "commands":
        return None

    is_reload, destructive = _parse_reload_request(args)
    if not is_reload:
        return None
    if not destructive:
        return {
            "decision": "handled",
            "message": (
                "Skipped destructive Discord app-command clearing to avoid rate limits. "
                "Wait out the cooldown, then run `horc restart <node>` once. "
                "Use `/commands reload clear` only if you intentionally want to wipe "
                "Discord app commands before a restart."
            ),
        }

    adapters = getattr(runner, "adapters", {}) or {}
    adapter = adapters.get("discord")
    if adapter is None:
        try:
            from gateway.config import Platform

            adapter = adapters.get(Platform.DISCORD)
        except Exception:
            adapter = None
    client = getattr(adapter, "_client", None) if adapter is not None else None
    if client is None:
        return {
            "decision": "handled",
            "message": "Discord adapter is not connected right now.",
        }

    app_id = str(
        getattr(client, "application_id", "")
        or getattr(getattr(client, "user", None), "id", "")
        or ""
    ).strip()
    if not app_id:
        return {
            "decision": "handled",
            "message": "Could not resolve `DISCORD_APP_ID` for Discord command reload.",
        }

    try:
        import discord  # type: ignore
    except Exception as exc:
        logger.warning("Failed to import discord while reloading commands: %s", exc)
        return {
            "decision": "handled",
            "message": "Discord command reload is unavailable in this runtime.",
        }

    cleared_global = 0
    cleared_guild_total = 0

    try:
        global_route = discord.http.Route(
            "GET",
            "/applications/{application_id}/commands",
            application_id=app_id,
        )
        existing_global = await client.http.request(global_route)
        if isinstance(existing_global, list):
            cleared_global = len(existing_global)

        overwrite_global_route = discord.http.Route(
            "PUT",
            "/applications/{application_id}/commands",
            application_id=app_id,
        )
        await client.http.request(overwrite_global_route, json=[])

        for guild in list(getattr(client, "guilds", []) or []):
            guild_id = getattr(guild, "id", None)
            if guild_id is None:
                continue

            guild_route = discord.http.Route(
                "GET",
                "/applications/{application_id}/guilds/{guild_id}/commands",
                application_id=app_id,
                guild_id=guild_id,
            )
            existing_guild = await client.http.request(guild_route)
            if isinstance(existing_guild, list):
                cleared_guild_total += len(existing_guild)

            overwrite_guild_route = discord.http.Route(
                "PUT",
                "/applications/{application_id}/guilds/{guild_id}/commands",
                application_id=app_id,
                guild_id=guild_id,
            )
            await client.http.request(overwrite_guild_route, json=[])
    except Exception as exc:
        logger.warning("Discord command reload failed: %s", exc, exc_info=True)
        return {
            "decision": "handled",
            "message": f"Failed to clear Discord app commands: `{exc}`",
        }

    return {
        "decision": "handled",
        "message": (
            "Discord app commands cleared successfully. "
            f"Removed {cleared_global} global and {cleared_guild_total} guild command(s). "
            "Run `horc restart` on the nodes you want to re-register."
        ),
    }


async def handle_pre_gateway_message(
    *,
    platform: str = "",
    source: Any = None,
    message: str = "",
    **_: Any,
) -> Dict[str, Any] | None:
    if str(platform or "").strip().lower() != "discord":
        return None

    command, raw_args = _split_command_text(message)
    if command != "faltas":
        return None

    reply = await _execute_faltas(raw_args, source=source)
    return {"decision": "handled", "message": str(reply or "Operação concluída.")}


async def handle_faltas_command(
    *,
    platform: str = "",
    args: str = "",
    event: Any = None,
    source: Any = None,
    **_: Any,
) -> Dict[str, Any] | None:
    if str(platform or "").strip().lower() != "discord":
        return None

    interaction = getattr(event, "raw_message", None)
    raw_args = _resolve_faltas_raw_args(args, interaction)
    reply = await _execute_faltas(raw_args, source=source)
    return {"decision": "handled", "message": str(reply or "Operação concluída.")}


def register_plugin(ctx) -> None:
    _log_registration_status()
    metricas_desc = str(
        _payload_command_spec("metricas").get("description")
        or "Show Colmeio metrics dashboard"
    )
    faltas_desc = str(
        _payload_command_spec("faltas").get("description")
        or "Gerenciar lista de faltas"
    )

    ctx.register_command(
        "metricas",
        handle_metricas,
        description=metricas_desc,
        args_hint="[dias:N formato:text|json|csv skill:nome]",
    )
    ctx.register_command(
        "faltas",
        handle_faltas,
        description=faltas_desc,
        args_hint="action:listar|adicionar|remover|limpar|help [loja:loja1|loja2|ambas] [itens:\"...\"] [formato:links|excel|texto] [confirm:sim]",
    )
    ctx.register_command(
        "discord-slash-status",
        handle_discord_slash_status,
        description="Show Discord slash registration diagnostics for this node",
        args_hint="",
    )
    ctx.register_hook("pre_gateway_dispatch", handle_pre_gateway_dispatch)
