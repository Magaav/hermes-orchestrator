from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from .settings import GatewaySettings


def _parse_iso(ts: str) -> datetime | None:
    raw = str(ts or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def activity_log_path(node: str, settings: GatewaySettings) -> Path:
    return settings.node_activity_root / f"{node}.jsonl"


def _tail_lines(path: Path, limit: int) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    max_lines = max(1, int(limit))
    buffer: list[str] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            buffer.append(line.rstrip("\n"))
            if len(buffer) > max_lines:
                buffer = buffer[-max_lines:]
    return buffer


def _tail_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in _tail_lines(path, max(1, limit) * 4):
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records[-max(1, limit) :]


def read_activity_entries(node: str, settings: GatewaySettings, *, limit: int = 40) -> list[dict[str, Any]]:
    path = activity_log_path(node, settings)
    entries = _tail_jsonl(path, limit)
    entries.sort(key=lambda item: str(item.get("ts") or ""))
    return entries


def guard_paths(settings: GatewaySettings) -> dict[str, str]:
    return {
        "root": str(settings.guard_logs_root),
        "runs": str(settings.guard_logs_root / "runs.jsonl"),
        "summary_log": str(settings.guard_logs_root / "summary.log"),
        "state": str(settings.guard_logs_root / "state.json"),
    }


def _default_guard_status(settings: GatewaySettings) -> dict[str, Any]:
    return {
        "daemon_status": "unknown",
        "effective_status": "unknown",
        "updated_at": "",
        "summary": {
            "total_nodes": 0,
            "healthy_nodes": 0,
            "warned_nodes": 0,
            "remediated_nodes": 0,
            "cooldown_nodes": 0,
            "retry_exhausted_nodes": 0,
        },
        "config": {},
        "nodes": {},
        "paths": guard_paths(settings),
    }


def read_guard_status(settings: GatewaySettings) -> dict[str, Any]:
    state_path = settings.guard_logs_root / "state.json"
    if not state_path.exists() or not state_path.is_file():
        return _default_guard_status(settings)

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return _default_guard_status(settings)

    if not isinstance(payload, dict):
        return _default_guard_status(settings)

    status = _default_guard_status(settings)
    status.update(payload)
    status["paths"] = guard_paths(settings)

    updated_at = _parse_iso(str(status.get("updated_at") or ""))
    config = status.get("config") if isinstance(status.get("config"), dict) else {}
    poll_interval_sec = float(config.get("poll_interval_sec") or 0.0)
    effective_status = str(status.get("daemon_status") or "unknown")
    if updated_at and poll_interval_sec > 0:
        age_sec = max(0.0, (datetime.now(timezone.utc) - updated_at).total_seconds())
        if age_sec > max(15.0, poll_interval_sec * 2.5):
            effective_status = "stale"
    status["effective_status"] = effective_status
    if not isinstance(status.get("summary"), dict):
        status["summary"] = _default_guard_status(settings)["summary"]
    if not isinstance(status.get("nodes"), dict):
        status["nodes"] = {}
    return status


def read_guard_node_detail(node: str, settings: GatewaySettings, *, limit: int = 12) -> dict[str, Any]:
    status = read_guard_status(settings)
    runs_path = settings.guard_logs_root / "runs.jsonl"
    records = [
        record
        for record in _tail_jsonl(runs_path, max(20, limit * 8))
        if str(record.get("node") or "") == node
    ]
    records = records[-max(1, limit) :]
    records.sort(key=lambda item: str(item.get("ts") or ""))

    return {
        "node": node,
        "summary": status.get("nodes", {}).get(node, {}),
        "records": records,
        "paths": guard_paths(settings),
    }
