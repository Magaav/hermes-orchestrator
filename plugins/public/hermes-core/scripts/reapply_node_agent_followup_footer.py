#!/usr/bin/env python3
"""Reapply node-agent followup/summary + final file-footer patches in gateway/run.py.

Why:
- Followup interval and summary should be configurable per node via env files.
- Final responses should optionally include a deterministic file-change footer.
- Keep customizations outside hermes-agent core so updates can be re-patched.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


HERMES_HOME = _resolve_hermes_home()
_ENV_AGENT_ROOT = str(os.getenv("HERMES_AGENT_ROOT", "") or "").strip()

RUN_PATH_CANDIDATES = (
    *(
        (Path(_ENV_AGENT_ROOT).expanduser() / "gateway" / "run.py",)
        if _ENV_AGENT_ROOT
        else ()
    ),
    Path("/local/hermes-agent/gateway/run.py"),
    HERMES_HOME / "hermes-agent" / "gateway" / "run.py",
    Path("/local/.hermes/hermes-agent/gateway/run.py"),
    Path("/home/ubuntu/.hermes/hermes-agent/gateway/run.py"),
)

RUNTIME_START = "COLMEIO_NODE_AGENT_RUNTIME_BEGIN"
RUNTIME_END = "COLMEIO_NODE_AGENT_RUNTIME_END"
STEP_START = "COLMEIO_NODE_AGENT_STEP_SUMMARY_BEGIN"
STEP_END = "COLMEIO_NODE_AGENT_STEP_SUMMARY_END"
NOTIFY_START = "COLMEIO_NODE_AGENT_FOLLOWUP_NOTIFY_BEGIN"
NOTIFY_END = "COLMEIO_NODE_AGENT_FOLLOWUP_NOTIFY_END"
FOOTER_START = "COLMEIO_NODE_AGENT_FINAL_FOOTER_BEGIN"
FOOTER_END = "COLMEIO_NODE_AGENT_FINAL_FOOTER_END"


RUNTIME_BLOCK = """        # COLMEIO_NODE_AGENT_RUNTIME_BEGIN
        def _coerce_node_int(raw_value: Any, default: int) -> int:
            try:
                if raw_value is None:
                    return default
                return int(str(raw_value).strip())
            except (TypeError, ValueError):
                return default

        def _coerce_node_bool(raw_value: Any, default: bool = False) -> bool:
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

        def _parse_node_env_file(path: Path) -> Dict[str, str]:
            values: Dict[str, str] = {}
            try:
                if not path.exists() or path.is_dir():
                    return values
                for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if not key:
                        continue
                    if value and len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                        value = value[1:-1]
                    values[key] = value
            except Exception:
                pass
            return values

        def _load_node_agent_env() -> Dict[str, str]:
            candidates: List[Path] = []
            explicit_file = str(os.getenv("NODE_AGENT_ENV_FILE", "") or "").strip()
            if explicit_file:
                candidates.append(Path(explicit_file).expanduser())

            node_name = str(os.getenv("NODE_NAME", "") or "").strip()
            if node_name:
                candidates.extend([
                    Path("/local/agents/nodes") / f"{node_name}.env",
                    Path("/local/agents/nodes") / node_name / ".env",
                    Path("/local/agents/envs") / f"{node_name}.env",
                    Path("/local/agents") / f"{node_name}.env",
                ])

            for candidate in candidates:
                data = _parse_node_env_file(candidate)
                if data:
                    return data
            return {}

        _node_agent_env = _load_node_agent_env()

        def _node_agent_setting(key: str, default: str = "") -> str:
            runtime_value = str(os.getenv(key, "") or "").strip()
            if runtime_value:
                return runtime_value
            file_value = str(_node_agent_env.get(key, "") or "").strip()
            if file_value:
                return file_value
            return default

        _followup_elapsed_minutes = _coerce_node_int(
            _node_agent_setting("NODE_AGENT_FOLLOWUP_ELAPSED", "10"),
            10,
        )
        if _followup_elapsed_minutes < 1:
            _followup_elapsed_minutes = 1

        _followup_summary_enabled = _coerce_node_bool(
            _node_agent_setting("NODE_AGENT_FOLLOWUP_SUMMARY", "false"),
            False,
        )
        _finalresponse_footer_enabled = _coerce_node_bool(
            _node_agent_setting("NODE_AGENT_FINALRESPONSE_ENFORCE_FILES_CHANGED", "false"),
            False,
        )

        _followup_state: Dict[str, Any] = {
            "iteration": 0,
            "tool_names": [],
            "error_count": 0,
        }

        def _safe_parse_json_obj(raw_payload: Any) -> Optional[Dict[str, Any]]:
            if not isinstance(raw_payload, str):
                return None
            payload = raw_payload.strip()
            if not payload or not payload.startswith("{"):
                return None
            try:
                parsed = json.loads(payload)
            except Exception:
                return None
            return parsed if isinstance(parsed, dict) else None

        def _normalize_changed_path(raw_path: Any) -> str:
            if raw_path is None:
                return ""
            path = str(raw_path).strip()
            if not path:
                return ""
            if " -> " in path:
                left, right = path.split(" -> ", 1)
                path = right.strip() or left.strip()
            if path.startswith("a/") or path.startswith("b/"):
                path = path[2:]
            return path

        def _count_unified_diff(diff_text: str) -> Dict[str, Dict[str, int]]:
            stats: Dict[str, Dict[str, int]] = {}
            current_path = ""
            for raw_line in str(diff_text or "").splitlines():
                line = raw_line.rstrip("\\n")
                if line.startswith("diff --git "):
                    parts = line.split()
                    if len(parts) >= 4:
                        candidate = parts[3]
                        if candidate.startswith("b/"):
                            candidate = candidate[2:]
                        current_path = _normalize_changed_path(candidate)
                        if current_path:
                            stats.setdefault(current_path, {"add": 0, "del": 0})
                    continue
                if line.startswith("+++ "):
                    candidate = line[4:].strip()
                    if candidate == "/dev/null":
                        current_path = ""
                    else:
                        current_path = _normalize_changed_path(candidate)
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

        def _build_files_changed_footer(agent_messages: List[Dict[str, Any]], history_offset: int = 0) -> str:
            if not agent_messages:
                return ""

            tool_call_meta: Dict[str, Dict[str, Any]] = {}
            for msg in agent_messages:
                if msg.get("role") != "assistant":
                    continue
                for tool_call in (msg.get("tool_calls") or []):
                    if not isinstance(tool_call, dict):
                        continue
                    call_id = str(tool_call.get("id") or "").strip()
                    fn_data = tool_call.get("function") or {}
                    fn_name = str(fn_data.get("name") or "").strip()
                    fn_args = fn_data.get("arguments")
                    parsed_args: Dict[str, Any] = {}
                    if isinstance(fn_args, str) and fn_args.strip():
                        try:
                            candidate_args = json.loads(fn_args)
                            if isinstance(candidate_args, dict):
                                parsed_args = candidate_args
                        except Exception:
                            parsed_args = {}
                    elif isinstance(fn_args, dict):
                        parsed_args = fn_args
                    if call_id:
                        tool_call_meta[call_id] = {
                            "name": fn_name,
                            "args": parsed_args,
                        }

            start_idx = 0
            if isinstance(history_offset, int):
                start_idx = max(0, min(history_offset, len(agent_messages)))

            file_stats: Dict[str, Dict[str, int]] = {}
            file_kinds: Dict[str, Dict[str, bool]] = {}
            for msg in agent_messages[start_idx:]:
                if msg.get("role") != "tool":
                    continue
                payload = _safe_parse_json_obj(msg.get("content"))
                if not payload:
                    continue

                call_id = str(msg.get("tool_call_id") or "").strip()
                meta = tool_call_meta.get(call_id, {})
                tool_name = str(meta.get("name") or "").strip()
                tool_args = meta.get("args") if isinstance(meta.get("args"), dict) else {}

                paths: List[str] = []
                for key, kind in (
                    ("files_modified", "modified"),
                    ("files_created", "created"),
                    ("files_deleted", "deleted"),
                ):
                    raw_paths = payload.get(key)
                    if isinstance(raw_paths, list):
                        for raw_path in raw_paths:
                            normalized = _normalize_changed_path(raw_path)
                            if normalized:
                                paths.append(normalized)
                                path_kinds = file_kinds.setdefault(
                                    normalized,
                                    {"modified": False, "created": False, "deleted": False},
                                )
                                path_kinds[kind] = True

                if not paths and isinstance(tool_args, dict):
                    arg_path = _normalize_changed_path(tool_args.get("path"))
                    if arg_path and tool_name in ("write_file", "patch"):
                        paths.append(arg_path)
                        path_kinds = file_kinds.setdefault(
                            arg_path,
                            {"modified": False, "created": False, "deleted": False},
                        )
                        path_kinds["modified"] = True

                unique_paths: List[str] = []
                seen_paths = set()
                for path in paths:
                    if path not in seen_paths:
                        seen_paths.add(path)
                        unique_paths.append(path)
                paths = unique_paths
                if not paths:
                    continue

                diff_stats = _count_unified_diff(str(payload.get("diff") or ""))
                for path in paths:
                    file_stats.setdefault(path, {"add": 0, "del": 0})
                    file_kinds.setdefault(
                        path,
                        {"modified": True, "created": False, "deleted": False},
                    )

                if diff_stats:
                    matched_any = False
                    for path in paths:
                        if path in diff_stats:
                            file_stats[path]["add"] += int(diff_stats[path].get("add", 0))
                            file_stats[path]["del"] += int(diff_stats[path].get("del", 0))
                            matched_any = True
                    if not matched_any:
                        total_add = sum(int(v.get("add", 0)) for v in diff_stats.values())
                        total_del = sum(int(v.get("del", 0)) for v in diff_stats.values())
                        file_stats[paths[0]]["add"] += total_add
                        file_stats[paths[0]]["del"] += total_del
                elif tool_name == "write_file" and isinstance(tool_args, dict):
                    content_arg = tool_args.get("content")
                    if isinstance(content_arg, str) and content_arg:
                        line_count = content_arg.count("\\n")
                        if not content_arg.endswith("\\n"):
                            line_count += 1
                        file_stats[paths[0]]["add"] += max(1, line_count)

            touched_stats: Dict[str, Dict[str, int]] = {}
            for path, stats in file_stats.items():
                path_kinds = file_kinds.get(path) or {}
                has_delta = bool(int(stats.get("add", 0) or 0) or int(stats.get("del", 0) or 0))
                has_kind = bool(
                    path_kinds.get("modified")
                    or path_kinds.get("created")
                    or path_kinds.get("deleted")
                )
                if has_delta or has_kind:
                    touched_stats[path] = stats
            if not touched_stats:
                return ""

            ordered_paths = sorted(touched_stats.keys())
            total_add = sum(int(v.get("add", 0) or 0) for v in touched_stats.values())
            total_del = sum(int(v.get("del", 0) or 0) for v in touched_stats.values())

            updated_paths: List[str] = []
            created_paths: List[str] = []
            deleted_paths: List[str] = []
            for path in ordered_paths:
                path_kinds = file_kinds.get(path) or {}
                is_created = bool(path_kinds.get("created"))
                is_deleted = bool(path_kinds.get("deleted"))
                if is_created and not is_deleted:
                    created_paths.append(path)
                elif is_deleted and not is_created:
                    deleted_paths.append(path)
                else:
                    updated_paths.append(path)

            summary_bits: List[str] = []
            if updated_paths:
                summary_bits.append(f"{len(updated_paths)} updated")
            if created_paths:
                summary_bits.append(f"{len(created_paths)} created")
            if deleted_paths:
                summary_bits.append(f"{len(deleted_paths)} deleted")
            summary_suffix = f" ({', '.join(summary_bits)})" if summary_bits else ""

            lines = [f"## 📁 {len(ordered_paths)} Files Changed +{total_add} -{total_del}{summary_suffix}"]

            def _append_paths(section_name: str, section_paths: List[str]) -> None:
                if not section_paths:
                    return
                lines.append(f"### {section_name} ({len(section_paths)})")
                for section_path in section_paths:
                    add = int(touched_stats[section_path].get("add", 0) or 0)
                    dele = int(touched_stats[section_path].get("del", 0) or 0)
                    deltas = []
                    if add:
                        deltas.append(f"+{add}")
                    if dele:
                        deltas.append(f"-{dele}")
                    if deltas:
                        lines.append(f"- {section_path} {' '.join(deltas)}")
                    else:
                        lines.append(f"- {section_path}")

            _append_paths("Updated", updated_paths)
            _append_paths("Created", created_paths)
            _append_paths("Deleted", deleted_paths)
            return "\\n".join(lines)

        def _build_followup_summary_lines(activity: Optional[Dict[str, Any]]) -> List[str]:
            lines: List[str] = []
            iteration = int(_followup_state.get("iteration") or 0)
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

            tool_names = _followup_state.get("tool_names") or []
            if isinstance(tool_names, list):
                trimmed = [str(name).strip() for name in tool_names if str(name).strip()]
                if trimmed:
                    lines.append(f"last tools: {', '.join(trimmed[:4])}")

            error_count = int(_followup_state.get("error_count") or 0)
            if error_count > 0:
                lines.append(f"tool errors detected: {error_count}")

            if activity:
                last_desc = str(activity.get("last_activity_desc") or "").strip()
                if last_desc:
                    lines.append(f"next: {last_desc}")

            if not lines:
                lines.append("collecting progress details")
            return lines[:4]
        # COLMEIO_NODE_AGENT_RUNTIME_END
