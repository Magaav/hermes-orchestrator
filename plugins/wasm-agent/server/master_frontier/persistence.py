from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from . import event_anchor_adapter


TRUNCATED_SCHEMA = "hermes.wasm_agent.truncated_json.v1"


def private_state_root(server: Any, fallback: str | Path) -> Path:
    """Resolve optional server state without requiring full HTTP-server fixtures."""
    value = getattr(server, "state_dir", None)
    return Path(value) if value is not None else Path(fallback)


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


def anchor_committed_event(
    *,
    private_state_root: str | Path,
    run: Mapping[str, Any],
    event: Mapping[str, Any],
    load_events: Callable[[], Iterable[dict[str, Any]]],
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Checkpoint a committed event without changing primary run success."""
    try:
        adapter_config = event_anchor_adapter.config(private_state_root, environ=environ)
        if adapter_config["enabled"] is not True:
            return None
        terminal = str(event.get("type") or "") in event_anchor_adapter.TERMINAL_TYPES
        sequence = max(0, int(event.get("seq") or 0))
        interval = max(1, int(adapter_config["interval"]))
        if not terminal and sequence % interval:
            return None
        result = event_anchor_adapter.persist(
            adapter_config=adapter_config,
            user_id=str(run.get("user_id") or ""),
            run_id=str(run.get("run_id") or event.get("run_id") or ""),
            events=load_events(),
            terminal=terminal,
        )
    except Exception as exc:
        result = {
            "schema": event_anchor_adapter.SCHEMA,
            "status": "failed",
            "ok": False,
            "stored": False,
            "code": "event_anchor_hook_failed",
            "error": str(exc)[:300],
            "terminal": str(event.get("type") or "") in event_anchor_adapter.TERMINAL_TYPES,
        }
    return {
        "schema": "hermes.wasm_agent.master_frontier.integrity_proof.v1",
        "status": "verified" if result.get("ok") and result.get("stored") else "unavailable",
        "reason": "" if result.get("ok") and result.get("stored") else str(result.get("code") or result.get("status") or "anchor_unavailable"),
        "anchor": result,
    }
