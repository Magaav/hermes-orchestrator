"""Helpers for deterministic final-response changed-files footers."""

from __future__ import annotations

import difflib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, Iterable


_PATCH_FILE_RE = re.compile(r"^\*\*\*\s+(Update|Add|Delete)\s+File:\s*(.+?)\s*$", re.MULTILINE)
_TOOL_SNAPSHOTS: dict[tuple[str, str], dict[str, Any]] = {}
_SESSION_CHANGESETS: dict[str, dict[str, dict[str, Any]]] = {}
_LOCK = threading.RLock()


def plugin_enabled() -> bool:
    """Return True when the deterministic footer plugin should be active."""
    raw = (
        os.getenv("PLUGIN_FINAL_RESPONSE_FILES_CHANGED")
        or os.getenv("NODE_AGENT_FINALRESPONSE_ENFORCE_FILES_CHANGED")
        or ""
    )
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def reset_turn_state(session_id: str = "", **_: Any) -> None:
    """Clear any accumulated file changes for the current user turn."""
    if not plugin_enabled():
        return
    session = str(session_id or "").strip()
    if not session:
        return
    with _LOCK:
        _SESSION_CHANGESETS.pop(session, None)
        stale_keys = [key for key in _TOOL_SNAPSHOTS if key[0] == session]
        for key in stale_keys:
            _TOOL_SNAPSHOTS.pop(key, None)


def record_pre_tool_snapshot(
    tool_name: str,
    args: Dict[str, Any] | None,
    session_id: str = "",
    tool_call_id: str = "",
    **_: Any,
) -> None:
    """Snapshot file state before a write-oriented tool runs."""
    if not plugin_enabled():
        return
    tool_name = str(tool_name or "").strip()
    args = args if isinstance(args, dict) else {}
    snapshot = _build_tool_snapshot(tool_name=tool_name, args=args)
    if not snapshot:
        return
    with _LOCK:
        _TOOL_SNAPSHOTS[_snapshot_key(session_id, tool_call_id)] = snapshot


def record_post_tool_result(
    tool_name: str,
    args: Dict[str, Any] | None,
    result: str,
    session_id: str = "",
    tool_call_id: str = "",
    **_: Any,
) -> None:
    """Capture file changes after a tool completes for deterministic footer rendering."""
    if not plugin_enabled():
        return
    tool_name = str(tool_name or "").strip()
    args = args if isinstance(args, dict) else {}
    key = _snapshot_key(session_id, tool_call_id)
    with _LOCK:
        snapshot = _TOOL_SNAPSHOTS.pop(key, None)

    payload = _extract_json_object(result)
    entries = _collect_changed_entries(
        tool_name=tool_name,
        args=args,
        payload=payload,
        snapshot=snapshot,
    )
    _merge_session_changes(session_id=session_id, entries=entries)


def transform_final_response(
    session_id: str = "",
    assistant_response: str = "",
    final_response: str = "",
    **_: Any,
) -> str | None:
    """Append the deterministic changed-files footer to the final response."""
    if not plugin_enabled():
        return None

    base = str(assistant_response or final_response or "")
    if not base.strip():
        return None

    session = str(session_id or "").strip()
    if session:
        with _LOCK:
            entries = _normalize_entries(_SESSION_CHANGESETS.pop(session, {}).values())
    else:
        entries = []

    footer = render_files_changed_footer(entries)
    if not footer:
        return base
    if footer in base:
        return base
    return f"{base.rstrip()}\n\n{footer}"


def render_files_changed_footer(entries: Iterable[Dict[str, Any]]) -> str:
    """Render the final footer appended to the assistant response."""
    normalized = _normalize_entries(entries)
    if not normalized:
        return ""

    visible_entries = [entry for entry in normalized if entry["status"] != "deleted"]
    total_add = sum(int(entry.get("add", 0) or 0) for entry in visible_entries)
    total_del = sum(int(entry.get("del", 0) or 0) for entry in visible_entries)

    lines = [f"📁 Files changed +{total_add} -{total_del}"]
    _append_footer_section(lines, "Updated", [e for e in normalized if e["status"] == "updated"])
    _append_footer_section(lines, "Created", [e for e in normalized if e["status"] == "created"])
    _append_footer_section(lines, "Deleted", [e for e in normalized if e["status"] == "deleted"])
    return "\n".join(lines)


