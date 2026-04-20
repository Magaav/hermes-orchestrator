"""Built-in hook that appends one structured activity summary per agent cycle."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import logging
import os
import uuid


logger = logging.getLogger("hooks.activity-timeline")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _trim(value: Any, limit: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}…"


def _activity_root() -> Path:
    raw = str(os.getenv("HERMES_AGENTS_ACTIVITY_LOG_ROOT", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path("/local/logs/nodes/activities")


def _node_name(context: dict[str, Any]) -> str:
    direct = str(context.get("node") or os.getenv("NODE_NAME", "") or "").strip()
    if direct:
        return direct

    hermes_home = str(os.getenv("HERMES_HOME", "") or "").strip()
    if hermes_home:
        path = Path(hermes_home).expanduser()
        parts = list(path.parts)
        if "nodes" in parts:
            idx = parts.index("nodes")
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return ""


def _interaction_source(context: dict[str, Any]) -> str:
    if bool(context.get("internal")):
        return "system"
    if bool(context.get("source_is_bot")):
        return "agent"
    platform = str(context.get("platform") or "").strip().lower()
    if platform in {"webhook", "api_server"}:
        return "system"
    if platform:
        return "human"
    return "system"


def _cycle_outcome(context: dict[str, Any]) -> str:
    raw = str(context.get("cycle_outcome") or context.get("outcome") or "").strip().lower()
    aliases = {
        "success": "completed",
        "failure": "errored",
        "cancelled": "interrupted",
        "canceled": "interrupted",
    }
    normalized = aliases.get(raw, raw)
    if normalized in {"completed", "interrupted", "errored", "waiting"}:
        return normalized
    return "completed"


def _tool_usage(context: dict[str, Any], activity_summary: dict[str, Any]) -> dict[str, Any]:
    raw = context.get("tool_usage")
    tool_usage = raw if isinstance(raw, dict) else {}
    names = tool_usage.get("names")
    if not isinstance(names, list):
        names = []

    return {
        "tool_count": int(tool_usage.get("tool_count") or len(names)),
        "unique_tool_count": int(tool_usage.get("unique_tool_count") or len(set(str(name) for name in names if name))),
        "tool_names": [str(name) for name in names if str(name or "").strip()],
        "api_call_count": int(activity_summary.get("api_call_count") or 0),
        "max_iterations": int(activity_summary.get("max_iterations") or 0),
        "budget_used": int(activity_summary.get("budget_used") or 0),
        "budget_max": int(activity_summary.get("budget_max") or 0),
        "current_tool": _trim(activity_summary.get("current_tool") or "", 120),
    }


def _build_summary_text(
    *,
    message_preview: str,
    response_preview: str,
    last_activity_desc: str,
    interaction_source: str,
    cycle_outcome: str,
) -> str:
    parts = [
        f"source={interaction_source}",
        f"outcome={cycle_outcome}",
    ]
    if last_activity_desc:
        parts.append(f"activity={last_activity_desc}")
    if message_preview:
        parts.append(f"input={message_preview}")
    if response_preview:
        parts.append(f"reply={response_preview}")
    return " | ".join(parts)


def build_activity_entry(context: dict[str, Any]) -> dict[str, Any] | None:
    node = _node_name(context)
    if not node:
        return None

    ts = str(context.get("finished_at") or context.get("ts") or _utc_now())
    activity_summary = context.get("activity_summary")
    if not isinstance(activity_summary, dict):
        activity_summary = {}

    interaction_source = _interaction_source(context)
    cycle_outcome = _cycle_outcome(context)
    message_preview = _trim(context.get("message") or "", 180)
    response_preview = _trim(context.get("response") or "", 180)
    last_activity_desc = _trim(
        activity_summary.get("last_activity_desc") or context.get("last_activity_desc") or "",
        180,
    )

    return {
        "id": uuid.uuid4().hex,
        "ts": ts,
        "node": node,
        "session_id": str(context.get("session_id") or "").strip(),
        "agent_identity": str(context.get("agent_identity") or node).strip(),
        "platform": str(context.get("platform") or "").strip(),
        "chat_type": str(context.get("chat_type") or "").strip(),
        "thread_id": str(context.get("thread_id") or "").strip(),
        "user_id": str(context.get("user_id") or "").strip(),
        "user_name": str(context.get("user_name") or "").strip(),
        "interaction_source": interaction_source,
        "cycle_outcome": cycle_outcome,
        "last_activity_desc": last_activity_desc,
        "message_preview": message_preview,
        "response_preview": response_preview,
        "tool_usage": _tool_usage(context, activity_summary),
        "summary_text": _build_summary_text(
            message_preview=message_preview,
            response_preview=response_preview,
            last_activity_desc=last_activity_desc,
            interaction_source=interaction_source,
            cycle_outcome=cycle_outcome,
        ),
    }


def append_activity_entry(entry: dict[str, Any]) -> Path:
    root = _activity_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{entry['node']}.jsonl"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return target


async def handle(event_type: str, context: dict[str, Any]) -> None:
    if event_type != "agent:end":
        return

    try:
        entry = build_activity_entry(context or {})
        if entry is None:
            return
        append_activity_entry(entry)
    except Exception as exc:
        logger.error("activity timeline hook failed: %s", exc)
