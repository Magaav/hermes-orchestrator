"""Canonical JSON contracts for the V6 Agent IR."""
from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal
from typing import Any


VERSION = 1
ID = re.compile(r"^[a-z][a-z0-9_.:-]{0,159}$")
KINDS = frozenset({"observe", "act", "verify", "state"})
RECEIPT_STATES = frozenset({"acknowledged", "completed", "failed", "pending", "rejected", "cancelled", "interrupted"})
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_JSON_DEPTH = 64
COMMENTARY_PHASES = frozenset({"orienting", "investigating", "acting", "checking", "correcting", "verifying"})
COMMENTARY_PHASE_ALIASES = {
    "plan": "orienting", "planning": "orienting", "orient": "orienting",
    "discover": "investigating", "discovering": "investigating", "inspect": "investigating",
    "inspecting": "investigating", "read": "investigating", "reading": "investigating",
    "edit": "acting", "editing": "acting", "patch": "acting", "patching": "acting",
    "write": "acting", "writing": "acting", "apply": "acting", "applying": "acting",
    "test": "checking", "testing": "checking", "check": "checking",
    "fix": "correcting", "fixing": "correcting", "repair": "correcting", "retrying": "correcting",
    "prove": "verifying", "proving": "verifying", "validate": "verifying", "validating": "verifying",
    "verify": "verifying",
}


class ContractError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > MAX_JSON_DEPTH:
        raise ContractError("json_depth_exceeded")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise ContractError("json_integer_unsafe")
        return value
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ContractError("json_unicode_invalid")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError("json_number_non_finite")
        return value
    if isinstance(value, list):
        return [_json_value(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError("json_key_not_string")
            result[key] = _json_value(item, depth=depth + 1)
        return result
    raise ContractError("json_type_unsupported")


def canonical(value: Any) -> str:
    """Canonicalize the I-JSON subset with ECMAScript number semantics."""
    normalized = _json_value(value)

    def string(item: str) -> str:
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))

    def number(item: float) -> str:
        if item == 0:
            return "0"
        text = repr(item).lower()
        absolute = abs(item)
        if 1e-6 <= absolute < 1e21:
            if "e" in text:
                text = format(Decimal(text), "f")
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            return text
        if "e" not in text:
            text = format(Decimal(text).normalize(), "e")
        mantissa, exponent = text.split("e", 1)
        mantissa = mantissa.rstrip("0").rstrip(".") if "." in mantissa else mantissa
        exponent_value = int(exponent)
        return f"{mantissa}e{'+' if exponent_value >= 0 else ''}{exponent_value}"

    def render(item: Any) -> str:
        if item is None:
            return "null"
        if item is True:
            return "true"
        if item is False:
            return "false"
        if isinstance(item, int):
            return str(item)
        if isinstance(item, float):
            return number(item)
        if isinstance(item, str):
            return string(item)
        if isinstance(item, list):
            return "[" + ",".join(render(child) for child in item) + "]"
        if isinstance(item, dict):
            ordered = sorted(item, key=lambda key: key.encode("utf-16-be"))
            return "{" + ",".join(f"{string(key)}:{render(item[key])}" for key in ordered) + "}"
        raise ContractError("json_type_unsupported")

    return render(normalized)


def digest(value: Any, *, prefix: str = "sha256") -> str:
    return f"{prefix}:" + hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def decode(raw: str, *, max_bytes: int = 1_000_000) -> Any:
    if len(raw.encode("utf-8")) > max_bytes:
        raise ContractError("json_bytes_exceeded")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ContractError("json_duplicate_key")
            result[key] = value
        return result

    def integer(value: str) -> int | float:
        parsed = int(value)
        return parsed if abs(parsed) <= MAX_SAFE_INTEGER else float(value)

    try:
        return _json_value(json.loads(
            raw, object_pairs_hook=pairs, parse_int=integer,
            parse_constant=lambda _value: (_ for _ in ()).throw(ContractError("json_number_non_finite")),
        ))
    except json.JSONDecodeError as exc:
        raise ContractError("json_invalid") from exc


def _required(value: dict[str, Any], keys: tuple[str, ...], code: str) -> None:
    if any(value.get(key) in (None, "") for key in keys):
        raise ContractError(code)


