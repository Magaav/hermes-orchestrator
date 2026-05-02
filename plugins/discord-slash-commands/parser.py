"""Argument parsing for `/acl`."""

from __future__ import annotations

import shlex
from typing import Dict, Tuple


def _split_acl_token(piece: str) -> tuple[str, str] | tuple[None, None]:
    text = str(piece or "").strip()
    if not text:
        return None, None
    if ":" in text:
        key, value = text.split(":", 1)
    elif "=" in text:
        key, value = text.split("=", 1)
    else:
        return None, None
    return str(key or "").strip(), str(value or "").strip()


def parse_acl_args(raw_args: str) -> Tuple[str, Dict[str, str]]:
    tokens = shlex.split(str(raw_args or "").strip())
    if not tokens:
        return "", {}

    values: Dict[str, str] = {}
    first = str(tokens[0] or "").strip()
    subcommand = first.lower()
    start_index = 1

    first_key, first_value = _split_acl_token(first)
    if first_key is not None:
        normalized_first_key = str(first_key or "").strip().lower().replace("-", "_")
        if normalized_first_key in {"command", "cmd"}:
            subcommand = "command"
            values["command"] = first_value
            start_index = 1
        elif normalized_first_key in {"channel", "channel_id"}:
            subcommand = "channel"
            values["channel"] = first_value
            start_index = 1

    for token in tokens[start_index:]:
        piece = str(token or "").strip()
        if not piece:
            continue
        key, value = _split_acl_token(piece)
        if key is None:
            continue
        values[str(key or "").strip().lower().replace("-", "_")] = str(value or "").strip()
    return subcommand, values
