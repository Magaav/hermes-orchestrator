"""Hermes-native final-response-changed-files plugin."""

from __future__ import annotations

import importlib.util
from pathlib import Path

try:
    from . import runtime
except ImportError:
    _RUNTIME_PATH = Path(__file__).with_name("runtime.py")
    _SPEC = importlib.util.spec_from_file_location("final_response_changed_files_runtime", _RUNTIME_PATH)
    if _SPEC is None or _SPEC.loader is None:
        raise RuntimeError(f"failed to load runtime from {_RUNTIME_PATH}")
    runtime = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(runtime)


def register(ctx):
    ctx.register_hook("pre_llm_call", runtime.reset_turn_state)
    ctx.register_hook("pre_tool_call", runtime.record_pre_tool_snapshot)
    ctx.register_hook("post_tool_call", runtime.record_post_tool_result)