def capability(value: dict[str, Any]) -> dict[str, Any]:
    _required(value, ("id", "kind", "authority", "executor"), "capability_fields_missing")
    cap_id = str(value["id"])
    kind = str(value["kind"])
    if not ID.fullmatch(cap_id) or kind not in KINDS:
        raise ContractError("capability_identity_invalid")
    mode = str(value.get("mode") or ("write" if kind == "act" else "read"))
    if mode not in {"read", "write"}:
        raise ContractError("capability_mode_invalid")
    terminal_result = value.get("terminal_result") is True
    authorization = str(value.get("authorization") or "reviewed")
    if authorization not in {"reviewed", "bounded_terminal"}:
        raise ContractError("capability_authorization_invalid")
    proof = [str(item)[:120] for item in (value.get("proof") or [])[:16]]
    if terminal_result and not ((kind == "observe" and mode == "read") or (kind == "act" and mode == "write" and proof)):
        raise ContractError("capability_terminal_result_unsafe")
    return {
        "v": VERSION, "id": cap_id, "kind": kind,
        "authority": str(value["authority"])[:160], "executor": str(value["executor"])[:240],
        "mode": mode, "summary": str(value.get("summary") or "")[:500],
        "input": value.get("input") if isinstance(value.get("input"), dict) else {"type": "object"},
        "result": value.get("result") if isinstance(value.get("result"), dict) else {"type": "object"},
        "proof": proof,
        "completion_proof": [str(item)[:120] for item in (value.get("completion_proof") or [])[:16]],
        "completion_effects": [str(item)[:120] for item in (value.get("completion_effects") or [])[:16] if ID.fullmatch(str(item))],
        "goal_completion": value.get("goal_completion") is not False,
        "setup_allowed": value.get("setup_allowed") is True,
        "activates": [str(item)[:160] for item in (value.get("activates") or [])[:16] if ID.fullmatch(str(item))],
        "conflicts": [str(item)[:240] for item in (value.get("conflicts") or [])[:16]],
        "requires_after": [str(item)[:160] for item in (value.get("requires_after") or [])[:16] if ID.fullmatch(str(item))],
        "terminal_result": terminal_result,
        "authorization": authorization,
        "detail": str(value.get("detail") or "")[:240],
    }


def operation(value: dict[str, Any]) -> dict[str, Any]:
    _required(value, ("id", "cap"), "operation_fields_missing")
    operation_id = str(value["id"])
    cap_id = str(value["cap"])
    if not ID.fullmatch(operation_id) or not ID.fullmatch(cap_id):
        raise ContractError("operation_identity_invalid")
    return {
        "v": VERSION, "id": operation_id, "cap": cap_id,
        "args": value.get("args") if isinstance(value.get("args"), dict) else {},
        "after": list(dict.fromkeys(str(item) for item in (value.get("after") or []) if ID.fullmatch(str(item))))[:64],
        "expect": value.get("expect") if isinstance(value.get("expect"), dict) else {},
        "completes_goal": value.get("completes_goal") is True,
        "goal_id": str(value.get("goal_id") or "")[:160],
        "idempotency_key": str(value.get("idempotency_key") or operation_id)[:160],
        "say": commentary(value.get("say")) if value.get("say") else None,
    }


def receipt(value: dict[str, Any]) -> dict[str, Any]:
    _required(value, ("id", "op", "state"), "receipt_fields_missing")
    state = str(value["state"])
    if state not in RECEIPT_STATES:
        raise ContractError("receipt_state_invalid")
    ok = value.get("ok") is True
    return {
        "v": VERSION, "id": str(value["id"])[:160], "op": str(value["op"])[:160],
        "ok": ok, "state": state,
        "observed": value.get("observed") if isinstance(value.get("observed"), dict) else {},
        "proof": [str(item)[:240] for item in (value.get("proof") or [])[:32]],
        "error": value.get("error") if isinstance(value.get("error"), dict) else {},
    }


def commentary(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = {"phase": "acting", "message": value}
    if not isinstance(value, dict):
        raise ContractError("commentary_invalid")
    phase = str(value.get("phase") or "acting").strip().lower().replace("-", "_").replace(" ", "_")
    phase = COMMENTARY_PHASE_ALIASES.get(phase, phase)
    if phase not in COMMENTARY_PHASES:
        phase = "acting"
    message = " ".join(str(value.get("message") or "").replace("\x00", "").split())[:600]
    if not message:
        raise ContractError("commentary_message_missing")
    return {"phase": phase, "message": message}
