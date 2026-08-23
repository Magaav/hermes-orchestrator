"""Atomic, bounded persistence for Master:frontier Codex thread continuity."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


SCHEMA = "hermes.wasm_agent.codex_conversation_state.v1"
_LOCK = threading.Lock()
_MAX_RECORDS = 256


def state_root() -> Path:
    configured = os.environ.get("HERMES_WASM_AGENT_STATE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / "plugins" / "wasm-agent" / "state").resolve()


def index_path() -> Path:
    configured = os.environ.get("MF5_CODEX_THREAD_INDEX", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return state_root() / "master-frontier" / "codex-conversations.json"


def decision_cwd() -> Path:
    path = state_root() / "master-frontier" / "codex-decision-head"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"schema": SCHEMA, "records": {}}
    records = value.get("records") if isinstance(value, dict) else None
    return {"schema": SCHEMA, "records": records if isinstance(records, dict) else {}}


def load(key: str) -> dict[str, Any]:
    if not key:
        return {}
    with _LOCK:
        record = _read(index_path())["records"].get(key)
    return dict(record) if isinstance(record, dict) else {}


def save(key: str, record: dict[str, Any]) -> None:
    if not key:
        return
    path = index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        value = _read(path)
        records = value["records"]
        bounded = {
            "thread_id": str(record.get("thread_id") or "")[:128],
            "tool_digest": str(record.get("tool_digest") or "")[:64],
            "model": str(record.get("model") or "")[:80],
            "turn_count": max(0, int(record.get("turn_count") or 0)),
            "compaction_generation": max(0, int(record.get("compaction_generation") or 0)),
            "compaction_status": str(record.get("compaction_status") or "none")[:32],
            "fork_reason": str(record.get("fork_reason") or "")[:80],
            "updated_at": int(time.time()),
        }
        records[key] = bounded
        if len(records) > _MAX_RECORDS:
            ordered = sorted(records, key=lambda item: int((records[item] or {}).get("updated_at") or 0))
            for stale in ordered[:len(records) - _MAX_RECORDS]:
                records.pop(stale, None)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)
