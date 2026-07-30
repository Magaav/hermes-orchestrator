#!/usr/bin/env python3
"""Shared Codex runtime discovery for Visão Studio subprocesses."""

from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


class CodexCredentialsError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodexCredentials:
    access_token: str
    account_id: str


def _base64url_json(segment: str) -> dict[str, object]:
    try:
        padding = "=" * (-len(segment) % 4)
        value = json.loads(base64.urlsafe_b64decode(segment + padding))
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        return {}


def codex_credentials(codex_home: Path | None = None) -> CodexCredentials:
    home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    try:
        payload = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CodexCredentialsError("Codex credentials missing") from error
    tokens = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else {}
    access_token = str(tokens.get("access_token") or payload.get("access_token") or "").strip()
    if not access_token:
        raise CodexCredentialsError("Codex credentials missing")
    account_id = str(tokens.get("account_id") or payload.get("account_id") or "").strip()
    parts = access_token.split(".")
    if not account_id and len(parts) == 3:
        claims = _base64url_json(parts[1])
        account_id = str(
            claims.get("https://api.openai.com/auth.chatgpt_account_id")
            or claims.get("chatgpt_account_id")
            or ""
        )
    return CodexCredentials(access_token=access_token, account_id=account_id)


def codex_environment() -> tuple[str, dict[str, str]]:
    os.umask(0o077)
    environment = os.environ.copy()
    for key in ("STUDIO_RUNTIME_ROOT", "HOME", "CODEX_HOME"):
        value = environment.get(key)
        if value:
            path = Path(value)
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)

    binary = environment.get("WASM_AGENT_CODEX_BIN") or shutil.which("codex")
    if not binary:
        root = Path(environment.get("STUDIO_CODEX_SEARCH_ROOT", "/home/ubuntu/.vscode-server/extensions"))
        candidates = sorted(root.glob("openai.chatgpt-*/bin/linux-*/codex"), reverse=True)
        if candidates:
            binary = str(candidates[0])
    if not binary:
        raise FileNotFoundError("Codex executable not found")
    environment["WASM_AGENT_CODEX_BIN"] = binary
    return binary, environment
