"""Versioned semantic capability plugin for the native Windows control plane."""
from __future__ import annotations

from typing import Any

from . import contracts


PLUGIN_ID = "windows-control"
PLUGIN_VERSION = 1


def describe(capabilities: set[str]) -> dict[str, Any]:
    """Return a tiny stable map; capability details remain pull-on-demand in V6."""
    layers = []
    if "run_hot_operation" in capabilities:
        layers.extend(["inventory", "pixels", "browser_cdp"])
    if "windows.desktop.inspect" in capabilities:
        layers.append("uia")
    if "windows.shell.execute.unrestricted" in capabilities:
        layers.append("shell")
    return {
        "plugin": PLUGIN_ID,
        "version": PLUGIN_VERSION,
        "platform": "windows",
        "layers": layers,
        "authority": "current_user",
        "elevation": "not_implicit",
    }


def capabilities(advertised: set[str], *, client_id: str, binding: str) -> list[dict[str, Any]]:
    """Compile only capabilities supported by the live native client."""
    result: list[dict[str, Any]] = []
    wait_30 = {"wait_sec": {"type": "number", "minimum": 0, "maximum": 30, "default": 30}}
    if "run_hot_operation" in advertised:
        result.append(contracts.capability({
            "id": "client.windows.browser.cdp.status", "kind": "observe", "authority": "client.ui.inspect",
            "executor": "client.windows.browser.cdp.status",
            "summary": "Report persistent CDP lifecycle when lifecycle itself is requested, or after direct inspection reports the realm unavailable. For browser write goals inspect first; do not spend a separate status decision.",
            "mode": "read", "proof": ["windows.browser.cdp.lifecycle.observed"],
            "completion_proof": ["windows.browser.cdp.lifecycle.observed"],
            "terminal_result": True, "detail": binding,
            "input": {"type": "object", "properties": wait_30, "additionalProperties": False},
        }))
        for capability_id, executor, summary, proof in (
            ("client.windows.desktop.windows.list", "client.windows.desktop.windows.list", "List bounded visible top-level Windows application windows with title, process, handle, and minimized state.", "windows.desktop.top_level_windows"),
            ("client.windows.desktop.screenshot", "client.windows.desktop.screenshot", "Capture the Windows virtual desktop into a local PNG artifact and return bounded dimensions, path, and SHA-256 metadata; pixels are not inserted into model context.", "windows.desktop.screenshot"),
        ):
            result.append(contracts.capability({
                "id": capability_id, "kind": "observe", "authority": "client.ui.inspect",
                "executor": executor, "summary": summary, "mode": "read", "proof": [proof],
                "terminal_result": True, "detail": binding,
                "input": {"type": "object", "properties": wait_30, "additionalProperties": False},
            }))
        for capability_id, summary, proof in (
            ("client.windows.browser.cdp.default.open", "Recovery action: open the default durable WASM Agent Chrome profile after CDP inspection reports the persistent realm unavailable.", "windows.browser.cdp.persistent.ready"),
            ("client.windows.browser.cdp.persistent.open", "Recovery action: explicitly open the persistent authenticated CDP realm after CDP inspection reports it unavailable.", "windows.browser.cdp.persistent.ready"),
            ("client.windows.browser.cdp.incognito.open", "Open a disposable incognito CDP realm; use only when private or non-persistent behavior is requested.", "windows.browser.cdp.incognito.ready"),
        ):
            result.append(contracts.capability({
                "id": capability_id, "kind": "act", "authority": "client.ui.control",
                "executor": capability_id, "summary": summary, "mode": "write",
                "conflicts": [f"client:{client_id or 'bound'}"], "proof": [proof],
                "completion_proof": [proof], "terminal_result": True,
                "setup_allowed": True,
                "authorization": "bounded_terminal", "detail": binding,
                "input": {"type": "object", "properties": wait_30, "additionalProperties": False},
            }))
        result.append(contracts.capability({
            "id": "client.windows.browser.cdp.navigate", "kind": "act", "authority": "client.ui.control",
            "executor": "client.windows.browser.cdp.navigate",
            "summary": "Navigate the active persistent CDP realm to an exact HTTP(S) URL and independently observe the resulting target URL.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"],
            "proof": ["windows.browser.cdp.navigation.observed"],
            "completion_proof": ["windows.browser.cdp.navigation.observed"],
            "terminal_result": True, "detail": binding,
            "setup_allowed": True,
            "input": {"type": "object", "required": ["url"], "properties": {
                "url": {"type": "string", "minLength": 8, "maxLength": 2048, "pattern": "^https?://"},
                **wait_30,
            }, "additionalProperties": False},
        }))
        step = {"type": "object", "required": ["locator", "action"], "properties": {
            "locator": {"type": "string", "minLength": 1, "maxLength": 2048},
            "action": {"type": "string", "enum": ["click", "set_value", "key"]},
            "value": {"type": "string", "maxLength": 4096}, "key": {"type": "string", "maxLength": 40},
        }, "additionalProperties": False}
        result.append(contracts.capability({
            "id": "client.windows.browser.cdp.transaction", "kind": "act", "authority": "client.ui.control",
            "executor": "client.windows.browser.cdp.transaction",
            "summary": "Run up to four ordered actions using snapshot CSS locators or text=<exact visible text>; clicks and keys use native CDP input, then a refreshed semantic snapshot must prove the expected predicate became newly true or increased. Use fill plus submit here. A failed step returns its index/action/locator plus one bounded recovery lens; reuse a returned actionLocator directly instead of repeating generic inspection.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"],
            "proof": ["windows.browser.cdp.action.observed"], "completion_proof": ["windows.browser.cdp.action.observed"], "detail": binding,
            "goal_completion": False,
            "setup_allowed": True,
            "terminal_result": True,
            "input": {"type": "object", "required": ["steps", "expect"], "properties": {
                "target_url": {"type": "string", "maxLength": 2048},
                "steps": {"type": "array", "minItems": 1, "maxItems": 4, "items": step},
                "expect": {"type": "object", "required": ["property", "equals"], "properties": {
                    "property": {"type": "string", "enum": ["name", "value", "focused", "url", "page_text_contains"]},
                    "equals": {"type": ["string", "boolean"]},
                }, "additionalProperties": False}, **wait_30,
            }, "additionalProperties": False},
        }))
        result.append(contracts.capability({
            "id": "client.windows.browser.cdp.inspect", "kind": "observe", "authority": "client.ui.inspect",
            "executor": "client.windows.browser.cdp.inspect",
            "summary": "Probe the persistent CDP session and inspect bounded actionable controls, page text, and an always-on compact editableTargets map with locator, semantic name, role, owner scope, and target fingerprint. Optional query lenses disambiguate only when that map is insufficient; use this first without a speculative open or outer-window UIA.",
            "mode": "read", "proof": ["windows.browser.cdp.dom.snapshot"], "detail": binding,
            "activates": ["client.windows.browser.cdp.procedure"],
            "input": {"type": "object", "properties": {
                "target_url": {"type": "string", "maxLength": 2048},
                "max_elements": {"type": "integer", "minimum": 1, "maximum": 200, "default": 120}, **wait_30,
                "query_text": {"type": "string", "maxLength": 300},
                "query_selector": {"type": "string", "maxLength": 300},
            }, "additionalProperties": False},
        }))
        result.append(contracts.capability({
            "id": "client.windows.browser.cdp.runtime.inspect", "kind": "observe", "authority": "client.ui.inspect",
            "executor": "client.windows.browser.cdp.runtime.inspect",
            "summary": "Inspect bounded getter-safe JavaScript runtime descriptors and correlate one optional semantic locator with DOM ancestry, prototype descriptors, page revision, and a short-lived handle. Use when ordinary DOM semantics cannot establish application ownership or state; this capability never invokes getters or mutates the page.",
            "mode": "read", "proof": ["windows.browser.cdp.runtime.snapshot"],
            "completion_proof": ["windows.browser.cdp.runtime.snapshot"],
            "terminal_result": True, "detail": binding,
            "input": {"type": "object", "properties": {
                "target_url": {"type": "string", "maxLength": 2048},
                "locator": {"type": "string", "maxLength": 2048},
                "max_ancestors": {"type": "integer", "minimum": 1, "maximum": 16, "default": 8},
                "max_properties": {"type": "integer", "minimum": 1, "maximum": 160, "default": 80},
                **wait_30,
            }, "additionalProperties": False},
        }))
        result.append(contracts.capability({
            "id": "client.windows.browser.cdp.act", "kind": "act", "authority": "client.ui.control",
            "executor": "client.windows.browser.cdp.act",
            "summary": "Perform one semantic action using a snapshot CSS locator or text=<exact visible text>; click/key use hit-tested native CDP input, followed by proof that the exact expected predicate became newly true or increased. A missing target returns compact targeted recovery matches whose actionLocator can be retried directly.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"],
            "proof": ["windows.browser.cdp.action.observed"], "completion_proof": ["windows.browser.cdp.action.observed"], "detail": binding,
            "goal_completion": False,
            "setup_allowed": True,
            "input": {"type": "object", "required": ["locator", "action", "expect"], "properties": {
                "target_url": {"type": "string", "maxLength": 2048}, "locator": {"type": "string", "minLength": 1, "maxLength": 2048},
                "action": {"type": "string", "enum": ["click", "set_value", "key"]}, "value": {"type": "string", "maxLength": 4096},
                "key": {"type": "string", "maxLength": 40},
                "expect": {"type": "object", "required": ["property", "equals"], "properties": {
                    "property": {"type": "string", "enum": ["name", "value", "focused", "url", "page_text_contains"]},
                    "equals": {"type": ["string", "boolean"]},
                }, "additionalProperties": False}, **wait_30,
            }, "additionalProperties": False},
        }))

    target = {"type": "object", "properties": {"hwnd": {"type": ["string", "integer"]}, "process_id": {"type": "integer", "minimum": 1}, "title_contains": {"type": "string", "maxLength": 240}}, "additionalProperties": False}
    expect = {"type": "object", "required": ["property", "equals"], "properties": {"property": {"type": "string", "enum": ["name", "value", "toggle_state", "enabled", "offscreen", "selected", "expanded"]}, "equals": {"type": ["string", "number", "boolean"]}}, "additionalProperties": False}
    ref = {"snapshot_id": {"type": "string", "pattern": "^s-[a-f0-9]{16}$"}, "ref": {"type": "string", "pattern": "^e[0-9]{1,3}$"}}
    if "windows.desktop.describe" in advertised:
        result.append(contracts.capability({"id": "client.windows.desktop.describe", "kind": "observe", "authority": "client.ui.inspect", "executor": "client.windows.desktop.describe", "summary": "Describe Windows UI Automation actions, limits, caller-token authority, and elevation boundary.", "mode": "read", "proof": ["windows.desktop.capability_manifest"], "detail": binding, "input": {"type": "object", "properties": {"wait_sec": {"type": "number", "minimum": 0, "maximum": 20}}, "additionalProperties": False}}))
    if "windows.desktop.inspect" in advertised:
        result.append(contracts.capability({"id": "client.windows.desktop.inspect", "kind": "observe", "authority": "client.ui.inspect", "executor": "client.windows.desktop.inspect", "summary": "Inspect a bounded UI Automation tree for the foreground or exactly targeted Windows window and return short-lived element refs.", "mode": "read", "proof": ["windows.uia.snapshot"], "detail": binding, "input": {"type": "object", "properties": {"target": target, "max_elements": {"type": "integer", "minimum": 1, "maximum": 200, "default": 80}, "max_depth": {"type": "integer", "minimum": 1, "maximum": 32, "default": 12}, "include_values": {"type": "boolean", "default": False}, "timeout_ms": {"type": "integer", "minimum": 3000, "maximum": 30000, "default": 15000}, **wait_30}, "additionalProperties": False}}))
    if "windows.desktop.act" in advertised:
        result.append(contracts.capability({"id": "client.windows.desktop.act", "kind": "act", "authority": "client.ui.control", "executor": "client.windows.desktop.act", "summary": "Act on a revision-bound Windows UI Automation element ref and independently observe the declared postcondition.", "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"], "proof": ["windows.uia.action_receipt"], "completion_proof": ["client.windows.uia.postcondition"], "detail": binding, "input": {"type": "object", "required": ["snapshot_id", "ref", "action", "expect"], "properties": {**ref, "action": {"type": "string", "enum": ["focus", "invoke", "click", "set_value", "toggle", "select", "expand", "collapse"]}, "value": {"type": "string", "maxLength": 4096}, "expect": expect, "timeout_ms": {"type": "integer", "minimum": 3000, "maximum": 30000, "default": 15000}, **wait_30}, "additionalProperties": False}}))
    if "windows.desktop.prove" in advertised:
        result.append(contracts.capability({"id": "client.windows.desktop.prove", "kind": "verify", "authority": "client.ui.inspect", "executor": "client.windows.desktop.prove", "summary": "Reacquire a revision-bound Windows UI Automation element and verify one scalar postcondition without mutation.", "mode": "read", "proof": ["client.windows.uia.postcondition"], "detail": binding, "input": {"type": "object", "required": ["snapshot_id", "ref", "expect"], "properties": {**ref, "expect": expect, "timeout_ms": {"type": "integer", "minimum": 3000, "maximum": 30000, "default": 15000}, **wait_30}, "additionalProperties": False}}))
    if "windows.shell.execute.unrestricted" in advertised:
        result.append(contracts.capability({"id": "client.windows.shell.execute.unrestricted", "kind": "act", "authority": "client.ui.control", "executor": "client.windows.shell.execute.unrestricted", "summary": "Execute arbitrary PowerShell or cmd as the installed Windows user; use as the full-control escape hatch when no structured primitive exists.", "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"], "proof": ["client.ack", "windows.shell.exit"], "detail": binding, "input": {"type": "object", "required": ["command"], "properties": {"command": {"type": "string", "minLength": 1, "maxLength": 1_048_576}, "shell": {"type": "string", "enum": ["powershell", "cmd"], "default": "powershell"}, "cwd": {"type": "string", "maxLength": 32_768}, "environment": {"type": "object", "maxProperties": 128}, "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 240000, "default": 60000}, "wait_sec": {"type": "number", "minimum": 0, "maximum": 20}}, "additionalProperties": False}}))
    return result
