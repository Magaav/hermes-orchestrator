from __future__ import annotations

import json
from typing import Any


TRUNCATED_SCHEMA = "hermes.wasm_agent.truncated_json.v1"


def bounded_json_text(value: Any, max_chars: int) -> str:
    limit = max(64, int(max_chars))
    text = json.dumps(value if value is not None else {}, ensure_ascii=True, separators=(",", ":"), default=str)
    if len(text) <= limit:
        return text
    low, high = 0, min(len(text), limit)
    best = ""
    while low <= high:
        size = (low + high) // 2
        marker = json.dumps({
            "schema": TRUNCATED_SCHEMA,
            "truncated": True,
            "original_chars": len(text),
            "preview": text[:size],
        }, ensure_ascii=True, separators=(",", ":"))
        if len(marker) <= limit:
            best = marker
            low = size + 1
        else:
            high = size - 1
    if not best:
        best = json.dumps({"schema": TRUNCATED_SCHEMA, "truncated": True}, separators=(",", ":"))
    return best
