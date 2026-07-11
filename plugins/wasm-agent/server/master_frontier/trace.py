from __future__ import annotations

import json
from typing import Any

from . import envelope as direct_envelope


PREVIEW_CHARS = 4000


def _clip(value: Any, limit: int = PREVIEW_CHARS) -> str:
    return direct_envelope.clipped(str(value or "").strip(), limit)


def _json(value: Any, limit: int = PREVIEW_CHARS) -> str:
    redacted = direct_envelope.redact(value)
    try:
        rendered = json.dumps(redacted, ensure_ascii=False, indent=2, sort_keys=True)
    except (TypeError, ValueError):
        rendered = str(redacted or "")
    return _clip(rendered, limit)


def inference_action(index: int, result: dict[str, Any], choice: dict[str, Any]) -> dict[str, Any]:
    kind = str(choice.get("kind") or "invalid")
    action = choice.get("action") if isinstance(choice.get("action"), dict) else {}
    operation = str(action.get("operation") or action.get("action") or "")
    detail = (
        f"Selected {operation}"
        if kind == "tool" and operation
        else "Prepared final answer"
        if kind == "final"
        else f"Needs action repair: {choice.get('code') or 'invalid output'}"
    )
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    return {
        "id": f"mf_llm_{index}",
        "label": "LLM decision",
        "status": "error" if kind == "invalid" else "done",
        "detail": detail,
        "kind": "trace",
        "topic": "run-api",
        "meta": "buffered",
        "arguments": {
            "inference": index,
            "decision": kind,
            "operation": operation,
            "usage": direct_envelope.redact(usage),
        },
        "preview": _clip(result.get("reply"), PREVIEW_CHARS),
    }


def tool_action(index: int, action: dict[str, Any], observed: dict[str, Any] | None = None) -> dict[str, Any]:
    operation = str(action.get("operation") or action.get("action") or "function")
    args = action.get("args") if isinstance(action.get("args"), dict) else {}
    if observed is None:
        status = "running"
        detail = f"Calling {operation}"
        preview = ""
        meta = "calling"
    else:
        satisfying = bool(observed.get("satisfying"))
        status = "done" if satisfying else "error"
        detail = str(observed.get("model_line") or observed.get("line") or f"{operation} returned")
        preview = _clip(observed.get("detail"), PREVIEW_CHARS)
        meta = str(observed.get("evidence_class") or ("received" if satisfying else observed.get("failure_code") or "missing"))
    return {
        "id": f"mf_tool_{index}",
        "label": operation,
        "status": status,
        "detail": _clip(detail, 240),
        "kind": "tool",
        "topic": "run-api",
        "meta": meta,
        "arguments": direct_envelope.redact(args),
        "preview": preview,
    }


def feedback_action(index: int, observed: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"mf_feedback_{index}_{observed.get('handle') or 'gate'}",
        "label": "Controller feedback",
        "status": "error",
        "detail": _clip(observed.get("model_line") or observed.get("line") or "Action needs repair", 240),
        "kind": "policy",
        "topic": "run-wasm",
        "meta": str(observed.get("failure_code") or observed.get("status") or "repair"),
        "arguments": {},
        "preview": _clip(observed.get("detail"), PREVIEW_CHARS),
    }


def compact_result_preview(value: Any) -> str:
    return _json(value, PREVIEW_CHARS)
