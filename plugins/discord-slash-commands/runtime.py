"""Canonical Discord slash commands runtime."""

from __future__ import annotations

import asyncio
import contextvars
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

from .legacy import (
    load_channel_acl_module,
    load_role_acl_module,
    load_slash_handlers_module,
)
from .parser import parse_acl_args
from .paths import (
    resolve_acl_path,
    resolve_custom_catalog_file,
    resolve_faltas_pipeline_script,
    resolve_scientific_pipeline_script,
    resolve_governance_models_file,
    resolve_legacy_bridge_handlers_path,
    resolve_metrics_script_path,
    resolve_python_bin,
    resolve_register_script_path,
    resolve_runtime_cache_root,
    resolve_runtime_env_file,
    resolve_runtime_hermes_home,
    runtime_node_name,
)
from .state import (
    get_command_definition,
    is_command_enabled,
    list_commands_for_display,
    load_active_model_state,
    load_app_scope,
    load_node_activation,
    set_command_enabled,
    write_active_model_state,
    write_node_activation,
)

logger = logging.getLogger(__name__)
_STARTUP_RECONCILE_SCHEDULED = False
_EMPTY_TEXT_SENTINEL = "(The user sent a message with no text content)"

_LEGACY_HANDLERS_MODULE: Any = None
_CURRENT_GATEWAY_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "canonical_discord_slash_commands_gateway_context",
    default=None,
)


class _NoopChannelAcl:
    def normalize_to_channel_skill(self, source: Any, message: str) -> tuple[str, str]:
        return "PASSTHROUGH", str(message or "")

    def check_command_allowed(
        self,
        channel_id: str,
        command: str,
        thread_id: str | None = None,
        parent_id: str | None = None,
    ) -> tuple[bool, str]:
        return True, ""

    def enforce_channel_model(self, source: Any, turn_route: dict[str, Any]) -> dict[str, Any]:
        return dict(turn_route or {})

    async def dispatch_normalized_command(self, source: Any, message: str) -> tuple[bool, str]:
        return False, ""

    def clear_cache(self) -> None:
        return None


_NOOP_CHANNEL_ACL = _NoopChannelAcl()


def _safe_channel_acl_module() -> Any:
    try:
        return load_channel_acl_module()
    except Exception:
        logger.debug("Falling back to noop channel ACL runtime", exc_info=True)
        return _NOOP_CHANNEL_ACL


def _event_audio_paths(event: Any) -> list[str]:
    media_urls = list(getattr(event, "media_urls", None) or [])
    media_types = list(getattr(event, "media_types", None) or [])
    if not media_urls:
        return []
    audio_paths: list[str] = []
    for index, path in enumerate(media_urls):
        media_type = str(media_types[index] if index < len(media_types) else "" or "").strip().lower()
        if media_type.startswith("audio/"):
            audio_paths.append(str(path))
    return audio_paths


def _maybe_normalize_audio_only_restricted_message(
    channel_acl: Any,
    source: Any,
    event: Any,
    *,
    initial_action: str,
) -> tuple[str, str] | None:
    if initial_action != "BLOCK":
        return None
    raw_text = str(getattr(event, "text", "") or "").strip()
    if raw_text and raw_text != _EMPTY_TEXT_SENTINEL:
        return None
    audio_paths = _event_audio_paths(event)
    if not audio_paths:
        return None
    try:
        from tools.transcription_tools import transcribe_audio
    except Exception:
        logger.debug("Audio-only restricted-channel fallback could not import STT helper", exc_info=True)
        return None

    transcripts: list[str] = []
    for path in audio_paths:
        try:
            result = transcribe_audio(path)
        except Exception:
            logger.debug("Audio-only restricted-channel transcription failed for %s", path, exc_info=True)
            continue
        if not isinstance(result, dict) or not result.get("success"):
            logger.debug("Audio-only restricted-channel transcription unsuccessful for %s: %r", path, result)
            continue
        transcript = re.sub(r"\s+", " ", str(result.get("transcript") or "").strip())
        if transcript:
            transcripts.append(transcript.replace('"', "'"))
    if not transcripts:
        return None

    transcript_text = " ".join(transcripts).strip()
    if not transcript_text:
        return None
    wrapped = f'[The user sent a voice message~ Here\'s what they said: "{transcript_text}"]'
    return channel_acl.normalize_to_channel_skill(source, wrapped)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _acl_mapping_hint(command_name: str, *, role_name: str = "admin") -> str:
    command = _canonical_command_name(command_name) or str(command_name or "").strip().lower().lstrip("/")
    if not command:
        command = "<nome>"
    return (
        f"Use `/acl command command:{command} role:{role_name}` para mapear este comando via Discord; "
        f"troque `role:{role_name}` pela role desejada."
    )


def _acl_unmapped_command_message(command_name: str, acl_path: Path) -> str:
    command = _canonical_command_name(command_name) or str(command_name or "").strip().lower().lstrip("/")
    return (
        f"🚫 ACL: `/{command}` não está mapeado neste node. "
        "Admins com permissão `Administrator` no Discord ou role literal `admin` fazem bypass automático. "
        f"{_acl_mapping_hint(command)} Arquivo: `{acl_path}`."
    )


def _acl_missing_min_role_message(command_name: str, acl_path: Path) -> str:
    command = _canonical_command_name(command_name) or str(command_name or "").strip().lower().lstrip("/")
    return (
        f"🚫 ACL: `/{command}` está sem `min_role`. "
        f"Corrija via Discord com {_acl_mapping_hint(command)} "
        f"Arquivo: `{acl_path}`."
    )


def _collect_registration_status() -> Dict[str, Any]:
    scope = load_app_scope()
    enabled_commands = [
        str(item).strip().lower()
        for item in scope.get("enabled_commands") or []
        if str(item).strip()
    ]
    return {
        "node_name": str(os.getenv("NODE_NAME", "") or "").strip() or "orchestrator",
        "catalog_path": str(resolve_custom_catalog_file()),
        "catalog_exists": resolve_custom_catalog_file().exists(),
        "enabled_commands": enabled_commands,
        "discord_app_id": str(os.getenv("DISCORD_APP_ID", "") or ""),
        "discord_server_id": str(os.getenv("DISCORD_SERVER_ID", "") or ""),
    }


def _log_registration_status() -> None:
    status = _collect_registration_status()
    logger.info(
        "canonical-discord-slash-commands register_plugin: node=%s catalog=%s exists=%s enabled=%s app_id=%s guild_id=%s",
        status.get("node_name") or "",
        status.get("catalog_path") or "",
        bool(status.get("catalog_exists")),
        ",".join(status.get("enabled_commands") or []),
        status.get("discord_app_id") or "",
        status.get("discord_server_id") or "",
    )


def _definition_help_text(name: str, fallback: str = "") -> str:
    definition = get_command_definition(name)
    return str(definition.get("help_text") or fallback).strip() or fallback


def _definition_description(name: str, fallback: str = "") -> str:
    definition = get_command_definition(name)
    return str(definition.get("description") or fallback).strip() or fallback


def _disabled_command_message(command_name: str) -> str:
    command = _canonical_command_name(command_name)
    if not command:
        return "🚫 Este comando está desabilitado neste node."
    return f"🚫 `/{command}` está desabilitado neste node. Use `/slash command:{command} enable:true`."


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
        "canonical_discord_slash_commands_legacy_handlers",
        resolve_legacy_bridge_handlers_path(),
        "_LEGACY_HANDLERS_MODULE",
    )


def _split_command_text(message: str) -> tuple[str, str]:
    text = str(message or "").strip()
    if not text.startswith("/"):
        return "", ""
    parts = text.split(maxsplit=1)
    command = parts[0].lower().lstrip("/")
    args = parts[1].strip() if len(parts) > 1 else ""
    return command, args


def _normalize_scientific_query(raw_args: str) -> str:
    text = str(raw_args or "").strip()
    if not text:
        return ""

    lowered = text.lower()
    if lowered.startswith("query:") or lowered.startswith("query="):
        text = text[6:].strip()
    else:
        try:
            tokens = shlex.split(text)
        except Exception:
            tokens = []
        if len(tokens) == 1:
            token = str(tokens[0] or "").strip()
            lowered_token = token.lower()
            if lowered_token.startswith("query:"):
                text = token.split(":", 1)[1].strip()
            elif lowered_token.startswith("query="):
                text = token.split("=", 1)[1].strip()

    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text


def _build_scientific_skill_message(gateway: Any, source: Any, raw_args: str) -> tuple[str, str]:
    if not is_command_enabled("scientific-paper-meta-analysis"):
        return "", (
            "🚫 `/scientific-paper-meta-analysis` está desabilitado neste node. "
            "Use `/slash command:scientific-paper-meta-analysis enable:true`."
        )

    query = _normalize_scientific_query(raw_args)
    if not query:
        return "", _definition_help_text(
            "scientific-paper-meta-analysis",
            "Uso: `/scientific-paper-meta-analysis query:\"tema do paper\"`.",
        )

    try:
        from agent.skill_commands import build_skill_invocation_message, resolve_skill_command_key
    except Exception:
        logger.debug("Could not import skill command helpers for scientific-paper-meta-analysis", exc_info=True)
        return "", "❌ Não foi possível carregar o runtime da skill `scientific-paper-meta-analysis`."

    cmd_key = resolve_skill_command_key("scientific-paper-meta-analysis") or "/scientific-paper-meta-analysis"
    session_key = None
    if gateway is not None and source is not None:
        try:
            session_key = gateway._session_key_for_source(source)
        except Exception:
            logger.debug("Could not resolve session key for scientific-paper-meta-analysis", exc_info=True)

    message = build_skill_invocation_message(cmd_key, query, task_id=session_key)
    if not message:
        return "", (
            "❌ A skill `scientific-paper-meta-analysis` não está disponível neste node. "
            "Verifique `/local/.hermes/skills`."
        )
    return str(message), ""


def _truncate(text: Any, limit: int = 3800) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _scientific_usage_text() -> str:
    return _definition_help_text(
        "scientific-paper-meta-analysis",
        (
            "Uso do `/scientific-paper-meta-analysis`:\n"
            "- `/scientific-paper-meta-analysis help`\n"
            "- `/scientific-paper-meta-analysis query:\"tema do paper\"`\n\n"
            "Executa o pipeline persistente do Paracelsus e atualiza o cache em tempo real."
        ),
    )


def _reply_metadata_for_source(source: Any) -> Dict[str, Any] | None:
    if source is None:
        return None
    return {"thread_id": source.thread_id} if getattr(source, "thread_id", None) else None


def _gateway_adapter_for_source(gateway: Any, source: Any) -> tuple[Any, str, Dict[str, Any] | None]:
    if gateway is None or source is None:
        return None, "", None
    adapters = getattr(gateway, "adapters", {}) or {}
    platform_key = getattr(source, "platform", None)
    try:
        adapter = adapters.get(platform_key)
    except TypeError:
        adapter = None
    if adapter is None:
        return None, "", None
    chat_id = str(getattr(source, "chat_id", "") or "").strip()
    if not chat_id:
        return None, "", None
    return adapter, chat_id, _reply_metadata_for_source(source)


