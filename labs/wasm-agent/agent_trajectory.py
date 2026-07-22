"""Compact, redacted, adapter-neutral learning trajectory events.

Adapters may optionally write JSONL to ``WASM_AGENT_EVENTS_PATH``.  The lane
owns normalization and always appends its own authoritative terminal event.
Raw prompts, tool arguments, tool results, and private reasoning are never
copied into the normalized trajectory.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCHEMA = "wasm-agent.safe-lab.agent-trajectory.v1"
EVENT_PATH_ENV = "WASM_AGENT_EVENTS_PATH"
MAX_SOURCE_BYTES = 65_536
MAX_EVENTS = 96
MAX_SUMMARY_CHARS = 480

# Shared dictionary for the compact JSONL projection.  It is declared once in
# code instead of repeated in every model- or scorer-facing event.
FIELD_DICTIONARY = {
    "v": "schema version",
    "q": "lane-local sequence",
    "k": "event kind",
    "s": "status",
    "a": "action or lane reference",
    "t": "tool or operation",
    "p": "safe source/workspace-relative path",
    "d": "argument digest",
    "r": "receipt, proof, or result reference",
    "x": "bounded redacted summary",
    "n": "bounded numeric metrics",
    "o": "event provenance",
}
KIND_CODES = frozenset({
    "start", "search", "read", "inspect", "edit", "command", "test",
    "diff", "proof", "checkpoint", "resume", "tool", "warning", "error",
    "final", "terminal",
})
STATUS_CODES = frozenset({"ok", "run", "skip", "block", "err"})

_SECRET = re.compile(
    r"(?i)\b(?:bearer\s+\S+|sk[-_][A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9_-]{12,}|"
    r"github_pat_[A-Za-z0-9_-]{12,}|xox[baprs]-[A-Za-z0-9_-]{12,})\b"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_KEYED_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|secret|access[_-]?token|refresh[_-]?token)"
    r"\s*[:=]\s*['\"]?[^\s,'\"]+"
)
_RAW_RUNTIME_REF = re.compile(
    r"(?i)\b(?:wa_run_[a-z0-9]{12,}|agent_[a-z0-9]{6,}_[a-z0-9]{4,})\b"
)
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
_PRIVATE_KINDS = frozenset({"analysis", "reasoning", "thought", "chain_of_thought"})

_KINDS = {
    "start": "start",
    "run.started": "start",
    "search": "search",
    "read": "read",
    "inspect": "inspect",
    "edit": "edit",
    "patch": "edit",
    "command": "command",
    "shell": "command",
    "test": "test",
    "diff": "diff",
    "proof": "proof",
    "checkpoint": "checkpoint",
    "resume": "resume",
    "tool": "tool",
    "tool_call": "tool",
    "tool.started": "tool",
    "tool_result": "tool",
    "tool.finished": "tool",
    "warning": "warning",
    "error": "error",
    "final": "final",
    "finish": "final",
    "terminal": "final",
}

_STATUSES = {
    "ok": "ok",
    "pass": "ok",
    "passed": "ok",
    "complete": "ok",
    "completed": "ok",
    "success": "ok",
    "running": "run",
    "started": "run",
    "pending": "run",
    "skip": "skip",
    "skipped": "skip",
    "blocked": "block",
    "unavailable": "block",
    "fail": "err",
    "failed": "err",
    "error": "err",
    "timeout": "err",
    "interrupted": "err",
}

_METRICS = {
    "durationMs": "ms",
    "promptTokens": "pt",
    "completionTokens": "ct",
    "providerCalls": "pc",
    "toolCalls": "tc",
    "toolCallCount": "tc",
    "returncode": "rc",
    "bytes": "b",
    "matches": "mc",
}


def _redact_text(value: Any, limit: int = MAX_SUMMARY_CHARS) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    text = _SECRET.sub("[redacted-secret]", text)
    text = _KEYED_SECRET.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = _EMAIL.sub("[redacted-email]", text)
    text = _RAW_RUNTIME_REF.sub("[redacted-runtime-ref]", text)
    return text[:limit]


def _safe_name(value: Any) -> str:
    text = str(value or "").strip()
    if _SECRET.search(text) or _EMAIL.search(text) or _RAW_RUNTIME_REF.search(text):
        return ""
    return text if _SAFE_NAME.fullmatch(text) else ""


def _safe_reference(value: Any) -> str:
    text = str(value or "").strip()
    if _SECRET.search(text) or _EMAIL.search(text) or _RAW_RUNTIME_REF.search(text):
        return _digest(text)
    if re.fullmatch(r"(?:sha256:)?[a-fA-F0-9]{64}", text):
        return _digest(text)
    if re.fullmatch(r"(?:receipt|proof|checkpoint|action|ref)[-_:][A-Za-z0-9_.:-]{1,80}", text):
        return text
    return _digest(text) if text else ""


def _digest(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str) and re.fullmatch(r"(?:sha256:)?[a-fA-F0-9]{64}", value):
        return "sha256:" + value.removeprefix("sha256:").lower()
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    except (TypeError, ValueError, RecursionError):
        encoded = repr(value)[:4096].encode("utf-8", "replace")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _safe_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if text.startswith("/source/"):
        text = "src:" + text.removeprefix("/source/")
    elif text.startswith("/workspace/"):
        text = "ws:" + text.removeprefix("/workspace/")
    elif text.startswith("/"):
        return ""
    if not text or ".." in text.split("/") or len(text) > 240:
        return ""
    return _redact_text(text, 240)


def normalize_event(value: Any, sequence: int) -> tuple[dict[str, Any] | None, str | None]:
    """Normalize one untrusted adapter event into the compact vocabulary."""

    if not isinstance(value, dict):
        return None, "event_not_object"
    raw_kind = str(value.get("kind") or value.get("type") or value.get("event") or "").strip().lower()
    if raw_kind in _PRIVATE_KINDS or any(part in raw_kind for part in ("reasoning", "thought")):
        return None, "private_reasoning_ignored"
    kind = _KINDS.get(raw_kind)
    if not kind:
        return None, "unsupported_event_kind"

    event: dict[str, Any] = {"v": 1, "q": sequence, "k": kind}
    event["o"] = "adapter"
    status = _STATUSES.get(str(value.get("status") or "").strip().lower())
    if status:
        event["s"] = status
    action = _safe_name(value.get("actionId") or value.get("action_id") or value.get("actionRef"))
    if action:
        event["a"] = action
    tool = _safe_name(value.get("tool") or value.get("toolName") or value.get("operation"))
    if tool:
        event["t"] = tool
    path = _safe_path(value.get("path") or value.get("file"))
    if path:
        event["p"] = path

    argument_digest = value.get("argumentsDigest") or value.get("argsDigest")
    if not argument_digest and "arguments" in value:
        argument_digest = _digest(value.get("arguments"))
    argument_digest = _digest(argument_digest) if argument_digest else ""
    if argument_digest:
        event["d"] = argument_digest

    reference = value.get("receiptRef") or value.get("resultDigest") or value.get("proofRef") or value.get("ref")
    safe_reference = _safe_reference(reference)
    if safe_reference:
        event["r"] = safe_reference

    summary = value.get("summary") or value.get("message") or value.get("detail")
    if summary not in (None, ""):
        event["x"] = _redact_text(summary)

    metrics: dict[str, int] = {}
    for source, target in _METRICS.items():
        raw = value.get(source)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)):
            metrics[target] = max(-2_147_483_648, min(2_147_483_647, int(raw)))
    changed = value.get("changedFiles") or value.get("changed_files")
    if isinstance(changed, list):
        metrics["fc"] = len(changed)
    if metrics:
        event["n"] = metrics
    return event, None


def _read_source(path: Path) -> tuple[list[Any], list[str], bool]:
    if not path.exists():
        return [], [], False
    if path.is_symlink() or not path.is_file():
        return [], ["adapter_event_path_not_regular"], True
    warnings: list[str] = []
    size = path.stat().st_size
    with path.open("rb") as handle:
        raw = handle.read(MAX_SOURCE_BYTES + 1)
    if size > MAX_SOURCE_BYTES or len(raw) > MAX_SOURCE_BYTES:
        raw = raw[:MAX_SOURCE_BYTES]
        warnings.append("adapter_event_bytes_truncated")
    values: list[Any] = []
    for line_number, line in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
        if len(values) >= MAX_EVENTS:
            warnings.append("adapter_event_count_truncated")
            break
        if not line.strip():
            continue
        try:
            values.append(json.loads(line))
        except (ValueError, RecursionError):
            warnings.append(f"adapter_event_invalid_json:{line_number}")
    return values, warnings, True


def build_trajectory(
    source_path: Path,
    *,
    terminal_status: str,
    slot: str,
    terminal_summary: str,
) -> dict[str, Any]:
    """Load optional adapter events and append one lane-owned terminal event."""

    raw_events, warnings, source_present = _read_source(source_path)
    events: list[dict[str, Any]] = []
    for raw in raw_events:
        if len(events) >= MAX_EVENTS - 1:
            warnings.append("normalized_event_count_truncated")
            break
        event, warning = normalize_event(raw, len(events) + 1)
        if warning:
            warnings.append(warning)
        if event:
            events.append(event)

    successful = terminal_status in {"completed", "topology_proven"}
    terminal: dict[str, Any] = {
        "v": 1,
        "q": len(events) + 1,
        "k": "terminal",
        "s": "ok" if successful else "err",
        "o": "lane",
        "x": _redact_text(terminal_summary or terminal_status),
    }
    safe_slot = _safe_name(slot)
    if safe_slot:
        terminal["a"] = safe_slot
    events.append(terminal)
    unique_warnings = list(dict.fromkeys(warnings))
    complete = successful and source_present and bool(events[:-1]) and not unique_warnings
    return {
        "schema": SCHEMA,
        "events": events,
        "metadata": {
            "sourcePresent": source_present,
            "adapterEventsRead": len(raw_events),
            "normalizedEvents": len(events) - 1,
            "terminalPreserved": True,
            "completeness": "complete" if complete else "incomplete",
            "provenance": ["adapter", "lane"] if source_present else ["lane"],
            "admissibleForStrategyMining": complete,
            "warnings": unique_warnings,
        },
    }


def write_trajectory(
    output_path: Path,
    source_path: Path,
    *,
    terminal_status: str,
    slot: str,
    terminal_summary: str,
) -> dict[str, Any]:
    trajectory = build_trajectory(
        source_path,
        terminal_status=terminal_status,
        slot=slot,
        terminal_summary=terminal_summary,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in trajectory["events"]),
        encoding="utf-8",
    )
    return trajectory
