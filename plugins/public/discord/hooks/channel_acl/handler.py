"""
Discord Channel ACL Hook — deterministic per-channel routing.

BEHAVIOR:
  Channels are classified as:
    - livre (free): default model, any skill/context allowed
    - condicionado (restricted): forced model + bounded skill/command scope

  In restricted (`condicionado`) channels:
    - Any message not matching allowed scope → BLOCKED with helpful error
    - Voice transcribed text → same restricted behavior
    - Thread inherits from parent channel unless overridden

  This hook SURVIVES hermes-agent updates because it lives in
  /local/plugins/public/discord/hooks/ and is re-applied via
  apply_channel_acl_run_py.py after each agent update.

SURVIVES: hermes-agent updates (lives in /local/plugins/public/discord/hooks/)
CONFIG:   /local/plugins/private/discord/hooks/channel_acl/config.yaml

CHANGELOG:
- 2026-04-01: v1 — fork of channel_acl with free/restricted modes
- 2026-04-17: strict channels no longer bypass ACL for admins
"""

import re
import os
import json
import shutil
import asyncio
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

_HOOK_DIR = Path(__file__).parent
_CONFIG_PATH = _HOOK_DIR / "config.yaml"
_cache: Dict[str, Dict[str, Any]] = {}
_cache_mtime_ns: int = -1
_cache_config_path: Optional[Path] = None
_models_cache: Dict[str, Dict[str, str]] = {}
_models_cache_path: Optional[Path] = None
_models_cache_mtime_ns: int = -1
_admin_users_cache: set[str] = set()
_admin_users_cache_path: Optional[Path] = None
_admin_users_cache_mtime_ns: int = -1
_live_admin_cache: Dict[str, Tuple[float, bool]] = {}
_LIVE_ADMIN_CACHE_TTL_SEC = 60.0

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
_CONVERSATIONAL_STARTERS = {
    "quero",
    "preciso",
    "gostaria",
    "poderia",
    "podem",
    "manda",
    "mandaai",
    "envia",
    "mostra",
    "listar",
    "lista",
    "ajuda",
    "help",
    "obrigado",
    "valeu",
}
_CONVERSATIONAL_SNIPPETS = (
    "por favor",
    "me ajuda",
    "pode me",
    "pode ",
    "consegue ",
    "quero ",
    "preciso ",
    "gostaria ",
)
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


def clear_cache() -> None:
    global _cache
    global _cache_mtime_ns
    global _cache_config_path
    global _models_cache
    global _models_cache_path
    global _models_cache_mtime_ns
    global _admin_users_cache
    global _admin_users_cache_path
    global _admin_users_cache_mtime_ns
    global _live_admin_cache

    _cache = {}
    _cache_mtime_ns = -1
    _cache_config_path = None
    _models_cache = {}
    _models_cache_path = None
    _models_cache_mtime_ns = -1
    _admin_users_cache = set()
    _admin_users_cache_path = None
    _admin_users_cache_mtime_ns = -1
    _live_admin_cache = {}


def _runtime_node_name() -> str:
    raw = str(os.getenv("NODE_NAME", "") or "").strip().lower()
    if raw.endswith(".json"):
        raw = raw[:-5]
    return raw or "orchestrator"


