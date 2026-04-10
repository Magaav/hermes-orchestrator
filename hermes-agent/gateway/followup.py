"""Helpers for long-running followup notifications in gateway mode."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional


def coerce_followup_minutes(raw_value: Any, default: int = 10) -> int:
    """Parse followup interval minutes from env-style values."""
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError):
        return default
    return max(1, value)


def coerce_followup_bool(raw_value: Any, default: bool = False) -> bool:
    """Parse booleans from common env-style strings."""
    if raw_value is None:
        return default
    value = str(raw_value).strip().lower()
    if not value:
        return default
    if value in ("1", "true", "yes", "on", "y", "sim"):
        return True
    if value in ("0", "false", "no", "off", "n", "nao", "não"):
        return False
    return default


def resolve_followup_config() -> tuple[int, bool]:
    """Resolve followup interval/summary toggles from env vars."""
    elapsed_raw = (
        os.getenv("HERMES_GATEWAY_FOLLOWUP_ELAPSED_MINUTES")
        or os.getenv("NODE_AGENT_FOLLOWUP_ELAPSED")
        or "10"
    )
    summary_raw = (
        os.getenv("HERMES_GATEWAY_FOLLOWUP_SUMMARY")
        or os.getenv("NODE_AGENT_FOLLOWUP_SUMMARY")
        or "false"
    )
    return (
        coerce_followup_minutes(elapsed_raw, default=10),
        coerce_followup_bool(summary_raw, default=False),
    )


def _parse_tool_result_dict(raw_result: Any) -> Optional[Dict[str, Any]]:
    """Best-effort parse of tool result JSON strings."""
    if not isinstance(raw_result, str):
        return None
    payload = raw_result.strip()
    if not payload or not payload.startswith("{"):
        return None
    try:
        parsed = json.loads(payload)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def count_followup_tool_errors(prev_tools: list) -> int:
    """Count obvious tool failures for followup summaries."""
    errors = 0
    for entry in (prev_tools or []):
        if not isinstance(entry, dict):
            continue
        parsed = _parse_tool_result_dict(entry.get("result"))
        if isinstance(parsed, dict):
            if parsed.get("error") or parsed.get("success") is False:
                errors += 1
            continue
        result_text = entry.get("result")
        if isinstance(result_text, str) and result_text.strip().lower().startswith("error"):
            errors += 1
    return errors


def build_followup_summary_lines(activity: Optional[Dict[str, Any]], state: Dict[str, Any]) -> List[str]:
    """Build bullet lines for long-running followup pings."""
    lines: List[str] = []
    iteration = int(state.get("iteration") or 0)
    if activity:
        api_call_count = int(activity.get("api_call_count") or 0)
        max_iterations = int(activity.get("max_iterations") or 0)
        if api_call_count and max_iterations:
            lines.append(f"iteration {api_call_count}/{max_iterations} in progress")
        elif iteration:
            lines.append(f"iteration {iteration} in progress")

        current_tool = str(activity.get("current_tool") or "").strip()
        if current_tool:
            lines.append(f"running tool: {current_tool}")
    elif iteration:
        lines.append(f"iteration {iteration} in progress")

    tool_names = state.get("tool_names") or []
    if isinstance(tool_names, list):
        trimmed = [str(name).strip() for name in tool_names if str(name).strip()]
        if trimmed:
            lines.append(f"last tools: {', '.join(trimmed[:4])}")

    error_count = int(state.get("error_count") or 0)
    if error_count > 0:
        lines.append(f"tool errors detected: {error_count}")

    if activity:
        last_desc = str(activity.get("last_activity_desc") or "").strip()
        if last_desc:
            lines.append(f"next: {last_desc}")

    if not lines:
        lines.append("collecting progress details")
    return lines[:4]