"""

STEP_BLOCK = """                # COLMEIO_NODE_AGENT_STEP_SUMMARY_BEGIN
                if _followup_summary_enabled:
                    _followup_state["iteration"] = int(iteration)
                    _trimmed_names = [n for n in _names if n][:6]
                    if _trimmed_names:
                        _followup_state["tool_names"] = _trimmed_names
                    _error_count = 0
                    for _tool_entry in (prev_tools or []):
                        if not isinstance(_tool_entry, dict):
                            continue
                        _tool_result = _tool_entry.get("result")
                        _parsed_result = _safe_parse_json_obj(_tool_result)
                        if isinstance(_parsed_result, dict):
                            if _parsed_result.get("error") or _parsed_result.get("success") is False:
                                _error_count += 1
                            _record_followup_tool_result(_tool_entry.get("name"), _tool_result)
                            continue
                        if isinstance(_tool_result, str) and _tool_result.strip().lower().startswith("error"):
                            _error_count += 1
                    _followup_state["error_count"] = _error_count

                if _hooks_ref.loaded_hooks:
                    asyncio.run_coroutine_threadsafe(
                        _hooks_ref.emit("agent:step", {
                            "platform": source.platform.value if source.platform else "",
                            "user_id": source.user_id,
                            "session_id": session_id,
                            "iteration": iteration,
                            "tool_names": _names,
                            "tools": prev_tools,
                        }),
                        _loop_for_step,
                    )
                # COLMEIO_NODE_AGENT_STEP_SUMMARY_END
