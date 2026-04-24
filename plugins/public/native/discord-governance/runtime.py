"""Native `/acl` command and governance hooks."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from .legacy import (
    load_channel_acl_module,
    load_role_acl_module,
    load_slash_handlers_module,
)
from .parser import parse_acl_args
from .paths import resolve_acl_path

logger = logging.getLogger(__name__)


def _usage_text() -> str:
    return (
        "Uso de `/acl`:\n"
        "- `/acl command command:metricas role:gerente`\n"
        "- `/acl channel channel:123456 mode:specific model_key:mini "
        "allowed_commands:faltas always_allowed_commands:status "
        "default_action:skill:add free_text_policy:strict_item`\n"
        "- `/acl channel channel:123456 mode:default`"
    )


def _format_command_update(result: Dict[str, Any]) -> str:
    return (
        "✅ ACL de comando atualizado com sucesso.\n"
        f"comando: `/{result.get('command')}`\n"
        f"min_role: `{result.get('min_role_label')}` (`{result.get('min_role')}`)\n"
        f"anterior: `{result.get('previous_min_role') or '(sem min_role)'}`\n"
        f"arquivo: `{result.get('acl_path')}`"
    )


def _format_channel_update(result: Dict[str, Any]) -> str:
    channel_mode = str(result.get("channel_mode") or "")
    lines = [
        "✅ ACL de canal atualizado com sucesso.",
        f"channel: `{result.get('channel_id')}`",
        f"mode: `{result.get('mode')}` ({channel_mode})",
    ]
    if channel_mode == "condicionado":
        lines.append(f"model_key: `{result.get('model_key')}`")
        lines.append(f"provider/model: `{result.get('provider')}` / `{result.get('model')}`")
        label_value = str(result.get("label") or "").strip()
        if label_value:
            lines.append(f"label: `{label_value}`")
    lines.append(f"arquivo: `{result.get('config_path')}`")
    return "\n".join(lines)


async def handle_acl(raw_args: str) -> str:
    subcommand, values = parse_acl_args(raw_args)
    if not subcommand:
        return _usage_text()

    if subcommand == "command":
        command_value = values.get("command") or values.get("cmd") or ""
        role_value = values.get("role") or values.get("min_role") or ""
        if not command_value or not role_value:
            return "❌ Informe `command:<nome>` e `role:<hierarquia>`.\n\n" + _usage_text()
        role_acl = load_role_acl_module()
        result = role_acl.update_command_min_role(
            resolve_acl_path(),
            command_value,
            role_value,
        )
        return _format_command_update(result)

    if subcommand == "channel":
        channel_value = values.get("channel") or values.get("channel_id") or ""
        mode_value = values.get("mode") or ""
        if not channel_value or not mode_value:
            return "❌ Informe `channel:<id>` e `mode:<default|specific>`.\n\n" + _usage_text()
        handlers = load_slash_handlers_module()
        result = handlers.update_channel_acl_policy(
            channel_id=channel_value,
            mode=mode_value,
            model_key=values.get("model_key", ""),
            instructions=values.get("instructions", ""),
            allowed_commands=values.get("allowed_commands", ""),
            allowed_skills=values.get("allowed_skills", ""),
            always_allowed_commands=values.get("always_allowed_commands", ""),
            default_action=values.get("default_action", ""),
            free_text_policy=values.get("free_text_policy", ""),
            label=values.get("label", "") or values.get("store", ""),
            settings={},
        )
        try:
            channel_acl = load_channel_acl_module()
            clear_cache = getattr(channel_acl, "clear_cache", None)
            if callable(clear_cache):
                clear_cache()
        except Exception:
            logger.debug("Failed to clear channel ACL cache after /acl update", exc_info=True)
        return _format_channel_update(result)

    return f"❌ Subcomando inválido: `{subcommand}`.\n\n{_usage_text()}"


def _platform_value(source: Any) -> str:
    platform = getattr(source, "platform", None)
    return str(getattr(platform, "value", platform) or "").strip().lower()


def _schedule_gateway_reply(gateway: Any, source: Any, message: str) -> None:
    text = str(message or "").strip()
    if gateway is None or source is None or not text:
        return

    adapters = getattr(gateway, "adapters", {}) or {}
    platform_key = getattr(source, "platform", None)
    try:
        adapter = adapters.get(platform_key)
    except TypeError:
        adapter = None
    if adapter is None:
        return

    metadata = {"thread_id": source.thread_id} if getattr(source, "thread_id", None) else None

    async def _send_reply() -> None:
        try:
            await adapter.send(str(getattr(source, "chat_id", "") or ""), text, metadata=metadata)
        except Exception:
            logger.debug("Failed sending governance reply to source=%s", source, exc_info=True)

    try:
        asyncio.get_running_loop().create_task(_send_reply())
    except Exception:
        logger.debug("Could not schedule governance reply for source=%s", source, exc_info=True)


async def _dispatch_normalized_command(
    gateway: Any,
    source: Any,
    message_text: str,
) -> None:
    try:
        channel_acl = load_channel_acl_module()
        handled, reply = await channel_acl.dispatch_normalized_command(source, message_text)
        if handled:
            _schedule_gateway_reply(gateway, source, str(reply or "✅ Comando processado."))
            return
    except Exception:
        logger.debug("Failed dispatching normalized restricted-channel command", exc_info=True)

    _schedule_gateway_reply(
        gateway,
        source,
        "🚫 Falha ao processar comando normalizado do canal restrito.",
    )


def _resolve_roles_sync(role_acl: Any, interaction: Any) -> list[Dict[str, str]]:
    extract = getattr(role_acl, "_extract_member_roles_from_object", None)
    if not callable(extract):
        return []

    user = getattr(interaction, "user", None)
    roles = extract(user)
    if roles:
        return roles

    guild = getattr(interaction, "guild", None)
    user_id = str(getattr(user, "id", "") or "").strip()
    if guild is None or not user_id.isdigit():
        return []

    member = None
    try:
        getter = getattr(guild, "get_member", None)
        if callable(getter):
            member = getter(int(user_id))
    except Exception:
        member = None

    return extract(member)


def _authorize_interaction_sync(interaction: Any, command_name: str) -> Dict[str, Any]:
    role_acl = load_role_acl_module()
    command = role_acl.normalize_command_name(command_name)
    if not command:
        return {
            "allowed": False,
            "message": "🚫 ACL: comando inválido.",
            "command": command,
            "decision": "invalid_command",
        }

    acl_path = resolve_acl_path()
    acl = role_acl.load_acl(acl_path)
    rank_map = role_acl.build_rank_map(acl.get("hierarchy") or [])
    role_labels = role_acl.build_role_label_map(acl.get("hierarchy") or [])

    guild = getattr(interaction, "guild", None)
    if guild is None:
        return {
            "allowed": False,
            "message": f"🚫 ACL: `/{command}` exige uso em servidor com papéis (roles).",
            "command": command,
            "decision": "guild_required",
            "acl_path": str(acl_path),
            "required_role": "admin",
        }

    actor_tokens = role_acl._tokens_from_roles(_resolve_roles_sync(role_acl, interaction))
    actor_user_id = str(getattr(getattr(interaction, "user", None), "id", "") or "").strip()
    if actor_user_id:
        actor_tokens = role_acl._apply_user_override_tokens(actor_tokens, acl, actor_user_id)
    actor_role_name = role_acl._resolve_top_role_name(actor_tokens, rank_map, role_labels)

    admin_tokens = role_acl._admin_tokens_from_acl(acl)
    if admin_tokens and (actor_tokens & admin_tokens):
        return {
            "allowed": True,
            "message": "",
            "command": command,
            "decision": "admin_bypass",
            "acl_path": str(acl_path),
            "required_role": "admin",
            "actor_role": actor_role_name,
        }

    commands = acl.get("commands") if isinstance(acl.get("commands"), dict) else {}
    cfg = commands.get(command)
    if not isinstance(cfg, dict):
        return {
            "allowed": False,
            "message": (
                f"🚫 ACL: `/{command}` não está mapeado neste node. "
                f"Atualize `{acl_path}` em `commands.{command}.min_role`."
            ),
            "command": command,
            "decision": "unmapped_command",
            "acl_path": str(acl_path),
        }

    min_role = role_acl.normalize_role_token(cfg.get("min_role") or "")
    if not min_role:
        return {
            "allowed": False,
            "message": (
                f"🚫 ACL: `/{command}` está sem `min_role`. "
                f"Atualize `{acl_path}` em `commands.{command}.min_role`."
            ),
            "command": command,
            "decision": "missing_min_role",
            "acl_path": str(acl_path),
        }

    actor_rank = role_acl._resolve_actor_rank(actor_tokens, rank_map)
    required_rank = role_acl._resolve_required_rank(min_role, rank_map)
    required_label = str(
        role_labels.get(role_acl.normalize_role_token(min_role))
        or role_acl.role_display_name(min_role)
    )

    if required_rank is None:
        return {
            "allowed": False,
            "message": (
                f"🚫 ACL: `/{command}` referencia role inválida (`{role_acl.role_display_name(min_role)}`). "
                f"Corrija `{acl_path}`."
            ),
            "command": command,
            "decision": "invalid_required_role",
            "acl_path": str(acl_path),
            "required_role": required_label,
        }

    if actor_rank is None:
        return {
            "allowed": False,
            "message": (
                f"🚫 ACL: você não possui role autorizada para `/{command}`. "
                f"Role mínima: `{required_label}`."
            ),
            "command": command,
            "decision": "no_rank_match",
            "acl_path": str(acl_path),
            "required_role": required_label,
        }

    if actor_rank > required_rank:
        return {
            "allowed": False,
            "message": (
                f"🚫 ACL: `/{command}` requer role `{role_acl.role_display_name(min_role)}` ou superior. "
                f"Sua role atual: `{actor_role_name}`."
            ),
            "command": command,
            "decision": "role_too_low",
            "acl_path": str(acl_path),
            "required_role": required_label,
            "actor_role": actor_role_name,
        }

    return {
        "allowed": True,
        "message": "",
        "command": command,
        "decision": "allow",
        "acl_path": str(acl_path),
        "required_role": required_label,
        "actor_role": actor_role_name,
    }


def _canonical_command_name(command: str) -> str:
    raw = str(command or "").strip().lower().lstrip("/")
    if not raw:
        return ""

    try:
        from hermes_cli.commands import resolve_command

        cmd_def = resolve_command(raw)
        if cmd_def is not None:
            return str(cmd_def.name or raw).strip().lower()
    except Exception:
        pass
    return raw


def _apply_channel_route(gateway: Any, event: Any, source: Any) -> str:
    if gateway is None or event is None or source is None:
        return ""

    overrides = getattr(gateway, "_session_model_overrides", None)
    if not isinstance(overrides, dict):
        return ""

    try:
        session_key = gateway._session_key_for_source(source)
    except Exception:
        logger.debug("Could not resolve session key for governance routing", exc_info=True)
        return ""

    previous_override = overrides.pop(session_key, None)
    try:
        base_model, base_runtime = gateway._resolve_session_agent_runtime(source=source)
    except Exception:
        logger.debug("Could not resolve base runtime for governance routing", exc_info=True)
        if previous_override is not None:
            overrides[session_key] = previous_override
        return ""

    channel_acl = load_channel_acl_module()
    routed = channel_acl.enforce_channel_model(
        source,
        {
            "model": base_model,
            "runtime": dict(base_runtime or {}),
        },
    )
    blocked = str(routed.get("channel_acl_blocked") or "").strip()
    if blocked:
        return blocked

    addon = str(routed.get("system_prompt_addon") or "").strip()
    if addon:
        existing_prompt = str(getattr(event, "channel_prompt", "") or "").strip()
        event.channel_prompt = "\n\n".join(
            part for part in (existing_prompt, addon) if part
        )

    routed_model = str(routed.get("model") or base_model or "").strip()
    routed_runtime = dict(base_runtime or {})
    extra_runtime = routed.get("runtime")
    if isinstance(extra_runtime, dict):
        for key in ("provider", "api_key", "base_url", "api_mode"):
            if extra_runtime.get(key) is not None:
                routed_runtime[key] = extra_runtime.get(key)

    changed = routed_model != str(base_model or "").strip() or any(
        routed_runtime.get(key) != dict(base_runtime or {}).get(key)
        for key in ("provider", "api_key", "base_url", "api_mode")
    )

    if changed:
        override = {"model": routed_model}
        for key in ("provider", "api_key", "base_url", "api_mode"):
            if routed_runtime.get(key) is not None:
                override[key] = routed_runtime.get(key)
        overrides[session_key] = override

    return ""


def _resolve_status_route(gateway: Any, source: Any) -> tuple[str, str, str]:
    route_model = "n/a"
    route_provider = "n/a"
    routing_note = "default (no channel rule matched)"

    if gateway is None or source is None:
        return route_model, route_provider, routing_note

    try:
        base_model, base_runtime = gateway._resolve_session_agent_runtime(source=source)
    except Exception:
        logger.debug("Could not resolve base runtime for governance status", exc_info=True)
        return route_model, route_provider, routing_note

    route_model = str(base_model or "").strip() or "n/a"
    base_runtime_dict = dict(base_runtime or {})
    route_provider = str(base_runtime_dict.get("provider") or "").strip() or "n/a"

    try:
        channel_acl = load_channel_acl_module()
        routed = channel_acl.enforce_channel_model(
            source,
            {
                "model": route_model,
                "runtime": dict(base_runtime_dict),
            },
        )
        blocked = str(routed.get("channel_acl_blocked") or "").strip()
        if blocked:
            return route_model, route_provider, blocked

        routed_model = str(routed.get("model") or route_model).strip() or route_model
        routed_runtime = dict(base_runtime_dict)
        extra_runtime = routed.get("runtime")
        if isinstance(extra_runtime, dict):
            for key in ("provider", "api_key", "base_url", "api_mode"):
                if extra_runtime.get(key) is not None:
                    routed_runtime[key] = extra_runtime.get(key)
        routed_provider = str(routed_runtime.get("provider") or route_provider).strip() or route_provider

        if routed_model != route_model or routed_provider != route_provider:
            routing_note = "channel-acl forced (condicionado)"
        else:
            try:
                channel_id = str(getattr(source, "chat_id_alt", "") or getattr(source, "chat_id", "") or "")
                thread_id = str(getattr(source, "thread_id", "") or "") or None
                parent_id = str(getattr(source, "chat_id_alt", "") or "") or None
                mode, _cfg = channel_acl.get_channel_routing(channel_id, thread_id, parent_id)
                if mode == "condicionado":
                    routing_note = "channel-acl matched (condicionado)"
            except Exception:
                logger.debug("Could not compute governance status routing note", exc_info=True)

        return routed_model, routed_provider, routing_note
    except Exception:
        logger.debug("Could not resolve governance status route", exc_info=True)
        return route_model, route_provider, routing_note


def _format_status_text(gateway: Any, source: Any) -> str:
    if gateway is None or source is None:
        return "📊 **Hermes Gateway Status**"

    session_store = getattr(gateway, "session_store", None)
    if session_store is None:
        return "📊 **Hermes Gateway Status**"

    session_entry = session_store.get_or_create_session(source)
    connected_platforms = [
        getattr(platform, "value", str(platform))
        for platform in (getattr(gateway, "adapters", {}) or {}).keys()
    ]

    try:
        session_key = gateway._session_key_for_source(source)
    except Exception:
        logger.debug("Could not resolve session key for governance status", exc_info=True)
        session_key = ""

    running_agents = getattr(gateway, "_running_agents", {}) or {}
    is_running = bool(session_key and session_key in running_agents)

    title = None
    session_db = getattr(gateway, "_session_db", None)
    if session_db is not None:
        try:
            title = session_db.get_session_title(session_entry.session_id)
        except Exception:
            title = None

    tokens_used = getattr(session_entry, "total_tokens", None)
    if tokens_used in (None, ""):
        try:
            tokens_used = (getattr(session_entry, "input_tokens", 0) or 0) + (
                getattr(session_entry, "output_tokens", 0) or 0
            )
        except Exception:
            tokens_used = 0

    route_model, route_provider, routing_note = _resolve_status_route(gateway, source)

    lines = [
        "📊 **Hermes Gateway Status**",
        "",
        f"**Session ID:** `{session_entry.session_id}`",
    ]
    if title:
        lines.append(f"**Title:** {title}")
    lines.extend(
        [
            f"**Created:** {session_entry.created_at.strftime('%Y-%m-%d %H:%M')}",
            f"**Last Activity:** {session_entry.updated_at.strftime('%Y-%m-%d %H:%M')}",
            f"**Tokens:** {int(tokens_used or 0):,}",
            f"**Agent Running:** {'Yes ⚡' if is_running else 'No'}",
            "",
            f"**Connected Platforms:** {', '.join(connected_platforms) if connected_platforms else '(none)'}",
            "",
            "**Model Routing**",
            f"  model: `{route_model}`",
            f"  provider: `{route_provider}`",
            f"  route: {routing_note}",
        ]
    )
    return "\n".join(lines)


def handle_pre_gateway_dispatch(
    *,
    event: Any = None,
    gateway: Any = None,
    **_: Any,
) -> Dict[str, Any] | None:
    source = getattr(event, "source", None)
    if source is None or _platform_value(source) != "discord":
        return None

    channel_acl = load_channel_acl_module()
    message_text = str(getattr(event, "text", "") or "")
    action, payload = channel_acl.normalize_to_channel_skill(source, message_text)
    normalized = str(payload or "")

    if action == "BLOCK":
        _schedule_gateway_reply(gateway, source, normalized)
        return {"action": "skip", "reason": "channel_policy_block"}

    if action in {"SKILL_ADD", "FALTAS_ADD"}:
        try:
            asyncio.get_running_loop().create_task(
                _dispatch_normalized_command(gateway, source, normalized)
            )
        except Exception:
            logger.debug("Could not schedule normalized restricted-channel dispatch", exc_info=True)
            if gateway is None and normalized:
                event.text = normalized
                return None
            _schedule_gateway_reply(
                gateway,
                source,
                "🚫 Falha ao processar comando normalizado do canal restrito.",
            )
        return {"action": "skip", "reason": "channel_policy_normalized"}

    if action != "PASSTHROUGH" and normalized and normalized != message_text:
        event.text = normalized

    command = _canonical_command_name(getattr(event, "get_command", lambda: "")() or "")
    if command == "status":
        _schedule_gateway_reply(gateway, source, _format_status_text(gateway, source))
        return {"action": "skip", "reason": "status_override"}

    if command:
        interaction = getattr(event, "raw_message", None)
        if interaction is not None:
            role_result = _authorize_interaction_sync(interaction, command)
            if not bool(role_result.get("allowed")):
                _schedule_gateway_reply(
                    gateway,
                    source,
                    str(role_result.get("message") or f"🚫 ACL: `/{command}` não permitido."),
                )
                return {"action": "skip", "reason": "command_acl_role_block"}

        try:
            allowed, message = channel_acl.check_command_allowed(
                str(getattr(source, "chat_id", "") or ""),
                command,
                thread_id=str(getattr(source, "thread_id", "") or "") or None,
                parent_id=str(getattr(source, "chat_id_alt", "") or "") or None,
            )
        except Exception:
            logger.debug("Channel ACL slash check failed for /%s", command, exc_info=True)
            allowed, message = True, ""

        if not allowed:
            _schedule_gateway_reply(
                gateway,
                source,
                str(message or f"🚫 O comando `/{command}` não é permitido neste canal."),
            )
            return {"action": "skip", "reason": "command_acl_channel_block"}

    blocked_message = _apply_channel_route(gateway, event, source)
    if blocked_message:
        _schedule_gateway_reply(gateway, source, blocked_message)
        return {"action": "skip", "reason": "channel_route_block"}

    return None


async def handle_command_policy(
    *,
    platform: str = "",
    command: str = "",
    event: Any = None,
    source: Any = None,
    **_: Any,
) -> Dict[str, Any] | None:
    if str(platform or "").strip().lower() != "discord":
        return None

    interaction = getattr(event, "raw_message", None)
    if interaction is None:
        return None

    role_acl = load_role_acl_module()
    role_result = await role_acl.authorize_interaction(
        interaction,
        command,
        acl_path=resolve_acl_path(),
    )
    if not bool(role_result.get("allowed")):
        return {
            "decision": "deny",
            "message": str(role_result.get("message") or f"🚫 ACL: `/{command}` não permitido."),
        }

    try:
        channel_acl = load_channel_acl_module()
        channel_id = str(getattr(source, "chat_id", "") or "")
        thread_id = str(getattr(source, "thread_id", "") or "") or None
        parent_id = str(getattr(source, "chat_id_alt", "") or "") or None
        allowed, message = channel_acl.check_command_allowed(
            channel_id,
            command,
            thread_id=thread_id,
            parent_id=parent_id,
        )
        if not allowed:
            return {
                "decision": "deny",
                "message": str(message or f"🚫 O comando `/{command}` não é permitido neste canal."),
            }
    except Exception:
        logger.debug("Channel ACL slash check failed for /%s", command, exc_info=True)

    return None


async def handle_pre_gateway_message(
    *,
    platform: str = "",
    source: Any = None,
    message: str = "",
    **_: Any,
) -> Dict[str, Any] | None:
    if str(platform or "").strip().lower() != "discord" or source is None:
        return None

    channel_acl = load_channel_acl_module()
    action, payload = channel_acl.normalize_to_channel_skill(source, message)
    normalized = str(payload or "")

    if action == "BLOCK":
        return {"decision": "deny", "message": normalized}

    if action in {"SKILL_ADD", "FALTAS_ADD"}:
        handled, reply = await channel_acl.dispatch_normalized_command(source, normalized)
        if handled:
            return {"decision": "handled", "message": str(reply or "✅ Comando processado.")}
        return {
            "decision": "handled",
            "message": "🚫 Falha ao processar comando normalizado do canal restrito.",
        }

    if action != "PASSTHROUGH" and normalized and normalized != str(message or ""):
        return {"decision": "rewrite", "message": normalized}

    return None


async def handle_transform_turn_route(
    *,
    platform: str = "",
    source: Any = None,
    turn_route: Dict[str, Any] | None = None,
    **_: Any,
) -> Dict[str, Any] | None:
    if str(platform or "").strip().lower() != "discord" or source is None:
        return None

    channel_acl = load_channel_acl_module()
    routed = channel_acl.enforce_channel_model(source, dict(turn_route or {}))

    try:
        channel_id = str(getattr(source, "chat_id_alt", "") or getattr(source, "chat_id", "") or "")
        thread_id = str(getattr(source, "thread_id", "") or "") or None
        parent_id = str(getattr(source, "chat_id_alt", "") or "") or None
        mode, _cfg = channel_acl.get_channel_routing(channel_id, thread_id, parent_id)
        if mode == "condicionado":
            routed.setdefault("routing_note", "channel policy matched (condicionado)")
    except Exception:
        logger.debug("Could not compute routing note for source=%s", source, exc_info=True)

    return {"turn_route": routed}


def register_plugin(ctx) -> None:
    ctx.register_command(
        "acl",
        handle_acl,
        description="Manage Discord command and channel ACL policy",
        args_hint="command ... | channel ...",
    )
    ctx.register_hook("pre_gateway_dispatch", handle_pre_gateway_dispatch)
