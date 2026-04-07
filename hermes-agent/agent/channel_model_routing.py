"""Channel-aware model routing and guardrails for gateway sessions."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from agent.smart_model_routing import is_complex_turn


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_id_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    if isinstance(value, (list, tuple, set)):
        out: set[str] = set()
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                out.add(text)
        return out
    return set()


def _source_matches_rule(source: Any, rule: Dict[str, Any]) -> bool:
    platform_obj = getattr(source, "platform", None)
    platform = str(getattr(platform_obj, "value", platform_obj) or "").strip().lower()

    rule_platform = str(rule.get("platform") or "").strip().lower()
    if rule_platform and rule_platform != platform:
        return False

    chat_id = str(getattr(source, "chat_id", "") or "").strip()
    thread_id = str(getattr(source, "thread_id", "") or "").strip()

    chat_ids = _as_id_set(rule.get("chat_ids"))
    thread_ids = _as_id_set(rule.get("thread_ids"))

    # If selectors were provided, at least one must match.
    if chat_ids or thread_ids:
        if chat_id and chat_id in chat_ids:
            return True
        if thread_id and thread_id in thread_ids:
            return True
        return False

    # No explicit selector means this is a platform-wide rule.
    return True


def resolve_channel_turn_route(
    user_message: str,
    routing_config: Optional[Dict[str, Any]],
    source: Any,
    primary: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Return a channel-specific route decision, or None when no rule matches.

    Return payload may contain:
      - standard route dict fields: model/runtime/label/signature
      - blocked=True + block_message when a rule blocks complex requests
    """
    cfg = routing_config or {}
    if not _coerce_bool(cfg.get("enabled"), False):
        return None

    rules = cfg.get("rules")
    if not isinstance(rules, list) or not rules:
        return None

    for raw_rule in rules:
        if not isinstance(raw_rule, dict):
            continue
        if not _source_matches_rule(source, raw_rule):
            continue

        # Optional guardrail: block complex asks in operational channels.
        if _coerce_bool(raw_rule.get("block_complex"), False):
            max_chars = _coerce_int(raw_rule.get("max_simple_chars"), 180)
            max_words = _coerce_int(raw_rule.get("max_simple_words"), 32)
            if is_complex_turn(user_message, max_simple_chars=max_chars, max_simple_words=max_words):
                msg = str(raw_rule.get("complex_block_message") or "").strip() or (
                    "🚫 Este canal é operacional. Pedidos de código/sistema devem ser feitos no canal de engenharia/frontier."
                )
                return {
                    "blocked": True,
                    "block_message": msg,
                    "label": "channel guardrail",
                }

        provider = str(raw_rule.get("provider") or "").strip().lower()
        model = str(raw_rule.get("model") or "").strip()
        if not provider or not model:
            # Rule matched but is incomplete; fail-safe to primary by not routing.
            return None

        explicit_api_key = str(raw_rule.get("api_key") or "").strip() or None
        api_key_env = str(raw_rule.get("api_key_env") or "").strip()
        if not explicit_api_key and api_key_env:
            explicit_api_key = os.getenv(api_key_env) or None

        from hermes_cli.runtime_provider import resolve_runtime_provider

        try:
            runtime = resolve_runtime_provider(
                requested=provider,
                explicit_api_key=explicit_api_key,
                explicit_base_url=raw_rule.get("base_url"),
            )
        except Exception:
            return None

        return {
            "model": model,
            "runtime": {
                "api_key": runtime.get("api_key"),
                "base_url": runtime.get("base_url"),
                "provider": runtime.get("provider"),
                "api_mode": runtime.get("api_mode"),
                "command": runtime.get("command"),
                "args": list(runtime.get("args") or []),
            },
            "label": f"channel route → {model} ({runtime.get('provider')})",
            "signature": (
                model,
                runtime.get("provider"),
                runtime.get("base_url"),
                runtime.get("api_mode"),
                runtime.get("command"),
                tuple(runtime.get("args") or ()),
            ),
        }

    return None