def _resolve_private_discord_root() -> Path:
    configured = str(os.getenv("HERMES_DISCORD_PRIVATE_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path("/local/plugins/private/discord")


def _resolve_private_channel_acl_config_path() -> Path:
    return _resolve_private_discord_root() / "hooks" / "channel_acl" / "config.yaml"


def _resolve_channel_acl_config_path() -> Path:
    # Optional explicit override for diagnostics/tests.
    configured = str(os.getenv("HERMES_DISCORD_CHANNEL_ACL_CONFIG", "") or "").strip()
    if configured:
        return Path(configured).expanduser()

    private_path = _resolve_private_channel_acl_config_path()
    runtime_path = _HOOK_DIR / "config.yaml"

    # Test/runtime explicit override via module variable.
    override_path = _CONFIG_PATH
    if override_path not in {private_path, runtime_path}:
        return override_path

    # Canonical source-of-truth is private policy.
    if private_path.exists():
        return private_path

    return runtime_path


def _resolve_private_models_path() -> Path:
    return _resolve_private_discord_root() / "models" / f"{_runtime_node_name()}_models.json"


def _resolve_private_discord_users_path() -> Path:
    return _resolve_private_discord_root() / "discord_users.json"


def _normalize_model_catalog(raw: Any) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    entries: list[Dict[str, Any]] = []

    if isinstance(raw, dict):
        models = raw.get("models")
        if isinstance(models, dict):
            for key, value in models.items():
                if isinstance(value, dict):
                    item = dict(value)
                    item.setdefault("key", str(key))
                    entries.append(item)
        elif isinstance(models, list):
            entries.extend(item for item in models if isinstance(item, dict))
        elif {"key", "provider", "model"} <= set(raw.keys()):
            entries.append(dict(raw))
    elif isinstance(raw, list):
        entries.extend(item for item in raw if isinstance(item, dict))

    for item in entries:
        key = str(item.get("key") or "").strip()
        provider = str(item.get("provider") or "").strip()
        model = str(item.get("model") or "").strip()
        if not key or not provider or not model:
            continue
        out[key] = {
            "key": key,
            "label": str(item.get("label") or key).strip() or key,
            "provider": provider,
            "model": model,
        }
    return out


def _load_models_catalog() -> Dict[str, Dict[str, str]]:
    global _models_cache
    global _models_cache_path
    global _models_cache_mtime_ns

    models_path = _resolve_private_models_path()
    try:
        mtime_ns = int(models_path.stat().st_mtime_ns)
    except Exception:
        mtime_ns = -1

    if (
        _models_cache_path == models_path
        and _models_cache_mtime_ns == mtime_ns
        and _models_cache
    ):
        return dict(_models_cache)

    if not models_path.exists():
        _models_cache = {}
        _models_cache_path = models_path
        _models_cache_mtime_ns = mtime_ns
        return {}

    try:
        raw = json.loads(models_path.read_text(encoding="utf-8"))
        parsed = _normalize_model_catalog(raw)
    except Exception:
        parsed = {}

    _models_cache = parsed
    _models_cache_path = models_path
    _models_cache_mtime_ns = mtime_ns
    return dict(_models_cache)


def _load_admin_users() -> set[str]:
    global _admin_users_cache
    global _admin_users_cache_path
    global _admin_users_cache_mtime_ns

    users_path = _resolve_private_discord_users_path()
    try:
        mtime_ns = int(users_path.stat().st_mtime_ns)
    except Exception:
        mtime_ns = -1

    if (
        _admin_users_cache_path == users_path
        and _admin_users_cache_mtime_ns == mtime_ns
        and _admin_users_cache
    ):
        return set(_admin_users_cache)

    admin_ids: set[str] = set()

    env_admins = str(os.getenv("DISCORD_ADMIN_USER_IDS", "") or "").strip()
    if env_admins:
        for part in env_admins.split(","):
            uid = str(part or "").strip()
            if uid:
                admin_ids.add(uid)

    if users_path.exists():
        try:
            payload = json.loads(users_path.read_text(encoding="utf-8"))
            users = payload.get("users") if isinstance(payload, dict) else []
            if isinstance(users, list):
                for row in users:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("role") or "").strip().lower() != "admin":
                        continue
                    uid = str(row.get("discord_user_id") or "").strip()
                    if uid:
                        admin_ids.add(uid)
        except Exception:
            pass

    _admin_users_cache = admin_ids
    _admin_users_cache_path = users_path
    _admin_users_cache_mtime_ns = mtime_ns
    return set(_admin_users_cache)


def _resolve_discord_guild_id() -> str:
    return str(
        os.getenv("DISCORD_SERVER_ID")
        or os.getenv("DISCORD_GUILD_ID")
        or ""
    ).strip()


def _resolve_discord_bot_token() -> str:
    return str(os.getenv("DISCORD_BOT_TOKEN", "") or "").strip()


def _admin_role_ids_from_acl() -> set[str]:
    acl_path = _resolve_private_discord_root() / "acl" / f"{_runtime_node_name()}_acl.json"
    if not acl_path.exists():
        return set()
    try:
        payload = json.loads(acl_path.read_text(encoding="utf-8"))
    except Exception:
        return set()

    hierarchy = payload.get("hierarchy") if isinstance(payload, dict) else []
    out: set[str] = set()
    if isinstance(hierarchy, list):
        for entry in hierarchy:
            if not isinstance(entry, dict):
                continue
            role_name = str(entry.get("role_name") or "").strip().lower()
            role_id = str(entry.get("role_id") or "").strip()
            if role_name == "admin" and role_id and role_id != "@everyone":
                out.add(role_id)
    return out


def _is_admin_via_discord_role(user_id: str) -> Optional[bool]:
    uid = str(user_id or "").strip()
    if not uid:
        return False

    cached = _live_admin_cache.get(uid)
    now = time.time()
    if cached and cached[0] > now:
        return bool(cached[1])

    guild_id = _resolve_discord_guild_id()
    token = _resolve_discord_bot_token()
    admin_role_ids = _admin_role_ids_from_acl()
    if not guild_id or not token or not admin_role_ids:
        return None

    url = f"https://discord.com/api/v10/guilds/{guild_id}/members/{uid}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bot {token}"}, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            body = (resp.read() or b"").decode("utf-8", errors="ignore")
            payload = json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        if int(getattr(exc, "code", 0) or 0) == 404:
            _live_admin_cache[uid] = (now + _LIVE_ADMIN_CACHE_TTL_SEC, False)
            return False
        return None
    except Exception:
        return None

    roles = payload.get("roles") if isinstance(payload, dict) else []
    role_ids = {str(item or "").strip() for item in roles if str(item or "").strip()}
    is_admin = bool(role_ids & admin_role_ids)
    _live_admin_cache[uid] = (now + _LIVE_ADMIN_CACHE_TTL_SEC, is_admin)
    return is_admin


