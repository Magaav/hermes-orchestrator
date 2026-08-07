"""Private native-control key resolution and constant-time verification."""

from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Callable


ENV_NAME = "WASM_AGENT_NATIVE_CONTROL_KEY"


def resolve_key(env_file: Path, *, environ: dict[str, str] | None = None) -> str:
    environment = os.environ if environ is None else environ
    direct = str(environment.get(ENV_NAME) or "").strip()
    if direct:
        return direct
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    prefix = f"{ENV_NAME}="
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix):].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.strip()
    return ""


def header_matches(header_value: str, env_file: Path, *, environ: dict[str, str] | None = None) -> bool:
    key = resolve_key(env_file, environ=environ)
    return bool(key) and hmac.compare_digest(key, str(header_value or ""))


def actor(
    header_value: str,
    env_file: Path,
    user: dict | None,
    *,
    is_admin: Callable[[dict | None], bool],
    safe_id: Callable[[str, str], str],
) -> str:
    if is_admin(user):
        label = str(user.get("email") or user.get("id") or "admin").strip() if isinstance(user, dict) else "admin"
        return f"admin:{safe_id(label, 'admin')}"
    if header_matches(header_value, env_file):
        return "control-key"
    return "localhost"
