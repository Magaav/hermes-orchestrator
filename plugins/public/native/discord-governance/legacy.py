"""Load legacy governance helpers without syncing them into Hermes hooks."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from .paths import (
    resolve_legacy_channel_acl_path,
    resolve_legacy_role_acl_path,
    resolve_legacy_slash_handlers_path,
)

_CACHE: dict[str, ModuleType] = {}


def _load_module(cache_key: str, module_path: Path) -> ModuleType:
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    if not module_path.exists():
        raise FileNotFoundError(f"legacy helper not found: {module_path}")
    spec = importlib.util.spec_from_file_location(cache_key, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load legacy helper from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[cache_key] = module
    spec.loader.exec_module(module)
    _CACHE[cache_key] = module
    return module


def load_role_acl_module() -> ModuleType:
    return _load_module(
        "native_discord_governance_role_acl",
        resolve_legacy_role_acl_path(),
    )


def load_channel_acl_module() -> ModuleType:
    return _load_module(
        "native_discord_governance_channel_acl",
        resolve_legacy_channel_acl_path(),
    )


def load_slash_handlers_module() -> ModuleType:
    module = _load_module(
        "native_discord_governance_slash_handlers",
        resolve_legacy_slash_handlers_path(),
    )
    setattr(module, "_refresh_runtime_channel_acl_copy", lambda payload: None)
    return module
