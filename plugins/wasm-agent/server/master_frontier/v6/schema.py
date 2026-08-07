"""Small deterministic JSON-Schema admission subset for V6 operations.

The kernel only needs the validation vocabulary emitted by its capability
adapters.  Keeping that subset local avoids a heavyweight runtime dependency
while still failing closed before repository, client, or MCP execution.
"""
from __future__ import annotations

import re
from typing import Any

from . import contracts


def _fail(code: str) -> None:
    raise contracts.ContractError(code)


def validate(value: Any, schema: dict[str, Any], *, depth: int = 0) -> None:
    if depth > 12:
        _fail("schema_depth_exceeded")
    if not isinstance(schema, dict):
        _fail("schema_invalid")
    if "enum" in schema and value not in schema.get("enum", []):
        _fail("schema_enum_mismatch")
    expected = schema.get("type")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    if isinstance(expected, list):
        if not any(valid.get(str(item), False) for item in expected):
            _fail("schema_type_mismatch")
    elif expected and not valid.get(str(expected), False):
        _fail("schema_type_mismatch")
    if isinstance(value, dict):
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        if any(str(key) not in value for key in required):
            _fail("schema_required_missing")
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if schema.get("additionalProperties") is False and any(key not in properties for key in value):
            _fail("schema_property_unknown")
        for key, item in value.items():
            child = properties.get(key)
            if isinstance(child, dict):
                validate(item, child, depth=depth + 1)
    elif isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            _fail("schema_items_too_few")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            _fail("schema_items_too_many")
        child = schema.get("items")
        if isinstance(child, dict):
            for item in value:
                validate(item, child, depth=depth + 1)
    elif isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            _fail("schema_string_too_short")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            _fail("schema_string_too_long")
        if schema.get("pattern") and re.search(str(schema["pattern"]), value) is None:
            _fail("schema_pattern_mismatch")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            _fail("schema_number_too_small")
        if "maximum" in schema and value > schema["maximum"]:
            _fail("schema_number_too_large")
