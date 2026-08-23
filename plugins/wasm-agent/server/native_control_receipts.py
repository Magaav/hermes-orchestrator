"""Bounded, read-only projections of native-control command receipts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


RECEIPT_SCHEMA = "hermes.wasm_agent.native_control_receipt.v1"
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_id(value: Any, fallback: str = "unknown") -> str:
    cleaned = _SAFE_ID.sub("-", str(value or "").strip()).strip("-._")[:160]
    return cleaned or fallback


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _bounded(value: Any, depth: int = 0) -> Any:
    if depth > 7:
        return "[depth-limit]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, list):
        items = value[-6:] if depth and all(isinstance(item, str) for item in value) else value[:40]
        return [_bounded(item, depth + 1) for item in items]
    if isinstance(value, dict):
        return {str(key)[:120]: _bounded(item, depth + 1) for key, item in list(value.items())[:80]}
    return str(value)[:4000]


def _resolve_record(root: Path, record_id: str) -> Path:
    exact = root / f"{record_id}.json"
    if exact.exists():
        return exact
    needle = exact.name.lower()
    try:
        return next((path for path in root.glob("*.json") if path.name.lower() == needle), exact)
    except OSError:
        return exact


def _latest(root: Path, device_id: str = "") -> dict[str, Any]:
    safe_device = _safe_id(device_id, "")
    candidates = list((root / safe_device).glob("*.json")) if safe_device and (root / safe_device).exists() else []
    if not candidates and root.exists():
        candidates = list(root.glob("*/*.json"))
    if not candidates:
        return {}
    return _read_json(max(candidates, key=lambda item: item.stat().st_mtime))


def latest_result(state_dir: Path, device_id: str = "") -> dict[str, Any]:
    return _latest(Path(state_dir) / "native-control" / "results", device_id)


def latest_command(state_dir: Path, device_id: str = "") -> dict[str, Any]:
    return _latest(Path(state_dir) / "native-control" / "commands", device_id)


def command_receipt(state_dir: Path, device_id: Any, command_id: Any) -> dict[str, Any]:
    """Return a compact receipt without replaying the potentially large command payload."""
    safe_device = _safe_id(device_id)
    safe_command = _safe_id(command_id)
    control_root = Path(state_dir) / "native-control"
    command = _read_json(_resolve_record(control_root / "commands" / safe_device, safe_command))
    record = _read_json(_resolve_record(control_root / "results" / safe_device, safe_command))
    found = bool(command or record)
    status = str(command.get("status") or ("finished" if record else "missing"))
    if not record and isinstance(command.get("result"), dict):
        record = {
            "ok": True,
            "schema": "hermes.wasm_agent.native_control_result.v1",
            "device_id": safe_device,
            "command_id": safe_command,
            "received_at": command.get("finished_at") or "",
            "result": command["result"],
        }
    bounded_record = _bounded(record) if record else None
    return {
        "ok": True,
        "schema": RECEIPT_SCHEMA,
        "found": found,
        "terminal": status in {"finished", "failed", "expired"} and bool(record),
        "device_id": safe_device,
        "command_id": safe_command,
        "status": status,
        "command": {
            "type": command.get("type") or "",
            "created_at": command.get("created_at") or "",
            "delivered_at": command.get("delivered_at") or "",
            "deadline_at": command.get("deadline_at") or "",
            "finished_at": command.get("finished_at") or "",
        } if command else None,
        "record": bounded_record,
    }


def attach_requested_receipt(status: dict[str, Any], state_dir: Path, query: dict[str, list[str]]) -> dict[str, Any]:
    """Attach one exact receipt to the existing native status contract on demand."""
    command_id = str((query.get("command_id") or [""])[0] or "")
    if not command_id:
        return status
    device_id = str((query.get("device_id") or [""])[0] or status.get("deviceId") or "")
    return {**status, "commandReceipt": command_receipt(state_dir, device_id, command_id)}
