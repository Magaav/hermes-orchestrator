"""Topology-scoped initial capability projection for model-led V6 turns."""

from __future__ import annotations

from typing import Any


def initial_client_capabilities(
    catalog: Any, *, topology: dict[str, Any] | None = None,
) -> set[str]:
    """Expose the connected realm; leave semantic tool choice to the model."""
    topology = topology if isinstance(topology, dict) else {}
    realm = str(
        topology.get("active_execution_realm")
        or topology.get("default_execution_realm")
        or "browser_sandbox"
    )
    visible = sorted(
        str(item.get("id") or "")
        for item in catalog.all().values()
        if str(item.get("id") or "").startswith("client.")
        and str(item.get("id") or "") != "client.environment.inspect"
    )
    if realm == "native_windows":
        visible = [item for item in visible if item.startswith("client.windows.")]
        default_browser = "client.windows.browser.cdp.default.open"
        default_browser_tools = {
            default_browser,
            "client.windows.browser.cdp.status",
            "client.windows.browser.cdp.navigate",
            "client.windows.browser.cdp.inspect",
            "client.windows.browser.cdp.runtime.inspect",
            "client.windows.browser.cdp.act",
            "client.windows.browser.cdp.transaction",
            "client.windows.browser.cdp.procedure",
        }
        browser_prefix = "client.windows.browser.cdp."
        if default_browser in visible:
            visible = [
                item for item in visible
                if not item.startswith(browser_prefix) or item in default_browser_tools
            ]
    else:
        visible = [item for item in visible if not item.startswith("client.windows.")]
    return set(visible)