def _source_is_admin(source: Any) -> bool:
    uid = str(getattr(source, "user_id", "") or "").strip()
    if not uid:
        return False

    env_admins = str(os.getenv("DISCORD_ADMIN_USER_IDS", "") or "").strip()
    if env_admins:
        tokens = {str(part or "").strip() for part in env_admins.split(",") if str(part or "").strip()}
        if uid in tokens:
            return True

    live = _is_admin_via_discord_role(uid)
    if live is not None:
        return bool(live)

    # Last-resort fallback for degraded Discord API reachability.
    if uid in _load_admin_users():
        return True

    acl_path = _resolve_private_discord_root() / "acl" / f"{_runtime_node_name()}_acl.json"
    if not acl_path.exists():
        return False
    try:
        payload = json.loads(acl_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    hierarchy = payload.get("hierarchy") if isinstance(payload, dict) else []
    admin_tokens: set[str] = set()
    if isinstance(hierarchy, list):
        for entry in hierarchy:
            if not isinstance(entry, dict):
                continue
            role_name = str(entry.get("role_name") or "").strip().lower()
            role_id = str(entry.get("role_id") or "").strip()
            if role_name == "admin":
                if role_id and role_id != "@everyone":
                    admin_tokens.add(role_id)
                admin_tokens.add("name:admin")

    overrides = payload.get("user_overrides") if isinstance(payload, dict) else {}
    row = overrides.get(uid) if isinstance(overrides, dict) else None
    if not isinstance(row, dict):
        return False
    roles = row.get("roles")
    if not isinstance(roles, list):
        return False
    role_tokens = {str(item or "").strip().lower() for item in roles if str(item or "").strip()}
    return bool(role_tokens & {token.lower() for token in admin_tokens})


def _resolve_faltas_pipeline_script() -> Path:
    hermes_home_raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    hermes_home = Path(hermes_home_raw).expanduser() if hermes_home_raw else None
    if hermes_home is None:
        node_name = str(os.getenv("NODE_NAME", "") or "").strip()
        if node_name:
            candidate = Path("/local/agents/nodes") / node_name / ".hermes"
            if candidate.exists():
                hermes_home = candidate
    if hermes_home is None:
        orchestrator_home = Path("/local/agents/nodes/orchestrator/.hermes")
        if orchestrator_home.exists():
            hermes_home = orchestrator_home

    candidates = [
        str(os.getenv("COLMEIO_FALTAS_PIPELINE_SCRIPT", "") or "").strip(),
        "/local/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py",
    ]
    if hermes_home is not None:
        candidates.append(
            str(
                hermes_home
                / "skills"
                / "custom"
                / "colmeio"
                / "colmeio-lista-de-faltas"
                / "scripts"
                / "faltas_pipeline.py"
            )
        )
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.exists() and path.is_file():
            return path
    return Path(candidates[-1])


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


def _extract_normalized_faltas_item(message_text: str) -> str:
    text = str(message_text or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if not lowered.startswith("/faltas "):
        return ""
    parts = text.split(maxsplit=2)
    if len(parts) < 3:
        return ""
    action = str(parts[1] or "").strip().lower()
    if action not in {"adicionar", "add"}:
        return ""
    return str(parts[2] or "").strip()


def _summarize_store_items(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    names: list[str] = []
    for row in items:
        if isinstance(row, (list, tuple)) and row:
            value = str(row[0] or "").strip()
        else:
            value = str(row or "").strip()
        if value:
            names.append(value)
    return ", ".join(names)


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


def _strip_leading_sender_prefix(text: str) -> str:
    return _LEADING_SENDER_PREFIX_RE.sub("", str(text or "")).strip()


def _normalize_candidate_item(text: str) -> str:
    item = _strip_leading_sender_prefix(text)
    item = _strip_discord_mentions(item)
    if not item:
        return ""
    item = item.strip().strip("\"'`")
    item = re.sub(r"\s+", " ", item).strip()
    item = _TRAILING_STT_PUNCT_RE.sub("", item).strip()
    return item


def _normalize_channel_label(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    if not key:
        return ""
    compact = re.sub(r"[^0-9a-z]+", "", key)
    mapping = {
        "l1": "loja1",
        "1": "loja1",
        "loja1": "loja1",
        "store1": "loja1",
        "l2": "loja2",
        "2": "loja2",
        "loja2": "loja2",
        "store2": "loja2",
        "ambas": "ambas",
        "todas": "ambas",
    }
    if compact in mapping:
        return mapping[compact]
    return mapping.get(key, key)


def _store_from_channel_config(cfg: Dict[str, Any]) -> str:
    value = _normalize_channel_label(cfg.get("label") or cfg.get("store"))
    return value if value in {"loja1", "loja2", "ambas"} else ""


def _resolve_source_channel_config(source: Any) -> Optional[Dict[str, Any]]:
    chat_id = getattr(source, "chat_id", None) or getattr(source, "chat_id_alt", None) or ""
    thread_id = getattr(source, "thread_id", None)
    parent_id = getattr(source, "chat_id_alt", None)
    if parent_id:
        return _get_channel_config(str(parent_id), str(thread_id) if thread_id else None, str(parent_id))
    return _get_channel_config(str(chat_id), None, None)


def _looks_like_item_text(text: str, cfg: Dict[str, Any]) -> bool:
    item = _normalize_candidate_item(text)
    if not item:
        return False

    lowered = item.lower()
    greeting_probe = lowered.lstrip(" ,.!;:-_")
    if "http://" in lowered or "https://" in lowered:
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
    if words[0] in _CONVERSATIONAL_STARTERS:
        return False
    if any(snippet in lowered for snippet in _CONVERSATIONAL_SNIPPETS):
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
    raw_no_sender = _strip_leading_sender_prefix(raw)

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
        "Use `/faltas action:adicionar itens:<item>` ou envie apenas o nome do item.\n"
        "Exemplo: `papel higienico`."
        f"{cmd_line}"
    )


def _load_config() -> Dict[str, Dict[str, Any]]:
    """Load routing config from config.yaml, with caching."""
    global _cache
    global _cache_mtime_ns
    global _cache_config_path

    config_path = _resolve_channel_acl_config_path()

    try:
        current_mtime = int(config_path.stat().st_mtime_ns) if config_path.exists() else -1
    except Exception:
        current_mtime = -1

    if _cache and _cache_mtime_ns == current_mtime and _cache_config_path == config_path:
        return _cache
    try:
        import yaml
        if config_path.exists():
            with open(config_path) as f:
                raw = yaml.safe_load(f) or {}
            raw_channels = raw.get("channels", {}) or {}
            # Normalize all channel IDs to strings
            _cache = {str(k): v for k, v in raw_channels.items()}
            _cache_mtime_ns = current_mtime
            _cache_config_path = config_path
        else:
            _cache = {}
            _cache_mtime_ns = current_mtime
            _cache_config_path = config_path
    except Exception:
        _cache = {}
        _cache_mtime_ns = current_mtime
        _cache_config_path = config_path
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
    model_entry, error = _resolve_specific_model_config(cfg)
    if error:
        return None, None
    if model_entry is None:
        return None, None
    return model_entry.get("model"), model_entry.get("provider")


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


def _resolve_specific_model_config(cfg: Dict[str, Any]) -> tuple[Optional[Dict[str, str]], str]:
    mode = str(cfg.get("mode") or "condicionado").strip().lower()
    if mode != "condicionado":
        return None, ""

    model_key = str(cfg.get("model_key") or "").strip()
    catalog = _load_models_catalog()

    if not model_key:
        return None, (
            "🚫 Canal condicionado sem `model_key` válido. "
            f"Atualize `{_resolve_private_models_path()}` e o ACL do canal."
        )

    model_entry = catalog.get(model_key)
    if not isinstance(model_entry, dict):
        return None, (
            f"🚫 model_key `{model_key}` não encontrado em `{_resolve_private_models_path()}`. "
            "Canal permanece bloqueado (fail-closed)."
        )
    return model_entry, ""


async def dispatch_normalized_command(source: Any, message_text: str) -> Tuple[bool, str]:
    """Deterministic handler for normalized restricted-channel commands."""
    item = _extract_normalized_faltas_item(message_text)
    if not item:
        return False, ""

    script_path = _resolve_faltas_pipeline_script()
    if not script_path.exists():
        return True, f"❌ Pipeline de faltas não encontrado: `{script_path}`"

    cmd = [
        _resolve_python_bin(),
        str(script_path),
        "add",
        "--trigger-mode",
        "channel_acl_normalized",
        "--itens",
        item,
    ]

    channel_id = str(getattr(source, "chat_id", "") or "").strip()
    chat_id_alt = str(getattr(source, "chat_id_alt", "") or "").strip()
    author_id = str(getattr(source, "user_id", "") or "").strip()
    author_name = str(getattr(source, "user_name", "") or "").strip()

    if channel_id:
        cmd.extend(["--channel-id", channel_id, "--origin-channel-id", channel_id])
    if chat_id_alt:
        cmd.extend(["--chat-id-alt", chat_id_alt])
    effective = _resolve_source_channel_config(source) or {}
    inferred_store = _store_from_channel_config(effective)
    if inferred_store:
        cmd.extend(["--loja", inferred_store])
    if author_id:
        cmd.extend(["--author-id", author_id])
    if author_name:
        cmd.extend(["--author-name", author_name])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        return True, "❌ Timeout ao executar pipeline de faltas para este canal."
    except Exception as exc:
        return True, f"❌ Falha ao executar pipeline de faltas: {exc}"

    out_text = (stdout or b"").decode(errors="ignore").strip()
    err_text = (stderr or b"").decode(errors="ignore").strip()

    payload: Dict[str, Any] = {}
    try:
        payload = json.loads(out_text) if out_text else {}
    except Exception:
        payload = {}

    if proc.returncode != 0:
        detail = str(payload.get("error") or err_text or out_text or "erro desconhecido").strip()
        return True, f"❌ Falha ao processar item neste canal: {detail}"

    stores = payload.get("data", {}).get("stores") if isinstance(payload.get("data"), dict) else {}
    if isinstance(stores, dict) and stores:
        lines = ["✅ Item processado."]
        for store_name, store_data in stores.items():
            if not isinstance(store_data, dict):
                continue
            added = store_data.get("added") if isinstance(store_data.get("added"), list) else []
            incremented = store_data.get("incremented") if isinstance(store_data.get("incremented"), list) else []
            item_names = _summarize_store_items(added) or _summarize_store_items(incremented) or item
            lines.append(
                f"loja:`{store_name[-1:] or store_name}` "
                f"nome:`{item_names}` "
                f"novos:`{len(added)}` "
                f"atualizados:`{len(incremented)}`"
            )
        return True, "\n".join(lines)

    return True, "✅ Item processado."


def normalize_to_channel_skill(
    source: Any,
    message_text: str,
) -> Tuple[str, str]:
    """
    Given a message in a channel, return (action, transformed_text).

    For free channels:
      - PASSTHROUGH: let Hermes handle it normally

    For restricted (`condicionado`) channels:
      - If message starts with allowed command (/faltas, etc.)
        → PASSTHROUGH
      - If message starts with / but NOT an allowed command
        → BLOCK with error
      - If free text / voice transcript
        → applies default_action:
            "skill:add" → /faltas adicionar <text> (internal normalization)
      - Meta commands (/status, /help, /reset, etc.) → always PASSTHROUGH

    Returns (cmd, transformed_text).
    cmd = "BLOCK"  → reject with block message
    cmd = "PASSTHROUGH" → use message_text as-is
    cmd = "SKILL_ADD"   → transformed to /faltas adicionar <text> (internal)
    """
    effective = _resolve_source_channel_config(source)

    # Free channel -> no transformation
    if effective is None:
        return "PASSTHROUGH", message_text

    _model_entry, model_error = _resolve_specific_model_config(effective)
    if model_error:
        return "BLOCK", model_error

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
                    f"Use `/faltas action:adicionar itens:<item>` ou envie apenas o nome do item.\n"
                    f"Comandos permitidos: `/{'/'.join(sorted(allowed_cmds))}`"
                )
            return "PASSTHROUGH", message_text
        else:
            # Free text or voice → apply default_action
            if default_action == "skill:add":
                item = _normalize_candidate_item(text)
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

    model_entry, model_error = _resolve_specific_model_config(cfg)
    if model_error:
        turn_route["channel_acl_blocked"] = model_error
        return turn_route

    if model_entry:
        model = str(model_entry.get("model") or "").strip()
        provider = str(model_entry.get("provider") or "").strip()
        if model:
            turn_route["model"] = model
            if provider:
                runtime = turn_route.get("runtime") or {}
                runtime["provider"] = provider
                turn_route["runtime"] = runtime

    # Build system_prompt_addon for skill gating in restricted channels
    allowed_skills = cfg.get("allowed_skills", [])
    prompt_parts: list[str] = []
    if allowed_skills and cfg.get("mode") == "condicionado":
        skills_list = ", ".join(f"`{s}`" for s in allowed_skills)
        prompt_parts.append(
            f"\n\n[CHANNEL RESTRICTION] "
            f"This channel only allows these skills: {skills_list}. "
            f"Do not invoke, inspect, or list other skills. "
            f"If the user asks for something that needs another skill, "
            f"explain that it is not allowed in this channel."
        )
    instructions = str(cfg.get("instructions") or "").strip()
    if instructions:
        prompt_parts.append(f"\n\n[CHANNEL INSTRUCTIONS] {instructions}")

    if prompt_parts:
        turn_route["system_prompt_addon"] = "".join(prompt_parts)

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

    _model_entry, model_error = _resolve_specific_model_config(cfg)
    if model_error:
        return False, model_error

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

    _model_entry, model_error = _resolve_specific_model_config(cfg)
    if model_error:
        return False, model_error

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


def handle(event_name: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Hook entrypoint for gateway event bus (no-op for compatibility)."""
    return context or {}
