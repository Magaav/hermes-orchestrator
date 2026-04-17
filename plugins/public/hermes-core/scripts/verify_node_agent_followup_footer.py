#!/usr/bin/env python3
"""Verify node-agent followup/footer markers in gateway/run.py."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


def _candidate_run_paths() -> list[Path]:
    home = _resolve_hermes_home()
    env_root = str(os.getenv("HERMES_AGENT_ROOT", "") or "").strip()
    out: list[Path] = []
    if env_root:
        out.append(Path(env_root).expanduser() / "gateway" / "run.py")
    out.extend([
        Path("/local/hermes-agent/gateway/run.py"),
        home / "hermes-agent" / "gateway" / "run.py",
        Path("/local/.hermes/hermes-agent/gateway/run.py"),
        Path("/home/ubuntu/.hermes/hermes-agent/gateway/run.py"),
    ])
    return out


def _find_run_path() -> Path:
    for path in _candidate_run_paths():
        if path.exists():
            return path
    raise FileNotFoundError("run.py not found in expected locations")


def main() -> int:
    try:
        run_path = _find_run_path()
    except Exception as exc:
        print(f"[error] {exc}")
        return 1

    text = run_path.read_text(encoding="utf-8")

    legacy_mode = "COLMEIO_NODE_AGENT_RUNTIME_BEGIN" in text

    if legacy_mode:
        checks: list[tuple[str, list[str]]] = [
            ("runtime_marker_begin", ["COLMEIO_NODE_AGENT_RUNTIME_BEGIN"]),
            ("runtime_marker_end", ["COLMEIO_NODE_AGENT_RUNTIME_END"]),
            ("step_marker_begin", ["COLMEIO_NODE_AGENT_STEP_SUMMARY_BEGIN"]),
            ("step_marker_end", ["COLMEIO_NODE_AGENT_STEP_SUMMARY_END"]),
            ("notify_marker_begin", ["COLMEIO_NODE_AGENT_FOLLOWUP_NOTIFY_BEGIN"]),
            ("notify_marker_end", ["COLMEIO_NODE_AGENT_FOLLOWUP_NOTIFY_END"]),
            ("footer_marker_begin", ["COLMEIO_NODE_AGENT_FINAL_FOOTER_BEGIN"]),
            ("footer_marker_end", ["COLMEIO_NODE_AGENT_FINAL_FOOTER_END"]),
            (
                "step_callback_gate",
                ["agent.step_callback = _step_callback_sync if (_hooks_ref.loaded_hooks or _followup_summary_enabled) else None"],
            ),
            ("notify_interval_env", ["_NOTIFY_INTERVAL = _followup_elapsed_minutes * 60"]),
            ("rich_activity_recorder", ["def _record_followup_activity(tool_name: Any, preview: Any, raw_args: Any) -> None"]),
            ("rich_summary_objective", ["Objective:"]),
            ("rich_summary_decision", ["Decision:"]),
            ("rich_window_tools", ['"window_tool_names": []']),
            ("rich_progress_hook", ["_record_followup_activity(tool_name, preview, args)"]),
        ]
    else:
        checks = [
            ("modern_step_callback_fn", ["def _step_callback_sync("]),
            (
                "modern_step_callback_gate",
                [
                    "agent.step_callback = _step_callback_sync if _hooks_ref.loaded_hooks else None",
                    "agent.step_callback = _step_callback_sync if (_hooks_ref.loaded_hooks or _followup_summary_enabled) else None",
                ],
            ),
            (
                "modern_notify_interval_env",
                [
                    "HERMES_AGENT_NOTIFY_INTERVAL",
                    "_NOTIFY_INTERVAL = _followup_elapsed_minutes * 60",
                ],
            ),
            (
                "modern_followup_send_typing",
                ["await _followup_adapter.send_typing("],
            ),
        ]

    failed = 0
    print(f"[verify] run.py: {run_path}")
    print(f"  [info] mode={'legacy-patched' if legacy_mode else 'modern-upstream'}")
    for label, markers in checks:
        matched = next((marker for marker in markers if marker in text), "")
        ok = bool(matched)
        detail = matched if matched else " | ".join(markers)
        print(f"  {'[ok]' if ok else '[!!]'} {label}: {detail}")
        if not ok:
            failed += 1

    if failed:
        print(f"[verify] failed ({failed} missing marker(s))")
        return 1

    print("[verify] success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
