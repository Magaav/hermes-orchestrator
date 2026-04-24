"""Argument parsing for `/acl`."""

from __future__ import annotations

import shlex
from typing import Dict, Tuple


def parse_acl_args(raw_args: str) -> Tuple[str, Dict[str, str]]:
    tokens = shlex.split(str(raw_args or "").strip())
    if not tokens:
        return "", {}

    subcommand = str(tokens[0] or "").strip().lower()
    values: Dict[str, str] = {}
    for token in tokens[1:]:
        piece = str(token or "").strip()
        if not piece:
            continue
        if ":" in piece:
            key, value = piece.split(":", 1)
        elif "=" in piece:
            key, value = piece.split("=", 1)
        else:
            continue
        values[str(key or "").strip().lower().replace("-", "_")] = str(value or "").strip()
    return subcommand, values