"""

NOTIFY_BLOCK = """                # COLMEIO_NODE_AGENT_FOLLOWUP_NOTIFY_BEGIN
                _status_detail = ""
                _activity = None
                if _agent_ref and hasattr(_agent_ref, "get_activity_summary"):
                    try:
                        _activity = _agent_ref.get_activity_summary()
                        _parts = [f"iteration {_activity['api_call_count']}/{_activity['max_iterations']}"]
                        if _activity.get("current_tool"):
                            _parts.append(f"running: {_activity['current_tool']}")
                        else:
                            _parts.append(_activity.get("last_activity_desc", ""))
                        _status_detail = " — " + ", ".join(_parts)
                    except Exception:
                        _activity = None

                _notify_message = f"⏳ Still working... ({_elapsed_mins} min elapsed{_status_detail})"
                if _followup_summary_enabled:
                    _summary_lines = _build_followup_summary_lines(_activity)
                    if _summary_lines:
                        _notify_message += "\\n👷summary:\\n" + "\\n".join(
                            f"- {line}" for line in _summary_lines
                        )

                try:
                    await _notify_adapter.send(
                        source.chat_id,
                        _notify_message,
                        metadata=_status_thread_metadata,
                    )
                    if _followup_summary_enabled:
                        _reset_followup_window()
                # COLMEIO_NODE_AGENT_FOLLOWUP_NOTIFY_END
"""

FINAL_BLOCK = """            # COLMEIO_NODE_AGENT_FINAL_FOOTER_BEGIN
            if _finalresponse_footer_enabled and final_response:
                try:
                    _footer = _build_files_changed_footer(
                        result.get("messages", []) if isinstance(result, dict) else [],
                        history_offset=len(agent_history),
                    )
                    if _footer:
                        final_response = final_response.rstrip() + "\\n\\n" + _footer
                except Exception as _footer_exc:
                    logger.debug("Final response footer generation failed: %s", _footer_exc)
            # COLMEIO_NODE_AGENT_FINAL_FOOTER_END
