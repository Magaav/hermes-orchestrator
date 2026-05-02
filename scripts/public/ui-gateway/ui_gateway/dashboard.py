from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from .settings import GatewaySettings


def _helper_path(settings: GatewaySettings) -> Path:
    return (
        settings.repo_root
        / "hackaton-hermes-dashboard"
        / "plugin"
        / "dashboard"
        / "dashboard_metrics.py"
    ).resolve()


def _load_dashboard_module(settings: GatewaySettings) -> Any:
    module_path = _helper_path(settings)
    if not module_path.exists():
        raise FileNotFoundError(f"dashboard helper not found: {module_path}")

    module_name = f"ui_gateway_hackathon_dashboard_metrics_{abs(hash(str(module_path)))}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load dashboard helper from {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def discover_dashboard_nodes(settings: GatewaySettings) -> list[dict[str, Any]]:
    module = _load_dashboard_module(settings)
    return list(module.discover_dashboard_nodes(repo_root=settings.repo_root, agents_root=settings.agents_root))


def list_dashboard_nodes(settings: GatewaySettings) -> list[dict[str, Any]]:
    module = _load_dashboard_module(settings)
    return list(module.fleet_dashboard_nodes(repo_root=settings.repo_root, agents_root=settings.agents_root))


def _node_root(settings: GatewaySettings, node_name: str) -> Path:
    return settings.agents_root / "nodes" / node_name


def is_dashboard_node(settings: GatewaySettings, node_name: str) -> bool:
    return any(item.get("node") == node_name for item in discover_dashboard_nodes(settings))


def node_overview(settings: GatewaySettings, node_name: str) -> dict[str, Any]:
    module = _load_dashboard_module(settings)
    return module.node_overview(node_name=node_name, node_root=_node_root(settings, node_name))


def allowed_channels(settings: GatewaySettings, node_name: str) -> list[dict[str, Any]]:
    module = _load_dashboard_module(settings)
    return module.allowed_channels_for_node(node_name=node_name, node_root=_node_root(settings, node_name))


def channel_detail(settings: GatewaySettings, node_name: str, channel_id: str) -> dict[str, Any] | None:
    module = _load_dashboard_module(settings)
    return module.channel_detail(node_name=node_name, node_root=_node_root(settings, node_name), channel_id=channel_id)


def channel_series(settings: GatewaySettings, node_name: str, channel_id: str, window: str = "7d") -> dict[str, Any] | None:
    module = _load_dashboard_module(settings)
    return module.channel_series(
        node_name=node_name,
        node_root=_node_root(settings, node_name),
        channel_id=channel_id,
        window=window,
    )
