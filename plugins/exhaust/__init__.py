"""Hermes-native exhaust plugin.

The plugin is intentionally inert unless PLUGINS_EXHAUST=true is present in
the node environment. This keeps discovery safe and makes node env the source
of truth for activation.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

try:
    from . import runtime
except ImportError:
    _RUNTIME_PATH = Path(__file__).with_name("runtime.py")
    _SPEC = importlib.util.spec_from_file_location("exhaust_runtime", _RUNTIME_PATH)
    if _SPEC is None or _SPEC.loader is None:
        raise RuntimeError(f"failed to load runtime from {_RUNTIME_PATH}")
    runtime = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(runtime)


def register(ctx):
    runtime.register(ctx)