def _render_scientific_pipeline_response(payload: Dict[str, Any]) -> str:
    papers = payload.get("papers") if isinstance(payload, dict) else []
    papers = papers if isinstance(papers, list) else []
    meta_analysis = payload.get("meta_analysis") if isinstance(payload, dict) else {}
    meta_analysis = meta_analysis if isinstance(meta_analysis, dict) else {}
    cache = payload.get("cache") if isinstance(payload, dict) else {}
    cache = cache if isinstance(cache, dict) else {}
    if not papers:
        lines = [
            "🔬 Paracelsus scientific-paper-meta-analysis",
            f"report: {payload.get('report_id') or 'pending'}",
            f"query: {payload.get('query') or ''}",
            "Nenhum paper suficientemente relevante foi encontrado para essa busca.",
            "Tente refinar com um tema mais específico, como `carnivore diet`, `animal-based diet`, `low-carbohydrate diet`, ou informe um DOI/PMID.",
            (
                "results: "
                f"raw={int(payload.get('total_raw') or 0)} · "
                f"deduplicated={int(payload.get('total_deduplicated') or 0)}"
            ),
            (
                "cache: "
                f"hit={int(cache.get('hits') or 0)} · "
                f"new={int(cache.get('new_assets') or cache.get('asset_downloads') or 0)} assets"
            ),
        ]
        if cache.get("db_path"):
            lines.append(f"db: {cache.get('db_path')}")
        return _truncate("\n".join(lines))

    if meta_analysis:
        evidence = meta_analysis.get("evidence_profile") if isinstance(meta_analysis.get("evidence_profile"), dict) else {}
        counts = evidence.get("study_design_counts") if isinstance(evidence.get("study_design_counts"), dict) else {}
        narrative = meta_analysis.get("narrative") or meta_analysis.get("summary") or ""
        lines = [
            "🔬 Paracelsus scientific-paper-meta-analysis",
            f"report: {payload.get('report_id') or 'pending'}",
            f"theme: {payload.get('query') or ''}",
            "meta-analysis:",
            narrative,
            f"bottom line: {meta_analysis.get('bottom_line') or meta_analysis.get('summary') or ''}",
            (
                "evidence: "
                f"{int(evidence.get('total_papers') or len(papers))} papers · "
                f"{int(counts.get('synthesis') or 0)} syntheses · "
                f"{int(counts.get('trial') or 0)} trials · "
                f"{int(counts.get('observational') or 0)} observational · "
                f"{int(evidence.get('open_access_count') or 0)} OA"
            ),
            (
                "cache: "
                f"{cache.get('mode') or 'miss'} "
                f"(hit={int(cache.get('hits') or 0)} · new={int(cache.get('new_assets') or cache.get('asset_downloads') or 0)} assets)"
            ),
            (
                "run stats: "
                f"raw={int(payload.get('total_raw') or 0)} · "
                f"ranked={int(payload.get('total_deduplicated') or 0)}"
            ),
        ]
        takeaways = list(meta_analysis.get("clinical_takeaways") or [])
        if takeaways:
            lines.append("clinical takeaways:")
            for takeaway in takeaways[:3]:
                lines.append(f"- {takeaway}")
        uncertainties = list(meta_analysis.get("uncertainties") or [])
        if uncertainties:
            lines.append("caveats:")
            for item in uncertainties[:2]:
                lines.append(f"- {item}")
        rabbit_holes = list(meta_analysis.get("rabbit_holes") or [])
        if rabbit_holes:
            lines.append("rabbit holes to close:")
            for item in rabbit_holes[:3]:
                lines.append(f"- {item}")
        ranked_papers = list(meta_analysis.get("ranked_papers") or [])
        if ranked_papers:
            lines.append("ranked leads:")
            for paper in ranked_papers[:3]:
                lines.append(f"{int(paper.get('rank') or 0)}. ({paper.get('year') or '?'}) {paper.get('title') or 'Untitled paper'}")
                lines.append(f"   {paper.get('why_it_matters') or 'ranked by relevance'}")
        if cache.get("db_path"):
            lines.append(f"db: {cache.get('db_path')}")
        return _truncate("\n".join(lines))

    lines = [
        "🔬 Paracelsus scientific-paper-meta-analysis",
        f"query: {payload.get('query') or ''}",
        f"mode: {payload.get('mode') or 'search'}",
        (
            "cache: "
            f"{cache.get('mode') or 'miss'} "
            f"(hits={int(cache.get('hits') or 0)}, misses={int(cache.get('misses') or 0)}, "
            f"assets={int(cache.get('asset_downloads') or 0)})"
        ),
        (
            "results: "
            f"raw={int(payload.get('total_raw') or 0)} · "
            f"deduplicated={int(payload.get('total_deduplicated') or 0)}"
        ),
    ]
    if cache.get("db_path"):
        lines.append(f"db: {cache.get('db_path')}")
    for index, paper in enumerate(papers[:5], start=1):
        title = str(paper.get("title") or "Untitled paper").strip()
        year = str(paper.get("year") or paper.get("published") or "?").strip() or "?"
        journal = str(paper.get("journal") or "").strip()
        source_mix = ",".join(
            dict.fromkeys(
                str(item).strip()
                for item in (paper.get("sources") or [paper.get("source") or "unknown"])
                if str(item).strip()
            )
        )
        lines.append(f"{index}. ({year}) {title}")
        meta = []
        if journal:
            meta.append(journal)
        if source_mix:
            meta.append(f"sources={source_mix}")
        if meta:
            lines.append("   " + " | ".join(meta))
    return _truncate("\n".join(lines))


async def _execute_scientific_pipeline(raw_args: str) -> str:
    script_path = resolve_scientific_pipeline_script()
    if not script_path.exists():
        return f"Script do pipeline científico não encontrado: `{script_path}`"

    if not is_command_enabled("scientific-paper-meta-analysis"):
        return (
            "🚫 `/scientific-paper-meta-analysis` está desabilitado neste node. "
            "Use `/slash command:scientific-paper-meta-analysis enable:true`."
        )

    query = _normalize_scientific_query(raw_args)
    if not query or query.lower() == "help":
        return _scientific_usage_text()

    cmd = [
        resolve_python_bin(required_modules=("sqlite3",)),
        str(script_path),
        query,
        "--format",
        "json",
    ]
    env = os.environ.copy()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=900)
    except asyncio.TimeoutError:
        return "Timeout ao executar `/scientific-paper-meta-analysis` (900s)."
    except Exception as exc:
        return f"Falha ao iniciar `/scientific-paper-meta-analysis`: {exc}"

    out_text = (stdout or b"").decode(errors="ignore").strip()
    err_text = (stderr or b"").decode(errors="ignore").strip()
    payload: Dict[str, Any] = {}
    if out_text:
        try:
            payload = json.loads(out_text)
        except Exception:
            payload = {}

    if proc.returncode != 0:
        detail = (
            payload.get("error")
            if isinstance(payload, dict) and payload.get("error")
            else err_text or out_text or "erro desconhecido."
        )
        return _truncate(f"Falha no `/scientific-paper-meta-analysis`: {detail}")

    if isinstance(payload, dict) and payload:
        return _render_scientific_pipeline_response(payload)
    if out_text:
        return _truncate(out_text)
    return "Pipeline científico concluído."


async def _run_scientific_pipeline_with_feedback(
    raw_args: str,
    *,
    gateway: Any = None,
    source: Any = None,
) -> str:
    if gateway is None or source is None:
        return await _execute_scientific_pipeline(raw_args)

    adapter, chat_id, metadata = _gateway_adapter_for_source(gateway, source)
    typing_started = False
    if adapter is not None and hasattr(adapter, "send_typing"):
        try:
            await adapter.send_typing(chat_id, metadata=metadata)
            typing_started = True
        except Exception:
            logger.debug("Failed to start typing indicator for scientific pipeline", exc_info=True)

    try:
        return await _execute_scientific_pipeline(raw_args)
    finally:
        if typing_started and adapter is not None and hasattr(adapter, "stop_typing"):
            try:
                await adapter.stop_typing(chat_id)
            except Exception:
                logger.debug("Failed to stop typing indicator for scientific pipeline", exc_info=True)


def _platform_value(source: Any) -> str:
    platform = getattr(source, "platform", None)
    return str(getattr(platform, "value", platform) or "").strip().lower()


def _capture_gateway_context(*, event: Any = None, gateway: Any = None) -> None:
    source = getattr(event, "source", None)
    _CURRENT_GATEWAY_CONTEXT.set(
        {
            "event": event,
            "gateway": gateway,
            "source": source,
            "interaction": getattr(event, "raw_message", None),
        }
    )


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


def _resolve_status_action(raw_args: str, interaction: Any = None) -> str:
    text = str(raw_args or "").strip().lower()
    if text:
        return text
    option_map = _interaction_option_map(interaction)
    return str(option_map.get("action") or "").strip().lower()


def _resolve_acl_raw_args(raw_args: str, interaction: Any = None) -> str:
    text = str(raw_args or "").strip()
    if text:
        return text

    option_map = _interaction_option_map(interaction)
    action = str(option_map.get("action") or "").strip()
    args = str(option_map.get("args") or "").strip()
    if not action:
        if any(str(option_map.get(key) or "").strip() for key in ("command", "role", "min_role")):
            action = "command"
        elif any(
            str(option_map.get(key) or "").strip()
            for key in (
                "channel",
                "mode",
                "model_key",
                "allowed_commands",
                "allowed_skills",
                "always_allowed_commands",
                "default_action",
                "free_text_policy",
                "instructions",
                "label",
            )
        ):
            action = "channel"
    if action == "help":
        return "help"
    if action and args:
        return f"{action} {args}".strip()
    structured_parts: list[str] = []
    for key in (
        "channel",
        "mode",
        "model_key",
        "allowed_commands",
        "allowed_skills",
        "always_allowed_commands",
        "default_action",
        "free_text_policy",
        "instructions",
        "label",
        "command",
        "role",
        "min_role",
    ):
        value = str(option_map.get(key) or "").strip()
        if not value:
            continue
        structured_parts.append(f"{key}:{_quote_command_value(value)}")
    if action and structured_parts:
        return " ".join([action, *structured_parts]).strip()
    if action:
        return action
    return args


def _resolve_slash_request(raw_args: str, interaction: Any = None) -> dict[str, str]:
    text = str(raw_args or "").strip()
    if text and text.lower() == "help":
        return {"help": "true"}

    option_map = _interaction_option_map(interaction)
    command = str(option_map.get("command") or "").strip().lower()
    enable = str(option_map.get("enable") or "").strip().lower()

    if text:
        if text.lower() == "help":
            return {"help": "true"}
        for token in shlex.split(text):
            if ":" in token:
                key, value = token.split(":", 1)
            elif "=" in token:
                key, value = token.split("=", 1)
            else:
                key, value = "command", token
            normalized = str(key or "").strip().lower().replace("-", "_")
            if normalized in {"command", "cmd", "slash"}:
                command = str(value or "").strip().lower()
            elif normalized in {"enable", "enabled"}:
                enable = str(value or "").strip().lower()
            elif normalized == "help":
                return {"help": "true"}

    result: dict[str, str] = {}
    if command:
        result["command"] = command.lstrip("/")
    if enable:
        result["enable"] = enable
    return result


def _resolve_clean_confirm(raw_args: str, interaction: Any = None) -> bool:
    text = str(raw_args or "").strip()
    option_map = _interaction_option_map(interaction)
    raw_value: Any = option_map.get("confirm", "")

    if text:
        for token in shlex.split(text):
            if ":" in token:
                key, value = token.split(":", 1)
            elif "=" in token:
                key, value = token.split("=", 1)
            else:
                key, value = "confirm", token
            if str(key or "").strip().lower().replace("-", "_") == "confirm":
                raw_value = value
                break

    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, (int, float)):
        return bool(raw_value)
    return str(raw_value or "").strip().lower() in {"1", "true", "yes", "y", "sim", "s"}


def _resolve_model_request(raw_args: str, interaction: Any = None) -> dict[str, str]:
    option_map = _interaction_option_map(interaction)
    request = {
        "name": str(option_map.get("name") or option_map.get("model") or "").strip(),
        "provider": str(option_map.get("provider") or "").strip().lower(),
        "list": str(option_map.get("list") or "").strip().lower(),
        "persist_global": "",
    }

    text = str(raw_args or "").strip()
    if text:
        for token in shlex.split(text):
            piece = str(token or "").strip()
            if not piece:
                continue
            if piece.startswith("--provider="):
                request["provider"] = piece.split("=", 1)[1].strip().lower()
                continue
            if piece == "--provider":
                continue
            if piece.startswith("--global"):
                request["persist_global"] = "true"
                continue
            if ":" in piece:
                key, value = piece.split(":", 1)
            elif "=" in piece:
                key, value = piece.split("=", 1)
            else:
                if not request["name"] and piece != "--provider":
                    request["name"] = piece
                continue
            normalized_key = str(key or "").strip().lower().replace("-", "_")
            if normalized_key in {"name", "model"}:
                request["name"] = str(value or "").strip()
            elif normalized_key == "provider":
                request["provider"] = str(value or "").strip().lower()
            elif normalized_key == "list":
                request["list"] = str(value or "").strip().lower()
            elif normalized_key in {"global", "persist"}:
                request["persist_global"] = str(value or "").strip().lower()

        if "--provider" in text.split():
            tokens = text.split()
            for index, token in enumerate(tokens[:-1]):
                if token == "--provider":
                    request["provider"] = str(tokens[index + 1] or "").strip().lower()
                    break

    return request


