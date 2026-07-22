"""Public, deployment-safe wasm-agent app configuration shaping."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def projected_bridge_url(*, internal_url: str, deployment_mode: str, public_origin: str) -> str:
    origin = public_origin.rstrip("/")
    parsed = urlparse(origin)
    if deployment_mode == "cloud" and parsed.scheme == "https" and parsed.netloc:
        return f"{origin}/bridge"
    return internal_url.rstrip("/")


def payload(
    *,
    app_name: str,
    app_version: str,
    internal_bridge_url: str,
    agent_turn_timeout_sec: float,
    google_client_id: str,
    google_login_uri: str,
    public_origin: str,
    deployment_mode: str,
    instance_id: str,
    host_browser_enabled: bool,
    public_default_disabled: bool,
    shared_voice_enabled: bool,
    shared_voice_ice_servers: list[dict[str, Any]],
) -> dict[str, Any]:
    bridge_url = projected_bridge_url(
        internal_url=internal_bridge_url,
        deployment_mode=deployment_mode,
        public_origin=public_origin,
    )
    return {
        "appId": app_name,
        "service": app_name,
        "name": app_name,
        "version": app_version,
        "bridgeUrl": bridge_url,
        "agentTurnTimeoutSec": agent_turn_timeout_sec,
        "auth": {
            "googleClientId": google_client_id,
            "googleClientIdConfigured": bool(google_client_id),
            "googleLoginUri": google_login_uri,
            "publicOrigin": public_origin,
            "required": True,
            "userTable": "user_tb",
        },
        "deployment": {
            "mode": deployment_mode,
            "instanceId": instance_id,
            "clientFirst": True,
            "serverRole": "auth-sync-relay-backup-fleet",
        },
        "features": {
            "devHmr": {
                "enabled": deployment_mode != "cloud",
            },
            "hostBrowser": {
                "enabled": host_browser_enabled,
                "publicDefaultDisabled": public_default_disabled,
            },
            "sharedVoice": {
                "enabled": shared_voice_enabled,
                "productionDefaultDisabled": True,
                "iceServers": shared_voice_ice_servers,
                "signalingPollMs": 900,
            },
        },
        "bridge": {"owner": app_name, "url": bridge_url},
    }
