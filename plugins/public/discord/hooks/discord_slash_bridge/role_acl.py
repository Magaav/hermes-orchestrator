from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

DEFAULT_SAFE_COMMANDS = ["status", "help", "usage", "provider"]
DEFAULT_FALLBACK_HIERARCHY = [
    "admin",
    "orchestrator",
    "bot",
    "gerente",
    "balconista",
    "loja1",
    "loja2",
    "aprovado",
]
DEFAULT_CORE_SLASH_COMMANDS = [
    "new",
    "reset",
    "model",
    "reasoning",
    "personality",
    "retry",
    "undo",
    "status",
    "sethome",
    "stop",
    "compress",
    "title",
    "resume",
    "usage",
    "provider",
    "help",
    "insights",
    "reload-mcp",
    "voice",
    "update",
    "restart",
    "approve",
    "deny",
    "thread",
    "queue",
    "background",
    "btw",
    "skill",
]

_ACL_CACHE: Dict[str, tuple[int, Dict[str, Any]]] = {}
ADMIN_ROLE_NAME = "admin"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_command_name(value: Any) -> str:
    return str(value or "").strip().lower().lstrip("/")


def normalize_node_name(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw.endswith(".json"):
        raw = raw[:-5]
    return raw or "orchestrator"


def runtime_node_name() -> str:
    return normalize_node_name(os.getenv("NODE_NAME", "") or "orchestrator")


def resolve_private_discord_root() -> Path:
    configured = str(os.getenv("HERMES_DISCORD_PRIVATE_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path("/local/plugins/private/discord")


def resolve_acl_path(node_name: Optional[str] = None, private_root: Optional[Path] = None) -> Path:
    node = normalize_node_name(node_name or runtime_node_name())
    root = Path(private_root or resolve_private_discord_root())
    return root / "acl" / f"{node}_acl.json"


def normalize_role_token(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text == "@everyone":
        return text
    if text.startswith("name:"):
        return "name:" + text[5:].strip().lower()
    if text.isdigit():
        return text
    return "name:" + text.lower()


def role_display_name(token: str) -> str:
    token = normalize_role_token(token)
    if token.startswith("name:"):
        return token[5:]
    return token


def _normalize_hierarchy_entry(entry: Any) -> Dict[str, str]:
    if isinstance(entry, str):
        token = normalize_role_token(entry)
        if token == "@everyone":
            return {"role_id": "@everyone", "role_name": "@everyone"}
        if token.startswith("name:"):
            return {"role_id": "", "role_name": token[5:]}
        return {"role_id": token, "role_name": ""}

    if not isinstance(entry, dict):
        return {"role_id": "", "role_name": ""}

    role_id = normalize_role_token(entry.get("role_id") or entry.get("id") or "")
    role_name = str(entry.get("role_name") or entry.get("name") or "").strip()

    if role_id.startswith("name:") and not role_name:
        role_name = role_id[5:]
        role_id = ""
    if role_id == "@everyone":
        role_name = "@everyone"

    return {
        "role_id": role_id if role_id not in {"@everyone"} else "@everyone",
        "role_name": role_name,
    }


def _normalize_hierarchy(raw: Any) -> list[Dict[str, str]]:
    if not isinstance(raw, list):
        raw = []

    out: list[Dict[str, str]] = []
    seen: set[str] = set()

    for entry in raw:
        normalized = _normalize_hierarchy_entry(entry)
        rid = normalize_role_token(normalized.get("role_id"))
        rname = str(normalized.get("role_name") or "").strip().lower()

        if rid == "@everyone" or rname == "@everyone":
            key = "@everyone"
        else:
            key = rid or ("name:" + rname if rname else "")
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)

        if rid == "@everyone" or rname == "@everyone":
            out.append({"role_id": "@everyone", "role_name": "@everyone"})
            continue

        if rid.startswith("name:"):
            out.append({"role_id": "", "role_name": rid[5:]})
            continue

        out.append(
            {
                "role_id": rid if rid and rid != "@everyone" else "",
                "role_name": (normalized.get("role_name") or "").strip(),
            }
        )

    if not any((normalize_role_token(item.get("role_id")) == "@everyone") for item in out):
        out.append({"role_id": "@everyone", "role_name": "@everyone"})

    return out


def _normalize_safe_commands(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",") if part.strip()]
    if not isinstance(raw, list):
        raw = []

    out: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        cmd = normalize_command_name(entry)
        if not cmd or cmd in seen:
            continue
        seen.add(cmd)
        out.append(cmd)
    return out


def _normalize_commands(raw: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for key, cfg in raw.items():
        cmd = normalize_command_name(key)
        if not cmd:
            continue

        block = cfg if isinstance(cfg, dict) else {}
        min_role = normalize_role_token(block.get("min_role") or "")
        item: Dict[str, Any] = {}
        if min_role:
            item["min_role"] = min_role
        if "description" in block:
            item["description"] = str(block.get("description") or "")
        if "notes" in block:
            item["notes"] = str(block.get("notes") or "")
        out[cmd] = item

    return out


def normalize_acl(raw: Any, *, node_name: Optional[str] = None, guild_id: Optional[str] = None) -> Dict[str, Any]:
    payload = dict(raw) if isinstance(raw, dict) else {}

    commands = _normalize_commands(payload.get("commands"))
    hierarchy = _normalize_hierarchy(payload.get("hierarchy"))

    user_overrides = payload.get("user_overrides") if isinstance(payload.get("user_overrides"), dict) else {}
    normalized_overrides: Dict[str, Dict[str, Any]] = {}
    for user_id, cfg in user_overrides.items():
        uid = str(user_id or "").strip()
        if not uid:
            continue
        block = cfg if isinstance(cfg, dict) else {}
        raw_roles = block.get("roles")
        if isinstance(raw_roles, str):
            raw_roles = [part.strip() for part in raw_roles.split(",") if part.strip()]
        if not isinstance(raw_roles, list):
            raw_roles = []

        roles = [normalize_role_token(item) for item in raw_roles]
        roles = [token for token in roles if token]
        override_block: Dict[str, Any] = {"roles": roles}
        if bool(block.get("replace")):
            override_block["replace"] = True
        normalized_overrides[uid] = override_block

    safe_commands = _normalize_safe_commands(payload.get("safe_commands"))
    if not safe_commands:
        safe_commands = list(DEFAULT_SAFE_COMMANDS)

    policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
    normalized_policy = {
        "unmapped_command": str(policy.get("unmapped_command") or "deny").strip().lower() or "deny",
    }

    out: Dict[str, Any] = {
        "version": int(payload.get("version") or 1),
        "node": normalize_node_name(payload.get("node") or node_name or runtime_node_name()),
        "guild_id": str(payload.get("guild_id") or guild_id or "").strip(),
        "updated_at": str(payload.get("updated_at") or "").strip() or utc_now_iso(),
        "seed_source": str(payload.get("seed_source") or "").strip(),
        "safe_commands": safe_commands,
        "policy": normalized_policy,
        "hierarchy": hierarchy,
        "commands": commands,
        "user_overrides": normalized_overrides,
    }

    return out


def _read_json_file(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data
    return {}


def load_acl(path: Path) -> Dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return normalize_acl({}, node_name=resolved.stem.replace("_acl", ""))

    try:
        stat = resolved.stat()
        mtime_ns = int(stat.st_mtime_ns)
    except Exception:
        mtime_ns = 0

    cache_key = str(resolved)
    cached = _ACL_CACHE.get(cache_key)
    if cached and cached[0] == mtime_ns:
        return deepcopy(cached[1])

    raw = _read_json_file(resolved)
    acl = normalize_acl(raw, node_name=resolved.stem.replace("_acl", ""))
    _ACL_CACHE[cache_key] = (mtime_ns, acl)
    return deepcopy(acl)


def write_acl(path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    normalized = normalize_acl(
        payload,
        node_name=payload.get("node") if isinstance(payload, dict) else None,
        guild_id=payload.get("guild_id") if isinstance(payload, dict) else None,
    )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(resolved)
    _ACL_CACHE.pop(str(resolved), None)
    return normalized


def available_hierarchy_roles(acl: Dict[str, Any]) -> list[Dict[str, str]]:
    hierarchy = _normalize_hierarchy(acl.get("hierarchy") if isinstance(acl, dict) else [])
    out: list[Dict[str, str]] = []
    for entry in hierarchy:
        role_id = normalize_role_token(entry.get("role_id") or "")
        role_name = str(entry.get("role_name") or "").strip()

        if role_id == "@everyone":
            out.append({"token": "@everyone", "label": "@everyone"})
            continue

        token = role_id
        if not token and role_name:
            token = "name:" + role_name.lower()
        if not token:
            continue

        label = role_name or role_display_name(token)
        out.append({"token": token, "label": label})
    return out


def resolve_hierarchy_role_token(acl: Dict[str, Any], requested_role: Any) -> Optional[Dict[str, str]]:
    requested = normalize_role_token(requested_role)
    if not requested:
        return None

    if requested == "@everyone":
        return {"token": "@everyone", "label": "@everyone"}

    for item in available_hierarchy_roles(acl):
        token = normalize_role_token(item.get("token") or "")
        label = str(item.get("label") or "").strip()
        if not token:
            continue
        if requested == token:
            return {"token": token, "label": label or role_display_name(token)}
        if requested.startswith("name:") and label and requested == ("name:" + label.lower()):
            return {"token": token, "label": label}

    return None


def update_command_min_role(path: Path, command_name: Any, requested_role: Any) -> Dict[str, Any]:
    command = normalize_command_name(command_name)
    if not command:
        raise ValueError("comando inválido")

    resolved = Path(path).expanduser().resolve()
    acl = load_acl(resolved)
    role_match = resolve_hierarchy_role_token(acl, requested_role)
    if role_match is None:
        available = ", ".join(
            f"{entry.get('label')} ({entry.get('token')})"
            for entry in available_hierarchy_roles(acl)
        ) or "(nenhuma role no hierarchy)"
        raise ValueError(f"role não encontrada no hierarchy: {requested_role!r}. Disponíveis: {available}")

    commands = acl.get("commands") if isinstance(acl.get("commands"), dict) else {}
    command_cfg = commands.get(command)
    if not isinstance(command_cfg, dict):
        command_cfg = {}
    else:
        command_cfg = dict(command_cfg)

    previous_min_role = normalize_role_token(command_cfg.get("min_role") or "")
    command_cfg["min_role"] = role_match["token"]
    commands[command] = command_cfg
    acl["commands"] = {key: commands[key] for key in sorted(commands)}
    acl["updated_at"] = utc_now_iso()

    saved = write_acl(resolved, acl)
    return {
        "ok": True,
        "command": command,
        "min_role": role_match["token"],
        "min_role_label": role_match["label"],
        "previous_min_role": previous_min_role,
        "acl_path": str(resolved),
        "node": str(saved.get("node") or ""),
    }


def build_rank_map(hierarchy: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    rank: Dict[str, int] = {}
    normalized = _normalize_hierarchy(list(hierarchy))

    for idx, entry in enumerate(normalized):
        role_id = normalize_role_token(entry.get("role_id") or "")
        role_name = str(entry.get("role_name") or "").strip().lower()

        if role_id:
            rank[role_id] = idx
        if role_name:
            rank["name:" + role_name] = idx

    rank.setdefault("@everyone", len(normalized) - 1)
    return rank


def build_role_label_map(hierarchy: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    normalized = _normalize_hierarchy(list(hierarchy))
    for entry in normalized:
        role_id = normalize_role_token(entry.get("role_id") or "")
        role_name = str(entry.get("role_name") or "").strip()
        if role_id and role_name:
            labels[role_id] = role_name
        if role_name:
            labels["name:" + role_name.lower()] = role_name
    labels.setdefault("@everyone", "@everyone")
    return labels


def _extract_member_roles_from_object(member: Any) -> list[Dict[str, str]]:
    roles = []
    raw_roles = getattr(member, "roles", None)
    if not isinstance(raw_roles, (list, tuple)):
        return roles

    for role in raw_roles:
        rid = str(getattr(role, "id", "") or "").strip()
        rname = str(getattr(role, "name", "") or "").strip()
        if rid == "":
            continue
        roles.append({"role_id": rid, "role_name": rname})

    return roles


async def resolve_interaction_roles(interaction: Any) -> list[Dict[str, str]]:
    user = getattr(interaction, "user", None)
    roles = _extract_member_roles_from_object(user)
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

    if member is None:
        try:
            fetcher = getattr(guild, "fetch_member", None)
            if callable(fetcher):
                member = await fetcher(int(user_id))
        except Exception:
            member = None

    return _extract_member_roles_from_object(member)


def _tokens_from_roles(roles: Iterable[Dict[str, str]]) -> set[str]:
    tokens: set[str] = set()
    for role in roles:
        rid = normalize_role_token(role.get("role_id") or "")
        rname = str(role.get("role_name") or "").strip().lower()
        if rid:
            tokens.add(rid)
        if rname:
            tokens.add("name:" + rname)
    tokens.add("@everyone")
    return tokens


def _apply_user_override_tokens(actor_tokens: set[str], acl: Dict[str, Any], user_id: str) -> set[str]:
    overrides = acl.get("user_overrides") if isinstance(acl.get("user_overrides"), dict) else {}
    raw = overrides.get(user_id)
    if not isinstance(raw, dict):
        return actor_tokens

    roles = raw.get("roles")
    if not isinstance(roles, list):
        roles = []

    override_tokens = {normalize_role_token(item) for item in roles}
    override_tokens = {token for token in override_tokens if token}
    override_tokens.add("@everyone")

    replace = bool(raw.get("replace"))
    if replace:
        return override_tokens

    return actor_tokens | override_tokens


def _resolve_actor_rank(actor_tokens: set[str], rank_map: Dict[str, int]) -> Optional[int]:
    ranks = [rank_map[token] for token in actor_tokens if token in rank_map]
    if not ranks:
        return None
    return min(ranks)


def _resolve_required_rank(min_role: str, rank_map: Dict[str, int]) -> Optional[int]:
    token = normalize_role_token(min_role)
    if not token:
        return None
    if token in rank_map:
        return rank_map[token]

    if token.isdigit() and ("name:" + token) in rank_map:
        return rank_map["name:" + token]

    if token.startswith("name:"):
        fallback = token[5:]
        if fallback in rank_map:
            return rank_map[fallback]

    return None


def _resolve_top_role_name(actor_tokens: set[str], rank_map: Dict[str, int], role_labels: Dict[str, str]) -> str:
    ranked = [(token, rank_map[token]) for token in actor_tokens if token in rank_map]
    if not ranked:
        return "unknown"
    token, _ = sorted(ranked, key=lambda item: item[1])[0]
    return str(role_labels.get(token) or role_display_name(token))


def _admin_tokens_from_acl(acl: Dict[str, Any]) -> set[str]:
    hierarchy = _normalize_hierarchy(acl.get("hierarchy") if isinstance(acl, dict) else [])
    admin_tokens: set[str] = set()
    for entry in hierarchy:
        role_name = str(entry.get("role_name") or "").strip().lower()
        if role_name != ADMIN_ROLE_NAME:
            continue
        role_id = normalize_role_token(entry.get("role_id") or "")
        if role_id and role_id != "@everyone":
            admin_tokens.add(role_id)
        admin_tokens.add("name:admin")
    return admin_tokens


async def _resolve_actor_tokens(interaction: Any, acl: Dict[str, Any]) -> tuple[set[str], str]:
    roles = await resolve_interaction_roles(interaction)
    actor_tokens = _tokens_from_roles(roles)
    actor_user_id = str(getattr(getattr(interaction, "user", None), "id", "") or "").strip()
    if actor_user_id:
        actor_tokens = _apply_user_override_tokens(actor_tokens, acl, actor_user_id)
    return actor_tokens, actor_user_id


async def is_interaction_admin(
    interaction: Any,
    *,
    acl_path: Optional[Path] = None,
) -> Dict[str, Any]:
    path = Path(acl_path or resolve_acl_path()).expanduser().resolve()
    acl = load_acl(path)
    rank_map = build_rank_map(acl.get("hierarchy") or [])
    role_labels = build_role_label_map(acl.get("hierarchy") or [])

    guild = getattr(interaction, "guild", None)
    if guild is None:
        return {
            "is_admin": False,
            "decision": "guild_required",
            "acl_path": str(path),
            "actor_role": "unknown",
        }

    actor_tokens, actor_user_id = await _resolve_actor_tokens(interaction, acl)
    admin_tokens = _admin_tokens_from_acl(acl)
    is_admin = bool(actor_tokens & admin_tokens)
    return {
        "is_admin": is_admin,
        "decision": "admin_bypass" if is_admin else "not_admin",
        "acl_path": str(path),
        "actor_user_id": actor_user_id,
        "actor_role": _resolve_top_role_name(actor_tokens, rank_map, role_labels),
        "admin_tokens": sorted(admin_tokens),
    }


async def authorize_interaction(
    interaction: Any,
    command_name: str,
    *,
    acl_path: Optional[Path] = None,
) -> Dict[str, Any]:
    command = normalize_command_name(command_name)
    if not command:
        return {
            "allowed": False,
            "message": "🚫 ACL: comando inválido.",
            "command": command,
            "decision": "invalid_command",
        }

    path = Path(acl_path or resolve_acl_path()).expanduser().resolve()
    acl = load_acl(path)
    rank_map = build_rank_map(acl.get("hierarchy") or [])
    role_labels = build_role_label_map(acl.get("hierarchy") or [])

    guild = getattr(interaction, "guild", None)
    if guild is None:
        return {
            "allowed": False,
            "message": f"🚫 ACL: `/{command}` exige uso em servidor com papéis (roles).",
            "command": command,
            "decision": "guild_required",
            "acl_path": str(path),
            "required_role": "admin",
        }

    actor_tokens, _actor_user_id = await _resolve_actor_tokens(interaction, acl)
    actor_role_name = _resolve_top_role_name(actor_tokens, rank_map, role_labels)
    admin_tokens = _admin_tokens_from_acl(acl)
    if admin_tokens and (actor_tokens & admin_tokens):
        return {
            "allowed": True,
            "message": "",
            "command": command,
            "decision": "admin_bypass",
            "acl_path": str(path),
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
                f"Atualize `{path}` em `commands.{command}.min_role`."
            ),
            "command": command,
            "decision": "unmapped_command",
            "acl_path": str(path),
        }

    min_role = normalize_role_token(cfg.get("min_role") or "")
    if not min_role:
        return {
            "allowed": False,
            "message": (
                f"🚫 ACL: `/{command}` está sem `min_role`. "
                f"Atualize `{path}` em `commands.{command}.min_role`."
            ),
            "command": command,
            "decision": "missing_min_role",
            "acl_path": str(path),
        }

    actor_rank = _resolve_actor_rank(actor_tokens, rank_map)
    required_rank = _resolve_required_rank(min_role, rank_map)
    required_label = str(role_labels.get(normalize_role_token(min_role)) or role_display_name(min_role))

    if required_rank is None:
        return {
            "allowed": False,
            "message": (
                f"🚫 ACL: `/{command}` referencia role inválida (`{role_display_name(min_role)}`). "
                f"Corrija `{path}`."
            ),
            "command": command,
            "decision": "invalid_required_role",
            "acl_path": str(path),
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
            "acl_path": str(path),
            "required_role": required_label,
        }

    allowed = actor_rank <= required_rank
    if not allowed:
        return {
            "allowed": False,
            "message": (
                f"🚫 ACL: `/{command}` requer role `{role_display_name(min_role)}` ou superior. "
                f"Sua role atual: `{actor_role_name}`."
            ),
            "command": command,
            "decision": "role_too_low",
            "acl_path": str(path),
            "required_role": required_label,
            "actor_role": actor_role_name,
        }

    return {
        "allowed": True,
        "message": "",
        "command": command,
        "decision": "allow",
        "acl_path": str(path),
        "required_role": required_label,
        "actor_role": actor_role_name,
    }
