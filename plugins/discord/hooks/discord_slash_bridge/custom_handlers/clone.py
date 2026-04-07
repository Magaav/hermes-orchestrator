from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Tuple


SCRIPT_CANDIDATES = (
    Path("/local/scripts/clone/clone_manager.py"),
    Path("/local/scripts/clone_manager.py"),
    Path("/local/workspace/discord/scripts/hermes_clone_manager.py"),
    Path("/local/workspace/colmeio/discord/scripts/hermes_clone_manager.py"),
)
_py_override = str(__import__("os").getenv("HERMES_CLONE_PYTHON_BIN", "") or "").strip()
if _py_override:
    PYTHON_BIN = Path(_py_override).expanduser()
elif Path("/local/.venv/bin/python3").exists():
    PYTHON_BIN = Path("/local/.venv/bin/python3")
elif Path("/local/hermes-agent/.venv/bin/python3").exists():
    PYTHON_BIN = Path("/local/hermes-agent/.venv/bin/python3")
else:
    PYTHON_BIN = Path("/usr/bin/python3")

ACTION_MAP = {
    "spawn": "start",
    "start": "start",
    "status": "status",
    "stop": "stop",
    "delete": "delete",
    "logs": "logs",
}


def _truncate(text: str, limit: int = 1900) -> str:
    clean = str(text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)] + "..."


async def _send_ephemeral(interaction: Any, content: str) -> None:
    msg = _truncate(content)
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


async def _edit_or_followup(interaction: Any, content: str) -> None:
    msg = _truncate(content)
    try:
        await interaction.edit_original_response(content=msg)
    except Exception:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


def _extract_action_and_name(interaction: Any, option_values: Dict[str, Any]) -> Tuple[str, str]:
    raw_action = str(option_values.get("action") or "").strip().lower()
    raw_name = str(option_values.get("name") or "").strip().lower()

    # Future-proofing for subcommand payloads, if clone becomes /clone <subcommand>.
    data = getattr(interaction, "data", None)
    if isinstance(data, dict):
        options = data.get("options")
        if isinstance(options, list):
            for item in options:
                if not isinstance(item, dict):
                    continue
                item_type = int(item.get("type") or 0)
                if item_type in (1, 2):  # subcommand / subcommand group
                    sub_name = str(item.get("name") or "").strip().lower()
                    if sub_name and not raw_action:
                        raw_action = sub_name
                    nested = item.get("options")
                    if isinstance(nested, list):
                        for opt in nested:
                            if not isinstance(opt, dict):
                                continue
                            if str(opt.get("name") or "").strip().lower() == "name":
                                raw_name = str(opt.get("value") or "").strip().lower()
                    break

    action = ACTION_MAP.get(raw_action or "spawn", "start")
    return action, raw_name


