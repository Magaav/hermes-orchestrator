"""One-shot, evidence-bound explanation for an ambiguous V6 semantic stall."""
from __future__ import annotations

from typing import Any

from .. import provider_tools
from . import contracts


SCHEMA = "master.frontier.v6.stall_diagnostic.v1"
MODEL_SCHEMA = "master.frontier.v6.stall_diagnostic.model.v1"
MAX_OUTPUT_TOKENS = 600
SYSTEM = """You are the final diagnostic closeout for a stalled Master:frontier run.
You cannot use tools, retry an action, or verify anything new. Use only the bounded STALL/1 evidence supplied by the host. Return only one JSON object with this exact shape:
{"schema":"master.frontier.v6.stall_diagnostic.model.v1","facts":["observed fact"],"hypotheses":[{"cause":"probable cause","confidence":"high|medium|low","because":"specific supporting evidence","next_check":"one read-only discriminating check"}],"next_check":"the single highest-leverage read-only check"}
Give one to three hypotheses in descending probability. Keep observed facts separate from inference. Do not claim the requested action succeeded, and do not expose private reasoning or invent state absent from STALL/1."""


class StallDiagnosticError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _strings(values: Any, *, limit: int, item_limit: int) -> list[str]:
    items = values if isinstance(values, list) else []
    normalized = []
    for item in items:
        text = _text(item, item_limit)
        if text and text not in normalized:
            normalized.append(text)
    return normalized[:limit]


def _active_client(value: Any) -> dict[str, Any]:
    client = value if isinstance(value, dict) else {}
    return {
        key: projected
        for key, projected in {
            "runtime_type": _text(client.get("runtime_type"), 80),
            "client_id": _text(client.get("client_id"), 120),
            "space_id": _text(client.get("space_id"), 120),
            "space_name": _text(client.get("space_name"), 160),
            "widget_manifest": _text(client.get("widget_manifest"), 80),
            "available_widget_ids": _strings(client.get("available_widget_ids"), limit=32, item_limit=80),
            "capabilities": _strings(client.get("capabilities"), limit=32, item_limit=120),
        }.items()
        if projected not in ("", [])
    }