"""

RICH_HELPER_BLOCK = """        def _push_recent_line(bucket_key: str, value: str, limit: int) -> None:
            text = str(value or "").strip()
            if not text:
                return
            bucket = _followup_state.get(bucket_key)
            if not isinstance(bucket, list):
                bucket = []
                _followup_state[bucket_key] = bucket
            if bucket and str(bucket[-1]).strip().lower() == text.lower():
                return
            if text in bucket:
                bucket.remove(text)
            bucket.append(text)
            if len(bucket) > limit:
                del bucket[:-limit]

        def _reset_followup_window() -> None:
            _followup_state["window_started_at"] = time.time()
            _followup_state["window_tool_calls"] = 0
            _followup_state["window_errors"] = 0
            _followup_state["window_actions"] = []
            _followup_state["window_tool_names"] = []
            _followup_state["window_paths"] = []
            _followup_state["window_files"] = {}
            _followup_state["window_result_notes"] = []
            _followup_state["window_phase_counts"] = {
                "investigation": 0,
                "implementation": 0,
                "validation": 0,
                "coordination": 0,
            }

        def _path_hint_from_text(raw_text: Any) -> str:
            text = str(raw_text or "")
            if not text:
                return ""
            for match in re.findall(r"(/[-_A-Za-z0-9./]+)", text):
                candidate = _normalize_changed_path(match.strip(" ,;:()[]{}\\"'"))
                if not candidate or candidate in ("/", "/dev/null"):
                    continue
                if len(candidate) > 180:
                    continue
                return candidate
            return ""

        def _path_hint_from_args(raw_args: Any) -> str:
            if not isinstance(raw_args, dict):
                return ""
            for key in ("path", "file", "filepath", "target", "workdir", "cwd"):
                value = raw_args.get(key)
                hint = _normalize_changed_path(value)
                if hint:
                    return hint
            for key in ("files", "paths"):
                value = raw_args.get(key)
                if isinstance(value, list):
                    for entry in value:
                        hint = _normalize_changed_path(entry)
                        if hint:
                            return hint
            return ""

        def _describe_terminal_action(preview: Any, raw_args: Any) -> Dict[str, str]:
            command = ""
            if isinstance(raw_args, dict):
                for key in ("command", "cmd"):
                    candidate = raw_args.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        command = candidate.strip()
                        break
            if not command:
                command = str(preview or "").strip()

            lowered = command.lower()
            path_hint = _path_hint_from_text(command)
            phase = "implementation"
            note = "executing shell commands for implementation"

            if any(token in lowered for token in (
                "pytest", "unittest", "go test", "cargo test", "npm test",
                "pnpm test", "ruff ", "mypy ", "flake8 ", "python -m pytest",
            )):
                phase = "validation"
                note = "running tests and validation checks"
            elif any(token in lowered for token in (
                " rg ", "grep ", "find ", " ls ", "cat ", "head ", "tail ",
                "sed -n", "wc ", "du -", "stat ", "tree ",
            )) or lowered.startswith(("ls ", "cat ", "rg ", "grep ", "find ")):
                phase = "investigation"
                note = "inspecting files, logs, and runtime state"
            elif any(token in lowered for token in (
                "git status", "git diff", "git show", "git log", "git branch", "git rev-parse",
            )):
                phase = "investigation"
                note = "checking repository state and recent changes"
            elif any(token in lowered for token in (
                "mkdir ", "cp ", "mv ", "chmod ", "chown ", "ln -s", "touch ",
                "python ", "python3 ", "bash ", "sh ", "./",
            )):
                phase = "implementation"
                note = "updating scripts and local files"
            elif any(token in lowered for token in (
                "curl ", "wget ", "rclone ", "gdrive ", "http://", "https://",
            )):
                phase = "validation"
                note = "verifying external services and integrations"

            return {"phase": phase, "note": note, "path": path_hint}

        def _describe_tool_activity(tool_name: Any, preview: Any, raw_args: Any) -> Dict[str, str]:
            name = str(tool_name or "").strip()
            if name == "terminal":
                return _describe_terminal_action(preview, raw_args)

            path_hint = _path_hint_from_args(raw_args) or _path_hint_from_text(preview)
            phase = "implementation"
            note = ""

            if name in ("read_file", "search_files"):
                phase = "investigation"
                note = "reviewing files to gather context"
            elif name in ("patch", "write_file"):
                phase = "implementation"
                note = "applying file edits"
            elif name in ("todo",):
                phase = "coordination"
                note = "updating the task plan"
            elif name in ("process", "cronjob"):
                phase = "validation"
                note = "verifying background jobs and automation status"
            elif name in ("clarify", "delegate_task"):
                phase = "coordination"
                note = "coordinating next decisions and task split"
            elif name in ("execute_code", "python_exec", "code_interpreter"):
                phase = "validation"
                note = "running focused code probes and inspecting outputs"
            elif name in ("web_search", "browser_navigate", "browser_snapshot"):
                phase = "investigation"
                note = "gathering external context"

            if not note:
                phase = "implementation"
                note = f"working via {name or 'tool'}"

            return {"phase": phase, "note": note, "path": path_hint}

        def _record_followup_activity(tool_name: Any, preview: Any, raw_args: Any) -> None:
            info = _describe_tool_activity(tool_name, preview, raw_args)
            name = str(tool_name or "").strip()
            if name:
                _push_recent_line("window_tool_names", name, 10)

            note = str(info.get("note") or "").strip()
            if note:
                _push_recent_line("recent_actions", note, 6)
                _push_recent_line("window_actions", note, 8)

            path_hint = str(info.get("path") or "").strip()
            if path_hint:
                _push_recent_line("recent_paths", path_hint, 4)
                _push_recent_line("window_paths", path_hint, 6)

            phase = str(info.get("phase") or "").strip().lower()
            counts = _followup_state.get("phase_counts")
            if not isinstance(counts, dict):
                counts = {}
                _followup_state["phase_counts"] = counts
            if phase:
                counts[phase] = int(counts.get(phase, 0) or 0) + 1
                window_counts = _followup_state.get("window_phase_counts")
                if not isinstance(window_counts, dict):
                    window_counts = {}
                    _followup_state["window_phase_counts"] = window_counts
                window_counts[phase] = int(window_counts.get(phase, 0) or 0) + 1
            _followup_state["window_tool_calls"] = int(_followup_state.get("window_tool_calls", 0) or 0) + 1

        def _record_followup_tool_result(tool_name: Any, raw_result: Any) -> None:
            payload = _safe_parse_json_obj(raw_result)
            if not payload:
                return

            name = str(tool_name or "").strip()
            has_error = bool(payload.get("error")) or payload.get("success") is False
            if has_error:
                _followup_state["window_errors"] = int(_followup_state.get("window_errors", 0) or 0) + 1
                reason = str(payload.get("error") or "").strip()
                if reason:
                    compact_reason = reason.replace("\\n", " ").strip()
                    if len(compact_reason) > 140:
                        compact_reason = compact_reason[:137] + "..."
                    _push_recent_line("window_result_notes", f"tool error: {compact_reason}", 6)

            window_files_raw = _followup_state.get("window_files")
            if not isinstance(window_files_raw, dict):
                window_files_raw = {}
                _followup_state["window_files"] = window_files_raw
            window_files: Dict[str, Dict[str, int]] = window_files_raw

            changed_paths: List[str] = []
            for key in ("files_modified", "files_created", "files_deleted"):
                raw_paths = payload.get(key)
                if isinstance(raw_paths, list):
                    for raw_path in raw_paths:
                        path = _normalize_changed_path(raw_path)
                        if path:
                            changed_paths.append(path)

            diff_stats = _count_unified_diff(str(payload.get("diff") or ""))
            for path in changed_paths:
                _push_recent_line("window_paths", path, 6)
                window_files.setdefault(path, {"add": 0, "del": 0})

            if diff_stats:
                matched_any = False
                for path in changed_paths:
                    if path in diff_stats:
                        window_files[path]["add"] += int(diff_stats[path].get("add", 0) or 0)
                        window_files[path]["del"] += int(diff_stats[path].get("del", 0) or 0)
                        matched_any = True
                if not matched_any and changed_paths:
                    total_add = sum(int(v.get("add", 0) or 0) for v in diff_stats.values())
                    total_del = sum(int(v.get("del", 0) or 0) for v in diff_stats.values())
                    window_files[changed_paths[0]]["add"] += total_add
                    window_files[changed_paths[0]]["del"] += total_del

            if name in ("patch", "write_file") and changed_paths:
                _push_recent_line(
                    "window_result_notes",
                    f"captured edits in {len(set(changed_paths))} file(s)",
                    6,
                )
            elif has_error and not str(payload.get("error") or "").strip():
                _push_recent_line("window_result_notes", f"{name or 'tool'} returned an unsuccessful result", 6)

        def _followup_phase_summary() -> str:
            counts_raw = _followup_state.get("phase_counts")
            if not isinstance(counts_raw, dict):
                return ""
            counts = {
                "investigation": int(counts_raw.get("investigation", 0) or 0),
                "implementation": int(counts_raw.get("implementation", 0) or 0),
                "validation": int(counts_raw.get("validation", 0) or 0),
                "coordination": int(counts_raw.get("coordination", 0) or 0),
            }
            if counts["investigation"] and counts["implementation"] and counts["validation"]:
                return "iterating between investigation, edits, and validation"
            if counts["implementation"] and counts["validation"]:
                return "applying changes and validating them in loops"
            if counts["investigation"] and counts["implementation"]:
                return "mapping the current state and applying targeted fixes"

            top_phase = max(counts, key=lambda key: counts[key])
            if counts[top_phase] <= 0:
                return ""
            labels = {
                "investigation": "mapping the current state and gathering context",
                "implementation": "implementing and refining changes",
                "validation": "running validations and debugging results",
                "coordination": "coordinating execution steps",
            }
            return labels.get(top_phase, "")

        def _next_followup_hint(activity: Optional[Dict[str, Any]]) -> str:
            if not activity:
                return ""
            current_tool = str(activity.get("current_tool") or "").strip()
            if current_tool:
                if current_tool == "terminal":
                    return "running the next terminal command and checking results"
                if current_tool in ("execute_code", "python_exec", "code_interpreter"):
                    return "running the next code probe and validating the output"
                return f"running the next {current_tool} step"

            last_desc = str(activity.get("last_activity_desc") or "").strip()
            if not last_desc:
                return ""
            if last_desc.lower().startswith("starting api call"):
                window_errors = int(_followup_state.get("window_errors", 0) or 0)
                window_files_raw = _followup_state.get("window_files")
                window_files = window_files_raw if isinstance(window_files_raw, dict) else {}
                if window_errors > 0:
                    return "triaging recent tool errors and choosing the safest recovery step"
                if window_files:
                    return "choosing the next validation pass for the files changed in this window"
                return "selecting the next concrete tool step from the latest evidence"
            return last_desc
"""

RICH_SUMMARY_BLOCK = """        def _build_followup_summary_lines(activity: Optional[Dict[str, Any]]) -> List[str]:
            def _as_sentence(text: Any) -> str:
                sentence = str(text or "").strip()
                if not sentence:
                    return ""
                if sentence[-1] not in ".!?":
                    sentence += "."
                return sentence

            def _top_counts(entries: List[str], limit: int = 2) -> List[str]:
                counts: Dict[str, int] = {}
                order: List[str] = []
                for entry in entries:
                    text = str(entry or "").strip()
                    if not text:
                        continue
                    if text not in counts:
                        counts[text] = 0
                        order.append(text)
                    counts[text] += 1
                ranked = sorted(order, key=lambda item: (-counts[item], order.index(item)))
                result: List[str] = []
                for item in ranked[:limit]:
                    count = counts[item]
                    result.append(f"{item} ({count}x)" if count > 1 else item)
                return result

            lines: List[str] = []
            phase_summary = _followup_phase_summary()
            if phase_summary:
                lines.append(_as_sentence(f"Objective: {phase_summary}"))
            else:
                lines.append("Objective: keeping momentum while I work through the current plan.")

            window_started_at = float(_followup_state.get("window_started_at") or time.time())
            window_minutes = max(1, int((time.time() - window_started_at) // 60))
            window_tools = int(_followup_state.get("window_tool_calls", 0) or 0)
            window_files_raw = _followup_state.get("window_files")
            window_files = window_files_raw if isinstance(window_files_raw, dict) else {}
            window_tool_names_raw = _followup_state.get("window_tool_names")
            window_tool_names = [str(entry).strip() for entry in window_tool_names_raw] if isinstance(window_tool_names_raw, list) else []
            top_tool_names = _top_counts(window_tool_names, limit=3)
            window_notes_raw = _followup_state.get("window_result_notes")
            window_notes = [str(entry).strip() for entry in window_notes_raw] if isinstance(window_notes_raw, list) else []
            top_notes = _top_counts(window_notes, limit=2)

            if window_files:
                total_add = sum(int(v.get("add", 0) or 0) for v in window_files.values())
                total_del = sum(int(v.get("del", 0) or 0) for v in window_files.values())
                ranked_paths = sorted(
                    window_files.keys(),
                    key=lambda path: (
                        -(int(window_files[path].get("add", 0) or 0) + int(window_files[path].get("del", 0) or 0)),
                        path,
                    ),
                )
                path_bits: List[str] = []
                for path in ranked_paths[:3]:
                    add = int(window_files[path].get("add", 0) or 0)
                    dele = int(window_files[path].get("del", 0) or 0)
                    delta_bits: List[str] = []
                    if add:
                        delta_bits.append(f"+{add}")
                    if dele:
                        delta_bits.append(f"-{dele}")
                    suffix = f" ({' '.join(delta_bits)})" if delta_bits else ""
                    path_bits.append(f"{path}{suffix}")
                lines.append(
                    _as_sentence(
                        f"Evidence: in the last {window_minutes} min I ran {window_tools} tool step(s) and captured edits across "
                        f"{len(window_files)} file(s) (+{total_add} -{total_del}) in {'; '.join(path_bits)}"
                    )
                )
            else:
                window_actions_raw = _followup_state.get("window_actions")
                window_actions = [str(entry).strip() for entry in window_actions_raw] if isinstance(window_actions_raw, list) else []
                top_actions = _top_counts(window_actions, limit=2)
                evidence_bits: List[str] = []
                if top_tool_names:
                    evidence_bits.append(f"tools: {', '.join(top_tool_names)}")
                if top_actions:
                    evidence_bits.append(f"activity: {'; '.join(top_actions)}")
                if evidence_bits:
                    lines.append(
                        _as_sentence(
                            f"Evidence: in the last {window_minutes} min I ran {window_tools} tool step(s); {'; '.join(evidence_bits)}"
                        )
                    )
                elif window_tools > 0:
                    lines.append(_as_sentence(f"Evidence: in the last {window_minutes} min I ran {window_tools} tool step(s) and collected partial outputs"))
                else:
                    lines.append(_as_sentence(f"Evidence: minimal external progress in the last {window_minutes} min while preparing the next move"))

            error_count = int(_followup_state.get("error_count") or 0)
            window_errors = int(_followup_state.get("window_errors", 0) or 0)
            window_phase_counts_raw = _followup_state.get("window_phase_counts")
            window_phase_counts = window_phase_counts_raw if isinstance(window_phase_counts_raw, dict) else {}
            investigation_count = int(window_phase_counts.get("investigation", 0) or 0)
            implementation_count = int(window_phase_counts.get("implementation", 0) or 0)
            validation_count = int(window_phase_counts.get("validation", 0) or 0)
            coordination_count = int(window_phase_counts.get("coordination", 0) or 0)
            decision = ""
            if window_errors > 0:
                if implementation_count > 0:
                    decision = "prioritize corrective edits before broadening scope"
                else:
                    decision = "inspect failing outputs first, then pick a targeted recovery path"
            elif window_files:
                if validation_count > 0:
                    decision = "shift toward validation to confirm recent edits"
                else:
                    decision = "finish patching on touched files, then run targeted validation"
            elif investigation_count > 0 and implementation_count == 0:
                decision = "continue narrowing root cause before committing edits"
            elif implementation_count > 0 and validation_count == 0:
                decision = "translate gathered evidence into concrete file changes"
            elif coordination_count > 0 and (investigation_count + implementation_count + validation_count) == 0:
                decision = "stabilize task decomposition before the next tool sequence"
            elif window_tools > 0:
                decision = "keep iterating on the highest-signal tool path"
            elif error_count > 0:
                decision = "revisit recent failures to recover forward progress"

            if decision and top_notes:
                lines.append(_as_sentence(f"Decision: {decision}; latest signal: {'; '.join(top_notes)}"))
            elif decision:
                lines.append(_as_sentence(f"Decision: {decision}"))

            next_hint = _next_followup_hint(activity)
            looking_for_hint = ""
            if top_notes and not window_files:
                looking_for_hint = f"confirming {'; '.join(top_notes)}"
            else:
                window_paths_raw = _followup_state.get("window_paths")
                window_paths = [str(entry).strip() for entry in window_paths_raw] if isinstance(window_paths_raw, list) else []
                unique_window_paths: List[str] = []
                for path in window_paths:
                    if path and path not in unique_window_paths:
                        unique_window_paths.append(path)
                if unique_window_paths:
                    looking_for_hint = f"progress on {', '.join(unique_window_paths[:3])}"

            if next_hint:
                looking_for_hint = next_hint
            if looking_for_hint:
                lines.append(_as_sentence(f"Next step: {looking_for_hint}"))

            cleaned = [line for line in lines if line]
            if not cleaned:
                cleaned.append("Objective: collecting progress details for the next checkpoint.")
            return cleaned[:4]
"""


def _find_run_path() -> Path:
    for path in RUN_PATH_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(
        "Could not find gateway/run.py in expected locations:\n"
        + "\n".join(f"- {p}" for p in RUN_PATH_CANDIDATES)
    )


def _resolve_backup_dir(run_path: Path) -> Path:
    candidates = []

    if HERMES_HOME.exists() and HERMES_HOME.is_dir():
        candidates.append(HERMES_HOME / "logs" / "patch-backups")

    # Preferred fallback in dev shells without HERMES_HOME.
    candidates.append(Path("/tmp/hermes-patch-backups"))

    # Last resort: repository-local backup directory.
    candidates.append(run_path.parent.parent / ".patch-backups")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            continue

    raise RuntimeError("could not create a backup directory for patching")


def _replace_marker_block(content: str, start_marker: str, end_marker: str, block: str) -> tuple[str, bool, bool]:
    start = content.find(start_marker)
    if start < 0:
        return content, False, False
    line_start = content.rfind("\n", 0, start)
    start = 0 if line_start < 0 else line_start + 1
    end = content.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"found {start_marker} but missing {end_marker}")
    end += len(end_marker)
    line_end = content.find("\n", end)
    if line_end >= 0:
        end = line_end + 1
    replaced = content[:start] + block + content[end:]
    changed = replaced != content
    return replaced, changed, True


def _insert_before_anchor(content: str, marker: str, anchor: str, block: str) -> tuple[str, bool]:
    if marker in content:
        return content, False
    idx = content.find(anchor)
    if idx < 0:
        raise RuntimeError(f"anchor not found for {marker}: {anchor!r}")
    return content[:idx] + block + content[idx:], True


def _replace_once(content: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if new in content:
        return content, False
    if old not in content:
        raise RuntimeError(f"anchor not found for {label}")
    return content.replace(old, new, 1), True


def _replace_between(content: str, start_anchor: str, end_anchor: str, new_block: str, label: str) -> tuple[str, bool]:
    start = content.find(start_anchor)
    if start < 0:
        return content, False
    end = content.find(end_anchor, start)
    if end < 0:
        raise RuntimeError(f"anchor not found for {label}: {end_anchor!r}")
    replacement = new_block
    if not replacement.endswith("\n"):
        replacement += "\n"
    original = content[start:end]
    if original == replacement:
        return content, False
    return content[:start] + replacement + content[end:], True


def _apply_runtime_block(content: str) -> tuple[str, bool]:
    # If the richer summary helpers are already present inside the runtime
    # marker block, keep it as-is instead of downgrading to the base block.
    if (
        RUNTIME_START in content
        and RUNTIME_END in content
        and "def _push_recent_line(bucket_key: str, value: str, limit: int) -> None:" in content
        and '_append_paths("Created", created_paths)' in content
        and '_append_paths("Deleted", deleted_paths)' in content
    ):
        return content, False

    content, changed, found = _replace_marker_block(content, RUNTIME_START, RUNTIME_END, RUNTIME_BLOCK)
    if found:
        return content, changed

    anchor = "        # Bridge sync step_callback → async hooks.emit for agent:step events\n"
    return _insert_before_anchor(content, RUNTIME_START, anchor, RUNTIME_BLOCK)


def _apply_step_summary_block(content: str) -> tuple[str, bool]:
    content, changed, found = _replace_marker_block(content, STEP_START, STEP_END, STEP_BLOCK)
    if found:
        return content, changed

    old = """                _names: list[str] = []
                for _t in (prev_tools or []):
                    if isinstance(_t, dict):
                        _names.append(_t.get(\"name\") or \"\")
                    else:
                        _names.append(str(_t))
                asyncio.run_coroutine_threadsafe(
                    _hooks_ref.emit(\"agent:step\", {
                        \"platform\": source.platform.value if source.platform else \"\",
                        \"user_id\": source.user_id,
                        \"session_id\": session_id,
                        \"iteration\": iteration,
                        \"tool_names\": _names,
                        \"tools\": prev_tools,
                    }),
                    _loop_for_step,
                )
"""
    new = """                _names: list[str] = []
                for _t in (prev_tools or []):
                    if isinstance(_t, dict):
                        _names.append(_t.get(\"name\") or \"\")
                    else:
                        _names.append(str(_t))
""" + STEP_BLOCK

    return _replace_once(content, old, new, "step summary block")


def _apply_step_callback_assignment(content: str) -> tuple[str, bool]:
    old = "            agent.step_callback = _step_callback_sync if _hooks_ref.loaded_hooks else None\n"
    new = "            agent.step_callback = _step_callback_sync if (_hooks_ref.loaded_hooks or _followup_summary_enabled) else None\n"
    return _replace_once(content, old, new, "step callback assignment")


def _apply_notify_block(content: str) -> tuple[str, bool]:
    changed = False

    old_interval = """        # Periodic \"still working\" notifications for long-running tasks.
        # Fires every 10 minutes so the user knows the agent hasn't died.
        _NOTIFY_INTERVAL = 600  # 10 minutes
        _notify_start = time.time()
"""
    new_interval = """        # Periodic \"still working\" notifications for long-running tasks.
        # Interval is configurable per node via NODE_AGENT_FOLLOWUP_ELAPSED.
        _NOTIFY_INTERVAL = _followup_elapsed_minutes * 60
        _notify_start = time.time()
"""
    content, did = _replace_once(content, old_interval, new_interval, "notify interval")
    changed |= did

    if NOTIFY_START in content and NOTIFY_END in content:
        _start = content.find(NOTIFY_START)
        _end = content.find(NOTIFY_END, _start)
        if _start >= 0 and _end >= 0:
            _existing_notify = content[_start:_end]
            if "_build_followup_summary_lines" in _existing_notify and "_reset_followup_window()" in _existing_notify:
                return content, changed

    content, did, found = _replace_marker_block(content, NOTIFY_START, NOTIFY_END, NOTIFY_BLOCK)
    if found:
        changed |= did
        return content, changed

    old_notify = """                _status_detail = ""
                if _agent_ref and hasattr(_agent_ref, \"get_activity_summary\"):
                    try:
                        _a = _agent_ref.get_activity_summary()
                        _parts = [f\"iteration {_a['api_call_count']}/{_a['max_iterations']}\"]
                        if _a.get(\"current_tool\"):
                            _parts.append(f\"running: {_a['current_tool']}\")
                        else:
                            _parts.append(_a.get(\"last_activity_desc\", \"\"))
                        _status_detail = \" — \" + \", \".join(_parts)
                    except Exception:
                        pass
                try:
                    await _notify_adapter.send(
                        source.chat_id,
                        f\"⏳ Still working... ({_elapsed_mins} min elapsed{_status_detail})\",
                        metadata=_status_thread_metadata,
                    )
"""
    content, did = _replace_once(content, old_notify, NOTIFY_BLOCK, "notify summary block")
    changed |= did
    return content, changed


def _apply_final_footer_block(content: str) -> tuple[str, bool]:
    content, changed, found = _replace_marker_block(content, FOOTER_START, FOOTER_END, FINAL_BLOCK)
    if found:
        return content, changed

    anchor = "            # Sync session_id: the agent may have created a new session during\n"
    return _insert_before_anchor(content, FOOTER_START, anchor, FINAL_BLOCK)


def _apply_richer_followup_summary(content: str) -> tuple[str, bool]:
    changed = False

    old_coerce = """        def _coerce_node_int(raw_value: Any, default: int) -> int:
            try:
                if raw_value is None:
                    return default
                return int(str(raw_value).strip())
            except (TypeError, ValueError):
                return default
"""
    new_coerce = """        def _coerce_node_int(raw_value: Any, default: int) -> int:
            try:
                if raw_value is None:
                    return default
                value = str(raw_value).strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1].strip()
                return int(value)
            except (TypeError, ValueError):
                try:
                    match = re.search(r"-?\\d+", str(raw_value))
                    return int(match.group(0)) if match else default
                except Exception:
                    return default
"""
    if new_coerce in content:
        did = False
    elif old_coerce in content:
        content = content.replace(old_coerce, new_coerce, 1)
        did = True
    else:
        did = False
    changed |= did

    old_env_merge = """            for candidate in candidates:
                data = _parse_node_env_file(candidate)
                if data:
                    return data
            return {}
"""
    new_env_merge = """            merged: Dict[str, str] = {}
            for candidate in candidates:
                data = _parse_node_env_file(candidate)
                if not data:
                    continue
                for key, value in data.items():
                    if key not in merged and str(value).strip():
                        merged[key] = str(value).strip()
            return merged
"""
    if new_env_merge in content:
        did = False
    elif old_env_merge in content:
        content = content.replace(old_env_merge, new_env_merge, 1)
        did = True
    else:
        did = False
    changed |= did

    old_state = """        _followup_state: Dict[str, Any] = {
            "iteration": 0,
            "tool_names": [],
            "error_count": 0,
        }
"""
    old_state_with_windows = """        _followup_state: Dict[str, Any] = {
            "iteration": 0,
            "tool_names": [],
            "error_count": 0,
            "recent_actions": [],
            "recent_paths": [],
            "window_started_at": time.time(),
            "window_tool_calls": 0,
            "window_errors": 0,
            "window_actions": [],
            "window_paths": [],
            "window_files": {},
            "window_result_notes": [],
            "phase_counts": {
                "investigation": 0,
                "implementation": 0,
                "validation": 0,
                "coordination": 0,
            },
        }
"""
    new_state = """        _followup_state: Dict[str, Any] = {
            "iteration": 0,
            "tool_names": [],
            "error_count": 0,
            "recent_actions": [],
            "recent_paths": [],
            "window_started_at": time.time(),
            "window_tool_calls": 0,
            "window_errors": 0,
            "window_actions": [],
            "window_tool_names": [],
            "window_paths": [],
            "window_files": {},
            "window_result_notes": [],
            "window_phase_counts": {
                "investigation": 0,
                "implementation": 0,
                "validation": 0,
                "coordination": 0,
            },
            "phase_counts": {
                "investigation": 0,
                "implementation": 0,
                "validation": 0,
                "coordination": 0,
            },
        }
"""
    if "\"window_tool_names\": []" in content and "\"window_phase_counts\": {" in content:
        did = False
    elif new_state in content:
        did = False
    elif old_state_with_windows in content:
        content = content.replace(old_state_with_windows, new_state, 1)
        did = True
    elif old_state in content:
        content = content.replace(old_state, new_state, 1)
        did = True
    else:
        did = False
    changed |= did

    content, did = _insert_before_anchor(
        content,
        "def _push_recent_line(bucket_key: str, value: str, limit: int) -> None:",
        "        def _build_files_changed_footer(agent_messages: List[Dict[str, Any]], history_offset: int = 0) -> str:\n",
        RICH_HELPER_BLOCK,
    )
    changed |= did

    content, did = _replace_between(
        content,
        "        def _build_followup_summary_lines(activity: Optional[Dict[str, Any]]) -> List[str]:\n",
        "\n        # COLMEIO_NODE_AGENT_RUNTIME_END",
        RICH_SUMMARY_BLOCK,
        "rich followup summary",
    )
    changed |= did

    old_footer_tail = """            if not file_stats:
                return ""

            ordered_paths = sorted(file_stats.keys())
            total_add = sum(v.get("add", 0) for v in file_stats.values())
            total_del = sum(v.get("del", 0) for v in file_stats.values())
            lines = [f"## 📁 {len(ordered_paths)} Arquivos Modificados +{total_add} -{total_del}"]
            for path in ordered_paths:
                add = int(file_stats[path].get("add", 0))
                dele = int(file_stats[path].get("del", 0))
                deltas = []
                if add:
                    deltas.append(f"+{add}")
                if dele:
                    deltas.append(f"-{dele}")
                if not deltas:
                    deltas = ["+0", "-0"]
                lines.append(f"- {path} {' '.join(deltas)}")
            return "\\n".join(lines)
"""
    new_footer_tail = """            nonzero_stats = {
                path: stats
                for path, stats in file_stats.items()
                if int(stats.get("add", 0) or 0) or int(stats.get("del", 0) or 0)
            }
            if not nonzero_stats:
                return ""

            ordered_paths = sorted(nonzero_stats.keys())
            total_add = sum(int(v.get("add", 0) or 0) for v in nonzero_stats.values())
            total_del = sum(int(v.get("del", 0) or 0) for v in nonzero_stats.values())
            lines = [f"## 📁 {len(ordered_paths)} Files Changed +{total_add} -{total_del}"]
            for path in ordered_paths:
                add = int(nonzero_stats[path].get("add", 0) or 0)
                dele = int(nonzero_stats[path].get("del", 0) or 0)
                deltas = []
                if add:
                    deltas.append(f"+{add}")
                if dele:
                    deltas.append(f"-{dele}")
                if not deltas:
                    continue
                lines.append(f"- {path} {' '.join(deltas)}")
            return "\\n".join(lines)
"""
    if new_footer_tail in content:
        did = False
    elif old_footer_tail in content:
        content = content.replace(old_footer_tail, new_footer_tail, 1)
        did = True
    else:
        did = False
    changed |= did

    old_terminal_path_suffix = """            if path_hint:
                note = f"{note} ({path_hint})"
            return {"phase": phase, "note": note, "path": path_hint}
"""
    new_terminal_path_suffix = """            return {"phase": phase, "note": note, "path": path_hint}
"""
    if old_terminal_path_suffix in content:
        content = content.replace(old_terminal_path_suffix, new_terminal_path_suffix, 1)
        did = True
    else:
        did = False
    changed |= did

    old_tool_path_suffix = """            if path_hint:
                note = f"{note} ({path_hint})"

            return {"phase": phase, "note": note, "path": path_hint}
"""
    new_tool_path_suffix = """            return {"phase": phase, "note": note, "path": path_hint}
"""
    if old_tool_path_suffix in content:
        content = content.replace(old_tool_path_suffix, new_tool_path_suffix, 1)
        did = True
    else:
        did = False
    changed |= did

    old_progress = """            if progress_mode == "new" and tool_name == last_tool[0]:
                return
            last_tool[0] = tool_name
            
            # Build progress message with primary argument preview
"""
    new_progress = """            if progress_mode == "new" and tool_name == last_tool[0]:
                return
            last_tool[0] = tool_name

            # Feed richer long-running followup summaries with tool-level activity.
            try:
                if _followup_summary_enabled:
                    _record_followup_activity(tool_name, preview, args)
            except Exception:
                pass
            
            # Build progress message with primary argument preview
"""
    if new_progress in content:
        did = False
    elif old_progress in content:
        content = content.replace(old_progress, new_progress, 1)
        did = True
    else:
        did = False
    changed |= did

    return content, changed


def reapply() -> int:
    try:
        run_path = _find_run_path()
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    print(f"[apply] Node-agent followup/footer patch")
    print(f"[apply] run.py: {run_path}")

    original = run_path.read_text(encoding="utf-8")
    content = original
    changed_any = False

    try:
        for patch_fn in (
            _apply_runtime_block,
            _apply_step_summary_block,
            _apply_step_callback_assignment,
            _apply_notify_block,
            _apply_final_footer_block,
            _apply_richer_followup_summary,
        ):
            content, changed = patch_fn(content)
            changed_any |= changed
    except Exception as exc:
        modern_markers = (
            "def _step_callback_sync(iteration: int, prev_tools: list) -> None:",
            "agent.step_callback = _step_callback_sync if _hooks_ref.loaded_hooks else None",
            "HERMES_AGENT_NOTIFY_INTERVAL",
        )
        if all(marker in original for marker in modern_markers):
            print(
                "  [warn] legacy node-agent followup anchors not found; "
                "modern run.py flow detected, skipping patch."
            )
            return 0
        print(f"[error] failed to patch run.py: {exc}", file=sys.stderr)
        return 1

    if not changed_any:
        print("  [ok] run.py patch already applied")
        return 0

    backup_dir = _resolve_backup_dir(run_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"run.py.node_agent_followup_footer.{stamp}.bak"
    backup.write_text(original, encoding="utf-8")

    run_path.write_text(content, encoding="utf-8")
    print(f"  [ok] run.py patched: {run_path}")
    print(f"  [ok] backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(reapply())
