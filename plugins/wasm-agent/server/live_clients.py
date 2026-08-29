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
ACTIVE_SURFACE_MANIFEST = "active-surface-v1"
SPACE_CATALOG_MANIFEST = "space-catalog-v1"
ACTIVE_TTL_SEC = 75
RUNTIME_TYPES = {"pwa", "electron", "android-kotlin"}
OBSERVABILITY_COMMAND_TYPES = frozenset({"observability_enable", "observability_collect", "observability_disable", "observability_status", "runtime_diagnose"})
OBSERVABILITY_OPERATOR_COMMANDS = {command: command for command in OBSERVABILITY_COMMAND_TYPES}
CLIENT_SURFACE_COMMANDS = {command: command for command in ("open_widget", "space_open")}
SPACE_DISCOVERY_COMMANDS = {"space_catalog": "space_catalog"}
RUNTIME_CONTROL_COMMANDS = {"runtime_refresh": "runtime_refresh"}
AGENT_CONTROL_COMMANDS = {"agent_prompt_submit": "agent_prompt_submit", "agent_session_new": "agent_session_new"}
WINDOWS_FULL_POWER_COMMANDS = {
    "windows_shell_execute_unrestricted": "windows_shell_execute_unrestricted",
    "show_companion_overlay": "show_companion_overlay",
    "run_notepad_uia_canary": "run_notepad_uia_canary",
    "windows_desktop_describe": "windows_desktop_describe",
    "windows_desktop_inspect": "windows_desktop_inspect",
    "windows_desktop_act": "windows_desktop_act",
    "windows_desktop_prove": "windows_desktop_prove",
}
CLIENT_SURFACE_COMMAND_TYPES = frozenset(CLIENT_SURFACE_COMMANDS)
CLIENT_COMMAND_TYPES = OBSERVABILITY_COMMAND_TYPES | CLIENT_SURFACE_COMMAND_TYPES | frozenset(SPACE_DISCOVERY_COMMANDS) | frozenset(RUNTIME_CONTROL_COMMANDS) | frozenset(AGENT_CONTROL_COMMANDS) | frozenset(WINDOWS_FULL_POWER_COMMANDS)
CLIENT_OPERATOR_COMMANDS = {**OBSERVABILITY_OPERATOR_COMMANDS, **SPACE_DISCOVERY_COMMANDS, **RUNTIME_CONTROL_COMMANDS, **AGENT_CONTROL_COMMANDS, **CLIENT_SURFACE_COMMANDS, **WINDOWS_FULL_POWER_COMMANDS}
STRICT_CONTROL_COMMAND_TYPES = frozenset(WINDOWS_FULL_POWER_COMMANDS)

WINDOWS_DESKTOP_ACTIONS = frozenset({"focus", "invoke", "click", "set_value", "toggle", "select", "expand", "collapse"})
WINDOWS_DESKTOP_PROPERTIES = frozenset({"name", "value", "toggle_state", "enabled", "offscreen", "selected", "expanded"})


def _windows_desktop_expectation(value: Any, *, required: bool = False) -> dict[str, Any] | None:
    if value is None and not required:
        return None
    if not isinstance(value, dict) or set(value) != {"property", "equals"}:
        raise ValueError("Windows desktop expectation requires exactly property and equals")
    prop = str(value.get("property") or "")
    if prop not in WINDOWS_DESKTOP_PROPERTIES or not isinstance(value.get("equals"), (str, int, float, bool)):
        raise ValueError("Windows desktop expectation property or scalar equals is invalid")
    return {"property": prop, "equals": value["equals"]}