def build_packet(
    *, objective: str, phase: str, missing: list[str], repeated_decisions: int,
    state: dict[str, Any], capabilities: list[dict[str, Any]],
    evidence: list[dict[str, Any]], receipts: list[dict[str, Any]],
    host: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project only the compact facts already available when the stall is detected."""
    host = host if isinstance(host, dict) else {}
    goals = state.get("goals") if isinstance(state.get("goals"), list) else []
    packet = {
        "schema": SCHEMA,
        "objective": _text(objective, 1_000),
        "phase": _text(phase, 160),
        "repeated_decisions": max(2, min(int(repeated_decisions or 2), 128)),
        "missing": _strings(missing, limit=12, item_limit=240),
        "route": {
            key: value for key, value in {
                "route_id": _text(host.get("route_id"), 160),
                "surface": _text(host.get("surface"), 120),
            }.items() if value
        },
        "active_client": _active_client(host.get("active_client")),
        "state": {
            "status": _text(state.get("status"), 40),
            "open": _strings(state.get("open"), limit=24, item_limit=160),
            "goals": [{
                "id": _text(item.get("id"), 120),
                "outcome": _text(item.get("outcome"), 240),
                "status": _text(item.get("status"), 40),
            } for item in goals[:12] if isinstance(item, dict)],
        },
        "capabilities": [{
            "id": _text(item.get("id"), 160),
            "kind": _text(item.get("kind"), 40),
            "mode": _text(item.get("mode"), 40),
            "summary": _text(item.get("summary"), 320),
            "detail": _text(item.get("detail"), 240),
        } for item in capabilities[-16:] if isinstance(item, dict)],
        "evidence": [{
            "kind": _text(item.get("kind"), 80),
            "subject": _text(item.get("subject"), 160),
            "summary": _text(item.get("summary"), 320),
            "proof": _strings(item.get("proof"), limit=4, item_limit=80),
        } for item in evidence[-8:] if isinstance(item, dict)],
        "receipts": [{
            "op": _text(item.get("op"), 160),
            "ok": item.get("ok") is True,
            "state": _text(item.get("state"), 40),
            "error": {
                "code": _text((item.get("error") or {}).get("code"), 160),
                "summary": _text((item.get("error") or {}).get("summary"), 320),
            } if isinstance(item.get("error"), dict) else {},
            "proof": _strings(item.get("proof"), limit=4, item_limit=80),
        } for item in receipts[-8:] if isinstance(item, dict)],
    }
    # Re-canonicalize so callers cannot retain mutable aliases into controller state.
    return contracts.decode(contracts.canonical(packet), max_bytes=48_000)


def messages(packet: dict[str, Any]) -> list[dict[str, str]]:
    if packet.get("schema") != SCHEMA:
        raise StallDiagnosticError("stall_diagnostic_packet_invalid")
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"STALL/1\n{contracts.canonical(packet)}"},
    ]


def _json_reply(result: dict[str, Any]) -> dict[str, Any]:
    if provider_tools.response_calls(result):
        raise StallDiagnosticError("stall_diagnostic_tool_call_denied")
    text = str(result.get("reply") or "").strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1:] if first_newline >= 0 else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()
    try:
        value = contracts.decode(text, max_bytes=16_000)
    except (contracts.ContractError, UnicodeError) as exc:
        raise StallDiagnosticError("stall_diagnostic_response_invalid") from exc
    if not isinstance(value, dict) or value.get("schema") != MODEL_SCHEMA:
        raise StallDiagnosticError("stall_diagnostic_response_invalid")
    return value


def _model_diagnostic(result: dict[str, Any]) -> dict[str, Any]:
    value = _json_reply(result)
    facts = _strings(value.get("facts"), limit=4, item_limit=360)
    hypotheses = []
    for item in (value.get("hypotheses") if isinstance(value.get("hypotheses"), list) else [])[:3]:
        if not isinstance(item, dict):
            continue
        cause = _text(item.get("cause"), 360)
        because = _text(item.get("because"), 420)
        next_check = _text(item.get("next_check"), 360)
        confidence = _text(item.get("confidence"), 20).lower()
        if cause and because and next_check and confidence in {"high", "medium", "low"}:
            hypotheses.append({
                "cause": cause, "confidence": confidence,
                "because": because, "next_check": next_check,
            })
    next_check = _text(value.get("next_check"), 360)
    if not hypotheses or not next_check:
        raise StallDiagnosticError("stall_diagnostic_response_incomplete")
    return {"facts": facts, "hypotheses": hypotheses, "next_check": next_check, "model_valid": True}


def _fallback(packet: dict[str, Any], code: str) -> dict[str, Any]:
    receipts = packet.get("receipts") if isinstance(packet.get("receipts"), list) else []
    failed = next((item for item in reversed(receipts) if isinstance(item, dict) and item.get("ok") is not True), None)
    active_client = packet.get("active_client") if isinstance(packet.get("active_client"), dict) else {}
    missing = _strings(packet.get("missing"), limit=6, item_limit=200)
    facts = [
        f"The no-progress gate stopped the run during {_text(packet.get('phase'), 120) or 'an unresolved decision phase'}.",
        *([f"The unresolved requirements were {', '.join(missing)}."] if missing else []),
    ]
    hypotheses = []
    error = failed.get("error") if isinstance(failed, dict) and isinstance(failed.get("error"), dict) else {}
    if _text(error.get("summary"), 320):
        hypotheses.append({
            "cause": _text(error.get("summary"), 320), "confidence": "high",
            "because": f"The last failed receipt reported {_text(error.get('code'), 120) or 'a typed operation failure'}.",
            "next_check": "Inspect that failed receipt and the capability preconditions before retrying.",
        })
    if active_client:
        space = _text(active_client.get("space_name") or active_client.get("space_id"), 160) or "the active surface"
        widgets = _strings(active_client.get("available_widget_ids"), limit=32, item_limit=80)
        facts.append(f"The bound client reported {space} with available widgets: {', '.join(widgets) or 'none'}.")
        hypotheses.append({
            "cause": "The active client surface may not expose the state or target required by the action.",
            "confidence": "medium",
            "because": "The active-surface capability manifest did not lead to a proof-correlated completion.",
            "next_check": "Inspect the current active-surface manifest and compare it with the requested capability.",
        })
    hypotheses.append({
        "cause": "The model may have repeated a decision without choosing a different evidence or capability path.",
        "confidence": "medium",
        "because": f"The semantic state remained unchanged across {int(packet.get('repeated_decisions') or 2)} decisions.",
        "next_check": "Compare the repeated decisions and select the first missing capability or new evidence probe.",
    })
    return {
        "facts": list(dict.fromkeys(facts))[:4], "hypotheses": hypotheses[:3],
        "next_check": hypotheses[0]["next_check"], "model_valid": False,
        "error": _text(code, 160) or "stall_diagnostic_response_invalid",
    }


def interpret(
    result: dict[str, Any], packet: dict[str, Any], *, failure_code: str = "",
) -> dict[str, Any]:
    try:
        diagnostic = _fallback(packet, failure_code) if failure_code else _model_diagnostic(result)
    except StallDiagnosticError as exc:
        diagnostic = _fallback(packet, exc.code)
    facts = diagnostic["facts"]
    hypotheses = diagnostic["hypotheses"]
    lines = [
        "I stopped after repeated decisions made no measurable progress, so I did not complete the requested action.",
    ]
    if facts:
        lines.append("Observed: " + " ".join(facts))
    lines.append("Most likely possibilities:")
    for index, item in enumerate(hypotheses, start=1):
        lines.append(
            f"{index}. {item['cause']} ({item['confidence']} confidence). "
            f"Evidence: {item['because']} Possible next check: {item['next_check']}"
        )
    lines.append(f"Best next check: {diagnostic['next_check']}")
    lines.append("These causes are inferred from the recorded stall evidence; I did not verify the root cause or complete the action.")
    return {"schema": SCHEMA, "answer": "\n".join(lines), **diagnostic}
