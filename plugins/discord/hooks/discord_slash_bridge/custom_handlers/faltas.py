from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Tuple

_CLEAR_CONFIRM_TTL_S = 90.0
_PENDING_CLEAR: Dict[Tuple[str, str], float] = {}


def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


def _resolve_python_bin() -> str:
    candidates = (
        "/local/hermes-agent/.venv/bin/python",
        "/local/hermes-agent/.venv/bin/python3",
        "/usr/bin/python3",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return sys.executable or "python3"


def _resolve_pipeline_script(config: Dict[str, Any]) -> Path:
    import sys
    print(f"[FALTAS_DEBUG _resolve_pipeline_script] START pid={os.getpid()} HERMES_HOME={os.environ.get('HERMES_HOME','unset')}", file=sys.stderr, flush=True)
    hermes_home = _resolve_hermes_home()
    print(f"[FALTAS_DEBUG _resolve_pipeline_script] hermes_home={hermes_home}", file=sys.stderr, flush=True)
    configured = str(config.get("pipeline_script") or "").strip()
    print(f"[FALTAS_DEBUG _resolve_pipeline_script] configured={repr(configured)}", file=sys.stderr, flush=True)
    candidates = [
        configured,
        str(
            hermes_home
            / "skills"
            / "custom"
            / "colmeio"
            / "colmeio-lista-de-faltas"
            / "scripts"
            / "faltas_pipeline.py"
        ),
        "/local/.hermes/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py",
        "/local/workspace/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py",
        "/local/agents/nodes/colmeio/.hermes/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py",
        "/opt/data/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py",
    ]
    for i, raw in enumerate(candidates):
        path = Path(str(raw).strip()) if raw else Path("")
        exists = path.exists() if raw else False
        is_file = path.is_file() if exists else False
        print(f"[FALTAS_DEBUG candidate[{i}]={repr(raw)}] path={path} exists={exists} is_file={is_file}", file=sys.stderr, flush=True)
        if raw and exists and is_file:
            print(f"[FALTAS_DEBUG] ==> RETURNING: {path}", file=sys.stderr, flush=True)
            return path
    fallback = Path(candidates[1])
    print(f"[FALTAS_DEBUG] ALL CANDIDATES FAILED, FALLBACK: {fallback}", file=sys.stderr, flush=True)
    return fallback


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


def _interaction_data_to_dict(interaction: Any) -> Dict[str, Any]:
    raw = getattr(interaction, "data", None)
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    try:
        return dict(raw)
    except Exception:
        return {}


def _leaf_values(options: Any) -> Dict[str, Any]:
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
            nested = _leaf_values(opt.get("options") or [])
            if nested:
                values.update(nested)
            continue

        if "value" in opt:
            values[name] = opt.get("value")
    return values


def _extract_action_and_values(interaction: Any, option_values: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    values = dict(option_values or {})
    action = str(values.get("action") or "").strip().lower()

    data = _interaction_data_to_dict(interaction)
    options = data.get("options") if isinstance(data, dict) else None

    if isinstance(options, list):
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
                if not action:
                    action = name
                nested = _leaf_values(opt.get("options") or [])
                if nested:
                    values.update(nested)
                continue

            if "value" in opt and name not in values:
                values[name] = opt.get("value")

    return action, values


def _normalize_action(raw: str) -> str:
    key = str(raw or "").strip().lower()
    mapping = {
        "list": "listar",
        "listar": "listar",
        "sync": "listar",
        "sincronizar": "listar",
        "adicionar": "adicionar",
        "add": "adicionar",
        "remover": "remover",
        "remove": "remover",
        "rm": "remover",
        "limpar": "limpar",
        "clear": "limpar",
        "help": "help",
        "ajuda": "help",
    }
    return mapping.get(key, key)


def _normalize_store(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    mapping = {
        "loja1": "loja1",
        "l1": "loja1",
        "1": "loja1",
        "loja2": "loja2",
        "l2": "loja2",
        "2": "loja2",
        "ambas": "ambas",
        "todas": "ambas",
    }
    return mapping.get(key, "")


def _normalize_format(raw: Any) -> str:
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


def _normalize_items(raw: Any) -> str:
    text = str(raw or "").strip()
    return re.sub(r"\s+", " ", text)


def _clear_key(interaction: Any) -> Tuple[str, str]:
    uid = str(getattr(getattr(interaction, "user", None), "id", "") or "")
    cid = str(getattr(interaction, "channel_id", "") or "")
    return uid, cid


def _confirm_clear(interaction: Any, values: Dict[str, Any]) -> bool:
    now = time.time()
    uid, cid = _clear_key(interaction)
    if not uid or not cid:
        return False

    raw = str(values.get("confirm") or "").strip().lower()
    if raw in {"1", "true", "yes", "sim", "s"}:
        _PENDING_CLEAR.pop((uid, cid), None)
        return True

    ts = _PENDING_CLEAR.get((uid, cid), 0.0)
    if ts and (now - ts) <= _CLEAR_CONFIRM_TTL_S:
        _PENDING_CLEAR.pop((uid, cid), None)
        return True

    _PENDING_CLEAR[(uid, cid)] = now
    return False


def _build_pipeline_command(
    interaction: Any,
    action: str,
    values: Dict[str, Any],
    script_path: Path,
    parent_channel_id: str = "",
) -> tuple[list[str], str]:
    normalized = _normalize_action(action)
    loja = _normalize_store(values.get("loja"))
    itens = _normalize_items(values.get("itens"))
    py = _resolve_python_bin()

    if normalized == "help":
        return [], (
            "Uso do `/faltas`:\n"
            "- `/faltas action:listar loja:loja1 formato:links`\n"
            "- `/faltas action:adicionar itens:\"produto\" loja:loja2`\n"
            "- `/faltas action:remover itens:\"produto\" loja:loja1`\n"
            "- `/faltas action:limpar` (repita uma 2a vez em até 90s para confirmar)"
        )

    action_map = {
        "listar": "list",
        "adicionar": "add",
        "remover": "remove",
        "limpar": "clear",
    }
    pipeline_action = action_map.get(normalized)
    if not pipeline_action:
        return [], (
            "❌ Ação inválida para `/faltas`.\n"
            "Use uma destas ações: `listar`, `adicionar`, `remover`, `limpar`, `help`."
        )

    cmd = [py, str(script_path), pipeline_action, "--trigger-mode", "slash_command"]
    if loja:
        cmd.extend(["--loja", loja])

    channel_id = str(getattr(interaction, "channel_id", "") or "").strip()
    if channel_id:
        cmd.extend(["--channel-id", channel_id, "--origin-channel-id", channel_id])

    if parent_channel_id:
        cmd.extend(["--chat-id-alt", parent_channel_id])

    user = getattr(interaction, "user", None)
    uid = str(getattr(user, "id", "") or "").strip()
    uname = str(getattr(user, "display_name", "") or getattr(user, "name", "") or "").strip()
    if uid:
        cmd.extend(["--author-id", uid])
    if uname:
        cmd.extend(["--author-name", uname])

    if pipeline_action in {"add", "remove"}:
        if not itens:
            return [], f"❌ Informe `itens` para a ação `{normalized}`."
        cmd.extend(["--itens", itens])

    if pipeline_action == "clear":
        if not _confirm_clear(interaction, values):
            return [], (
                "⚠️ Confirmação obrigatória para limpar.\n"
                "Repita `/faltas action:limpar` em até 90s para confirmar."
            )
        cmd.extend(["--confirm", "sim"])

    return cmd, ""


def _truncate(text: str, limit: int = 1900) -> str:
    clean = str(text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)] + "..."


def _render_list_response(payload: Dict[str, Any], output_format: str) -> str:
    data = payload.get("data") if isinstance(payload, dict) else {}
    stores = data.get("stores") if isinstance(data, dict) else {}
    if not isinstance(stores, dict) or not stores:
        return "✅ Lista consultada (sem dados)."

    if output_format in {"links", "excel"}:
        lines = ["📋 Faltas — links por loja"]
        for store in ("loja1", "loja2"):
            summary = stores.get(store) if isinstance(stores.get(store), dict) else {}
            if not summary:
                continue
            url = str(summary.get("sheet_url") or "").strip()
            total = int(summary.get("total_items") or 0)
            if url:
                lines.append(f"- {store}: {url} (itens: {total})")
            else:
                lines.append(f"- {store}: (sem link configurado) (itens: {total})")
        return "\n".join(lines)

    lines = ["📋 Faltas — resumo texto"]
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
                lines.append(f"  • {item} ({qty})")
    return "\n".join(lines)


def _render_mutation_response(payload: Dict[str, Any], normalized_action: str) -> str:
    data = payload.get("data") if isinstance(payload, dict) else {}
    stores = data.get("stores") if isinstance(data, dict) else {}
    if not isinstance(stores, dict):
        stores = {}

    title = {
        "adicionar": "✅ Itens adicionados",
        "remover": "✅ Itens removidos",
        "limpar": "✅ Listas limpas",
    }.get(normalized_action, "✅ Operação concluída")

    lines = [title]
    for store, row in stores.items():
        if not isinstance(row, dict):
            continue
        if normalized_action == "adicionar":
            added = row.get("added") if isinstance(row.get("added"), list) else []
            incremented = row.get("incremented") if isinstance(row.get("incremented"), list) else []
            lines.append(f"- {store}: novos={len(added)} atualizados={len(incremented)}")
        elif normalized_action == "remover":
            removed = row.get("removed") if isinstance(row.get("removed"), list) else []
            not_found = row.get("not_found") if isinstance(row.get("not_found"), list) else []
            lines.append(f"- {store}: removidos={len(removed)} não_encontrados={len(not_found)}")
    if len(lines) == 1:
        lines.append("- sem alterações reportadas")
    return "\n".join(lines)


def _render_response(payload: Dict[str, Any], normalized_action: str, output_format: str) -> str:
    if payload.get("confirmation_required"):
        msg = str(payload.get("data", {}).get("message") or payload.get("message") or "").strip()
        return msg or "⚠️ Confirmação obrigatória."

    if normalized_action == "listar":
        return _render_list_response(payload, output_format)

    if normalized_action in {"adicionar", "remover", "limpar"}:
        return _render_mutation_response(payload, normalized_action)

    data = payload.get("data")
    if isinstance(data, dict):
        return _truncate("```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```")
    return "✅ Operação concluída."


async def handle(
    *,
    adapter: Any,
    interaction: Any,
    command_name: str,
    option_values: Dict[str, Any],
    command_config: Dict[str, Any],
) -> bool:
    del command_name  # Unused.

    action, values = _extract_action_and_values(interaction, option_values)
    normalized_action = _normalize_action(action)
    output_format = _normalize_format(values.get("formato"))

    import sys
    script_path = _resolve_pipeline_script(command_config)
    print(f"[FALTAS_DEBUG _handle_faltas_command] script_path={script_path} exists={script_path.exists()} is_file={script_path.is_file() if script_path.exists() else 'N/A'} cwd={os.getcwd()} HERMES_HOME={os.environ.get('HERMES_HOME','unset')}", file=sys.stderr, flush=True)
    if not script_path.exists():
        await _send_ephemeral(
            interaction,
            f"❌ Script do pipeline de faltas não encontrado: `{script_path}`",
        )
        return True

    parent_id = ""
    try:
        getter = getattr(adapter, "_get_parent_channel_id", None)
        if callable(getter):
            parent_id = str(getter(getattr(interaction, "channel", None)) or "").strip()
    except Exception:
        parent_id = ""

    cmd, err = _build_pipeline_command(
        interaction,
        action,
        values,
        script_path,
        parent_channel_id=parent_id,
    )
    print(f"[FALTAS_DEBUG _handle_faltas_command] cmd={cmd!r} err={err!r}", file=sys.stderr, flush=True)
    if err:
        await _send_ephemeral(interaction, err)
        return True

    timeout_sec = int(command_config.get("timeout_sec") or 180)
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        import traceback
        print(f"[FALTAS_DEBUG PRE-SUBPROC] cmd={cmd!r}", file=sys.stderr, flush=True)
        print(f"[FALTAS_DEBUG PRE-SUBPROC] script_path={script_path!r} type={type(script_path).__name__}", file=sys.stderr, flush=True)
        print(f"[FALTAS_DEBUG PRE-SUBPROC] str(script_path)={str(script_path)!r}", file=sys.stderr, flush=True)
        print(f"[FALTAS_DEBUG PRE-SUBPROC] cwd={os.getcwd()!r}", file=sys.stderr, flush=True)
        print(f"[FALTAS_DEBUG PRE-SUBPROC] trace={traceback.format_stack()[-4:]}", file=sys.stderr, flush=True)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        await _edit_or_followup(interaction, f"❌ Timeout ao executar `/faltas` ({timeout_sec}s).")
        return True
    except Exception as exc:
        await _edit_or_followup(interaction, f"❌ Falha ao iniciar `/faltas`: {exc}")
        return True

    out_text = (stdout or b"").decode(errors="ignore").strip()
    err_text = (stderr or b"").decode(errors="ignore").strip()

    payload: Dict[str, Any] = {}
    try:
        payload = json.loads(out_text) if out_text else {}
    except Exception:
        payload = {}

    if proc.returncode != 0:
        if isinstance(payload, dict) and payload.get("confirmation_required"):
            msg = _render_response(payload, normalized_action, output_format)
            await _edit_or_followup(interaction, _truncate(msg))
            return True
        detail = str(payload.get("error") or err_text or out_text or "erro desconhecido.").strip()
        await _edit_or_followup(interaction, _truncate(f"❌ Falha no `/faltas`: {detail}"))
        return True

    if not isinstance(payload, dict):
        msg = out_text or "✅ Operação concluída."
        await _edit_or_followup(interaction, _truncate(msg))
        return True

    rendered = _render_response(payload, normalized_action, output_format)
    await _edit_or_followup(interaction, _truncate(rendered))
    return True