def _load_governance_models_payload() -> dict[str, Any]:
    path = resolve_governance_models_file()
    if not path.exists():
        return {"version": 1, "node": runtime_node_name(), "models": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    models = payload.get("models")
    if not isinstance(models, list):
        payload["models"] = []
    payload.setdefault("version", 1)
    payload.setdefault("node", runtime_node_name())
    return payload


def _save_governance_models_payload(payload: dict[str, Any]) -> None:
    path = resolve_governance_models_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _slug_model_key(provider: str, model: str, existing_keys: set[str]) -> str:
    leaf = str(model or "").strip().split("/")[-1].lower()
    base = re.sub(r"[^a-z0-9]+", "", leaf) or re.sub(r"[^a-z0-9]+", "", str(provider or "").lower()) or "model"
    key = base
    index = 2
    while key in existing_keys:
        key = f"{base}{index}"
        index += 1
    return key


def _label_for_model_entry(provider: str, model: str) -> str:
    leaf = str(model or "").strip().split("/")[-1].replace("-", " ").replace("_", " ").strip()
    pretty_model = " ".join(part.capitalize() for part in leaf.split()) or str(model or "").strip()
    pretty_provider = str(provider or "").strip().upper() if len(str(provider or "").strip()) <= 4 else str(provider or "").strip().title()
    return f"{pretty_model} ({pretty_provider})"


def _record_governance_model(provider: str, model: str) -> dict[str, str]:
    provider_value = str(provider or "").strip()
    model_value = str(model or "").strip()
    payload = _load_governance_models_payload()
    models = [dict(item) for item in payload.get("models") or [] if isinstance(item, dict)]
    for item in models:
        if (
            str(item.get("provider") or "").strip().lower() == provider_value.lower()
            and str(item.get("model") or "").strip() == model_value
        ):
            return {
                "key": str(item.get("key") or "").strip(),
                "label": str(item.get("label") or "").strip(),
                "status": "existing",
            }

    existing_keys = {
        str(item.get("key") or "").strip().lower()
        for item in models
        if str(item.get("key") or "").strip()
    }
    key = _slug_model_key(provider_value, model_value, existing_keys)
    label = _label_for_model_entry(provider_value, model_value)
    models.append(
        {
            "key": key,
            "label": label,
            "provider": provider_value,
            "model": model_value,
        }
    )
    payload["models"] = models
    payload["updated_at"] = _utc_now()
    _save_governance_models_payload(payload)
    return {"key": key, "label": label, "status": "added"}


def _format_configured_models_text(*, current_model: str = "", current_provider: str = "") -> str:
    payload = _load_governance_models_payload()
    models = [dict(item) for item in payload.get("models") or [] if isinstance(item, dict)]
    lines = ["🧠 **Discord Model Catalog**", ""]
    if current_model or current_provider:
        lines.append(
            f"Current: `{current_model or 'unknown'}`"
            + (f" via `{current_provider}`" if current_provider else "")
        )
        lines.append("")
    if not models:
        lines.append("No configured models yet.")
    else:
        for item in models:
            lines.append(
                f"- `{item.get('key')}` → `{item.get('provider')}` / `{item.get('model')}`"
            )
    lines.extend(
        [
            "",
            "Use `/model name:<model> provider:<slug>` to add or switch.",
            "Use `/model list:available` to inspect authenticated provider catalogs.",
        ]
    )
    return "\n".join(lines)


def _format_available_models_text(
    *,
    current_provider: str,
    current_model: str,
    current_base_url: str,
    user_providers: Any,
    custom_providers: Any,
) -> str:
    from hermes_cli.model_switch import list_authenticated_providers
    from hermes_cli.providers import get_label

    lines = [f"Current: `{current_model or 'unknown'}` on {get_label(current_provider)}", ""]
    providers = list_authenticated_providers(
        current_provider=current_provider,
        current_base_url=current_base_url,
        user_providers=user_providers,
        custom_providers=custom_providers,
        max_models=10,
    )
    if not providers:
        lines.append("No authenticated providers found.")
    else:
        for provider in providers:
            tag = " (current)" if provider.get("is_current") else ""
            lines.append(f"**{provider.get('name') or provider.get('slug') or 'Provider'}** `{provider.get('slug')}`{tag}:")
            models = list(provider.get("models") or [])
            if models:
                model_text = ", ".join(f"`{model}`" for model in models[:10])
                extra = ""
                total = int(provider.get("total_models") or 0)
                if total > len(models[:10]):
                    extra = f" (+{total - len(models[:10])} more)"
                lines.append(f"  {model_text}{extra}")
            elif provider.get("api_url"):
                lines.append(f"  `{provider.get('api_url')}`")
            lines.append("")
    lines.append("Use `/model name:<model> provider:<slug>` to switch.")
    return "\n".join(lines)


def _load_persisted_node_model_override() -> dict[str, str]:
    payload = load_active_model_state()
    model_value = str(payload.get("model") or "").strip()
    provider_value = str(payload.get("provider") or "").strip()
    if not model_value or not provider_value:
        return {}
    override = {
        "model": model_value,
        "provider": provider_value,
    }
    for key in ("base_url", "api_mode"):
        value = str(payload.get(key) or "").strip()
        if value:
            override[key] = value
    return override


def _sync_node_model_to_config(
    *,
    model: str,
    provider: str,
    base_url: str = "",
    api_mode: str = "",
) -> bool:
    model_value = str(model or "").strip()
    provider_value = str(provider or "").strip()
    if not model_value or not provider_value:
        return False
    try:
        from hermes_cli.config import load_config, save_config

        cfg = load_config() or {}
        if not isinstance(cfg, dict):
            cfg = {}
        model_cfg = cfg.setdefault("model", {})
        if not isinstance(model_cfg, dict):
            model_cfg = {}
            cfg["model"] = model_cfg

        changed = False
        desired = {
            "default": model_value,
            "provider": provider_value,
        }
        for key, value in desired.items():
            if str(model_cfg.get(key) or "").strip() != value:
                model_cfg[key] = value
                changed = True

        normalized_base_url = str(base_url or "").strip()
        normalized_api_mode = str(api_mode or "").strip()

        if normalized_base_url:
            if str(model_cfg.get("base_url") or "").strip() != normalized_base_url:
                model_cfg["base_url"] = normalized_base_url
                changed = True
        elif "base_url" in model_cfg:
            model_cfg.pop("base_url", None)
            changed = True

        if normalized_api_mode:
            if str(model_cfg.get("api_mode") or "").strip() != normalized_api_mode:
                model_cfg["api_mode"] = normalized_api_mode
                changed = True
        elif "api_mode" in model_cfg:
            model_cfg.pop("api_mode", None)
            changed = True

        if changed:
            save_config(cfg)
        return changed
    except Exception:
        logger.warning("Failed to sync persisted node model to config.yaml", exc_info=True)
        return False


def _sync_persisted_node_model_to_config() -> bool:
    persisted = _load_persisted_node_model_override()
    if not persisted:
        return False
    return _sync_node_model_to_config(
        model=str(persisted.get("model") or ""),
        provider=str(persisted.get("provider") or ""),
        base_url=str(persisted.get("base_url") or ""),
        api_mode=str(persisted.get("api_mode") or ""),
    )


def _hydrate_persisted_node_model_override(gateway: Any, source: Any) -> dict[str, str]:
    if gateway is None or source is None:
        return {}
    persisted = _load_persisted_node_model_override()
    if not persisted:
        return {}
    try:
        session_key = str(gateway._session_key_for_source(source) or "").strip()
    except Exception:
        logger.debug("Could not resolve session key for persisted node model override", exc_info=True)
        return {}
    if not session_key:
        return {}
    overrides = getattr(gateway, "_session_model_overrides", None)
    if not isinstance(overrides, dict):
        overrides = {}
        gateway._session_model_overrides = overrides
    existing = overrides.get(session_key)
    if isinstance(existing, dict) and str(existing.get("model") or "").strip():
        return dict(existing)
    overrides[session_key] = dict(persisted)
    return dict(persisted)


def _load_gateway_model_context(gateway: Any, source: Any) -> dict[str, Any]:
    import yaml

    current_model = ""
    current_provider = "openrouter"
    current_base_url = ""
    current_api_key = ""
    user_providers = None
    custom_providers = None
    config_path = resolve_runtime_hermes_home() / "config.yaml"
    try:
        if config_path.exists():
            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            model_cfg = cfg.get("model", {})
            if isinstance(model_cfg, dict):
                current_model = str(model_cfg.get("default") or "").strip()
                current_provider = str(model_cfg.get("provider") or current_provider).strip() or current_provider
                current_base_url = str(model_cfg.get("base_url") or "").strip()
            user_providers = cfg.get("providers")
            try:
                from hermes_cli.config import get_compatible_custom_providers
                custom_providers = get_compatible_custom_providers(cfg)
            except Exception:
                custom_providers = cfg.get("custom_providers")
        else:
            cfg = {}
    except Exception:
        cfg = {}

    persisted_override = _load_persisted_node_model_override()
    if persisted_override:
        current_model = str(persisted_override.get("model") or current_model).strip()
        current_provider = str(persisted_override.get("provider") or current_provider).strip() or current_provider
        current_base_url = str(persisted_override.get("base_url") or current_base_url).strip()

    session_key = ""
    if gateway is not None and source is not None:
        try:
            session_key = gateway._session_key_for_source(source)
        except Exception:
            logger.debug("Could not resolve session key for /model override", exc_info=True)
    override = {}
    overrides = getattr(gateway, "_session_model_overrides", None)
    if session_key and isinstance(overrides, dict):
        override = dict(overrides.get(session_key) or {})
    if override:
        current_model = str(override.get("model") or current_model).strip()
        current_provider = str(override.get("provider") or current_provider).strip() or current_provider
        current_base_url = str(override.get("base_url") or current_base_url).strip()
        current_api_key = str(override.get("api_key") or current_api_key).strip()
    return {
        "config": cfg,
        "config_path": config_path,
        "session_key": session_key,
        "current_model": current_model,
        "current_provider": current_provider,
        "current_base_url": current_base_url,
        "current_api_key": current_api_key,
        "user_providers": user_providers,
        "custom_providers": custom_providers,
    }


def _parent_session_key_for_thread_source(gateway: Any, source: Any) -> str:
    if gateway is None or source is None:
        return ""
    thread_id = str(getattr(source, "thread_id", "") or "").strip()
    parent_chat_id = str(getattr(source, "parent_chat_id", "") or "").strip()
    if not thread_id or not parent_chat_id:
        return ""
    try:
        from gateway.session import SessionSource

        parent_source = SessionSource(
            platform=getattr(source, "platform", None),
            chat_id=parent_chat_id,
            chat_name=getattr(source, "chat_name", None),
            chat_type="group",
            user_id=getattr(source, "user_id", None),
            user_name=getattr(source, "user_name", None),
            chat_topic=getattr(source, "chat_topic", None),
            user_id_alt=getattr(source, "user_id_alt", None),
            chat_id_alt=getattr(source, "chat_id_alt", None),
            is_bot=bool(getattr(source, "is_bot", False)),
            guild_id=getattr(source, "guild_id", None),
            parent_chat_id=None,
            message_id=getattr(source, "message_id", None),
        )
        return str(gateway._session_key_for_source(parent_source) or "").strip()
    except Exception:
        logger.debug("Could not resolve parent channel session key for threaded Discord source", exc_info=True)
        return ""


def _inherit_parent_channel_model_state(gateway: Any, source: Any) -> None:
    """Mirror parent-channel /model state into a Discord thread session on first turn.

    This keeps the fix plugin-scoped: native slash `/model` can be invoked from
    the parent channel, and when Discord auto-threads the next free-text turn we
    copy the override and pending note into the thread session before Hermes
    core resolves runtime.
    """
    if gateway is None or source is None:
        return
    current_thread_id = str(getattr(source, "thread_id", "") or "").strip()
    parent_chat_id = str(getattr(source, "parent_chat_id", "") or "").strip()
    if not current_thread_id or not parent_chat_id:
        return

    try:
        thread_session_key = str(gateway._session_key_for_source(source) or "").strip()
    except Exception:
        logger.debug("Could not resolve thread session key for Discord /model inheritance", exc_info=True)
        return
    if not thread_session_key:
        return

    parent_session_key = _parent_session_key_for_thread_source(gateway, source)
    if not parent_session_key or parent_session_key == thread_session_key:
        return

    overrides = getattr(gateway, "_session_model_overrides", None)
    if isinstance(overrides, dict) and thread_session_key not in overrides and parent_session_key in overrides:
        overrides[thread_session_key] = dict(overrides[parent_session_key])

    pending_notes = getattr(gateway, "_pending_model_notes", None)
    if isinstance(pending_notes, dict) and thread_session_key not in pending_notes and parent_session_key in pending_notes:
        pending_notes[thread_session_key] = pending_notes.pop(parent_session_key)


def _apply_gateway_model_switch(
    gateway: Any,
    *,
    session_key: str,
    current_model: str,
    result: Any,
) -> None:
    cached_entry = None
    cache_lock = getattr(gateway, "_agent_cache_lock", None)
    cache = getattr(gateway, "_agent_cache", None)
    if cache_lock is not None and cache is not None:
        try:
            with cache_lock:
                cached_entry = cache.get(session_key)
        except Exception:
            cached_entry = None
    if cached_entry and cached_entry[0] is not None:
        try:
            cached_entry[0].switch_model(
                new_model=result.new_model,
                new_provider=result.target_provider,
                api_key=result.api_key,
                base_url=result.base_url,
                api_mode=result.api_mode,
            )
        except Exception:
            logger.warning("In-place model switch failed for cached agent", exc_info=True)

    if not hasattr(gateway, "_pending_model_notes"):
        gateway._pending_model_notes = {}
    gateway._pending_model_notes[session_key] = (
        f"[Note: model was just switched from {current_model or 'unknown'} to {result.new_model} "
        f"via {result.provider_label or result.target_provider}. "
        "Adjust your self-identification accordingly.]"
    )

    overrides = getattr(gateway, "_session_model_overrides", None)
    if isinstance(overrides, dict):
        overrides[session_key] = {
            "model": result.new_model,
            "provider": result.target_provider,
            "api_key": result.api_key,
            "base_url": result.base_url,
            "api_mode": result.api_mode,
        }
    evict = getattr(gateway, "_evict_cached_agent", None)
    if callable(evict):
        try:
            evict(session_key)
        except Exception:
            logger.debug("Could not evict cached agent after /model switch", exc_info=True)


def _smoke_test_model_switch(
    *,
    model: str,
    provider: str,
    api_key: str,
    base_url: str,
    api_mode: str,
    timeout_seconds: float = 12.0,
) -> tuple[bool, str]:
    normalized_mode = str(api_mode or "").strip().lower()
    if normalized_mode and normalized_mode != "chat_completions":
        return True, ""
    try:
        from openai import OpenAI
    except Exception as exc:
        logger.debug("Skipping /model smoke test because OpenAI client is unavailable: %s", exc)
        return True, ""

    client = OpenAI(
        api_key=str(api_key or ""),
        base_url=str(base_url or "") or None,
        timeout=float(timeout_seconds),
    )
    request = {
        "model": str(model or ""),
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "max_tokens": 1,
    }
    try:
        client.chat.completions.create(**request)
        return True, ""
    except Exception as first_exc:
        retry_message = str(first_exc or "")
        if "max_tokens" in retry_message.lower():
            retry_request = dict(request)
            retry_request.pop("max_tokens", None)
            retry_request["max_completion_tokens"] = 1
            try:
                client.chat.completions.create(**retry_request)
                return True, ""
            except Exception as retry_exc:
                first_exc = retry_exc
        provider_label = str(provider or "provider").strip() or "provider"
        return False, f"{provider_label}: {first_exc}"


def _format_model_switch_success(
    result: Any,
    *,
    current_base_url: str,
    current_api_key: str,
    custom_providers: Any,
    persist_global: bool,
    catalog_record: dict[str, str],
) -> str:
    from hermes_cli.model_switch import resolve_display_context_length

    provider_label = result.provider_label or result.target_provider
    lines = [f"Model switched to `{result.new_model}`", f"Provider: {provider_label}"]
    ctx = resolve_display_context_length(
        result.new_model,
        result.target_provider,
        base_url=result.base_url or current_base_url or "",
        api_key=result.api_key or current_api_key or "",
        model_info=result.model_info,
        custom_providers=custom_providers,
    )
    if ctx:
        lines.append(f"Context: {ctx:,} tokens")
    if result.model_info:
        if result.model_info.max_output:
            lines.append(f"Max output: {result.model_info.max_output:,} tokens")
        if result.model_info.has_cost_data():
            lines.append(f"Cost: {result.model_info.format_cost()}")
        lines.append(f"Capabilities: {result.model_info.format_capabilities()}")
    if result.warning_message:
        lines.append(f"Warning: {result.warning_message}")
    lines.append(
        f"Catalog: `{catalog_record.get('key')}` "
        f"({'added' if catalog_record.get('status') == 'added' else 'already present'})"
    )
    lines.append("Saved as node default in `cache/status/active_model.json`.")
    lines.append("Synced to this node's `config.yaml` so Hermes restarts keep using it.")
    if persist_global:
        lines.append("`global:true` also updated the standard Hermes model config path.")
    return "\n".join(lines)


async def _execute_model(raw_args: str, *, gateway: Any = None, source: Any = None, interaction: Any = None) -> str:
    from hermes_cli.model_switch import switch_model

    request = _resolve_model_request(raw_args, interaction)
    model_name = str(request.get("name") or "").strip()
    provider_name = str(request.get("provider") or "").strip().lower()
    list_mode = str(request.get("list") or "").strip().lower()
    persist_global = _parse_bool(str(request.get("persist_global") or "")) is True

    context = _load_gateway_model_context(gateway, source)
    if list_mode in {"help"}:
        return (
            "Uso do `/model`:\n"
            "- `/model name:deepseek-ai/deepseek-v4-pro provider:nvidia`\n"
            "- `/model provider:nvidia`\n"
            "- `/model list:configured`\n"
            "- `/model list:available`\n"
            "- `/model name:gpt-5.4 provider:openai-codex global:true`"
        )
    if list_mode == "available":
        return _format_available_models_text(
            current_provider=context["current_provider"],
            current_model=context["current_model"],
            current_base_url=context["current_base_url"],
            user_providers=context["user_providers"],
            custom_providers=context["custom_providers"],
        )
    if list_mode == "configured" or (not model_name and not provider_name):
        return _format_configured_models_text(
            current_model=context["current_model"],
            current_provider=context["current_provider"],
        )

    result = switch_model(
        raw_input=model_name,
        current_provider=context["current_provider"],
        current_model=context["current_model"],
        current_base_url=context["current_base_url"],
        current_api_key=context["current_api_key"],
        is_global=persist_global,
        explicit_provider=provider_name or None,
        user_providers=context["user_providers"],
        custom_providers=context["custom_providers"],
    )
    if not result.success:
        return f"Error: {result.error_message}"

    smoke_ok, smoke_error = _smoke_test_model_switch(
        model=result.new_model,
        provider=result.target_provider,
        api_key=result.api_key,
        base_url=result.base_url or context["current_base_url"] or "",
        api_mode=result.api_mode or "",
    )
    if not smoke_ok:
        return (
            "Error: model switch failed live verification; nothing was persisted.\n"
            f"Provider/model: `{result.target_provider}` / `{result.new_model}`\n"
            f"Reason: {smoke_error}"
        )

    if gateway is not None and context["session_key"]:
        _apply_gateway_model_switch(
            gateway,
            session_key=context["session_key"],
            current_model=context["current_model"],
            result=result,
        )
    try:
        write_active_model_state(
            model=result.new_model,
            provider=result.target_provider,
            base_url=result.base_url or "",
            api_mode=result.api_mode or "",
        )
    except Exception:
        logger.warning("Failed to persist node active model state after /model switch", exc_info=True)
    _sync_node_model_to_config(
        model=result.new_model,
        provider=result.target_provider,
        base_url=result.base_url or "",
        api_mode=result.api_mode or "",
    )

    if persist_global:
        try:
            from hermes_cli.config import save_config
            cfg = dict(context.get("config") or {})
            model_cfg = cfg.setdefault("model", {})
            model_cfg["default"] = result.new_model
            model_cfg["provider"] = result.target_provider
            if result.base_url:
                model_cfg["base_url"] = result.base_url
            save_config(cfg)
        except Exception:
            logger.warning("Failed to persist /model switch to config.yaml", exc_info=True)

    catalog_record = _record_governance_model(result.target_provider, result.new_model)
    return _format_model_switch_success(
        result,
        current_base_url=context["current_base_url"],
        current_api_key=context["current_api_key"],
        custom_providers=context["custom_providers"],
        persist_global=persist_global,
        catalog_record=catalog_record,
    )


async def _handle_model_and_reply(
    raw_args: str,
    *,
    gateway: Any = None,
    source: Any = None,
    interaction: Any = None,
) -> None:
    reply = await _execute_model(raw_args, gateway=gateway, source=source, interaction=interaction)
    if interaction is not None:
        try:
            await interaction.followup.send(reply, ephemeral=True)
            return
        except Exception:
            logger.debug("Could not send /model followup response", exc_info=True)
    _schedule_gateway_reply(gateway, source, reply)


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


def _resolve_metricas_raw_args(raw_args: str, interaction: Any = None) -> str:
    text = str(raw_args or "").strip()
    if text:
        return text

    option_map = _interaction_option_map(interaction)
    if str(option_map.get("action") or "").strip().lower() == "help":
        return "help"
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


def parse_metricas_args(raw_args: str) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "dias": 30,
        "formato": "text",
        "skill": "",
        "action": "",
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
        elif normalized_key == "action":
            values["action"] = str(value or "").strip().lower()
    return values


async def handle_metricas(raw_args: str) -> str:
    if not is_command_enabled("metricas"):
        return "🚫 `/metricas` está desabilitado neste node. Use `/slash command:metricas enable:true`."

    gateway_context = _current_gateway_context()
    interaction = gateway_context.get("interaction")
    resolved_args = _resolve_metricas_raw_args(raw_args, interaction)
    if str(resolved_args or "").strip().lower() == "help":
        return _definition_help_text("metricas", "Uso: `/metricas dias:7 formato:text`.")
    options = parse_metricas_args(resolved_args)
    if options.get("action") == "help" or str(raw_args or "").strip().lower() == "help":
        return _definition_help_text("metricas", "Uso: `/metricas dias:7 formato:text`.")
    script_path = resolve_metrics_script_path()
    if not script_path.exists():
        return f"Script do dashboard de métricas não encontrado: `{script_path}`"

    source = gateway_context.get("source")
    actor_user_id = str(
        getattr(getattr(interaction, "user", None), "id", "")
        or getattr(source, "user_id", "")
        or ""
    ).strip()
    actor_user_name = str(
        getattr(getattr(interaction, "user", None), "display_name", "")
        or getattr(getattr(interaction, "user", None), "name", "")
        or getattr(source, "user_name", "")
        or ""
    ).strip()

    fmt = str(options.get("formato") or "text").strip().lower() or "text"
    if fmt not in {"text", "json", "csv"}:
        fmt = "text"

    cmd = [
        resolve_python_bin(required_modules=("sqlite3", "requests")),
        str(script_path),
        "dashboard",
        "--days",
        str(max(1, int(options.get("dias") or 30))),
        "--format",
        fmt,
    ]
    if str(options.get("skill") or "").strip():
        cmd.extend(["--skill-name", str(options.get("skill") or "").strip()])
    if actor_user_id:
        cmd.extend(["--actor-user-id", actor_user_id])
    if actor_user_name:
        cmd.extend(["--actor-user-name", actor_user_name])
    if interaction is not None:
        # Native Discord interactions were already authorized by role ACL.
        cmd.append("--skip-dashboard-admin-check")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        return "Timeout ao executar `/metricas` (60s)."
    except Exception as exc:
        return f"Falha ao iniciar `/metricas`: {exc}"

    out_text = (stdout or b"").decode(errors="ignore").strip()
    err_text = (stderr or b"").decode(errors="ignore").strip()
    try:
        payload = json.loads(out_text) if out_text else {}
    except Exception:
        payload = {}

    if proc.returncode != 0:
        detail = (
            payload.get("error")
            if isinstance(payload, dict) and payload.get("error")
            else err_text or out_text or "erro desconhecido."
        )
        return _truncate(f"Falha no `/metricas`: {detail}")

    if isinstance(payload, dict) and payload:
        if fmt == "text":
            return _truncate(str(payload.get("text") or "Dashboard de métricas executado."))
        if fmt == "csv":
            csv_text = str(payload.get("csv") or "").strip()
            if csv_text:
                return _truncate(f"```csv\n{csv_text}\n```")
        return _truncate("```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```")
    if out_text:
        return _truncate(out_text)
    return "Dashboard de métricas executado."


async def handle_scientific_paper_meta_analysis(raw_args: str) -> str:
    gateway_context = _current_gateway_context()
    return await _run_scientific_pipeline_with_feedback(
        raw_args,
        gateway=gateway_context.get("gateway"),
        source=gateway_context.get("source"),
    )


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
    return _definition_help_text(
        "faltas",
        (
            "Uso do `/faltas`:\n"
            "- `/faltas action:listar loja:loja1 formato:links`\n"
            "- `/faltas action:adicionar itens:\"produto\" loja:loja2`\n"
            "- `/faltas action:remover itens:\"produto\" loja:loja1`\n"
            "- `/faltas action:limpar confirm:sim`\n"
            "- ações: `listar`, `adicionar`, `remover`, `limpar`, `help`"
        ),
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
    if payload.get("ok") is False:
        detail = str(payload.get("error") or payload.get("message") or "").strip()
        if detail:
            return f"Falha no `/faltas`: {detail}"
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
        return [], "Ação inválida para `/faltas`."

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
    if not is_command_enabled("faltas"):
        return "🚫 `/faltas` está desabilitado neste node. Use `/slash command:faltas enable:true`."

    gateway_context = _current_gateway_context()
    interaction = gateway_context.get("interaction")
    source = gateway_context.get("source")
    return await _execute_faltas(_resolve_faltas_raw_args(raw_args, interaction), source=source)


def _usage_text() -> str:
    return _definition_help_text(
        "acl",
        (
            "Uso do `/acl`:\n"
            "- `/acl command command:metricas role:gerente`\n"
            "- `/acl channel channel:123456 mode:specific model_key:nemotron120b allowed_commands:faltas always_allowed_commands:status default_action:skill:add free_text_policy:strict_item`\n"
            "- `/acl channel channel:1497340589191204898 mode:specific model_key:minimaxm26 allowed_commands:scientific-paper-meta-analysis allowed_skills:scientific-paper-meta-analysis always_allowed_commands:status default_action:command:scientific-paper-meta-analysis instructions:\"Canal dedicado a meta-analysis de papers\"`\n"
            "- `/acl channel channel:123456 mode:default`\n\n"
            "Comportamento:\n"
            "- `/acl command` define a role minima por comando neste node\n"
            "- `/acl channel` transforma um canal em `livre` ou `condicionado`\n"
            "- Em canal `condicionado`, `allowed_commands` e `allowed_skills` fecham o escopo\n"
            "- `default_action:skill:add` faz texto livre virar fluxo de faltas\n"
            "- `default_action:command:<nome>` faz texto livre virar `/<nome> ...`\n"
            "- `always_allowed_commands:status` deixa comandos de diagnostico passarem\n"
            "- `/acl help` mostra esta ajuda"
        ),
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
    if not is_command_enabled("acl"):
        return "🚫 `/acl` está desabilitado neste node. Use `/slash command:acl enable:true`."

    gateway_context = _current_gateway_context()
    raw_args = _resolve_acl_raw_args(raw_args, gateway_context.get("interaction"))
    if str(raw_args or "").strip().lower() in {"", "help"}:
        return _usage_text()

    subcommand, values = parse_acl_args(raw_args)
    if not subcommand:
        return _usage_text()

    if subcommand == "command":
        command_value = values.get("command") or values.get("cmd") or ""
        role_value = values.get("role") or values.get("min_role") or ""
        if not command_value or not role_value:
            return "❌ Informe `command:<nome>` e `role:<hierarquia>`.\n\n" + _usage_text()
        try:
            role_acl = load_role_acl_module()
            updater = getattr(role_acl, "update_command_min_role", None)
            if not callable(updater):
                raise AttributeError("legacy role ACL updater unavailable")
            result = updater(resolve_acl_path(), command_value, role_value)
        except Exception:
            logger.debug("Falling back to builtin ACL command updater", exc_info=True)
            try:
                result = _update_command_min_role_without_legacy(resolve_acl_path(), command_value, role_value)
            except ValueError as exc:
                return f"❌ {exc}\n\n{_usage_text()}"
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


def _format_slash_help() -> str:
    return _definition_help_text("slash", "Use `/slash` ou `/slash command:<nome> enable:true|false`.")


def _format_slash_listing() -> str:
    rows = list_commands_for_display()
    global_lines = ["Comandos `global`"]
    custom_lines = ["Comandos `custom`"]
    for row in rows:
        line = f"- /{row.get('name')}: {'enabled' if row.get('enabled') else 'disabled'}"
        description = str(row.get("description") or "").strip()
        if description:
            line += f" — {description}"
        if str(row.get("name") or "").strip().lower() == "status":
            line += " (disable => Hermes builtin /status)"
        if str(row.get("name") or "").strip().lower() == "slash":
            line += " (always enabled)"
        if str(row.get("namespace") or "") == "global":
            global_lines.append(line)
        else:
            custom_lines.append(line)
    return "\n".join(global_lines + [""] + custom_lines)


def _parse_bool(value: str) -> bool | None:
    clean = str(value or "").strip().lower()
    if clean in {"1", "true", "yes", "on", "sim"}:
        return True
    if clean in {"0", "false", "no", "off", "nao", "não"}:
        return False
    return None


def _peer_nodes_for_scope(app_id: str, guild_id: str) -> list[str]:
    env_root = Path("/local/agents/envs")
    peers: list[str] = []
    for env_file in sorted(env_root.glob("*.env")):
        text = env_file.read_text(encoding="utf-8")
        values = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        if values.get("DISCORD_APP_ID", "") != app_id:
            continue
        if values.get("DISCORD_SERVER_ID", values.get("DISCORD_GUILD_ID", "")) != guild_id:
            continue
        if not (
            str(values.get("PLUGIN_DISCORD_SLASH_COMMANDS", "")).lower() in {"1", "true", "yes", "on"}
            or str(values.get("PLUGIN_DISCORD_GOVERNANCE", "")).lower() in {"1", "true", "yes", "on"}
        ):
            continue
        peers.append(env_file.stem)
    return peers


def _mirror_scope_payload(payload: dict[str, Any]) -> list[str]:
    app_id = str(payload.get("app_id") or os.getenv("DISCORD_APP_ID") or "").strip()
    guild_id = str(payload.get("guild_id") or os.getenv("DISCORD_SERVER_ID") or os.getenv("DISCORD_GUILD_ID") or "").strip()
    if not app_id or not guild_id:
        return []
    mirrored: list[str] = []
    for node_name in _peer_nodes_for_scope(app_id, guild_id):
        path = (
            Path("/local/agents/nodes")
            / node_name
            / "workspace"
            / "plugins"
            / "discord-slash-commands"
            / "cache"
            / "state"
            / "app_scope.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        mirrored.append(node_name)
    return mirrored


def _update_node_activation_for_custom(command_name: str, enabled: bool) -> None:
    payload = load_node_activation() or {}
    current = {
        str(item).strip().lower()
        for item in payload.get("custom_enabled") or []
        if str(item).strip()
    }
    if enabled:
        current.add(command_name)
    else:
        current.discard(command_name)
    payload["version"] = 1
    payload["node_name"] = str(os.getenv("NODE_NAME", "") or "").strip() or "orchestrator"
    payload["custom_enabled"] = sorted(current)
    payload["updated_at"] = str(load_app_scope().get("updated_at") or "")
    write_node_activation(payload)


def _startup_reconcile_enabled() -> bool:
    raw = str(os.getenv("HERMES_DISCORD_SLASH_STARTUP_RECONCILE", "true") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _build_reconcile_command() -> list[str]:
    cmd = [
        resolve_python_bin(required_modules=("yaml",)),
        str(resolve_register_script_path()),
        "--env-file",
        str(resolve_runtime_env_file()),
        "--cache-root",
        str(resolve_runtime_cache_root()),
    ]
    app_id = str(os.getenv("DISCORD_APP_ID", "") or "").strip()
    guild_id = str(os.getenv("DISCORD_SERVER_ID", "") or os.getenv("DISCORD_GUILD_ID", "") or "").strip()
    bot_token = str(os.getenv("DISCORD_BOT_TOKEN", "") or "").strip()
    if app_id:
        cmd.extend(["--app-id", app_id])
    if guild_id:
        cmd.extend(["--guild-id", guild_id])
    if bot_token:
        cmd.extend(["--bot-token", bot_token])
    return cmd


def _startup_reconcile_worker() -> None:
    try:
        proc = subprocess.run(
            _build_reconcile_command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
            check=False,
        )
    except Exception as exc:
        logger.warning("Discord slash startup reconcile failed to run: %s", exc)
        return

    out_text = str(proc.stdout or "").strip()
    err_text = str(proc.stderr or "").strip()
    if proc.returncode != 0:
        logger.warning("Discord slash startup reconcile failed rc=%s: %s", proc.returncode, err_text or out_text)
        return

    try:
        payload = json.loads(out_text) if out_text else {}
    except Exception:
        logger.info("Discord slash startup reconcile completed")
        return
    summary = payload.get("summary") if isinstance(payload, dict) else {}
    if isinstance(summary, dict):
        logger.info(
            "Discord slash startup reconcile: patched=%s created=%s deleted=%s enabled=%s",
            summary.get("patched") or [],
            summary.get("created") or [],
            summary.get("deleted") or [],
            summary.get("enabled") or [],
        )
    else:
        logger.info("Discord slash startup reconcile completed")


def _schedule_startup_reconcile() -> None:
    global _STARTUP_RECONCILE_SCHEDULED
    if _STARTUP_RECONCILE_SCHEDULED or not _startup_reconcile_enabled():
        return
    app_id = str(os.getenv("DISCORD_APP_ID", "") or "").strip()
    guild_id = str(os.getenv("DISCORD_SERVER_ID", "") or os.getenv("DISCORD_GUILD_ID", "") or "").strip()
    bot_token = str(os.getenv("DISCORD_BOT_TOKEN", "") or "").strip()
    if not (app_id and guild_id and bot_token):
        logger.info("Discord slash startup reconcile skipped: missing app/guild/token")
        return
    _STARTUP_RECONCILE_SCHEDULED = True
    thread = threading.Thread(
        target=_startup_reconcile_worker,
        name="discord-slash-startup-reconcile",
        daemon=True,
    )
    thread.start()


async def _reconcile_registered_commands() -> str:
    cmd = _build_reconcile_command()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        return "Timed out while reconciling Discord slash commands."
    except Exception as exc:
        return f"Failed to reconcile Discord slash commands: {exc}"

    out_text = (stdout or b"").decode(errors="ignore").strip()
    err_text = (stderr or b"").decode(errors="ignore").strip()
    if proc.returncode != 0:
        return err_text or out_text or "Discord reconciliation failed."

    try:
        payload = json.loads(out_text) if out_text else {}
    except Exception:
        payload = {}
    summary = payload.get("summary") if isinstance(payload, dict) else {}
    if isinstance(summary, dict):
        touched = []
        for key in ("patched", "created", "deleted"):
            values = summary.get(key) or []
            if values:
                touched.append(f"{key}={','.join(str(item) for item in values)}")
        if touched:
            return "Discord reconciled: " + " ".join(touched)
    return "Discord commands reconciled."


async def handle_slash(raw_args: str) -> str:
    gateway_context = _current_gateway_context()
    request = _resolve_slash_request(raw_args, gateway_context.get("interaction"))
    if request.get("help") == "true":
        return _format_slash_help()
    if not request:
        return _format_slash_listing()

    command_name = str(request.get("command") or "").strip().lower().lstrip("/")
    enable_value = _parse_bool(request.get("enable", ""))
    if not command_name:
        return "Informe `command:<nome>` para alterar um comando.\n\n" + _format_slash_help()
    definition = get_command_definition(command_name)
    if not definition:
        return f"🚫 Comando desconhecido: `/{command_name}`."
    if enable_value is None:
        enabled_now = is_command_enabled(command_name)
        namespace = str(definition.get("namespace") or "")
        return f"`/{command_name}` namespace={namespace} enabled={enabled_now}"
    if command_name == "slash" and enable_value is False:
        return "🚫 `/slash` é sempre habilitado."

    scope = set_command_enabled(command_name, enable_value)
    if str(definition.get("namespace") or "") == "custom":
        _update_node_activation_for_custom(command_name, enable_value)
    mirrored_nodes = _mirror_scope_payload(scope)
    reconcile_text = await _reconcile_registered_commands()
    return "\n".join(
        [
            f"✅ `/{command_name}` agora está {'enabled' if enable_value else 'disabled'}.",
            f"scope nodes: {', '.join(mirrored_nodes) if mirrored_nodes else '(local only)'}",
            reconcile_text,
        ]
    )


async def _send_clean_followup(interaction: Any, content: str) -> None:
    message = _truncate(content)
    response = getattr(interaction, "response", None)
    followup = getattr(interaction, "followup", None)
    try:
        if response is not None and not response.is_done():
            await response.send_message(message, ephemeral=True)
            return
    except Exception:
        logger.debug("/clean initial response failed", exc_info=True)
    if followup is not None:
        await followup.send(message, ephemeral=True)


def _permission_has_flag(perms: Any, bit: int, attr: str) -> bool:
    if perms is None:
        return False
    if isinstance(perms, dict):
        if perms.get(attr) is True:
            return True
        value = perms.get("value")
        if value is None:
            value = perms.get("permissions")
        try:
            return bool(value is not None and (int(value) & bit))
        except Exception:
            return False
    if getattr(perms, attr, None) is True:
        return True
    value = getattr(perms, "value", None)
    try:
        if value is not None and (int(value) & bit):
            return True
    except Exception:
        pass
    try:
        if isinstance(perms, int) and (int(perms) & bit):
            return True
        if int(perms) & bit:
            return True
    except Exception:
        return False
    return False


def _interaction_permission_candidates(interaction: Any) -> list[Any]:
    candidates = [
        getattr(interaction, "permissions", None),
        getattr(interaction, "resolved_permissions", None),
        getattr(getattr(interaction, "user", None), "guild_permissions", None),
        getattr(getattr(interaction, "user", None), "resolved_permissions", None),
        getattr(getattr(interaction, "user", None), "permissions", None),
        getattr(getattr(interaction, "member", None), "guild_permissions", None),
        getattr(getattr(interaction, "member", None), "resolved_permissions", None),
        getattr(getattr(interaction, "member", None), "permissions", None),
    ]
    for holder in _interaction_role_holders(interaction):
        if isinstance(holder, dict):
            for key in ("permissions", "guild_permissions", "resolved_permissions"):
                candidates.append(holder.get(key))
    for role in _interaction_roles(interaction):
        candidates.append(getattr(role, "permissions", None))
        if isinstance(role, dict):
            candidates.append(role.get("permissions"))
    return [item for item in candidates if item is not None]


def _user_can_clean(interaction: Any) -> bool:
    for perms in _interaction_permission_candidates(interaction):
        if _permission_has_flag(perms, 0x8, "administrator") or _permission_has_flag(perms, 0x2000, "manage_messages"):
            return True
    return getattr(interaction, "guild", None) is None


async def _bot_can_clean(adapter: Any, interaction: Any, channel: Any) -> tuple[bool, str]:
    guild = getattr(interaction, "guild", None)
    if guild is None:
        return True, ""

    client = getattr(adapter, "_client", None)
    bot_user = getattr(client, "user", None)
    if client is None or bot_user is None:
        return False, "cliente do bot indisponivel"

    member = getattr(guild, "me", None)
    if member is None:
        try:
            member = guild.get_member(bot_user.id)
        except Exception:
            member = None
    if member is None:
        try:
            member = await guild.fetch_member(bot_user.id)
        except Exception:
            member = None

    if member is None or not hasattr(channel, "permissions_for"):
        return False, "nao consegui resolver permissoes do bot no canal/thread"

    perms = channel.permissions_for(member)
    ok = _permission_has_flag(perms, 0x8, "administrator") or _permission_has_flag(
        perms,
        0x2000,
        "manage_messages",
    )
    if not ok:
        return False, "faltando permissao Manage Messages para o bot"
    return True, ""


def _classify_clean_delete_error(exc: Exception) -> str:
    text = str(exc or "").lower()
    if "system message" in text or "cannot delete" in text:
        return "undeletable"
    if "missing permissions" in text or "403" in text or "50013" in text:
        return "permission"
    return "other"


def _clean_message_created_at(msg: Any) -> datetime | None:
    value = getattr(msg, "created_at", None)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return None


def _clean_can_bulk_delete(msg: Any, *, now: datetime) -> bool:
    created_at = _clean_message_created_at(msg)
    if created_at is None:
        return False
    # Discord bulk-delete rejects messages 14 days or older.
    return created_at > now - timedelta(days=14)


def _clean_chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


async def _clean_delete_one(msg: Any) -> tuple[bool, str]:
    try:
        await msg.delete()
        return True, ""
    except Exception as exc:
        return False, _classify_clean_delete_error(exc)


async def _clean_delete_individual(messages: list[Any], *, concurrency: int = 8) -> tuple[int, int, int, str]:
    if not messages:
        return 0, 0, 0, ""

    deleted = 0
    failed = 0
    skipped_undeletable = 0
    first_error = ""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _worker(msg: Any) -> tuple[bool, str, str]:
        async with semaphore:
            try:
                await msg.delete()
                return True, "", ""
            except Exception as exc:
                return False, _classify_clean_delete_error(exc), str(exc)

    for ok, kind, error in await asyncio.gather(*[_worker(msg) for msg in messages]):
        if ok:
            deleted += 1
        elif kind == "undeletable":
            skipped_undeletable += 1
        else:
            failed += 1
            if not first_error:
                first_error = error

    return deleted, failed, skipped_undeletable, first_error


async def _clean_delete_bulk(channel: Any, messages: list[Any]) -> tuple[int, list[Any], str]:
    if not messages:
        return 0, [], ""
    delete_messages = getattr(channel, "delete_messages", None)
    if not callable(delete_messages):
        return 0, messages, ""

    deleted = 0
    fallback: list[Any] = []
    first_error = ""
    for chunk in _clean_chunks(messages, 100):
        if len(chunk) == 1:
            fallback.extend(chunk)
            continue
        try:
            await delete_messages(chunk)
            deleted += len(chunk)
        except Exception as exc:
            fallback.extend(chunk)
            if not first_error:
                first_error = str(exc)
    return deleted, fallback, first_error


async def _execute_clean(
    raw_args: str,
    *,
    gateway: Any = None,
    source: Any = None,
    interaction: Any = None,
) -> str:
    if not is_command_enabled("clean"):
        return _disabled_command_message("clean")
    if interaction is None:
        return "🚫 `/clean` precisa ser chamado como slash command nativo do Discord."
    if not _resolve_clean_confirm(raw_args, interaction):
        return "⚠️ Ação destrutiva bloqueada. Use `/clean confirm:true` para confirmar a limpeza total."

    channel = getattr(interaction, "channel", None)
    if channel is None:
        return "❌ Não consegui identificar o canal para limpar."
    if not _user_can_clean(interaction):
        return "🚫 Você precisa de permissão de administrador ou `Manage Messages` para usar `/clean`."

    adapter, _chat_id, _metadata = _gateway_adapter_for_source(gateway, source)
    bot_ok, bot_reason = await _bot_can_clean(adapter, interaction, channel)
    if not bot_ok:
        return (
            "❌ Eu preciso da permissão `Manage Messages` neste canal/thread para executar `/clean`.\n"
            f"detalhe: {bot_reason}"
        )
    if not hasattr(channel, "history"):
        return "❌ Este tipo de canal não suporta limpeza de histórico."

    response = getattr(interaction, "response", None)
    try:
        if response is not None and not response.is_done():
            await response.defer(ephemeral=True)
    except Exception:
        logger.debug("/clean defer failed", exc_info=True)

    started = time.monotonic()
    deleted = 0
    failed = 0
    skipped_undeletable = 0
    first_error = ""

    try:
        now = datetime.now(timezone.utc)
        bulkable: list[Any] = []
        individual: list[Any] = []
        async for msg in channel.history(limit=None, oldest_first=False):
            if _clean_can_bulk_delete(msg, now=now):
                bulkable.append(msg)
            else:
                individual.append(msg)
            if len(bulkable) >= 100:
                bulk_deleted, fallback, bulk_error = await _clean_delete_bulk(channel, bulkable)
                deleted += bulk_deleted
                individual.extend(fallback)
                bulkable = []
                if bulk_error and not first_error:
                    first_error = bulk_error
                await asyncio.sleep(0)

        bulk_deleted, fallback, bulk_error = await _clean_delete_bulk(channel, bulkable)
        deleted += bulk_deleted
        individual.extend(fallback)
        if bulk_error and not first_error:
            first_error = bulk_error

        one_deleted, one_failed, one_undeletable, one_error = await _clean_delete_individual(individual)
        deleted += one_deleted
        failed += one_failed
        skipped_undeletable += one_undeletable
        if one_error and not first_error:
            first_error = one_error
    except Exception as exc:
        logger.warning("/clean handler failed: %s", exc, exc_info=True)
        return f"❌ Falha ao executar `/clean`: {exc}"

    elapsed = time.monotonic() - started
    channel_name = str(getattr(channel, "name", "canal") or "canal")
    channel_id = str(getattr(channel, "id", "") or "")
    kind = "thread" if getattr(channel, "parent_id", None) else "canal"
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
    return summary


async def _handle_clean_and_reply(
    raw_args: str,
    *,
    gateway: Any = None,
    source: Any = None,
    interaction: Any = None,
) -> None:
    reply = await _execute_clean(raw_args, gateway=gateway, source=source, interaction=interaction)
    if interaction is not None:
        await _send_clean_followup(interaction, reply)
        return
    _schedule_gateway_reply(gateway, source, reply)


async def handle_clean(raw_args: str) -> str:
    gateway_context = _current_gateway_context()
    return await _execute_clean(
        raw_args,
        gateway=gateway_context.get("gateway"),
        source=gateway_context.get("source"),
        interaction=gateway_context.get("interaction"),
    )


def _schedule_gateway_reply(gateway: Any, source: Any, message: str) -> None:
    text = str(message or "").strip()
    if gateway is None or source is None or not text:
        return
    adapter, chat_id, metadata = _gateway_adapter_for_source(gateway, source)
    if adapter is None or not chat_id:
        return

    async def _send_reply() -> None:
        try:
            await adapter.send(chat_id, text, metadata=metadata)
        except Exception:
            logger.debug("Failed sending governance reply to source=%s", source, exc_info=True)

    try:
        asyncio.get_running_loop().create_task(_send_reply())
    except Exception:
        logger.debug("Could not schedule governance reply for source=%s", source, exc_info=True)


async def _dispatch_normalized_command(gateway: Any, source: Any, message_text: str) -> None:
    try:
        channel_acl = _safe_channel_acl_module()
        handled, reply = await channel_acl.dispatch_normalized_command(source, message_text)
        if handled:
            _schedule_gateway_reply(gateway, source, str(reply or "✅ Comando processado."))
            return
    except Exception:
        logger.debug("Failed dispatching normalized restricted-channel command", exc_info=True)
    command, raw_args = _split_command_text(message_text)
    if command == "scientific-paper-meta-analysis":
        reply = await _run_scientific_pipeline_with_feedback(raw_args, gateway=gateway, source=source)
        if str(reply or "").strip():
            _schedule_gateway_reply(gateway, source, str(reply))
        return
    try:
        fallback = await handle_pre_gateway_message(
            platform="discord",
            source=source,
            message=message_text,
            gateway=gateway,
        )
        if isinstance(fallback, dict) and str(fallback.get("decision") or "").strip().lower() == "handled":
            if not bool(fallback.get("already_replied")):
                _schedule_gateway_reply(gateway, source, str(fallback.get("message") or "✅ Comando processado."))
            return
    except Exception:
        logger.debug("Failed dispatching normalized plugin command", exc_info=True)
    _schedule_gateway_reply(gateway, source, "🚫 Falha ao processar comando normalizado do canal restrito.")


def _resolve_roles_sync(role_acl: Any, interaction: Any) -> list[Dict[str, str]]:
    extract = getattr(role_acl, "_extract_member_roles_from_object", None)
    if callable(extract):
        user = getattr(interaction, "user", None)
        roles = extract(user)
        if roles:
            return roles
        member = getattr(interaction, "member", None)
        roles = extract(member)
        if roles:
            return roles
        guild = getattr(interaction, "guild", None)
        user_id = str(getattr(user, "id", "") or "").strip()
        if guild is not None and user_id.isdigit():
            member = None
            try:
                getter = getattr(guild, "get_member", None)
                if callable(getter):
                    member = getter(int(user_id))
            except Exception:
                member = None
            roles = extract(member)
            if roles:
                return roles

    guild = getattr(interaction, "guild", None)
    resolved: list[Dict[str, str]] = []
    for role in _interaction_roles(interaction):
        role_id, role_name = _fallback_resolve_role_identity(role, guild)
        if role_id or role_name:
            resolved.append({"role_id": role_id, "role_name": role_name})
    return resolved


def _fallback_acl_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _fallback_normalize_role_token(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _runtime_get_value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _runtime_extend_roles_from_value(target: list[Any], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, (str, bytes, int)):
        target.append(value)
        return
    try:
        target.extend(list(value))
    except TypeError:
        target.append(value)


def _fallback_resolve_role_identity(role: Any, guild: Any = None) -> tuple[str, str]:
    role_obj = role
    raw_text = str(role or "").strip()
    if isinstance(role_obj, dict):
        role_id = str(role_obj.get("role_id") or role_obj.get("id") or "").strip()
        role_name = str(role_obj.get("role_name") or role_obj.get("name") or "").strip()
    else:
        role_id = str(getattr(role_obj, "role_id", "") or getattr(role_obj, "id", "") or "").strip()
        role_name = str(getattr(role_obj, "role_name", "") or getattr(role_obj, "name", "") or "").strip()

    if not role_id and raw_text.isdigit():
        role_id = raw_text
    if not role_name and raw_text and not raw_text.isdigit():
        role_name = raw_text

    if role_id.isdigit() and not role_name and guild is not None:
        try:
            getter = getattr(guild, "get_role", None)
            resolved = getter(int(role_id)) if callable(getter) else None
        except Exception:
            resolved = None
        if resolved is not None:
            resolved_id = str(getattr(resolved, "id", "") or "").strip()
            resolved_name = str(getattr(resolved, "name", "") or "").strip()
            if resolved_id:
                role_id = resolved_id
            if resolved_name:
                role_name = resolved_name
    if role_id.isdigit() and not role_name and guild is not None:
        try:
            for candidate in list(getattr(guild, "roles", []) or []):
                if str(getattr(candidate, "id", "") or "").strip() == role_id:
                    role_name = str(getattr(candidate, "name", "") or "").strip()
                    break
        except Exception:
            pass

    return role_id, role_name


def _fallback_build_rank_map(hierarchy: Any) -> dict[str, int]:
    rank_map: dict[str, int] = {}
    if not isinstance(hierarchy, list):
        return rank_map
    for index, row in enumerate(hierarchy):
        if not isinstance(row, dict):
            continue
        for key in ("role_id", "role_name"):
            token = _fallback_normalize_role_token(row.get(key))
            if token and token not in rank_map:
                rank_map[token] = index
    return rank_map


def _fallback_build_role_label_map(hierarchy: Any) -> dict[str, str]:
    labels: dict[str, str] = {}
    if not isinstance(hierarchy, list):
        return labels
    for row in hierarchy:
        if not isinstance(row, dict):
            continue
        label = str(row.get("role_name") or row.get("role_id") or "").strip()
        if not label:
            continue
        for key in ("role_id", "role_name"):
            token = _fallback_normalize_role_token(row.get(key))
            if token and token not in labels:
                labels[token] = label
    return labels


def _fallback_admin_tokens_from_acl(acl: dict[str, Any]) -> set[str]:
    tokens = {"admin"}
    hierarchy = acl.get("hierarchy")
    if not isinstance(hierarchy, list):
        return tokens
    for row in hierarchy:
        if not isinstance(row, dict):
            continue
        role_name = _fallback_normalize_role_token(row.get("role_name"))
        if role_name != "admin":
            continue
        for key in ("role_id", "role_name"):
            token = _fallback_normalize_role_token(row.get(key))
            if token:
                tokens.add(token)
    return tokens


def _interaction_role_holders(interaction: Any) -> list[Any]:
    holders: list[Any] = []
    seen: set[int] = set()

    for candidate in (
        _runtime_get_value(interaction, "member"),
        _runtime_get_value(interaction, "user"),
        _runtime_get_value(interaction, "author"),
        _runtime_get_value(interaction, "data"),
        _runtime_get_value(interaction, "_raw_member"),
    ):
        if candidate is None:
            continue
        marker = id(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        holders.append(candidate)

    for holder in list(holders):
        nested = _runtime_get_value(holder, "member")
        if nested is None:
            continue
        marker = id(nested)
        if marker not in seen:
            seen.add(marker)
            holders.append(nested)

    guild = _runtime_get_value(interaction, "guild")
    user = _runtime_get_value(interaction, "user")
    user_id = str(_runtime_get_value(user, "id", "") or "").strip()
    if guild is not None and user_id.isdigit():
        try:
            getter = getattr(guild, "get_member", None)
            member = getter(int(user_id)) if callable(getter) else None
        except Exception:
            member = None
        if member is not None:
            marker = id(member)
            if marker not in seen:
                seen.add(marker)
                holders.append(member)

    return holders


def _interaction_roles(interaction: Any) -> list[Any]:
    roles: list[Any] = []
    for holder in _interaction_role_holders(interaction):
        _runtime_extend_roles_from_value(roles, _runtime_get_value(holder, "roles"))
        _runtime_extend_roles_from_value(roles, _runtime_get_value(holder, "role_ids"))
    return roles


def _interaction_has_admin_permission(interaction: Any) -> bool:
    return any(_permission_has_flag(perms, 0x8, "administrator") for perms in _interaction_permission_candidates(interaction))


def _fallback_extract_actor_tokens(interaction: Any, acl: dict[str, Any]) -> set[str]:
    tokens = {"@everyone"}
    guild = getattr(interaction, "guild", None)
    for role in _interaction_roles(interaction):
        role_id, role_name = _fallback_resolve_role_identity(role, guild)
        tokens.add(_fallback_normalize_role_token(role_id))
        tokens.add(_fallback_normalize_role_token(role_name))

    user_id = str(getattr(getattr(interaction, "user", None), "id", "") or "").strip()
    overrides = acl.get("user_overrides") if isinstance(acl.get("user_overrides"), dict) else {}
    user_override = overrides.get(user_id) if isinstance(overrides, dict) else None
    if isinstance(user_override, dict):
        for item in user_override.get("roles") or []:
            token = _fallback_normalize_role_token(item)
            if token:
                tokens.add(token)
    return {token for token in tokens if token}


def _interaction_has_literal_admin_role(interaction: Any) -> bool:
    guild = getattr(interaction, "guild", None)
    for role in _interaction_roles(interaction):
        _role_id, role_name = _fallback_resolve_role_identity(role, guild)
        if _fallback_normalize_role_token(role_name) == "admin":
            return True
    return False


def _runtime_acl_normalize_role_token(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("name:"):
        text = text[5:].strip()
    if text == "@everyone":
        return text
    if text.isdigit():
        return text
    return text.lower()


def _runtime_acl_role_label(token: str) -> str:
    clean = _runtime_acl_normalize_role_token(token)
    if not clean:
        return ""
    return clean


def _runtime_acl_hierarchy_entries(acl: dict[str, Any]) -> list[dict[str, Any]]:
    hierarchy = acl.get("hierarchy")
    return list(hierarchy) if isinstance(hierarchy, list) else []


def _runtime_acl_ensure_hierarchy_role(acl: dict[str, Any], requested_role: Any) -> tuple[str, str]:
    token = _runtime_acl_normalize_role_token(requested_role)
    if not token:
        raise ValueError("role inválida; use `role:<hierarquia>`.")

    hierarchy = _runtime_acl_hierarchy_entries(acl)
    for entry in hierarchy:
        role_id = _runtime_acl_normalize_role_token(entry.get("role_id") or "")
        role_name = _runtime_acl_normalize_role_token(entry.get("role_name") or "")
        if token in {role_id, role_name}:
            label = str(entry.get("role_name") or entry.get("role_id") or token).strip() or token
            acl["hierarchy"] = hierarchy
            return token, label

    new_entry = {"role_id": token if token.isdigit() or token == "@everyone" else "", "role_name": "" if token.isdigit() else token}
    everyone_index = next(
        (
            idx
            for idx, entry in enumerate(hierarchy)
            if _runtime_acl_normalize_role_token(entry.get("role_id") or entry.get("role_name") or "") == "@everyone"
        ),
        len(hierarchy),
    )
    hierarchy.insert(everyone_index, new_entry)
    acl["hierarchy"] = hierarchy
    return token, _runtime_acl_role_label(token)


def _write_runtime_acl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _update_command_min_role_without_legacy(path: Path, command_name: Any, requested_role: Any) -> Dict[str, Any]:
    command = _canonical_command_name(command_name)
    if not command:
        raise ValueError("comando inválido; use `command:<nome>`.")

    resolved = Path(path).expanduser().resolve()
    acl = _fallback_acl_payload(resolved)
    if not acl:
        acl = {
            "version": 1,
            "node": str(os.getenv("NODE_NAME", "") or "").strip() or "orchestrator",
            "updated_at": _utc_now(),
            "policy": {"unmapped_command": "deny"},
            "hierarchy": [{"role_id": "@everyone", "role_name": "@everyone"}],
            "commands": {},
            "user_overrides": {},
        }

    role_token, role_label = _runtime_acl_ensure_hierarchy_role(acl, requested_role)
    commands = acl.get("commands") if isinstance(acl.get("commands"), dict) else {}
    command_cfg = dict(commands.get(command) or {})
    previous_min_role = _runtime_acl_normalize_role_token(command_cfg.get("min_role") or "")
    command_cfg["min_role"] = role_token
    commands[command] = command_cfg
    acl["commands"] = {key: commands[key] for key in sorted(commands)}
    acl["updated_at"] = _utc_now()
    _write_runtime_acl(resolved, acl)
    return {
        "ok": True,
        "command": command,
        "min_role": role_token,
        "min_role_label": role_label,
        "previous_min_role": previous_min_role,
        "acl_path": str(resolved),
        "node": str(acl.get("node") or ""),
    }


def _fallback_resolve_actor_rank(actor_tokens: set[str], rank_map: dict[str, int]) -> int | None:
    ranks = [rank_map[token] for token in actor_tokens if token in rank_map]
    return min(ranks) if ranks else None


def _fallback_resolve_top_role_name(actor_tokens: set[str], rank_map: dict[str, int], labels: dict[str, str]) -> str:
    actor_rank = _fallback_resolve_actor_rank(actor_tokens, rank_map)
    if actor_rank is None:
        return "@everyone"
    best_tokens = [token for token in actor_tokens if rank_map.get(token) == actor_rank]
    for token in best_tokens:
        label = str(labels.get(token) or "").strip()
        if label:
            return label
    return "@everyone"


def _authorize_interaction_sync_without_legacy(interaction: Any, command_name: str) -> Dict[str, Any]:
    command = _canonical_command_name(command_name)
    if not command:
        return {"allowed": False, "message": "🚫 ACL: comando inválido.", "command": command}

    acl_path = resolve_acl_path()
    acl = _fallback_acl_payload(acl_path)
    rank_map = _fallback_build_rank_map(acl.get("hierarchy"))
    role_labels = _fallback_build_role_label_map(acl.get("hierarchy"))
    guild = getattr(interaction, "guild", None)
    if guild is None:
        return {
            "allowed": False,
            "message": f"🚫 ACL: `/{command}` exige uso em servidor com papéis (roles).",
            "command": command,
            "acl_path": str(acl_path),
            "required_role": "admin",
        }

    actor_tokens = _fallback_extract_actor_tokens(interaction, acl)
    actor_role_name = _fallback_resolve_top_role_name(actor_tokens, rank_map, role_labels)
    admin_tokens = _fallback_admin_tokens_from_acl(acl)
    if (
        _interaction_has_admin_permission(interaction)
        or _interaction_has_literal_admin_role(interaction)
        or (admin_tokens and (actor_tokens & admin_tokens))
    ):
        return {
            "allowed": True,
            "message": "",
            "command": command,
            "actor_role": "admin" if actor_role_name == "@everyone" else actor_role_name,
            "bypass_governance": True,
            "decision": "admin_bypass",
        }

    commands = acl.get("commands") if isinstance(acl.get("commands"), dict) else {}
    cfg = commands.get(command) if isinstance(commands, dict) else None
    if not isinstance(cfg, dict):
        return {
            "allowed": False,
            "message": _acl_unmapped_command_message(command, acl_path),
            "command": command,
        }

    min_role = _fallback_normalize_role_token(cfg.get("min_role"))
    if not min_role:
        return {
            "allowed": False,
            "message": _acl_missing_min_role_message(command, acl_path),
            "command": command,
        }

    required_label = str(role_labels.get(min_role) or min_role or "").strip()
    required_rank = rank_map.get(min_role)
    actor_rank = _fallback_resolve_actor_rank(actor_tokens, rank_map)
    if required_rank is None:
        return {
            "allowed": False,
            "message": f"🚫 ACL: `/{command}` referencia role inválida (`{required_label}`).",
            "command": command,
        }
    if actor_rank is None:
        return {
            "allowed": False,
            "message": f"🚫 ACL: você não possui role autorizada para `/{command}`. Role mínima: `{required_label}`.",
            "command": command,
        }
    if actor_rank > required_rank:
        return {
            "allowed": False,
            "message": f"🚫 ACL: `/{command}` requer role `{required_label}` ou superior. Sua role atual: `{actor_role_name}`.",
            "command": command,
        }
    return {"allowed": True, "message": "", "command": command, "actor_role": actor_role_name}


def _authorize_interaction_sync(interaction: Any, command_name: str) -> Dict[str, Any]:
    try:
        role_acl = load_role_acl_module()
    except Exception:
        logger.debug("Falling back to builtin interaction ACL runtime", exc_info=True)
        return _authorize_interaction_sync_without_legacy(interaction, command_name)
    command = role_acl.normalize_command_name(command_name)
    if not command:
        return {"allowed": False, "message": "🚫 ACL: comando inválido.", "command": command}

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
            "acl_path": str(acl_path),
            "required_role": "admin",
        }

    actor_tokens = role_acl._tokens_from_roles(_resolve_roles_sync(role_acl, interaction))
    actor_user_id = str(getattr(getattr(interaction, "user", None), "id", "") or "").strip()
    if actor_user_id:
        actor_tokens = role_acl._apply_user_override_tokens(actor_tokens, acl, actor_user_id)
    actor_role_name = role_acl._resolve_top_role_name(actor_tokens, rank_map, role_labels)
    admin_tokens = role_acl._admin_tokens_from_acl(acl)
    if _interaction_has_admin_permission(interaction) or _interaction_has_literal_admin_role(interaction) or (admin_tokens and (actor_tokens & admin_tokens)):
        return {
            "allowed": True,
            "message": "",
            "command": command,
            "actor_role": "admin" if actor_role_name == "@everyone" else actor_role_name,
            "bypass_governance": True,
            "decision": "admin_bypass",
        }

    resolve_cfg = getattr(role_acl, "resolve_command_acl_config", None)
    if callable(resolve_cfg):
        cfg, _implicit_skill_command = resolve_cfg(acl, command)
    else:
        commands = acl.get("commands") if isinstance(acl.get("commands"), dict) else {}
        cfg = commands.get(command)
    if not isinstance(cfg, dict):
        return {
            "allowed": False,
            "message": _acl_unmapped_command_message(command, acl_path),
            "command": command,
        }

    min_role = role_acl.normalize_role_token(cfg.get("min_role") or "")
    if not min_role:
        return {
            "allowed": False,
            "message": _acl_missing_min_role_message(command, acl_path),
            "command": command,
        }

    actor_rank = role_acl._resolve_actor_rank(actor_tokens, rank_map)
    required_rank = role_acl._resolve_required_rank(min_role, rank_map)
    required_label = str(role_labels.get(role_acl.normalize_role_token(min_role)) or role_acl.role_display_name(min_role))
    if required_rank is None:
        return {
            "allowed": False,
            "message": f"🚫 ACL: `/{command}` referencia role inválida (`{role_acl.role_display_name(min_role)}`).",
            "command": command,
        }
    if actor_rank is None:
        return {
            "allowed": False,
            "message": f"🚫 ACL: você não possui role autorizada para `/{command}`. Role mínima: `{required_label}`.",
            "command": command,
        }
    if actor_rank > required_rank:
        return {
            "allowed": False,
            "message": f"🚫 ACL: `/{command}` requer role `{role_acl.role_display_name(min_role)}` ou superior. Sua role atual: `{actor_role_name}`.",
            "command": command,
        }
    return {"allowed": True, "message": "", "command": command}


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
    channel_acl = _safe_channel_acl_module()
    routed = channel_acl.enforce_channel_model(source, {"model": base_model, "runtime": dict(base_runtime or {})})
    blocked = str(routed.get("channel_acl_blocked") or "").strip()
    if blocked:
        return blocked
    addon = str(routed.get("system_prompt_addon") or "").strip()
    if addon:
        existing_prompt = str(getattr(event, "channel_prompt", "") or "").strip()
        event.channel_prompt = "\n\n".join(part for part in (existing_prompt, addon) if part)

    routed_model = str(routed.get("model") or base_model or "").strip()
    routed_runtime = dict(base_runtime or {})
    extra_runtime = routed.get("runtime")
    if isinstance(extra_runtime, dict):
        for key in ("provider", "api_key", "base_url", "api_mode"):
            if extra_runtime.get(key) is not None:
                routed_runtime[key] = extra_runtime.get(key)
    changed = routed_model != str(base_model or "").strip() or any(
        routed_runtime.get(key) != dict(base_runtime or {}).get(key) for key in ("provider", "api_key", "base_url", "api_mode")
    )
    if changed:
        override = {"model": routed_model}
        for key in ("provider", "api_key", "base_url", "api_mode"):
            if routed_runtime.get(key) is not None:
                override[key] = routed_runtime.get(key)
        overrides[session_key] = override
    elif previous_override is not None:
        # Preserve an existing /model selection when channel ACL routing
        # doesn't need to replace it for this turn.
        overrides[session_key] = previous_override
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
        channel_acl = _safe_channel_acl_module()
        routed = channel_acl.enforce_channel_model(source, {"model": route_model, "runtime": dict(base_runtime_dict)})
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
        return routed_model, routed_provider, routing_note
    except Exception:
        logger.debug("Could not resolve governance status route", exc_info=True)
        return route_model, route_provider, routing_note


def _format_status_text(gateway: Any, source: Any) -> str:
    if gateway is None or source is None:
        return "📊 **Hermes Gateway Status**"
    _hydrate_persisted_node_model_override(gateway, source)
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
            tokens_used = (getattr(session_entry, "input_tokens", 0) or 0) + (getattr(session_entry, "output_tokens", 0) or 0)
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


def handle_pre_gateway_dispatch(*, event: Any = None, gateway: Any = None, **_: Any) -> Dict[str, Any] | None:
    source = getattr(event, "source", None)
    if source is None or _platform_value(source) != "discord":
        return None

    _capture_gateway_context(event=event, gateway=gateway)

    command = _canonical_command_name(getattr(event, "get_command", lambda: "")() or "")
    interaction = getattr(event, "raw_message", None)
    if command:
        definition = get_command_definition(command)
        if definition and not is_command_enabled(command):
            _schedule_gateway_reply(gateway, source, _disabled_command_message(command))
            return {"action": "skip", "reason": "command_disabled"}

    role_result: Dict[str, Any] = {}
    bypass_governance = False
    if command and interaction is not None:
        role_result = _authorize_interaction_sync(interaction, command)
        if not bool(role_result.get("allowed")):
            _schedule_gateway_reply(
                gateway,
                source,
                str(role_result.get("message") or f"🚫 ACL: `/{command}` não permitido."),
            )
            return {"action": "skip", "reason": "command_acl_role_block"}
        bypass_governance = bool(role_result.get("bypass_governance"))
        if command == "clean":
            try:
                _command, raw_args = _split_command_text(str(getattr(event, "text", "") or ""))
                asyncio.get_running_loop().create_task(
                    _handle_clean_and_reply(
                        raw_args,
                        gateway=gateway,
                        source=source,
                        interaction=interaction,
                    )
                )
            except Exception:
                logger.debug("Could not schedule /clean dispatch", exc_info=True)
                _schedule_gateway_reply(gateway, source, "❌ Falha ao iniciar `/clean`.")
            return {"action": "skip", "reason": "clean_dispatch"}

    channel_acl = _safe_channel_acl_module()
    message_text = str(getattr(event, "text", "") or "")
    action, payload = channel_acl.normalize_to_channel_skill(source, message_text)
    if action == "BLOCK" and not command:
        audio_override = _maybe_normalize_audio_only_restricted_message(
            channel_acl,
            source,
            event,
            initial_action=action,
        )
        if audio_override is not None:
            action, payload = audio_override
    normalized = str(payload or "")
    rewrite_text = ""

    if action == "BLOCK":
        if bypass_governance and command:
            action = "PASSTHROUGH"
            normalized = message_text
        else:
            _schedule_gateway_reply(gateway, source, normalized)
            return {"action": "skip", "reason": "channel_policy_block"}

    if action in {"SKILL_ADD", "FALTAS_ADD", "COMMAND"}:
        try:
            asyncio.get_running_loop().create_task(_dispatch_normalized_command(gateway, source, normalized))
        except Exception:
            logger.debug("Could not schedule normalized restricted-channel dispatch", exc_info=True)
            if gateway is None and normalized:
                event.text = normalized
                return None
            _schedule_gateway_reply(gateway, source, "🚫 Falha ao processar comando normalizado do canal restrito.")
        return {"action": "skip", "reason": "channel_policy_normalized"}

    if action != "PASSTHROUGH" and normalized and normalized != message_text:
        event.text = normalized
        if not rewrite_text:
            rewrite_text = normalized

    _inherit_parent_channel_model_state(gateway, source)
    _hydrate_persisted_node_model_override(gateway, source)

    if command == "status" and is_command_enabled("status"):
        _ignored_command, raw_status_args = _split_command_text(str(getattr(event, "text", "") or ""))
        status_action = _resolve_status_action(raw_status_args, interaction)
        reply = _definition_help_text("status") if status_action == "help" else _format_status_text(gateway, source)
        _schedule_gateway_reply(gateway, source, reply)
        return {"action": "skip", "reason": "status_override"}

    if command:
        if not bypass_governance:
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
                _schedule_gateway_reply(gateway, source, str(message or f"🚫 O comando `/{command}` não é permitido neste canal."))
                return {"action": "skip", "reason": "command_acl_channel_block"}

    if command == "scientific-paper-meta-analysis" and is_command_enabled("scientific-paper-meta-analysis"):
        try:
            asyncio.get_running_loop().create_task(
                _dispatch_normalized_command(gateway, source, str(getattr(event, "text", "") or ""))
            )
        except Exception:
            logger.debug("Could not schedule scientific skill dispatch from slash command", exc_info=True)
            _schedule_gateway_reply(gateway, source, "❌ Falha ao iniciar a skill científica.")
        return {"action": "skip", "reason": "scientific_skill_dispatch"}

    if command == "model" and is_command_enabled("model"):
        try:
            _ignored_command, raw_model_args = _split_command_text(str(getattr(event, "text", "") or ""))
            asyncio.get_running_loop().create_task(
                _handle_model_and_reply(
                    raw_model_args,
                    gateway=gateway,
                    source=source,
                    interaction=interaction,
                )
            )
        except Exception:
            logger.debug("Could not schedule /model dispatch", exc_info=True)
            _schedule_gateway_reply(gateway, source, "❌ Falha ao iniciar `/model`.")
        return {"action": "skip", "reason": "model_override"}

    blocked_message = _apply_channel_route(gateway, event, source)
    if blocked_message:
        _schedule_gateway_reply(gateway, source, blocked_message)
        return {"action": "skip", "reason": "channel_route_block"}
    if rewrite_text and rewrite_text != message_text:
        return {"action": "rewrite", "text": rewrite_text}
    return None


async def handle_pre_gateway_message(
    *,
    platform: str = "",
    source: Any = None,
    message: str = "",
    gateway: Any = None,
    **_: Any,
) -> Dict[str, Any] | None:
    if str(platform or "").strip().lower() != "discord":
        return None
    command, raw_args = _split_command_text(message)
    if command == "clean":
        gateway_context = _current_gateway_context()
        interaction = gateway_context.get("interaction")
        await _handle_clean_and_reply(
            raw_args,
            gateway=gateway or gateway_context.get("gateway"),
            source=source or gateway_context.get("source"),
            interaction=interaction,
        )
        return {"decision": "handled", "message": "", "already_replied": True}
    if command == "faltas":
        reply = await _execute_faltas(raw_args, source=source)
        return {"decision": "handled", "message": str(reply or "Operação concluída.")}
    if command == "scientific-paper-meta-analysis":
        gateway_context = _current_gateway_context()
        gateway_obj = gateway or gateway_context.get("gateway")
        source_obj = source or gateway_context.get("source")
        if gateway_obj is not None and source_obj is not None and str(raw_args or "").strip().lower() not in {"", "help"}:
            await _dispatch_normalized_command(gateway_obj, source_obj, message)
            return {"decision": "handled", "message": "", "already_replied": True}
        reply = await handle_scientific_paper_meta_analysis(raw_args)
        return {"decision": "handled", "message": str(reply or "Operação concluída.")}
    if command == "model":
        gateway_context = _current_gateway_context()
        reply = await _execute_model(
            raw_args,
            gateway=gateway or gateway_context.get("gateway"),
            source=source or gateway_context.get("source"),
            interaction=gateway_context.get("interaction"),
        )
        return {"decision": "handled", "message": str(reply or "Operação concluída.")}
    return None


def register_plugin(ctx) -> None:
    _log_registration_status()
    _schedule_startup_reconcile()
    _sync_persisted_node_model_to_config()
    ctx.register_command(
        "metricas",
        handle_metricas,
        description=_definition_description("metricas", "Show Colmeio metrics dashboard"),
        args_hint="[dias:N formato:text|json|csv skill:nome|action:help]",
    )
    ctx.register_command(
        "faltas",
        handle_faltas,
        description=_definition_description("faltas", "Gerenciar lista de faltas"),
        args_hint="action:listar|adicionar|remover|limpar|help [loja:loja1|loja2|ambas] [itens:\"...\"] [formato:links|excel|texto] [confirm:sim]",
    )
    ctx.register_command(
        "acl",
        handle_acl,
        description=_definition_description("acl", "Manage Discord command and channel ACL policy"),
        args_hint="command ... | channel ... | help",
    )
    ctx.register_command(
        "clean",
        handle_clean,
        description=_definition_description("clean", "Clean all deletable messages in the current Discord channel"),
        args_hint="confirm:true",
    )
    ctx.register_command(
        "scientific-paper-meta-analysis",
        handle_scientific_paper_meta_analysis,
        description=_definition_description(
            "scientific-paper-meta-analysis",
            "Run the scientific paper meta-analysis workflow",
        ),
        args_hint="[query:\"tema\"|help]",
    )
    ctx.register_command(
        "slash",
        handle_slash,
        description=_definition_description("slash", "List and toggle plugin-owned Discord slash commands"),
        args_hint="[command:nome enable:true|false]",
    )
    ctx.register_hook("pre_gateway_dispatch", handle_pre_gateway_dispatch)
