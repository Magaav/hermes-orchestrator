"""Generic proof-owned browser procedure capability."""
from __future__ import annotations

from typing import Any

from . import contracts


PLUGIN_ID = "browser-procedure"
PLUGIN_VERSION = 1


def capabilities(advertised: set[str], *, client_id: str, binding: str) -> list[dict[str, Any]]:
    if "run_hot_operation" not in advertised:
        return []
    step = {
        "type": "object", "required": ["locator", "action"], "additionalProperties": False,
        "properties": {
            "locator": {"type": "string", "minLength": 1, "maxLength": 2048},
            "action": {"type": "string", "enum": ["click", "set_value", "key"]},
            "value": {"type": "string", "maxLength": 4096},
            "key": {"type": "string", "maxLength": 40},
            "target_contract": {
                "type": "object", "required": ["role", "editable", "scope_locator", "name_contains"],
                "additionalProperties": False,
                "properties": {
                    "role": {"type": "string", "minLength": 1, "maxLength": 80},
                    "zone": {"type": "string", "enum": [
                        "left-top", "left-middle", "left-bottom", "center-top", "center-middle",
                        "center-bottom", "right-top", "right-middle", "right-bottom",
                    ]},
                    "region": {"type": "string", "maxLength": 80},
                    "editable": {"type": "boolean"},
                    "scope_locator": {"type": "string", "minLength": 1, "maxLength": 2048},
                    "name_contains": {"type": "string", "minLength": 1, "maxLength": 180},
                },
            },
        },
    }
    assertion = {
        "type": "object", "required": ["id", "selector", "scope_locator", "property", "transition"], "additionalProperties": False,
        "properties": {
            "id": {"type": "string", "minLength": 1, "maxLength": 80},
            "selector": {"type": "string", "minLength": 1, "maxLength": 2048},
            "scope_locator": {"type": "string", "minLength": 1, "maxLength": 2048},
            "property": {"type": "string", "enum": ["count", "text", "last_text", "value", "focused"]},
            "equals": {"type": ["string", "number", "boolean"]},
            "transition": {"type": "string", "enum": ["count_increased", "became_equal", "equals_after"]},
        },
    }
    return [contracts.capability({
        "id": "client.windows.browser.cdp.procedure", "kind": "act", "authority": "client.ui.control",
        "executor": "client.windows.browser.cdp.procedure",
        "summary": "Observe-bind-act-prove: inspect once, copy targetId into page_target_id, bind editable steps to inspected role/name and an owning scope, then require scoped before/after outcome assertions. Stable owner identity uses equals_after; mutation evidence uses a real transition such as count_increased. Never use became_equal for a field known empty before and after submission. Geometry is diagnostic only; setup observations cannot prove mutations.",
        "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"], "detail": binding,
        "proof": ["windows.browser.cdp.procedure.completed"],
        "completion_proof": ["windows.browser.cdp.procedure.completed"], "terminal_result": True,
        "completion_effects": ["browser.message.sent"],
        "authorization": "bounded_terminal",
        "input": {"type": "object", "required": ["page_target_id", "steps", "assertions"], "additionalProperties": False, "properties": {
            "target_url": {"type": "string", "maxLength": 2048},
            "page_target_id": {"type": "string", "minLength": 1, "maxLength": 160},
            "steps": {"type": "array", "minItems": 1, "maxItems": 6, "items": step},
            "assertions": {"type": "array", "minItems": 1, "maxItems": 6, "items": assertion},
            "wait_sec": {"type": "number", "minimum": 0, "maximum": 30, "default": 30},
        }},
    })]