def _append_footer_section(lines: list[str], title: str, entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    lines.append(f"{title}:")
    for entry in entries:
        if entry["status"] == "deleted":
            lines.append(f"- {entry['path']}")
            continue
        lines.append(f"- {entry['path']} +{int(entry.get('add', 0) or 0)} -{int(entry.get('del', 0) or 0)}")


def _snapshot_key(session_id: str, tool_call_id: str) -> tuple[str, str]:
    return (str(session_id or "").strip(), str(tool_call_id or "").strip())


def _normalize_status(raw_status: Any) -> str:
    value = str(raw_status or "").strip().lower()
    if value in {"created", "create", "added", "add"}:
        return "created"
    if value in {"deleted", "delete", "removed", "remove"}:
        return "deleted"
    if value in {"updated", "update", "modified", "modify", "patched", "patch"}:
        return "updated"
    return ""


def _resolve_path(raw_path: Any) -> str:
    text = str(raw_path or "").strip()
    if not text:
        return ""
    path = Path(os.path.expanduser(text))
    if not path.is_absolute():
        base = Path(os.getenv("TERMINAL_CWD", os.getcwd()))
        path = base / path
    try:
        return str(path.resolve(strict=False))
    except Exception:
        return str(path)


def _build_tool_snapshot(tool_name: str, args: Dict[str, Any]) -> dict[str, Any]:
    if tool_name == "write_file":
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            return {}
        resolved_path = _resolve_path(raw_path)
        return {
            "tool_name": tool_name,
            "raw_path": raw_path,
            "resolved_path": resolved_path,
            "existed_before": bool(resolved_path and Path(resolved_path).exists()),
            "previous_content": _read_text_file(resolved_path) if resolved_path and Path(resolved_path).exists() else "",
        }

    if tool_name != "patch":
        return {}

    patch_mode = str(args.get("mode") or "replace").strip().lower()
    if patch_mode == "replace":
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            return {}
        resolved_path = _resolve_path(raw_path)
        return {
            "tool_name": tool_name,
            "mode": patch_mode,
            "raw_path": raw_path,
            "resolved_path": resolved_path,
            "existed_before": bool(resolved_path and Path(resolved_path).exists()),
            "previous_content": _read_text_file(resolved_path) if resolved_path and Path(resolved_path).exists() else "",
        }

    patch_text = str(args.get("patch") or "")
    if not patch_text.strip():
        return {}
    operations: list[dict[str, str]] = []
    for match in _PATCH_FILE_RE.finditer(patch_text):
        op_kind = str(match.group(1) or "").strip().lower()
        raw_path = str(match.group(2) or "").strip()
        if not raw_path:
            continue
        operations.append(
            {
                "op": op_kind,
                "raw_path": raw_path,
                "resolved_path": _resolve_path(raw_path),
            }
        )
    if not operations:
        return {}
    return {
        "tool_name": tool_name,
        "mode": patch_mode,
        "operations": operations,
    }


def _extract_json_object(raw_result: str) -> dict[str, Any] | None:
    text = str(raw_result or "").lstrip()
    if not text.startswith("{"):
        return None
    try:
        parsed, _index = json.JSONDecoder().raw_decode(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _collect_changed_entries(
    tool_name: str,
    args: Dict[str, Any],
    payload: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    delta_by_path: dict[str, dict[str, int]] = _extract_payload_deltas(payload)

    if isinstance(payload, dict):
        for key, status in (
            ("files_created", "created"),
            ("files_deleted", "deleted"),
            ("files_modified", "updated"),
        ):
            raw_paths = payload.get(key)
            if not isinstance(raw_paths, list):
                continue
            for raw_path in raw_paths:
                path = str(raw_path or "").strip()
                if not path:
                    continue
                delta = delta_by_path.get(path, {"add": 0, "del": 0})
                entries.append(
                    {
                        "path": path,
                        "status": status,
                        "add": int(delta.get("add", 0) or 0),
                        "del": int(delta.get("del", 0) or 0),
                    }
                )

    if entries:
        return entries

    if tool_name == "write_file":
        raw_path = str(args.get("path") or "").strip()
        if raw_path:
            existed_before = bool((snapshot or {}).get("existed_before"))
            delta = _diff_counts(
                str((snapshot or {}).get("previous_content") or ""),
                str(args.get("content") or ""),
            )
            entries.append(
                {
                    "path": raw_path,
                    "status": "updated" if existed_before else "created",
                    "add": int(delta.get("add", 0) or 0),
                    "del": int(delta.get("del", 0) or 0),
                }
            )
        return entries

    if tool_name != "patch":
        return entries

    if snapshot and isinstance(snapshot.get("operations"), list):
        for operation in snapshot["operations"]:
            raw_path = str(operation.get("raw_path") or "").strip()
            status = _normalize_status(operation.get("op"))
            if not raw_path or not status:
                continue
            delta = delta_by_path.get(raw_path, {"add": 0, "del": 0})
            entries.append(
                {
                    "path": raw_path,
                    "status": status,
                    "add": int(delta.get("add", 0) or 0),
                    "del": int(delta.get("del", 0) or 0),
                }
            )
        return entries

    raw_path = str(args.get("path") or "").strip()
    if raw_path:
        existed_before = bool((snapshot or {}).get("existed_before", True))
        delta = delta_by_path.get(raw_path, {"add": 0, "del": 0})
        entries.append(
            {
                "path": raw_path,
                "status": "updated" if existed_before else "created",
                "add": int(delta.get("add", 0) or 0),
                "del": int(delta.get("del", 0) or 0),
            }
        )
    return entries


def _read_text_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _count_unified_diff(diff_text: str) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    current_path = ""
    for raw_line in str(diff_text or "").splitlines():
        line = raw_line.rstrip("\n")
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                current_path = _normalize_diff_path(parts[3])
                if current_path:
                    stats.setdefault(current_path, {"add": 0, "del": 0})
            continue
        if line.startswith("+++ "):
            candidate = line[4:].strip()
            if candidate != "/dev/null":
                current_path = _normalize_diff_path(candidate)
                if current_path:
                    stats.setdefault(current_path, {"add": 0, "del": 0})
            continue
        if line.startswith("@@"):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            if current_path:
                stats.setdefault(current_path, {"add": 0, "del": 0})["add"] += 1
            continue
        if line.startswith("-") and not line.startswith("---"):
            if current_path:
                stats.setdefault(current_path, {"add": 0, "del": 0})["del"] += 1
            continue
    return stats


def _normalize_diff_path(raw_path: Any) -> str:
    path = str(raw_path or "").strip()
    if not path:
        return ""
    if " -> " in path:
        left, right = path.split(" -> ", 1)
        path = right.strip() or left.strip()
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def _extract_payload_deltas(payload: dict[str, Any] | None) -> dict[str, dict[str, int]]:
    if not isinstance(payload, dict):
        return {}
    return _count_unified_diff(str(payload.get("diff") or ""))


def _diff_counts(before: str, after: str) -> dict[str, int]:
    diff_lines = difflib.unified_diff(
        str(before or "").splitlines(keepends=True),
        str(after or "").splitlines(keepends=True),
        fromfile="a/file",
        tofile="b/file",
    )
    add = 0
    delete = 0
    for line in diff_lines:
        if line.startswith("+") and not line.startswith("+++"):
            add += 1
        elif line.startswith("-") and not line.startswith("---"):
            delete += 1
    return {"add": add, "del": delete}


def _merge_session_changes(session_id: str, entries: Iterable[Dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = _normalize_entries(entries)
    if not session_id:
        return normalized
    with _LOCK:
        state = _SESSION_CHANGESETS.setdefault(session_id, {})
        for entry in normalized:
            _merge_entry_into_state(state, entry)
        return _normalize_entries(state.values())


def _merge_entry_into_state(state: dict[str, dict[str, Any]], entry: dict[str, Any]) -> None:
    path = str(entry.get("path") or "").strip()
    status = _normalize_status(entry.get("status"))
    if not path or not status:
        return
    add = int(entry.get("add", 0) or 0)
    delete = int(entry.get("del", 0) or 0)

    current = state.get(path)
    if current is None:
        state[path] = {"path": path, "status": status, "add": add, "del": delete}
        return

    current_status = _normalize_status(current.get("status"))
    next_status = status
    if current_status == "created" and status == "updated":
        next_status = "created"
    elif current_status == "created" and status == "deleted":
        state.pop(path, None)
        return
    elif current_status == "updated" and status == "deleted":
        next_status = "deleted"
    elif current_status == "deleted" and status == "created":
        next_status = "updated"

    current["status"] = next_status
    current["add"] = int(current.get("add", 0) or 0) + add
    current["del"] = int(current.get("del", 0) or 0) + delete


def _normalize_entries(entries: Iterable[Dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        _merge_entry_into_state(merged, entry)
    return sorted(
        merged.values(),
        key=lambda item: (_status_sort_key(item["status"]), item["path"]),
    )


def _status_sort_key(status: str) -> int:
    return {"updated": 0, "created": 1, "deleted": 2}.get(_normalize_status(status), 99)