def _windows_desktop_target(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not set(value) <= {"hwnd", "process_id", "title_contains"}:
        raise ValueError("Windows desktop target fields are invalid")
    target: dict[str, Any] = {}
    if value.get("hwnd") not in (None, ""):
        hwnd = str(value["hwnd"])
        if re.fullmatch(r"(?:0x[0-9A-Fa-f]{1,16}|[0-9]{1,20})", hwnd) is None:
            raise ValueError("Windows desktop hwnd is invalid")
        target["hwnd"] = hwnd
    if value.get("process_id") not in (None, ""):
        if type(value["process_id"]) is not int or not 1 <= value["process_id"] <= 2_147_483_647:
            raise ValueError("Windows desktop process_id is invalid")
        target["process_id"] = value["process_id"]
    if value.get("title_contains") not in (None, ""):
        title = str(value["title_contains"]).strip()
        if not title or len(title) > 240:
            raise ValueError("Windows desktop title_contains is invalid")
        target["title_contains"] = title
    return target


def _normalize_windows_desktop_payload(command_type: str, value: dict[str, Any]) -> dict[str, Any]:
    if command_type == "windows_desktop_describe":
        if value:
            raise ValueError("windows_desktop_describe accepts no payload")
        return {}
    timeout_ms = value.get("timeout_ms", 15000)
    if type(timeout_ms) is not int or not 3000 <= timeout_ms <= 30000:
        raise ValueError("Windows desktop timeout_ms must be an integer from 3000 through 30000")
    if command_type == "windows_desktop_inspect":
        if not set(value) <= {"target", "max_elements", "max_depth", "include_values", "timeout_ms"}:
            raise ValueError("windows_desktop_inspect fields are invalid")
        max_elements = value.get("max_elements", 80)
        max_depth = value.get("max_depth", 12)
        if type(max_elements) is not int or not 1 <= max_elements <= 200 or type(max_depth) is not int or not 1 <= max_depth <= 32:
            raise ValueError("Windows desktop inspection bounds are invalid")
        include_values = value.get("include_values", False)
        if type(include_values) is not bool:
            raise ValueError("Windows desktop include_values must be boolean")
        return {"target": _windows_desktop_target(value.get("target")), "max_elements": max_elements, "max_depth": max_depth, "include_values": include_values, "timeout_ms": timeout_ms}
    allowed = {"snapshot_id", "ref", "action", "value", "expect", "timeout_ms"}
    if not set(value) <= allowed:
        raise ValueError("Windows desktop action fields are invalid")
    snapshot_id = str(value.get("snapshot_id") or "")
    ref = str(value.get("ref") or "")
    if re.fullmatch(r"s-[a-f0-9]{16}", snapshot_id) is None or re.fullmatch(r"e[0-9]{1,3}", ref) is None:
        raise ValueError("Windows desktop snapshot reference is invalid")
    if command_type == "windows_desktop_prove":
        return {"snapshot_id": snapshot_id, "ref": ref, "expect": _windows_desktop_expectation(value.get("expect"), required=True), "timeout_ms": timeout_ms}
    action = str(value.get("action") or "")
    if action not in WINDOWS_DESKTOP_ACTIONS:
        raise ValueError("Windows desktop action is invalid")
    text = str(value.get("value") or "")
    if len(text) > 4_096:
        raise ValueError("Windows desktop action value exceeds 4096 characters")
    expectation_value = (value.get("expect") or {}).get("equals") if isinstance(value.get("expect"), dict) else None
    if isinstance(expectation_value, str) and len(expectation_value) > 4_096:
        raise ValueError("Windows desktop expectation exceeds 4096 characters")
    result: dict[str, Any] = {"snapshot_id": snapshot_id, "ref": ref, "action": action, "timeout_ms": timeout_ms}
    if action == "set_value" or "value" in value:
        result["value"] = text
    expectation = _windows_desktop_expectation(value.get("expect"))
    if expectation is not None:
        result["expect"] = expectation
    return result


def normalize_control_payload(command_type: str, payload: Any, *, command_id: str = "") -> dict[str, Any]:
    """Validate client controls once, before any renderer receives them."""
    value = payload if isinstance(payload, dict) else {}
    if command_type == "runtime_diagnose":
        if not set(value) <= {"lease_ms"} or type(value.get("lease_ms", 30000)) is not int or not 5000 <= value.get("lease_ms", 30000) <= 120000:
            raise ValueError("runtime_diagnose lease_ms must be an integer from 5000 through 120000")
        return {"lease_ms": value.get("lease_ms", 30000)}
    if command_type == "runtime_refresh":
        if value:
            raise ValueError("runtime_refresh accepts no payload")
        return {}
    if command_type == "agent_session_new":
        if value:
            raise ValueError("agent_session_new accepts no payload")
        return {}
    if command_type == "agent_prompt_submit":
        message = str(value.get("message") or "").strip()
        if set(value) != {"message"} or not message or len(message) > 4_096:
            raise ValueError("agent_prompt_submit requires exactly one non-empty message of at most 4096 characters")
        return {"message": message}
    if command_type == "windows_shell_execute_unrestricted":
        allowed = {"command", "shell", "cwd", "environment", "timeout_ms"}
        if not set(value) <= allowed or not isinstance(value.get("command"), str) or not value["command"].strip():
            raise ValueError("windows_shell_execute_unrestricted requires command and only declared execution fields")
        if len(value["command"].encode("utf-8")) > 1_048_576:
            raise ValueError("Windows command exceeds the 1048576-byte transport limit")
        shell = str(value.get("shell") or "powershell").lower()
        if shell not in {"powershell", "cmd"}:
            raise ValueError("Windows shell must be powershell or cmd")
        environment = value.get("environment") or {}
        if not isinstance(environment, dict) or len(environment) > 128:
            raise ValueError("Windows environment must be an object with at most 128 entries")
        timeout_ms = value.get("timeout_ms", 60000)
        if type(timeout_ms) is not int or not 1000 <= timeout_ms <= 240000:
            raise ValueError("Windows timeout_ms must be an integer from 1000 through 240000")
        return {"command": value["command"], "shell": shell, "cwd": str(value.get("cwd") or ""), "environment": {str(k): str(v) for k, v in environment.items()}, "timeout_ms": timeout_ms}
    if command_type == "show_companion_overlay":
        if value:
            raise ValueError("show_companion_overlay accepts no payload")
        return {}
    if command_type == "run_notepad_uia_canary":
        allowed = {"canary", "timeout_ms"}
        canary = str(value.get("canary") or "").strip()
        timeout_ms = value.get("timeout_ms", 30000)
        if not set(value) <= allowed or not canary or len(canary) > 240 or re.fullmatch(r"[A-Za-z0-9 ._:-]+", canary) is None:
            raise ValueError("run_notepad_uia_canary requires a safe ASCII canary of at most 240 characters")
        if type(timeout_ms) is not int or not 5000 <= timeout_ms <= 60000:
            raise ValueError("Notepad canary timeout_ms must be an integer from 5000 through 60000")
        return {"canary": canary, "timeout_ms": timeout_ms}
    if command_type in {"windows_desktop_describe", "windows_desktop_inspect", "windows_desktop_act", "windows_desktop_prove"}:
        return _normalize_windows_desktop_payload(command_type, value)
    return value


def operator_control_payload(command_type: str, payload: Any, metadata: dict[str, Any]) -> dict[str, Any]:
    """Keep strict renderer payloads free of audit metadata carried at command level."""
    value = payload if isinstance(payload, dict) else {}
    return value if command_type in STRICT_CONTROL_COMMAND_TYPES else {**value, **metadata}


def _clean(value: Any, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def _safe_id(value: Any) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "-", _clean(value, 120)).strip("-.").lower()
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


def _widget_ids(value: Any) -> list[str]:
    items = value if isinstance(value, list) else str(value or "").split(",")
    cleaned = {
        re.sub(r"[^a-zA-Z0-9._-]+", "-", _clean(item, 80)).strip("-.")
        for item in items if _clean(item, 80)
    }
    return sorted(item for item in cleaned if item)[:32]


def heartbeat_from_query(
    query: dict[str, list[str]], *, native_runtime: str = "", remote_addr: str = "",
    received_at: str = "",
) -> dict[str, Any]:
    """Own the compact renderer heartbeat contract outside the HTTP monolith."""
    first = lambda name, default="": str((query.get(name) or [default])[0])
    device_id = _safe_id(first("device_id", "unknown"))
    runtime_type = _runtime_type(first("runtime_type", native_runtime), device_id)
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.native_control_heartbeat.v1",
        "device_id": device_id,
        "build_id": _clean(first("build_id"), 120),
        "route": _clean(first("route"), 600),
        "runtime_type": runtime_type,
        "platform": _clean(first("platform"), 40),
        "app_version": _clean(first("app_version"), 40),
        "title": _clean(first("title"), 160),
        "visibility": _clean(first("visibility"), 20),
        "space_id": _clean(first("space_id"), 120),
        "space_name": _clean(first("space_name"), 160),
        "widget_manifest": _clean(first("widget_manifest"), 40),
        "widget_ids": _widget_ids(first("widget_ids")),
        "capabilities": _capabilities(first("capabilities"), runtime_type),
        "remote_addr": _clean(remote_addr, 120),
        "received_at": _clean(received_at, 60),
    }


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
        "space_id": _clean(payload.get("space_id"), 120),
        "space_name": _clean(payload.get("space_name"), 160),
        "widget_manifest": _clean(payload.get("widget_manifest"), 40),
        "widget_ids": _widget_ids(payload.get("widget_ids")),
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


