"""Hermes-native Discord governance plugin."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_register_plugin():
    try:
        from .runtime import register_plugin as register_impl

        return register_impl
    except ImportError:
        package_root = Path(__file__).resolve().parent
        package_name = "_native_discord_governance"
        runtime_name = f"{package_name}.runtime"
        runtime_module = sys.modules.get(runtime_name)
        if runtime_module is None:
            package_module = sys.modules.get(package_name)
            if package_module is None:
                package_spec = importlib.util.spec_from_loader(package_name, loader=None, is_package=True)
                package_module = importlib.util.module_from_spec(package_spec)
                package_module.__path__ = [str(package_root)]  # type: ignore[attr-defined]
                sys.modules[package_name] = package_module
            runtime_spec = importlib.util.spec_from_file_location(runtime_name, package_root / "runtime.py")
            if runtime_spec is None or runtime_spec.loader is None:
                raise RuntimeError("failed to load discord governance runtime")
            runtime_module = importlib.util.module_from_spec(runtime_spec)
            runtime_module.__package__ = package_name
            sys.modules[runtime_name] = runtime_module
            runtime_spec.loader.exec_module(runtime_module)
        return runtime_module.register_plugin


register_plugin = _load_register_plugin()


def register(ctx):
    register_plugin(ctx)
