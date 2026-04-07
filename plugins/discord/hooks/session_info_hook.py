"""
Session Info Hook — carregado pelo gateway para formatar /status.

CHANGELOG:
- 2026-03-31: inicial (fix /status tokens=0, model/provider=unknown no Discord)
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional


def _apply_channel_acl_route(
    source: Any,
    model_label: str,
    provider_label: str,
    routing_note: str,
) -> tuple[str, str, str]:
    """Apply channel_acl routing on top of smart-model routing for /status."""
    try:
        import importlib.util
        import sys

        hook_path = Path.home() / ".hermes" / "hooks" / "channel_acl" / "handler.py"
        if not hook_path.exists():
            return model_label, provider_label, routing_note

        spec = importlib.util.spec_from_file_location("colmeio_channel_acl_status", hook_path)
        if not spec or not spec.loader:
            return model_label, provider_label, routing_note

        mod = importlib.util.module_from_spec(spec)
        sys.modules["colmeio_channel_acl_status"] = mod
        spec.loader.exec_module(mod)

        enforce = getattr(mod, "enforce_channel_model", None)
        if not callable(enforce):
            return model_label, provider_label, routing_note

        probe_route = {
            "model": model_label or "?",
            "provider": provider_label or "?",
            "runtime": {},
        }
        routed = enforce(source, dict(probe_route))
        routed_model = routed.get("model") or model_label
        routed_provider = (routed.get("runtime") or {}).get("provider") or provider_label

        if routed_model != model_label or routed_provider != provider_label:
            return routed_model, routed_provider, "channel-acl forced (condicionado)"

        get_channel_routing = getattr(mod, "get_channel_routing", None)
        if callable(get_channel_routing):
            mode, _ = get_channel_routing(
                str(getattr(source, "chat_id", "") or ""),
                str(getattr(source, "thread_id", "") or "") or None,
                str(getattr(source, "chat_id_alt", "") or "") or None,
            )
            if mode == "condicionado":
                return routed_model, routed_provider, "channel-acl matched (condicionado)"
    except Exception:
        pass

    return model_label, provider_label, routing_note


def get_session_info(platform_adapter, session_entry, source) -> Dict[str, Any]:
    """
    Hook principal. Recebe o adapter, session_entry e source; retorna dict com:
      - tokens_used: int
      - model_label: str
      - provider_label: str
      - routing_note: str
    """
    tokens_used = 0
    model_label = "?"
    provider_label = "?"
    routing_note = "default (no channel rule matched)"

    # ── Token count (from session_entry, provider-independent) ─────────────
    if session_entry:
        try:
            tokens_used = (
                (session_entry.input_tokens or 0) +
                (session_entry.output_tokens or 0)
            )
        except Exception:
            pass

    # ── Model + Provider (from config.yaml, not gateway config) ──────────
    _full_cfg = {}
    try:
        import yaml as _y
        _hermes_home = Path(__file__).parent.parent.parent / ".hermes"
        _cfg_path = _hermes_home / "config.yaml"
        if _cfg_path.exists():
            with open(_cfg_path) as _f:
                _full_cfg = _y.safe_load(_f) or {}
            model_label = _full_cfg.get("model", {}).get("default") or "?"
            provider_label = _full_cfg.get("model", {}).get("provider") or "?"
    except Exception:
        pass

    # ── Smart model routing (re-aplica se configurado) ────────────────────
    try:
        from agent.smart_model_routing import resolve_turn_route
        cfg = _full_cfg.get("smart_model_routing", {}) or {}
        if cfg:
            primary = {
                "model": model_label or "unknown",
                "provider": provider_label or "unknown",
                "api_key": None,
                "base_url": None,
                "api_mode": None,
                "command": None,
                "args": [],
            }
            route = resolve_turn_route("", cfg, primary, source=source)
            model_label = route.get("model", model_label)
            runtime = route.get("runtime", {}) or {}
            provider_label = runtime.get("provider", provider_label)
            raw_label = route.get("label", "")
            if raw_label:
                routing_note = raw_label
    except Exception:
        pass

    # ── Channel ACL routing (final override, mirrors run.py order) ──────────
    model_label, provider_label, routing_note = _apply_channel_acl_route(
        source=source,
        model_label=model_label,
        provider_label=provider_label,
        routing_note=routing_note,
    )

    return {
        "tokens_used": tokens_used,
        "model_label": model_label,
        "provider_label": provider_label,
        "routing_note": routing_note,
    }