def apply_command_result_surface(
    root: Path, device_id: Any, command_type: Any, result: Any, *, received_at: Any,
) -> dict[str, Any] | None:
    """Advance cached active-surface state from one proved space transition receipt."""
    if str(command_type or "") != "space_open" or not isinstance(result, dict) or result.get("ok") is not True:
        return None
    surface = result.get("surface") if isinstance(result.get("surface"), dict) else {}
    if surface.get("manifest") != ACTIVE_SURFACE_MANIFEST:
        return None
    space_id = _clean(surface.get("space_id"), 120)
    result_space_id = _clean(result.get("space_id"), 120)
    if not space_id or not result_space_id or space_id != result_space_id:
        return None
    safe_device = _safe_id(device_id)
    target = Path(root) / "live-clients" / f"{safe_device}.json"
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(existing, dict):
        return None
    timestamp = _clean(received_at, 60)
    return save_client(Path(root), {
        **existing,
        "device_id": safe_device,
        "space_id": space_id,
        "space_name": _clean(surface.get("space_name") or result.get("space_name"), 160),
        "widget_manifest": ACTIVE_SURFACE_MANIFEST,
        "widget_ids": _widget_ids(surface.get("widget_ids")),
        "received_at": timestamp,
        "last_seen_at": timestamp,
    })


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
