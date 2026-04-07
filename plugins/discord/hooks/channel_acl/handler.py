"""
Discord Channel Routing Hook v1 — deterministic per-channel routing.

BEHAVIOR:
  Channels are classified as:
    - livre (free): default model, any skill/context allowed
    - condicionado (restricted): forced model + bounded skill/command scope

  In restricted (`condicionado`) channels:
    - Any message not matching allowed scope → BLOCKED with helpful error
    - Voice transcribed text → same restricted behavior
    - Thread inherits from parent channel unless overridden

  This hook SURVIVES hermes-agent updates because it lives in
  /local/workspace/discord/hooks/ and is re-applied via
  reapply_discord_channel_routing_hook.py after each agent update.

SURVIVES: hermes-agent updates (lives in /local/workspace/discord/hooks/)
CONFIG:   /local/workspace/discord/hooks/discord_channel_routing_hook/config.yaml

CHANGELOG:
- 2026-04-01: v1 — fork of channel_acl with free/restricted modes
"""

import re
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

_HOOK_DIR = Path(__file__).parent
_CONFIG_PATH = _HOOK_DIR / "config.yaml"
_cache: Dict[str, Dict[str, Any]] = {}

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
    r"\[The user sent a voice message~ Here's what they said: \"([^\"]+)\"\]"
)
_EMPTY_TEXT_SENTINEL = "(The user sent a message with no text content)"


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
    if configured:
        return configured
    return set(_DEFAULT_ALWAYS_ALLOWED_COMMANDS)


def _strip_discord_mentions(text: str) -> str:
    cleaned = re.sub(r"<@!?\d+>", " ", text or "")
    # Also handle plain-text mention forms that may appear after adapter parsing,
    # e.g. "@Orchestrator oi", "@here", "@everyone".
    cleaned = re.sub(r"(?<!\w)@[\w.\-À-ÿ_]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _looks_like_item_text(text: str, cfg: Dict[str, Any]) -> bool:
    item = _strip_discord_mentions(text)
    if not item:
        return False

    lowered = item.lower()
    greeting_probe = lowered.lstrip(" ,.!;:-_")
    if "http://" in lowered or "https://" in lowered:
        return False
    if "\n" in item:
        return False
    if "?" in item:
        return False
    if any(greeting_probe == g or greeting_probe.startswith(f"{g} ") for g in _GREETING_PREFIXES):
        return False

    words = [w for w in re.split(r"\s+", lowered) if w]
    if not words:
        return False
    if words[0] in _QUESTION_STARTERS:
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
    raw = str(text or "").strip()
    if not raw:
        return ""

    transcripts = [m.strip() for m in _VOICE_TRANSCRIPT_PATTERN.findall(raw) if str(m or "").strip()]
    if not transcripts:
        return ""

    remainder = _VOICE_TRANSCRIPT_PATTERN.sub(" ", raw)
    remainder = re.sub(r"\s+", " ", remainder).strip()
    if remainder == _EMPTY_TEXT_SENTINEL:
        remainder = ""

    if remainder:
        transcripts.append(remainder)
    return " ".join(transcripts).strip()


def _invalid_free_text_message(cfg: Dict[str, Any], allowed_cmds: Set[str]) -> str:
    custom = str(cfg.get("invalid_text_message", "") or "").strip()
    if custom:
        return custom

    cmd_list = sorted(allowed_cmds)
    cmd_line = ""
    if cmd_list:
        cmd_line = f"\nComandos permitidos: `/{'`, `/'.join(cmd_list)}`."

    return (
        "🚫 Este canal executa apenas itens de faltas.\n\n"
        "Use `/faltas adicionar <item>` ou envie apenas o nome do item.\n"
        "Exemplo: `papel higienico`."
        f"{cmd_line}"
    )


def _load_config() -> Dict[str, Dict[str, Any]]:
    """Load routing config from config.yaml, with caching."""
    global _cache
    if _cache:
        return _cache
    try:
        import yaml
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH) as f:
                raw = yaml.safe_load(f) or {}
            raw_channels = raw.get("channels", {}) or {}
            # Normalize all channel IDs to strings
            _cache = {str(k): v for k, v in raw_channels.items()}
    except Exception:
        _cache = {}
    return _cache


