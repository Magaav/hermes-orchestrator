from __future__ import annotations

import asyncio
import inspect
import importlib.util
import json
import logging
import os
import re
import shlex
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import yaml

logger = logging.getLogger(__name__)
_CUSTOM_HANDLER_CACHE: Dict[str, Any] = {}
_LOCAL_PREFIX = "/local/"
_WORKSPACE_PREFIX = "/local/workspace/"
_WORKSPACE_LEGACY_PREFIX = "/local/workspace/colmeio/"


def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


_HERMES_HOME = _resolve_hermes_home()


def _resolve_python_bin() -> str:
    candidates = (
        "/local/hermes-agent/.venv/bin/python",
        "/local/hermes-agent/.venv/bin/python3",
        "/usr/bin/python3",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return shutil.which("python3") or shutil.which("python") or "python3"


def _path_variants(raw_path: Any) -> list[Path]:
    text = str(raw_path or "").strip()
    if not text:
        return []

    out: list[Path] = []

    def _append(path: Path) -> None:
        if path not in out:
            out.append(path)

    base = Path(text)
    _append(base)

    if text.startswith(_WORKSPACE_LEGACY_PREFIX):
        suffix = text[len(_WORKSPACE_LEGACY_PREFIX) :]
        _append(Path(_WORKSPACE_PREFIX + suffix))
        _append(Path(_LOCAL_PREFIX + suffix))
    elif text.startswith(_WORKSPACE_PREFIX):
        suffix = text[len(_WORKSPACE_PREFIX) :]
        _append(Path(_LOCAL_PREFIX + suffix))
        _append(Path(_WORKSPACE_LEGACY_PREFIX + suffix))
    elif text.startswith(_LOCAL_PREFIX):
        suffix = text[len(_LOCAL_PREFIX) :]
        _append(Path(_WORKSPACE_PREFIX + suffix))
        _append(Path(_WORKSPACE_LEGACY_PREFIX + suffix))
    elif not base.is_absolute():
        _append(Path("/local") / text)
        _append(Path("/local/workspace") / text)
        _append(Path("/local/workspace/colmeio") / text)

    return out


def _resolve_existing_path(configured: Any, *fallbacks: Any) -> tuple[Path, list[Path]]:
    attempts: list[Path] = []

    for raw in (configured, *fallbacks):
        for candidate in _path_variants(raw):
            if candidate not in attempts:
                attempts.append(candidate)
            if candidate.exists():
                return candidate, attempts

    if attempts:
        return attempts[0], attempts
    return Path(str(configured or "")), attempts


def _format_path_attempts(attempts: list[Path], limit: int = 6) -> str:
    if not attempts:
        return "- `(nenhum caminho candidato)`"
    shown = attempts[:limit]
    lines = [f"- `{path}`" for path in shown]
    if len(attempts) > limit:
        lines.append(f"- `... +{len(attempts) - limit} caminhos`")
    return "\n".join(lines)


def interaction_data_to_dict(interaction: Any) -> Dict[str, Any]:
    raw = getattr(interaction, "data", None)
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    if hasattr(raw, "name") or hasattr(raw, "options") or hasattr(raw, "type"):
        out_attr: Dict[str, Any] = {}
        for key in ("name", "options", "type"):
            val = getattr(raw, key, None)
            if val is not None:
                out_attr[key] = val
        if out_attr:
            return out_attr
    try:
        return dict(raw)
    except Exception:
        out: Dict[str, Any] = {}
        for key in ("name", "options", "type"):
            try:
                out[key] = raw[key]  # type: ignore[index]
            except Exception:
                pass
        return out


def unknown_slash_name_from_error(error: Exception) -> str:
    try:
        text = str(error or "")
    except Exception:
        text = ""
    if not text:
        return ""
    match = re.search(r"Application command '([^']+)' not found", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return str(match.group(1) or "").strip().lower()


def unknown_slash_option_values(options: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    if not isinstance(options, list):
        return values

    for opt in options:
        if not isinstance(opt, dict):
            continue
        name = str(opt.get("name") or "").strip().lower()
        if not name:
            continue

        try:
            otype = int(opt.get("type") or 0)
        except Exception:
            otype = 0

        if otype in (1, 2):
            nested = unknown_slash_option_values(opt.get("options") or [])
            if nested:
                values.update(nested)
            continue

        if "value" not in opt:
            continue

        values[name] = opt.get("value")

    return values


def flatten_unknown_slash_options(options: Any) -> list[str]:
    tokens: list[str] = []
    if not isinstance(options, list):
        return tokens

    for opt in options:
        if not isinstance(opt, dict):
            continue
        name = str(opt.get("name") or "").strip()
        if not name:
            continue

        try:
            otype = int(opt.get("type") or 0)
        except Exception:
            otype = 0

        if otype in (1, 2):
            tokens.append(name)
            tokens.extend(flatten_unknown_slash_options(opt.get("options") or []))
            continue

        if "value" not in opt:
            continue

        val = opt.get("value")
        if val is None:
            continue

        flag = "--" + name.replace("_", "-")
        sval = str(val)
        tokens.append(flag)
        tokens.append(shlex.quote(sval))

    return tokens


def truncate_text(text: str, limit: int = 1900) -> str:
    clean = str(text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)] + "..."


async def send_ephemeral(interaction: Any, content: str) -> None:
    msg = truncate_text(content)
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


async def safe_edit_or_followup(interaction: Any, content: str) -> None:
    msg = truncate_text(content)
    try:
        await interaction.edit_original_response(content=msg)
    except Exception:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


def _load_channel_acl_module() -> Any:
    hook_path = _HERMES_HOME / "hooks" / "channel_acl" / "handler.py"
    if not hook_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("colmeio_channel_acl_runtime", hook_path)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _resolve_interaction_channel_ids(adapter: Any, interaction: Any) -> tuple[str, Optional[str], Optional[str]]:
    channel_id = str(getattr(interaction, "channel_id", "") or "")

    parent_id: Optional[str] = None
    thread_id: Optional[str] = None

    try:
        import discord  # type: ignore
        is_thread = isinstance(getattr(interaction, "channel", None), discord.Thread)
    except Exception:
        is_thread = False

    if is_thread:
        thread_id = channel_id or None
        try:
            parent_getter = getattr(adapter, "_get_parent_channel_id", None)
            if callable(parent_getter):
                parent_id = parent_getter(interaction.channel)
            else:
                parent_id = str(getattr(interaction.channel, "parent_id", "") or "") or None
        except Exception:
            parent_id = None

    routing_channel_id = str(parent_id or channel_id or "")
    return routing_channel_id, thread_id, parent_id


def check_command_acl(adapter: Any, interaction: Any, command_name: str) -> tuple[bool, str]:
    cmd = str(command_name or "").strip().lower().lstrip("/")
    if not cmd:
        return True, ""

    checker = getattr(adapter, "_check_colmeio_acl_slash", None)
    if callable(checker):
        try:
            allowed, message = checker(interaction, cmd)
            return bool(allowed), str(message or "")
        except Exception as exc:
            logger.debug("Adapter ACL checker failed for /%s: %s", cmd, exc)

    try:
        mod = _load_channel_acl_module()
        if mod is None:
            return True, ""
        fn = getattr(mod, "check_command_allowed", None)
        if not callable(fn):
            return True, ""
        channel_id, thread_id, parent_id = _resolve_interaction_channel_ids(adapter, interaction)
        allowed, message = fn(channel_id, cmd, thread_id=thread_id, parent_id=parent_id)
        return bool(allowed), str(message or "")
    except Exception as exc:
        logger.debug("Fallback ACL checker failed for /%s: %s", cmd, exc)
        return True, ""


async def dispatch_slash_to_gateway(
    adapter: Any,
    interaction: Any,
    target: str,
    options: Any,
    *,
    followup_message: Optional[str] = None,
    cleanup: bool = True,
) -> bool:
    command_target = str(target or "").strip().lstrip("/")
    if not command_target:
        return False

    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        tokens = flatten_unknown_slash_options(options)
        command_text = f"/{command_target}"
        if tokens:
            command_text = f"{command_text} {' '.join(tokens)}"

        event = adapter._build_slash_event(interaction, command_text)
        await adapter.handle_message(event)

        if followup_message:
            await safe_edit_or_followup(interaction, followup_message)
        elif cleanup:
            try:
                await interaction.delete_original_response()
            except Exception:
                pass
        return True
    except Exception as exc:
        logger.warning("Slash dispatch bridge failed for /%s: %s", command_target, exc, exc_info=True)
        try:
            await safe_edit_or_followup(interaction, f"❌ Falha ao executar `/{command_target}`: {exc}")
        except Exception:
            pass
        return True


async def run_metrics_dashboard(
    interaction: Any,
    command_name: str,
    option_values: Dict[str, Any],
    settings: Optional[Dict[str, Any]] = None,
) -> tuple[str, bool]:
    cfg = settings or {}
    script, script_attempts = _resolve_existing_path(
        cfg.get("script_path"),
        str(_HERMES_HOME / "skills" / "custom" / "colmeio" / "colmeio-metrics" / "scripts" / "metrics_logger.py"),
        "/local/.hermes/skills/custom/colmeio/colmeio-metrics/scripts/metrics_logger.py",
        "/local/workspace/skills/custom/colmeio/colmeio-metrics/scripts/metrics_logger.py",
    )
    timeout_sec = int(cfg.get("timeout_sec") or 45)

    if not script.exists():
        return (
            "❌ Script de métricas não encontrado.\n"
            f"tentativas:\n{_format_path_attempts(script_attempts)}",
            True,
        )

    raw_fmt = str(option_values.get("formato") or "text").strip().lower()
    fmt = {"texto": "text", "text": "text", "json": "json", "csv": "csv"}.get(raw_fmt, "text")

    raw_days = option_values.get("dias", 30)
    try:
        days = int(raw_days)
    except Exception:
        days = 30
    days = max(1, min(365, days))

    skill_name = str(option_values.get("skill") or "").strip()

    actor = getattr(interaction, "user", None)
    actor_user_id = str(getattr(actor, "id", "") or "")
    actor_user_name = str(
        getattr(actor, "display_name", "") or getattr(actor, "name", "") or ""
    )

    python_bin = _resolve_python_bin()
    cmd = [
        python_bin,
        str(script),
        "dashboard",
        "--days",
        str(days),
        "--format",
        fmt,
        "--actor-user-id",
        actor_user_id,
        "--actor-user-name",
        actor_user_name,
    ]
    if skill_name:
        cmd.extend(["--skill-name", skill_name])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        return (f"❌ Timeout ao executar `/{command_name}` ({timeout_sec}s).", True)
    except Exception as exc:
        return (f"❌ Falha ao iniciar `/{command_name}`: {exc}", True)

    out_text = (stdout or b"").decode(errors="ignore").strip()
    err_text = (stderr or b"").decode(errors="ignore").strip()

    if proc.returncode != 0:
        detail = err_text or out_text or "erro desconhecido."
        return (
            truncate_text(f"❌ Falha ao executar `/{command_name}`: {detail}"),
            True,
        )

    payload = None
    try:
        payload = json.loads(out_text) if out_text else None
    except Exception:
        payload = None

    if isinstance(payload, dict):
        if payload.get("ok") is False:
            detail = str(payload.get("error") or "erro desconhecido.")
            return (truncate_text(f"❌ {detail}"), True)

        if fmt == "json":
            body = json.dumps(payload, ensure_ascii=False, indent=2)
            return (truncate_text(f"```json\n{body}\n```"), False)

        if fmt == "csv":
            csv_body = str(payload.get("csv") or "").strip()
            if csv_body:
                return (truncate_text(f"```csv\n{csv_body}\n```"), False)
            return ("✅ Dashboard CSV gerado (sem linhas).", False)

        text_body = str(payload.get("text") or "").strip()
        if text_body:
            return (truncate_text(text_body), False)
        return ("✅ Dashboard de métricas executado.", False)

    if out_text:
        return (truncate_text(out_text), False)

    return ("✅ Dashboard de métricas executado.", False)


async def handle_metricas(
    adapter: Any,
    interaction: Any,
    option_values: Dict[str, Any],
    settings: Optional[Dict[str, Any]] = None,
    *,
    command_name: str = "metricas",
) -> bool:
    cfg = settings or {}
    acl_command = str(cfg.get("acl_command") or command_name)
    allowed, acl_msg = check_command_acl(adapter, interaction, acl_command)
    if not allowed:
        msg = acl_msg or f"🚫 O comando `/{command_name}` não é permitido neste canal."
        try:
            await send_ephemeral(interaction, msg)
        except Exception:
            pass
        return True

    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        text, _is_error = await run_metrics_dashboard(
            interaction,
            command_name=command_name,
            option_values=option_values,
            settings=cfg,
        )
        if text:
            await safe_edit_or_followup(interaction, text)
        return True
    except Exception as exc:
        logger.warning("Metrics handler failed for /%s: %s", command_name, exc, exc_info=True)
        try:
            await safe_edit_or_followup(interaction, f"❌ Falha ao executar `/{command_name}`: {exc}")
        except Exception:
            pass
        return True


async def handle_restart(adapter: Any, interaction: Any, settings: Optional[Dict[str, Any]] = None) -> bool:
    cfg = settings or {}
    restart_cmd_env = str(cfg.get("restart_cmd_env") or "COLMEIO_DISCORD_RESTART_CMD")
    restart_delay_env = str(cfg.get("restart_delay_env") or "COLMEIO_DISCORD_RESTART_DELAY_SEC")
    default_restart_cmd = str(cfg.get("default_restart_cmd") or "sudo hermes gateway restart --system")
    default_delay = str(cfg.get("default_delay_sec") or "0.1")
    ack_message = str(
        cfg.get("ack_message")
        or "✅ Reinício solicitado. O gateway será reiniciado em alguns segundos."
    )
    log_path = str(cfg.get("log_path") or "/tmp/hermes-discord-restart.log")

    restart_cmd = os.getenv(restart_cmd_env, "").strip() or default_restart_cmd
    restart_delay = os.getenv(restart_delay_env, "").strip() or default_delay

    try:
        if interaction.response.is_done():
            await interaction.followup.send(ack_message, ephemeral=True)
        else:
            await interaction.response.send_message(ack_message, ephemeral=True)
    except Exception as exc:
        logger.debug("Discord restart ack failed: %s", exc)

    detached = (
        "nohup bash -lc "
        + shlex.quote(f"sleep {restart_delay}; {restart_cmd}")
        + f" >{shlex.quote(log_path)} 2>&1 &"
    )

    try:
        proc = await asyncio.create_subprocess_shell(
            detached,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            err = ((stderr or stdout) or b"unknown scheduling error").decode(errors="ignore").strip()
            try:
                await interaction.followup.send(f"❌ Não consegui agendar o restart: {err}", ephemeral=True)
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Failed to schedule gateway restart from Discord slash: %s", exc)
        try:
            await interaction.followup.send(f"❌ Falha ao agendar restart: {exc}", ephemeral=True)
        except Exception:
            pass
    return True


def _format_reboot_ack(cfg: Dict[str, Any]) -> str:
    base = str(
        cfg.get("ack_message")
        or (
            "✅ Reboot solicitado. O container será reiniciado em alguns segundos.\n"
            "Ao voltar, o prestart reaplica os patches/configurações."
        )
    ).strip()
    raw_steps = cfg.get("reapplies")
    if not isinstance(raw_steps, list):
        return base
    steps = [str(item or "").strip() for item in raw_steps if str(item or "").strip()]
    if not steps:
        return base
    joined = "\n".join(f"- {item}" for item in steps[:8])
    return f"{base}\n\nReaplica no boot:\n{joined}"


async def handle_reboot(adapter: Any, interaction: Any, settings: Optional[Dict[str, Any]] = None) -> bool:
    cfg = settings or {}
    reboot_cmd_env = str(cfg.get("reboot_cmd_env") or "COLMEIO_DISCORD_REBOOT_CMD")
    reboot_delay_env = str(cfg.get("reboot_delay_env") or "COLMEIO_DISCORD_REBOOT_DELAY_SEC")
    default_reboot_cmd = str(cfg.get("default_reboot_cmd") or "kill -TERM 1")
    default_delay = str(cfg.get("default_delay_sec") or "0.2")
    ack_message = _format_reboot_ack(cfg)
    log_path = str(cfg.get("log_path") or "/tmp/hermes-discord-reboot.log")

    reboot_cmd = os.getenv(reboot_cmd_env, "").strip() or default_reboot_cmd
    reboot_delay = os.getenv(reboot_delay_env, "").strip() or default_delay

    try:
        if interaction.response.is_done():
            await interaction.followup.send(ack_message, ephemeral=True)
        else:
            await interaction.response.send_message(ack_message, ephemeral=True)
    except Exception as exc:
        logger.debug("Discord reboot ack failed: %s", exc)

    detached = (
        "nohup bash -lc "
        + shlex.quote(f"sleep {reboot_delay}; {reboot_cmd}")
        + f" >{shlex.quote(log_path)} 2>&1 &"
    )

    try:
        proc = await asyncio.create_subprocess_shell(
            detached,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            err = ((stderr or stdout) or b"unknown scheduling error").decode(errors="ignore").strip()
            try:
                await interaction.followup.send(f"❌ Não consegui agendar o reboot: {err}", ephemeral=True)
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Failed to schedule container reboot from Discord slash: %s", exc)
        try:
            await interaction.followup.send(f"❌ Falha ao agendar reboot: {exc}", ephemeral=True)
        except Exception:
            pass
    return True


async def handle_backup_version(
    adapter: Any,
    interaction: Any,
    version: str,
    node: str = "all",
    settings: Optional[Dict[str, Any]] = None,
) -> bool:
    cfg = settings or {}
    acl_command = str(cfg.get("acl_command") or "backup")
    allowed, acl_msg = check_command_acl(adapter, interaction, acl_command)
    if not allowed:
        msg = acl_msg or "🚫 O comando `/backup` não é permitido neste canal."
        try:
            await send_ephemeral(interaction, msg)
        except Exception:
            pass
        return True

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    raw_choices = cfg.get("node_choices")
    allowed_nodes: set[str] = set()
    if isinstance(raw_choices, list):
        for entry in raw_choices:
            if isinstance(entry, dict):
                value = str(entry.get("value") or "").strip().lower()
            else:
                value = str(entry or "").strip().lower()
            if value:
                allowed_nodes.add(value)
    if not allowed_nodes:
        allowed_nodes = {"orchestrator", "all"}

    default_node = str(cfg.get("default_node") or "all").strip().lower() or "all"
    raw_target = str(node or "").strip().lower() or default_node
    if raw_target not in allowed_nodes:
        options = ", ".join(f"`{name}`" for name in sorted(allowed_nodes))
        await safe_edit_or_followup(
            interaction,
            f"❌ Node inválido: `{raw_target}`. Opções permitidas: {options}",
        )
        return True
    backup_target = raw_target

    raw_version = str(version or "").strip()
    if not raw_version:
        await safe_edit_or_followup(
            interaction,
            "❌ Informe `version` (obrigatório). Exemplo: `/backup version:2.0 node:all`.",
        )
        return True

    safe_version = "".join(
        ch if (ch.isalnum() or ch in "._-") else "-"
        for ch in raw_version
    ).strip("-.")
    if not safe_version:
        await safe_edit_or_followup(
            interaction,
            "❌ Versão inválida. Use apenas letras, números, `.`, `_` ou `-`.",
        )
        return True
    if safe_version.lower().startswith("v"):
        safe_version = safe_version[1:] or safe_version

    clone_manager_script, clone_attempts = _resolve_existing_path(
        cfg.get("clone_manager_script"),
        "/local/scripts/clone/clone_manager.py",
        "/local/workspace/scripts/clone/clone_manager.py",
    )
    drive_script, drive_attempts = _resolve_existing_path(
        cfg.get("drive_script"),
        "/local/cron/scripts/backup/drive_backup.py",
        "/local/agents/private/crons/colmeio/scripts/backup/drive_backup.py",
        "/local/agents/private/crons/catatau/scripts/backup/drive_backup.py",
        "/local/cron/colmeio/scripts/backup/drive_backup.py",
        "/local/cron/catatau/scripts/backup/drive_backup.py",
        "/local/crons/colmeio/scripts/backup/drive_backup.py",
        "/local/crons/catatau/scripts/backup/drive_backup.py",
        "/local/workspace/crons/scripts/backup/drive_backup.py",
    )
    local_backup_root = Path(str(cfg.get("local_backup_root") or "/local/backups"))
    drive_folder_path = str(cfg.get("drive_folder_path") or "backups/orchestrator")
    timeout_backup_sec = int(cfg.get("timeout_backup_sec") or 1800)
    timeout_drive_sec = int(cfg.get("timeout_drive_sec") or 3600)

    if not clone_manager_script.exists():
        await safe_edit_or_followup(
            interaction,
            "❌ Script do clone manager não encontrado.\n"
            f"tentativas:\n{_format_path_attempts(clone_attempts)}",
        )
        return True
    if not drive_script.exists():
        await safe_edit_or_followup(
            interaction,
            "❌ Script de upload para Drive não encontrado.\n"
            f"tentativas:\n{_format_path_attempts(drive_attempts)}",
        )
        return True

    try:
        local_backup_root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        await safe_edit_or_followup(interaction, f"❌ Não foi possível criar diretórios de backup: {exc}")
        return True

    python_bin = _resolve_python_bin()

    backup_cmd = [python_bin, str(clone_manager_script), "backup"]
    if backup_target == "all":
        backup_cmd.append("--all")
    else:
        backup_cmd.extend(["--name", backup_target])

    try:
        backup_proc = await asyncio.create_subprocess_exec(
            *backup_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        backup_out, backup_err = await asyncio.wait_for(
            backup_proc.communicate(),
            timeout=timeout_backup_sec,
        )
    except asyncio.TimeoutError:
        await safe_edit_or_followup(interaction, "❌ Timeout ao executar backup pelo clone manager.")
        return True

    backup_detail = ((backup_out or backup_err) or b"").decode(errors="ignore").strip()
    backup_payload: Dict[str, Any] = {}
    if backup_detail:
        try:
            parsed = json.loads(backup_detail)
            if isinstance(parsed, dict):
                backup_payload = parsed
        except Exception:
            backup_payload = {}

    if backup_proc.returncode != 0:
        detail = str(backup_payload.get("error") or backup_detail or "unknown error")
        detail = detail[-1500:] if len(detail) > 1500 else detail
        await safe_edit_or_followup(interaction, f"❌ Falha ao criar backup local: {detail}")
        return True

    if not backup_payload.get("ok", True):
        detail = str(backup_payload.get("error") or backup_detail or "unknown error")
        detail = detail[-1500:] if len(detail) > 1500 else detail
        await safe_edit_or_followup(interaction, f"❌ Falha ao criar backup local: {detail}")
        return True

    archive_path = str(backup_payload.get("archive") or "").strip()
    if not archive_path:
        await safe_edit_or_followup(
            interaction,
            f"❌ Backup concluído, mas clone manager não retornou o caminho do arquivo.\noutput: `{backup_detail[:500]}`",
        )
        return True

    archive_local = Path(archive_path)
    if not archive_local.is_absolute():
        archive_local = local_backup_root / archive_local.name
    if not archive_local.exists():
        await safe_edit_or_followup(
            interaction,
            f"❌ Backup local reportado, mas arquivo não encontrado em disco: `{archive_local}`",
        )
        return True

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    remote_name = f"orchestrator-{backup_target}-v{safe_version}-{timestamp}.tar.gz"
    target_local_archive = local_backup_root / remote_name

    try:
        if archive_local.resolve(strict=False) != target_local_archive.resolve(strict=False):
            if target_local_archive.exists():
                target_local_archive.unlink()
            archive_local.rename(target_local_archive)
            archive_local = target_local_archive
    except Exception as exc:
        await safe_edit_or_followup(
            interaction,
            (
                "❌ Backup local criado, mas falhou ao padronizar nome do arquivo.\n"
                f"origem: `{archive_local}`\n"
                f"destino: `{target_local_archive}`\n"
                f"erro: {exc}"
            ),
        )
        return True

    ensure_cmd = [
        python_bin,
        str(drive_script),
        "ensure-path",
        drive_folder_path,
    ]
    try:
        ensure_proc = await asyncio.create_subprocess_exec(
            *ensure_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        ensure_out, ensure_err = await asyncio.wait_for(ensure_proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        await safe_edit_or_followup(
            interaction,
            "❌ Backup local criado, mas timeout ao resolver pasta no Google Drive.",
        )
        return True

    ensure_text = ((ensure_out or ensure_err) or b"").decode(errors="ignore").strip()
    if ensure_proc.returncode != 0:
        detail = ensure_text[-1500:] if len(ensure_text) > 1500 else ensure_text
        await safe_edit_or_followup(
            interaction,
            f"❌ Backup local criado, mas falhou ao resolver pasta no Google Drive: {detail}",
        )
        return True

    folder_match = re.search(r"Folder ID:\s*([A-Za-z0-9_-]+)", ensure_text)
    if not folder_match:
        await safe_edit_or_followup(
            interaction,
            (
                "❌ Backup local criado, mas não consegui obter o Folder ID da pasta "
                f"`{drive_folder_path}` no Google Drive.\n"
                f"Resposta: `{ensure_text[:500]}`"
            ),
        )
        return True
    folder_id = folder_match.group(1)

    async def upload_drive_file(local_file: Path, remote_file_name: str, timeout_sec: int = 1800) -> tuple[bool, str, str, str]:
        cmd = [
            python_bin,
            str(drive_script),
            "upload",
            str(local_file),
            folder_id,
            "--name",
            remote_file_name,
        ]
        proc_u = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        u_out, u_err = await asyncio.wait_for(proc_u.communicate(), timeout=timeout_sec)
        raw = ((u_out or u_err) or b"").decode(errors="ignore").strip()
        if proc_u.returncode != 0:
            return False, "", "", raw
        file_id = ""
        web_link = ""
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                file_id = str(payload.get("id") or "")
                web_link = str(payload.get("webViewLink") or "")
        except Exception:
            pass
        return True, file_id, web_link, raw

    try:
        up_ok, drive_file_id, drive_link, up_detail = await upload_drive_file(
            archive_local,
            remote_name,
            timeout_sec=timeout_drive_sec,
        )
    except asyncio.TimeoutError:
        await safe_edit_or_followup(
            interaction,
            "❌ Backup local criado, mas timeout no upload para Google Drive.",
        )
        return True

    if not up_ok:
        detail = up_detail[-1500:] if len(up_detail) > 1500 else up_detail
        await safe_edit_or_followup(
            interaction,
            (
                "❌ Backup local criado, mas falhou upload para Google Drive.\n"
                f"archive: `{archive_local}`\n"
                f"path: `{drive_folder_path}/{remote_name}`\n"
                f"erro: {detail}"
            ),
        )
        return True

    # Drive validation fallback: if upload output could not be parsed for file id,
    # query folder listing and verify the expected filename exists there.
    if not drive_file_id:
        try:
            list_cmd = [
                python_bin,
                str(drive_script),
                "list",
                folder_id,
            ]
            list_proc = await asyncio.create_subprocess_exec(
                *list_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            list_out, list_err = await asyncio.wait_for(list_proc.communicate(), timeout=180)
            if list_proc.returncode == 0:
                raw = (list_out or b"").decode(errors="ignore").strip()
                payload = json.loads(raw) if raw else []
                names = {
                    str(item.get("name") or "").strip()
                    for item in payload
                    if isinstance(item, dict)
                }
                if remote_name not in names:
                    await safe_edit_or_followup(
                        interaction,
                        (
                            "❌ Upload retornou sem `file_id` e o arquivo não foi confirmado na pasta do Drive.\n"
                            f"archive: `{archive_local}`\n"
                            f"path: `{drive_folder_path}/{remote_name}`"
                        ),
                    )
                    return True
            else:
                detail = ((list_err or list_out) or b"").decode(errors="ignore").strip()
                detail = detail[-1000:] if len(detail) > 1000 else detail
                await safe_edit_or_followup(
                    interaction,
                    (
                        "❌ Upload retornou sem `file_id` e não foi possível validar no Drive.\n"
                        f"archive: `{archive_local}`\n"
                        f"path: `{drive_folder_path}/{remote_name}`\n"
                        f"list_error: {detail}"
                    ),
                )
                return True
        except Exception as exc:
            await safe_edit_or_followup(
                interaction,
                (
                    "❌ Upload retornou sem `file_id` e falhou validação no Drive.\n"
                    f"archive: `{archive_local}`\n"
                    f"path: `{drive_folder_path}/{remote_name}`\n"
                    f"error: {exc}"
                ),
            )
            return True

    size_bytes = archive_local.stat().st_size if archive_local.exists() else 0
    size_mb = size_bytes / (1024 * 1024) if size_bytes else 0.0
    nodes = backup_payload.get("nodes")
    if isinstance(nodes, list) and nodes:
        node_label = ", ".join(str(item) for item in nodes if str(item or "").strip())
    else:
        node_label = backup_target

    await safe_edit_or_followup(
        interaction,
        (
            "✅ Backup criado com sucesso.\n"
            f"target: `{backup_target}`\n"
            f"nodes: `{node_label}`\n"
            f"version: `{safe_version}`\n"
            f"archive: `{archive_local}`\n"
            f"mirror: `/{drive_folder_path}/{remote_name}` (Google Drive)\n"
            f"drive_folder_id: `{folder_id}`\n"
            f"drive_file_id: `{drive_file_id or 'n/a'}`\n"
            f"drive_link: {drive_link or 'n/a'}\n"
            f"size: `{size_mb:.2f} MB`"
        ),
    )
    return True


def _normalize_model_choices(settings: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    cfg = settings or {}
    raw = cfg.get("choices")
    if not isinstance(raw, list):
        raw = []

    out: Dict[str, Dict[str, str]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        provider = str(item.get("provider") or "").strip()
        model = str(item.get("model") or "").strip()
        usage_left = str(item.get("usage_left") or "").strip()
        if not key or not label or not provider or not model:
            continue
        out[key] = {
            "key": key,
            "label": label,
            "provider": provider,
            "model": model,
            "usage_left": usage_left,
        }
    return out


def _canonical_model_choice_token(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    # Accept legacy typo variants and user-entered labels.
    text = text.replace("openia", "openai")
    return re.sub(r"[^a-z0-9:/]+", "", text)


def _find_model_choice(
    model_input: str,
    choices_map: Dict[str, Dict[str, str]],
) -> Optional[Dict[str, str]]:
    selected_key = str(model_input or "").strip()
    if not selected_key:
        return None

    selected = choices_map.get(selected_key)
    if selected:
        return selected

    lowered = selected_key.lower()
    canonical = _canonical_model_choice_token(selected_key)
    for entry in choices_map.values():
        candidates = (
            str(entry.get("key") or ""),
            str(entry.get("label") or ""),
            str(entry.get("model") or ""),
            f"{entry.get('provider', '')}:{entry.get('model', '')}",
        )
        for candidate in candidates:
            if not candidate:
                continue
            if lowered == candidate.lower():
                return entry
            if canonical and canonical == _canonical_model_choice_token(candidate):
                return entry

    return None


def _extract_bridge_model_key(option_values: Dict[str, Any]) -> str:
    for key in ("modelo", "model", "name", "key"):
        raw = option_values.get(key)
        text = str(raw or "").strip()
        if text:
            return text

    if len(option_values) == 1:
        only_value = next(iter(option_values.values()))
        text = str(only_value or "").strip()
        if text:
            return text

    return ""


def _extract_usage_hint(payload: Any, depth: int = 0) -> Optional[str]:
    if depth > 5:
        return None

    usage_keys = (
        "remaining_tokens",
        "tokens_remaining",
        "usage_left",
        "remaining",
        "quota_remaining",
        "credits_remaining",
    )

    if isinstance(payload, dict):
        for key in usage_keys:
            val = payload.get(key)
            if val not in (None, "", [], {}):
                return str(val)
        for val in payload.values():
            found = _extract_usage_hint(val, depth + 1)
            if found:
                return found
        return None

    if isinstance(payload, list):
        for item in payload:
            found = _extract_usage_hint(item, depth + 1)
            if found:
                return found
        return None

    return None


def _resolve_usage_left(provider: str, selected: Dict[str, str], settings: Optional[Dict[str, Any]]) -> str:
    direct = str(selected.get("usage_left") or "").strip()
    if direct:
        return direct

    default_label = str((settings or {}).get("usage_left_default") or "unlimited").strip() or "unlimited"
    auth_path = _HERMES_HOME / "auth.json"
    if not auth_path.exists():
        return default_label

    try:
        auth_data = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception:
        return default_label

    providers = auth_data.get("providers") if isinstance(auth_data, dict) else None
    if not isinstance(providers, dict):
        return default_label

    provider_candidates = [provider]
    if provider == "kimi":
        provider_candidates.append("kimi-coding")
    if provider == "openai":
        provider_candidates.append("openai-codex")

    for prov in provider_candidates:
        blob = providers.get(prov)
        if blob is None:
            continue
        hint = _extract_usage_hint(blob)
        if hint:
            return hint

    return default_label


def _load_gateway_config() -> tuple[Path, Dict[str, Any]]:
    cfg_path = _HERMES_HOME / "config.yaml"
    if not cfg_path.exists():
        return cfg_path, {}
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            return cfg_path, raw
    except Exception:
        pass
    return cfg_path, {}


def _atomic_write_gateway_config(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    serialized = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    tmp.write_text(serialized, encoding="utf-8")
    tmp.replace(path)


def _evict_gateway_cache_after_model_switch(adapter: Any, interaction: Any) -> None:
    runner = getattr(adapter, "gateway_runner", None)
    if runner is None:
        return

    try:
        event = adapter._build_slash_event(interaction, "/status")
    except Exception:
        event = None

    source = getattr(event, "source", None) if event is not None else None
    session_key = None
    try:
        key_fn = getattr(runner, "_session_key_for_source", None)
        if callable(key_fn) and source is not None:
            session_key = key_fn(source)
    except Exception:
        session_key = None

    try:
        evict = getattr(runner, "_evict_cached_agent", None)
        if callable(evict) and session_key:
            evict(session_key)
    except Exception:
        pass

    if hasattr(runner, "_effective_model"):
        setattr(runner, "_effective_model", None)
    if hasattr(runner, "_effective_provider"):
        setattr(runner, "_effective_provider", None)


async def handle_model_switch(
    adapter: Any,
    interaction: Any,
    model_key: str = "",
    settings: Optional[Dict[str, Any]] = None,
) -> bool:
    cfg = settings or {}
    acl_command = str(cfg.get("acl_command") or "model")
    allowed, acl_msg = check_command_acl(adapter, interaction, acl_command)
    if not allowed:
        msg = acl_msg or "🚫 O comando `/model` não é permitido neste canal."
        try:
            await send_ephemeral(interaction, msg)
        except Exception:
            pass
        return True

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    choices_map = _normalize_model_choices(cfg)
    config_path, config = _load_gateway_config()

    model_cfg = config.get("model")
    if not isinstance(model_cfg, dict):
        model_cfg = {}
    current_model = str(model_cfg.get("default") or model_cfg.get("model") or "?")
    current_provider = str(model_cfg.get("provider") or "?")

    selected_key = str(model_key or "").strip()
    if not selected_key:
        if choices_map:
            option_lines = [
                f"- `{entry['key']}`: {entry['label']} → `{entry['provider']}` / `{entry['model']}`"
                for entry in choices_map.values()
            ]
            listing = "\n".join(option_lines)
        else:
            listing = "- (sem opções configuradas)"

        await safe_edit_or_followup(
            interaction,
            (
                "🤖 **Modelo padrão atual**\n"
                f"model: `{current_model}`\n"
                f"provider: `{current_provider}`\n\n"
                "**Opções disponíveis**\n"
                f"{listing}"
            ),
        )
        return True

    selected = _find_model_choice(selected_key, choices_map)
    if not selected:
        await safe_edit_or_followup(
            interaction,
            (
                f"❌ Opção de modelo inválida: `{selected_key}`.\n"
                "Use `/model` e selecione um item da lista."
            ),
        )
        return True

    if "model" not in config or not isinstance(config.get("model"), dict):
        config["model"] = {}
    cfg_model = config["model"]
    cfg_model["provider"] = selected["provider"]
    cfg_model["default"] = selected["model"]
    cfg_model.pop("api_key", None)
    cfg_model.pop("base_url", None)
    cfg_model.pop("model", None)

    try:
        _atomic_write_gateway_config(config_path, config)
    except Exception as exc:
        await safe_edit_or_followup(interaction, f"❌ Falha ao salvar `config.yaml`: {exc}")
        return True

    _evict_gateway_cache_after_model_switch(adapter, interaction)

    usage_left = _resolve_usage_left(selected["provider"], selected, cfg)
    await safe_edit_or_followup(
        interaction,
        (
            "✅ Modelo padrão atualizado.\n"
            f"selected: `{selected['label']}`\n"
            f"model: `{selected['model']}`\n"
            f"provider: `{selected['provider']}`\n"
            f"usage_left: `{usage_left}`"
        ),
    )
    return True


async def run_bridge_handler(
    name: str,
    adapter: Any,
    interaction: Any,
    *,
    command_name: str,
    option_values: Dict[str, Any],
    command_config: Optional[Dict[str, Any]] = None,
) -> bool:
    handler = str(name or "").strip().lower()
    cfg = command_config or {}

    if handler in ("metrics", "metrics_dashboard", "metricas"):
        return await handle_metricas(
            adapter,
            interaction,
            option_values,
            settings=cfg,
            command_name=command_name,
        )

    if handler in ("model", "model_switch", "model-switch"):
        model_key = _extract_bridge_model_key(option_values)
        return await handle_model_switch(
            adapter,
            interaction,
            model_key=model_key,
            settings=cfg,
        )

    custom_fn = _resolve_custom_handler(handler)
    if custom_fn is not None:
        try:
            result = custom_fn(
                adapter=adapter,
                interaction=interaction,
                command_name=command_name,
                option_values=option_values,
                command_config=cfg,
            )
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except Exception as exc:
            logger.warning("Custom handler `%s` failed: %s", handler, exc, exc_info=True)
            await send_ephemeral(interaction, f"❌ Falha no handler customizado `{handler}`: {exc}")
            return True

    await send_ephemeral(interaction, f"❌ Handler desconhecido: `{handler}`")
    return True


def _resolve_custom_handler(handler_name: str):
    handler = str(handler_name or "").strip()
    if not handler.startswith("custom:"):
        return None

    key = handler.lower()
    if key in _CUSTOM_HANDLER_CACHE:
        return _CUSTOM_HANDLER_CACHE[key]

    custom_id = handler.split(":", 1)[1].strip()
    if not custom_id:
        return None

    # Keep IDs deterministic and filesystem-safe.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", custom_id):
        return None

    base = Path(__file__).resolve().parent / "custom_handlers"
    path = base / f"{custom_id}.py"
    if not path.exists():
        return None

    mod_name = f"colmeio_discord_custom_handler_{custom_id.lower()}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if not spec or not spec.loader:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fn = getattr(module, "handle", None)
    if not callable(fn):
        return None

    _CUSTOM_HANDLER_CACHE[key] = fn
    return fn
