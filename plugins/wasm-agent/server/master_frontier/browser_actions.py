"""Bounded model-facing browser actions over an explicitly authorized local CDP bridge."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


BRIDGE = Path(__file__).with_name("browser_cdp_bridge.cjs")
OPERATIONS = frozenset({"snapshot", "navigate", "click", "type", "key"})


def execute(arguments: dict[str, Any], route: dict[str, Any] | None = None) -> dict[str, Any]:
    operation = str(arguments.get("operation") or "snapshot").strip().lower()
    if operation not in OPERATIONS:
        return {"ok": False, "code": "browser_operation_unsupported", "summary": "Unsupported browser operation."}
    payload: dict[str, Any] = {"operation": operation}
    route_target = str((route or {}).get("browser_entry_url") or "").strip()
    if route_target:
        target = urlparse(route_target)
        if target.scheme in {"http", "https"} and target.netloc:
            payload["target_url"] = route_target[:2000]
    declared = {str(item or "").strip().lower() for item in ((route or {}).get("caps") or [])}
    if operation != "snapshot" and "browser.control" not in declared:
        return {"ok": False, "code": "browser_control_denied", "summary": "The route grants browser inspection but not browser control."}
    if operation == "navigate":
        url = str(arguments.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {"ok": False, "code": "browser_url_invalid", "summary": "Browser navigation requires an HTTP(S) URL."}
        payload["url"] = url[:2000]
    if operation in {"click", "type", "key"}:
        try:
            ref = int(arguments.get("ref") or 0)
        except (TypeError, ValueError):
            ref = 0
        if operation != "key" and not 1 <= ref <= 160:
            return {"ok": False, "code": "browser_ref_invalid", "summary": "Browser action requires a snapshot ref from 1 to 160."}
        payload["ref"] = max(0, ref)
    if operation == "type":
        payload["value"] = str(arguments.get("value") or "")[:4000]
    if operation == "key":
        payload["key"] = str(arguments.get("key") or "")[:80]
    endpoint = str(os.getenv("WASM_AGENT_BROWSER_CDP_URL") or "http://127.0.0.1:9222").rstrip("/")
    parsed_endpoint = urlparse(endpoint)
    if parsed_endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return {"ok": False, "code": "browser_cdp_scope_denied", "summary": "CDP endpoint must be loopback-scoped."}
    try:
        completed = subprocess.run(
            ["node", str(BRIDGE), endpoint, json.dumps(payload, separators=(",", ":"))],
            capture_output=True, text=True, timeout=8, check=False,
        )
        result = json.loads((completed.stdout or "{}").strip())
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return {"ok": False, "code": "browser_cdp_unavailable", "summary": str(exc)[:300]}
    if result.get("ok") is not True:
        return {**result, "ok": False, "summary": str(result.get("message") or result.get("code") or "Browser action failed.")[:300]}
    return {**result, "summary": f"Browser {operation} completed with a bounded page snapshot."}