def _build_message(action: str, payload: Dict[str, Any]) -> str:
    if action == "start":
        result = str(payload.get("result") or "started")
        prefix = "✅ Clone started." if result == "started" else "ℹ️ Clone already running."
        state = payload.get("container_state") or {}
        camofox = payload.get("camofox") if isinstance(payload.get("camofox"), dict) else {}
        openviking = payload.get("openviking") if isinstance(payload.get("openviking"), dict) else {}
        models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
        restart_sync = payload.get("restart_reboot_sync") if isinstance(payload.get("restart_reboot_sync"), dict) else {}
        camofox_line = ""
        if camofox:
            camofox_line = (
                f"\ncamofox_enabled: `{str(bool(camofox.get('enabled'))).lower()}`"
                f"\ncamofox_url: `{camofox.get('effective_url', '')}`"
            )
        openviking_line = ""
        if openviking:
            effective = openviking.get("effective")
            endpoint = ""
            if isinstance(effective, dict):
                endpoint = str(effective.get("endpoint", "") or "")
            openviking_line = (
                f"\nopenviking_enabled: `{str(bool(openviking.get('enabled'))).lower()}`"
                f"\nopenviking_endpoint: `{endpoint}`"
                f"\nopenviking_degraded: `{str(bool(openviking.get('degraded'))).lower()}`"
            )
        model_line = ""
        if models:
            effective = models.get("effective")
            default_model = {}
            fallback_model = {}
            if isinstance(effective, dict):
                if isinstance(effective.get("default"), dict):
                    default_model = effective.get("default", {})
                if isinstance(effective.get("fallback"), dict):
                    fallback_model = effective.get("fallback", {})
            model_line = (
                f"\ndefault_model: `{default_model.get('model', '')}`"
                f"\ndefault_provider: `{default_model.get('provider', '')}`"
            )
            if fallback_model.get("model") or fallback_model.get("provider"):
                model_line += (
                    f"\nfallback_model: `{fallback_model.get('model', '')}`"
                    f"\nfallback_provider: `{fallback_model.get('provider', '')}`"
                )
        restart_line = ""
        if restart_sync:
            restart_line = (
                f"\nrestart_cmd: `{restart_sync.get('restart_cmd', '')}`"
                f"\nreboot_cmd: `{restart_sync.get('reboot_cmd', '')}`"
            )
        return (
            f"{prefix}\n"
            f"clone: `{payload.get('clone_name', '?')}`\n"
            f"container: `{payload.get('container_name', '?')}`\n"
            f"state_mode: `{payload.get('state_mode', '?')}`\n"
            f"status: `{state.get('status', '?')}`\n"
            f"log_file: `{payload.get('log_file', '?')}`"
            f"{camofox_line}"
            f"{openviking_line}"
            f"{model_line}"
            f"{restart_line}"
        )

    if action == "status":
        state = payload.get("container_state") or {}
        return (
            "ℹ️ Clone status.\n"
            f"clone: `{payload.get('clone_name', '?')}`\n"
            f"container: `{payload.get('container_name', '?')}`\n"
            f"env_exists: `{str(payload.get('env_exists')).lower()}`\n"
            f"clone_root_exists: `{str(payload.get('clone_root_exists')).lower()}`\n"
            f"state_mode: `{payload.get('state_mode', '?')}`\n"
            f"camofox_enabled: `{str(payload.get('camofox_enabled')).lower()}`\n"
            f"camofox_url: `{payload.get('camofox_url', '')}`\n"
            f"openviking_enabled: `{str(payload.get('openviking_enabled')).lower()}`\n"
            f"openviking_endpoint: `{payload.get('openviking_endpoint', '')}`\n"
            f"openviking_user: `{payload.get('openviking_user', '')}`\n"
            f"openviking_supported: `{str(payload.get('openviking_supported')).lower()}`\n"
            f"default_model_env: `{payload.get('default_model_env', '')}`\n"
            f"default_provider_env: `{payload.get('default_model_provider_env', '')}`\n"
            f"fallback_model_env: `{payload.get('fallback_model_env', '')}`\n"
            f"fallback_provider_env: `{payload.get('fallback_model_provider_env', '')}`\n"
            f"restart_cmd: `{payload.get('discord_restart_cmd', '')}`\n"
            f"reboot_cmd: `{payload.get('discord_reboot_cmd', '')}`\n"
            f"status: `{state.get('status', '?')}`\n"
            f"running: `{str(state.get('running')).lower()}`\n"
            f"log_file: `{payload.get('log_file', '?')}`"
        )

    if action == "stop":
        state = payload.get("container_state") or {}
        return (
            "🛑 Clone stop requested.\n"
            f"clone: `{payload.get('clone_name', '?')}`\n"
            f"container: `{payload.get('container_name', '?')}`\n"
            f"status: `{state.get('status', payload.get('result', '?'))}`"
        )

    if action == "delete":
        return (
            "🧹 Clone container deleted.\n"
            f"clone: `{payload.get('clone_name', '?')}`\n"
            f"container: `{payload.get('container_name', '?')}`\n"
            f"data_preserved: `{str(payload.get('data_preserved')).lower()}`\n"
            f"clone_root: `{payload.get('clone_root', '?')}`"
        )

    if action == "logs":
        log_text = str(payload.get("log_text") or "").strip()
        if not log_text:
            return (
                "📄 No logs found yet.\n"
                f"clone: `{payload.get('clone_name', '?')}`\n"
                f"log_file: `{payload.get('log_file', '?')}`"
            )
        clipped = _truncate(log_text, limit=1600)
        return (
            "📄 Clone logs (tail).\n"
            f"clone: `{payload.get('clone_name', '?')}`\n"
            f"log_file: `{payload.get('log_file', '?')}`\n"
            f"```text\n{clipped}\n```"
        )

    return f"ℹ️ Action `{action}` completed."


def _resolve_clone_manager_script() -> Path:
    for candidate in SCRIPT_CANDIDATES:
        if candidate.exists():
            return candidate
    return SCRIPT_CANDIDATES[0]


async def handle(
    *,
    adapter: Any,
    interaction: Any,
    command_name: str,
    option_values: Dict[str, Any],
    command_config: Dict[str, Any],
) -> bool:
    del adapter, command_name  # Unused currently.

    script_path = _resolve_clone_manager_script()
    if not script_path.exists():
        attempted = "\n".join(f"- `{path}`" for path in SCRIPT_CANDIDATES)
        await _send_ephemeral(
            interaction,
            "❌ Clone manager script not found.\n"
            f"tentativas:\n{attempted}",
        )
        return True

    action, clone_name = _extract_action_and_name(interaction, option_values)
    if not clone_name:
        await _send_ephemeral(
            interaction,
            "❌ Missing clone name. Use `/clone name:<clone_name>`.",
        )
        return True

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    cmd = [str(PYTHON_BIN), str(script_path), action, "--name", clone_name]
    if action == "logs":
        cmd.extend(["--lines", "120"])

    image_override = str(command_config.get("docker_image") or "").strip()
    if image_override:
        cmd.extend(["--image", image_override])

    timeout_sec = {
        "start": 600,
        "status": 45,
        "stop": 120,
        "delete": 120,
        "logs": 60,
    }.get(action, 120)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        await _edit_or_followup(
            interaction,
            f"❌ Timeout while executing clone action `{action}`.",
        )
        return True
    except Exception as exc:
        await _edit_or_followup(
            interaction,
            f"❌ Failed to execute clone action `{action}`: {exc}",
        )
        return True

    out = (stdout or b"").decode(errors="ignore").strip()
    err = (stderr or b"").decode(errors="ignore").strip()

    payload: Dict[str, Any] = {}
    if out:
        try:
            loaded = json.loads(out)
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {}

    if proc.returncode != 0 or payload.get("ok") is False:
        detail = str(payload.get("error") or err or out or "unknown clone error")
        await _edit_or_followup(
            interaction,
            _truncate(f"❌ Clone action `{action}` failed: {detail}"),
        )
        return True

    await _edit_or_followup(interaction, _build_message(action, payload))
    return True
