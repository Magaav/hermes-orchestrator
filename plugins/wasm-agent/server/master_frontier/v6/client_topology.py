"""Compact, capability-owned topology for live application clients."""
from __future__ import annotations

from typing import Any


WINDOWS_PREFIXES = ("windows.", "companion.")


def primary(manifests: list[dict[str, Any]], required: set[str]) -> dict[str, Any]:
    if not manifests:
        return {}
    return max(enumerate(manifests), key=lambda pair: (
        len(required & set(pair[1].get("capabilities") or [])),
        len(pair[1].get("available_widget_ids") or []),
        -pair[0],
    ))[1]


def projection(manifests: list[dict[str, Any]], selected: dict[str, Any]) -> dict[str, Any]:
    members = []
    windows_actions: set[str] = set()
    for item in manifests[:8]:
        capabilities = {str(value) for value in (item.get("capabilities") or [])}
        windows_actions.update(value for value in capabilities if value.startswith(WINDOWS_PREFIXES))
        members.append({
            "client_id": str(item.get("client_id") or "")[:120],
            "runtime": str(item.get("runtime_type") or "unknown")[:40],
            "role": "primary" if item is selected else "capability-provider",
            "capability_count": len(capabilities),
            "windows_control": any(value.startswith(WINDOWS_PREFIXES) for value in capabilities),
        })
    environment = "windows-native" if windows_actions else str(selected.get("runtime_type") or "client")
    execution_realms = ["native_windows", "browser_sandbox"] if windows_actions else ["browser_sandbox"]
    has_cdp_kernel = any("run_hot_operation" in set(item.get("capabilities") or []) for item in manifests)
    browser_realms = ["browser_cdp_persistent", "browser_cdp_incognito"] if has_cdp_kernel else []
    active_execution_realm = execution_realms[0]
    return {
        "schema": "master.frontier.client_environment.v1",
        "environment": environment,
        "execution_realms": execution_realms,
        "active_execution_realm": active_execution_realm,
        "default_execution_realm": active_execution_realm,
        "renderer_role": "presentation_surface" if windows_actions else "execution_surface",
        "browser_realms": browser_realms,
        "default_browser_realm": "browser_cdp_persistent" if has_cdp_kernel else "unavailable",
        "primary_client_id": str(selected.get("client_id") or "")[:120],
        "members": members,
        "windows_actions": sorted(windows_actions),
        "binding": "live-registry-capability-owned",
    }


def summary(value: dict[str, Any]) -> str:
    return (
        f"Bound environment {value.get('environment')}; {len(value.get('members') or [])} live members; "
        f"active realm {value.get('active_execution_realm') or value.get('default_execution_realm') or 'browser_sandbox'}; "
        f"Windows control {'available on demand' if value.get('windows_actions') else 'unavailable'}; "
        f"default browser {value.get('default_browser_realm') or 'unavailable'}."
    )
