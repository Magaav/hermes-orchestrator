#!/usr/bin/env python3
"""Bootstrap SST (Speech-to-Text) model/language from profile .env.

Goal:
- Allow SST model and language to be set via NODE_SST_MODEL / NODE_SST_LANGUAGE
  in /local/agents/<name>.env (the node's .env file).
- Write stt.local.model and stt.local.language into the node's config.yaml.
- Keep behavior idempotent and fail-open.

This script is called by prestart_reapply.sh after model_env_bootstrap.py.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict

import yaml


VALID_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Map user-friendly short names to the values that faster-whisper / Groq accept.
# Not exhaustive — only the ones that make sense for local inference.
SHORT_TO_LOCAL_MODEL = {
    "tiny": "tiny",
    "base": "base",
    "small": "small",
    "medium": "medium",
    "large-v2": "large-v2",
    "large-v3": "large-v3",
    "large-v3-turbo": "large-v3-turbo",
}

# Groq/cloud API uses "whisper-*" naming; this maps short names to the
# canonical cloud model name so os.environ["STT_GROQ_MODEL"] can be set.
SHORT_TO_GROQ_MODEL = {
    "tiny": "whisper-large-v3",
    "base": "whisper-large-v3",
    "small": "whisper-large-v3",
    "medium": "whisper-large-v3",
    "large-v2": "whisper-large-v3",
    "large-v3": "whisper-large-v3",
    "large-v3-turbo": "whisper-large-v3-turbo",
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


def _infer_config_file(env_file: Path) -> Path:
    """Infer config.yaml path from an env file path.

    /x/.hermes/.env -> /x/.hermes/config.yaml
    /local/agents/<name>.env -> /local/agents/<name>/.hermes/config.yaml
    """
    if env_file.name == ".env" and env_file.parent.name == ".hermes":
        return env_file.parent / "config.yaml"
    if env_file.suffix == ".env":
        clone_name = env_file.stem
        return env_file.parent / clone_name / ".hermes" / "config.yaml"
    return env_file.parent / "config.yaml"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap SST model/language from profile .env"
    )
    parser.add_argument("--env-file", required=True, help="Path to profile env file")
    parser.add_argument(
        "--config-file",
        default="",
        help="Optional explicit config.yaml path",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    env_file = Path(str(args.env_file)).expanduser()
    if not env_file.exists():
        print(
            json.dumps({"ok": False, "error": f"env file not found: {env_file}"})
        )
        return 1

    config_file = (
        Path(str(args.config_file)).expanduser()
        if str(args.config_file).strip()
        else _infer_config_file(env_file)
    )

    env = _read_env(env_file)
    cfg = _load_config(config_file)

    # Initialise stt.local if missing
    stt_cfg: Dict[str, Any] = cfg.get("stt", {})
    if not isinstance(stt_cfg, dict):
        stt_cfg = {}
    local_cfg: Dict[str, Any] = stt_cfg.get("local", {})
    if not isinstance(local_cfg, dict):
        local_cfg = {}

    changed = False

    # --- NODE_SST_MODEL ---
    sst_model_short = env.get("NODE_SST_MODEL", "").strip()
    if sst_model_short:
        local_model = SHORT_TO_LOCAL_MODEL.get(sst_model_short, sst_model_short)
        if local_cfg.get("model") != local_model:
            local_cfg["model"] = local_model
            changed = True

        # Also set STT_GROQ_MODEL in .env so transcription_tools.py Groq path picks it up
        groq_model = SHORT_TO_GROQ_MODEL.get(sst_model_short, f"whisper-{sst_model_short}")
        _ensure_env_var(env_file, "STT_GROQ_MODEL", groq_model)

    # --- NODE_SST_LANGUAGE ---
    sst_language = env.get("NODE_SST_LANGUAGE", "").strip()
    if sst_language:
        if local_cfg.get("language") != sst_language:
            local_cfg["language"] = sst_language
            changed = True
        # Also keep HERMES_LOCAL_STT_COMMAND language in sync if it was set
        # (transcription_tools.py checks LOCAL_STT_LANGUAGE_ENV for CLI whisper path)

    # Persist stt.local back into config.yaml
    if changed:
        stt_cfg["local"] = local_cfg
        cfg["stt"] = stt_cfg
        _save_config(config_file, cfg)

    # Build effective result
    effective_local = cfg.get("stt", {}).get("local", {}) if changed else local_cfg

    payload: Dict[str, Any] = {
        "ok": True,
        "env_file": str(env_file),
        "config_file": str(config_file),
        "changed": changed,
        "effective": {
            "model": effective_local.get("model", ""),
            "language": effective_local.get("language", ""),
        },
        "source": {
            "model": "NODE_SST_MODEL" if sst_model_short else "config.yaml",
            "language": "NODE_SST_LANGUAGE" if sst_language else "config.yaml",
        },
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _ensure_env_var(env_file: Path, key: str, value: str) -> bool:
    """Add or update a KEY=VALUE line in the .env file. Returns True if changed."""
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    updated = False
    new_lines = []
    for line in lines:
        if pattern.match(line):
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={value}")
        updated = True
    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return updated


if __name__ == "__main__":
    raise SystemExit(main())
