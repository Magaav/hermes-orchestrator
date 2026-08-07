"""Compact unified registry for PWA and native WASM Agent clients."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from typing import Any


SCHEMA = "hermes.wasm_agent.live_clients.v1"
CLIENT_SCHEMA = "hermes.wasm_agent.live_client.v1"
ACTIVE_TTL_SEC = 75
RUNTIME_TYPES = {"pwa", "electron", "android-kotlin"}
OBSERVABILITY_COMMAND_TYPES = frozenset({"observability_enable", "observability_collect", "observability_disable", "observability_status"})
OBSERVABILITY_OPERATOR_COMMANDS = {command: command for command in OBSERVABILITY_COMMAND_TYPES}
def _clean(value: Any, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def _safe_id(value: Any) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "-", _clean(value, 120)).strip("-.")
    return clean or "unknown"


def _runtime_type(value: Any, device_id: str = "") -> str:
    declared = _clean(value, 40).lower()
    aliases = {"android": "android-kotlin", "kotlin": "android-kotlin", "windows": "electron", "web": "pwa"}
    declared = aliases.get(declared, declared)
    if declared in RUNTIME_TYPES:
        return declared
    lowered = device_id.lower()
    if lowered.startswith("android"):
        return "android-kotlin"
    if lowered.startswith("win"):
        return "electron"
    return "pwa"


def _capabilities(value: Any, runtime_type: str) -> list[str]:
    del runtime_type
    items = value if isinstance(value, list) else str(value or "").split(",")
    cleaned = sorted({_clean(item, 80) for item in items if _clean(item, 80)})[:32]
    return cleaned


def _parse_epoch(value: Any) -> float:
    text = _clean(value, 60)
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def normalize_client(payload: dict[str, Any], *, now_epoch: float | None = None) -> dict[str, Any]:
    now_epoch = time.time() if now_epoch is None else now_epoch
    device_id = _safe_id(payload.get("client_id") or payload.get("device_id"))
    runtime_type = _runtime_type(payload.get("runtime_type") or payload.get("runtime"), device_id)
    seen_at = _clean(payload.get("last_seen_at") or payload.get("received_at"), 60)
    age_sec = max(0, int(now_epoch - _parse_epoch(seen_at))) if seen_at else 2**31 - 1
    return {
        "schema": CLIENT_SCHEMA,
        "client_id": device_id,
        "device_id": device_id,
        "runtime_type": runtime_type,
        "platform": _clean(payload.get("platform"), 40),
        "build_id": _clean(payload.get("build_id"), 120),
        "app_version": _clean(payload.get("app_version"), 40),
        "route": _clean(payload.get("route"), 600),
        "title": _clean(payload.get("title"), 160),
        "visibility": _clean(payload.get("visibility"), 20),
        "capabilities": _capabilities(payload.get("capabilities"), runtime_type),
        "last_seen_at": seen_at,
        "age_sec": age_sec,
        "live": age_sec <= ACTIVE_TTL_SEC,
        "transport": _clean(payload.get("transport") or "poll", 40),
    }


def save_client(root: Path, payload: dict[str, Any], *, now_epoch: float | None = None) -> dict[str, Any]:
    client = normalize_client(payload, now_epoch=now_epoch)
    target = root / "live-clients" / f"{client['client_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(client, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return client


def list_clients(root: Path, *, native_root: Path | None = None, now_epoch: float | None = None) -> dict[str, Any]:
    now_epoch = time.time() if now_epoch is None else now_epoch
    merged: dict[str, dict[str, Any]] = {}
    paths = list((root / "live-clients").glob("*.json"))
    if native_root is not None:
        paths += list((native_root / "heartbeats").glob("*.json"))
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        client = normalize_client(raw, now_epoch=now_epoch)
        existing = merged.get(client["client_id"])
        if existing is None or client["last_seen_at"] > existing["last_seen_at"]:
            merged[client["client_id"]] = client
    clients = sorted(merged.values(), key=lambda item: item["last_seen_at"], reverse=True)[:160]
    return {
        "ok": True,
        "schema": SCHEMA,
        "clients": clients,
        "count": len(clients),
        "live_count": sum(1 for item in clients if item["live"]),
        "runtime_counts": {kind: sum(1 for item in clients if item["runtime_type"] == kind and item["live"]) for kind in sorted(RUNTIME_TYPES)},
    }
