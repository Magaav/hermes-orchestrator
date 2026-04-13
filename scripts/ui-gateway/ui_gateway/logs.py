from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import re
import uuid

from .contracts import FleetLogEvent
from .redaction import redact_text
from .settings import GatewaySettings


_ALLOWED_CHANNELS = {
    "management",
    "runtime",
    "attention",
    "hermes_errors",
    "hermes_gateway",
    "hermes_agent",
    "all",
}

_SEVERITY_RE = {
    "error": re.compile(r"\b(error|fatal|panic|critical|traceback|exception)\b", re.IGNORECASE),
    "warning": re.compile(r"\b(warn|warning|429|forbidden|denied|missing access)\b", re.IGNORECASE),
}

_TS_PREFIX_RE = re.compile(
    r"^\[?(?P<ts>\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\]?"
)



def allowed_channels() -> set[str]:
    return set(_ALLOWED_CHANNELS)



def channel_log_path(node: str, channel: str, settings: GatewaySettings) -> Path:
    if channel == "management":
        return settings.node_logs_root / node / "management.log"
    if channel == "runtime":
        return settings.node_logs_root / node / "runtime.log"
    if channel == "attention":
        return settings.attention_logs_root / node / "warning-plus.log"
    if channel == "hermes_errors":
        return settings.node_logs_root / node / "hermes" / "errors.log"
    if channel == "hermes_gateway":
        return settings.node_logs_root / node / "hermes" / "gateway.log"
    if channel == "hermes_agent":
        return settings.node_logs_root / node / "hermes" / "agent.log"
    raise ValueError(f"unsupported channel: {channel}")



def node_log_paths(node: str, settings: GatewaySettings) -> dict[str, str]:
    return {
        channel: str(channel_log_path(node, channel, settings))
        for channel in sorted(_ALLOWED_CHANNELS)
        if channel != "all"
    }



def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")



def infer_severity(line: str) -> str:
    if _SEVERITY_RE["error"].search(line):
        return "error"
    if _SEVERITY_RE["warning"].search(line):
        return "warning"
    return "info"



def parse_timestamp(line: str) -> str:
    match = _TS_PREFIX_RE.match(line.strip())
    if not match:
        return _utc_now()
    raw = str(match.group("ts") or "").strip()
    if raw.endswith("Z"):
        return raw.replace(" ", "T")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}", raw):
        return raw.replace(" ", "T") + "Z"
    return raw.replace(" ", "T")



def normalize_log_line(node: str, channel: str, line: str) -> FleetLogEvent:
    redacted = redact_text(line.rstrip("\n"))
    return FleetLogEvent(
        id=uuid.uuid4().hex,
        node=node,
        channel=channel,
        ts=parse_timestamp(redacted),
        severity=infer_severity(redacted),
        message=redacted,
        raw=redacted,
    )



def tail_lines(path: Path, lines: int) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    max_lines = max(1, lines)
    buffer: deque[str] = deque(maxlen=max_lines)
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            buffer.append(line.rstrip("\n"))
    return list(buffer)



def read_channel_events(node: str, channel: str, tail: int, settings: GatewaySettings) -> list[FleetLogEvent]:
    path = channel_log_path(node, channel, settings)
    lines = tail_lines(path, tail)
    return [normalize_log_line(node, channel, line) for line in lines]



def count_attention_events(node: str, settings: GatewaySettings, *, window_lines: int = 200) -> int:
    path = channel_log_path(node, "attention", settings)
    return len(tail_lines(path, window_lines))
