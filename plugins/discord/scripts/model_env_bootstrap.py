#!/usr/bin/env python3
"""Bootstrap model defaults/fallbacks from profile .env.

Goal:
- Allow deterministic per-agent model presets in /local/agents/<name>.env.
- Ensure model.default/provider are always present in config.yaml.
- Optionally configure fallback_model from env.
- Keep behavior idempotent and fail-open.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml


VALID_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

MODEL_DEFAULT_FALLBACK = "anthropic/claude-opus-4.6"
PROVIDER_DEFAULT_MODEL = {
    "minimax": "MiniMax-M2.7",
    "minimax-cn": "MiniMax-M2.7",
    "openai-codex": "gpt-5.3-codex",
    "kimi-coding": "moonshotai/kimi-k2.5",
}
PROVIDER_ALIASES = {
    "mini-max": "minimax",
    "mini_max": "minimax",
    "minimaxcn": "minimax-cn",
    "openai_codex": "openai-codex",
}


def _read_env(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not VALID_ENV_KEY_RE.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]
        env[key] = value
    return env


def _load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        return {}
    return data


def _save_config(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(0o600)
    except Exception:
        pass


def _normalize_provider(raw: object) -> str:
    value = str(raw or "").strip().lower()
    if not value:
        return ""
    return PROVIDER_ALIASES.get(value, value)


def _canonicalize_model_name(raw: object) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    norm = re.sub(r"[\s_]+", " ", value).strip().lower()
    if norm in {
        "minimax m2.7",
        "minimax-m2.7",
        "minimax m2 7",
        "m2.7",
        "m2 7",
    }:
        return "MiniMax-M2.7"
    return value


def _infer_provider_from_model(model: str) -> str:
    m = str(model or "").strip().lower()
    if not m:
        return ""
    if m.startswith("minimax") or m in {"m2.7", "m2 7"}:
        return "minimax"
    return ""


def _infer_config_file(env_file: Path) -> Path:
    # /x/.hermes/.env -> /x/.hermes/config.yaml
    if env_file.name == ".env" and env_file.parent.name == ".hermes":
        return env_file.parent / "config.yaml"

    # /local/agents/<name>.env -> /local/agents/<name>/.hermes/config.yaml
    if env_file.suffix == ".env":
        clone_name = env_file.stem
        return env_file.parent / clone_name / ".hermes" / "config.yaml"

    return env_file.parent / "config.yaml"


def _extract_model_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    model_cfg = cfg.get("model")
    if isinstance(model_cfg, str):
        return {"default": str(model_cfg)}
    if isinstance(model_cfg, dict):
        return dict(model_cfg)
    return {}


def _extract_existing_fallback(cfg: Dict[str, Any]) -> Dict[str, str]:
    fb = cfg.get("fallback_model")
    if isinstance(fb, dict):
        model = _canonicalize_model_name(fb.get("model"))
        provider = _normalize_provider(fb.get("provider"))
        if model and provider:
            return {"model": model, "provider": provider}

    fps = cfg.get("fallback_providers")
    if isinstance(fps, list):
        for item in fps:
            if not isinstance(item, dict):
                continue
            model = _canonicalize_model_name(item.get("model"))
            provider = _normalize_provider(item.get("provider"))
            if model and provider:
                return {"model": model, "provider": provider}
    return {}


def _build_default_target(env: Dict[str, str], cfg: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, str]]:
    model_cfg = _extract_model_cfg(cfg)
    cfg_model = _canonicalize_model_name(model_cfg.get("default"))
    cfg_provider = _normalize_provider(model_cfg.get("provider"))

    env_model = _canonicalize_model_name(env.get("DEFAULT_MODEL"))
    env_provider = _normalize_provider(env.get("DEFAULT_MODEL_PROVIDER"))
    env_provider_legacy = _normalize_provider(env.get("HERMES_INFERENCE_PROVIDER"))

    provider = env_provider or env_provider_legacy or cfg_provider
    if not provider:
        inferred = _infer_provider_from_model(env_model or cfg_model)
        provider = inferred or "auto"

    model = env_model or cfg_model
    if not model:
        model = PROVIDER_DEFAULT_MODEL.get(provider, MODEL_DEFAULT_FALLBACK)
    model = _canonicalize_model_name(model)

    if not provider:
        provider = _infer_provider_from_model(model) or "auto"

    target = {
        "provider": provider,
        "model": model,
        "base_url": str(env.get("DEFAULT_MODEL_BASE_URL", "") or "").strip(),
        "api_mode": str(env.get("DEFAULT_MODEL_API_MODE", "") or "").strip(),
    }
    source = {
        "provider": (
            "DEFAULT_MODEL_PROVIDER"
            if env_provider
            else ("HERMES_INFERENCE_PROVIDER" if env_provider_legacy else ("config.model.provider" if cfg_provider else "derived"))
        ),
        "model": (
            "DEFAULT_MODEL"
            if env_model
            else ("config.model.default" if cfg_model else f"provider-default:{provider}")
        ),
    }
    return target, source


def _build_fallback_target(env: Dict[str, str], cfg: Dict[str, Any], default_provider: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    existing = _extract_existing_fallback(cfg)

    env_model = _canonicalize_model_name(env.get("FALLBACK_MODEL"))
    env_provider = _normalize_provider(env.get("FALLBACK_MODEL_PROVIDER"))

    if not env_model and not existing:
        return {}, {"provider": "none", "model": "none"}

    model = env_model or existing.get("model", "")
    provider = env_provider or existing.get("provider", "")
    if model and not provider:
        provider = _infer_provider_from_model(model) or _normalize_provider(default_provider) or "auto"

    if not model or not provider:
        return {}, {"provider": "none", "model": "none"}

    target = {
        "provider": provider,
        "model": model,
        "base_url": str(env.get("FALLBACK_MODEL_BASE_URL", "") or "").strip(),
        "api_mode": str(env.get("FALLBACK_MODEL_API_MODE", "") or "").strip(),
    }
    source = {
        "provider": "FALLBACK_MODEL_PROVIDER" if env_provider else ("config.fallback_model.provider" if existing else "derived"),
        "model": "FALLBACK_MODEL" if env_model else ("config.fallback_model.model" if existing else "derived"),
    }
    return target, source


def _dict_changed(current: Dict[str, Any], desired: Dict[str, str]) -> bool:
    for key, desired_value in desired.items():
        if not desired_value:
            continue
        current_value = str(current.get(key, "") or "").strip()
        if current_value != desired_value:
            return True
    return False


def _apply_nonempty(dst: Dict[str, Any], src: Dict[str, str]) -> None:
    for key, value in src.items():
        if value:
            dst[key] = value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap model defaults/fallback from profile .env")
    parser.add_argument("--env-file", required=True, help="Path to profile env file")
    parser.add_argument("--config-file", default="", help="Optional explicit config.yaml path")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    env_file = Path(str(args.env_file)).expanduser()
    if not env_file.exists():
        print(json.dumps({"ok": False, "error": f"env file not found: {env_file}"}))
        return 1

    config_file = Path(str(args.config_file)).expanduser() if str(args.config_file).strip() else _infer_config_file(env_file)

    env = _read_env(env_file)
    cfg = _load_config(config_file)

    model_cfg = _extract_model_cfg(cfg)
    before_default = {
        "provider": _normalize_provider(model_cfg.get("provider")),
        "model": _canonicalize_model_name(model_cfg.get("default")),
        "base_url": str(model_cfg.get("base_url", "") or "").strip(),
        "api_mode": str(model_cfg.get("api_mode", "") or "").strip(),
    }
    before_fallback = _extract_existing_fallback(cfg)
    if before_fallback:
        raw_fb = cfg.get("fallback_model") if isinstance(cfg.get("fallback_model"), dict) else {}
        if isinstance(raw_fb, dict):
            before_fallback["base_url"] = str(raw_fb.get("base_url", "") or "").strip()
            before_fallback["api_mode"] = str(raw_fb.get("api_mode", "") or "").strip()

    default_target, default_source = _build_default_target(env, cfg)
    fallback_target, fallback_source = _build_fallback_target(env, cfg, default_target.get("provider", ""))

    changed = False
    model_changed = False
    fallback_changed = False

    next_cfg = dict(cfg)
    next_model_cfg = _extract_model_cfg(next_cfg)
    desired_model_cfg = {
        "default": default_target.get("model", ""),
        "provider": default_target.get("provider", ""),
        "base_url": default_target.get("base_url", ""),
        "api_mode": default_target.get("api_mode", ""),
    }
    if _dict_changed(next_model_cfg, desired_model_cfg):
        _apply_nonempty(next_model_cfg, desired_model_cfg)
        next_cfg["model"] = next_model_cfg
        # Keep root-level provider/base_url aligned when present or explicitly set.
        if default_target.get("provider"):
            next_cfg["provider"] = default_target["provider"]
        if default_target.get("base_url"):
            next_cfg["base_url"] = default_target["base_url"]
        model_changed = True
        changed = True

    if fallback_target:
        current_fb = cfg.get("fallback_model")
        current_fb_dict = current_fb if isinstance(current_fb, dict) else {}
        desired_fb = {
            "provider": fallback_target.get("provider", ""),
            "model": fallback_target.get("model", ""),
            "base_url": fallback_target.get("base_url", ""),
            "api_mode": fallback_target.get("api_mode", ""),
        }
        if _dict_changed(current_fb_dict, desired_fb):
            clean_fb: Dict[str, Any] = {}
            _apply_nonempty(clean_fb, desired_fb)
            next_cfg["fallback_model"] = clean_fb

            existing_fps = next_cfg.get("fallback_providers")
            tail: list[Dict[str, Any]] = []
            if isinstance(existing_fps, list):
                tail = [item for item in existing_fps[1:] if isinstance(item, dict)]
            next_cfg["fallback_providers"] = [dict(clean_fb)] + tail
            fallback_changed = True
            changed = True

    if changed:
        _save_config(config_file, next_cfg)

    payload: Dict[str, Any] = {
        "ok": True,
        "env_file": str(env_file),
        "config_file": str(config_file),
        "changed": changed,
        "model_changed": model_changed,
        "fallback_changed": fallback_changed,
        "effective": {
            "default": {
                "provider": default_target.get("provider", ""),
                "model": default_target.get("model", ""),
                "base_url": default_target.get("base_url", ""),
                "api_mode": default_target.get("api_mode", ""),
            },
            "fallback": {
                "provider": fallback_target.get("provider", ""),
                "model": fallback_target.get("model", ""),
                "base_url": fallback_target.get("base_url", ""),
                "api_mode": fallback_target.get("api_mode", ""),
            },
        },
        "before": {
            "default": before_default,
            "fallback": before_fallback,
        },
        "source": {
            "default": default_source,
            "fallback": fallback_source,
        },
        "warnings": [],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
