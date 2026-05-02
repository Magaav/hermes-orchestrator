"""
Plugin-local Discord channel ACL helper for the canonical slash runtime.

Resolution order for config:
1. ``HERMES_DISCORD_PRIVATE_DIR/channel_acl.yaml`` when set
2. ``HERMES_DISCORD_SLASH_CACHE_ROOT/governance/channel_acl.yaml`` when set
3. Bundled ``config.yaml`` next to this file
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

import yaml

_HOOK_DIR = Path(__file__).resolve().parent
_BUNDLED_CONFIG_PATH = _HOOK_DIR / "config.yaml"
_cache: Dict[str, Dict[str, Any]] = {}
_cache_path: Optional[Path] = None

_DEFAULT_ALWAYS_ALLOWED_COMMANDS = {"status"}
_GREETING_PREFIXES = (
    "oi",
    "ola",
    "olá",
    "hello",
    "hey",
    "eai",
    "fala",
    "bom dia",
    "boa tarde",
    "boa noite",
    "tudo bem",
    "como vai",
)
_QUESTION_STARTERS = {
    "como",
    "qual",
    "quais",
    "quando",
    "porque",
    "por",
    "onde",
    "quem",
    "pode",
    "voces",
    "você",
    "voce",
}
_VOICE_TRANSCRIPT_PATTERN = re.compile(
    r"\[The user sent (?:a )?(?:voice|audio) message\s*~?\s*Here(?:'|’)s what they said:\s*\"([^\"]+)\"\]",
    flags=re.IGNORECASE,
)
_EMPTY_TEXT_SENTINEL = "(The user sent a message with no text content)"
_TRAILING_STT_PUNCT_RE = re.compile(r"[ \t\r\n.,!?;:]+$")
_LEADING_SENDER_PREFIX_RE = re.compile(
    r"^\s*\[(?!the user sent\b)[^\]\n]{1,120}\]\s*",
    flags=re.IGNORECASE,
)
_GENERIC_EMPTY_TEXT_SENTINEL_RE = re.compile(
    r"\(\s*the user sent a message with no text content\s*\)",
    flags=re.IGNORECASE,
)
_VOICE_ITEM_PREFIX_RE = re.compile(
    r"^(?:"
    r"adiciona(?:r)?|"
    r"anota(?:r)?|"
    r"coloca(?:r)?|"
    r"inclui(?:r)?|"
    r"incluir|"
    r"bota(?:r)?|"
    r"compra(?:r)?|"
    r"precisa(?: de)?|"
    r"t[aá] faltando|"
    r"faltou|"
    r"tem que comprar|"
    r"tem que pegar|"
    r"manda(?:r)?"
    r")\b[\s,:;-]*",
    flags=re.IGNORECASE,
)


def clear_cache() -> None:
    global _cache, _cache_path
    _cache = {}
    _cache_path = None


def _runtime_governance_config_path() -> Optional[Path]:
    configured_root = str(os.getenv("HERMES_DISCORD_PRIVATE_DIR", "") or "").strip()
    if configured_root:
        return Path(configured_root).expanduser() / "channel_acl.yaml"
    configured_cache = str(os.getenv("HERMES_DISCORD_SLASH_CACHE_ROOT", "") or "").strip()
    if configured_cache:
        return Path(configured_cache).expanduser() / "governance" / "channel_acl.yaml"
    return None


def _config_path() -> Path:
    runtime_path = _runtime_governance_config_path()
    if runtime_path and runtime_path.exists():
        return runtime_path
    return _BUNDLED_CONFIG_PATH


def _normalize_command_set(raw_values: Any) -> Set[str]:
    if not isinstance(raw_values, (list, tuple, set)):
        return set()
    out = set()
    for value in raw_values:
        cmd = str(value or "").strip().lower().lstrip("/")
        if cmd:
            out.add(cmd)
    return out


def _always_allowed_commands(cfg: Dict[str, Any]) -> Set[str]:
    configured = _normalize_command_set(cfg.get("always_allowed_commands"))
    return configured or set(_DEFAULT_ALWAYS_ALLOWED_COMMANDS)


def _strip_discord_mentions(text: str) -> str:
    cleaned = re.sub(r"<@!?\d+>", " ", text or "")
    cleaned = re.sub(r"(?<!\w)@[\w.\-À-ÿ_]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _strip_leading_sender_prefix(text: str) -> str:
    return _LEADING_SENDER_PREFIX_RE.sub("", str(text or "")).strip()


def _normalize_candidate_item(text: str) -> str:
    item = _strip_leading_sender_prefix(text)
    item = _strip_discord_mentions(item)
    item = item.strip().strip("\"'`")
    item = re.sub(r"\s+", " ", item).strip()
    item = _TRAILING_STT_PUNCT_RE.sub("", item).strip()
    return item


def _normalize_store(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    return {
        "loja1": "loja1",
        "l1": "loja1",
        "1": "loja1",
        "loja2": "loja2",
        "l2": "loja2",
        "2": "loja2",
    }.get(key, "")


def _looks_like_item_text(text: str, cfg: Dict[str, Any]) -> bool:
    item = _normalize_candidate_item(text)
    if not item:
        return False
    lowered = item.lower()
    greeting_probe = lowered.lstrip(" ,.!;:-_")
    if "http://" in lowered or "https://" in lowered or "?" in item:
        return False
    if any(greeting_probe == g or greeting_probe.startswith(f"{g} ") for g in _GREETING_PREFIXES):
        return False
    words = [w for w in re.split(r"\s+", lowered) if w]
    if not words or words[0] in _QUESTION_STARTERS:
        return False
    max_words = cfg.get("max_item_words", 8)
    try:
        max_words = int(max_words)
    except Exception:
        max_words = 8
    if len(words) > max_words:
        return False
    return bool(re.search(r"[0-9A-Za-zÀ-ÿ]", item))


def _extract_voice_transcript_text(text: str) -> str:
    raw_no_sender = _strip_leading_sender_prefix(str(text or "").strip())
    if not raw_no_sender:
        return ""
    transcripts = [m.strip() for m in _VOICE_TRANSCRIPT_PATTERN.findall(raw_no_sender) if str(m or "").strip()]
    if not transcripts:
        transcripts = [
            m.strip()
            for m in re.findall(r"Here(?:'|’)s what they said:\s*\"([^\"]+)\"", raw_no_sender, flags=re.IGNORECASE)
            if str(m or "").strip()
        ]
    if not transcripts:
        return ""
    remainder = _VOICE_TRANSCRIPT_PATTERN.sub(" ", raw_no_sender)
    remainder = re.sub(r"Here(?:'|’)s what they said:\s*\"([^\"]+)\"", " ", remainder, flags=re.IGNORECASE)
    remainder = _GENERIC_EMPTY_TEXT_SENTINEL_RE.sub(" ", remainder)
    remainder = _strip_leading_sender_prefix(remainder)
    remainder = re.sub(r"\s+", " ", remainder).strip()
    if remainder == _EMPTY_TEXT_SENTINEL:
        remainder = ""
    if remainder:
        transcripts.append(remainder)
    return " ".join(transcripts).strip()


def _is_voice_transcript_message(text: str) -> bool:
    raw = _strip_leading_sender_prefix(str(text or "").strip())
    if not raw:
        return False
    return bool(_VOICE_TRANSCRIPT_PATTERN.search(raw) or re.search(r"Here(?:'|’)s what they said:\s*\"([^\"]+)\"", raw, flags=re.IGNORECASE))


def _normalize_voice_candidate_item(text: str) -> str:
    item = _normalize_candidate_item(text)
    item = _VOICE_ITEM_PREFIX_RE.sub("", item).strip()
    item = re.sub(r"^(?:que|pra|para)\s+", "", item, flags=re.IGNORECASE).strip()
    item = _TRAILING_STT_PUNCT_RE.sub("", item).strip()
    return item


def _invalid_free_text_message(cfg: Dict[str, Any], allowed_cmds: Set[str]) -> str:
    custom = str(cfg.get("invalid_text_message", "") or "").strip()
    if custom:
        return custom
    cmd_line = f"\nComandos permitidos: `/{'`, `/'.join(sorted(allowed_cmds))}`." if allowed_cmds else ""
    return (
        "🚫 Este canal executa apenas itens de faltas.\n\n"
        "Use `/faltas action:adicionar itens:<item>` ou envie apenas o nome do item.\n"
        "Exemplo: `papel higienico`."
        f"{cmd_line}"
    )


def _load_config() -> Dict[str, Dict[str, Any]]:
    global _cache, _cache_path
    path = _config_path()
    if _cache and _cache_path == path:
        return _cache
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        channels = raw.get("channels", {}) or {}
        _cache = {str(k): v for k, v in channels.items()}
        _cache_path = path
    except Exception:
        _cache = {}
        _cache_path = path
    return _cache


def _get_channel_config(channel_id: str, thread_id: Optional[str] = None, parent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    cfg = _load_config()
    if thread_id and thread_id != channel_id and thread_id in cfg:
        return cfg[thread_id]
    routing_id = parent_id if parent_id else channel_id
    if routing_id in cfg:
        return cfg[routing_id]
    if channel_id in cfg:
        return cfg[channel_id]
    return None


def get_channel_routing(channel_id: str, thread_id: Optional[str] = None, parent_id: Optional[str] = None) -> Tuple[str, Optional[Dict[str, Any]]]:
    cfg = _get_channel_config(channel_id, thread_id, parent_id)
    return ("livre", None) if cfg is None else (cfg.get("mode", "livre"), cfg)


def is_livre(channel_id: str, thread_id: Optional[str] = None, parent_id: Optional[str] = None) -> bool:
    return _get_channel_config(channel_id, thread_id, parent_id) is None


def is_condicional(channel_id: str, thread_id: Optional[str] = None, parent_id: Optional[str] = None) -> bool:
    return _get_channel_config(channel_id, thread_id, parent_id) is not None


def get_forced_model(channel_id: str, thread_id: Optional[str] = None, parent_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    cfg = _get_channel_config(channel_id, thread_id, parent_id)
    if cfg is None:
        return None, None
    return cfg.get("model"), cfg.get("provider")


def get_allowed_scope(channel_id: str, thread_id: Optional[str] = None, parent_id: Optional[str] = None) -> Dict[str, Any]:
    cfg = _get_channel_config(channel_id, thread_id, parent_id)
    if cfg is None:
        return {}
    return {
        "allowed_skills": cfg.get("allowed_skills", []),
        "allowed_commands": cfg.get("allowed_commands", []),
        "always_allowed_commands": cfg.get("always_allowed_commands", list(_DEFAULT_ALWAYS_ALLOWED_COMMANDS)),
        "default_action": cfg.get("default_action"),
        "free_text_policy": cfg.get("free_text_policy", "auto_add"),
    }


def normalize_to_channel_skill(source: Any, message_text: str) -> Tuple[str, str]:
    chat_id = getattr(source, "chat_id", None) or getattr(source, "chat_id_alt", None) or ""
    thread_id = getattr(source, "thread_id", None)
    parent_id = getattr(source, "chat_id_alt", None)
    effective = _get_channel_config(str(parent_id or chat_id), str(thread_id) if parent_id and thread_id else None, str(parent_id) if parent_id else None)
    if effective is None:
        return "PASSTHROUGH", message_text

    text = (message_text or "").strip()
    is_voice_transcript = _is_voice_transcript_message(text)
    voice_text = _extract_voice_transcript_text(text)
    if voice_text:
        text = voice_text
    allowed_cmds = _normalize_command_set(effective.get("allowed_commands", []))
    always_allowed = _always_allowed_commands(effective)
    default_action = effective.get("default_action", "")
    if text.startswith("/"):
        cmd = text.split()[0][1:].lower()
        if cmd in always_allowed:
            return "PASSTHROUGH", message_text
        allowed_any = any(cmd == ac or cmd.startswith(ac) or ac.startswith(cmd) for ac in allowed_cmds)
        if not allowed_any:
            return "BLOCK", (
                f"🚫 O comando `/{cmd}` não é permitido neste canal.\n\n"
                "Use `/faltas action:adicionar itens:<item>` ou envie apenas o nome do item.\n"
                f"Comandos permitidos: `/{'/'.join(sorted(allowed_cmds))}`"
            )
        return "PASSTHROUGH", message_text

    if default_action == "skill:add":
        item = _normalize_candidate_item(text)
        if is_voice_transcript:
            item = _normalize_voice_candidate_item(text) or item
        free_text_policy = str(effective.get("free_text_policy", "auto_add") or "auto_add").strip().lower()
        if not item:
            return "BLOCK", _invalid_free_text_message(effective, allowed_cmds)
        if free_text_policy == "strict_item" and not is_voice_transcript and not _looks_like_item_text(item, effective):
            return "BLOCK", _invalid_free_text_message(effective, allowed_cmds)
        store = _normalize_store(effective.get("store"))
        if store and not re.search(r"\b(?:loja\s*[12]|l[12]|ambas|todas)\b", item.lower()):
            item = f"{item} {store}"
        return "SKILL_ADD", f"/faltas adicionar {item}"
    return "PASSTHROUGH", message_text


def enforce_channel_model(source: Any, turn_route: Dict[str, Any]) -> Dict[str, Any]:
    chat_id = getattr(source, "chat_id", None) or getattr(source, "chat_id_alt", None) or ""
    thread_id = getattr(source, "thread_id", None)
    parent_id = getattr(source, "chat_id_alt", None)
    cfg = _get_channel_config(str(parent_id or chat_id), str(thread_id) if parent_id and thread_id else None, str(parent_id) if parent_id else None)
    if cfg is None:
        return turn_route
    model = cfg.get("model")
    provider = cfg.get("provider")
    if model:
        turn_route["model"] = model
        if provider:
            runtime = turn_route.get("runtime") or {}
            runtime["provider"] = provider
            turn_route["runtime"] = runtime
    allowed_skills = cfg.get("allowed_skills", [])
    if allowed_skills and cfg.get("mode") == "condicionado":
        skills_list = ", ".join(f"`{s}`" for s in allowed_skills)
        turn_route["system_prompt_addon"] = (
            "\n\n[CHANNEL RESTRICTION] "
            f"This channel only allows these skills: {skills_list}. "
            "Do not invoke, inspect, or list other skills. "
            "If the user asks for something that needs another skill, "
            "explain that it is not allowed in this channel."
        )
    return turn_route


def check_command_allowed(channel_id: str, command: Optional[str], thread_id: Optional[str] = None, parent_id: Optional[str] = None) -> Tuple[bool, str]:
    cfg = _get_channel_config(channel_id, thread_id, parent_id)
    if cfg is None:
        return True, ""
    cmd = (command or "").lower().strip().lstrip("/")
    if cmd in _always_allowed_commands(cfg):
        return True, ""
    allowed_cmds = _normalize_command_set(cfg.get("allowed_commands", []))
    allowed_any = any(cmd == ac or cmd.startswith(ac) or ac.startswith(cmd) for ac in allowed_cmds)
    if cfg.get("mode", "condicionado") == "condicionado" and not allowed_any:
        return False, (
            f"🚫 O comando `/{command}` não é permitido neste canal.\n\n"
            "Este canal é dedicado à lista de faltas.\n"
            f"Comandos: `/{'/'.join(sorted(allowed_cmds))}`"
        )
    return True, ""


def check_skill_allowed(channel_id: str, skill_name: Optional[str], thread_id: Optional[str] = None, parent_id: Optional[str] = None) -> Tuple[bool, str]:
    cfg = _get_channel_config(channel_id, thread_id, parent_id)
    if cfg is None:
        return True, ""
    allowed_skills = cfg.get("allowed_skills", [])
    if cfg.get("mode", "condicionado") == "condicionado":
        if not allowed_skills:
            return False, "This channel only allows faltas skills."
        if skill_name and skill_name not in allowed_skills:
            return False, f"Skill `{skill_name}` is not allowed in this channel.\nAllowed: {', '.join(allowed_skills)}"
    return True, ""


def handle(event_name: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return context or {}
