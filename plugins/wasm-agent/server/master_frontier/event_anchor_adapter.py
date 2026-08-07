"""Feature-flagged adapter from committed run events to external anchors."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import event_anchor_store, event_integrity


SCHEMA = "hermes.wasm_agent.master_frontier.event_anchor_adapter.v1"
FLAG = "WASM_AGENT_EVENT_ANCHORS"
PATH_ENV = "WASM_AGENT_EVENT_ANCHOR_DB"
INTERVAL_ENV = "WASM_AGENT_EVENT_ANCHOR_INTERVAL"
DEFAULT_INTERVAL = 16
TERMINAL_TYPES = frozenset({"run.final", "run.error", "run.cancelled"})


def _enabled(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def config(
    private_state_root: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    source = environ if environ is not None else os.environ
    enabled = _enabled(source.get(FLAG))
    raw_path = str(source.get(PATH_ENV) or "").strip()
    path = Path(raw_path) if raw_path else event_anchor_store.default_path(private_state_root)
    if not path.is_absolute():
        path = Path(private_state_root) / path
    try:
        interval = int(source.get(INTERVAL_ENV) or DEFAULT_INTERVAL)
    except (TypeError, ValueError):
        interval = DEFAULT_INTERVAL
    interval = max(1, min(interval, event_integrity.MAX_EVENTS))
    return {
        "schema": SCHEMA,
        "enabled": enabled,
        "path": path,
        "interval": interval,
    }


def _terminal(events: list[dict[str, Any]], terminal: bool | None) -> bool:
    if terminal is not None:
        return bool(terminal)
    return bool(events and str(events[-1].get("type") or "") in TERMINAL_TYPES)


def persist(
    *,
    adapter_config: dict[str, Any],
    user_id: str,
    run_id: str,
    events: Iterable[dict[str, Any]],
    terminal: bool | None = None,
    withheld_sequences: Iterable[int] = (),
    store: event_anchor_store.EventAnchorStore | None = None,
    created_at: int | None = None,
) -> dict[str, Any]:
    if adapter_config.get("enabled") is not True:
        return {
            "schema": SCHEMA,
            "status": "disabled",
            "ok": True,
            "stored": False,
        }
    rows = list(events)
    is_terminal = _terminal(rows, terminal)
    interval = max(1, int(adapter_config.get("interval") or DEFAULT_INTERVAL))
    if not rows:
        return {
            "schema": SCHEMA,
            "status": "skipped",
            "ok": True,
            "stored": False,
            "reason": "no_events",
        }
    if not is_terminal and len(rows) % interval:
        return {
            "schema": SCHEMA,
            "status": "skipped",
            "ok": True,
            "stored": False,
            "events": len(rows),
            "next_checkpoint": ((len(rows) // interval) + 1) * interval,
        }
    try:
        ledger = event_integrity.seal(
            run_id,
            rows,
            withheld_sequences=withheld_sequences,
        )
        trusted_anchor = event_integrity.anchor(ledger)
        target = store or event_anchor_store.EventAnchorStore(adapter_config["path"])
        stored = target.append(
            user_id=user_id,
            run_id=run_id,
            anchor=trusted_anchor,
            final=is_terminal,
            created_at=created_at,
        )
    except (event_integrity.EventIntegrityError, event_anchor_store.EventAnchorStoreError, OSError) as exc:
        return {
            "schema": SCHEMA,
            "status": "failed",
            "ok": False,
            "stored": False,
            "code": getattr(exc, "code", "event_anchor_store_failed"),
            "error": str(exc)[:300],
            "events": len(rows),
            "terminal": is_terminal,
        }
    return {
        "schema": SCHEMA,
        "status": "stored",
        "ok": True,
        "stored": True,
        "events": len(rows),
        "terminal": is_terminal,
        "checkpoint": stored["checkpoint"],
        "declared": stored["declared"],
        "record_digest": stored["record_digest"],
        "idempotent": stored["idempotent"],
    }