def _get_channel_config(
    channel_id: str,
    thread_id: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Get routing config for this channel/thread.

    Thread inheritance rules:
      1. If thread has explicit config → use it (overrides parent)
      2. If thread has parent_id (chat_id_alt) → inherit from parent channel
      3. Otherwise → direct channel_id lookup

    Args:
        channel_id: the primary channel/thread ID from source.chat_id
        thread_id: source.thread_id (may equal channel_id for thread-ping messages)
        parent_id: source.chat_id_alt (parent channel for threads)
    """
    cfg = _load_config()

    # For threads: parent_id (chat_id_alt) is the authoritative channel for routing.
    # Even when thread_id == channel_id (thread ping), we use parent_id.
    # Direct thread config only if thread_id is explicitly listed in config.
    if thread_id and thread_id != channel_id:
        # Thread explicitly listed in config → use it
        if thread_id in cfg:
            return cfg[thread_id]

    # Use parent channel for routing (handles thread inheritance correctly)
    routing_id = parent_id if parent_id else channel_id
    if routing_id in cfg:
        return cfg[routing_id]

    # Fallback: direct channel_id lookup
    if channel_id in cfg:
        return cfg[channel_id]

    return None


# ── Public API used by run.py (same interface as channel_acl) ────────────────

def get_channel_routing(
    channel_id: str,
    thread_id: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Returns (mode, config) for this channel.
    mode = 'livre' (free) | 'condicionado' (restricted)
    config = full channel config dict (or None for free channels)
    """
    cfg = _get_channel_config(channel_id, thread_id, parent_id)
    if cfg is None:
        return "livre", None
    mode = cfg.get("mode", "livre")
    return mode, cfg


def is_livre(channel_id: str, thread_id: Optional[str] = None, parent_id: Optional[str] = None) -> bool:
    """True if channel is free (no restrictions)."""
    return _get_channel_config(channel_id, thread_id, parent_id) is None


def is_condicional(channel_id: str, thread_id: Optional[str] = None, parent_id: Optional[str] = None) -> bool:
    """True if channel is restricted (`condicionado`)."""
    return _get_channel_config(channel_id, thread_id, parent_id) is not None


def get_forced_model(
    channel_id: str,
    thread_id: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Returns (model, provider) for restricted channels. (None, None) for free channels."""
    cfg = _get_channel_config(channel_id, thread_id, parent_id)
    if cfg is None:
        return None, None
    model = cfg.get("model")
    provider = cfg.get("provider")
    return model, provider


def get_allowed_scope(
    channel_id: str,
    thread_id: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Returns allowed scope for restricted channels:
      {allowed_skills: [...], allowed_commands: [...], default_action: ...}
    Empty for free channels.
    """
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


def normalize_to_channel_skill(
    source: Any,
    message_text: str,
) -> Tuple[str, str]:
    """
    Given a message in a channel, return (action, transformed_text).

    For free channels:
      - PASSTHROUGH: let Hermes handle it normally

    For restricted (`condicionado`) channels:
      - If message starts with allowed command (/faltas, /lista-de-faltas, etc.)
        → PASSTHROUGH
      - If message starts with / but NOT an allowed command
        → BLOCK with error
      - If free text / voice transcript
        → applies default_action:
            "skill:add" → /faltas adicionar <text>
      - Meta commands (/status, /help, /reset, etc.) → always PASSTHROUGH

    Returns (cmd, transformed_text).
    cmd = "BLOCK"  → reject with block message
    cmd = "PASSTHROUGH" → use message_text as-is
    cmd = "SKILL_ADD"   → transformed to /faltas adicionar <text>
    """
    # Resolve channel IDs from source
    chat_id = getattr(source, "chat_id", None) or getattr(source, "chat_id_alt", None) or ""
    thread_id = getattr(source, "thread_id", None)
    parent_id = getattr(source, "chat_id_alt", None)  # parent for threads

    # For threads: use parent_id (chat_id_alt) for routing lookup.
    # The thread inherits from its parent channel, NOT from its own thread ID.
    # channel_id = parent for routing, thread_id = thread itself
    if parent_id:
        effective = _get_channel_config(str(parent_id), str(thread_id) if thread_id else None, str(parent_id))
    else:
        effective = _get_channel_config(str(chat_id), None, None)

    # Free channel -> no transformation
    if effective is None:
        return "PASSTHROUGH", message_text

    text = (message_text or "").strip()
    _voice_text = _extract_voice_transcript_text(text)
    if _voice_text:
        text = _voice_text
    allowed_cmds = _normalize_command_set(effective.get("allowed_commands", []))
    always_allowed = _always_allowed_commands(effective)
    default_action = effective.get("default_action", "")
    mode = effective.get("mode", "condicionado")

    # Configurable always-allowed commands (defaults to /status).
    if text.startswith("/"):
        cmd = text.split()[0][1:].lower()
        if cmd in always_allowed:
            return "PASSTHROUGH", message_text

    # Handle Conditioning
    if mode == "condicionado":
        if text.startswith("/"):
            cmd = text.split()[0][1:].lower()
            # Check if it's an allowed command (full match or partial)
            allowed_any = any(
                cmd == ac or cmd.startswith(ac) or ac.startswith(cmd)
                for ac in allowed_cmds
            )
            if not allowed_any:
                return "BLOCK", (
                    f"🚫 O comando `/{cmd}` não é permitido neste canal.\n\n"
                    f"Use `/faltas adicionar <item>` ou envie apenas o nome do item.\n"
                    f"Comandos permitidos: `/{'/'.join(sorted(allowed_cmds))}`"
                )
            return "PASSTHROUGH", message_text
        else:
            # Free text or voice → apply default_action
            if default_action == "skill:add":
                item = _strip_discord_mentions(text)
                free_text_policy = str(effective.get("free_text_policy", "auto_add") or "auto_add").strip().lower()
                if free_text_policy == "strict_item" and not _looks_like_item_text(item, effective):
                    return "BLOCK", _invalid_free_text_message(effective, allowed_cmds)
                return "SKILL_ADD", f"/faltas adicionar {item}"
            # Fallback: pass through
            return "PASSTHROUGH", message_text

    # Should not reach here - free channels return early
    return "PASSTHROUGH", message_text


def enforce_channel_model(
    source: Any,
    turn_route: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Override turn_route with a channel-specific model if the channel is restricted.
    For threads: use parent channel for routing lookup.

    Returns turn_route with extra keys when the channel is restricted:
      - "system_prompt_addon": str injected into ephemeral system prompt for skill gating
    """
    chat_id = getattr(source, "chat_id", None) or getattr(source, "chat_id_alt", None) or ""
    thread_id = getattr(source, "thread_id", None)
    parent_id = getattr(source, "chat_id_alt", None)

    # For threads: routing is by parent channel, not thread ID
    if parent_id:
        channel_id_for_routing = str(parent_id)
        thread_id_for_cfg = str(thread_id) if thread_id else None
        parent_id_for_cfg = str(parent_id)
    else:
        channel_id_for_routing = str(chat_id) if chat_id else ""
        thread_id_for_cfg = None
        parent_id_for_cfg = None

    cfg = _get_channel_config(channel_id_for_routing, thread_id_for_cfg, parent_id_for_cfg)
    if cfg is None:
        # Free channel - no override
        return turn_route

    model = cfg.get("model")
    provider = cfg.get("provider")
    if model:
        turn_route["model"] = model
        if provider:
            runtime = turn_route.get("runtime") or {}
            runtime["provider"] = provider
            turn_route["runtime"] = runtime

    # Build system_prompt_addon for skill gating in restricted channels
    allowed_skills = cfg.get("allowed_skills", [])
    if allowed_skills and cfg.get("mode") == "condicionado":
        skills_list = ", ".join(f"`{s}`" for s in allowed_skills)
        turn_route["system_prompt_addon"] = (
            f"\n\n[CHANNEL RESTRICTION] "
            f"This channel only allows these skills: {skills_list}. "
            f"Do not invoke, inspect, or list other skills. "
            f"If the user asks for something that needs another skill, "
            f"explain that it is not allowed in this channel."
        )

    return turn_route


def check_command_allowed(
    channel_id: str,
    command: Optional[str],
    thread_id: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Check if a slash command is allowed in this channel.
    Returns (allowed, error_message).
    """
    cfg = _get_channel_config(channel_id, thread_id, parent_id)
    if cfg is None:
        return True, ""

    allowed_cmds = _normalize_command_set(cfg.get("allowed_commands", []))
    cmd = (command or "").lower().strip().lstrip("/")
    mode = cfg.get("mode", "condicionado")
    always_allowed = _always_allowed_commands(cfg)

    if cmd in always_allowed:
        return True, ""

    if mode == "condicionado":
        allowed_any = any(
            cmd == ac or cmd.startswith(ac) or ac.startswith(cmd)
            for ac in allowed_cmds
        )
        if not allowed_any:
            return False, (
                f"🚫 O comando `/{command}` não é permitido neste canal.\n\n"
                f"Este canal é dedicado à lista de faltas.\n"
                f"Comandos: `/{'/'.join(sorted(allowed_cmds))}`"
            )

    return True, ""


def check_skill_allowed(
    channel_id: str,
    skill_name: Optional[str],
    thread_id: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """Check if a skill is allowed in this channel."""
    cfg = _get_channel_config(channel_id, thread_id, parent_id)
    if cfg is None:
        return True, ""

    allowed_skills = cfg.get("allowed_skills", [])
    mode = cfg.get("mode", "condicionado")

    if mode == "condicionado":
        if not allowed_skills:
            return False, f"This channel only allows faltas skills."
        if skill_name and skill_name not in allowed_skills:
            return False, (
                f"Skill `{skill_name}` is not allowed in this channel.\n"
                f"Allowed: {', '.join(allowed_skills)}"
            )

    return True, ""
