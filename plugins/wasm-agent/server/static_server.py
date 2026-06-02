#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import math
import mimetypes
import os
import queue
import re
import secrets
import select
import shutil
import socket
import sqlite3
import subprocess
import struct
import threading
import time
import uuid
import zipfile
from ipaddress import ip_address, ip_network
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import HTTPBasicAuthHandler, HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm, Request, build_opener, urlopen

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional runtime guard
    Image = None  # type: ignore[assignment]


PLUGIN_NAME = "wasm-agent"
PLUGIN_VERSION = "0.1.0"
DEPLOYMENT_MODE_LOCAL = "local"
DEPLOYMENT_MODE_CLOUD = "cloud"
IMAGE_CARD_ANALYZER_REVISION = "image-card-text-v2"
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DEFAULT_BROWSER_STREAM_FPS = 4.0
DEFAULT_BROWSER_STREAM_QUALITY = 62
DEFAULT_BROWSER_STREAM_EVERY_NTH_FRAME = 3
DEFAULT_BROWSER_SESSION_TTL_SEC = 30 * 60
DEFAULT_AGENT_BRIDGE_TIMEOUT_SEC = 30 * 60
DEFAULT_AGENT_IMAGE_MAX_BYTES = 1024 * 1024
DEFAULT_AGENT_IMAGE_LIMIT = 8
DEFAULT_AGENT_BRIDGE_IMAGE_BYTES = 900 * 1024
DEFAULT_AGENT_BRIDGE_IMAGE_SINGLE_BYTES = 640 * 1024
DEFAULT_AGENT_BRIDGE_REQUEST_BYTES = 1536 * 1024
DEFAULT_AGENT_BRIDGE_FORWARD_IMAGE_URLS = False
DEFAULT_AGENT_MODEL_SETUP_TIMEOUT_SEC = 6 * 60
DEFAULT_PROVIDER_PROXY_TIMEOUT_SEC = 45
DEFAULT_PROVIDER_MODELS_TIMEOUT_SEC = 15
PROVIDER_MODELS_CACHE_TTL_SEC = 10 * 60
DEFAULT_AGENT_ATTACHMENT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_AGENT_ATTACHMENT_STORE_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_AGENT_ATTACHMENT_STORE_MAX_FILES = 240
DEFAULT_AGENT_ATTACHMENT_MAX_AGE_SEC = 14 * 24 * 60 * 60
DEFAULT_CAMERA_SNAPSHOT_PROXY_TIMEOUT_SEC = 8
DEFAULT_CAMERA_SNAPSHOT_PROXY_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_CAMERA_STREAM_PROXY_TIMEOUT_SEC = 20
DEFAULT_CAMERA_STREAM_SESSION_TTL_SEC = 10 * 60
DEFAULT_CAMERA_STREAM_PROXY_CHUNK_BYTES = 64 * 1024
DEFAULT_CAMERA_RTSP_RELAY_TIMEOUT_SEC = 20
DEFAULT_CAMERA_RTSP_RELAY_FPS = 5
DEFAULT_CAMERA_RTSP_RELAY_QUALITY = 5
DEFAULT_CAMERA_RTSP_FRAME_TIMEOUT_SEC = 8
CAMERA_RTSP_MJPEG_BOUNDARY = "wasm-agent-rtsp"
DEFAULT_CAMERA_PUSH_RTMP_PORT = 1935
DEFAULT_CAMERA_PUSH_FRAME_FPS = 15
DEFAULT_CAMERA_PUSH_FRAME_QUALITY = 2
DEFAULT_CAMERA_PUSH_STALE_AFTER_SEC = 10
DEFAULT_CAMERA_PUSH_REPLAY_SEC = 5 * 60
DEFAULT_CAMERA_PUSH_REPLAY_MAX_SEC = 10 * 60
DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC = 10 * 60
DEFAULT_CAMERA_PUSH_ARCHIVE_RETENTION_SEC = 24 * 60 * 60
DEFAULT_CAMERA_PUSH_PLAYBACK_FPS = 15
DEFAULT_CAMERA_PUSH_PLAYBACK_RETENTION_SEC = DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC
DEFAULT_CAMERA_PUSH_PLAYBACK_SAMPLE_SEC = 1 / DEFAULT_CAMERA_PUSH_PLAYBACK_FPS
DEFAULT_CAMERA_PUSH_PLAYBACK_GAP_SEC = 5.0
DEFAULT_CAMERA_PUSH_TIMELINE_SAMPLE_SEC = 30
CAMERA_PUSH_MJPEG_BOUNDARY = "wasm-agent-push"
CAMERA_PUSH_SCHEMA = "hermes.wasm_agent.camera.push_ingest.v1"
PRIVATE_IPV4_RANGES = (
    (ip_network("10.0.0.0/8"), "10.0.0.0/8"),
    (ip_network("172.16.0.0/12"), "172.16.0.0/12"),
    (ip_network("192.168.0.0/16"), "192.168.0.0/16"),
)
DEFAULT_USER_QUOTA_BYTES = 1024 * 1024 * 1024
SPACE_AREA_MIN_PX = 1
SPACE_AREA_MAX_PX = 2000
DEVICE_ONLINE_WINDOW_SEC = 3 * 60
NATIVE_COMPANION_PACKAGE_SCHEMA = "hermes.wasm_agent.native_companion_package.v1"
NATIVE_DEVICE_PROFILE_SCHEMA = "hermes.wasm_agent.native_device_profile.v1"
SECURITY_LOOP_STALE_AFTER_SEC = 24 * 60 * 60
WASM_AGENT_SNOWFLAKE_EPOCH_MS = 1767225600000
DEFAULT_WA_ENV_PATH = Path(__file__).resolve().parents[1] / "conf" / "wa.env"
DEFAULT_AUTH_DB_PATH = Path(__file__).resolve().parents[1] / "state" / "db" / "sqlite" / "wa_db.sqlite3"
DEFAULT_AUTH_SECRET_PATH = Path(__file__).resolve().parents[1] / "state" / "db" / "sqlite" / "wa_auth_secret"
AUTH_COOKIE_MAX_AGE_SEC = 60 * 60 * 24 * 30
ACTIVE_BRIDGE_TASK_STATUSES = {"active", "in_progress", "pending", "queued", "running", "started", "stopping", "submitted", "working"}
PROVIDER_MODELS_URLS = {
    "openrouter": "https://openrouter.ai/api/v1/models",
    "opencode-go": "https://opencode.ai/zen/go/v1/models",
}
PROVIDER_MODELS_CACHE: dict[str, dict[str, Any]] = {}
CORE_FIRMWARE_PREFIXES = (
    "docs/roadmap/",
    "plugins/wasm-agent/ARTIFACTS.md",
    "plugins/wasm-agent/DESIGN.md",
    "plugins/wasm-agent/README.md",
    "plugins/wasm-agent/conf/",
    "plugins/wasm-agent/public/",
    "plugins/wasm-agent/scripts/",
    "plugins/wasm-agent/server/",
    "plugins/wasm-agent/tests/",
)
WIS_SPACE_SCHEMA = "hermes.wasm_agent.wis.space.v1"
WIS_PATCH_SCHEMA = "hermes.wasm_agent.wis.patch.v1"
WIS_PATCH_RESULT_SCHEMA = "hermes.wasm_agent.wis.patch_result.v1"
BUILT_IN_SPACE_IDS = {"home", "admin"}
BUILT_IN_SPACE_ID_ALIASES = {
    "space-home": "home",
    "space-admin": "admin",
}
RESERVED_USER_SPACE_IDS = BUILT_IN_SPACE_IDS | set(BUILT_IN_SPACE_ID_ALIASES)
WIS_CURRENT_SPACE_SENTINELS = {
    "active",
    "active-space",
    "active_space",
    "active-space-id",
    "active_space_id",
    "current",
    "current-space",
    "current_space",
    "current-space-id",
    "current_space_id",
    "current-wasm-agent-space",
}
CLIENT_SNAPSHOT_SCHEMA = "hermes.wasm_agent.client_snapshot.v1"
CLIENT_SNAPSHOT_REQUEST_SCHEMA = "hermes.wasm_agent.client_snapshot.request.v1"
CLIENT_SNAPSHOT_RESPONSE_SCHEMA = "hermes.wasm_agent.client_snapshot.response.v1"
CLIENT_SNAPSHOT_HISTORY_LIMIT = 12
CLIENT_SNAPSHOT_MAX_STORED_BYTES = 1024 * 1024
SHARED_SPACE_SCHEMA = "hermes.wasm_agent.shared_space.v1"
SHARED_SPACE_LIST_SCHEMA = "hermes.wasm_agent.shared_spaces.v1"
SHARED_SPACE_ROOM_SCHEMA = "hermes.wasm_agent.shared_space.room.v1"
SHARED_SPACE_ROOM_EVENT_SCHEMA = "hermes.wasm_agent.shared_space.room_event.v1"
SHARED_SPACE_PRESENCE_SCHEMA = "hermes.wasm_agent.shared_space.presence.v1"
SHARED_SPACE_POINTER_BINARY_MAGIC = b"WAPB"
SHARED_SPACE_POINTER_BINARY_HEADER_BYTES = 36
SHARED_SPACE_POINTER_BINARY_SAMPLE_BYTES = 10
SHARED_SPACE_POINTER_BINARY_MAX_SAMPLES = 32
SHARED_SPACE_PRESENCE_TTL_SEC = 20
SHARED_SPACE_EVENT_LIMIT = 240
SHARED_SPACE_ROOM_PUBLIC_EVENT_LIMIT = 80
SHARED_SPACE_SIGNAL_TEXT_LIMIT = 131072
SYNC_EVENT_SCHEMA = "hermes.wasm_agent.sync.event.v1"
SYNC_EVENT_LIST_SCHEMA = "hermes.wasm_agent.sync.events.v1"
FRIENDSHIP_SCHEMA = "hermes.wasm_agent.friendship.v1"
FRIENDSHIP_LIST_SCHEMA = "hermes.wasm_agent.friendships.v1"
USER_FLEET_SCHEMA = "hermes.wasm_agent.user_fleet.v1"
USER_FLEET_NODE_SCHEMA = "hermes.wasm_agent.user_fleet.node.v1"
AGENT_READINESS_SCHEMA = "hermes.wasm_agent.agent_readiness.v1"
ACCOUNT_CREDITS_SCHEMA = "hermes.wasm_agent.account_credits.v1"
FLUX_LEDGER_ROW_SCHEMA = "hermes.wasm_agent.flux_ledger.row.v1"
FLUX_PROVISION_SCHEMA = "hermes.wasm_agent.fleet.provision_main.v1"
SYNC_EVENT_PAYLOAD_LIMIT = 24 * 1024
SYNC_EVENT_REQUEST_MAX_BYTES = 4 * 1024 * 1024
SYNC_EVENT_PAGE_LIMIT = 120
REMOTE_CONTROL_FRAME_PAYLOAD_LIMIT = 3 * 1024 * 1024
REMOTE_CONTROL_FRAME_EVENT_KEEP = 8
REMOTE_CONTROL_EVENT_KINDS = {
    "remote-control-request",
    "remote-control-response",
    "remote-control-action",
    "remote-control-frame",
    "remote-control-stop",
}
REMOTE_CONTROL_ADMIN_REPLY_KINDS = {"remote-control-response", "remote-control-frame", "remote-control-stop"}
FRIENDSHIP_VISIBLE_STATUSES = {"pending", "accepted"}
FRIENDSHIP_TERMINAL_STATUSES = {"declined", "canceled", "removed"}
VOICE_LAB_ROOM_SCHEMA = "hermes.wasm_agent.voice_lab.room.v1"
VOICE_LAB_ROOM_EVENT_SCHEMA = "hermes.wasm_agent.voice_lab.room_event.v1"
VOICE_LAB_PRESENCE_SCHEMA = "hermes.wasm_agent.voice_lab.presence.v1"
VOICE_LAB_PRESENCE_TTL_SEC = 20
VOICE_LAB_EVENT_LIMIT = 240
VOICE_LAB_ROOM_PUBLIC_EVENT_LIMIT = 120
GLOBAL_AGENT_NODE_IDS = {"admin-orchestrator", "hermes-orchestrator", "orchestrator"}
AGENT_DEFAULT_SANDBOX_NODE_ID = "account-sandbox"
AGENT_READINESS_READY = "ready"
AGENT_READINESS_BACKEND_UNAVAILABLE = "backend_unavailable"
AGENT_READINESS_SANDBOX_NOT_PROVISIONED = "sandbox_not_provisioned"
AGENT_READINESS_SANDBOX_BILLING_INCOMPLETE = "sandbox_billing_incomplete"
AGENT_READINESS_INSUFFICIENT_FLUX = "insufficient_flux"
AGENT_READINESS_PROVIDER_NOT_AVAILABLE = "provider_not_available"
AGENT_HARNESS_SCHEMA = "hermes.wasm_agent.agent_harness.v1"
AGENT_HARNESS_PROVISION_SCHEMA = "hermes.wasm_agent.agent_harness.provision.v1"
AGENT_HARNESS_LIFECYCLE_STATES = {"requested", "charging", "provisioning", "ready", "failed", "stopped", "archived"}
AGENT_HARNESS_INFRA_MODES = {"hermes_backend", "custom_bridge"}
AGENT_HARNESS_TYPE = "hermes"
FLUX_MAIN_NODE_PROVISION_COST = 100
FLUX_AGENT_HARNESS_COST = 10
FLUX_MAIN_NODE_PROVIDER = "opencode-go"
FLUX_MAIN_NODE_MODEL = "deepseek-v4-flash"
AGENT_MUTATION_ALLOWED_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
AGENT_MUTATION_MAX_OPS = 8
AGENT_MUTATION_MAX_FILE_BYTES = 2 * 1024 * 1024
AGENT_MUTATION_MAX_TOTAL_REPLACE_BYTES = 128 * 1024
_SNOWFLAKE_LOCK = threading.Lock()
_SNOWFLAKE_LAST_MS = -1
_SNOWFLAKE_SEQUENCE = 0


class WasmAgentServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[SimpleHTTPRequestHandler],
        *,
        plugin_root: Path,
        public_root: Path,
        state_dir: Path,
        bridge_url: str,
        browser_timeout_sec: float,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.plugin_root = plugin_root
        self.public_root = public_root
        self.state_dir = state_dir
        self.bridge_url = bridge_url.rstrip("/")
        self.browser_timeout_sec = browser_timeout_sec
        self.browser_sessions: dict[str, dict[str, Any]] = {}
        self.browser_sessions_lock = threading.Lock()
        self.camera_stream_sessions: dict[str, dict[str, Any]] = {}
        self.camera_stream_sessions_lock = threading.Lock()
        self.camera_push_processes: dict[str, subprocess.Popen[bytes]] = {}
        self.camera_push_processes_lock = threading.Lock()
        self.remote_control_live_clients: dict[str, set[Any]] = {}
        self.remote_control_live_clients_lock = threading.Lock()
        self.shared_space_live_clients: dict[str, set[Any]] = {}
        self.shared_space_live_clients_lock = threading.Lock()


def endpoint_path(path: str, endpoint: str) -> bool:
    return path == endpoint or path.endswith(endpoint)


class WasmAgentHandler(SimpleHTTPRequestHandler):
    server: WasmAgentServer
    server_version = "wasm-agent"
    sys_version = ""

    def __init__(self, *args: Any, directory: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.getenv("HERMES_WASM_AGENT_ACCESS_LOG", "").lower() in {"1", "true", "yes", "on"}:
            super().log_message(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        user = authenticated_request_user(self)
        if not is_public_request("GET", path) and not user:
            self._json(
                HTTPStatus.UNAUTHORIZED,
                {"ok": False, "error": {"code": "auth_required", "message": "Account sign-in is required."}},
            )
            return
        if user and requires_admin_request("GET", path) and not user_is_admin(user):
            self._json(
                HTTPStatus.FORBIDDEN,
                {"ok": False, "error": {"code": "admin_required", "message": "Admin access is required."}},
            )
            return
        if path == "/browser/stream":
            try:
                require_browser_feature_enabled(self)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
                return
            if not same_origin_websocket(self):
                self._json(
                    HTTPStatus.FORBIDDEN,
                    {
                        "ok": False,
                        "error": {
                            "code": "origin_rejected",
                            "message": "WebSocket origin does not match this wasm-agent host.",
                        },
                    },
                )
                return
            serve_browser_stream(self)
            return
        if path == "/remote-control/live":
            if not same_origin_websocket(self):
                self._json(
                    HTTPStatus.FORBIDDEN,
                    {
                        "ok": False,
                        "error": {
                            "code": "origin_rejected",
                            "message": "WebSocket origin does not match this wasm-agent host.",
                        },
                    },
                )
                return
            serve_remote_control_live(self, user)
            return
        if path == "/spaces/room/live":
            if not same_origin_websocket(self):
                self._json(
                    HTTPStatus.FORBIDDEN,
                    {
                        "ok": False,
                        "error": {
                            "code": "origin_rejected",
                            "message": "WebSocket origin does not match this wasm-agent host.",
                        },
                    },
                )
                return
            serve_shared_space_room_live(self, user)
            return
        if path == "/camera/stream":
            try:
                token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
                serve_camera_stream_proxy(self, token)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_stream_proxy_error", "message": str(exc)}},
                )
            return
        if path == "/camera/rtsp-stream":
            try:
                token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
                serve_camera_rtsp_mjpeg_proxy(self, token)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_rtsp_stream_error", "message": str(exc)}},
                )
            return
        if endpoint_path(path, "/camera/push-frame"):
            try:
                query = parse_qs(urlparse(self.path).query)
                stream_id = (query.get("stream_id") or query.get("stream") or ["cam-1"])[0]
                serve_camera_push_frame(self, stream_id)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_push_frame_error", "message": str(exc)}},
                )
            return
        if endpoint_path(path, "/camera/push-stream"):
            try:
                query = parse_qs(urlparse(self.path).query)
                stream_id = (query.get("stream_id") or query.get("stream") or ["cam-1"])[0]
                serve_camera_push_mjpeg_stream(self, stream_id)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_push_stream_error", "message": str(exc)}},
                )
            return
        if endpoint_path(path, "/camera/push-playback"):
            try:
                query = parse_qs(urlparse(self.path).query)
                stream_id = (query.get("stream_id") or query.get("stream") or ["cam-1"])[0]
                from_ms = (query.get("from_ms") or query.get("timestamp_ms") or query.get("from") or [""])[0]
                seconds = (query.get("seconds") or query.get("sec") or [""])[0]
                follow = (query.get("follow") or ["1"])[0]
                serve_camera_push_playback(self, stream_id, from_ms, seconds, follow)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_push_playback_error", "message": str(exc)}},
                )
            return
        if endpoint_path(path, "/camera/push-replay"):
            try:
                query = parse_qs(urlparse(self.path).query)
                stream_id = (query.get("stream_id") or query.get("stream") or ["cam-1"])[0]
                seconds = (query.get("seconds") or query.get("sec") or [""])[0]
                serve_camera_push_replay(self, stream_id, seconds)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_push_replay_error", "message": str(exc)}},
                )
            return
        if endpoint_path(path, "/camera/push-timeline"):
            try:
                query = parse_qs(urlparse(self.path).query)
                stream_id = (query.get("stream_id") or query.get("stream") or ["cam-1"])[0]
                day = (query.get("day") or [""])[0]
                mode = (query.get("mode") or ["live"])[0]
                seconds = (query.get("seconds") or query.get("sec") or [""])[0]
                self._json(HTTPStatus.OK, camera_push_timeline(self.server, stream_id, day, mode, seconds))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_push_timeline_error", "message": str(exc)}},
                )
            return
        if endpoint_path(path, "/camera/push-archive-frame"):
            try:
                query = parse_qs(urlparse(self.path).query)
                stream_id = (query.get("stream_id") or query.get("stream") or ["cam-1"])[0]
                frame = (query.get("frame") or query.get("id") or [""])[0]
                serve_camera_push_archive_frame(self, stream_id, frame)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_push_archive_frame_error", "message": str(exc)}},
                )
            return
        if endpoint_path(path, "/camera/push/status"):
            try:
                query = parse_qs(urlparse(self.path).query)
                stream_id = (query.get("stream_id") or query.get("stream") or ["cam-1"])[0]
                self._json(HTTPStatus.OK, camera_push_status(self.server, stream_id, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_push_status_error", "message": str(exc)}},
                )
            return
        if path.startswith("/bridge/"):
            try:
                self._json(HTTPStatus.OK, bridge_proxy(self.server, "GET", self.path.removeprefix("/bridge"), None))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/modules/hmr/events":
            serve_dev_hmr_events(self)
            return
        if path.startswith("/agent/attachments/"):
            try:
                serve_agent_attachment(self, path, user)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/health":
            self._json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "health": {
                        "name": PLUGIN_NAME,
                        "version": PLUGIN_VERSION,
                        "status": "ok",
                        "bridge_url": self.server.bridge_url,
                        "public_root": str(self.server.public_root),
                        "wasm_core": "embedded",
                    },
                },
            )
            return
        if path == "/auth/session":
            try:
                self._json(HTTPStatus.OK, auth_session(self.server, self.headers.get("Cookie", "")))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/auth/google/callback":
            self._redirect("/home")
            return
        if path == "/config.json":
            self._json(
                HTTPStatus.OK,
                {
                    "name": PLUGIN_NAME,
                    "version": PLUGIN_VERSION,
                    "bridgeUrl": self.server.bridge_url,
                    "agentTurnTimeoutSec": agent_bridge_timeout_sec(),
                    "auth": {
                        "googleClientId": google_client_id(),
                        "googleClientIdConfigured": bool(google_client_id()),
                        "googleLoginUri": google_login_uri(self),
                        "publicOrigin": public_origin(),
                        "required": True,
                        "userTable": "user_tb",
                    },
                    "deployment": {
                        "mode": wasm_agent_deployment_mode(),
                        "instanceId": cloud_instance_id(),
                        "clientFirst": True,
                        "serverRole": "auth-sync-relay-backup-fleet",
                    },
                    "features": {
                        "hostBrowser": {
                            "enabled": browser_feature_enabled(self),
                            "publicDefaultDisabled": public_deployment(self),
                        },
                        "sharedVoice": {
                            "enabled": shared_voice_enabled(),
                            "productionDefaultDisabled": True,
                            "iceServers": shared_voice_ice_servers(),
                            "signalingPollMs": 900,
                        },
                    },
                    "bridge": {
                        "owner": "wasm-agent",
                        "url": self.server.bridge_url,
                    },
                },
            )
            return
        if path == "/observation/latest":
            try:
                self._json(HTTPStatus.OK, latest_observation(self.server, user))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/client/snapshot":
            try:
                self._json(HTTPStatus.OK, latest_client_snapshot(self.server, user))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/client/snapshot/request":
            try:
                query = parse_qs(urlparse(self.path).query)
                status = str((query.get("status") or ["pending"])[0] or "pending")
                self._json(HTTPStatus.OK, list_client_snapshot_requests(self.server, user, status=status))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/timeline/status":
            try:
                query = parse_qs(urlparse(self.path).query)
                space_id = str((query.get("space") or ["home"])[0] or "home")
                self._json(HTTPStatus.OK, {"ok": True, "timeline": timeline_status(self.server, user, space_id=space_id)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/spaces":
            try:
                self._json(HTTPStatus.OK, list_user_spaces(self.server, user, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/spaces/shared":
            try:
                self._json(HTTPStatus.OK, list_shared_spaces(self.server, user))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/spaces/room":
            try:
                query = parse_qs(urlparse(self.path).query)
                body = {
                    "action": "read",
                    "shared_space_id": str((query.get("shared_space_id") or query.get("shared_space") or [""])[0] or ""),
                    "space_id": str((query.get("space_id") or query.get("space") or [""])[0] or ""),
                }
                self._json(HTTPStatus.OK, shared_space_room(self.server, user, body, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/voice-lab/room":
            try:
                query = parse_qs(urlparse(self.path).query)
                body = {
                    "action": "read",
                    "room_id": str((query.get("room_id") or query.get("room") or [""])[0] or ""),
                }
                self._json(HTTPStatus.OK, voice_lab_room(self.server, user, body, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/wis/artifacts":
            try:
                query = parse_qs(urlparse(self.path).query)
                space_id = str((query.get("space") or ["home"])[0] or "home")
                shared_space_id = str((query.get("shared_space") or [""])[0] or "")
                self._json(HTTPStatus.OK, list_wis_artifacts(self.server, user, space_id, shared_space_id=shared_space_id))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        wis_artifact_match = re.fullmatch(r"/wis/artifacts/([A-Za-z0-9_-]+)", path)
        if wis_artifact_match:
            try:
                query = parse_qs(urlparse(self.path).query)
                space_id = str((query.get("space") or ["home"])[0] or "home")
                shared_space_id = str((query.get("shared_space") or [""])[0] or "")
                self._json(HTTPStatus.OK, read_wis_artifact(self.server, user, space_id, wis_artifact_match.group(1), shared_space_id=shared_space_id))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/storage/export":
            try:
                self._json(HTTPStatus.OK, export_user_storage(self.server, user, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/account/devices":
            try:
                self._json(HTTPStatus.OK, list_account_devices(self.server, user, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/account/users/lookup":
            try:
                query = parse_qs(urlparse(self.path).query)
                value = str((query.get("q") or query.get("query") or [""])[0] or "")
                self._json(HTTPStatus.OK, account_user_lookup(value, user))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/account/friends":
            try:
                self._json(HTTPStatus.OK, list_friendships(user))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/account/credits":
            try:
                self._json(HTTPStatus.OK, account_credits(user))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/sync/events":
            try:
                query = parse_qs(urlparse(self.path).query)
                self._json(HTTPStatus.OK, list_sync_events(self.server, user, query))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/agent/readiness":
            try:
                query = parse_qs(urlparse(self.path).query)
                target_node = str((query.get("target_node") or query.get("node_id") or [""])[0] or "")
                self._json(HTTPStatus.OK, agent_readiness(self.server, user, target_node=target_node))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/agent/provider/models":
            try:
                query = parse_qs(urlparse(self.path).query)
                provider = str((query.get("provider") or [""])[0] or "")
                self._json(HTTPStatus.OK, provider_models_catalog(provider))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/fleet":
            try:
                self._json(HTTPStatus.OK, list_user_fleet(user))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/security-loop/status":
            try:
                self._json(HTTPStatus.OK, security_loop_status(self.server))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/security-loop/findings":
            try:
                query = parse_qs(urlparse(self.path).query)
                limit = int(str((query.get("limit") or ["80"])[0] or "80"))
                self._json(HTTPStatus.OK, list_security_loop_findings(self.server, limit=limit))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": {"code": "invalid_limit", "message": "limit must be a number."}})
            return
        if path == "/security-loop/runs":
            try:
                query = parse_qs(urlparse(self.path).query)
                limit = int(str((query.get("limit") or ["24"])[0] or "24"))
                self._json(HTTPStatus.OK, list_security_loop_runs(self.server, limit=limit))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": {"code": "invalid_limit", "message": "limit must be a number."}})
            return
        super().do_GET()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        origin = request_origin(self)
        allowed = {item for item in {public_origin(), request_host_origin(self)} if item}
        if origin and origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        user = authenticated_request_user(self)
        if not is_public_request("POST", path) and not user:
            self._json(
                HTTPStatus.UNAUTHORIZED,
                {"ok": False, "error": {"code": "auth_required", "message": "Account sign-in is required."}},
            )
            return
        if requires_admin_request("POST", path) and not user_is_admin(user):
            self._json(
                HTTPStatus.FORBIDDEN,
                {"ok": False, "error": {"code": "admin_required", "message": "Admin access is required."}},
            )
            return
        if not is_public_request("POST", path) and not same_origin_post(self):
            self._json(
                HTTPStatus.FORBIDDEN,
                {"ok": False, "error": {"code": "origin_rejected", "message": "POST origin does not match this wasm-agent host."}},
            )
            return
        if path == "/browser/open":
            try:
                require_browser_feature_enabled(self)
                body = self._read_json()
                self._json(HTTPStatus.OK, {"ok": True, "browser": capture_browser(self.server, body)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "browser_error", "message": str(exc)}},
                )
            return
        if path.startswith("/bridge/"):
            try:
                body = self._read_json(max_bytes=1024 * 1024)
                self._json(HTTPStatus.OK, bridge_proxy(self.server, "POST", self.path.removeprefix("/bridge"), body))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "bridge_proxy_error", "message": str(exc)}},
                )
            return
        if path == "/browser/input":
            try:
                require_browser_feature_enabled(self)
                body = self._read_json()
                self._json(HTTPStatus.OK, {"ok": True, "browser": browser_input(self.server, body)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "browser_error", "message": str(exc)}},
                )
            return
        if path == "/browser/close":
            try:
                require_browser_feature_enabled(self)
                body = self._read_json()
                self._json(HTTPStatus.OK, {"ok": True, "browser": close_browser_session(self.server, body)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/account/devices/sync":
            try:
                body = self._read_json(max_bytes=256 * 1024)
                self._json(HTTPStatus.OK, create_device_sync_package(self.server, user, body, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/account/devices/native":
            try:
                body = self._read_json(max_bytes=256 * 1024)
                self._json(HTTPStatus.OK, create_native_companion_package(self.server, user, body, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/account/devices/native/download":
            try:
                body = self._read_json(max_bytes=256 * 1024)
                serve_native_download_package(self, user, body)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/account/devices/main":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, set_main_account_device(self.server, user, body, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/account/friends":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, request_friendship(user, body))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/account/friends/respond":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, respond_friendship(user, body))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/sync/events":
            try:
                body = self._read_json(max_bytes=SYNC_EVENT_REQUEST_MAX_BYTES)
                result = append_sync_event(self.server, user, body)
                event = result.get("event") if isinstance(result.get("event"), dict) else {}
                if remote_control_kind_allowed(event.get("kind")):
                    remote_control_live_broadcast_async(self.server, event)
                self._json(HTTPStatus.OK, result)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/fleet/nodes/ensure-main":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, ensure_main_fleet_node(user, body))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/fleet/nodes/provision-main":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, provision_main_fleet_node(self.server, user, body))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/agent/harnesses/provision":
            try:
                body = self._read_json(max_bytes=64 * 1024)
                self._json(HTTPStatus.OK, provision_agent_harness_node(self.server, user, body))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        grant_match = re.fullmatch(r"/admin/users/([0-9]+)/credits/grant", path)
        if grant_match:
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, grant_flux_credits(user, grant_match.group(1), body))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/storage/import":
            try:
                body = self._read_json(max_bytes=4 * 1024 * 1024)
                self._json(HTTPStatus.OK, import_user_storage(self.server, user, body, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/auth/google":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                payload = google_auth_login(self.server, body)
                self._json(HTTPStatus.OK, payload, headers={"Set-Cookie": auth_cookie(payload["user"]["id"])})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "auth_error", "message": str(exc)}},
                )
            return
        if path == "/auth/google/callback":
            try:
                body = self._read_form(max_bytes=32 * 1024)
                payload = google_auth_login(self.server, body)
                self._redirect("/home", headers={"Set-Cookie": auth_cookie(payload["user"]["id"])})
            except BrowserError as exc:
                self._redirect(f"/home?auth_error={quote(exc.code, safe='')}&message={quote(exc.message, safe='')}")
            except Exception as exc:
                self._redirect(f"/home?auth_error=auth_error&message={quote(str(exc), safe='')}")
            return
        if path == "/auth/logout":
            self._json(
                HTTPStatus.OK,
                {"ok": True, "authenticated": False, "user": None},
                headers={"Set-Cookie": auth_cookie("", max_age=0)},
            )
            return
        if path == "/observation/latest":
            try:
                body = self._read_json(max_bytes=256 * 1024)
                self._json(HTTPStatus.OK, {"ok": True, "observation": save_observation(self.server, body, user)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "observation_error", "message": str(exc)}},
                )
            return
        if path == "/client/snapshot":
            try:
                body = self._read_json(max_bytes=2 * 1024 * 1024)
                self._json(HTTPStatus.OK, save_client_snapshot(self.server, body, user, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "client_snapshot_error", "message": str(exc)}},
                )
            return
        if path == "/client/snapshot/request":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, create_client_snapshot_request(self.server, body, user))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "client_snapshot_request_error", "message": str(exc)}},
                )
            return
        if path == "/client/snapshot/response":
            try:
                body = self._read_json(max_bytes=2 * 1024 * 1024)
                self._json(HTTPStatus.OK, save_client_snapshot_response(self.server, body, user, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "client_snapshot_response_error", "message": str(exc)}},
                )
            return
        if path == "/camera/snapshot":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, camera_snapshot_proxy(body))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_snapshot_proxy_error", "message": str(exc)}},
                )
            return
        if endpoint_path(path, "/camera/push-timeline"):
            try:
                body = self._read_json(max_bytes=16 * 1024)
                self._json(HTTPStatus.OK, camera_push_timeline(
                    self.server,
                    body.get("stream_id") or body.get("stream") or "cam-1",
                    body.get("day") or "",
                    body.get("mode") or "live",
                    body.get("seconds") or body.get("sec") or DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC,
                ))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_push_timeline_error", "message": str(exc)}},
                )
            return
        if path == "/camera/stream-session":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, create_camera_stream_session(self.server, body))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_stream_session_error", "message": str(exc)}},
                )
            return
        if path == "/camera/rtsp-session":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, create_camera_rtsp_stream_session(self.server, body))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_rtsp_session_error", "message": str(exc)}},
                )
            return
        if path == "/camera/rtsp-frame":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, camera_rtsp_frame_proxy(body))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_rtsp_frame_error", "message": str(exc)}},
                )
            return
        if path == "/camera/diagnostics":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, camera_diagnostics(body))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_diagnostics_error", "message": str(exc)}},
                )
            return
        if path == "/camera/push/start":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, start_camera_push_ingest(self.server, body, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_push_start_error", "message": str(exc)}},
                )
            return
        if path == "/camera/push/stop":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, stop_camera_push_ingest(self.server, body, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": {"code": "camera_push_stop_error", "message": str(exc)}},
                )
            return
        if path == "/agent/attachments":
            try:
                body = self._read_json(max_bytes=4 * 1024 * 1024)
                self._json(HTTPStatus.OK, {"ok": True, "asset": save_agent_attachment(self.server, body, user)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "attachment_error", "message": str(exc)}},
                )
            return
        if path == "/agent/models/setup":
            try:
                body = self._read_json(max_bytes=32 * 1024)
                self._json(HTTPStatus.OK, {"ok": True, "model_setup": setup_agent_model(self.server, body)})
            except AgentModelSetupError as exc:
                self._json(
                    exc.status,
                    {
                        "ok": False,
                        "error": {"code": exc.code, "message": exc.message},
                        "model_setup": {"steps": exc.steps},
                    },
                )
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "model_setup_error", "message": str(exc)}},
                )
            return
        if path in {"/agent/provider/probe", "/agent/provider/chat"}:
            try:
                body = self._read_json(max_bytes=8 * 1024 * 1024)
                provider = provider_proxy_completion(self.server, body, user=user, probe=path.endswith("/probe"))
                payload = {
                    "ok": True,
                    "provider": provider,
                    "reply": provider.get("reply", ""),
                    "usage": provider.get("usage"),
                    "model": provider.get("model", ""),
                    "mode": "backend-proxy",
                }
                self._json(HTTPStatus.OK, payload)
            except ProviderProxyError as exc:
                self._json(
                    exc.status,
                    {
                        "ok": False,
                        "error": {"code": exc.code, "message": exc.message},
                        "provider": {"diagnostic": exc.diagnostic},
                    },
                )
            except Exception as exc:
                diagnostic = provider_diagnostic("unreachable", "backend-proxy-error", str(exc), HTTPStatus.BAD_GATEWAY)
                self._json(
                    HTTPStatus.BAD_GATEWAY,
                    {
                        "ok": False,
                        "error": {"code": "provider_proxy_error", "message": diagnostic["message"]},
                        "provider": {"diagnostic": diagnostic},
                    },
                )
            return
        if path == "/agent/session/message":
            try:
                body = self._read_json(max_bytes=8 * 1024 * 1024)
                self._json(HTTPStatus.OK, {"ok": True, "agent": embedded_agent_message(self.server, body, user=user)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "agent_error", "message": str(exc)}},
                )
            return
        if path == "/agent/session/message/stream":
            try:
                body = self._read_json(max_bytes=8 * 1024 * 1024)
                stream_embedded_agent_message(self, body, user=user)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "agent_error", "message": str(exc)}},
                )
            return
        if path == "/timeline/checkpoint":
            try:
                body = self._read_json(max_bytes=16 * 1024)
                self._json(HTTPStatus.OK, {"ok": True, "checkpoint": timeline_checkpoint(self.server, body, user)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "timeline_error", "message": str(exc)}},
                )
            return
        if path == "/timeline/stepback":
            try:
                body = self._read_json(max_bytes=16 * 1024)
                self._json(HTTPStatus.OK, {"ok": True, "stepback": timeline_stepback(self.server, body, user)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "timeline_error", "message": str(exc)}},
                )
            return
        if path == "/spaces":
            try:
                body = self._read_json(max_bytes=256 * 1024)
                self._json(HTTPStatus.OK, save_user_spaces(self.server, user, body, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "spaces_error", "message": str(exc)}},
                )
            return
        if path == "/spaces/share":
            try:
                body = self._read_json(max_bytes=64 * 1024)
                self._json(HTTPStatus.OK, share_user_space(self.server, user, body))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "space_share_error", "message": str(exc)}},
                )
            return
        if path == "/spaces/join":
            try:
                body = self._read_json(max_bytes=64 * 1024)
                self._json(HTTPStatus.OK, join_shared_space(self.server, user, body, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "space_join_error", "message": str(exc)}},
                )
            return
        if path == "/spaces/room":
            try:
                body = self._read_json(max_bytes=64 * 1024)
                self._json(HTTPStatus.OK, shared_space_room(self.server, user, body, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "space_room_error", "message": str(exc)}},
                )
            return
        if path == "/voice-lab/room":
            try:
                body = self._read_json(max_bytes=256 * 1024)
                self._json(HTTPStatus.OK, voice_lab_room(self.server, user, body, self))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "voice_lab_error", "message": str(exc)}},
                )
            return
        if path == "/wis/artifacts/patch":
            try:
                body = self._read_json(max_bytes=512 * 1024)
                self._json(HTTPStatus.OK, {"ok": True, "wis_patch": patch_wis_artifact(self.server, user, body)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "wis_patch_error", "message": str(exc)}},
                )
            return
        if path == "/security-loop/findings":
            try:
                body = self._read_json(max_bytes=256 * 1024)
                self._json(HTTPStatus.OK, save_security_loop_finding(self.server, body, user))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "security_loop_error", "message": str(exc)}},
                )
            return
        decision_match = re.fullmatch(r"/security-loop/findings/([^/]+)/decision", path)
        if decision_match:
            try:
                body = self._read_json(max_bytes=128 * 1024)
                self._json(HTTPStatus.OK, decide_security_loop_finding(self.server, decision_match.group(1), body, user))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "security_loop_error", "message": str(exc)}},
                )
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint was not found")

    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(self), microphone=(self), geolocation=(), payment=()")
        if public_deployment(self):
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header("Content-Security-Policy", content_security_policy(self))
        super().end_headers()

    def translate_path(self, path: str) -> str:
        if path.split("?", 1)[0] == "/voice-lab":
            return str(self.server.public_root.resolve() / "voice-lab.html")
        if path.split("?", 1)[0] == "/composer-lab":
            return str(self.server.public_root.resolve() / "composer-lab.html")
        translated = Path(super().translate_path(path))
        public_root = self.server.public_root.resolve()
        try:
            translated.resolve().relative_to(public_root)
        except ValueError:
            return str(public_root / "index.html")
        if translated.is_file() or translated.suffix:
            return str(translated)
        return str(public_root / "index.html")

    def _json(self, status: HTTPStatus, payload: dict[str, Any], *, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _redirect(self, location: str, *, headers: dict[str, str] | None = None) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_json(self, *, max_bytes: int = 64 * 1024) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise BrowserError("invalid_content_length", "Invalid Content-Length header.") from exc
        if length > max_bytes:
            raise BrowserError(
                "payload_too_large",
                "Request body is too large.",
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BrowserError("invalid_json", "Request body must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise BrowserError("invalid_json", "Request body must be a JSON object.")
        return payload

    def _read_form(self, *, max_bytes: int = 64 * 1024) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise BrowserError("invalid_content_length", "Invalid Content-Length header.") from exc
        if length > max_bytes:
            raise BrowserError(
                "payload_too_large",
                "Request body is too large.",
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return {key: values[-1] if values else "" for key, values in parse_qs(raw, keep_blank_values=True).items()}


class BrowserError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class AgentModelSetupError(BrowserError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        steps: list[dict[str, str]],
        status: HTTPStatus = HTTPStatus.BAD_GATEWAY,
    ) -> None:
        super().__init__(code, message, status=status)
        self.steps = steps


class ProviderProxyError(BrowserError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        diagnostic: dict[str, Any] | None = None,
        status: HTTPStatus = HTTPStatus.BAD_GATEWAY,
    ) -> None:
        super().__init__(code, message, status=status)
        self.diagnostic = diagnostic or provider_diagnostic("unreachable", code, message, status)


def provider_diagnostic(
    mode: str,
    category: str,
    message: str,
    status: int | HTTPStatus | None = None,
    *,
    endpoint: str = "",
    model: str = "",
) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "mode": mode,
        "category": category,
        "message": clipped(str(message or category), 600),
    }
    if status is not None:
        diagnostic["http_status"] = int(status)
    if endpoint:
        diagnostic["endpoint"] = endpoint
    if model:
        diagnostic["model"] = clipped(model, 180)
    return diagnostic


def provider_name_from_base_url(base_url: str) -> str:
    base = base_url.strip().lower()
    if "perplexity.ai" in base:
        return "perplexity"
    if "openrouter.ai" in base:
        return "openrouter"
    if "api.groq.com" in base:
        return "groq"
    if "moonshot.ai" in base:
        return "moonshot"
    if "deepseek.com" in base:
        return "deepseek"
    if "dashscope.aliyuncs.com" in base:
        return "dashscope"
    if "generativelanguage.googleapis.com" in base:
        return "google"
    if "api.x.ai" in base:
        return "xai"
    if "api.mistral.ai" in base:
        return "mistral"
    if "api.openai.com" in base:
        return "openai"
    if "opencode.ai/zen/go" in base:
        return "opencode-go"
    if "opencode.ai/zen" in base:
        return "opencode-zen"
    return ""


def normalize_provider_base_url(value: Any) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or any(char.isspace() for char in raw):
        raise ProviderProxyError(
            "malformed-base-url",
            "Base URL must be a valid HTTP or HTTPS URL.",
            diagnostic=provider_diagnostic("config-missing", "malformed-base-url", "Base URL must be a valid HTTP or HTTPS URL.", HTTPStatus.BAD_REQUEST),
            status=HTTPStatus.BAD_REQUEST,
        )
    return parsed._replace(query="", fragment="").geturl().rstrip("/")


def provider_endpoint_for_base_url(base_url: str, provider: str = "") -> str:
    clean_base = normalize_provider_base_url(base_url)
    parsed = urlparse(clean_base)
    normalized_path = parsed.path.rstrip("/")
    parsed = parsed._replace(path=normalized_path)
    base = parsed.geturl().rstrip("/")
    if normalized_path.endswith("/chat/completions"):
        return base
    provider_name = (provider or provider_name_from_base_url(base)).strip().lower()
    if provider_name == "perplexity":
        return f"{base}/chat/completions"
    if normalized_path.endswith("/openai") or normalized_path.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def normalize_provider_model(model: str, base_url: str = "", provider: str = "") -> str:
    clean = clipped(str(model or "").strip(), 180)
    provider_name = (provider or provider_name_from_base_url(base_url)).strip().lower()
    if provider_name in {"opencode-go", "opencode-zen"} and "/" in clean:
        prefix, _, rest = clean.partition("/")
        if prefix == provider_name and rest:
            return clipped(rest, 180)
    return clean


def normalize_provider_models_name(value: str) -> str:
    raw = re.sub(r"[\s_]+", "-", str(value or "").strip().lower())
    if raw in {"openrouter", "open-router"}:
        return "openrouter"
    if raw in {"opencode-go", "open-code-go", "opencode"}:
        return "opencode-go"
    return ""


def provider_models_from_payload(provider: str, payload: Any) -> list[dict[str, str]]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []
    models: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in data:
        if isinstance(item, str):
            model_id = item.strip()
            label = model_id
        elif isinstance(item, dict):
            model_id = str(item.get("id") or "").strip()
            label = str(item.get("name") or model_id).strip()
        else:
            continue
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        models.append({"id": clipped(model_id, 180), "label": clipped(label or model_id, 220)})
    return models


def provider_models_catalog(provider: str) -> dict[str, Any]:
    provider_name = normalize_provider_models_name(provider)
    source_url = PROVIDER_MODELS_URLS.get(provider_name)
    if not source_url:
        raise BrowserError(
            "provider_not_supported",
            "Model listing is available for OpenRouter and OpenCode-Go.",
            status=HTTPStatus.BAD_REQUEST,
        )
    now = time.time()
    cached = PROVIDER_MODELS_CACHE.get(provider_name)
    if cached and now - float(cached.get("fetched_at") or 0) < PROVIDER_MODELS_CACHE_TTL_SEC:
        return {
            "ok": True,
            "provider": provider_name,
            "source": source_url,
            "cached": True,
            "fetched_at": cached.get("fetched_at_iso", ""),
            "models": cached.get("models", []),
        }
    try:
        req = Request(
            source_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "wasm-agent/0.1 provider-model-list",
            },
        )
        with urlopen(req, timeout=DEFAULT_PROVIDER_MODELS_TIMEOUT_SEC) as response:
            text = response.read(8 * 1024 * 1024).decode("utf-8", errors="replace")
        payload = json.loads(text) if text.strip() else {}
    except HTTPError as exc:
        raise BrowserError(
            "provider_models_unavailable",
            f"{provider_name} model list returned HTTP {exc.code}.",
            status=HTTPStatus.BAD_GATEWAY,
        ) from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise BrowserError(
            "provider_models_unavailable",
            f"{provider_name} model list is unavailable: {exc}",
            status=HTTPStatus.BAD_GATEWAY,
        ) from exc
    models = provider_models_from_payload(provider_name, payload)
    if not models:
        raise BrowserError(
            "provider_models_empty",
            f"{provider_name} did not return any models.",
            status=HTTPStatus.BAD_GATEWAY,
        )
    fetched_at = time.time()
    fetched_at_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(fetched_at))
    PROVIDER_MODELS_CACHE[provider_name] = {
        "models": models,
        "fetched_at": fetched_at,
        "fetched_at_iso": fetched_at_iso,
    }
    return {
        "ok": True,
        "provider": provider_name,
        "source": source_url,
        "cached": False,
        "fetched_at": fetched_at_iso,
        "models": models,
    }


def provider_http_diagnostic(status: int, message: str = "", *, endpoint: str = "", model: str = "") -> dict[str, Any]:
    lower_message = message.lower()
    if status == 403 and (
        "cloudflare" in lower_message
        or "browser_signature" in lower_message
        or "site owner has blocked" in lower_message
    ):
        return provider_diagnostic("unreachable", "provider-access-denied", message or "Provider edge rejected the request.", status, endpoint=endpoint, model=model)
    if status in {401, 403}:
        return provider_diagnostic("auth-failed", "auth-failed", message or "Provider rejected the API key.", status, endpoint=endpoint, model=model)
    if status == 404:
        return provider_diagnostic("model-failed", "model-not-found", message or "Provider could not find that model or endpoint.", status, endpoint=endpoint, model=model)
    if status in {400, 422}:
        return provider_diagnostic("unreachable", "request-shape-error", message or "Provider rejected the request shape.", status, endpoint=endpoint, model=model)
    if status >= 500:
        return provider_diagnostic("unreachable", "provider-unavailable", message or f"Provider returned HTTP {status}.", status, endpoint=endpoint, model=model)
    return provider_diagnostic("unreachable", "http-error", message or f"Provider returned HTTP {status}.", status, endpoint=endpoint, model=model)


def provider_config_from_body(body: dict[str, Any]) -> dict[str, str]:
    raw = body.get("provider_config") if isinstance(body.get("provider_config"), dict) else body
    base_url_raw = raw.get("base_url") or raw.get("baseUrl") or ""
    raw_model = str(raw.get("model") or "").strip()
    api_key = str(raw.get("api_key") or raw.get("apiKey") or "").strip()
    provider = clipped(str(raw.get("provider") or "").strip().lower(), 64)
    if not str(base_url_raw or "").strip():
        diagnostic = provider_diagnostic("config-missing", "missing-base-url", "Missing Base URL.", HTTPStatus.BAD_REQUEST)
        raise ProviderProxyError("missing-base-url", diagnostic["message"], diagnostic=diagnostic, status=HTTPStatus.BAD_REQUEST)
    base_url = normalize_provider_base_url(base_url_raw)
    if not api_key:
        diagnostic = provider_diagnostic("config-missing", "missing-api-key", "Missing API key.", HTTPStatus.BAD_REQUEST)
        raise ProviderProxyError("missing-api-key", diagnostic["message"], diagnostic=diagnostic, status=HTTPStatus.BAD_REQUEST)
    endpoint = provider_endpoint_for_base_url(base_url, provider)
    model = normalize_provider_model(raw_model, base_url, provider)
    if not model:
        diagnostic = provider_diagnostic("config-missing", "missing-model", "Missing model.", HTTPStatus.BAD_REQUEST)
        raise ProviderProxyError("missing-model", diagnostic["message"], diagnostic=diagnostic, status=HTTPStatus.BAD_REQUEST)
    return {
        "base_url": base_url,
        "endpoint": endpoint,
        "model": model,
        "api_key": api_key,
        "provider": provider or provider_name_from_base_url(base_url),
    }


def provider_proxy_message_content(value: Any) -> str | list[dict[str, Any]]:
    if isinstance(value, str):
        return clipped(value.strip(), 12000)
    if not isinstance(value, list):
        return ""
    parts: list[dict[str, Any]] = []
    for item in value[:16]:
        if not isinstance(item, dict):
            continue
        part_type = str(item.get("type") or "").strip().lower()
        if part_type == "text":
            text = clipped(str(item.get("text") or "").strip(), 12000)
            if text:
                parts.append({"type": "text", "text": text})
            continue
        if part_type == "image_url":
            image_source = item.get("image_url")
            if not isinstance(image_source, dict):
                image_source = item.get("imageUrl")
            url = ""
            detail = ""
            if isinstance(image_source, dict):
                url = str(image_source.get("url") or "").strip()
                detail = str(image_source.get("detail") or "").strip()
            else:
                url = str(image_source or "").strip()
            if not url or len(url) > 2_000_000:
                continue
            if not (url.startswith("data:image/") or url.startswith("https://") or url.startswith("http://")):
                continue
            image_part: dict[str, Any] = {"type": "image_url", "image_url": {"url": url}}
            if detail in {"low", "high", "auto"}:
                image_part["image_url"]["detail"] = detail
            parts.append(image_part)
            continue
        if part_type == "video_url":
            video_source = item.get("videoUrl")
            if not isinstance(video_source, dict):
                video_source = item.get("video_url")
            url = ""
            if isinstance(video_source, dict):
                url = str(video_source.get("url") or "").strip()
            else:
                url = str(video_source or "").strip()
            if not url or len(url) > 7_500_000:
                continue
            if not (url.startswith("data:video/") or url.startswith("https://") or url.startswith("http://")):
                continue
            parts.append({"type": "video_url", "videoUrl": {"url": url}})
    return parts


def provider_proxy_messages(body: dict[str, Any], *, probe: bool = False) -> list[dict[str, Any]]:
    raw_messages = body.get("messages") if isinstance(body.get("messages"), list) else []
    messages: list[dict[str, Any]] = []
    allowed_roles = {"system", "developer", "user", "assistant"}
    for item in raw_messages[:24]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = provider_proxy_message_content(item.get("content"))
        if role not in allowed_roles or not content:
            continue
        messages.append({"role": role, "content": content})
    if probe and not messages:
        return [
            {"role": "system", "content": "Reply with exactly: wasm-agent-provider-ok"},
            {"role": "user", "content": "Reply with exactly: wasm-agent-provider-ok"},
        ]
    if not messages:
        diagnostic = provider_diagnostic("unreachable", "request-shape-error", "Provider proxy request needs at least one message.", HTTPStatus.BAD_REQUEST)
        raise ProviderProxyError("request-shape-error", diagnostic["message"], diagnostic=diagnostic, status=HTTPStatus.BAD_REQUEST)
    return messages


def provider_error_message(payload: Any, fallback: str = "") -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, str):
            return clipped(error, 600)
        if isinstance(error, dict):
            return clipped(str(error.get("message") or error.get("code") or fallback), 600)
        if payload.get("detail") or payload.get("title"):
            return clipped(str(payload.get("detail") or payload.get("title")), 600)
        if payload.get("message"):
            return clipped(str(payload.get("message")), 600)
    return clipped(fallback, 600)


def provider_payload_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "".join(parts)
    return ""


def provider_reply_from_payload(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content = provider_payload_text(message.get("content"))
    if not content:
        content = provider_payload_text(choice.get("text"))
    if not content:
        content = provider_payload_text(choice.get("delta", {}).get("content") if isinstance(choice.get("delta"), dict) else "")
    return clipped(content.strip(), 120000)


def provider_proxy_completion(
    server: WasmAgentServer,
    body: dict[str, Any],
    *,
    user: dict[str, Any] | None = None,
    probe: bool = False,
) -> dict[str, Any]:
    if not user:
        diagnostic = provider_diagnostic("config-missing", "auth-required", "Account sign-in is required.", HTTPStatus.UNAUTHORIZED)
        raise ProviderProxyError("auth_required", diagnostic["message"], diagnostic=diagnostic, status=HTTPStatus.UNAUTHORIZED)
    config = provider_config_from_body(body)
    messages = provider_proxy_messages(body, probe=probe)
    endpoint = config["endpoint"]
    model = config["model"]
    payload = {
        "model": model,
        "stream": False,
        "messages": messages,
    }
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        endpoint,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['api_key']}",
            "User-Agent": f"{PLUGIN_NAME}/{PLUGIN_VERSION} provider-proxy",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urlopen(request, timeout=DEFAULT_PROVIDER_PROXY_TIMEOUT_SEC) as response:
            raw = response.read().decode("utf-8", "replace")
            status = int(response.status)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        parsed_error: Any = {}
        try:
            parsed_error = json.loads(detail) if detail else {}
        except json.JSONDecodeError:
            parsed_error = {}
        diagnostic = provider_http_diagnostic(
            int(exc.code),
            provider_error_message(parsed_error, detail[:600]),
            endpoint=endpoint,
            model=model,
        )
        raise ProviderProxyError(diagnostic["category"], diagnostic["message"], diagnostic=diagnostic, status=HTTPStatus.BAD_GATEWAY) from exc
    except TimeoutError as exc:
        diagnostic = provider_diagnostic("unreachable", "network-timeout", "Provider request timed out.", HTTPStatus.BAD_GATEWAY, endpoint=endpoint, model=model)
        raise ProviderProxyError("network-timeout", diagnostic["message"], diagnostic=diagnostic, status=HTTPStatus.BAD_GATEWAY) from exc
    except URLError as exc:
        reason = str(getattr(exc, "reason", exc))
        category = "network-offline" if "Name or service not known" in reason or "Temporary failure" in reason else "network-failed"
        diagnostic = provider_diagnostic("unreachable", category, reason or "Provider request failed.", HTTPStatus.BAD_GATEWAY, endpoint=endpoint, model=model)
        raise ProviderProxyError(category, diagnostic["message"], diagnostic=diagnostic, status=HTTPStatus.BAD_GATEWAY) from exc
    try:
        response_payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        diagnostic = provider_diagnostic("unreachable", "request-shape-error", "Provider returned non-JSON content.", HTTPStatus.BAD_GATEWAY, endpoint=endpoint, model=model)
        raise ProviderProxyError("provider-non-json", diagnostic["message"], diagnostic=diagnostic, status=HTTPStatus.BAD_GATEWAY) from exc
    if not isinstance(response_payload, dict):
        diagnostic = provider_diagnostic("unreachable", "request-shape-error", "Provider returned an unsupported response.", HTTPStatus.BAD_GATEWAY, endpoint=endpoint, model=model)
        raise ProviderProxyError("provider-response-shape", diagnostic["message"], diagnostic=diagnostic, status=HTTPStatus.BAD_GATEWAY)
    if status < 200 or status >= 300:
        diagnostic = provider_http_diagnostic(status, provider_error_message(response_payload, raw[:600]), endpoint=endpoint, model=model)
        raise ProviderProxyError(diagnostic["category"], diagnostic["message"], diagnostic=diagnostic, status=HTTPStatus.BAD_GATEWAY)
    reply = provider_reply_from_payload(response_payload)
    if not reply:
        diagnostic = provider_diagnostic("unreachable", "request-shape-error", "Provider returned no message content.", HTTPStatus.BAD_GATEWAY, endpoint=endpoint, model=model)
        raise ProviderProxyError("provider-empty-response", diagnostic["message"], diagnostic=diagnostic, status=HTTPStatus.BAD_GATEWAY)
    duration_ms = round((time.monotonic() - started) * 1000)
    return {
        "schema": "hermes.wasm_agent.provider_proxy.v1",
        "mode": "backend-proxy",
        "category": "ready",
        "base_url": config["base_url"],
        "endpoint": endpoint,
        "provider": config["provider"],
        "model": clipped(str(response_payload.get("model") or model), 180),
        "reply": reply,
        "usage": response_payload.get("usage") if isinstance(response_payload.get("usage"), dict) else None,
        "duration_ms": duration_ms,
        "diagnostic": provider_diagnostic("backend-proxy", "ready", "Backend proxy provider request succeeded.", HTTPStatus.OK, endpoint=endpoint, model=model),
    }


def camera_proxy_clean_url(raw_url: str) -> tuple[str, str, str]:
    raw = clipped_verbatim(str(raw_url or "").strip(), 4096)
    if not raw:
        raise BrowserError("camera_snapshot_missing_url", "Camera snapshot proxy requires a URL.")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise BrowserError("camera_snapshot_bad_scheme", "Camera snapshot proxy only supports HTTP or HTTPS DVR URLs.")
    if not parsed.hostname:
        raise BrowserError("camera_snapshot_missing_host", "Camera snapshot proxy requires a DVR host.")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    clean_url = parsed._replace(netloc=netloc).geturl()
    return clean_url, unquote(parsed.username or ""), unquote(parsed.password or "")


def camera_rtsp_clean_url(raw_url: str) -> tuple[str, str, str]:
    raw = clipped_verbatim(str(raw_url or "").strip(), 4096)
    if not raw:
        raise BrowserError("camera_rtsp_missing_url", "Camera RTSP relay requires a URL.")
    parsed = urlparse(raw)
    if parsed.scheme != "rtsp":
        raise BrowserError("camera_rtsp_bad_scheme", "Camera RTSP relay only supports rtsp:// DVR URLs.")
    if not parsed.hostname:
        raise BrowserError("camera_rtsp_missing_host", "Camera RTSP relay requires a DVR host.")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    clean_url = parsed._replace(netloc=netloc).geturl()
    return clean_url, unquote(parsed.username or ""), unquote(parsed.password or "")


def camera_url_with_credentials(clean_url: str, username: str, password: str) -> str:
    if not (username or password):
        return clean_url
    parsed = urlparse(clean_url)
    if not parsed.hostname:
        return clean_url
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    netloc = f"{auth}{host}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return parsed._replace(netloc=netloc).geturl()


def camera_proxy_auth_opener(clean_url: str, username: str, password: str):
    if not (username or password):
        return None
    password_mgr = HTTPPasswordMgrWithDefaultRealm()
    password_mgr.add_password(None, clean_url, username, password)
    return build_opener(HTTPDigestAuthHandler(password_mgr), HTTPBasicAuthHandler(password_mgr))


def camera_parse_any_url(raw_url: Any) -> Any:
    raw = clipped_verbatim(str(raw_url or "").strip(), 4096)
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in {"rtsp", "http", "https"} or not parsed.hostname:
        return None
    return parsed


def camera_host_port_parts(raw_host: str) -> tuple[str, int | None]:
    raw = clipped_verbatim(str(raw_host or "").strip(), 512)
    if not raw:
        return "", None
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    host = parsed.hostname or raw.strip("[]")
    try:
        port = parsed.port
    except ValueError:
        port = None
    if not parsed.hostname and ":" in host and not host.startswith("["):
        maybe_host, maybe_port = host.rsplit(":", 1)
        if maybe_port.isdigit():
            host = maybe_host
            port = max(1, min(65535, int(maybe_port)))
    return host.strip("[]"), port


def camera_tcp_check(host: str, port: int, *, label: str, timeout_sec: float = 2.0) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {
        "label": label,
        "host": host,
        "port": port,
        "ok": False,
    }
    try:
        with socket.create_connection((host, port), timeout=max(0.5, min(5.0, timeout_sec))):
            result["ok"] = True
    except OSError as exc:
        result["error"] = clipped(str(exc), 180)
    result["duration_ms"] = round((time.monotonic() - started) * 1000)
    return result


def camera_private_ipv4_range(value: str) -> str:
    try:
        address = ip_address(str(value or ""))
    except ValueError:
        return ""
    if address.version != 4:
        return ""
    for network, label in PRIVATE_IPV4_RANGES:
        if address in network:
            return label
    return ""


def camera_private_route_advice(target_ip: str, source_ip: str) -> str:
    target_range = camera_private_ipv4_range(target_ip)
    source_range = camera_private_ipv4_range(source_ip)
    if not target_range or not source_range or target_range == source_range:
        return ""
    return (
        f"The DVR target {target_ip} is in private range {target_range}, but wasm-agent would route from "
        f"{source_ip} in {source_range}. That usually means the DVR is on a different private LAN or VPN. "
        "Use a routed/VPN path or an RTSP tunnel host:port reachable from the wasm-agent server."
    )


def camera_route_hint(host: str, port: int) -> dict[str, Any]:
    result: dict[str, Any] = {"host": host, "port": port}
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
    except OSError as exc:
        result["error"] = clipped(str(exc), 180)
        return result
    if not infos:
        result["error"] = "no route candidates"
        return result
    family, _socktype, _proto, _canonname, sockaddr = infos[0]
    target_ip = str(sockaddr[0])
    result["target_ip"] = target_ip
    try:
        target_address = ip_address(target_ip)
        result["target_scope"] = (
            "loopback"
            if target_address.is_loopback
            else ("private" if target_address.is_private else ("link-local" if target_address.is_link_local else "public"))
        )
    except ValueError:
        pass
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.connect(sockaddr)
            source_ip = str(sock.getsockname()[0])
            result["source_ip"] = source_ip
            advice = camera_private_route_advice(target_ip, source_ip)
            if advice:
                result["advice"] = advice
                result["private_lan_mismatch"] = True
    except OSError as exc:
        result["source_error"] = clipped(str(exc), 180)
    return result


def camera_diagnostics(body: dict[str, Any]) -> dict[str, Any]:
    urls = [
        ("source", body.get("url")),
        ("portal", body.get("portalUrl") or body.get("portal_url")),
        ("snapshot", body.get("snapshotUrl") or body.get("snapshot_url")),
        ("stream", body.get("streamUrl") or body.get("stream_url")),
    ]
    host, host_port = camera_host_port_parts(str(body.get("host") or ""))
    timeout_ms = max(500, min(5000, int(body.get("timeout_ms") or body.get("timeoutMs") or 2000)))
    checks: list[tuple[str, str, int]] = []
    seen: set[tuple[str, int]] = set()

    def port_value(*names: str, default: int) -> int:
        for name in names:
            raw = body.get(name)
            if raw in {None, ""}:
                continue
            try:
                return max(1, min(65535, int(float(str(raw)))))
            except (TypeError, ValueError):
                continue
        return default

    def add_check(label: str, check_host: str, port: int) -> None:
        clean_host = str(check_host or "").strip("[]")
        if not clean_host or port <= 0:
            return
        key = (clean_host, port)
        if key in seen:
            return
        seen.add(key)
        checks.append((label, clean_host, port))

    for label, raw_url in urls:
        parsed = camera_parse_any_url(raw_url)
        if not parsed:
            continue
        default_port = 554 if parsed.scheme == "rtsp" else (443 if parsed.scheme == "https" else 80)
        add_check(f"{label}:{parsed.scheme}", parsed.hostname or "", parsed.port or default_port)
    if host:
        add_check("host:rtsp", host, port_value("rtspPort", "rtsp_port", default=host_port or 554))
        add_check("host:http", host, port_value("httpPort", "http_port", default=80))
        add_check("host:https", host, port_value("httpsPort", "https_port", default=443))
    if not checks:
        raise BrowserError("camera_diagnostics_missing_target", "Camera diagnostics require a DVR URL or host.")

    tcp = [camera_tcp_check(check_host, port, label=label, timeout_sec=timeout_ms / 1000) for label, check_host, port in checks]
    route_hints = [camera_route_hint(check_host, port) for _label, check_host, port in checks]
    reachable = any(item.get("ok") for item in tcp)
    route_advice = next((str(item.get("advice") or "") for item in route_hints if item.get("advice")), "")
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.camera.diagnostics.v1",
        "reachable": reachable,
        "tcp": tcp,
        "route": route_hints,
        "advice": (
            "At least one DVR port is reachable from wasm-agent."
            if reachable
            else (
                route_advice
                or "No checked DVR ports are reachable from wasm-agent. Use a DVR/cloud tunnel host that forwards RTSP and, if needed, HTTP/HTTPS."
            )
        ),
    }


def camera_snapshot_proxy(body: dict[str, Any]) -> dict[str, Any]:
    clean_url, url_user, url_password = camera_proxy_clean_url(str(body.get("url") or ""))
    username = str(body.get("username") or body.get("user") or url_user or "")
    password = str(body.get("password") or url_password or "")
    timeout_ms = max(1000, min(20000, int(body.get("timeout_ms") or body.get("timeoutMs") or DEFAULT_CAMERA_SNAPSHOT_PROXY_TIMEOUT_SEC * 1000)))
    headers = {
        "Accept": "image/jpeg,image/jpg,image/png,image/webp,image/*,*/*;q=0.8",
        "Cache-Control": "no-cache",
        "User-Agent": f"{PLUGIN_NAME}/{PLUGIN_VERSION} camera-snapshot-proxy",
    }
    opener = camera_proxy_auth_opener(clean_url, username, password)
    request = Request(clean_url, headers=headers, method="GET")
    started = time.monotonic()
    try:
        with (opener.open(request, timeout=timeout_ms / 1000) if opener else urlopen(request, timeout=timeout_ms / 1000)) as response:
            content_type = str(response.headers.get("Content-Type") or "image/jpeg").split(";", 1)[0].strip().lower()
            data = response.read(DEFAULT_CAMERA_SNAPSHOT_PROXY_MAX_BYTES + 1)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise BrowserError("camera_snapshot_auth_failed", f"DVR rejected the camera credentials (HTTP {exc.code}).", status=HTTPStatus.BAD_GATEWAY) from exc
        raise BrowserError("camera_snapshot_http_error", f"DVR snapshot request failed with HTTP {exc.code}.", status=HTTPStatus.BAD_GATEWAY) from exc
    except URLError as exc:
        raise BrowserError("camera_snapshot_unreachable", f"DVR snapshot endpoint was unreachable: {exc.reason}", status=HTTPStatus.BAD_GATEWAY) from exc
    if len(data) > DEFAULT_CAMERA_SNAPSHOT_PROXY_MAX_BYTES:
        raise BrowserError("camera_snapshot_too_large", "DVR snapshot response exceeded the 2 MB limit.", status=HTTPStatus.BAD_GATEWAY)
    if not data:
        raise BrowserError("camera_snapshot_empty", "DVR snapshot endpoint returned an empty response.", status=HTTPStatus.BAD_GATEWAY)
    if not content_type.startswith("image/"):
        raise BrowserError("camera_snapshot_not_image", f"DVR returned {content_type or 'an unknown content type'} instead of an image.", status=HTTPStatus.BAD_GATEWAY)
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.camera.snapshot_proxy.v1",
        "image": {
            "content_type": content_type,
            "bytes": len(data),
            "data_url": f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}",
        },
        "diagnostic": {
            "mode": "same-origin-snapshot-proxy",
            "duration_ms": round((time.monotonic() - started) * 1000),
            "has_credentials": bool(username or password),
        },
    }


def prune_camera_stream_sessions(server: WasmAgentServer) -> None:
    now = time.time()
    with server.camera_stream_sessions_lock:
        for token, session in list(server.camera_stream_sessions.items()):
            if float(session.get("expires_at") or 0) <= now:
                server.camera_stream_sessions.pop(token, None)


def create_camera_stream_session(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    clean_url, url_user, url_password = camera_proxy_clean_url(str(body.get("url") or ""))
    username = str(body.get("username") or body.get("user") or url_user or "")
    password = str(body.get("password") or url_password or "")
    timeout_ms = max(1000, min(60000, int(body.get("timeout_ms") or body.get("timeoutMs") or DEFAULT_CAMERA_STREAM_PROXY_TIMEOUT_SEC * 1000)))
    token = secrets.token_urlsafe(24)
    now = time.time()
    expires_at = now + DEFAULT_CAMERA_STREAM_SESSION_TTL_SEC
    session = {
        "url": clean_url,
        "username": username,
        "password": password,
        "timeout_ms": timeout_ms,
        "transport": "http-mjpeg",
        "created_at": now,
        "expires_at": expires_at,
    }
    prune_camera_stream_sessions(server)
    with server.camera_stream_sessions_lock:
        server.camera_stream_sessions[token] = session
    parsed = urlparse(clean_url)
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.camera.stream_session.v1",
        "stream": {
            "url": f"/camera/stream?token={quote(token, safe='')}",
            "expires_at": int(expires_at),
            "mode": "same-origin-mjpeg-proxy",
        },
        "diagnostic": {
            "source_host": parsed.hostname or "",
            "source_path": parsed.path,
            "has_credentials": bool(username or password),
            "ttl_sec": DEFAULT_CAMERA_STREAM_SESSION_TTL_SEC,
        },
    }


def camera_stream_session_for_token(server: WasmAgentServer, token: str) -> dict[str, Any]:
    clean_token = str(token or "").strip()
    if not clean_token:
        raise BrowserError("camera_stream_missing_token", "Camera stream token is required.", status=HTTPStatus.BAD_REQUEST)
    now = time.time()
    with server.camera_stream_sessions_lock:
        session = server.camera_stream_sessions.get(clean_token)
        if not session:
            raise BrowserError("camera_stream_unknown_token", "Camera stream token is not active.", status=HTTPStatus.NOT_FOUND)
        if float(session.get("expires_at") or 0) <= now:
            server.camera_stream_sessions.pop(clean_token, None)
            raise BrowserError("camera_stream_expired_token", "Camera stream token expired.", status=HTTPStatus.GONE)
        return dict(session)


def serve_camera_stream_proxy(handler: WasmAgentHandler, token: str) -> None:
    session = camera_stream_session_for_token(handler.server, token)
    if str(session.get("transport") or "http-mjpeg") != "http-mjpeg":
        raise BrowserError("camera_stream_wrong_transport", "Camera stream token is not for the HTTP MJPEG relay.", status=HTTPStatus.BAD_REQUEST)
    clean_url = str(session.get("url") or "")
    username = str(session.get("username") or "")
    password = str(session.get("password") or "")
    timeout_ms = max(1000, min(60000, int(session.get("timeout_ms") or DEFAULT_CAMERA_STREAM_PROXY_TIMEOUT_SEC * 1000)))
    headers = {
        "Accept": "multipart/x-mixed-replace,image/jpeg,image/jpg,image/*,*/*;q=0.8",
        "Cache-Control": "no-cache",
        "Connection": "close",
        "User-Agent": f"{PLUGIN_NAME}/{PLUGIN_VERSION} camera-stream-proxy",
    }
    opener = camera_proxy_auth_opener(clean_url, username, password)
    request = Request(clean_url, headers=headers, method="GET")
    try:
        response = opener.open(request, timeout=timeout_ms / 1000) if opener else urlopen(request, timeout=timeout_ms / 1000)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise BrowserError("camera_stream_auth_failed", f"DVR rejected the camera credentials (HTTP {exc.code}).", status=HTTPStatus.BAD_GATEWAY) from exc
        raise BrowserError("camera_stream_http_error", f"DVR stream request failed with HTTP {exc.code}.", status=HTTPStatus.BAD_GATEWAY) from exc
    except URLError as exc:
        raise BrowserError("camera_stream_unreachable", f"DVR stream endpoint was unreachable: {exc.reason}", status=HTTPStatus.BAD_GATEWAY) from exc

    with response:
        content_type = str(response.headers.get("Content-Type") or "multipart/x-mixed-replace").strip()
        base_type = content_type.split(";", 1)[0].strip().lower()
        if not (base_type.startswith("multipart/") or base_type.startswith("image/") or base_type == "application/octet-stream"):
            raise BrowserError("camera_stream_not_media", f"DVR returned {base_type or 'an unknown content type'} instead of a media stream.", status=HTTPStatus.BAD_GATEWAY)
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        handler.send_header("Pragma", "no-cache")
        handler.send_header("Connection", "close")
        handler.send_header("X-Accel-Buffering", "no")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()
        while True:
            try:
                chunk = response.read(DEFAULT_CAMERA_STREAM_PROXY_CHUNK_BYTES)
                if not chunk:
                    break
                handler.wfile.write(chunk)
                handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break


def create_camera_rtsp_stream_session(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    clean_url, url_user, url_password = camera_rtsp_clean_url(str(body.get("url") or ""))
    username = str(body.get("username") or body.get("user") or url_user or "")
    password = str(body.get("password") or url_password or "")
    timeout_ms = max(1000, min(60000, int(body.get("timeout_ms") or body.get("timeoutMs") or DEFAULT_CAMERA_RTSP_RELAY_TIMEOUT_SEC * 1000)))
    fps = max(1, min(12, int(float(body.get("fps") or DEFAULT_CAMERA_RTSP_RELAY_FPS))))
    quality = max(2, min(12, int(float(body.get("quality") or DEFAULT_CAMERA_RTSP_RELAY_QUALITY))))
    token = secrets.token_urlsafe(24)
    now = time.time()
    expires_at = now + DEFAULT_CAMERA_STREAM_SESSION_TTL_SEC
    session = {
        "url": clean_url,
        "username": username,
        "password": password,
        "timeout_ms": timeout_ms,
        "fps": fps,
        "quality": quality,
        "transport": "rtsp-mjpeg",
        "created_at": now,
        "expires_at": expires_at,
    }
    prune_camera_stream_sessions(server)
    with server.camera_stream_sessions_lock:
        server.camera_stream_sessions[token] = session
    parsed = urlparse(clean_url)
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.camera.rtsp_stream_session.v1",
        "stream": {
            "url": f"/camera/rtsp-stream?token={quote(token, safe='')}",
            "expires_at": int(expires_at),
            "mode": "same-origin-rtsp-mjpeg-transcode",
            "fps": fps,
        },
        "diagnostic": {
            "source_host": parsed.hostname or "",
            "source_path": parsed.path,
            "source_query": parsed.query,
            "has_credentials": bool(username or password),
            "ttl_sec": DEFAULT_CAMERA_STREAM_SESSION_TTL_SEC,
        },
    }


def camera_rtsp_ffmpeg_path() -> str:
    configured = os.getenv("HERMES_WASM_AGENT_FFMPEG", "ffmpeg").strip() or "ffmpeg"
    resolved = shutil.which(configured) if os.path.basename(configured) == configured else configured
    if not resolved:
        raise BrowserError("camera_rtsp_ffmpeg_missing", "True RTSP camera relay requires ffmpeg on the wasm-agent host.", status=HTTPStatus.BAD_GATEWAY)
    return resolved


def camera_rtsp_ffmpeg_command(input_url: str, *, timeout_ms: int, fps: int, quality: int) -> list[str]:
    return [
        camera_rtsp_ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        str(max(1000, timeout_ms) * 1000),
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-analyzeduration",
        "1000000",
        "-probesize",
        "32768",
        "-i",
        input_url,
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"fps={max(1, min(12, fps))}",
        "-q:v",
        str(max(2, min(12, quality))),
        "-f",
        "mpjpeg",
        "-boundary_tag",
        CAMERA_RTSP_MJPEG_BOUNDARY,
        "pipe:1",
    ]


def camera_rtsp_ffmpeg_frame_command(input_url: str, *, timeout_ms: int, quality: int) -> list[str]:
    return [
        camera_rtsp_ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        str(max(1000, timeout_ms) * 1000),
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-analyzeduration",
        "1000000",
        "-probesize",
        "32768",
        "-i",
        input_url,
        "-an",
        "-sn",
        "-dn",
        "-frames:v",
        "1",
        "-q:v",
        str(max(2, min(12, quality))),
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]


def camera_rtsp_url_with_subtype(clean_url: str, subtype: str) -> str:
    parsed = urlparse(clean_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["subtype"] = [subtype]
    return parsed._replace(query=urlencode(query, doseq=True)).geturl()


def camera_rtsp_frame_candidate_urls(clean_url: str) -> list[tuple[str, str]]:
    candidates = [(clean_url, "requested")]
    parsed = urlparse(clean_url)
    if not parsed.path.rstrip("/").lower().endswith("/cam/realmonitor"):
        return candidates
    query = parse_qs(parsed.query, keep_blank_values=True)
    if not query.get("channel"):
        return candidates
    current_subtype = str((query.get("subtype") or [""])[0]).strip()
    fallback_subtypes: list[str]
    if current_subtype == "0":
        fallback_subtypes = ["1"]
    elif current_subtype == "1":
        fallback_subtypes = ["0"]
    else:
        fallback_subtypes = ["0", "1"]
    seen = {clean_url}
    for subtype in fallback_subtypes:
        fallback_url = camera_rtsp_url_with_subtype(clean_url, subtype)
        if fallback_url in seen:
            continue
        seen.add(fallback_url)
        candidates.append((fallback_url, f"subtype={subtype}"))
    return candidates


def skip_camera_rtsp_preflight() -> bool:
    return os.getenv("HERMES_WASM_AGENT_SKIP_RTSP_PREFLIGHT", "").lower() in {"1", "true", "yes", "on"}


def camera_rtsp_tcp_preflight(clean_url: str) -> None:
    parsed = urlparse(clean_url)
    host = parsed.hostname
    if not host:
        return
    port = parsed.port or 554
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return
    except OSError as exc:
        route_hint = camera_route_hint(host, port)
        route_advice = str(route_hint.get("advice") or "")
        extra = f" {route_advice}" if route_advice else ""
        raise BrowserError(
            "camera_rtsp_unreachable",
            f"wasm-agent cannot open TCP to the DVR RTSP host at {host}:{port}. Check that the DVR/cloud tunnel is reachable from the wasm-agent host and that RTSP port forwarding is enabled.{extra}",
            status=HTTPStatus.BAD_GATEWAY,
        ) from exc


def redact_camera_diagnostic_text(text: str) -> str:
    return re.sub(r"(rtsp://)[^/@\s]+@", r"\1user:***@", str(text or ""))[:700]


def camera_jpeg_diagnostic(data: bytes) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "bytes": len(data),
        "probably_black": False,
    }
    if Image is None:
        return diagnostic
    try:
        with Image.open(io.BytesIO(data)) as image:
            rgb = image.convert("RGB")
            extrema = rgb.getextrema()
            pixels = max(1, rgb.width * rgb.height)
            # Sample every nth pixel cheaply through resize so a full frame does not
            # turn the relay into an image-analysis workload.
            sample = rgb.resize((min(64, rgb.width), min(64, rgb.height)))
            values = list(sample.getdata())
            mean = [sum(pixel[channel] for pixel in values) / len(values) for channel in range(3)]
            bright_pixels = sum(1 for pixel in values if max(pixel) >= 24)
            diagnostic.update({
                "width": rgb.width,
                "height": rgb.height,
                "mean": [round(value, 2) for value in mean],
                "bright_ratio": round(bright_pixels / len(values), 4),
                "probably_black": max(mean) < 8 and bright_pixels / len(values) < 0.01 and pixels > 0,
                "extrema": extrema,
            })
    except Exception:
        diagnostic["image_probe"] = "unreadable"
    return diagnostic


def camera_rtsp_frame_proxy(body: dict[str, Any]) -> dict[str, Any]:
    clean_url, url_user, url_password = camera_rtsp_clean_url(str(body.get("url") or ""))
    username = str(body.get("username") or body.get("user") or url_user or "")
    password = str(body.get("password") or url_password or "")
    timeout_ms = max(1000, min(20000, int(body.get("timeout_ms") or body.get("timeoutMs") or DEFAULT_CAMERA_RTSP_FRAME_TIMEOUT_SEC * 1000)))
    quality = max(2, min(12, int(float(body.get("quality") or DEFAULT_CAMERA_RTSP_RELAY_QUALITY))))
    if not skip_camera_rtsp_preflight():
        camera_rtsp_tcp_preflight(clean_url)
    started = time.monotonic()
    attempts: list[dict[str, Any]] = []
    saw_black_frame = False
    last_detail = ""
    last_timeout: subprocess.TimeoutExpired | None = None
    for candidate_url, reason in camera_rtsp_frame_candidate_urls(clean_url):
        input_url = camera_url_with_credentials(candidate_url, username, password)
        command = camera_rtsp_ffmpeg_frame_command(input_url, timeout_ms=timeout_ms, quality=quality)
        parsed = urlparse(candidate_url)
        attempt_started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=(timeout_ms / 1000) + 2,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            last_timeout = exc
            attempts.append({
                "source_query": parsed.query,
                "status": "timeout",
                "reason": reason,
                "duration_ms": round((time.monotonic() - attempt_started) * 1000),
            })
            continue
        except FileNotFoundError as exc:
            raise BrowserError("camera_rtsp_ffmpeg_missing", "True RTSP camera relay requires ffmpeg on the wasm-agent host.", status=HTTPStatus.BAD_GATEWAY) from exc
        if completed.returncode != 0 or not completed.stdout:
            last_detail = redact_camera_diagnostic_text(completed.stderr.decode("utf-8", "replace"))
            attempts.append({
                "source_query": parsed.query,
                "status": "no_frame",
                "reason": reason,
                "duration_ms": round((time.monotonic() - attempt_started) * 1000),
                "detail": last_detail,
            })
            continue
        diagnostic = camera_jpeg_diagnostic(completed.stdout)
        if diagnostic.get("probably_black"):
            saw_black_frame = True
            attempts.append({
                "source_query": parsed.query,
                "status": "black_frame",
                "reason": reason,
                "duration_ms": round((time.monotonic() - attempt_started) * 1000),
            })
            continue
        attempts.append({
            "source_query": parsed.query,
            "status": "ok",
            "reason": reason,
            "duration_ms": round((time.monotonic() - attempt_started) * 1000),
        })
        return {
            "ok": True,
            "schema": "hermes.wasm_agent.camera.rtsp_frame.v1",
            "image": {
                "content_type": "image/jpeg",
                "bytes": len(completed.stdout),
                "data_url": f"data:image/jpeg;base64,{base64.b64encode(completed.stdout).decode('ascii')}",
            },
            "diagnostic": {
                **diagnostic,
                "mode": "same-origin-rtsp-frame",
                "duration_ms": round((time.monotonic() - started) * 1000),
                "source_host": parsed.hostname or "",
                "source_path": parsed.path,
                "source_query": parsed.query,
                "has_credentials": bool(username or password),
                "attempts": attempts,
            },
        }
    checked_alternate = len(attempts) > 1
    if saw_black_frame:
        raise BrowserError(
            "camera_rtsp_black_frame",
            "DVR RTSP endpoint returned an all-black frame, so WIS did not treat it as the real camera image. Check the selected channel/subtype or the camera signal on the DVR.",
            status=HTTPStatus.BAD_GATEWAY,
        )
    if last_timeout is not None and not last_detail:
        message = "DVR RTSP endpoint did not emit a video frame before the timeout."
        if checked_alternate:
            message = "DVR RTSP endpoint did not emit a video frame before the timeout on the selected or alternate subtype."
        raise BrowserError(
            "camera_rtsp_no_frame",
            f"{message} Check that wasm-agent can reach the DVR/cloud tunnel, RTSP is enabled, credentials are correct, and the channel/subtype has live video.",
            status=HTTPStatus.BAD_GATEWAY,
        ) from last_timeout
    detail = last_detail
    if checked_alternate and detail:
        detail = f"Checked selected and alternate subtype. {detail}"
    raise BrowserError(
        "camera_rtsp_no_frame",
        f"DVR RTSP endpoint did not return a frame. {detail}".strip(),
        status=HTTPStatus.BAD_GATEWAY,
    )


def camera_push_root(server: WasmAgentServer) -> Path:
    root = server.state_dir / "camera-push"
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_camera_push_stream_id(raw: Any) -> str:
    return safe_state_id(str(raw or "cam-1"), "cam-1")[:64]


def camera_push_stream_index(stream_id: str) -> int:
    match = re.search(r"(\d+)$", stream_id)
    if not match:
        return 1
    try:
        return max(1, min(128, int(match.group(1))))
    except ValueError:
        return 1


def camera_push_port(stream_id: str, body: dict[str, Any] | None = None) -> int:
    body = body or {}
    raw = body.get("port") or body.get("rtmpPort") or body.get("rtmp_port")
    if raw in {None, ""}:
        base = int(os.getenv("HERMES_WASM_AGENT_RTMP_INGEST_PORT", str(DEFAULT_CAMERA_PUSH_RTMP_PORT)) or DEFAULT_CAMERA_PUSH_RTMP_PORT)
        return max(1024, min(65535, base + camera_push_stream_index(stream_id) - 1))
    try:
        return max(1024, min(65535, int(float(str(raw)))))
    except (TypeError, ValueError):
        raise BrowserError("camera_push_bad_port", "RTMP push ingest port must be a number between 1024 and 65535.", status=HTTPStatus.BAD_REQUEST)


def camera_push_stream_dir(server: WasmAgentServer, stream_id: str) -> Path:
    path = camera_push_root(server) / safe_camera_push_stream_id(stream_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def camera_push_session_path(server: WasmAgentServer, stream_id: str) -> Path:
    return camera_push_stream_dir(server, stream_id) / "session.json"


def camera_push_latest_frame_path(server: WasmAgentServer, stream_id: str) -> Path:
    return camera_push_stream_dir(server, stream_id) / "latest.jpg"


def camera_push_archive_dir(server: WasmAgentServer, stream_id: str) -> Path:
    path = camera_push_stream_dir(server, stream_id) / "archive"
    path.mkdir(parents=True, exist_ok=True)
    return path


def camera_push_playback_dir(server: WasmAgentServer, stream_id: str) -> Path:
    path = camera_push_stream_dir(server, stream_id) / "playback"
    path.mkdir(parents=True, exist_ok=True)
    return path


def camera_push_log_path(server: WasmAgentServer, stream_id: str) -> Path:
    return camera_push_stream_dir(server, stream_id) / "ffmpeg.log"


def camera_push_read_session(server: WasmAgentServer, stream_id: str) -> dict[str, Any]:
    payload = read_json_file(camera_push_session_path(server, stream_id), {})
    return payload if isinstance(payload, dict) else {}


def camera_push_write_session(server: WasmAgentServer, stream_id: str, payload: dict[str, Any]) -> None:
    write_json_file(camera_push_session_path(server, stream_id), payload)


def camera_push_public_host(body: dict[str, Any], handler: WasmAgentHandler | None = None) -> str:
    explicit = str(body.get("publicHost") or body.get("public_host") or os.getenv("HERMES_WASM_AGENT_RTMP_PUBLIC_HOST", "")).strip()
    if explicit:
        return explicit.replace("rtmp://", "").replace("rtmps://", "").split("/", 1)[0].split(":", 1)[0]
    host = request_host_origin(handler).removeprefix("https://").removeprefix("http://").split(":", 1)[0] if handler else ""
    return host or "127.0.0.1"


def camera_push_public_port(bind_port: int, body: dict[str, Any]) -> int:
    raw = body.get("publicPort") or body.get("public_port") or os.getenv("HERMES_WASM_AGENT_RTMP_PUBLIC_PORT", "")
    if raw in {None, ""}:
        return bind_port
    try:
        return max(1, min(65535, int(float(str(raw)))))
    except (TypeError, ValueError):
        return bind_port


def camera_push_stream_key(existing: dict[str, Any], stream_id: str) -> str:
    previous = str(existing.get("stream_key") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9._-]{6,96}", previous):
        return previous
    token = secrets.token_urlsafe(9).replace("_", "").replace("-", "")
    return f"{safe_camera_push_stream_id(stream_id)}-{token}"


def camera_push_rtmp_urls(
    *,
    stream_id: str,
    stream_key: str,
    bind_port: int,
    body: dict[str, Any],
    handler: WasmAgentHandler | None = None,
) -> tuple[str, str]:
    bind_host = str(body.get("bindHost") or body.get("bind_host") or os.getenv("HERMES_WASM_AGENT_RTMP_BIND_HOST", "0.0.0.0") or "0.0.0.0").strip()
    public_host = camera_push_public_host(body, handler)
    public_port = camera_push_public_port(bind_port, body)
    bind_url = f"rtmp://{bind_host}:{bind_port}/live/{quote(stream_key, safe='._-')}"
    public_url = f"rtmp://{public_host}:{public_port}/live/{quote(stream_key, safe='._-')}"
    return bind_url, public_url


def camera_push_ffmpeg_command(input_url: str, output_path: Path, *, fps: int, quality: int) -> list[str]:
    return [
        camera_rtsp_ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-listen",
        "1",
        "-i",
        input_url,
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"fps={max(1, min(15, fps))}",
        "-q:v",
        str(max(2, min(12, quality))),
        "-f",
        "image2",
        "-update",
        "1",
        "-y",
        str(output_path),
    ]


def camera_push_process_for(server: WasmAgentServer, stream_id: str) -> subprocess.Popen[bytes] | None:
    processes = getattr(server, "camera_push_processes", {})
    proc = processes.get(stream_id) if isinstance(processes, dict) else None
    return proc if proc is not None and hasattr(proc, "poll") else None


def camera_push_process_running(server: WasmAgentServer, stream_id: str) -> bool:
    proc = camera_push_process_for(server, stream_id)
    if proc is not None:
        return proc.poll() is None
    session = camera_push_read_session(server, stream_id)
    pid = int(session.get("pid") or 0)
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def camera_push_frame_info(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    stat = path.stat()
    age_sec = max(0.0, time.time() - stat.st_mtime)
    return {
        "available": True,
        "bytes": stat.st_size,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
        "age_sec": round(age_sec, 3),
        "fresh": age_sec <= DEFAULT_CAMERA_PUSH_STALE_AFTER_SEC,
        "stale_after_sec": DEFAULT_CAMERA_PUSH_STALE_AFTER_SEC,
    }


def camera_push_archive_latest_frame(
    server: WasmAgentServer,
    stream_id: str,
    frame_path: Path | None = None,
    *,
    min_interval_sec: int = 0,
) -> Path | None:
    frame_path = frame_path or camera_push_latest_frame_path(server, stream_id)
    if not frame_path.exists():
        return None
    try:
        stat = frame_path.stat()
    except OSError:
        return None
    if stat.st_size <= 0:
        return None
    archive_dir = camera_push_archive_dir(server, stream_id)
    if min_interval_sec > 0:
        newest: tuple[float, Path] | None = None
        for existing in archive_dir.glob("*.jpg"):
            try:
                existing_stat = existing.stat()
            except OSError:
                continue
            if newest is None or existing_stat.st_mtime > newest[0]:
                newest = (existing_stat.st_mtime, existing)
        if newest is not None and stat.st_mtime - newest[0] < min_interval_sec:
            return newest[1]
    archive_path = archive_dir / f"{stat.st_mtime_ns}-{stat.st_size}.jpg"
    if not archive_path.exists():
        try:
            shutil.copy2(frame_path, archive_path)
        except OSError:
            return None
    camera_push_prune_archive(server, stream_id)
    return archive_path


def camera_push_playback_latest_frame(
    server: WasmAgentServer,
    stream_id: str,
    frame_path: Path | None = None,
    *,
    min_interval_sec: float = DEFAULT_CAMERA_PUSH_PLAYBACK_SAMPLE_SEC,
) -> Path | None:
    frame_path = frame_path or camera_push_latest_frame_path(server, stream_id)
    if not frame_path.exists():
        return None
    try:
        stat = frame_path.stat()
    except OSError:
        return None
    if stat.st_size <= 0:
        return None
    try:
        data = frame_path.read_bytes()
        after_stat = frame_path.stat()
    except OSError:
        return None
    if after_stat.st_mtime_ns != stat.st_mtime_ns or after_stat.st_size != stat.st_size:
        stat = after_stat
        try:
            data = frame_path.read_bytes()
        except OSError:
            return None
    if not data:
        return None
    playback_dir = camera_push_playback_dir(server, stream_id)
    newest: tuple[float, Path] | None = None
    for existing in playback_dir.glob("*.jpg"):
        try:
            existing_stat = existing.stat()
        except OSError:
            continue
        if newest is None or existing_stat.st_mtime > newest[0]:
            newest = (existing_stat.st_mtime, existing)
    if not data.startswith(b"\xff\xd8") or not data.rstrip().endswith(b"\xff\xd9"):
        return newest[1] if newest is not None else None
    if min_interval_sec > 0 and newest is not None and stat.st_mtime - newest[0] < min_interval_sec:
        return newest[1]
    playback_path = playback_dir / f"{stat.st_mtime_ns}-{stat.st_size}.jpg"
    if not playback_path.exists():
        temp_path = playback_dir / f".{playback_path.name}.tmp"
        try:
            temp_path.write_bytes(data)
            os.utime(temp_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            temp_path.replace(playback_path)
        except OSError:
            try:
                temp_path.unlink()
            except OSError:
                pass
            return None
    else:
        try:
            os.utime(playback_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        except OSError:
            pass
    camera_push_prune_playback(server, stream_id)
    return playback_path


def camera_push_prune_archive(server: WasmAgentServer, stream_id: str, keep_sec: int = DEFAULT_CAMERA_PUSH_ARCHIVE_RETENTION_SEC) -> None:
    archive_dir = camera_push_archive_dir(server, stream_id)
    cutoff = time.time() - max(DEFAULT_CAMERA_PUSH_REPLAY_SEC, min(DEFAULT_CAMERA_PUSH_ARCHIVE_RETENTION_SEC, keep_sec))
    for path in archive_dir.glob("*.jpg"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def camera_push_prune_playback(server: WasmAgentServer, stream_id: str, keep_sec: int = DEFAULT_CAMERA_PUSH_PLAYBACK_RETENTION_SEC) -> None:
    playback_dir = camera_push_playback_dir(server, stream_id)
    cutoff = time.time() - max(30, min(DEFAULT_CAMERA_PUSH_PLAYBACK_RETENTION_SEC, keep_sec))
    for path in playback_dir.glob("*.jpg"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def safe_camera_push_archive_frame_id(raw: Any) -> str:
    frame_id = Path(str(raw or "")).name
    if not re.fullmatch(r"\d+-\d+\.jpg", frame_id):
        raise BrowserError("camera_push_bad_frame", "Camera timeline frame id is invalid.", status=HTTPStatus.BAD_REQUEST)
    return frame_id


def camera_push_archive_frame_path(server: WasmAgentServer, stream_id: str, frame_id: Any) -> Path:
    archive_dir = camera_push_archive_dir(server, stream_id).resolve()
    path = (archive_dir / safe_camera_push_archive_frame_id(frame_id)).resolve()
    if path.parent != archive_dir:
        raise BrowserError("camera_push_bad_frame", "Camera timeline frame id is invalid.", status=HTTPStatus.BAD_REQUEST)
    return path


def camera_push_archive_frame_url(stream_id: str, frame_id: str) -> str:
    return f"/camera/push-archive-frame?stream_id={quote(stream_id, safe='')}&frame={quote(frame_id, safe='')}"


def camera_push_archive_frame_record(stream_id: str, path: Path) -> dict[str, Any] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    if stat.st_size <= 0:
        return None
    frame_id = path.name
    return {
        "id": frame_id,
        "url": camera_push_archive_frame_url(stream_id, frame_id),
        "bytes": stat.st_size,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
        "timestamp_ms": int(stat.st_mtime * 1000),
    }


def camera_push_timeline(
    server: WasmAgentServer,
    stream_id: Any = "cam-1",
    day: Any = "",
    mode: Any = "live",
    seconds: Any = DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC,
) -> dict[str, Any]:
    clean_stream = safe_camera_push_stream_id(stream_id)
    camera_push_archive_latest_frame(
        server,
        clean_stream,
        min_interval_sec=DEFAULT_CAMERA_PUSH_TIMELINE_SAMPLE_SEC,
    )
    camera_push_prune_archive(server, clean_stream)
    clean_mode = str(mode or "live").strip().lower()
    if clean_mode not in {"live", "recorded"}:
        clean_mode = "live"
    try:
        live_seconds = int(float(str(seconds or DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC)))
    except (TypeError, ValueError):
        live_seconds = DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC
    live_seconds = max(60, min(24 * 60 * 60, live_seconds))
    requested_day = str(day or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", requested_day):
        requested_day = time.strftime("%Y-%m-%d", time.gmtime())
    frames: list[dict[str, Any]] = []
    latest_frame_ms = 0
    latest_frame_path = camera_push_latest_frame_path(server, clean_stream)
    try:
        latest_frame_stat = latest_frame_path.stat()
        if latest_frame_stat.st_size > 0:
            latest_frame_ms = int(latest_frame_stat.st_mtime * 1000)
    except OSError:
        latest_frame_ms = 0
    latest_playback = camera_push_playback_latest_frame(server, clean_stream)
    if latest_playback:
        try:
            latest_frame_ms = max(latest_frame_ms, int(latest_playback.stat().st_mtime * 1000))
        except OSError:
            pass
    for path in camera_push_archive_dir(server, clean_stream).glob("*.jpg"):
        record = camera_push_archive_frame_record(clean_stream, path)
        if not record:
            continue
        if clean_mode == "recorded" or str(record["updated_at"])[:10] == requested_day:
            frames.append(record)
    frames.sort(key=lambda item: int(item["timestamp_ms"]))
    available_start_ms = int(frames[0]["timestamp_ms"]) if frames else 0
    sampled_available_end_ms = int(frames[-1]["timestamp_ms"]) if frames else 0
    available_end_ms = max(sampled_available_end_ms, latest_frame_ms)
    if not available_start_ms and latest_frame_ms:
        available_start_ms = latest_frame_ms
    end_ms = available_end_ms if clean_mode == "live" else sampled_available_end_ms
    start_ms = max(available_start_ms, end_ms - (live_seconds * 1000)) if clean_mode == "live" and end_ms else available_start_ms
    visible_frames = [
        frame for frame in frames
        if not end_ms or (start_ms <= int(frame["timestamp_ms"]) <= end_ms)
    ]
    return {
        "ok": True,
        "schema": f"{CAMERA_PUSH_SCHEMA}.timeline",
        "stream_id": clean_stream,
        "mode": clean_mode,
        "day": requested_day,
        "range_source": "wasm-agent-retained-archive",
        "sample_interval_sec": DEFAULT_CAMERA_PUSH_TIMELINE_SAMPLE_SEC,
        "live_window_sec": live_seconds,
        "retention_sec": DEFAULT_CAMERA_PUSH_ARCHIVE_RETENTION_SEC,
        "available_range": {
            "start_ms": available_start_ms,
            "end_ms": available_end_ms,
            "frame_count": len(frames),
            "duration_sec": int(max(0, available_end_ms - available_start_ms) / 1000),
        },
        "range": {
            "start_ms": start_ms,
            "end_ms": end_ms,
            "duration_sec": int(max(0, end_ms - start_ms) / 1000),
        },
        "frames": visible_frames[-2880:],
    }


def camera_push_recent_archive_frames(server: WasmAgentServer, stream_id: str, seconds: Any = DEFAULT_CAMERA_PUSH_REPLAY_SEC) -> list[Path]:
    try:
        replay_sec = int(float(str(seconds or DEFAULT_CAMERA_PUSH_REPLAY_SEC)))
    except (TypeError, ValueError):
        replay_sec = DEFAULT_CAMERA_PUSH_REPLAY_SEC
    replay_sec = max(5, min(DEFAULT_CAMERA_PUSH_REPLAY_MAX_SEC, replay_sec))
    camera_push_archive_latest_frame(server, stream_id, min_interval_sec=DEFAULT_CAMERA_PUSH_TIMELINE_SAMPLE_SEC)
    camera_push_prune_archive(server, stream_id)
    cutoff = time.time() - replay_sec
    frames: list[tuple[float, Path]] = []
    for path in camera_push_archive_dir(server, stream_id).glob("*.jpg"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size > 0 and stat.st_mtime >= cutoff:
            frames.append((stat.st_mtime, path))
    return [path for _mtime, path in sorted(frames)]


def camera_push_playback_frames_from(
    server: WasmAgentServer,
    stream_id: str,
    from_ms: Any = 0,
    seconds: Any = DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC,
) -> list[Path]:
    try:
        start_ms = int(float(str(from_ms or 0)))
    except (TypeError, ValueError):
        start_ms = 0
    try:
        playback_sec = int(float(str(seconds or DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC)))
    except (TypeError, ValueError):
        playback_sec = DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC
    playback_sec = max(5, min(DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC, playback_sec))
    end_ms = start_ms + (playback_sec * 1000) if start_ms > 0 else 0
    frames = camera_push_recorded_frame_candidates(
        server,
        stream_id,
        start_ms=start_ms,
        end_ms=end_ms,
        refresh_latest=True,
    )
    return [path for _mtime_ns, _source_priority, path, _stat in frames]


def camera_push_recorded_frame_candidates(
    server: WasmAgentServer,
    stream_id: str,
    *,
    start_ms: int = 0,
    after_mtime_ns: int = -1,
    end_ms: int = 0,
    include_archive: bool = True,
    refresh_latest: bool = True,
) -> list[tuple[int, int, Path, os.stat_result]]:
    if refresh_latest:
        camera_push_playback_latest_frame(server, stream_id)
    camera_push_prune_playback(server, stream_id)
    if include_archive:
        camera_push_prune_archive(server, stream_id)
    playback_dir = camera_push_playback_dir(server, stream_id)
    directories: list[tuple[int, Path]] = [(0, playback_dir)]
    if include_archive:
        directories.append((1, camera_push_archive_dir(server, stream_id)))
    by_mtime_ns: dict[int, tuple[int, Path, os.stat_result]] = {}
    for source_priority, directory in directories:
        for path in directory.glob("*.jpg"):
            try:
                stat = path.stat()
            except OSError:
                continue
            timestamp_ms = int(stat.st_mtime * 1000)
            if stat.st_size <= 0 or stat.st_mtime_ns <= after_mtime_ns:
                continue
            if start_ms > 0 and timestamp_ms < start_ms:
                continue
            if end_ms > 0 and timestamp_ms > end_ms:
                continue
            existing = by_mtime_ns.get(stat.st_mtime_ns)
            if existing is not None and existing[0] <= source_priority:
                continue
            by_mtime_ns[stat.st_mtime_ns] = (source_priority, path, stat)
    return [
        (mtime_ns, source_priority, path, stat)
        for mtime_ns, (source_priority, path, stat)
        in sorted(by_mtime_ns.items(), key=lambda item: (item[0], item[1][0]))
    ]


def camera_push_playback_frame_count_from(
    server: WasmAgentServer,
    stream_id: str,
    *,
    start_ms: int = 0,
    end_ms: int = 0,
    include_archive: bool = True,
    refresh_latest: bool = False,
) -> int:
    return len(camera_push_recorded_frame_candidates(
        server,
        stream_id,
        start_ms=start_ms,
        end_ms=end_ms,
        include_archive=include_archive,
        refresh_latest=refresh_latest,
    ))


def camera_push_next_playback_frame(
    server: WasmAgentServer,
    stream_id: str,
    *,
    start_ms: int = 0,
    after_mtime_ns: int = -1,
    end_ms: int = 0,
    include_archive: bool = True,
    refresh_latest: bool = True,
) -> tuple[Path, os.stat_result] | None:
    frames = camera_push_recorded_frame_candidates(
        server,
        stream_id,
        start_ms=start_ms,
        after_mtime_ns=after_mtime_ns,
        end_ms=end_ms,
        include_archive=include_archive,
        refresh_latest=refresh_latest,
    )
    if not frames:
        return None
    _mtime_ns, _source_priority, path, stat = frames[0]
    return path, stat


def camera_push_nearest_playback_frame(
    server: WasmAgentServer,
    stream_id: str,
    *,
    target_ms: int = 0,
    end_ms: int = 0,
    max_distance_ms: int = 0,
    include_archive: bool = True,
    refresh_latest: bool = True,
) -> tuple[Path, os.stat_result] | None:
    if target_ms <= 0:
        return camera_push_next_playback_frame(
            server,
            stream_id,
            start_ms=0,
            after_mtime_ns=-1,
            end_ms=end_ms,
            include_archive=include_archive,
            refresh_latest=refresh_latest,
        )
    frames = camera_push_recorded_frame_candidates(
        server,
        stream_id,
        end_ms=end_ms,
        include_archive=include_archive,
        refresh_latest=refresh_latest,
    )
    if not frames:
        return None
    nearest: list[tuple[int, int, Path, os.stat_result]] = []
    for _mtime_ns, _source_priority, path, stat in frames:
        try:
            timestamp_ms = int(stat.st_mtime * 1000)
        except (OverflowError, ValueError):
            timestamp_ms = 0
        nearest.append((abs(timestamp_ms - target_ms), stat.st_mtime_ns, path, stat))
    distance_ms, _mtime_ns, path, stat = sorted(nearest, key=lambda item: (item[0], item[1]))[0]
    if max_distance_ms > 0 and distance_ms > max_distance_ms:
        return None
    return path, stat


def camera_push_frame_url(stream_id: str) -> str:
    return f"/camera/push-frame?stream_id={quote(stream_id, safe='')}"


def camera_push_stream_url(stream_id: str) -> str:
    return f"/camera/push-stream?stream_id={quote(stream_id, safe='')}"


def camera_push_replay_url(stream_id: str, seconds: int = DEFAULT_CAMERA_PUSH_REPLAY_SEC) -> str:
    return f"/camera/push-replay?stream_id={quote(stream_id, safe='')}&seconds={int(seconds)}"


def camera_push_status(server: WasmAgentServer, stream_id: Any = "cam-1", handler: WasmAgentHandler | None = None) -> dict[str, Any]:
    clean_stream = safe_camera_push_stream_id(stream_id)
    session = camera_push_read_session(server, clean_stream)
    bind_port = int(session.get("bind_port") or camera_push_port(clean_stream))
    stream_key = camera_push_stream_key(session, clean_stream)
    _bind_url, public_url = camera_push_rtmp_urls(
        stream_id=clean_stream,
        stream_key=stream_key,
        bind_port=bind_port,
        body=session,
        handler=handler,
    )
    frame_path = camera_push_latest_frame_path(server, clean_stream)
    camera_push_archive_latest_frame(
        server,
        clean_stream,
        frame_path,
        min_interval_sec=DEFAULT_CAMERA_PUSH_TIMELINE_SAMPLE_SEC,
    )
    frame = camera_push_frame_info(frame_path)
    running = camera_push_process_running(server, clean_stream)
    fresh = bool(frame.get("available") and frame.get("fresh"))
    state = "receiving" if fresh and running else ("stale" if frame.get("available") else ("listening" if running else ("stopped" if session else "not_configured")))
    replay_frames = camera_push_recent_archive_frames(server, clean_stream)
    return {
        "ok": True,
        "schema": CAMERA_PUSH_SCHEMA,
        "stream_id": clean_stream,
        "state": state,
        "running": running,
        "ingest": {
            "mode": "rtmp-push",
            "url": public_url,
            "bind_port": bind_port,
            "app": "live",
            "stream_key": stream_key,
        },
        "frame": {
            **frame,
            "url": camera_push_frame_url(clean_stream),
        },
        "stream": {
            "url": camera_push_stream_url(clean_stream),
            "mode": "mjpeg",
            "fps": int(session.get("fps") or DEFAULT_CAMERA_PUSH_FRAME_FPS),
            "audio": False,
        },
        "audio": {
            "available": False,
            "source": "jpeg-frame-extractor",
        },
        "replay": {
            "url": camera_push_replay_url(clean_stream),
            "seconds": DEFAULT_CAMERA_PUSH_REPLAY_SEC,
            "frame_count": len(replay_frames),
        },
        "pid": int(session.get("pid") or 0),
        "started_at": str(session.get("started_at") or ""),
        "log_path": str(camera_push_log_path(server, clean_stream)),
    }


def start_camera_push_ingest(server: WasmAgentServer, body: dict[str, Any], handler: WasmAgentHandler | None = None) -> dict[str, Any]:
    stream_id = safe_camera_push_stream_id(body.get("stream_id") or body.get("streamId") or body.get("stream") or "cam-1")
    stream_dir = camera_push_stream_dir(server, stream_id)
    latest_path = camera_push_latest_frame_path(server, stream_id)
    existing = camera_push_read_session(server, stream_id)
    bind_port = camera_push_port(stream_id, body or existing)
    stream_key = camera_push_stream_key(existing, stream_id)
    bind_url, public_url = camera_push_rtmp_urls(
        stream_id=stream_id,
        stream_key=stream_key,
        bind_port=bind_port,
        body={**existing, **body},
        handler=handler,
    )
    fps = max(1, min(15, int(float(body.get("fps") or existing.get("fps") or DEFAULT_CAMERA_PUSH_FRAME_FPS))))
    quality = max(2, min(12, int(float(body.get("quality") or existing.get("quality") or DEFAULT_CAMERA_PUSH_FRAME_QUALITY))))
    command = camera_push_ffmpeg_command(bind_url, latest_path, fps=fps, quality=quality)
    lock = getattr(server, "camera_push_processes_lock", threading.Lock())
    with lock:
        proc = camera_push_process_for(server, stream_id)
        if proc is not None and proc.poll() is None:
            if (
                int(existing.get("fps") or 0) == fps
                and int(existing.get("quality") or 0) == quality
                and int(existing.get("bind_port") or bind_port) == bind_port
            ):
                return camera_push_status(server, stream_id, handler)
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
            getattr(server, "camera_push_processes", {}).pop(stream_id, None)
        if proc is None and camera_push_process_running(server, stream_id):
            if (
                int(existing.get("fps") or 0) == fps
                and int(existing.get("quality") or 0) == quality
                and int(existing.get("bind_port") or bind_port) == bind_port
            ):
                return camera_push_status(server, stream_id, handler)
            try:
                os.kill(int(existing.get("pid") or 0), 15)
            except OSError:
                pass
        log_handle = camera_push_log_path(server, stream_id).open("ab")
        try:
            proc = subprocess.Popen(
                command,
                cwd=str(stream_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log_handle,
            )
        except FileNotFoundError as exc:
            raise BrowserError("camera_push_ffmpeg_missing", "RTMP push ingest requires ffmpeg on the wasm-agent host.", status=HTTPStatus.BAD_GATEWAY) from exc
        except OSError as exc:
            raise BrowserError("camera_push_start_failed", f"Could not start the RTMP ingest listener on port {bind_port}: {exc}", status=HTTPStatus.BAD_GATEWAY) from exc
        finally:
            log_handle.close()
        getattr(server, "camera_push_processes", {})[stream_id] = proc
    session = {
        "schema": CAMERA_PUSH_SCHEMA,
        "stream_id": stream_id,
        "stream_key": stream_key,
        "bind_port": bind_port,
        "public_url": public_url,
        "fps": fps,
        "quality": quality,
        "pid": proc.pid,
        "started_at": iso_timestamp(),
        "publicHost": camera_push_public_host(body, handler),
        "publicPort": camera_push_public_port(bind_port, body),
    }
    camera_push_write_session(server, stream_id, session)
    return camera_push_status(server, stream_id, handler)


def stop_camera_push_ingest(server: WasmAgentServer, body: dict[str, Any], handler: WasmAgentHandler | None = None) -> dict[str, Any]:
    stream_id = safe_camera_push_stream_id(body.get("stream_id") or body.get("streamId") or body.get("stream") or "cam-1")
    proc = camera_push_process_for(server, stream_id)
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=4)
    session = camera_push_read_session(server, stream_id)
    if proc is None and int(session.get("pid") or 0) > 0:
        try:
            os.kill(int(session.get("pid") or 0), 15)
        except OSError:
            pass
    if session:
        session["stopped_at"] = iso_timestamp()
        session["pid"] = 0
        camera_push_write_session(server, stream_id, session)
    return camera_push_status(server, stream_id, handler)


def serve_camera_push_frame(handler: WasmAgentHandler, stream_id: Any) -> None:
    clean_stream = safe_camera_push_stream_id(stream_id)
    frame_path = camera_push_latest_frame_path(handler.server, clean_stream)
    if not frame_path.exists():
        raise BrowserError("camera_push_frame_missing", "No RTMP-pushed frame is available yet.", status=HTTPStatus.NOT_FOUND)
    data = frame_path.read_bytes()
    if not data:
        raise BrowserError("camera_push_frame_empty", "The latest RTMP-pushed frame is empty.", status=HTTPStatus.NOT_FOUND)
    camera_push_playback_latest_frame(
        handler.server,
        clean_stream,
        frame_path,
        min_interval_sec=DEFAULT_CAMERA_PUSH_PLAYBACK_SAMPLE_SEC,
    )
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "image/jpeg")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(data)


def serve_camera_push_archive_frame(handler: WasmAgentHandler, stream_id: Any, frame_id: Any) -> None:
    clean_stream = safe_camera_push_stream_id(stream_id)
    frame_path = camera_push_archive_frame_path(handler.server, clean_stream, frame_id)
    if not frame_path.exists():
        raise BrowserError("camera_push_archive_frame_missing", "That camera timeline frame is no longer retained.", status=HTTPStatus.NOT_FOUND)
    data = frame_path.read_bytes()
    if not data:
        raise BrowserError("camera_push_archive_frame_empty", "That camera timeline frame is empty.", status=HTTPStatus.NOT_FOUND)
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "image/jpeg")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(data)


def camera_push_request_fps(handler: WasmAgentHandler, stream_id: str) -> float:
    query = parse_qs(urlparse(handler.path).query)
    raw = (query.get("fps") or [""])[0]
    if raw in {None, ""}:
        raw = camera_push_read_session(handler.server, stream_id).get("fps") or DEFAULT_CAMERA_PUSH_FRAME_FPS
    try:
        return max(1.0, min(15.0, float(str(raw))))
    except (TypeError, ValueError):
        return float(DEFAULT_CAMERA_PUSH_FRAME_FPS)


def write_camera_push_mjpeg_frame(handler: WasmAgentHandler, boundary: str, data: bytes, path: Path) -> None:
    try:
        stat = path.stat()
        updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime))
        timestamp_ms = int(stat.st_mtime * 1000)
    except OSError:
        updated_at = iso_timestamp()
        timestamp_ms = int(time.time() * 1000)
    header = (
        f"--{boundary}\r\n"
        "Content-Type: image/jpeg\r\n"
        f"Content-Length: {len(data)}\r\n"
        f"X-Frame-Updated-At: {updated_at}\r\n"
        f"X-Frame-Timestamp-Ms: {timestamp_ms}\r\n"
        f"X-Frame-Id: {path.name}\r\n"
        "\r\n"
    ).encode("ascii")
    handler.wfile.write(header)
    handler.wfile.write(data)
    handler.wfile.write(b"\r\n")
    handler.wfile.flush()


def send_camera_push_mjpeg_headers(handler: WasmAgentHandler, boundary: str) -> None:
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Connection", "close")
    handler.send_header("X-Accel-Buffering", "no")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()


def serve_camera_push_mjpeg_stream(handler: WasmAgentHandler, stream_id: Any) -> None:
    clean_stream = safe_camera_push_stream_id(stream_id)
    frame_path = camera_push_latest_frame_path(handler.server, clean_stream)
    fps = camera_push_request_fps(handler, clean_stream)
    interval = 1.0 / fps
    last_mtime_ns = -1
    boundary = CAMERA_PUSH_MJPEG_BOUNDARY
    send_camera_push_mjpeg_headers(handler, boundary)
    while True:
        try:
            stat = frame_path.stat()
        except OSError:
            time.sleep(min(0.5, interval))
            continue
        if time.time() - stat.st_mtime > DEFAULT_CAMERA_PUSH_STALE_AFTER_SEC:
            last_mtime_ns = max(last_mtime_ns, stat.st_mtime_ns)
            time.sleep(min(0.5, interval))
            continue
        if stat.st_size <= 0 or stat.st_mtime_ns == last_mtime_ns:
            time.sleep(min(0.5, interval))
            continue
        data = frame_path.read_bytes()
        if not data:
            time.sleep(min(0.5, interval))
            continue
        last_mtime_ns = stat.st_mtime_ns
        camera_push_archive_latest_frame(handler.server, clean_stream, frame_path)
        camera_push_playback_latest_frame(handler.server, clean_stream, frame_path)
        write_camera_push_mjpeg_frame(handler, boundary, data, frame_path)
        time.sleep(interval)


def serve_camera_push_replay(handler: WasmAgentHandler, stream_id: Any, seconds: Any = DEFAULT_CAMERA_PUSH_REPLAY_SEC) -> None:
    clean_stream = safe_camera_push_stream_id(stream_id)
    fps = camera_push_request_fps(handler, clean_stream)
    interval = 1.0 / min(fps, 15.0)
    frames = camera_push_recent_archive_frames(handler.server, clean_stream, seconds)
    if not frames:
        raise BrowserError("camera_push_replay_empty", "No archived camera frames are available for replay yet.", status=HTTPStatus.NOT_FOUND)
    boundary = f"{CAMERA_PUSH_MJPEG_BOUNDARY}-replay"
    send_camera_push_mjpeg_headers(handler, boundary)
    for frame_path in frames:
        try:
            data = frame_path.read_bytes()
        except OSError:
            continue
        if not data:
            continue
        write_camera_push_mjpeg_frame(handler, boundary, data, frame_path)
        time.sleep(interval)


def serve_camera_push_playback(
    handler: WasmAgentHandler,
    stream_id: Any,
    from_ms: Any = 0,
    seconds: Any = DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC,
    follow: Any = "1",
) -> None:
    clean_stream = safe_camera_push_stream_id(stream_id)
    try:
        start_ms = int(float(str(from_ms or 0)))
    except (TypeError, ValueError):
        start_ms = 0
    try:
        playback_sec = int(float(str(seconds or DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC)))
    except (TypeError, ValueError):
        playback_sec = DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC
    playback_sec = max(5, min(DEFAULT_CAMERA_PUSH_TIMELINE_LIVE_SEC, playback_sec))
    end_ms = start_ms + (playback_sec * 1000) if start_ms > 0 else 0
    should_follow = str(follow or "1").strip().lower() not in {"0", "false", "no", "off"}
    first = camera_push_nearest_playback_frame(
        handler.server,
        clean_stream,
        end_ms=0 if should_follow else end_ms,
        target_ms=start_ms,
        max_distance_ms=int(DEFAULT_CAMERA_PUSH_PLAYBACK_GAP_SEC * 1000) if start_ms > 0 else 0,
        include_archive=True,
        refresh_latest=should_follow,
    )
    if not first:
        raise BrowserError("camera_push_playback_empty", "No smooth camera playback frames are available from that point yet.", status=HTTPStatus.NOT_FOUND)
    boundary = f"{CAMERA_PUSH_MJPEG_BOUNDARY}-playback"
    send_camera_push_mjpeg_headers(handler, boundary)
    origin_media_sec = 0.0
    origin_wall_sec = 0.0
    previous_media_sec = 0.0
    last_mtime_ns = -1
    next_frame: tuple[Path, os.stat_result] | None = first
    while next_frame:
        frame_path, stat = next_frame
        if previous_media_sec and stat.st_mtime - previous_media_sec > DEFAULT_CAMERA_PUSH_PLAYBACK_GAP_SEC:
            break
        if not origin_media_sec:
            origin_media_sec = stat.st_mtime
            origin_wall_sec = time.monotonic()
        target_wall_sec = origin_wall_sec + max(0.0, stat.st_mtime - origin_media_sec)
        delay_sec = target_wall_sec - time.monotonic()
        if delay_sec > 0:
            time.sleep(delay_sec)
        try:
            data = frame_path.read_bytes()
        except OSError:
            data = b""
        last_mtime_ns = stat.st_mtime_ns
        previous_media_sec = stat.st_mtime
        if data:
            write_camera_push_mjpeg_frame(handler, boundary, data, frame_path)
        while True:
            next_frame = camera_push_next_playback_frame(
                handler.server,
                clean_stream,
                start_ms=start_ms,
                after_mtime_ns=last_mtime_ns,
                end_ms=0 if should_follow else end_ms,
                include_archive=True,
                refresh_latest=should_follow,
            )
            if next_frame or not should_follow:
                break
            time.sleep(0.05)


def read_camera_process_chunk(process: subprocess.Popen[bytes], timeout_sec: float) -> bytes:
    assert process.stdout is not None
    deadline = time.monotonic() + max(0.5, timeout_sec)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            chunk = process.stdout.read(DEFAULT_CAMERA_STREAM_PROXY_CHUNK_BYTES)
            return chunk or b""
        ready, _, _ = select.select([process.stdout], [], [], min(0.25, max(0.0, deadline - time.monotonic())))
        if not ready:
            continue
        chunk = process.stdout.read(DEFAULT_CAMERA_STREAM_PROXY_CHUNK_BYTES)
        return chunk or b""
    return b""


def serve_camera_rtsp_mjpeg_proxy(handler: WasmAgentHandler, token: str) -> None:
    session = camera_stream_session_for_token(handler.server, token)
    if str(session.get("transport") or "") != "rtsp-mjpeg":
        raise BrowserError("camera_rtsp_wrong_transport", "Camera stream token is not for the RTSP relay.", status=HTTPStatus.BAD_REQUEST)
    clean_url = str(session.get("url") or "")
    if not skip_camera_rtsp_preflight():
        camera_rtsp_tcp_preflight(clean_url)
    input_url = camera_url_with_credentials(
        clean_url,
        str(session.get("username") or ""),
        str(session.get("password") or ""),
    )
    timeout_ms = max(1000, min(60000, int(session.get("timeout_ms") or DEFAULT_CAMERA_RTSP_RELAY_TIMEOUT_SEC * 1000)))
    fps = max(1, min(12, int(session.get("fps") or DEFAULT_CAMERA_RTSP_RELAY_FPS)))
    quality = max(2, min(12, int(session.get("quality") or DEFAULT_CAMERA_RTSP_RELAY_QUALITY)))
    command = camera_rtsp_ffmpeg_command(input_url, timeout_ms=timeout_ms, fps=fps, quality=quality)
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise BrowserError("camera_rtsp_ffmpeg_missing", "True RTSP camera relay requires ffmpeg on the wasm-agent host.", status=HTTPStatus.BAD_GATEWAY) from exc
    except Exception as exc:
        raise BrowserError("camera_rtsp_start_failed", f"Could not start the RTSP camera relay: {exc}", status=HTTPStatus.BAD_GATEWAY) from exc

    first_chunk = read_camera_process_chunk(process, min(DEFAULT_CAMERA_RTSP_FRAME_TIMEOUT_SEC, timeout_ms / 1000))
    if not first_chunk:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        raise BrowserError(
            "camera_rtsp_no_frame",
            "DVR RTSP relay opened but did not emit a video frame. Check DVR/cloud reachability, credentials, channel/subtype, and RTSP enablement.",
            status=HTTPStatus.BAD_GATEWAY,
        )

    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", f"multipart/x-mixed-replace;boundary={CAMERA_RTSP_MJPEG_BOUNDARY}")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Connection", "close")
    handler.send_header("X-Accel-Buffering", "no")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    try:
        assert process.stdout is not None
        try:
            handler.wfile.write(first_chunk)
            handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        while True:
            chunk = process.stdout.read(DEFAULT_CAMERA_STREAM_PROXY_CHUNK_BYTES)
            if not chunk:
                break
            try:
                handler.wfile.write(chunk)
                handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def wasm_agent_deployment_mode() -> str:
    raw = os.getenv("HERMES_WASM_AGENT_DEPLOYMENT_MODE", DEPLOYMENT_MODE_LOCAL).strip().lower()
    if raw in {DEPLOYMENT_MODE_LOCAL, DEPLOYMENT_MODE_CLOUD}:
        return raw
    raise RuntimeError("HERMES_WASM_AGENT_DEPLOYMENT_MODE must be 'local' or 'cloud'.")


def path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def cloud_state_root(*, required: bool = False) -> Path | None:
    raw = os.getenv("HERMES_WASM_AGENT_CLOUD_STATE_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    if required:
        raise RuntimeError("Cloud mode requires HERMES_WASM_AGENT_CLOUD_STATE_ROOT.")
    return None


def default_private_state_dir(plugin_root: Path | None = None) -> Path:
    root = cloud_state_root()
    if wasm_agent_deployment_mode() == DEPLOYMENT_MODE_CLOUD:
        if root is None:
            root = cloud_state_root(required=True)
        assert root is not None
        return root / "state"
    return (plugin_root or Path(__file__).resolve().parents[1]) / "state"


def ensure_cloud_private_paths(plugin_root: Path, *paths: Path) -> None:
    if wasm_agent_deployment_mode() != DEPLOYMENT_MODE_CLOUD:
        return
    root = cloud_state_root(required=True)
    assert root is not None
    unsafe_roots = (
        plugin_root / "state",
        plugin_root / "public",
        plugin_root / "server",
        plugin_root / "tests",
        plugin_root / "conf",
    )
    for path in (root, *paths):
        resolved = path.resolve()
        if path is root:
            if path_is_under(resolved, plugin_root):
                raise RuntimeError(
                    "HERMES_WASM_AGENT_CLOUD_STATE_ROOT must not live inside the public wasm-agent plugin tree."
                )
            continue
        if not path_is_under(resolved, root):
            raise RuntimeError(f"Cloud path must live under HERMES_WASM_AGENT_CLOUD_STATE_ROOT: {resolved}")
        if any(path_is_under(resolved, unsafe) for unsafe in unsafe_roots):
            raise RuntimeError(f"Cloud path must not use repo-local wasm-agent state/source paths: {resolved}")


def resolve_wasm_agent_state_dir(plugin_root: Path) -> Path:
    raw = os.getenv("HERMES_WASM_AGENT_STATE_DIR", "").strip()
    path = Path(raw).expanduser().resolve() if raw else default_private_state_dir(plugin_root).resolve()
    ensure_cloud_private_paths(plugin_root, path)
    return path


def cloud_instance_id() -> str:
    raw = os.getenv("HERMES_WASM_AGENT_CLOUD_INSTANCE_ID", "").strip()
    if raw:
        return safe_state_id(raw, "wasm-agent-cloud")
    root = cloud_state_root()
    if root is not None:
        return safe_state_id(root.name, "wasm-agent-cloud")
    return "local-dev"


def wa_env_path() -> Path:
    raw = os.getenv("HERMES_WASM_AGENT_ENV_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    root = cloud_state_root()
    if wasm_agent_deployment_mode() == DEPLOYMENT_MODE_CLOUD and root is not None:
        return (root / "conf" / "wa.env").resolve()
    return DEFAULT_WA_ENV_PATH.resolve()


def env_file_value(name: str, *, path: Path | None = None) -> str:
    source = path or wa_env_path()
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ""
    except Exception:
        return ""
    prefix = f"{name}="
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix):].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.strip()
    return ""


def google_client_id() -> str:
    return (
        os.getenv("HERMES_WASM_AGENT_GOOGLE_CLIENT_ID", "").strip()
        or env_file_value("GOOGLE_LOGIN_CLIENT_ID")
    )


def public_origin() -> str:
    return (
        os.getenv("HERMES_WASM_AGENT_PUBLIC_ORIGIN", "").strip()
        or env_file_value("HERMES_WASM_AGENT_PUBLIC_ORIGIN")
        or env_file_value("PUBLIC_ORIGIN")
    ).rstrip("/")


def env_bool(name: str) -> bool | None:
    raw = os.getenv(name, "").strip() or env_file_value(name)
    if not raw:
        return None
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def public_deployment(handler: BaseHTTPRequestHandler | None = None) -> bool:
    if public_origin().lower().startswith("https://"):
        return True
    if handler:
        forwarded_proto = handler.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
        if forwarded_proto == "https":
            return True
        host = (handler.headers.get("Host", "") or "").split(":", 1)[0].strip().lower()
        if host and host not in {"127.0.0.1", "localhost", "::1"}:
            return True
    return False


def browser_feature_enabled(handler: BaseHTTPRequestHandler | None = None) -> bool:
    configured = env_bool("HERMES_WASM_AGENT_BROWSER_ENABLED")
    if configured is not None:
        return configured
    return not public_deployment(handler)


def shared_voice_enabled() -> bool:
    configured = env_bool("HERMES_WASM_AGENT_SHARED_VOICE_ENABLED")
    return bool(configured) if configured is not None else False


def shared_voice_ice_servers() -> list[dict[str, Any]]:
    raw = os.getenv("HERMES_WASM_AGENT_VOICE_ICE_SERVERS_JSON", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            servers = []
            for item in parsed[:8]:
                if not isinstance(item, dict):
                    continue
                urls = item.get("urls")
                if isinstance(urls, str):
                    clean_urls: str | list[str] = clipped(urls, 400)
                elif isinstance(urls, list):
                    clean_urls = [clipped(str(url), 400) for url in urls[:8] if str(url).strip()]
                else:
                    continue
                server: dict[str, Any] = {"urls": clean_urls}
                if item.get("username"):
                    server["username"] = clipped(str(item.get("username")), 240)
                if item.get("credential"):
                    server["credential"] = clipped(str(item.get("credential")), 500)
                servers.append(server)
            if servers:
                return servers
    stun_urls = [
        clipped(item, 400)
        for item in os.getenv("HERMES_WASM_AGENT_VOICE_STUN_URLS", "stun:stun.l.google.com:19302").split(",")
        if item.strip()
    ]
    return [{"urls": stun_urls or ["stun:stun.l.google.com:19302"]}]


def require_browser_feature_enabled(handler: BaseHTTPRequestHandler | None = None) -> None:
    if browser_feature_enabled(handler):
        return
    raise BrowserError(
        "browser_disabled",
        (
            "Host Browser is disabled for public deployments. Set "
            "HERMES_WASM_AGENT_BROWSER_ENABLED=1 only after CDP and "
            "private-network isolation are reviewed."
        ),
        status=HTTPStatus.FORBIDDEN,
    )


def content_security_policy(handler: BaseHTTPRequestHandler | None = None) -> str:
    img_src = "'self' data: blob: https://accounts.google.com https://lh3.googleusercontent.com"
    media_src = "'self' data: blob: https:"
    connect_src = "'self' https://accounts.google.com stun: turn: turns:"
    if not public_deployment(handler):
        img_src = "'self' data: blob: http: https:"
        media_src = "'self' data: blob: http: https:"
        connect_src = "'self' ws: wss: http: https: stun: turn: turns:"
    script_src = "'self' 'wasm-unsafe-eval' https://accounts.google.com https://cdn.jsdelivr.net"
    if not public_deployment(handler):
        script_src = "'self' 'unsafe-inline' 'wasm-unsafe-eval' https://accounts.google.com https://cdn.jsdelivr.net"
    return (
        "default-src 'self'; "
        f"script-src {script_src}; "
        "style-src 'self' 'unsafe-inline' https://accounts.google.com; "
        f"img-src {img_src}; "
        f"media-src {media_src}; "
        f"connect-src {connect_src}; "
        "frame-src https://accounts.google.com; "
        "worker-src 'self' blob:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )


def allowed_admin_emails() -> set[str]:
    raw = env_file_value("ADMIN_EMAIL")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def allowed_user_emails() -> set[str]:
    raw = env_file_value("USER_EMAILS")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def admin_email_label() -> str:
    emails = sorted(allowed_admin_emails())
    return emails[0] if len(emails) == 1 else ",".join(emails)


def is_admin_email(email: str) -> bool:
    return email.strip().lower() in allowed_admin_emails()


def is_allowed_account_email(email: str) -> bool:
    value = email.strip().lower()
    return value in allowed_admin_emails() or value in allowed_user_emails()


def auth_db_path() -> Path:
    raw = os.getenv("HERMES_WASM_AGENT_DB_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    if wasm_agent_deployment_mode() == DEPLOYMENT_MODE_CLOUD:
        return (default_private_state_dir() / "db" / "sqlite" / "wa_db.sqlite3").resolve()
    return DEFAULT_AUTH_DB_PATH.resolve()


def auth_secret_path() -> Path:
    raw = os.getenv("HERMES_WASM_AGENT_AUTH_SECRET_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    if wasm_agent_deployment_mode() == DEPLOYMENT_MODE_CLOUD:
        return (default_private_state_dir() / "db" / "sqlite" / "wa_auth_secret").resolve()
    return DEFAULT_AUTH_SECRET_PATH.resolve()


def auth_secret() -> bytes:
    raw = os.getenv("HERMES_WASM_AGENT_AUTH_SECRET", "").strip()
    if raw:
        return raw.encode("utf-8")
    path = auth_secret_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        value = secrets.token_urlsafe(48)
        path.write_text(value + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except Exception:
            pass
    return value.encode("utf-8")


def snowflake_machine_id() -> int:
    raw = os.getenv("HERMES_WASM_AGENT_SNOWFLAKE_MACHINE_ID", "").strip()
    if raw:
        try:
            return int(raw) & 0x3FF
        except ValueError:
            pass
    host = socket.gethostname().encode("utf-8", "ignore")
    digest = hashlib.blake2s(host, digest_size=2).digest()
    return int.from_bytes(digest, "big") & 0x3FF


def next_snowflake_id() -> int:
    global _SNOWFLAKE_LAST_MS, _SNOWFLAKE_SEQUENCE
    machine = snowflake_machine_id()
    with _SNOWFLAKE_LOCK:
        now_ms = int(time.time() * 1000) - WASM_AGENT_SNOWFLAKE_EPOCH_MS
        if now_ms < _SNOWFLAKE_LAST_MS:
            now_ms = _SNOWFLAKE_LAST_MS
        if now_ms == _SNOWFLAKE_LAST_MS:
            _SNOWFLAKE_SEQUENCE = (_SNOWFLAKE_SEQUENCE + 1) & 0xFFF
            if _SNOWFLAKE_SEQUENCE == 0:
                while now_ms <= _SNOWFLAKE_LAST_MS:
                    time.sleep(0.001)
                    now_ms = int(time.time() * 1000) - WASM_AGENT_SNOWFLAKE_EPOCH_MS
        else:
            _SNOWFLAKE_SEQUENCE = 0
        _SNOWFLAKE_LAST_MS = now_ms
        return (now_ms << 22) | (machine << 12) | _SNOWFLAKE_SEQUENCE


def ensure_account_schema(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_tb (
          id INTEGER PRIMARY KEY,
          provider TEXT NOT NULL,
          provider_sub TEXT NOT NULL,
          email TEXT NOT NULL DEFAULT '',
          email_verified INTEGER NOT NULL DEFAULT 0,
          name TEXT NOT NULL DEFAULT '',
          picture_url TEXT NOT NULL DEFAULT '',
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          last_login_at INTEGER NOT NULL,
          UNIQUE(provider, provider_sub)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS friendship_tb (
          id TEXT PRIMARY KEY,
          requester_user_id TEXT NOT NULL,
          addressee_user_id TEXT NOT NULL,
          status TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          UNIQUE(requester_user_id, addressee_user_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_tb (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          space_id TEXT NOT NULL DEFAULT '',
          shared_space_id TEXT NOT NULL DEFAULT '',
          title TEXT NOT NULL DEFAULT '',
          created_by TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          client_owned INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_member_tb (
          conversation_id TEXT NOT NULL,
          user_id TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'member',
          joined_at INTEGER NOT NULL,
          last_read_event_id TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(conversation_id, user_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_event_tb (
          id TEXT PRIMARY KEY,
          client_event_id TEXT NOT NULL,
          conversation_id TEXT NOT NULL DEFAULT '',
          space_id TEXT NOT NULL DEFAULT '',
          shared_space_id TEXT NOT NULL DEFAULT '',
          author_user_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}',
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          UNIQUE(author_user_id, client_event_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_fleet_tb (
          user_id TEXT NOT NULL,
          node_id TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'owner',
          is_main INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          PRIMARY KEY(user_id, node_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS flux_credit_ledger_tb (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          actor_user_id TEXT NOT NULL DEFAULT '',
          amount INTEGER NOT NULL,
          kind TEXT NOT NULL,
          reason TEXT NOT NULL DEFAULT '',
          idempotency_key TEXT NOT NULL DEFAULT '',
          target TEXT NOT NULL DEFAULT '',
          created_at INTEGER NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_harness_tb (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          node_id TEXT NOT NULL DEFAULT '',
          node_name TEXT NOT NULL DEFAULT '',
          harness_name TEXT NOT NULL,
          harness_type TEXT NOT NULL DEFAULT 'hermes',
          infra_mode TEXT NOT NULL,
          lifecycle_state TEXT NOT NULL,
          bridge_url TEXT NOT NULL DEFAULT '',
          capabilities_json TEXT NOT NULL DEFAULT '{}',
          failure_reason TEXT NOT NULL DEFAULT '',
          quota_json TEXT NOT NULL DEFAULT '{}',
          cleanup_after_at INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS brain_profile_tb (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          label TEXT NOT NULL DEFAULT '',
          provider TEXT NOT NULL DEFAULT '',
          model TEXT NOT NULL DEFAULT '',
          node_id TEXT NOT NULL DEFAULT '',
          storage_scope TEXT NOT NULL DEFAULT 'browser',
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_manifest_tb (
          id TEXT PRIMARY KEY,
          instance_id TEXT NOT NULL,
          archive_path TEXT NOT NULL,
          manifest_json TEXT NOT NULL,
          created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS instance_audit_tb (
          id TEXT PRIMARY KEY,
          actor_user_id TEXT NOT NULL DEFAULT '',
          action TEXT NOT NULL,
          target TEXT NOT NULL DEFAULT '',
          created_at INTEGER NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS friendship_user_idx ON friendship_tb(requester_user_id, addressee_user_id, status)",
        "CREATE INDEX IF NOT EXISTS conversation_member_user_idx ON conversation_member_tb(user_id, conversation_id)",
        "CREATE INDEX IF NOT EXISTS sync_event_conversation_idx ON sync_event_tb(conversation_id, id)",
        "CREATE INDEX IF NOT EXISTS sync_event_space_idx ON sync_event_tb(shared_space_id, id)",
        "CREATE INDEX IF NOT EXISTS user_fleet_user_idx ON user_fleet_tb(user_id, is_main)",
        "CREATE INDEX IF NOT EXISTS flux_credit_user_idx ON flux_credit_ledger_tb(user_id, created_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS flux_credit_idempotency_idx ON flux_credit_ledger_tb(kind, idempotency_key) WHERE idempotency_key != ''",
        "CREATE INDEX IF NOT EXISTS agent_harness_user_idx ON agent_harness_tb(user_id, lifecycle_state, created_at)",
        "CREATE INDEX IF NOT EXISTS agent_harness_node_idx ON agent_harness_tb(node_id)",
    ):
        conn.execute(statement)


def auth_connect() -> sqlite3.Connection:
    path = auth_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    ensure_account_schema(conn)
    return conn


def public_user(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "provider": row["provider"],
        "email": row["email"],
        "email_verified": bool(row["email_verified"]),
        "role": "admin" if is_admin_email(str(row["email"])) else "user",
        "name": row["name"],
        "picture_url": row["picture_url"],
        "created_at": int(row["created_at"]),
        "last_login_at": int(row["last_login_at"]),
    }


def user_id(user: dict[str, Any] | None) -> str:
    value = str((user or {}).get("id") or "").strip()
    return value if value.isdigit() else "anonymous"


def user_is_admin(user: dict[str, Any] | None) -> bool:
    return str((user or {}).get("role") or "") == "admin" or is_admin_email(str((user or {}).get("email") or ""))


def row_is_admin(row: sqlite3.Row | dict[str, Any] | None) -> bool:
    if not row:
        return False
    role = row["role"] if isinstance(row, sqlite3.Row) else row.get("role")
    email = row["email"] if isinstance(row, sqlite3.Row) else row.get("email")
    return str(role or "") == "admin" or is_admin_email(str(email or ""))


def public_user_label(user: dict[str, Any] | None) -> str:
    if not user:
        return "Guest"
    return clipped(str(user.get("email") or user.get("name") or user_id(user) or "User"), 120)


def public_social_user(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
    user = public_user(row)
    if not user:
        return None
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "picture_url": user["picture_url"],
        "role": user["role"],
    }


def lookup_user_row(conn: sqlite3.Connection, query: str) -> sqlite3.Row | None:
    value = str(query or "").strip().lower()
    if not value:
        return None
    if value.isdigit():
        return conn.execute("SELECT * FROM user_tb WHERE id = ?", (int(value),)).fetchone()
    if "@" in value:
        return conn.execute("SELECT * FROM user_tb WHERE lower(email) = ?", (value,)).fetchone()
    return None


def account_user_lookup(query: str, user: dict[str, Any] | None) -> dict[str, Any]:
    if not user:
        raise BrowserError("auth_required", "Account sign-in is required.", status=HTTPStatus.UNAUTHORIZED)
    with auth_connect() as conn:
        found = public_social_user(lookup_user_row(conn, query))
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.account_user_lookup.v1",
        "query": clipped(str(query or ""), 160),
        "user": found,
    }


def friendship_public_payload(conn: sqlite3.Connection, row: sqlite3.Row, current_user_id: str) -> dict[str, Any]:
    requester = public_social_user(lookup_user_row(conn, str(row["requester_user_id"])))
    addressee = public_social_user(lookup_user_row(conn, str(row["addressee_user_id"])))
    other_id = str(row["addressee_user_id"] if str(row["requester_user_id"]) == current_user_id else row["requester_user_id"])
    other = public_social_user(lookup_user_row(conn, other_id))
    return {
        "schema": FRIENDSHIP_SCHEMA,
        "id": str(row["id"]),
        "requester_user_id": str(row["requester_user_id"]),
        "addressee_user_id": str(row["addressee_user_id"]),
        "status": str(row["status"]),
        "created_at": int(row["created_at"]),
        "updated_at": int(row["updated_at"]),
        "requester": requester,
        "addressee": addressee,
        "other_user": other,
        "direction": "outgoing" if str(row["requester_user_id"]) == current_user_id else "incoming",
    }


def list_friendships(user: dict[str, Any] | None) -> dict[str, Any]:
    uid = user_id(user)
    with auth_connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM friendship_tb
             WHERE (requester_user_id = ? OR addressee_user_id = ?)
               AND status IN ('pending', 'accepted')
             ORDER BY updated_at DESC
            """,
            (uid, uid),
        ).fetchall()
        friends = [friendship_public_payload(conn, row, uid) for row in rows]
    return {"ok": True, "schema": FRIENDSHIP_LIST_SCHEMA, "friendships": friends}


def existing_friendship(conn: sqlite3.Connection, user_a: str, user_b: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM friendship_tb
         WHERE (requester_user_id = ? AND addressee_user_id = ?)
            OR (requester_user_id = ? AND addressee_user_id = ?)
         ORDER BY updated_at DESC
         LIMIT 1
        """,
        (user_a, user_b, user_b, user_a),
    ).fetchone()


def request_friendship(user: dict[str, Any] | None, body: dict[str, Any]) -> dict[str, Any]:
    uid = user_id(user)
    target = str(body.get("target_user_id") or body.get("user_id") or body.get("email") or body.get("query") or "").strip()
    if not target:
        raise BrowserError("missing_friend_target", "Friend target id or email is required.")
    now = int(time.time())
    with auth_connect() as conn:
        target_row = lookup_user_row(conn, target)
        if not target_row:
            raise BrowserError("friend_target_not_found", "That user was not found.", status=HTTPStatus.NOT_FOUND)
        target_id = str(target_row["id"])
        if target_id == uid:
            raise BrowserError("friend_target_self", "You cannot send a friend request to yourself.")
        row = existing_friendship(conn, uid, target_id)
        if row:
            if str(row["status"]) in FRIENDSHIP_TERMINAL_STATUSES:
                conn.execute(
                    """
                    UPDATE friendship_tb
                       SET requester_user_id = ?, addressee_user_id = ?, status = 'pending', updated_at = ?
                     WHERE id = ?
                    """,
                    (uid, target_id, now, str(row["id"])),
                )
                row = conn.execute("SELECT * FROM friendship_tb WHERE id = ?", (str(row["id"]),)).fetchone()
            friendship = friendship_public_payload(conn, row, uid) if row else {}
        else:
            friendship_id = f"fr_{next_snowflake_id():x}"
            conn.execute(
                """
                INSERT INTO friendship_tb (
                  id, requester_user_id, addressee_user_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (friendship_id, uid, target_id, now, now),
            )
            row = conn.execute("SELECT * FROM friendship_tb WHERE id = ?", (friendship_id,)).fetchone()
            friendship = friendship_public_payload(conn, row, uid) if row else {}
    return {"ok": True, "friendship": friendship}


def respond_friendship(user: dict[str, Any] | None, body: dict[str, Any]) -> dict[str, Any]:
    uid = user_id(user)
    response = str(body.get("response") or body.get("status") or "").strip().lower()
    if response == "cancelled":
        response = "canceled"
    if response not in {"accepted", "declined", "blocked", "canceled", "removed"}:
        raise BrowserError("invalid_friend_response", "Friend response must be accepted, declined, blocked, canceled, or removed.")
    friendship_id = str(body.get("friendship_id") or body.get("id") or "").strip()
    requester_id = str(body.get("requester_user_id") or body.get("user_id") or "").strip()
    now = int(time.time())
    with auth_connect() as conn:
        row = None
        if friendship_id:
            row = conn.execute("SELECT * FROM friendship_tb WHERE id = ?", (friendship_id,)).fetchone()
        elif requester_id:
            row = existing_friendship(conn, uid, requester_id)
        if not row:
            return {"ok": True, "friendship": None, "status": response, "missing": True}
        if uid not in {str(row["requester_user_id"]), str(row["addressee_user_id"])}:
            raise BrowserError("friendship_response_denied", "You are not part of this friendship.", status=HTTPStatus.FORBIDDEN)
        current = str(row["status"])
        requester = str(row["requester_user_id"])
        addressee = str(row["addressee_user_id"])
        if str(row["addressee_user_id"]) != uid and response in {"accepted", "declined"} and current != response:
            raise BrowserError("friendship_response_denied", "Only the addressee can accept or decline this request.", status=HTTPStatus.FORBIDDEN)
        if requester != uid and response == "canceled" and current != response:
            raise BrowserError("friendship_response_denied", "Only the requester can cancel this friend request.", status=HTTPStatus.FORBIDDEN)
        if response in {"accepted", "declined"} and current not in {"pending", response}:
            friendship = friendship_public_payload(conn, row, uid)
            return {"ok": True, "friendship": friendship, "status": current, "unchanged": True}
        if response == "canceled" and current not in {"pending", "canceled"}:
            friendship = friendship_public_payload(conn, row, uid)
            return {"ok": True, "friendship": friendship, "status": current, "unchanged": True}
        if response == "removed" and current not in {"accepted", "removed"}:
            raise BrowserError("friendship_response_denied", "Only accepted friends can be removed.", status=HTTPStatus.FORBIDDEN)
        conn.execute("UPDATE friendship_tb SET status = ?, updated_at = ? WHERE id = ?", (response, now, str(row["id"])))
        updated = conn.execute("SELECT * FROM friendship_tb WHERE id = ?", (str(row["id"]),)).fetchone()
        friendship = friendship_public_payload(conn, updated, uid) if updated else {}
    return {"ok": True, "friendship": friendship}


def safe_state_id(raw: str, fallback: str = "space") -> str:
    base = "".join(ch.lower() if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(raw or "").strip())[:72].strip("-_")
    return base or fallback


def canonical_space_storage_id(raw: str, fallback: str = "home") -> str:
    sid = safe_state_id(raw, fallback)
    return BUILT_IN_SPACE_ID_ALIASES.get(sid, sid)


def is_reserved_user_space_id(raw: str) -> bool:
    sid = safe_state_id(raw, "")
    return sid in RESERVED_USER_SPACE_IDS


def user_root(server: WasmAgentServer, user: dict[str, Any] | None) -> Path:
    path = server.state_dir / "users" / user_id(user)
    path.mkdir(parents=True, exist_ok=True)
    return path


def directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def ensure_user_quota(server: WasmAgentServer, user: dict[str, Any] | None, incoming_bytes: int = 0) -> None:
    if user_is_admin(user):
        return
    used = directory_size(user_root(server, user))
    projected = used + max(0, int(incoming_bytes or 0))
    if projected > DEFAULT_USER_QUOTA_BYTES:
        raise BrowserError(
            "user_storage_quota_exceeded",
            "This account reached the 1 GB wasm-agent storage limit.",
            status=HTTPStatus.INSUFFICIENT_STORAGE,
        )


def user_storage(server: WasmAgentServer, user: dict[str, Any] | None) -> dict[str, Any]:
    root = user_root(server, user)
    used = directory_size(root)
    limit = None if user_is_admin(user) else DEFAULT_USER_QUOTA_BYTES
    disk = shutil.disk_usage(root)
    return {
        "schema": "hermes.wasm_agent.user_storage.v1",
        "used_bytes": used,
        "limit_bytes": limit,
        "available_bytes": disk.free,
        "local_total_bytes": disk.total,
        "unlimited": limit is None,
        "percent": 0 if limit in {None, 0} else min(100, round((used / limit) * 100, 2)),
    }


def user_spaces_dir(server: WasmAgentServer, user: dict[str, Any] | None) -> Path:
    path = user_root(server, user) / "spaces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_space_dir(server: WasmAgentServer, user: dict[str, Any] | None, space_id: str) -> Path:
    sid = canonical_space_storage_id(space_id, "home")
    path = user_spaces_dir(server, user) / sid
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_timeline_dir(server: WasmAgentServer, user: dict[str, Any] | None, space_id: str = "home") -> Path:
    path = user_root(server, user) / "timelines" / canonical_space_storage_id(space_id, "home")
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_wis_dir(server: WasmAgentServer, user: dict[str, Any] | None, space_id: str = "home") -> Path:
    path = user_space_dir(server, user, space_id) / "wis"
    path.mkdir(parents=True, exist_ok=True)
    return path


def shared_spaces_dir(server: WasmAgentServer) -> Path:
    path = server.state_dir / "shared-spaces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def shared_space_dir(server: WasmAgentServer, shared_space_id: str) -> Path:
    sid = safe_state_id(shared_space_id, "")
    if not sid:
        raise BrowserError("invalid_shared_space", "shared_space_id is required.")
    path = shared_spaces_dir(server) / sid
    path.mkdir(parents=True, exist_ok=True)
    return path


def repo_relative_string(server: WasmAgentServer, path: Path) -> str:
    root = repo_root(server).resolve()
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def user_sandbox_prefix(server: WasmAgentServer, user: dict[str, Any] | None) -> str:
    prefix = repo_relative_string(server, user_root(server, user))
    return prefix.rstrip("/")


def path_has_prefix(path: str, prefixes: tuple[str, ...] | list[str]) -> bool:
    value = str(path or "").strip().lstrip("/")
    return any(value == prefix.rstrip("/") or value.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def node_has_global_authority(target_node: str, user: dict[str, Any] | None) -> bool:
    node = str(target_node or "").strip().lower()
    return user_is_admin(user) and node in GLOBAL_AGENT_NODE_IDS


def default_agent_target_node(user: dict[str, Any] | None) -> str:
    return "orchestrator" if user_is_admin(user) else AGENT_DEFAULT_SANDBOX_NODE_ID


def ensure_agent_target_allowed(user: dict[str, Any] | None, target_node: str) -> None:
    if user_is_admin(user):
        return
    node = str(target_node or "").strip().lower()
    if node in GLOBAL_AGENT_NODE_IDS:
        raise BrowserError(
            "agent_target_denied",
            "Only an admin can route embedded chat turns to the global orchestrator. Select an account-owned sandbox node.",
            status=HTTPStatus.FORBIDDEN,
        )
    allowed = {AGENT_DEFAULT_SANDBOX_NODE_ID, *account_main_node_id_candidates(user)}
    if node not in allowed:
        raise BrowserError(
            "agent_target_denied",
            "Standard-user embedded chat can only route to the account main sandbox.",
            status=HTTPStatus.FORBIDDEN,
        )


def agent_mutation_policy(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    target_node: str,
) -> dict[str, Any]:
    sandbox_prefix = user_sandbox_prefix(server, user)
    global_authority = node_has_global_authority(target_node, user)
    if global_authority:
        return {
            "schema": "hermes.wasm_agent.mutation_policy.v1",
            "target_node": target_node,
            "scope": "global-orchestrator",
            "user_id": user_id(user),
            "admin": True,
            "can_modify_core_firmware": True,
            "can_patch_wis_artifacts": True,
            "allowed_write_roots": [str(repo_root(server).resolve())],
            "protected_prefixes": [],
            "userland_patch_schemas": [WIS_PATCH_SCHEMA],
            "rule": "The orchestrator may modify wasm-agent source, core modules, firmware, docs, and user-space state.",
        }
    return {
        "schema": "hermes.wasm_agent.mutation_policy.v1",
        "target_node": target_node,
        "scope": "user-sandbox",
        "user_id": user_id(user),
        "admin": user_is_admin(user),
        "can_modify_core_firmware": False,
        "can_patch_wis_artifacts": True,
        "allowed_write_roots": [str(user_root(server, user).resolve())],
        "allowed_repo_prefixes": [sandbox_prefix],
        "protected_prefixes": list(CORE_FIRMWARE_PREFIXES),
        "userland_patch_schemas": [WIS_PATCH_SCHEMA],
        "rule": "Sandboxed nodes may only mutate the mounted account-owned wasm-user sandbox; core wasm-agent firmware/source changes must be delegated to the orchestrator.",
    }


def mutation_block_spec() -> dict[str, Any]:
    return {
        "schema": "hermes.wasm_agent.mutation_spec.v1",
        "format": "Return a fenced json code block with schema hermes.wasm_agent.mutation.v1.",
        "example": {
            "schema": "hermes.wasm_agent.mutation.v1",
            "operations": [
                {
                    "op": "replace",
                    "path": "plugins/wasm-agent/public/styles.css",
                    "find": "width: clamp(120px, 50%, 218px);",
                    "replace": "width: clamp(120px, calc(50% + 8px), 218px);",
                },
                {
                    "op": "append",
                    "path": "plugins/wasm-agent/README.md",
                    "after": "## Runtime Contract\n",
                    "insert": "\nSmall runtime note.\n",
                }
            ],
        },
        "ops": ["replace", "append"],
        "required_fields": {
            "replace": ["path", "find", "replace"],
            "append": ["path", "insert"],
            "append_optional": ["after"],
        },
        "limits": {
            "max_operations": AGENT_MUTATION_MAX_OPS,
            "exact_replace_only": True,
            "max_total_replace_bytes": AGENT_MUTATION_MAX_TOTAL_REPLACE_BYTES,
        },
    }


def wis_patch_block_spec() -> dict[str, Any]:
    return {
        "schema": "hermes.wasm_agent.wis.patch_spec.v1",
        "format": (
            f"Return a fenced json block with schema {WIS_PATCH_SCHEMA} for userland WIS/interface artifacts. "
            "Omit space_id to target the current wasm-agent space; include it only for a known explicit space id."
        ),
        "example": {
            "schema": WIS_PATCH_SCHEMA,
            "artifact_id": "main",
            "operations": [
                {"op": "set_title", "title": "Deploy Checklist"},
                {
                    "op": "append_child",
                    "parent_id": "doc",
                    "node": {
                        "id": "deploy-title",
                        "type": "heading",
                        "level": 1,
                        "text": "Deploy Checklist",
                    },
                },
            ],
        },
        "ops": [
            "set_title",
            "set_state",
            "set_node_text",
            "set_node_props",
            "set_node_action",
            "append_child",
            "add_node",
            "remove_node",
            "replace_node",
            "add_document",
        ],
        "space_id": "optional; omitted means the active wasm-agent space injected by the adapter",
        "limits": {
            "max_operations": 40,
            "max_artifact_bytes": 512 * 1024,
            "core_firmware": "denied outside admin orchestrator source mutation policy",
        },
    }


def extract_agent_mutation_payloads(reply: str) -> tuple[str, list[dict[str, Any]]]:
    text = str(reply or "")
    payloads: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []
    fence_re = re.compile(r"```(?:json|wasm-agent-mutation|mutation)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
    for match in fence_re.finditer(text):
        block = match.group(1).strip()
        if "hermes.wasm_agent.mutation.v1" not in block:
            continue
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("schema") == "hermes.wasm_agent.mutation.v1":
            payloads.append(payload)
            spans.append(match.span())
    tag_re = re.compile(r"<wasm-agent-mutation>\s*(.*?)\s*</wasm-agent-mutation>", re.DOTALL | re.IGNORECASE)
    for match in tag_re.finditer(text):
        block = match.group(1).strip()
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("schema") == "hermes.wasm_agent.mutation.v1":
            payloads.append(payload)
            spans.append(match.span())
    if not spans:
        return text, payloads
    cleaned = text
    for start, end in sorted(spans, reverse=True):
        cleaned = cleaned[:start].rstrip() + "\n\n" + cleaned[end:].lstrip()
    return cleaned.strip(), payloads


def extract_agent_wis_patch_payloads(reply: str) -> tuple[str, list[dict[str, Any]]]:
    text = str(reply or "")
    payloads: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []

    def spans_overlap(candidate: tuple[int, int]) -> bool:
        start, end = candidate
        return any(start < span_end and end > span_start for span_start, span_end in spans)

    def json_object_end(start: int) -> int | None:
        if start < 0 or start >= len(text) or text[start] != "{":
            return None
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index + 1
        return None

    def expand_raw_json_span(start: int, end: int) -> tuple[int, int]:
        line_start = text.rfind("\n", 0, start) + 1
        previous_line_end = line_start - 1
        if previous_line_end < 0:
            return start, end
        previous_line_start = text.rfind("\n", 0, previous_line_end) + 1
        previous_line = text[previous_line_start:previous_line_end].strip().lower()
        between = text[previous_line_end: start].strip()
        if previous_line in {"json", "wis-patch", "patch"} and not between:
            return previous_line_start, end
        return start, end

    def append_payload(payload: dict[str, Any], span: tuple[int, int]) -> None:
        if spans_overlap(span):
            return
        payloads.append(payload)
        spans.append(span)

    fence_re = re.compile(r"```(?:json|wis-patch|patch)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
    for match in fence_re.finditer(text):
        block = match.group(1).strip()
        if WIS_PATCH_SCHEMA not in block:
            continue
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("schema") == WIS_PATCH_SCHEMA:
            append_payload(payload, match.span())
    tag_re = re.compile(r"<wis-patch>\s*(.*?)\s*</wis-patch>", re.DOTALL | re.IGNORECASE)
    for match in tag_re.finditer(text):
        block = match.group(1).strip()
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("schema") == WIS_PATCH_SCHEMA:
            append_payload(payload, match.span())

    schema_index = text.find(WIS_PATCH_SCHEMA)
    while schema_index != -1:
        if not spans_overlap((schema_index, schema_index + len(WIS_PATCH_SCHEMA))):
            start = text.rfind("{", 0, schema_index)
            while start != -1:
                end = json_object_end(start)
                if end is not None and end >= schema_index:
                    try:
                        payload = json.loads(text[start:end])
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, dict) and payload.get("schema") == WIS_PATCH_SCHEMA:
                        append_payload(payload, expand_raw_json_span(start, end))
                        break
                start = text.rfind("{", 0, start)
        schema_index = text.find(WIS_PATCH_SCHEMA, schema_index + len(WIS_PATCH_SCHEMA))

    if not spans:
        return text, payloads
    cleaned = text
    for start, end in sorted(spans, reverse=True):
        cleaned = cleaned[:start].rstrip() + "\n\n" + cleaned[end:].lstrip()
    return cleaned.strip(), payloads


def normalize_wis_patch_space_id(raw: Any, fallback: str) -> str:
    active_space_id = canonical_space_storage_id(str(fallback or ""), "home")
    candidate = safe_state_id(str(raw or ""), "")
    if not candidate or candidate in WIS_CURRENT_SPACE_SENTINELS:
        return active_space_id
    return canonical_space_storage_id(candidate, active_space_id)


def apply_agent_wis_patches_from_reply(
    server: WasmAgentServer,
    reply: str,
    *,
    user: dict[str, Any] | None,
    space_id: str,
    shared_space_id: str = "",
) -> tuple[str, dict[str, Any] | None]:
    cleaned_reply, payloads = extract_agent_wis_patch_payloads(reply)
    if not payloads:
        return reply, None
    result: dict[str, Any] = {
        "schema": WIS_PATCH_RESULT_SCHEMA,
        "applied": False,
        "patches": [],
        "operations": 0,
        "errors": [],
    }
    for payload in payloads:
        patch = json_clone(payload)
        patch["space_id"] = normalize_wis_patch_space_id(patch.get("space_id"), space_id)
        if shared_space_id and not patch.get("shared_space_id"):
            patch["shared_space_id"] = shared_space_id
        try:
            patch_result = patch_wis_artifact(server, user, patch)
            result["patches"].append(patch_result)
            result["operations"] += int(patch_result.get("operations") or 0)
            result["applied"] = bool(result["applied"] or patch_result.get("applied"))
        except BrowserError as exc:
            result["errors"].append(exc.message)
        except Exception as exc:
            result["errors"].append(str(exc))
    summary = append_agent_wis_patch_summary(cleaned_reply, result)
    return summary, result


def mutation_path_allowed(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    policy: dict[str, Any],
    raw_path: str,
) -> Path:
    root = repo_root(server).resolve()
    path = Path(str(raw_path or "")).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if ".git" in resolved.parts:
        raise BrowserError("agent_mutation_path_denied", "Mutation paths may not target .git.")
    allowed_roots = [
        Path(str(item)).resolve()
        for item in policy.get("allowed_write_roots", [])
        if str(item or "").strip()
    ]
    if not allowed_roots:
        raise BrowserError("agent_mutation_path_denied", "No mutation write roots are available.")
    if not any(resolved == allowed or allowed in resolved.parents for allowed in allowed_roots):
        raise BrowserError("agent_mutation_path_denied", "Mutation path is outside the allowed write roots.")
    relative = repo_relative_string(server, resolved)
    if policy.get("scope") == "global-orchestrator" and not path_has_prefix(relative, CORE_FIRMWARE_PREFIXES):
        raise BrowserError("agent_mutation_path_denied", "Global chat mutations are limited to wasm-agent firmware and docs.")
    allowed_prefixes = policy.get("allowed_repo_prefixes") if isinstance(policy.get("allowed_repo_prefixes"), list) else []
    if allowed_prefixes and not path_has_prefix(relative, allowed_prefixes):
        raise BrowserError("agent_mutation_path_denied", "Mutation path is outside the allowed repo prefixes.")
    protected = policy.get("protected_prefixes") if isinstance(policy.get("protected_prefixes"), list) else []
    if protected and path_has_prefix(relative, protected):
        raise BrowserError("agent_mutation_path_denied", "Mutation path targets protected core firmware.")
    if resolved.suffix.lower() not in AGENT_MUTATION_ALLOWED_EXTENSIONS:
        raise BrowserError("agent_mutation_path_denied", "Mutation path must be a recognized text source file.")
    return resolved


def apply_agent_mutations_from_reply(
    server: WasmAgentServer,
    reply: str,
    *,
    user: dict[str, Any] | None,
    mutation_policy: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    cleaned_reply, payloads = extract_agent_mutation_payloads(reply)
    if not payloads:
        return reply, None
    result: dict[str, Any] = {
        "schema": "hermes.wasm_agent.mutation_result.v1",
        "applied": False,
        "files": [],
        "operations": 0,
        "errors": [],
    }
    operations: list[dict[str, Any]] = []
    for payload in payloads:
        items = payload.get("operations")
        if isinstance(items, list):
            operations.extend([item for item in items if isinstance(item, dict)])
    if not operations:
        result["errors"].append("No valid mutation operations were provided.")
        return append_agent_mutation_summary(cleaned_reply, result), result
    if len(operations) > AGENT_MUTATION_MAX_OPS:
        result["errors"].append(f"Too many mutation operations: {len(operations)} > {AGENT_MUTATION_MAX_OPS}.")
        return append_agent_mutation_summary(cleaned_reply, result), result

    pending: dict[Path, str] = {}
    changed_files: set[str] = set()
    total_replace_bytes = 0
    try:
        for operation in operations:
            op = str(operation.get("op") or operation.get("operation") or "replace").strip().lower()
            path = mutation_path_allowed(server, user, mutation_policy, str(operation.get("path") or ""))
            if path.exists() and path.stat().st_size > AGENT_MUTATION_MAX_FILE_BYTES:
                raise BrowserError("agent_mutation_file_too_large", "Mutation target file is too large.")
            if not path.exists() and op != "append":
                raise BrowserError("agent_mutation_file_missing", "Mutation target file does not exist.")
            current = pending.get(path)
            if current is None:
                current = path.read_text(encoding="utf-8") if path.exists() else ""
            if op == "replace":
                find = str(operation.get("find") or "")
                replace = str(operation.get("replace") or "")
                if not find:
                    raise BrowserError("agent_mutation_invalid_replace", "Replace operations require a non-empty find string.")
                count = current.count(find)
                if count != 1:
                    raise BrowserError(
                        "agent_mutation_non_unique_match",
                        f"Replace match count for {repo_relative_string(server, path)} was {count}, expected 1.",
                    )
                total_replace_bytes += len(find.encode("utf-8")) + len(replace.encode("utf-8"))
                if total_replace_bytes > AGENT_MUTATION_MAX_TOTAL_REPLACE_BYTES:
                    raise BrowserError("agent_mutation_too_large", "Mutation replacement payload is too large.")
                pending[path] = current.replace(find, replace, 1)
            elif op == "append":
                insert = str(
                    operation.get("insert")
                    or operation.get("text")
                    or operation.get("content")
                    or operation.get("value")
                    or operation.get("body")
                    or ""
                )
                after = str(operation.get("after") or "")
                if not insert:
                    raise BrowserError("agent_mutation_invalid_append", "Append operations require a non-empty insert field.")
                total_replace_bytes += len(insert.encode("utf-8"))
                if total_replace_bytes > AGENT_MUTATION_MAX_TOTAL_REPLACE_BYTES:
                    raise BrowserError("agent_mutation_too_large", "Mutation append payload is too large.")
                if after:
                    count = current.count(after)
                    if count != 1:
                        raise BrowserError(
                            "agent_mutation_non_unique_match",
                            f"Append anchor count for {repo_relative_string(server, path)} was {count}, expected 1.",
                        )
                    pending[path] = current.replace(after, after + insert, 1)
                else:
                    pending[path] = current + insert
            else:
                raise BrowserError("agent_mutation_invalid_op", f"Unsupported mutation op: {op}.")
            changed_files.add(repo_relative_string(server, path))
    except BrowserError as exc:
        result["errors"].append(exc.message)
        return append_agent_mutation_summary(cleaned_reply, result), result
    except Exception as exc:
        result["errors"].append(str(exc))
        return append_agent_mutation_summary(cleaned_reply, result), result

    for path, content in pending.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    result.update({
        "applied": bool(pending),
        "files": sorted(changed_files),
        "operations": len(operations),
    })
    return append_agent_mutation_summary(cleaned_reply, result), result


def append_agent_mutation_summary(reply: str, result: dict[str, Any]) -> str:
    base = str(reply or "").strip()
    if result.get("applied"):
        files = ", ".join(f"`{item}`" for item in result.get("files", [])[:6])
        summary = f"Applied source mutation to {files}."
    else:
        errors = result.get("errors") if isinstance(result.get("errors"), list) else []
        summary = f"Mutation was not applied: {errors[0] if errors else 'no valid mutation was provided'}"
    return f"{base}\n\n{summary}".strip()


def append_agent_wis_patch_summary(reply: str, result: dict[str, Any]) -> str:
    base = str(reply or "").strip()
    if result.get("applied"):
        patches = result.get("patches") if isinstance(result.get("patches"), list) else []
        targets = ", ".join(
            f"`{item.get('artifact_id', 'main')}`"
            for item in patches[:6]
            if isinstance(item, dict)
        )
        summary = f"Applied WIS/userland patch to {targets or 'artifact'}."
    else:
        errors = result.get("errors") if isinstance(result.get("errors"), list) else []
        summary = f"WIS/userland patch was not applied: {errors[0] if errors else 'no valid patch was provided'}"
    return f"{base}\n\n{summary}".strip()


def user_attachment_dir(server: WasmAgentServer, user: dict[str, Any] | None) -> Path:
    path = user_root(server, user) / "attachments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_observation_path(server: WasmAgentServer, user: dict[str, Any] | None) -> Path:
    path = user_root(server, user) / "observation" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def user_client_snapshot_dir(server: WasmAgentServer, user: dict[str, Any] | None) -> Path:
    path = user_root(server, user) / "client-snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_client_snapshot_latest_path(server: WasmAgentServer, user: dict[str, Any] | None) -> Path:
    return user_client_snapshot_dir(server, user) / "latest.json"


def user_client_snapshot_request_dir(server: WasmAgentServer, user: dict[str, Any] | None) -> Path:
    path = user_client_snapshot_dir(server, user) / "requests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_client_snapshot_response_dir(server: WasmAgentServer, user: dict[str, Any] | None) -> Path:
    path = user_client_snapshot_dir(server, user) / "responses"
    path.mkdir(parents=True, exist_ok=True)
    return path


def client_snapshot_request_path(server: WasmAgentServer, user: dict[str, Any] | None, request_id: str) -> Path:
    return user_client_snapshot_request_dir(server, user) / f"request_{safe_state_id(request_id, 'request')}.json"


def user_devices_dir(server: WasmAgentServer, user: dict[str, Any] | None) -> Path:
    path = user_root(server, user) / "devices"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_device_sync_dir(server: WasmAgentServer, user: dict[str, Any] | None) -> Path:
    path = user_root(server, user) / "device-sync"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_native_companion_dir(server: WasmAgentServer, user: dict[str, Any] | None) -> Path:
    path = user_root(server, user) / "native-companion"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_device_settings_path(server: WasmAgentServer, user: dict[str, Any] | None) -> Path:
    path = user_root(server, user) / "device-settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_json_file(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8")
    tmp.replace(path)


def parse_cookies(raw: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in str(raw or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        cookies[key.strip()] = value.strip()
    return cookies


def signed_auth_value(user_id: str, issued_at: int | None = None) -> str:
    issued = int(issued_at or time.time())
    message = f"{user_id}.{issued}"
    signature = hmac.new(auth_secret(), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{message}.{signature}"


def verified_auth_user_id(value: str) -> str:
    parts = str(value or "").split(".")
    if len(parts) != 3:
        return ""
    user_id, issued_raw, signature = parts
    if not user_id.isdigit() or not issued_raw.isdigit() or not signature:
        return ""
    issued = int(issued_raw)
    if issued > int(time.time()) + 60 or int(time.time()) - issued > AUTH_COOKIE_MAX_AGE_SEC:
        return ""
    expected = hmac.new(auth_secret(), f"{user_id}.{issued}".encode("utf-8"), hashlib.sha256).hexdigest()
    return user_id if hmac.compare_digest(signature, expected) else ""


def auth_cookie(user_id: str, *, max_age: int = AUTH_COOKIE_MAX_AGE_SEC) -> str:
    value = signed_auth_value(str(user_id)) if user_id else ""
    secure = " Secure;" if public_origin().lower().startswith("https://") or os.getenv("HERMES_WASM_AGENT_SECURE_COOKIES", "").lower() in {"1", "true", "yes", "on"} else ""
    return f"wa_uid={value}; Path=/; Max-Age={max_age}; SameSite=Lax;{secure} HttpOnly"


def auth_session(server: WasmAgentServer, cookie_header: str) -> dict[str, Any]:
    user_id = verified_auth_user_id(parse_cookies(cookie_header).get("wa_uid", ""))
    if not user_id:
        return {"ok": True, "authenticated": False, "user": None}
    path = auth_db_path()
    if not path.exists():
        return {"ok": True, "authenticated": False, "user": None}
    with auth_connect() as conn:
        row = conn.execute("SELECT * FROM user_tb WHERE id = ?", (int(user_id),)).fetchone()
    user = public_user(row)
    if user and not is_allowed_account_email(str(user.get("email") or "")):
        user = None
    return {"ok": True, "authenticated": bool(user), "user": user}


def authenticated_request_user(handler: WasmAgentHandler) -> dict[str, Any] | None:
    try:
        payload = auth_session(handler.server, handler.headers.get("Cookie", ""))
    except Exception:
        return None
    user = payload.get("user")
    return user if isinstance(user, dict) else None


def request_ip(handler: WasmAgentHandler) -> str:
    forwarded = str(handler.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded
    try:
        return str(handler.client_address[0])
    except Exception:
        return ""


def request_client_device_id(handler: WasmAgentHandler) -> str:
    return safe_state_id(str(handler.headers.get("X-Wasm-Agent-Device-Id") or ""), "")


def browser_label(user_agent: str) -> str:
    ua = user_agent.lower()
    browser = "Browser"
    if "edg/" in ua:
        browser = "Edge"
    elif "chrome/" in ua or "crios/" in ua:
        browser = "Chrome"
    elif "firefox/" in ua or "fxios/" in ua:
        browser = "Firefox"
    elif "safari/" in ua:
        browser = "Safari"
    platform = "Device"
    if "android" in ua:
        platform = "Android"
    elif "iphone" in ua or "ipad" in ua:
        platform = "iOS"
    elif "mac os x" in ua or "macintosh" in ua:
        platform = "macOS"
    elif "windows" in ua:
        platform = "Windows"
    elif "linux" in ua:
        platform = "Linux"
    return f"{browser} on {platform}"


def display_time(epoch: int) -> str:
    if not epoch:
        return ""
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(epoch))


def account_device_id(user: dict[str, Any] | None, user_agent: str, ip: str, client_device_id: str = "") -> str:
    client_id = safe_state_id(client_device_id, "")
    fingerprint = f"client:{client_id}" if client_id else f"ua-ip:{user_agent}\n{ip}"
    raw = f"{user_id(user)}\n{fingerprint}".encode("utf-8", "replace")
    return hashlib.sha256(raw).hexdigest()[:18]


def request_account_device_id(user: dict[str, Any] | None, handler: WasmAgentHandler) -> str:
    return account_device_id(
        user,
        clipped(str(handler.headers.get("User-Agent") or "Browser"), 360),
        clipped(request_ip(handler), 80),
        request_client_device_id(handler),
    )


def read_device_settings(server: WasmAgentServer, user: dict[str, Any] | None) -> dict[str, Any]:
    payload = read_json_file(user_device_settings_path(server, user), {})
    return payload if isinstance(payload, dict) else {}


def write_device_settings(server: WasmAgentServer, user: dict[str, Any] | None, payload: dict[str, Any]) -> None:
    write_json_file(user_device_settings_path(server, user), {
        "schema": "hermes.wasm_agent.device_settings.v1",
        **payload,
    })


def device_is_online(device: dict[str, Any], now: int) -> bool:
    if bool(device.get("current")):
        return True
    last_seen = int(device.get("last_seen") or 0)
    return last_seen > 0 and now - last_seen <= DEVICE_ONLINE_WINDOW_SEC


def list_account_devices(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    handler: WasmAgentHandler,
) -> dict[str, Any]:
    if not user:
        raise BrowserError("auth_required", "Account sign-in is required.", status=HTTPStatus.UNAUTHORIZED)
    now = int(time.time())
    user_agent = clipped(str(handler.headers.get("User-Agent") or "Browser"), 360)
    ip = clipped(request_ip(handler), 80)
    client_device_id = request_client_device_id(handler)
    current_id = account_device_id(user, user_agent, ip, client_device_id)
    current = {
        "schema": "hermes.wasm_agent.account_device.v1",
        "id": current_id,
        "client_device_id": client_device_id,
        "label": browser_label(user_agent),
        "user_agent": user_agent,
        "ip": ip,
        "first_seen": now,
        "last_seen": now,
    }
    root = user_devices_dir(server, user)
    existing = read_json_file(root / f"{current_id}.json", {})
    if isinstance(existing, dict):
        current["first_seen"] = int(existing.get("first_seen") or now)
    write_json_file(root / f"{current_id}.json", current)
    sync_root = user_device_sync_dir(server, user)
    sync_by_device: dict[str, dict[str, Any]] = {}
    for sync_path in sorted(sync_root.glob("*.json")):
        sync_payload = read_json_file(sync_path, {})
        if not isinstance(sync_payload, dict):
            continue
        target_id = str(sync_payload.get("target_device_id") or "")
        if target_id:
            sync_by_device[target_id] = sync_payload
    settings = read_device_settings(server, user)
    main_device_id = safe_state_id(str(settings.get("main_device_id") or ""), "")
    if not main_device_id or not (root / f"{main_device_id}.json").exists():
        main_device_id = current_id
        write_device_settings(server, user, {
            "main_device_id": main_device_id,
            "updated_at": now,
            "updated_by_device_id": current_id,
        })
    devices = []
    for path in sorted(root.glob("*.json")):
        payload = read_json_file(path, {})
        if not isinstance(payload, dict):
            continue
        device_id = str(payload.get("id") or path.stem)
        last_seen = int(payload.get("last_seen") or 0)
        item = {
            "id": device_id,
            "client_device_id": clipped(str(payload.get("client_device_id") or ""), 96),
            "label": clipped(str(payload.get("label") or "Device"), 80),
            "user_agent": clipped(str(payload.get("user_agent") or ""), 360),
            "ip": clipped(str(payload.get("ip") or ""), 80),
            "first_seen": int(payload.get("first_seen") or last_seen or 0),
            "last_seen": last_seen,
            "last_seen_display": display_time(last_seen),
            "sync_status": clipped(str(sync_by_device.get(device_id, {}).get("status") or "not_synced"), 40),
            "main": device_id == main_device_id,
            "current": device_id == current_id,
        }
        item["online"] = device_is_online(item, now)
        item["reachability"] = "online" if item["online"] else "offline"
        devices.append(item)
    devices.sort(key=lambda item: (not item["current"], -int(item.get("last_seen") or 0)))
    main_device = next((item for item in devices if item["id"] == main_device_id), None)
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.account_devices.v1",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "current_device_id": current_id,
        "main_device_id": main_device_id,
        "main_device_online": bool(main_device and main_device.get("online")),
        "devices": devices[:20],
    }


def set_main_account_device(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    body: dict[str, Any],
    handler: WasmAgentHandler,
) -> dict[str, Any]:
    if not user:
        raise BrowserError("auth_required", "Account sign-in is required.", status=HTTPStatus.UNAUTHORIZED)
    device_id = safe_state_id(str(body.get("device_id") or ""), "")
    if not device_id:
        raise BrowserError("invalid_device", "device_id is required.")
    if not (user_devices_dir(server, user) / f"{device_id}.json").exists():
        raise BrowserError("device_not_found", "That account device was not found.", status=HTTPStatus.NOT_FOUND)
    now = int(time.time())
    current_device_id = request_account_device_id(user, handler)
    write_device_settings(server, user, {
        "main_device_id": device_id,
        "updated_at": now,
        "updated_by_device_id": current_device_id,
    })
    return list_account_devices(server, user, handler)


def create_device_sync_package(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    body: dict[str, Any],
    handler: WasmAgentHandler,
) -> dict[str, Any]:
    if not user:
        raise BrowserError("auth_required", "Account sign-in is required.", status=HTTPStatus.UNAUTHORIZED)
    device_id = safe_state_id(str(body.get("device_id") or ""), "")
    if not device_id:
        raise BrowserError("invalid_device", "device_id is required.")
    device = read_json_file(user_devices_dir(server, user) / f"{device_id}.json", {})
    if not isinstance(device, dict) or str(device.get("id") or device_id) != device_id:
        raise BrowserError("device_not_found", "That account device was not found.", status=HTTPStatus.NOT_FOUND)
    now = int(time.time())
    current_device_id = request_account_device_id(user, handler)
    token_id = uuid.uuid4().hex
    package = {
        "schema": "hermes.wasm_agent.device_sync_package.v1",
        "artifact_kind": "device-sync-installer",
        "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "token_id": token_id,
        "account_id": str(user.get("id") or ""),
        "target_device_id": device_id,
        "target_label": clipped(str(device.get("label") or "Device"), 80),
        "main_device_id": current_device_id,
        "mode": "local-first-tunnel-bootstrap",
        "capabilities": [
            "register-device",
            "report-online",
            "prepare-tunnel",
            "sync-device-state",
        ],
        "layout_policy": "client-local",
        "artifact_policy": "shareable-wasm-artifacts",
        "tunnel": {
            "status": "planned",
            "transport": "pending",
        },
    }
    write_json_file(user_device_sync_dir(server, user) / f"{token_id}.json", {
        "schema": "hermes.wasm_agent.device_sync_request.v1",
        "token_id": token_id,
        "target_device_id": device_id,
        "main_device_id": current_device_id,
        "status": "installer_downloaded",
        "created_at": now,
    })
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.device_sync_response.v1",
        "package": package,
    }


def native_install_channel(os_name: str) -> str:
    normalized = str(os_name or "").strip().lower()
    if normalized == "android":
        return "android-foreground-service"
    if normalized in {"ios", "iphoneos", "ipados"}:
        return "ios-companion"
    if normalized == "macos":
        return "macos-menu-bar-companion"
    if normalized == "windows":
        return "windows-tray-companion"
    if normalized == "linux":
        return "linux-daemon-companion"
    return "native-companion"


def sanitize_native_device_profile(raw: Any, user_agent: str) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    os_name = clipped(str(source.get("os") or ""), 40)
    if not os_name:
        os_name = browser_label(user_agent).split(" on ", 1)[-1] or "Device"
    device_type = str(source.get("device_type") or source.get("deviceType") or "").strip().lower()
    if device_type not in {"phone", "tablet", "desktop", "device"}:
        device_type = "device"
    browser = clipped(str(source.get("browser") or browser_label(user_agent).split(" on ", 1)[0] or "Browser"), 40)
    install_channel = clipped(str(source.get("install_channel") or source.get("installChannel") or native_install_channel(os_name)), 80)
    capabilities = source.get("pwa_capabilities") if isinstance(source.get("pwa_capabilities"), dict) else {}
    user_agent_data = source.get("user_agent_data") if isinstance(source.get("user_agent_data"), dict) else {}
    try:
        max_touch_points = int(float(source.get("max_touch_points") or source.get("maxTouchPoints") or 0))
    except (TypeError, ValueError):
        max_touch_points = 0
    return {
        "schema": NATIVE_DEVICE_PROFILE_SCHEMA,
        "os": os_name,
        "browser": browser,
        "device_type": device_type,
        "install_channel": install_channel,
        "display_mode": clipped(str(source.get("display_mode") or source.get("displayMode") or "browser"), 40),
        "platform": clipped(str(source.get("platform") or ""), 80),
        "max_touch_points": max(0, min(32, max_touch_points)),
        "user_agent": clipped(str(source.get("user_agent") or user_agent), 360),
        "user_agent_data": {
            "architecture": clipped(str(user_agent_data.get("architecture") or ""), 40),
            "bitness": clipped(str(user_agent_data.get("bitness") or ""), 20),
            "model": clipped(str(user_agent_data.get("model") or ""), 80),
            "platform": clipped(str(user_agent_data.get("platform") or ""), 80),
            "platform_version": clipped(str(user_agent_data.get("platform_version") or user_agent_data.get("platformVersion") or ""), 80),
            "mobile": bool(user_agent_data.get("mobile")),
        },
        "pwa_capabilities": {
            "microphone": bool(capabilities.get("microphone")),
            "service_worker": bool(capabilities.get("service_worker") or capabilities.get("serviceWorker")),
            "wake_lock": bool(capabilities.get("wake_lock") or capabilities.get("wakeLock")),
            "screen_off_standby": False,
        },
    }


def create_native_companion_package(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    body: dict[str, Any],
    handler: WasmAgentHandler,
) -> dict[str, Any]:
    if not user:
        raise BrowserError("auth_required", "Account sign-in is required.", status=HTTPStatus.UNAUTHORIZED)
    devices = list_account_devices(server, user, handler)
    current_device_id = str(devices.get("current_device_id") or request_account_device_id(user, handler))
    device_id = safe_state_id(str(body.get("device_id") or current_device_id), "")
    if not device_id:
        raise BrowserError("invalid_device", "device_id is required.")
    device = read_json_file(user_devices_dir(server, user) / f"{device_id}.json", {})
    if not isinstance(device, dict) or str(device.get("id") or device_id) != device_id:
        raise BrowserError("device_not_found", "That account device was not found.", status=HTTPStatus.NOT_FOUND)
    now = int(time.time())
    user_agent = clipped(str(device.get("user_agent") or handler.headers.get("User-Agent") or "Browser"), 360)
    profile = sanitize_native_device_profile(body.get("device_profile"), user_agent)
    token_id = uuid.uuid4().hex
    package = {
        "schema": NATIVE_COMPANION_PACKAGE_SCHEMA,
        "artifact_kind": "native-companion-installer",
        "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "token_id": token_id,
        "account_id": str(user.get("id") or ""),
        "target_device_id": device_id,
        "target_label": clipped(str(device.get("label") or browser_label(user_agent)), 80),
        "target_os": profile["os"],
        "target_device_type": profile["device_type"],
        "install_channel": profile["install_channel"],
        "mode": "native-companion-bootstrap",
        "standby_module_id": "native-standby",
        "capabilities": [
            "register-device",
            "report-online",
            "native-microphone",
            "wake-phrase-standby",
            "live-transcription",
            "device-presence",
        ],
        "standby": {
            "module_id": "native-standby",
            "enabled_from_pwa": bool(body.get("standby_module_enabled")),
            "wake_phrase": "hi wasm",
            "pwa_screen_off_standby": False,
            "native_screen_off_standby": profile["os"].lower() == "android",
            "transcript_event_schema": "hermes.wasm_agent.native_standby.transcript.v1",
        },
        "device_profile": profile,
        "layout_policy": "client-local",
        "artifact_policy": "shareable-wasm-artifacts",
        "transport": {
            "status": "planned",
            "preferred": "native-companion-relay",
            "fallback": "same-origin pwa foreground session",
        },
    }
    write_json_file(user_native_companion_dir(server, user) / f"{token_id}.json", {
        "schema": "hermes.wasm_agent.native_companion_request.v1",
        "token_id": token_id,
        "target_device_id": device_id,
        "target_os": profile["os"],
        "install_channel": profile["install_channel"],
        "standby_module_enabled": bool(body.get("standby_module_enabled")),
        "status": "installer_manifest_downloaded",
        "created_at": now,
        "created_by_device_id": current_device_id,
    })
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.native_companion_response.v1",
        "package": package,
    }


def shell_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def native_package_filename(package: dict[str, Any]) -> str:
    os_slug = safe_state_id(str(package.get("target_os") or "native").lower(), "native")
    device_slug = safe_state_id(str(package.get("target_device_id") or "device"), "device")[:48]
    return f"wasm-agent-native-{os_slug}-{device_slug}.zip"


NATIVE_WINDOWS_ELECTRON_VERSION = "42.3.2"


def native_desktop_channel(package: dict[str, Any]) -> str:
    os_name = str(package.get("target_os") or "").strip().lower()
    if os_name == "windows":
        return "electron-runtime-installer"
    if os_name in {"macos", "mac os", "mac", "linux"}:
        return "browser-wrapper"
    return "native-build-lane-pending"


def native_linux_install_script(app_url: str) -> str:
    quoted_url = shell_quote(app_url)
    return f"""#!/usr/bin/env sh
set -eu
APP_URL={quoted_url}
APP_DIR="${{XDG_DATA_HOME:-$HOME/.local/share}}/wasm-agent-native"
BIN_DIR="${{APP_DIR}}/bin"
DESKTOP_DIR="${{XDG_DATA_HOME:-$HOME/.local/share}}/applications"
mkdir -p "${{BIN_DIR}}" "${{DESKTOP_DIR}}"
cat > "${{BIN_DIR}}/wasm-agent-native" <<EOF
#!/usr/bin/env sh
APP_URL={quoted_url}
if command -v chromium >/dev/null 2>&1; then
  exec chromium --app="$APP_URL"
fi
if command -v google-chrome >/dev/null 2>&1; then
  exec google-chrome --app="$APP_URL"
fi
if command -v xdg-open >/dev/null 2>&1; then
  exec xdg-open "$APP_URL"
fi
printf '%s\\n' "$APP_URL"
EOF
chmod +x "${{BIN_DIR}}/wasm-agent-native"
cat > "${{DESKTOP_DIR}}/wasm-agent-native.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=WASM Agent
Comment=Open WASM Agent as a native desktop app wrapper
Exec=${{BIN_DIR}}/wasm-agent-native
Terminal=false
Categories=Utility;Development;
StartupNotify=true
EOF
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${{DESKTOP_DIR}}" >/dev/null 2>&1 || true
fi
printf 'WASM Agent native launcher installed.\\n'
"""


def native_macos_app_script(app_url: str) -> str:
    quoted_url = shell_quote(app_url)
    return f"""#!/bin/sh
APP_URL={quoted_url}
if command -v open >/dev/null 2>&1; then
  open -a "Google Chrome" --args --app="$APP_URL" 2>/dev/null && exit 0
  open -a "Microsoft Edge" --args --app="$APP_URL" 2>/dev/null && exit 0
  open "$APP_URL"
fi
"""


def native_windows_install_script(app_url: str) -> str:
    escaped_url = app_url.replace("'", "''")
    electron_version = NATIVE_WINDOWS_ELECTRON_VERSION.replace("'", "")
    return """$ErrorActionPreference = "Stop"
$AppUrl = '{escaped_url}'
$ElectronVersion = if ($env:WASM_AGENT_ELECTRON_VERSION) { $env:WASM_AGENT_ELECTRON_VERSION } else { '{electron_version}' }
$InstallDir = Join-Path $env:LOCALAPPDATA 'WASM Agent Native'
$StartMenu = Join-Path $env:APPDATA 'Microsoft\\Windows\\Start Menu\\Programs'
$Desktop = [Environment]::GetFolderPath('Desktop')
$RuntimeDir = Join-Path $InstallDir 'runtime'
$CacheDir = Join-Path $InstallDir 'cache'
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppSourceDir = Join-Path $ScriptRoot 'electron-app'
$AppDestDir = Join-Path $RuntimeDir 'resources\\app'
$AppExe = Join-Path $RuntimeDir 'WASM Agent.exe'
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $StartMenu | Out-Null
New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null

if (!(Test-Path $AppSourceDir)) {
  throw "Missing electron app payload: $AppSourceDir. Extract the ZIP first, then run windows\\install.cmd."
}

$arch = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
$electronArch = if ($arch -eq 'arm64') { 'arm64' } else { 'x64' }
$RuntimeZip = Join-Path $CacheDir "electron-v$ElectronVersion-win32-$electronArch.zip"
$RuntimeUrl = "https://github.com/electron/electron/releases/download/v$ElectronVersion/electron-v$ElectronVersion-win32-$electronArch.zip"

if (Test-Path $RuntimeDir) {
  Remove-Item -Recurse -Force $RuntimeDir
}
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

Write-Host "Downloading Electron $ElectronVersion for Windows $electronArch..."
Invoke-WebRequest -UseBasicParsing -Uri $RuntimeUrl -OutFile $RuntimeZip
Write-Host "Expanding native runtime..."
Expand-Archive -LiteralPath $RuntimeZip -DestinationPath $RuntimeDir -Force

if (!(Test-Path (Join-Path $RuntimeDir 'electron.exe'))) {
  throw "Electron runtime extraction did not produce electron.exe"
}

New-Item -ItemType Directory -Force -Path $AppDestDir | Out-Null
Copy-Item -Recurse -Force (Join-Path $AppSourceDir '*') $AppDestDir
Set-Content -Path (Join-Path $AppDestDir 'native-package.json') -Encoding UTF8 -Value (@{
  schema = 'hermes.wasm_agent.native_desktop_config.v1'
  appUrl = $AppUrl
  installChannel = 'electron-runtime-installer'
  electronVersion = $ElectronVersion
  generatedAt = (Get-Date).ToUniversalTime().ToString('o')
} | ConvertTo-Json -Depth 4)

Rename-Item -LiteralPath (Join-Path $RuntimeDir 'electron.exe') -NewName 'WASM Agent.exe' -Force

$UninstallPath = Join-Path $InstallDir 'uninstall-wasm-agent.cmd'
Set-Content -Path $UninstallPath -Encoding ASCII -Value @"
@echo off
del "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\WASM Agent.lnk" >nul 2>nul
del "%USERPROFILE%\\Desktop\\WASM Agent.lnk" >nul 2>nul
rmdir /s /q "%LOCALAPPDATA%\\WASM Agent Native"
echo WASM Agent native desktop app removed.
"@

try {
  $shell = New-Object -ComObject WScript.Shell
  $targets = @(
    (Join-Path $StartMenu 'WASM Agent.lnk'),
    (Join-Path $Desktop 'WASM Agent.lnk')
  )
  foreach ($target in $targets) {
    $shortcut = $shell.CreateShortcut($target)
    $shortcut.TargetPath = $AppExe
    $shortcut.WorkingDirectory = $RuntimeDir
    $shortcut.Description = 'Open WASM Agent native desktop app'
    $shortcut.IconLocation = "$AppExe,0"
    $shortcut.Save()
  }
} catch {
  Write-Warning "Could not create .lnk shortcuts: $($_.Exception.Message)"
}

Write-Host "WASM Agent native desktop app installed: $AppExe"
Write-Host "Start Menu: WASM Agent"
Write-Host "Desktop: WASM Agent"
Write-Host "Launching WASM Agent now..."
Start-Process -FilePath $AppExe
""".replace("{escaped_url}", escaped_url).replace("{electron_version}", electron_version)


def native_windows_install_cmd() -> str:
    return """@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo WASM Agent install failed. Keep this window open and share the error above.
  pause
)
"""


def native_windows_readme() -> str:
    return """# Windows

Extract the ZIP first, then run `install.cmd`. It launches PowerShell with a
temporary execution-policy bypass, downloads the pinned Electron runtime, builds
`WASM Agent.exe` under `%LOCALAPPDATA%\\WASM Agent Native`, creates Start Menu
and Desktop shortcuts, and opens the app once installation completes.

This is not an Edge/Chrome PWA shortcut. It is a native desktop process backed
by Electron. It still loads the wasm-agent app URL until the offline bundled UI
and signed MSI/EXE build lane are added.

You can also run `install.ps1` directly from PowerShell.
"""


def native_windows_electron_package_json() -> str:
    return json.dumps({
        "name": "wasm-agent-native",
        "version": "0.1.0",
        "description": "WASM Agent native desktop host",
        "main": "main.js",
        "private": True,
    }, indent=2, sort_keys=True)


def native_windows_electron_main_js() -> str:
    return """const { app, BrowserWindow, Menu, shell } = require("electron");
const fs = require("fs");
const path = require("path");

const DEFAULT_APP_URL = "http://127.0.0.1:8877";

function readConfig() {
  const configPath = path.join(__dirname, "native-package.json");
  try {
    return JSON.parse(fs.readFileSync(configPath, "utf8"));
  } catch {
    return {};
  }
}

function resolvedAppUrl() {
  const config = readConfig();
  const raw = process.env.WASM_AGENT_APP_URL || config.appUrl || DEFAULT_APP_URL;
  if (typeof raw !== "string" || !raw.trim() || raw.trim() === "/") {
    return DEFAULT_APP_URL;
  }
  return raw.trim();
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 640,
    title: "WASM Agent",
    backgroundColor: "#090d12",
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(resolvedAppUrl())) {
      return { action: "allow" };
    }
    shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, url) => {
    const appUrl = resolvedAppUrl();
    if (url.startsWith(appUrl)) return;
    if (url.startsWith("http://") || url.startsWith("https://")) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });
  win.loadURL(resolvedAppUrl());
}

app.setName("WASM Agent");
Menu.setApplicationMenu(null);

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
"""


def native_windows_electron_preload_js() -> str:
    return """const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("wasmAgentNative", {
  platform: "windows",
  runtime: "electron",
  nativeDesktop: true,
});
"""


def native_package_readme(package: dict[str, Any], app_url: str) -> str:
    return f"""# WASM Agent Native Download

This package was generated for `{package.get("target_label")}`.

App URL: {app_url}
Target OS: {package.get("target_os")}
Install channel: {package.get("install_channel")}

## What This Is

This bundle contains platform install assets for moving wasm-agent out of the
plain browser. It also includes internal package metadata for the future native
standby companion. On Windows, `windows/install.cmd` installs an
Electron-backed `WASM Agent.exe` desktop process instead of opening Edge or
Chrome.

## Install

- Linux: run `sh linux/install.sh`.
- macOS: copy `macos/WASM Agent.app` to Applications. The bundle is unsigned.
- Windows: extract the ZIP, then run `windows/install.cmd`; it downloads the
  pinned Electron runtime, installs `WASM Agent.exe`, and creates Start
  Menu/Desktop shortcuts for that executable.
- Android: use `android/README.md` until the APK builder/signing lane is added.
- iOS: use `ios/README.md` until the IPA/TestFlight lane is added.

The screen-off `hi wasm` standby path still requires a real native companion
binary. This package prepares the app install/download contract and keeps the
standby module metadata together with the platform launcher.
"""


def create_native_download_bundle(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    body: dict[str, Any],
    handler: WasmAgentHandler,
) -> tuple[str, bytes, dict[str, Any]]:
    response = create_native_companion_package(server, user, body, handler)
    package = dict(response.get("package") or {})
    app_url = public_origin() or request_host_origin(handler) or "/"
    package["app_url"] = app_url
    package["download_schema"] = "hermes.wasm_agent.native_app_download.v1"
    package["desktop_native_channel"] = native_desktop_channel(package)
    if package["desktop_native_channel"] == "electron-runtime-installer":
        package["desktop_runtime"] = {
            "kind": "electron",
            "version": NATIVE_WINDOWS_ELECTRON_VERSION,
            "installer": "windows/install.cmd",
            "app_executable": "WASM Agent.exe",
        }
    filename = native_package_filename(package)
    metadata = {
        "schema": "hermes.wasm_agent.native_app_download.v1",
        "filename": filename,
        "app_url": app_url,
        "package": package,
        "generated_at": iso_timestamp(),
    }
    macos_info = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>wasm-agent</string>
  <key>CFBundleIdentifier</key><string>com.colmeio.wasm-agent</string>
  <key>CFBundleName</key><string>WASM Agent</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
</dict>
</plist>
"""
    android_readme = """# Android

The generated desktop wrappers are in this ZIP. A real Android installable
requires an APK/AAB build and signing lane. The intended implementation is a
native companion or Trusted Web Activity that opens the app URL, registers the
device, and owns foreground-service wake/transcription behavior.
"""
    ios_readme = """# iOS

iOS installables require an Apple build/signing host and TestFlight/App Store or
enterprise distribution. The PWA can be added to the Home Screen, but screen-off
wake phrase standby requires a native companion path that is not built here yet.
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        def write_executable(name: str, text: str) -> None:
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o755 << 16
            archive.writestr(info, text)

        archive.writestr("README.md", native_package_readme(package, app_url))
        archive.writestr("metadata/package.json", json.dumps(metadata, indent=2, sort_keys=True))
        write_executable("linux/install.sh", native_linux_install_script(app_url))
        archive.writestr("linux/wasm-agent-native.desktop", "[Desktop Entry]\nType=Application\nName=WASM Agent\n")
        archive.writestr("macos/WASM Agent.app/Contents/Info.plist", macos_info)
        write_executable("macos/WASM Agent.app/Contents/MacOS/wasm-agent", native_macos_app_script(app_url))
        archive.writestr("windows/README.md", native_windows_readme())
        archive.writestr("windows/install.cmd", native_windows_install_cmd())
        archive.writestr("windows/install.ps1", native_windows_install_script(app_url))
        archive.writestr("windows/electron-app/package.json", native_windows_electron_package_json())
        archive.writestr("windows/electron-app/main.js", native_windows_electron_main_js())
        archive.writestr("windows/electron-app/preload.js", native_windows_electron_preload_js())
        archive.writestr("android/README.md", android_readme)
        archive.writestr("ios/README.md", ios_readme)
    return filename, buffer.getvalue(), metadata


def serve_native_download_package(handler: WasmAgentHandler, user: dict[str, Any] | None, body: dict[str, Any]) -> None:
    filename, data, metadata = create_native_download_bundle(handler.server, user, body, handler)
    platform = str(metadata.get("package", {}).get("target_os") or "native")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/zip")
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("X-Wasm-Agent-Native-Schema", str(metadata.get("schema") or ""))
    handler.send_header("X-Wasm-Agent-Native-Platform", clipped(platform, 80))
    handler.send_header("X-Wasm-Agent-Native-Desktop-Channel", clipped(str(metadata.get("package", {}).get("desktop_native_channel") or ""), 80))
    handler.end_headers()
    handler.wfile.write(data)


def export_user_storage(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    handler: WasmAgentHandler | None = None,
) -> dict[str, Any]:
    if not user:
        raise BrowserError("auth_required", "Account sign-in is required.", status=HTTPStatus.UNAUTHORIZED)
    spaces = list_user_spaces(server, user, handler)
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.storage_export.v1",
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "account_id": str(user.get("id") or ""),
        "current_device_id": spaces.get("current_device_id", ""),
        "layout_policy": "client-local",
        "storage": user_storage(server, user),
        "spaces": spaces.get("spaces", []),
        "widget_layouts": {},
        "device_layouts": {},
    }


def import_user_storage(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    body: dict[str, Any],
    handler: WasmAgentHandler | None = None,
) -> dict[str, Any]:
    if not user:
        raise BrowserError("auth_required", "Account sign-in is required.", status=HTTPStatus.UNAUTHORIZED)
    if str(body.get("schema") or "") != "hermes.wasm_agent.storage_export.v1":
        raise BrowserError("invalid_storage_import", "Storage import expects a wasm-agent storage export.")
    spaces = body.get("spaces")
    if not isinstance(spaces, list):
        raise BrowserError("invalid_storage_import", "Storage export is missing spaces.")
    ensure_user_quota(server, user, len(json.dumps(body, ensure_ascii=True).encode("utf-8")))
    save_user_spaces(server, user, {"action": "replace", "spaces": spaces}, handler)
    return list_user_spaces(server, user, handler)


def normalized_space_area_pixel(value: Any) -> int | None:
    try:
        number = int(round(float(value)))
    except (OverflowError, TypeError, ValueError):
        return None
    if number < SPACE_AREA_MIN_PX:
        return SPACE_AREA_MIN_PX
    if number > SPACE_AREA_MAX_PX:
        return SPACE_AREA_MAX_PX
    return number


def sanitize_space_area(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    width = normalized_space_area_pixel(
        value.get("width_px", value.get("widthPx", value.get("width")))
    )
    height = normalized_space_area_pixel(
        value.get("height_px", value.get("heightPx", value.get("height")))
    )
    if width is None or height is None:
        return None
    return {"width_px": width, "height_px": height}


def list_user_spaces(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    handler: WasmAgentHandler | None = None,
) -> dict[str, Any]:
    spaces = []
    current_device_id = request_account_device_id(user, handler) if handler else ""
    user_space_paths = [path for path in sorted(user_spaces_dir(server, user).iterdir()) if path.is_dir()]
    for path in user_space_paths:
        meta = read_json_file(path / "space.json", {})
        if isinstance(meta, dict) and meta and not is_reserved_user_space_id(path.name):
            shared_space_id = str(meta.get("shared_space_id") or "")
            space_area = sanitize_space_area(meta.get("space_area"))
            if shared_space_id:
                shared_record = read_shared_space_record(server, shared_space_id)
                if shared_record and user_can_access_shared_space(shared_record, user):
                    space_area = sanitize_space_area(shared_record.get("space_area")) or space_area
            spaces.append({
                "id": path.name,
                "title": clipped(str(meta.get("title") or path.name), 120),
                "created_at": str(meta.get("created_at") or ""),
                "updated_at": str(meta.get("updated_at") or ""),
                "shared": bool(meta.get("shared")),
                "shared_space_id": shared_space_id,
                "space_area": space_area or {},
            })
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.user_spaces.v1",
        "current_device_id": current_device_id,
        "layout_policy": "client-local",
        "storage": user_storage(server, user),
        "spaces": spaces,
        "shared_spaces": list_shared_spaces(server, user).get("spaces", []),
        "widget_layouts": {},
    }


def save_user_spaces(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    body: dict[str, Any],
    handler: WasmAgentHandler | None = None,
) -> dict[str, Any]:
    action = str(body.get("action") or "replace").strip().lower()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ensure_user_quota(server, user, len(json.dumps(body, ensure_ascii=True).encode("utf-8")))
    if action == "layout":
        raise BrowserError("layout_is_client_local", "Layout is client-local by default; server layout sync requires premium storage.")
    if action == "delete":
        space_id = safe_state_id(str(body.get("space_id") or ""), "")
        if not space_id or is_reserved_user_space_id(space_id):
            raise BrowserError("invalid_space_delete", "Only user-created spaces can be deleted.")
        shutil.rmtree(user_space_dir(server, user, space_id), ignore_errors=True)
        return list_user_spaces(server, user, handler)
    if action in {"area", "space_area"}:
        space_id = safe_state_id(str(body.get("space_id") or ""), "")
        if not space_id or is_reserved_user_space_id(space_id):
            raise BrowserError("invalid_space_area", "Only user-created spaces can store shared area metadata.")
        space_area = sanitize_space_area(body.get("space_area"))
        if not space_area:
            raise BrowserError("invalid_space_area", "space_area must include width_px and height_px.")
        space_path = user_spaces_dir(server, user) / space_id / "space.json"
        meta = read_json_file(space_path, {})
        if not isinstance(meta, dict) or not meta:
            raise BrowserError("space_not_found", "That space was not found.", status=HTTPStatus.NOT_FOUND)
        shared_space_id = safe_state_id(str(
            body.get("shared_space_id")
            or meta.get("shared_space_id")
            or ""
        ), "")
        meta["space_area"] = space_area
        meta["updated_at"] = now
        write_json_file(space_path, meta)
        if shared_space_id:
            record = read_shared_space_record(server, shared_space_id)
            if record and user_can_access_shared_space(record, user):
                record["space_area"] = space_area
                record["updated_at"] = now
                write_json_file(shared_space_record_path(server, shared_space_id), record)
        return list_user_spaces(server, user, handler)
    if action == "replace":
        spaces = body.get("spaces")
        if not isinstance(spaces, list):
            raise BrowserError("invalid_spaces", "spaces must be an array.")
        seen: set[str] = set()
        for item in spaces[:40]:
            if not isinstance(item, dict):
                continue
            space_id = safe_state_id(str(item.get("id") or ""), "")
            if not space_id or is_reserved_user_space_id(space_id) or space_id in seen:
                continue
            seen.add(space_id)
            root = user_space_dir(server, user, space_id)
            existing = read_json_file(root / "space.json", {})
            created_at = str(item.get("created_at") or (existing.get("created_at") if isinstance(existing, dict) else "") or now)
            title = clipped(str(item.get("title") or space_id), 120)
            shared_space_id = safe_state_id(str(
                item.get("shared_space_id")
                or (existing.get("shared_space_id") if isinstance(existing, dict) else "")
                or ""
            ), "")
            shared = bool(item.get("shared") or (existing.get("shared") if isinstance(existing, dict) else False) or shared_space_id)
            space_area = sanitize_space_area(item.get("space_area")) or (
                sanitize_space_area(existing.get("space_area")) if isinstance(existing, dict) else None
            )
            write_json_file(root / "space.json", {
                "schema": "hermes.wasm_agent.space.v1",
                "id": space_id,
                "title": title,
                "shared": shared,
                "shared_space_id": shared_space_id,
                "space_area": space_area or {},
                "created_at": created_at,
                "updated_at": now,
            })
            if shared_space_id:
                record = read_shared_space_record(server, shared_space_id)
                if record and user_can_access_shared_space(record, user):
                    record["title"] = title
                    # Shared area is canonical after creation; targeted area patches update it.
                    if space_area and not sanitize_space_area(record.get("space_area")):
                        record["space_area"] = space_area
                    record["updated_at"] = now
                    write_json_file(shared_space_record_path(server, shared_space_id), record)
        for path in user_spaces_dir(server, user).iterdir():
            if path.is_dir() and (path.name in BUILT_IN_SPACE_ID_ALIASES or (not is_reserved_user_space_id(path.name) and path.name not in seen)):
                shutil.rmtree(path, ignore_errors=True)
        return list_user_spaces(server, user, handler)
    raise BrowserError("invalid_space_action", "Unsupported space action.")


def iso_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=True))


def shared_space_record_path(server: WasmAgentServer, shared_space_id: str) -> Path:
    return shared_space_dir(server, shared_space_id) / "shared-space.json"


def read_shared_space_record(server: WasmAgentServer, shared_space_id: str) -> dict[str, Any]:
    payload = read_json_file(shared_space_record_path(server, shared_space_id), {})
    return payload if isinstance(payload, dict) else {}


def shared_space_member_ids(record: dict[str, Any]) -> set[str]:
    members = record.get("members") if isinstance(record.get("members"), list) else []
    return {str(item.get("user_id") if isinstance(item, dict) else item) for item in members if str(item).strip()}


def user_can_access_shared_space(record: dict[str, Any], user: dict[str, Any] | None) -> bool:
    uid = user_id(user)
    return user_is_admin(user) or str(record.get("owner_user_id") or "") == uid or uid in shared_space_member_ids(record)


def public_shared_space_record(
    record: dict[str, Any],
    user: dict[str, Any] | None,
    server: WasmAgentServer | None = None,
) -> dict[str, Any]:
    owner = str(record.get("owner_user_id") or "")
    uid = user_id(user)
    sid = str(record.get("id") or "")
    payload = {
        "schema": SHARED_SPACE_SCHEMA,
        "id": sid,
        "title": clipped(str(record.get("title") or "Shared Space"), 120),
        "owner_user_id": owner,
        "member_count": len(shared_space_member_ids(record)),
        "online_count": 0,
        "created_at": str(record.get("created_at") or ""),
        "updated_at": str(record.get("updated_at") or ""),
        "capabilities": record.get("capabilities") if isinstance(record.get("capabilities"), list) else [],
        "local_space_id": str(record.get("local_space_id") or ""),
        "source_space_id": str(record.get("source_space_id") or ""),
        "space_area": sanitize_space_area(record.get("space_area")) or {},
        "joined": user_can_access_shared_space(record, user),
        "owner": owner == uid,
    }
    if sid and server:
        try:
            payload.update(shared_space_presence_summary(read_shared_space_presence(server, sid), int(time.time())))
        except Exception:
            payload["online_count"] = 0
    if payload["joined"] or user_is_admin(user):
        payload["join_code"] = str(record.get("join_code") or "")
    return payload


def list_shared_spaces(server: WasmAgentServer, user: dict[str, Any] | None) -> dict[str, Any]:
    spaces = []
    for path in sorted(shared_spaces_dir(server).iterdir()):
        if not path.is_dir():
            continue
        record = read_json_file(path / "shared-space.json", {})
        if isinstance(record, dict) and user_can_access_shared_space(record, user):
            spaces.append(public_shared_space_record(record, user, server))
    return {
        "ok": True,
        "schema": SHARED_SPACE_LIST_SCHEMA,
        "spaces": spaces,
    }


def shared_space_presence_path(server: WasmAgentServer, shared_space_id: str) -> Path:
    return shared_space_dir(server, shared_space_id) / "presence.json"


def shared_space_events_path(server: WasmAgentServer, shared_space_id: str) -> Path:
    return shared_space_dir(server, shared_space_id) / "room-events.json"


def read_shared_space_presence(server: WasmAgentServer, shared_space_id: str) -> dict[str, Any]:
    payload = read_json_file(shared_space_presence_path(server, shared_space_id), {})
    return payload if isinstance(payload, dict) else {}


def sanitize_room_event_payload(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return ""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except (OverflowError, TypeError, ValueError):
            return 0
        return value if math.isfinite(number) else 0
    if isinstance(value, str):
        return clipped(value, 4000)
    if isinstance(value, list):
        return [sanitize_room_event_payload(item, depth=depth + 1) for item in value[:32]]
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in list(value.items())[:48]:
            clean_key = safe_state_id(str(key), "")
            if not clean_key:
                continue
            if re.search(r"password|secret|token|api[_-]?key|authorization|cookie|session", clean_key, re.I):
                clean[clean_key] = "[redacted]"
            elif clean_key in {"sdp", "candidate"}:
                clean[clean_key] = clipped_verbatim(str(item), SHARED_SPACE_SIGNAL_TEXT_LIMIT)
            else:
                clean[clean_key] = sanitize_room_event_payload(item, depth=depth + 1)
        return clean
    return clipped(str(value), 400)


def prune_shared_space_presence(payload: dict[str, Any], now: int) -> dict[str, Any]:
    entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
    live_entries = {
        key: item
        for key, item in entries.items()
        if isinstance(item, dict) and now - int(item.get("last_seen") or 0) <= SHARED_SPACE_PRESENCE_TTL_SEC
    }
    return {
        "schema": SHARED_SPACE_PRESENCE_SCHEMA,
        "updated_at": iso_timestamp(),
        "entries": live_entries,
    }


def touch_shared_space_presence(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    handler: WasmAgentHandler,
    shared_space_id: str,
    space_id: str,
) -> dict[str, Any]:
    now = int(time.time())
    presence = prune_shared_space_presence(read_shared_space_presence(server, shared_space_id), now)
    user_agent = clipped(str(handler.headers.get("User-Agent") or "Browser"), 360)
    device_id = request_account_device_id(user, handler)
    key = f"{user_id(user)}:{device_id}"
    entries = presence.get("entries") if isinstance(presence.get("entries"), dict) else {}
    entries[key] = {
        "user_id": user_id(user),
        "device_id": device_id,
        "space_id": safe_state_id(space_id, ""),
        "label": browser_label(user_agent),
        "user_label": public_user_label(user),
        "last_seen": now,
    }
    presence["entries"] = entries
    presence["updated_at"] = iso_timestamp()
    write_json_file(shared_space_presence_path(server, shared_space_id), presence)
    return presence


def shared_space_presence_summary(presence: dict[str, Any], now: int | None = None) -> dict[str, int]:
    now = now or int(time.time())
    entries = presence.get("entries") if isinstance(presence.get("entries"), dict) else {}
    online_users = {
        str(item.get("user_id") or "")
        for item in entries.values()
        if isinstance(item, dict) and now - int(item.get("last_seen") or 0) <= SHARED_SPACE_PRESENCE_TTL_SEC
    }
    online_users.discard("")
    online_devices = [
        item
        for item in entries.values()
        if isinstance(item, dict) and now - int(item.get("last_seen") or 0) <= SHARED_SPACE_PRESENCE_TTL_SEC
    ]
    return {"online_count": len(online_users), "online_device_count": len(online_devices)}


def public_shared_space_presence_entries(presence: dict[str, Any], now: int | None = None) -> list[dict[str, Any]]:
    now = now or int(time.time())
    entries = presence.get("entries") if isinstance(presence.get("entries"), dict) else {}
    visible = []
    for item in entries.values():
        if not isinstance(item, dict):
            continue
        last_seen = int(item.get("last_seen") or 0)
        if now - last_seen > SHARED_SPACE_PRESENCE_TTL_SEC:
            continue
        visible.append({
            "user_id": safe_state_id(str(item.get("user_id") or ""), ""),
            "device_id": safe_state_id(str(item.get("device_id") or ""), ""),
            "space_id": safe_state_id(str(item.get("space_id") or ""), ""),
            "label": clipped(str(item.get("label") or "Browser"), 80),
            "user_label": clipped(str(item.get("user_label") or item.get("user_id") or "User"), 120),
            "last_seen": last_seen,
        })
    visible.sort(key=lambda entry: (entry["user_label"].lower(), entry["device_id"]))
    return visible


def public_shared_space_member_entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    member_ids = {str(record.get("owner_user_id") or "")}
    member_ids.update(shared_space_member_ids(record))
    member_ids = {safe_state_id(item, "") for item in member_ids if safe_state_id(item, "")}
    if not member_ids:
        return []
    with auth_connect() as conn:
        members = []
        for member_id in sorted(member_ids):
            user = public_social_user(lookup_user_row(conn, member_id))
            if user:
                user["owner"] = member_id == str(record.get("owner_user_id") or "")
                members.append(user)
    return members


def read_shared_space_events(server: WasmAgentServer, shared_space_id: str) -> list[dict[str, Any]]:
    payload = read_json_file(shared_space_events_path(server, shared_space_id), {})
    events = payload.get("events") if isinstance(payload, dict) and isinstance(payload.get("events"), list) else []
    return [event for event in events if isinstance(event, dict)][-SHARED_SPACE_EVENT_LIMIT:]


def append_shared_space_room_event(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    shared_space_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    events = read_shared_space_events(server, shared_space_id)
    event = build_shared_space_room_event(user, body)
    events.append(event)
    write_json_file(shared_space_events_path(server, shared_space_id), {
        "schema": "hermes.wasm_agent.shared_space.room_events.v1",
        "updated_at": iso_timestamp(),
        "events": events[-SHARED_SPACE_EVENT_LIMIT:],
    })
    return event


def build_shared_space_room_event(
    user: dict[str, Any] | None,
    body: dict[str, Any],
) -> dict[str, Any]:
    event_kind = safe_state_id(str(body.get("kind") or body.get("event_kind") or "space-event"), "space-event")
    return {
        "schema": SHARED_SPACE_ROOM_EVENT_SCHEMA,
        "id": f"room_evt_{next_snowflake_id():x}",
        "kind": event_kind,
        "sender_user_id": user_id(user),
        "created_at": iso_timestamp(),
        "payload": sanitize_room_event_payload(body.get("payload") if isinstance(body.get("payload"), dict) else {}),
    }


def public_shared_space_room(
    server: WasmAgentServer,
    record: dict[str, Any],
    user: dict[str, Any] | None,
    presence: dict[str, Any] | None = None,
    current_device_id: str = "",
) -> dict[str, Any]:
    sid = str(record.get("id") or "")
    now = int(time.time())
    current_presence = prune_shared_space_presence(presence or read_shared_space_presence(server, sid), now)
    summary = shared_space_presence_summary(current_presence, now)
    member_count = len(shared_space_member_ids(record))
    return {
        "schema": SHARED_SPACE_ROOM_SCHEMA,
        "id": sid,
        "title": clipped(str(record.get("title") or "Shared Space"), 120),
        "member_count": member_count,
        "online_count": summary["online_count"],
        "online_device_count": summary["online_device_count"],
        "space_area": sanitize_space_area(record.get("space_area")) or {},
        "capabilities": record.get("capabilities") if isinstance(record.get("capabilities"), list) else [],
        "updated_at": str(record.get("updated_at") or ""),
        "presence_ttl_sec": SHARED_SPACE_PRESENCE_TTL_SEC,
        "presence": public_shared_space_presence_entries(current_presence, now),
        "members": public_shared_space_member_entries(record),
        "current_user_id": user_id(user),
        "current_device_id": safe_state_id(current_device_id, ""),
        "events": read_shared_space_events(server, sid)[-SHARED_SPACE_ROOM_PUBLIC_EVENT_LIMIT:],
        "joined": user_can_access_shared_space(record, user),
    }


def shared_space_room(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    body: dict[str, Any],
    handler: WasmAgentHandler,
) -> dict[str, Any]:
    shared_space_id = safe_state_id(str(body.get("shared_space_id") or body.get("shared_space") or ""), "")
    if not shared_space_id:
        raise BrowserError("invalid_shared_space", "shared_space_id is required.")
    record = read_shared_space_record(server, shared_space_id)
    if not record:
        raise BrowserError("shared_space_not_found", "That shared space was not found.", status=HTTPStatus.NOT_FOUND)
    if not user_can_access_shared_space(record, user):
        raise BrowserError("shared_space_denied", "You cannot access that shared space.", status=HTTPStatus.FORBIDDEN)
    action = str(body.get("action") or "presence").strip().lower()
    space_id = safe_state_id(str(body.get("space_id") or record.get("local_space_id") or ""), "")
    presence = read_shared_space_presence(server, shared_space_id)
    current_device_id = request_account_device_id(user, handler)
    if action in {"presence", "join", "heartbeat"}:
        presence = touch_shared_space_presence(server, user, handler, shared_space_id, space_id)
    elif action in {"event", "message", "signal"}:
        presence = touch_shared_space_presence(server, user, handler, shared_space_id, space_id)
        append_shared_space_room_event(server, user, shared_space_id, body)
    elif action != "read":
        raise BrowserError("invalid_space_room_action", "Unsupported shared-space room action.")
    return {"ok": True, "room": public_shared_space_room(server, record, user, presence, current_device_id)}


def sync_event_payload(raw: Any, kind: str = "") -> str:
    payload = raw if isinstance(raw, dict) else {}
    text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    limit = REMOTE_CONTROL_FRAME_PAYLOAD_LIMIT if kind == "remote-control-frame" else SYNC_EVENT_PAYLOAD_LIMIT
    if len(text.encode("utf-8")) > limit:
        raise BrowserError("sync_payload_too_large", "Sync event payload is too large.")
    return text


def sync_event_kind(raw: Any) -> str:
    return safe_state_id(str(raw or "message"), "message")


def normalize_sync_event_payload(user: dict[str, Any] | None, kind: str, raw: Any) -> dict[str, Any]:
    payload = dict(raw) if isinstance(raw, dict) else {}
    if kind in REMOTE_CONTROL_EVENT_KINDS:
        payload["admin_verified"] = user_is_admin(user)
        if kind == "remote-control-request" and not user_is_admin(user):
            payload["admin_support"] = False
    return payload


def user_can_access_conversation(conn: sqlite3.Connection, conversation_id: str, user: dict[str, Any] | None) -> bool:
    if user_is_admin(user):
        return True
    row = conn.execute(
        "SELECT 1 FROM conversation_member_tb WHERE conversation_id = ? AND user_id = ?",
        (conversation_id, user_id(user)),
    ).fetchone()
    return bool(row)


def direct_conversation_peer_id(conn: sqlite3.Connection, conversation_id: str, user: dict[str, Any] | None) -> str:
    row = conn.execute("SELECT kind FROM conversation_tb WHERE id = ?", (conversation_id,)).fetchone()
    if not row or str(row["kind"]) != "direct":
        return ""
    uid = user_id(user)
    peer = conn.execute(
        """
        SELECT user_id FROM conversation_member_tb
         WHERE conversation_id = ? AND user_id != ?
         ORDER BY user_id ASC
         LIMIT 1
        """,
        (conversation_id, uid),
    ).fetchone()
    return str(peer["user_id"]) if peer else ""


def remote_control_admin_support_allowed(
    conn: sqlite3.Connection,
    user: dict[str, Any] | None,
    peer_id: str,
    kind: str,
) -> bool:
    if kind not in REMOTE_CONTROL_EVENT_KINDS or not peer_id:
        return False
    if user_is_admin(user):
        return True
    peer = lookup_user_row(conn, peer_id)
    return row_is_admin(peer) and kind in REMOTE_CONTROL_ADMIN_REPLY_KINDS


def ensure_direct_conversation_send_allowed(
    conn: sqlite3.Connection,
    conversation_id: str,
    user: dict[str, Any] | None,
    kind: str = "message",
) -> None:
    peer_id = direct_conversation_peer_id(conn, conversation_id, user)
    if not peer_id:
        return
    friendship = existing_friendship(conn, user_id(user), peer_id)
    if (
        (not friendship or str(friendship["status"]) != "accepted")
        and not remote_control_admin_support_allowed(conn, user, peer_id, kind)
    ):
        raise BrowserError(
            "direct_peer_not_friend",
            "Direct chat requires an accepted friendship.",
            status=HTTPStatus.FORBIDDEN,
        )


def ensure_sync_conversation(
    server: WasmAgentServer,
    conn: sqlite3.Connection,
    user: dict[str, Any] | None,
    body: dict[str, Any],
) -> str:
    uid = user_id(user)
    event_kind = sync_event_kind(body.get("kind"))
    requested = safe_state_id(str(body.get("conversation_id") or body.get("conversation") or ""), "")
    shared_space_id = safe_state_id(str(body.get("shared_space_id") or body.get("shared_space") or ""), "")
    space_id = safe_state_id(str(body.get("space_id") or body.get("space") or ""), "")
    peer_user_id = safe_state_id(str(body.get("peer_user_id") or body.get("peer") or ""), "")
    direct_peer_id = ""
    shared_record: dict[str, Any] | None = None
    if peer_user_id:
        peer = lookup_user_row(conn, peer_user_id)
        if not peer:
            raise BrowserError("direct_peer_not_found", "That direct-chat user was not found.", status=HTTPStatus.NOT_FOUND)
        direct_peer_id = str(peer["id"])
        if direct_peer_id == uid:
            raise BrowserError("direct_peer_self", "Direct chat requires another user.")
        friendship = existing_friendship(conn, uid, direct_peer_id)
        if (
            (not friendship or str(friendship["status"]) != "accepted")
            and not remote_control_admin_support_allowed(conn, user, direct_peer_id, event_kind)
        ):
            raise BrowserError(
                "direct_peer_not_friend",
                "Direct chat requires an accepted friendship.",
                status=HTTPStatus.FORBIDDEN,
            )
        pair = sorted([uid, direct_peer_id])
        requested = requested or f"dm-{pair[0]}-{pair[1]}"
        kind = "direct"
        title = clipped(str(body.get("title") or f"DM {pair[0]} {pair[1]}"), 120)
    elif shared_space_id:
        shared_record = read_shared_space_record(server, shared_space_id)
        if not shared_record:
            raise BrowserError("shared_space_not_found", "That shared space was not found.", status=HTTPStatus.NOT_FOUND)
        if not user_can_access_shared_space(shared_record, user):
            raise BrowserError("shared_space_denied", "You cannot access that shared space.", status=HTTPStatus.FORBIDDEN)
        requested = requested or f"space-{shared_space_id}"
        kind = "shared-space"
        title = clipped(str(shared_record.get("title") or shared_space_id), 120)
    else:
        requested = requested or f"local-{uid}"
        kind = clipped(str(body.get("conversation_kind") or "local"), 40)
        title = clipped(str(body.get("title") or requested), 120)
    now = int(time.time())
    row = conn.execute("SELECT * FROM conversation_tb WHERE id = ?", (requested,)).fetchone()
    if not row:
        conn.execute(
            """
            INSERT INTO conversation_tb (
              id, kind, space_id, shared_space_id, title, created_by, created_at, updated_at, client_owned
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (requested, kind, space_id, shared_space_id, title, uid, now, now),
        )
    elif not user_can_access_conversation(conn, requested, user) and not (
        kind == "shared-space" and shared_record and user_can_access_shared_space(shared_record, user)
    ):
        raise BrowserError("conversation_denied", "You cannot access that conversation.", status=HTTPStatus.FORBIDDEN)
    conn.execute(
        """
        INSERT OR IGNORE INTO conversation_member_tb (conversation_id, user_id, role, joined_at)
        VALUES (?, ?, 'member', ?)
        """,
        (requested, uid, now),
    )
    if direct_peer_id:
        conn.execute(
            """
            INSERT OR IGNORE INTO conversation_member_tb (conversation_id, user_id, role, joined_at)
            VALUES (?, ?, 'member', ?)
            """,
            (requested, direct_peer_id, now),
        )
    return requested


def public_sync_event(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(str(row["payload_json"] or "{}"))
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "schema": SYNC_EVENT_SCHEMA,
        "id": str(row["id"]),
        "client_event_id": str(row["client_event_id"]),
        "conversation_id": str(row["conversation_id"]),
        "space_id": str(row["space_id"]),
        "shared_space_id": str(row["shared_space_id"]),
        "author_user_id": str(row["author_user_id"]),
        "kind": str(row["kind"]),
        "payload": payload,
        "created_at": int(row["created_at"]),
        "updated_at": int(row["updated_at"]),
    }


def prune_remote_control_frame_events(conn: sqlite3.Connection, conversation_id: str) -> None:
    rows = conn.execute(
        """
        SELECT id FROM sync_event_tb
         WHERE conversation_id = ? AND kind = 'remote-control-frame'
         ORDER BY CAST(id AS INTEGER) DESC
         LIMIT -1 OFFSET ?
        """,
        (conversation_id, REMOTE_CONTROL_FRAME_EVENT_KEEP),
    ).fetchall()
    ids = [str(row["id"]) for row in rows]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    conn.execute(f"DELETE FROM sync_event_tb WHERE id IN ({placeholders})", ids)


def list_sync_events(server: WasmAgentServer, user: dict[str, Any] | None, query: dict[str, list[str]]) -> dict[str, Any]:
    conversation_id = safe_state_id(str((query.get("conversation_id") or query.get("conversation") or [""])[0] or ""), "")
    shared_space_id = safe_state_id(str((query.get("shared_space_id") or query.get("shared_space") or [""])[0] or ""), "")
    kind_filter = safe_state_id(str((query.get("kind") or query.get("event_kind") or [""])[0] or ""), "")
    latest = str((query.get("latest") or [""])[0] or "").strip().lower() in {"1", "true", "yes"}
    after_id = str((query.get("after_id") or query.get("after") or [""])[0] or "").strip()
    try:
        limit = int(str((query.get("limit") or [SYNC_EVENT_PAGE_LIMIT])[0] or SYNC_EVENT_PAGE_LIMIT))
    except ValueError:
        limit = SYNC_EVENT_PAGE_LIMIT
    limit = max(1, min(limit, SYNC_EVENT_PAGE_LIMIT))
    with auth_connect() as conn:
        params: list[Any] = []
        where = []
        if conversation_id:
            if not user_can_access_conversation(conn, conversation_id, user):
                raise BrowserError("conversation_denied", "You cannot access that conversation.", status=HTTPStatus.FORBIDDEN)
            where.append("conversation_id = ?")
            params.append(conversation_id)
        elif shared_space_id:
            record = read_shared_space_record(server, shared_space_id)
            if not record or not user_can_access_shared_space(record, user):
                raise BrowserError("shared_space_denied", "You cannot access that shared space.", status=HTTPStatus.FORBIDDEN)
            where.append("shared_space_id = ?")
            params.append(shared_space_id)
        else:
            where.append(
                "conversation_id IN (SELECT conversation_id FROM conversation_member_tb WHERE user_id = ?)"
            )
            params.append(user_id(user))
        if after_id:
            where.append("CAST(id AS INTEGER) > CAST(? AS INTEGER)")
            params.append(after_id)
        if kind_filter:
            where.append("kind = ?")
            params.append(kind_filter)
        order = "DESC" if latest else "ASC"
        sql = "SELECT * FROM sync_event_tb WHERE " + " AND ".join(where) + f" ORDER BY CAST(id AS INTEGER) {order} LIMIT ?"
        rows = conn.execute(sql, (*params, limit)).fetchall()
        if latest:
            rows = list(reversed(rows))
    events = [public_sync_event(row) for row in rows]
    return {
        "ok": True,
        "schema": SYNC_EVENT_LIST_SCHEMA,
        "events": events,
        "cursor": events[-1]["id"] if events else after_id,
    }


def append_sync_event(server: WasmAgentServer, user: dict[str, Any] | None, body: dict[str, Any]) -> dict[str, Any]:
    uid = user_id(user)
    client_event_id = safe_state_id(str(body.get("client_event_id") or ""), "")
    if not client_event_id:
        client_event_id = f"client-{next_snowflake_id():x}"
    kind = sync_event_kind(body.get("kind"))
    payload = normalize_sync_event_payload(user, kind, body.get("payload"))
    now = int(time.time())
    with auth_connect() as conn:
        conversation_id = ensure_sync_conversation(server, conn, user, body)
        ensure_direct_conversation_send_allowed(conn, conversation_id, user, kind)
        row = conn.execute(
            "SELECT * FROM sync_event_tb WHERE author_user_id = ? AND client_event_id = ?",
            (uid, client_event_id),
        ).fetchone()
        if not row:
            event_id = str(next_snowflake_id())
            conn.execute(
                """
                INSERT INTO sync_event_tb (
                  id, client_event_id, conversation_id, space_id, shared_space_id,
                  author_user_id, kind, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    client_event_id,
                    conversation_id,
                    safe_state_id(str(body.get("space_id") or body.get("space") or ""), ""),
                    safe_state_id(str(body.get("shared_space_id") or body.get("shared_space") or ""), ""),
                    uid,
                    kind,
                    sync_event_payload(payload, kind),
                    now,
                    now,
                ),
            )
            if kind == "remote-control-frame":
                prune_remote_control_frame_events(conn, conversation_id)
            row = conn.execute("SELECT * FROM sync_event_tb WHERE id = ?", (event_id,)).fetchone()
        event = public_sync_event(row) if row else {}
    return {"ok": True, "event": event}


def base36_int(value: str) -> str:
    try:
        number = int(value)
    except ValueError:
        number = 0
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if number <= 0:
        return "0"
    chars = []
    while number:
        number, rem = divmod(number, 36)
        chars.append(alphabet[rem])
    return "".join(reversed(chars))


def account_main_node_id(user: dict[str, Any] | None) -> str:
    return safe_state_id(f"u{base36_int(user_id(user))}", "account")


def legacy_account_main_node_id(user: dict[str, Any] | None) -> str:
    return safe_state_id(f"{account_main_node_id(user)}-main", "account-main")


def account_main_node_id_candidates(user: dict[str, Any] | None) -> list[str]:
    node_id = account_main_node_id(user)
    legacy = legacy_account_main_node_id(user)
    return [node_id, legacy] if legacy != node_id else [node_id]


def flux_main_node_provision_cost() -> int:
    raw = os.getenv("HERMES_WASM_AGENT_MAIN_NODE_FLUX_COST", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return FLUX_MAIN_NODE_PROVISION_COST


def flux_agent_harness_cost() -> int:
    raw = os.getenv("HERMES_WASM_AGENT_HARNESS_FLUX_COST", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return FLUX_AGENT_HARNESS_COST


def append_instance_audit(
    conn: sqlite3.Connection | None,
    *,
    actor_user_id: str,
    action: str,
    target: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "id": f"audit_{next_snowflake_id():x}",
        "actor_user_id": str(actor_user_id or ""),
        "action": clipped(str(action or ""), 160),
        "target": clipped(str(target or ""), 240),
        "created_at": int(time.time()),
        "metadata_json": json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True),
    }
    if conn is not None:
        conn.execute(
            """
            INSERT INTO instance_audit_tb (id, actor_user_id, action, target, created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["actor_user_id"],
                row["action"],
                row["target"],
                row["created_at"],
                row["metadata_json"],
            ),
        )
        return row
    with auth_connect() as audit_conn:
        append_instance_audit(
            audit_conn,
            actor_user_id=row["actor_user_id"],
            action=row["action"],
            target=row["target"],
            metadata=json.loads(row["metadata_json"]),
        )
    return row


def flux_balance(conn: sqlite3.Connection, uid: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS balance FROM flux_credit_ledger_tb WHERE user_id = ?",
        (str(uid),),
    ).fetchone()
    return int(row["balance"] or 0) if row else 0


def public_flux_ledger_row(row: sqlite3.Row) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    try:
        parsed = json.loads(str(row["metadata_json"] or "{}"))
        metadata = parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        metadata = {}
    return {
        "schema": FLUX_LEDGER_ROW_SCHEMA,
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "actor_user_id": str(row["actor_user_id"]),
        "amount": int(row["amount"]),
        "kind": str(row["kind"]),
        "reason": str(row["reason"]),
        "target": str(row["target"]),
        "created_at": int(row["created_at"]),
        "metadata": metadata,
    }


def account_credits(user: dict[str, Any] | None, *, limit: int = 25) -> dict[str, Any]:
    if not user:
        raise BrowserError("auth_required", "Account sign-in is required.", status=HTTPStatus.UNAUTHORIZED)
    uid = user_id(user)
    with auth_connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM flux_credit_ledger_tb
             WHERE user_id = ?
             ORDER BY created_at DESC, id DESC
             LIMIT ?
            """,
            (uid, max(1, min(int(limit), 100))),
        ).fetchall()
        balance = flux_balance(conn, uid)
    return {
        "ok": True,
        "schema": ACCOUNT_CREDITS_SCHEMA,
        "currency": "flux",
        "balance": balance,
        "provision_main_cost": flux_main_node_provision_cost(),
        "agent_harness_cost": flux_agent_harness_cost(),
        "ledger": [public_flux_ledger_row(row) for row in rows],
    }


def parse_positive_credit_amount(value: Any) -> int:
    if isinstance(value, bool):
        raise BrowserError("invalid_credit_amount", "Credit amount must be a positive integer.")
    try:
        amount = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise BrowserError("invalid_credit_amount", "Credit amount must be a positive integer.") from exc
    if amount <= 0:
        raise BrowserError("invalid_credit_amount", "Credit amount must be greater than zero.")
    return amount


def grant_flux_credits(
    actor: dict[str, Any] | None,
    target_user_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    actor_id = user_id(actor)
    target_id = str(target_user_id or "").strip()
    if not actor or not user_is_admin(actor):
        append_instance_audit(
            None,
            actor_user_id=actor_id,
            action="credits.grant.denied",
            target=f"user:{target_id}",
            metadata={"reason": "non_admin"},
        )
        raise BrowserError("admin_required", "Admin access is required.", status=HTTPStatus.FORBIDDEN)
    if not target_id.isdigit():
        append_instance_audit(
            None,
            actor_user_id=actor_id,
            action="credits.grant.denied",
            target=f"user:{target_id}",
            metadata={"reason": "invalid_target"},
        )
        raise BrowserError("invalid_credit_target", "Credit target user id is invalid.")
    if target_id == actor_id:
        append_instance_audit(
            None,
            actor_user_id=actor_id,
            action="credits.grant.denied",
            target=f"user:{target_id}",
            metadata={"reason": "self_grant"},
        )
        raise BrowserError("credit_self_grant_denied", "Admins cannot grant Flux credits to themselves.", status=HTTPStatus.FORBIDDEN)
    try:
        amount = parse_positive_credit_amount(body.get("amount"))
    except BrowserError as exc:
        append_instance_audit(
            None,
            actor_user_id=actor_id,
            action="credits.grant.denied",
            target=f"user:{target_id}",
            metadata={"reason": exc.code, "amount": body.get("amount")},
        )
        raise
    reason = clipped(str(body.get("reason") or "").strip(), 300)
    if not reason:
        append_instance_audit(
            None,
            actor_user_id=actor_id,
            action="credits.grant.denied",
            target=f"user:{target_id}",
            metadata={"reason": "missing_credit_reason", "amount": amount},
        )
        raise BrowserError("missing_credit_reason", "Credit grant reason is required.")
    idempotency_key = clipped(str(body.get("idempotency_key") or body.get("idempotencyKey") or "").strip(), 160)
    if not idempotency_key:
        append_instance_audit(
            None,
            actor_user_id=actor_id,
            action="credits.grant.denied",
            target=f"user:{target_id}",
            metadata={"reason": "missing_idempotency_key", "amount": amount},
        )
        raise BrowserError("missing_idempotency_key", "Credit grants require an idempotency key.")
    now = int(time.time())
    with auth_connect() as conn:
        target_row = lookup_user_row(conn, target_id)
        if not target_row:
            append_instance_audit(
                conn,
                actor_user_id=actor_id,
                action="credits.grant.denied",
                target=f"user:{target_id}",
                metadata={"reason": "target_missing", "amount": amount},
            )
            conn.commit()
            raise BrowserError("credit_target_not_found", "Credit target user was not found.", status=HTTPStatus.NOT_FOUND)
        if is_admin_email(str(target_row["email"])):
            append_instance_audit(
                conn,
                actor_user_id=actor_id,
                action="credits.grant.denied",
                target=f"user:{target_id}",
                metadata={"reason": "admin_target", "amount": amount},
            )
            conn.commit()
            raise BrowserError("credit_admin_target_denied", "Flux credits cannot be granted to admin accounts.", status=HTTPStatus.FORBIDDEN)
        duplicate = conn.execute(
            "SELECT * FROM flux_credit_ledger_tb WHERE kind = 'grant' AND idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if duplicate:
            append_instance_audit(
                conn,
                actor_user_id=actor_id,
                action="credits.grant.denied",
                target=f"user:{target_id}",
                metadata={"reason": "duplicate_idempotency_key", "amount": amount, "idempotency_key": idempotency_key},
            )
            conn.commit()
            raise BrowserError("duplicate_idempotency_key", "That Flux credit grant idempotency key was already used.", status=HTTPStatus.CONFLICT)
        ledger_id = f"flux_{next_snowflake_id():x}"
        conn.execute(
            """
            INSERT INTO flux_credit_ledger_tb (
              id, user_id, actor_user_id, amount, kind, reason, idempotency_key, target, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, 'grant', ?, ?, ?, ?, ?)
            """,
            (
                ledger_id,
                target_id,
                actor_id,
                amount,
                reason,
                idempotency_key,
                f"user:{target_id}",
                now,
                json.dumps({"granted_by_email": actor.get("email") or ""}, ensure_ascii=True, sort_keys=True),
            ),
        )
        append_instance_audit(
            conn,
            actor_user_id=actor_id,
            action="credits.grant",
            target=f"user:{target_id}",
            metadata={"amount": amount, "reason": reason, "idempotency_key": idempotency_key},
        )
        row = conn.execute("SELECT * FROM flux_credit_ledger_tb WHERE id = ?", (ledger_id,)).fetchone()
        balance = flux_balance(conn, target_id)
    return {
        "ok": True,
        "schema": ACCOUNT_CREDITS_SCHEMA,
        "currency": "flux",
        "balance": balance,
        "ledger_row": public_flux_ledger_row(row) if row else None,
    }


def parse_node_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = value[1:-1]
        values[key] = str(value)
    return values


def agents_root(server: WasmAgentServer) -> Path:
    raw = os.getenv("HERMES_AGENTS_ROOT", "").strip()
    return Path(raw).expanduser().resolve() if raw else (repo_root(server) / "agents").resolve()


def account_node_runtime_url_source(server: WasmAgentServer, node_id: str) -> tuple[str, str]:
    node = safe_state_id(node_id, "")
    if not node:
        return "", "missing_account_sandbox_url"
    env_node = node.upper().replace("-", "_")
    explicit_key = f"HERMES_WASM_AGENT_BRIDGE_API_SERVER_{env_node}_URL"
    explicit = os.getenv(explicit_key, "").strip()
    if explicit:
        return explicit.rstrip("/"), explicit_key
    env_path = agents_root(server) / "envs" / f"{node}.env"
    env = parse_node_env_file(env_path)
    port = str(env.get("API_SERVER_PORT") or "").strip()
    if port:
        host = str(env.get("API_SERVER_HOST") or "127.0.0.1").strip() or "127.0.0.1"
        return f"http://{host}:{port}".rstrip("/"), str(env_path)
    return "", "missing_account_sandbox_url"


def resolve_account_main_node_id(server: WasmAgentServer, user: dict[str, Any] | None) -> str:
    node_id = account_main_node_id(user)
    legacy = legacy_account_main_node_id(user)
    if legacy == node_id:
        return node_id
    env_root = agents_root(server) / "envs"
    node_env = env_root / f"{node_id}.env"
    legacy_env = env_root / f"{legacy}.env"
    if not node_env.exists() and legacy_env.exists():
        return legacy
    with auth_connect() as conn:
        legacy_row = conn.execute(
            "SELECT 1 FROM user_fleet_tb WHERE user_id = ? AND node_id = ? LIMIT 1",
            (user_id(user), legacy),
        ).fetchone()
        node_row = conn.execute(
            "SELECT 1 FROM user_fleet_tb WHERE user_id = ? AND node_id = ? LIMIT 1",
            (user_id(user), node_id),
        ).fetchone()
    if legacy_row and not node_row:
        return legacy
    return node_id


def onboarding_options_for_readiness(user: dict[str, Any] | None, status: str) -> list[dict[str, Any]]:
    if user_is_admin(user) or status == AGENT_READINESS_READY:
        return []
    return [
        {
            "id": "direct_provider_key",
            "label": "Use my API key",
            "scope": "browser-only",
            "stores": "client_state",
            "backend_tools": False,
        },
        {
            "id": "flux_credits",
            "label": "Use Flux credits",
            "endpoint": "/agent/harnesses/provision",
            "cost": flux_agent_harness_cost(),
            "provider": FLUX_MAIN_NODE_PROVIDER,
            "model": FLUX_MAIN_NODE_MODEL,
        },
    ]


def readiness_payload(
    *,
    user: dict[str, Any] | None,
    requested_target_node: str,
    target_node: str,
    resolved_account_node: str,
    status: str,
    bridge_url_source: str,
    message: str,
    missing_dependency: str = "",
    bridge_url: str = "",
    account_sandbox_url: str = "",
    backend: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "schema": AGENT_READINESS_SCHEMA,
        "status": status,
        "ready": status == AGENT_READINESS_READY,
        "target_node": target_node,
        "requested_target_node": requested_target_node,
        "resolved_account_node": resolved_account_node,
        "bridge_url_source": bridge_url_source,
        "bridge_url": bridge_url,
        "account_sandbox_url": account_sandbox_url,
        "message": message,
        "missing_dependency": missing_dependency,
        "backend": backend or {},
        "onboarding_options": onboarding_options_for_readiness(user, status),
    }


def bridge_health_probe(server: WasmAgentServer) -> dict[str, Any]:
    payload = bridge_proxy(server, "GET", "/health", None)
    health = payload.get("health") if isinstance(payload.get("health"), dict) else payload
    return health if isinstance(health, dict) else {}


def bridge_node_probe(server: WasmAgentServer, node_id: str) -> dict[str, Any]:
    payload = bridge_proxy(server, "GET", f"/nodes/{quote(node_id, safe='')}", None)
    node = payload.get("node") if isinstance(payload.get("node"), dict) else payload.get("result")
    return node if isinstance(node, dict) else {}


def readiness_node_running(node: dict[str, Any]) -> bool:
    return bool(node.get("running")) or str(node.get("status") or "").lower() in {"running", "ok", "ready"}


def live_account_sandbox_snapshot(server: WasmAgentServer, node_id: str) -> dict[str, Any]:
    runtime_url, runtime_source = account_node_runtime_url_source(server, node_id)
    try:
        health = bridge_health_probe(server)
        node = bridge_node_probe(server, node_id)
    except BrowserError:
        return {}
    if not readiness_node_running(node):
        return {}
    return {
        "runtime_url": runtime_url,
        "runtime_source": runtime_source,
        "health": health,
        "node": node,
    }


def wait_for_live_account_sandbox(
    server: WasmAgentServer,
    node_id: str,
    *,
    timeout_sec: float = 30,
    interval_sec: float = 2,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout_sec)
    while True:
        snapshot = live_account_sandbox_snapshot(server, node_id)
        if snapshot:
            return snapshot
        if time.monotonic() >= deadline:
            return {}
        time.sleep(max(0.1, interval_sec))


def should_probe_late_sandbox_after_create_error(exc: Exception) -> bool:
    return isinstance(exc, BrowserError) and exc.code in {"bridge_timeout", "bridge_http_error"}


def account_sandbox_bridge_result(node_id: str, snapshot: dict[str, Any], *, source: str, recovered_after: str = "") -> dict[str, Any]:
    result = {
        "ok": True,
        "node_create": {
            "node_id": node_id,
            "already_running": True,
            "source": source,
        },
        "node": snapshot.get("node") or {},
    }
    if recovered_after:
        result["node_create"]["recovered_after"] = recovered_after
    return result


def account_sandbox_paid_binding(user: dict[str, Any] | None, node_id: str) -> dict[str, Any]:
    uid = user_id(user)
    target = f"node:{node_id}"
    with auth_connect() as conn:
        main = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
              FROM flux_credit_ledger_tb
             WHERE user_id = ? AND kind = 'provision' AND target = ?
            """,
            (uid, target),
        ).fetchone()
        main_total = int(main["total"] or 0) if main else 0
        if main_total < 0:
            return {"paid": True, "source": "main_provision", "net": main_total}
        rows = conn.execute(
            """
            SELECT * FROM agent_harness_tb
             WHERE user_id = ? AND node_id = ? AND lifecycle_state = 'ready'
             ORDER BY created_at DESC, id DESC
            """,
            (uid, node_id),
        ).fetchall()
        for row in rows:
            harness_id = str(row["id"])
            ledger = conn.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                  FROM flux_credit_ledger_tb
                 WHERE user_id = ?
                   AND (
                     (kind = 'harness_provision' AND target = ?)
                     OR (kind = 'refund' AND idempotency_key = ?)
                   )
                """,
                (uid, f"harness:{harness_id}", f"refund:{harness_id}"),
            ).fetchone()
            harness_total = int(ledger["total"] or 0) if ledger else 0
            if harness_total < 0:
                return {"paid": True, "source": "agent_harness", "net": harness_total, "harness": public_agent_harness(row)}
    return {"paid": False, "source": "none", "net": 0}


def latest_user_harness_for_node(user: dict[str, Any] | None, node_id: str) -> dict[str, Any]:
    uid = user_id(user)
    with auth_connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM agent_harness_tb
             WHERE user_id = ? AND (node_id = ? OR node_id = '')
             ORDER BY created_at DESC, id DESC
             LIMIT 1
            """,
            (uid, node_id),
        ).fetchone()
    if not row:
        return {}
    try:
        capabilities = json.loads(str(row["capabilities_json"] or "{}"))
        if not isinstance(capabilities, dict):
            capabilities = {}
    except Exception:
        capabilities = {}
    return {
        "id": str(row["id"]),
        "lifecycle_state": str(row["lifecycle_state"]),
        "failure_reason": str(row["failure_reason"]),
        "infra_mode": str(row["infra_mode"]),
        "bridge_url": str(row["bridge_url"]),
        "capabilities": capabilities,
    }


def readiness_from_harness_lifecycle(
    *,
    user: dict[str, Any] | None,
    requested_target_node: str,
    target_node: str,
    bridge_url_source: str,
    bridge_url: str,
    harness: dict[str, Any],
) -> dict[str, Any] | None:
    state = str(harness.get("lifecycle_state") or "")
    if state not in AGENT_HARNESS_LIFECYCLE_STATES or state == "ready":
        return None
    if state in {"requested", "charging", "provisioning"}:
        message = "Provisioning sandbox..."
    elif state == "failed":
        message = "Provisioning failed"
    elif state == "stopped":
        message = "Sandbox stopped"
    else:
        message = "Sandbox archived"
    return readiness_payload(
        user=user,
        requested_target_node=requested_target_node,
        target_node=target_node,
        resolved_account_node=target_node,
        status=state,
        bridge_url_source=bridge_url_source,
        bridge_url=bridge_url,
        message=message,
        missing_dependency=f"account_sandbox_{state}",
        backend={"harness": harness},
    )


def agent_readiness(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    *,
    target_node: str = "",
) -> dict[str, Any]:
    if not user:
        raise BrowserError("auth_required", "Account sign-in is required.", status=HTTPStatus.UNAUTHORIZED)
    requested = safe_state_id(str(target_node or default_agent_target_node(user)), default_agent_target_node(user))
    ensure_agent_target_allowed(user, requested)
    if user_is_admin(user):
        try:
            health = bridge_health_probe(server)
        except BrowserError as exc:
            return readiness_payload(
                user=user,
                requested_target_node=requested,
                target_node=requested,
                resolved_account_node="",
                status=AGENT_READINESS_BACKEND_UNAVAILABLE,
                bridge_url_source="global_bridge_url",
                bridge_url=server.bridge_url,
                message=f"Agent backend unavailable: {exc.message}",
                missing_dependency="wasm_agent_bridge",
                backend={"error": exc.code, "detail": exc.message},
            )
        try:
            node = bridge_node_probe(server, requested)
        except BrowserError as exc:
            return readiness_payload(
                user=user,
                requested_target_node=requested,
                target_node=requested,
                resolved_account_node="",
                status=AGENT_READINESS_BACKEND_UNAVAILABLE,
                bridge_url_source="global_bridge_url",
                bridge_url=server.bridge_url,
                message=f"Agent backend unavailable: selected node `{requested}` could not be inspected.",
                missing_dependency="selected_node",
                backend={"bridge": health, "error": exc.code, "detail": exc.message},
            )
        if not readiness_node_running(node):
            return readiness_payload(
                user=user,
                requested_target_node=requested,
                target_node=requested,
                resolved_account_node="",
                status=AGENT_READINESS_BACKEND_UNAVAILABLE,
                bridge_url_source="global_bridge_url",
                bridge_url=server.bridge_url,
                message=f"Agent backend unavailable: selected node `{requested}` is not running.",
                missing_dependency="selected_node_not_running",
                backend={"bridge": health, "node": node},
            )
        return readiness_payload(
            user=user,
            requested_target_node=requested,
            target_node=requested,
            resolved_account_node="",
            status=AGENT_READINESS_READY,
            bridge_url_source="global_bridge_url",
            bridge_url=server.bridge_url,
            message="Agent ready",
            backend={"bridge": health, "node": node},
        )

    account_node = resolve_account_main_node_id(server, user)
    lifecycle = latest_user_harness_for_node(user, account_node)
    runtime_url, runtime_source = account_node_runtime_url_source(server, account_node)
    env_path = agents_root(server) / "envs" / f"{account_node}.env"
    lifecycle_readiness = readiness_from_harness_lifecycle(
        user=user,
        requested_target_node=requested,
        target_node=account_node,
        bridge_url_source=runtime_source,
        bridge_url=server.bridge_url,
        harness=lifecycle,
    )
    if lifecycle_readiness:
        if lifecycle.get("lifecycle_state") == "failed":
            live_sandbox = live_account_sandbox_snapshot(server, account_node)
            billing = account_sandbox_paid_binding(user, account_node) if live_sandbox else {"paid": False, "source": "none"}
            if live_sandbox and not billing.get("paid"):
                return readiness_payload(
                    user=user,
                    requested_target_node=requested,
                    target_node=account_node,
                    resolved_account_node=account_node,
                    status=AGENT_READINESS_SANDBOX_BILLING_INCOMPLETE,
                    bridge_url_source=runtime_source,
                    bridge_url=server.bridge_url,
                    account_sandbox_url=runtime_url,
                    message="Sandbox exists, but the previous provisioning charge was refunded before harness binding completed.",
                    missing_dependency="account_sandbox_billing",
                    backend={"node": live_sandbox.get("node") or {}, "billing": billing, "harness": lifecycle},
        )
        return lifecycle_readiness
    if not runtime_url and not env_path.exists():
        return readiness_payload(
            user=user,
            requested_target_node=requested,
            target_node=account_node,
            resolved_account_node=account_node,
            status=AGENT_READINESS_SANDBOX_NOT_PROVISIONED,
            bridge_url_source=runtime_source,
            bridge_url=server.bridge_url,
            message="Sandbox not provisioned.",
            missing_dependency="account_sandbox_api_url",
        )
    try:
        health = bridge_health_probe(server)
    except BrowserError as exc:
        return readiness_payload(
            user=user,
            requested_target_node=requested,
            target_node=account_node,
            resolved_account_node=account_node,
            status=AGENT_READINESS_BACKEND_UNAVAILABLE,
            bridge_url_source=runtime_source,
            bridge_url=server.bridge_url,
            account_sandbox_url=runtime_url,
            message=f"Agent backend unavailable: {exc.message}",
            missing_dependency="wasm_agent_bridge",
            backend={"error": exc.code, "detail": exc.message},
        )
    try:
        node = bridge_node_probe(server, account_node)
    except BrowserError as exc:
        return readiness_payload(
            user=user,
            requested_target_node=requested,
            target_node=account_node,
            resolved_account_node=account_node,
            status=AGENT_READINESS_SANDBOX_NOT_PROVISIONED,
            bridge_url_source=runtime_source,
            bridge_url=server.bridge_url,
            account_sandbox_url=runtime_url,
            message="Sandbox not provisioned.",
            missing_dependency="account_sandbox_node",
            backend={"bridge": health, "error": exc.code, "detail": exc.message},
        )
    if not readiness_node_running(node):
        stopped_status = "stopped" if lifecycle.get("lifecycle_state") == "ready" else AGENT_READINESS_SANDBOX_NOT_PROVISIONED
        return readiness_payload(
            user=user,
            requested_target_node=requested,
            target_node=account_node,
            resolved_account_node=account_node,
            status=stopped_status,
            bridge_url_source=runtime_source,
            bridge_url=server.bridge_url,
            account_sandbox_url=runtime_url,
            message="Sandbox stopped" if stopped_status == "stopped" else "Sandbox not provisioned.",
            missing_dependency="account_sandbox_node_running",
            backend={"bridge": health, "node": node},
        )
    billing = account_sandbox_paid_binding(user, account_node)
    if not billing.get("paid"):
        return readiness_payload(
            user=user,
            requested_target_node=requested,
            target_node=account_node,
            resolved_account_node=account_node,
            status=AGENT_READINESS_SANDBOX_BILLING_INCOMPLETE,
            bridge_url_source=runtime_source,
            bridge_url=server.bridge_url,
            account_sandbox_url=runtime_url,
            message="Sandbox exists, but billing and harness binding did not complete.",
            missing_dependency="account_sandbox_billing",
            backend={"bridge": health, "node": node, "billing": billing},
        )
    return readiness_payload(
        user=user,
        requested_target_node=requested,
        target_node=account_node,
        resolved_account_node=account_node,
        status=AGENT_READINESS_READY,
        bridge_url_source=runtime_source,
        bridge_url=server.bridge_url,
        account_sandbox_url=runtime_url,
        message="Agent ready",
        backend={"bridge": health, "node": node},
    )


def public_fleet_node(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema": USER_FLEET_NODE_SCHEMA,
        "node_id": str(row["node_id"]),
        "role": str(row["role"]),
        "main": bool(row["is_main"]),
        "classification": "system" if bool(row["is_main"]) or str(row["role"]) == "owner" else "user_agent",
        "created_at": int(row["created_at"]),
        "updated_at": int(row["updated_at"]),
        "backend": "hermes-node",
    }


def provider_or_model_fleet_node_id(raw: str) -> bool:
    value = str(raw or "").strip().lower()
    safe = safe_state_id(value, "")
    provider_names = {"openrouter", "opencode-go", "opencode-zen", "openai", "nvidia", "minimax"}
    if value.startswith(("model:", "provider:", "agent:model:", "agent:provider:")):
        return True
    if value.startswith("agent:") and any(value.startswith(f"agent:{provider}:") for provider in provider_names):
        return True
    return (
        safe.startswith(("model-", "provider-", "agent-model-", "agent-provider-"))
        or any(safe.startswith(f"agent-{provider}-") for provider in provider_names)
    )


def validate_main_fleet_node_id(user: dict[str, Any] | None, raw_node_id: Any) -> str:
    requested_raw = str(raw_node_id or "").strip()
    node_id = safe_state_id(requested_raw, "") if requested_raw else account_main_node_id(user)
    expected = account_main_node_id(user)
    allowed = set(account_main_node_id_candidates(user))
    if requested_raw and (provider_or_model_fleet_node_id(requested_raw) or node_id not in allowed):
        raise BrowserError(
            "fleet_node_denied",
            "Fleet main-node metadata only accepts the authenticated user's deterministic system node; provider/model selections stay outside the fleet registry.",
            status=HTTPStatus.FORBIDDEN,
        )
    return node_id if requested_raw else expected


def list_user_fleet(user: dict[str, Any] | None) -> dict[str, Any]:
    uid = user_id(user)
    main_node_ids = set(account_main_node_id_candidates(user))
    with auth_connect() as conn:
        rows = conn.execute(
            "SELECT * FROM user_fleet_tb WHERE user_id = ? ORDER BY is_main DESC, created_at ASC",
            (uid,),
        ).fetchall()
        harness_rows = conn.execute(
            """
            SELECT * FROM agent_harness_tb
             WHERE user_id = ? AND lifecycle_state != 'archived'
             ORDER BY created_at DESC, id DESC
            """,
            (uid,),
        ).fetchall()
    public_nodes = [public_fleet_node(row) for row in rows if not provider_or_model_fleet_node_id(str(row["node_id"]))]
    system_nodes = [node for node in public_nodes if node["node_id"] in main_node_ids or node["main"] or node["role"] == "owner"]
    user_nodes = [node for node in public_nodes if node not in system_nodes]
    return {
        "ok": True,
        "schema": USER_FLEET_SCHEMA,
        "deployment_mode": wasm_agent_deployment_mode(),
        "nodes": user_nodes,
        "system_nodes": system_nodes,
        "harnesses": [public_agent_harness(row) for row in harness_rows],
        "direct_provider_scope": "browser-local",
        "server_policy": "server stores ownership metadata only until backend execution is explicitly requested",
    }


def ensure_main_fleet_node(user: dict[str, Any] | None, body: dict[str, Any]) -> dict[str, Any]:
    uid = user_id(user)
    node_id = validate_main_fleet_node_id(user, body.get("node_id"))
    now = int(time.time())
    with auth_connect() as conn:
        conn.execute("UPDATE user_fleet_tb SET is_main = 0, updated_at = ? WHERE user_id = ?", (now, uid))
        conn.execute(
            """
            INSERT INTO user_fleet_tb (user_id, node_id, role, is_main, created_at, updated_at)
            VALUES (?, ?, 'owner', 1, ?, ?)
            ON CONFLICT(user_id, node_id) DO UPDATE SET is_main = 1, updated_at = excluded.updated_at
            """,
            (uid, node_id, now, now),
        )
        row = conn.execute("SELECT * FROM user_fleet_tb WHERE user_id = ? AND node_id = ?", (uid, node_id)).fetchone()
        node = public_fleet_node(row) if row else {}
    return {
        "ok": True,
        "node": node,
        "provisioned": False,
        "note": "Reserved owned Hermes node metadata; backend provisioning is an explicit premium/heavy action.",
    }


def ensure_main_fleet_node_in_conn(conn: sqlite3.Connection, user: dict[str, Any] | None, node_id: str) -> dict[str, Any]:
    uid = user_id(user)
    node_id = validate_main_fleet_node_id(user, node_id)
    now = int(time.time())
    conn.execute("UPDATE user_fleet_tb SET is_main = 0, updated_at = ? WHERE user_id = ?", (now, uid))
    conn.execute(
        """
        INSERT INTO user_fleet_tb (user_id, node_id, role, is_main, created_at, updated_at)
        VALUES (?, ?, 'owner', 1, ?, ?)
        ON CONFLICT(user_id, node_id) DO UPDATE SET is_main = 1, updated_at = excluded.updated_at
        """,
        (uid, node_id, now, now),
    )
    row = conn.execute("SELECT * FROM user_fleet_tb WHERE user_id = ? AND node_id = ?", (uid, node_id)).fetchone()
    return public_fleet_node(row) if row else {}


def validate_provision_main_body(user: dict[str, Any] | None, body: dict[str, Any], node_id: str) -> None:
    denied_node = str(body.get("node_id") or body.get("node") or body.get("name") or body.get("target_node") or "").strip()
    if denied_node and safe_state_id(denied_node, "") != node_id:
        raise BrowserError("provision_node_denied", "Provisioning only supports the authenticated user's deterministic main node.", status=HTTPStatus.FORBIDDEN)
    denied_provider = str(body.get("provider") or body.get("default_model_provider") or "").strip()
    if denied_provider and denied_provider != FLUX_MAIN_NODE_PROVIDER:
        raise BrowserError("provision_provider_denied", "Provisioning uses the fixed DeepSeek v4 Flash premium provider.", status=HTTPStatus.FORBIDDEN)
    denied_model = str(body.get("model") or body.get("default_model") or "").strip()
    if denied_model and denied_model != FLUX_MAIN_NODE_MODEL:
        raise BrowserError("provision_model_denied", "Provisioning uses the fixed DeepSeek v4 Flash premium model.", status=HTTPStatus.FORBIDDEN)
    agent_type = str(body.get("agent_type") or body.get("type") or "hermes").strip().lower()
    if agent_type and agent_type != "hermes":
        raise BrowserError("provision_agent_type_denied", "Only Hermes service agents are available right now.", status=HTTPStatus.FORBIDDEN)


def provider_api_key_env_name(provider: str) -> str:
    clean = str(provider or "").strip().lower()
    if clean == "openrouter":
        return "OPENROUTER_API_KEY"
    if clean == "opencode-go":
        return "OPENCODE_GO_API_KEY"
    if clean == "opencode-zen":
        return "OPENCODE_ZEN_API_KEY"
    if clean == "nvidia":
        return "NVIDIA_API_KEY"
    if clean in {"minimax", "minimax-cn"}:
        return "MINIMAX_API_KEY"
    return "OPENAI_API_KEY"


def provision_main_bridge_payload(
    node_id: str,
    body: dict[str, Any] | None = None,
    provider_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    provider_config = provider_config if isinstance(provider_config, dict) else {}
    default_provider = str(provider_config.get("provider") or FLUX_MAIN_NODE_PROVIDER).strip() or FLUX_MAIN_NODE_PROVIDER
    default_model = str(provider_config.get("model") or FLUX_MAIN_NODE_MODEL).strip() or FLUX_MAIN_NODE_MODEL
    api_key = str(provider_config.get("api_key") or "").strip()
    agent_name = str(body.get("agent_name") or body.get("agentName") or "My agent").strip()[:80] or "My agent"
    agent_role = str(body.get("agent_role") or body.get("instructions") or body.get("role") or "").strip()[:2000]
    role_suffix = f"\n\nAgent name: {agent_name}."
    if agent_role:
        role_suffix += f"\nInstructions: {agent_role}"
    payload = {
        "node_id": node_id,
        "node_state": "4",
        "default_model_provider": default_provider,
        "default_model": default_model,
        "start_immediately": True,
        "personality": (
            "You are this account's bounded Hermes sandbox. Stay inside the authenticated user's "
            "workspace and do not mutate wasm-agent core firmware unless an admin-orchestrator path explicitly delegates it."
            f"{role_suffix}"
        ),
    }
    if api_key:
        payload[provider_api_key_env_name(default_provider)] = api_key
    base_url = str(provider_config.get("base_url") or "").strip()
    if base_url:
        payload["OPENAI_BASE_URL"] = base_url
    return payload


def normalize_harness_infra_mode(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"", "hermes", "hermes_backend", "hermes_infra", "backend", "backend_infra", "our", "our_infra"}:
        return "hermes_backend"
    if raw in {"custom", "custom_bridge", "bridge", "own", "own_bridge", "own_infra"}:
        return "custom_bridge"
    if raw in {"browser", "browser_direct", "direct", "direct_provider", "provider", "claude", "anthropic", "other"}:
        raise BrowserError("provider_not_available", "Infrastructure option not available yet.", status=HTTPStatus.BAD_REQUEST)
    raise BrowserError("invalid_infra_mode", "Node infrastructure mode is not supported.")


def normalize_harness_type(value: Any) -> str:
    raw = str(value or AGENT_HARNESS_TYPE).strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"", "agent", "hermes"}:
        return AGENT_HARNESS_TYPE
    if raw in {"openclaw", "kilo_code", "kilocode", "claude_code", "pi", "other"}:
        raise BrowserError("provider_not_available", "Agent not available yet.", status=HTTPStatus.BAD_REQUEST)
    raise BrowserError("provider_not_available", "Agent not available yet.", status=HTTPStatus.BAD_REQUEST)


def normalize_custom_bridge_url(value: Any) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception as exc:
        raise BrowserError("invalid_bridge_url", "Private bridge URL must be a valid HTTP or HTTPS URL.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or any(char.isspace() for char in raw):
        raise BrowserError("invalid_bridge_url", "Private bridge URL must be a valid HTTP or HTTPS URL.")
    if parsed.username or parsed.password:
        raise BrowserError("invalid_bridge_url", "Private bridge URL must not contain credentials.")
    return parsed._replace(query="", fragment="").geturl().rstrip("/")


def bridge_join_url(base_url: str, path: str) -> str:
    base = normalize_custom_bridge_url(base_url)
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}{suffix}"


def custom_bridge_get_json(base_url: str, path: str, *, timeout: float = 8.0) -> dict[str, Any]:
    request = Request(
        bridge_join_url(base_url, path),
        headers={"Accept": "application/json", "User-Agent": f"{PLUGIN_NAME}/{PLUGIN_VERSION} custom-bridge-probe"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        raise BrowserError("custom_bridge_unavailable", detail or f"Custom bridge returned HTTP {int(exc.code)}.", status=HTTPStatus.BAD_GATEWAY) from exc
    except URLError as exc:
        raise BrowserError("custom_bridge_unavailable", str(exc.reason), status=HTTPStatus.BAD_GATEWAY) from exc
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise BrowserError("custom_bridge_unavailable", "Custom bridge returned non-JSON health data.", status=HTTPStatus.BAD_GATEWAY) from exc
    return payload if isinstance(payload, dict) else {"result": payload}


def probe_custom_bridge_url(base_url: str) -> dict[str, Any]:
    health = custom_bridge_get_json(base_url, "/health")
    models: dict[str, Any] = {}
    models_route = ""
    last_error = ""
    for route in ("/bridge/v1/models", "/v1/models"):
        try:
            models = custom_bridge_get_json(base_url, route)
            models_route = route
            break
        except BrowserError as exc:
            last_error = exc.message
    if not models_route:
        raise BrowserError("custom_bridge_unavailable", last_error or "Custom bridge model route is unavailable.", status=HTTPStatus.BAD_GATEWAY)
    return {
        "health": health,
        "models": compact_json(models, 1200),
        "routes": {
            "health": "/health",
            "models": models_route,
            "chat": ["/bridge/v1/chat", "/tasks", "/v1/runs", "/v1/chat/completions"],
        },
    }


def validate_agent_harness_body(user: dict[str, Any] | None, body: dict[str, Any]) -> dict[str, Any]:
    if not user:
        raise BrowserError("auth_required", "Account sign-in is required.", status=HTTPStatus.UNAUTHORIZED)
    if user_is_admin(user):
        raise BrowserError("admin_provision_denied", "Admin accounts do not self-provision paid account sandboxes.", status=HTTPStatus.FORBIDDEN)
    name = clipped(str(body.get("harness_name") or body.get("harnessName") or body.get("agent_name") or body.get("name") or "").strip(), 80)
    if not name:
        raise BrowserError("missing_harness_name", "Agent harness name is required.")
    harness_type = normalize_harness_type(body.get("harness_type") or body.get("harnessType") or body.get("type") or AGENT_HARNESS_TYPE)
    infra_mode = normalize_harness_infra_mode(body.get("infra_mode") or body.get("infraMode") or body.get("provider") or "")
    bridge_url = normalize_custom_bridge_url(body.get("bridge_url") or body.get("bridgeUrl") or "")
    if infra_mode == "custom_bridge" and not bridge_url:
        raise BrowserError("missing_bridge_url", "Private bridge URL is required.")
    return {
        "harness_id": safe_state_id(f"harness-{next_snowflake_id():x}", "harness"),
        "harness_name": name,
        "harness_type": harness_type,
        "infra_mode": infra_mode,
        "instructions": clipped(str(body.get("instructions") or body.get("harness_instructions") or body.get("role") or "").strip(), 2000),
        "node_name": clipped(str(body.get("node_name") or body.get("nodeName") or "").strip(), 80),
        "bridge_url": bridge_url,
    }


def public_agent_harness(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    def parsed_json(key: str) -> dict[str, Any]:
        try:
            parsed = json.loads(str(row[key] or "{}"))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    metadata = parsed_json("metadata_json")
    return {
        "schema": AGENT_HARNESS_SCHEMA,
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "node_id": str(row["node_id"]),
        "node_name": str(row["node_name"]),
        "harness_name": str(row["harness_name"]),
        "harness_type": str(row["harness_type"]),
        "infra_mode": str(row["infra_mode"]),
        "lifecycle_state": str(row["lifecycle_state"]),
        "bridge_url": str(row["bridge_url"]),
        "capabilities": parsed_json("capabilities_json"),
        "failure_reason": str(row["failure_reason"]),
        "quota": parsed_json("quota_json"),
        "cleanup_after_at": int(row["cleanup_after_at"] or 0),
        "created_at": int(row["created_at"]),
        "updated_at": int(row["updated_at"]),
        "instructions": str(metadata.get("instructions") or ""),
        "metadata": metadata,
    }


def set_agent_harness_state(
    conn: sqlite3.Connection,
    harness_id: str,
    state: str,
    *,
    bridge_url: str = "",
    capabilities: dict[str, Any] | None = None,
    failure_reason: str = "",
) -> None:
    if state not in AGENT_HARNESS_LIFECYCLE_STATES:
        raise BrowserError("invalid_harness_state", "Harness lifecycle state is invalid.")
    conn.execute(
        """
        UPDATE agent_harness_tb
           SET lifecycle_state = ?,
               bridge_url = COALESCE(NULLIF(?, ''), bridge_url),
               capabilities_json = ?,
               failure_reason = ?,
               updated_at = ?
         WHERE id = ?
        """,
        (
            state,
            bridge_url,
            json.dumps(capabilities or {}, ensure_ascii=True, sort_keys=True),
            clipped(failure_reason, 600),
            int(time.time()),
            harness_id,
        ),
    )


def write_harness_row_in_conn(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    config: dict[str, Any],
    *,
    node_id: str,
    lifecycle_state: str,
    bridge_url: str = "",
    capabilities: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = int(time.time())
    cleanup_after = now + 30 * 24 * 60 * 60
    quota = {"max_flux_debit": flux_agent_harness_cost(), "cleanup_after_days": 30, "recovery_visible": True}
    stored_metadata = dict(metadata or {})
    if config.get("instructions"):
        stored_metadata["instructions"] = clipped(str(config.get("instructions") or ""), 2000)
    conn.execute(
        """
        INSERT INTO agent_harness_tb (
          id, user_id, node_id, node_name, harness_name, harness_type, infra_mode,
          lifecycle_state, bridge_url, capabilities_json, failure_reason, quota_json,
          cleanup_after_at, created_at, updated_at, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          node_id = excluded.node_id,
          node_name = excluded.node_name,
          harness_name = excluded.harness_name,
          harness_type = excluded.harness_type,
          infra_mode = excluded.infra_mode,
          lifecycle_state = excluded.lifecycle_state,
          bridge_url = excluded.bridge_url,
          capabilities_json = excluded.capabilities_json,
          failure_reason = '',
          quota_json = excluded.quota_json,
          cleanup_after_at = excluded.cleanup_after_at,
          updated_at = excluded.updated_at,
          metadata_json = excluded.metadata_json
        """,
        (
            config["harness_id"],
            user_id(user),
            node_id,
            config["node_name"],
            config["harness_name"],
            config["harness_type"],
            config["infra_mode"],
            lifecycle_state,
            bridge_url,
            json.dumps(capabilities or {}, ensure_ascii=True, sort_keys=True),
            json.dumps(quota, ensure_ascii=True, sort_keys=True),
            cleanup_after,
            now,
            now,
            json.dumps(stored_metadata, ensure_ascii=True, sort_keys=True),
        ),
    )
    row = conn.execute("SELECT * FROM agent_harness_tb WHERE id = ?", (config["harness_id"],)).fetchone()
    return public_agent_harness(row)


def refund_agent_harness_charge(user: dict[str, Any], harness_id: str, node_id: str, cost: int, reason: str) -> None:
    uid = user_id(user)
    with auth_connect() as conn:
        existing = conn.execute(
            "SELECT id FROM flux_credit_ledger_tb WHERE kind = 'refund' AND idempotency_key = ?",
            (f"refund:{harness_id}",),
        ).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT INTO flux_credit_ledger_tb (
                  id, user_id, actor_user_id, amount, kind, reason, idempotency_key, target, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, 'refund', ?, ?, ?, ?, ?)
                """,
                (
                    f"flux_{next_snowflake_id():x}",
                    uid,
                    uid,
                    cost,
                    f"Refund failed harness {harness_id}",
                    f"refund:{harness_id}",
                    f"node:{node_id}",
                    int(time.time()),
                    json.dumps({"failure_reason": clipped(reason, 600), "harness_id": harness_id}, ensure_ascii=True, sort_keys=True),
                ),
            )
        set_agent_harness_state(conn, harness_id, "failed", failure_reason=reason)
        append_instance_audit(
            conn,
            actor_user_id=uid,
            action="agent_harness.refund",
            target=f"harness:{harness_id}",
            metadata={"cost": cost, "node_id": node_id, "reason": clipped(reason, 600)},
        )


def provision_agent_harness_node(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    body: dict[str, Any],
) -> dict[str, Any]:
    config = validate_agent_harness_body(user, body)
    assert user is not None
    uid = user_id(user)
    node_id = account_main_node_id(user)
    if config["infra_mode"] == "custom_bridge":
        with auth_connect() as conn:
            harness = write_harness_row_in_conn(
                conn,
                user,
                config,
                node_id="",
                lifecycle_state="requested",
                bridge_url=config["bridge_url"],
                capabilities={"mode": "custom_bridge"},
            )
            append_instance_audit(conn, actor_user_id=uid, action="agent_harness.custom_bridge.requested", target=f"harness:{config['harness_id']}", metadata={"bridge_host": urlparse(config["bridge_url"]).netloc})
        try:
            capabilities = probe_custom_bridge_url(config["bridge_url"])
        except BrowserError as exc:
            with auth_connect() as conn:
                set_agent_harness_state(conn, config["harness_id"], "failed", failure_reason=exc.message)
            raise
        with auth_connect() as conn:
            set_agent_harness_state(conn, config["harness_id"], "ready", bridge_url=config["bridge_url"], capabilities=capabilities)
            row = conn.execute("SELECT * FROM agent_harness_tb WHERE id = ?", (config["harness_id"],)).fetchone()
            append_instance_audit(conn, actor_user_id=uid, action="agent_harness.custom_bridge.ready", target=f"harness:{config['harness_id']}", metadata={"routes": capabilities.get("routes", {})})
            harness = public_agent_harness(row)
        return {
            "ok": True,
            "schema": AGENT_HARNESS_PROVISION_SCHEMA,
            "charged": False,
            "cost": 0,
            "lifecycle_state": "ready",
            "harness": harness,
            "credits": account_credits(user),
        }

    cost = flux_agent_harness_cost()
    idempotency_key = clipped(str(body.get("idempotency_key") or body.get("idempotencyKey") or "").strip(), 160)
    bridge_body = {
        **body,
        "agent_name": config["harness_name"],
        "agent_role": config["instructions"],
        "agent_type": "hermes",
    }
    with auth_connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if idempotency_key:
            duplicate = conn.execute(
                "SELECT * FROM flux_credit_ledger_tb WHERE kind = 'harness_provision' AND idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if duplicate:
                raise BrowserError("duplicate_idempotency_key", "That harness provisioning idempotency key was already used.", status=HTTPStatus.CONFLICT)
        balance = flux_balance(conn, uid)
        if balance < cost:
            append_instance_audit(
                conn,
                actor_user_id=uid,
                action="agent_harness.denied",
                target=f"harness:{config['harness_id']}",
                metadata={"reason": "insufficient_flux", "balance": balance, "cost": cost},
            )
            raise BrowserError("insufficient_flux_credits", "Insufficient Flux for Wasm-Agent-Cloud based Hermes provisioning.", status=HTTPStatus.PAYMENT_REQUIRED)
        provider_config = provider_config_from_body({"provider_config": body.get("provider_config") or {}})
        bridge_payload = provision_main_bridge_payload(node_id, bridge_body, provider_config)
        ledger_id = f"flux_{next_snowflake_id():x}"
        harness = write_harness_row_in_conn(
            conn,
            user,
            config,
            node_id=node_id,
            lifecycle_state="charging",
            capabilities={"mode": "hermes_backend"},
        )
        conn.execute(
            """
            INSERT INTO flux_credit_ledger_tb (
              id, user_id, actor_user_id, amount, kind, reason, idempotency_key, target, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, 'harness_provision', ?, ?, ?, ?, ?)
            """,
            (
                ledger_id,
                uid,
                uid,
                -cost,
                f"Provision Hermes agent harness {config['harness_name']}",
                idempotency_key,
                f"harness:{config['harness_id']}",
                int(time.time()),
                json.dumps({"harness_id": config["harness_id"], "node_id": node_id, "infra_mode": "hermes_backend"}, ensure_ascii=True, sort_keys=True),
            ),
        )
        set_agent_harness_state(conn, config["harness_id"], "provisioning", capabilities={"mode": "hermes_backend"})
        append_instance_audit(
            conn,
            actor_user_id=uid,
            action="agent_harness.provisioning",
            target=f"harness:{config['harness_id']}",
            metadata={"cost": cost, "node_id": node_id, "ledger_id": ledger_id},
        )
        conn.execute("COMMIT")

    try:
        live_sandbox = live_account_sandbox_snapshot(server, node_id)
        if live_sandbox:
            bridge_result = account_sandbox_bridge_result(node_id, live_sandbox, source="existing_account_sandbox")
        else:
            try:
                bridge_result = bridge_proxy(server, "POST", "/nodes", bridge_payload, timeout=120)
            except Exception as create_exc:
                recovered_sandbox = wait_for_live_account_sandbox(server, node_id) if should_probe_late_sandbox_after_create_error(create_exc) else {}
                if not recovered_sandbox:
                    raise
                recovered_after = create_exc.code if isinstance(create_exc, BrowserError) else type(create_exc).__name__
                bridge_result = account_sandbox_bridge_result(
                    node_id,
                    recovered_sandbox,
                    source="late_account_sandbox_recovery",
                    recovered_after=recovered_after,
                )
        runtime_url, runtime_source = account_node_runtime_url_source(server, node_id)
        capabilities = {
            "mode": "hermes_backend",
            "bridge_url_source": runtime_source,
            "bridge_result": compact_json(sanitize_room_event_payload(bridge_result), 1200),
            "routes": {"models": "/bridge/v1/models", "chat": "/agent/session/message"},
        }
        with auth_connect() as conn:
            ensure_main_fleet_node_in_conn(conn, user, node_id)
            set_agent_harness_state(conn, config["harness_id"], "ready", bridge_url=runtime_url or server.bridge_url, capabilities=capabilities)
            row = conn.execute("SELECT * FROM agent_harness_tb WHERE id = ?", (config["harness_id"],)).fetchone()
            append_instance_audit(
                conn,
                actor_user_id=uid,
                action="agent_harness.ready",
                target=f"harness:{config['harness_id']}",
                metadata={"cost": cost, "node_id": node_id},
            )
            harness = public_agent_harness(row)
    except Exception as exc:
        reason = exc.message if isinstance(exc, BrowserError) else str(exc)
        refund_agent_harness_charge(user, config["harness_id"], node_id, cost, reason)
        if isinstance(exc, BrowserError):
            raise
        raise BrowserError("harness_provision_failed", "Provisioning failed.", status=HTTPStatus.BAD_GATEWAY) from exc

    return {
        "ok": True,
        "schema": AGENT_HARNESS_PROVISION_SCHEMA,
        "charged": True,
        "cost": cost,
        "lifecycle_state": "ready",
        "harness": harness,
        "node_id": node_id,
        "bridge": bridge_result,
        "readiness": agent_readiness(server, user, target_node=node_id),
        "credits": account_credits(user),
    }


def provision_main_fleet_node(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    body: dict[str, Any],
) -> dict[str, Any]:
    if not user:
        append_instance_audit(
            None,
            actor_user_id="",
            action="fleet.provision_main.denied",
            target="node:",
            metadata={"reason": "auth_required"},
        )
        raise BrowserError("auth_required", "Account sign-in is required.", status=HTTPStatus.UNAUTHORIZED)
    if user_is_admin(user):
        append_instance_audit(
            None,
            actor_user_id=user_id(user),
            action="fleet.provision_main.denied",
            target="node:",
            metadata={"reason": "admin_self_provision"},
        )
        raise BrowserError("admin_provision_denied", "Admin accounts do not self-provision paid account sandboxes.", status=HTTPStatus.FORBIDDEN)
    uid = user_id(user)
    node_id = account_main_node_id(user)
    try:
        validate_provision_main_body(user, body, node_id)
    except BrowserError as exc:
        append_instance_audit(
            None,
            actor_user_id=uid,
            action="fleet.provision_main.denied",
            target=f"node:{node_id}",
            metadata={
                "reason": exc.code,
                "requested_node": str(body.get("node_id") or body.get("node") or body.get("name") or body.get("target_node") or ""),
                "requested_provider": str(body.get("provider") or body.get("default_model_provider") or ""),
                "requested_model": str(body.get("model") or body.get("default_model") or ""),
            },
        )
        raise
    idempotency_key = clipped(str(body.get("idempotency_key") or body.get("idempotencyKey") or "").strip(), 160)

    readiness = agent_readiness(server, user, target_node=node_id)
    if readiness.get("status") == AGENT_READINESS_READY:
        with auth_connect() as conn:
            node = ensure_main_fleet_node_in_conn(conn, user, node_id)
            append_instance_audit(
                conn,
                actor_user_id=uid,
                action="fleet.provision_main.existing",
                target=f"node:{node_id}",
                metadata={"debited": False, "readiness": readiness},
            )
            credits = {
                "balance": flux_balance(conn, uid),
                "provision_main_cost": flux_main_node_provision_cost(),
            }
        return {
            "ok": True,
            "schema": FLUX_PROVISION_SCHEMA,
            "node": node,
            "node_id": node_id,
            "provisioned": False,
            "already_provisioned": True,
            "debited": False,
            "credits": credits,
            "readiness": readiness,
        }

    cost = flux_main_node_provision_cost()
    bridge_payload = provision_main_bridge_payload(node_id, body)
    conn = auth_connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if idempotency_key:
            duplicate = conn.execute(
                "SELECT * FROM flux_credit_ledger_tb WHERE kind = 'provision' AND idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if duplicate:
                append_instance_audit(
                    conn,
                    actor_user_id=uid,
                    action="fleet.provision_main.denied",
                    target=f"node:{node_id}",
                    metadata={"reason": "duplicate_idempotency_key", "idempotency_key": idempotency_key},
                )
                raise BrowserError("duplicate_idempotency_key", "That provisioning idempotency key was already used.", status=HTTPStatus.CONFLICT)
        balance = flux_balance(conn, uid)
        if balance < cost:
            append_instance_audit(
                conn,
                actor_user_id=uid,
                action="fleet.provision_main.denied",
                target=f"node:{node_id}",
                metadata={"reason": "insufficient_credits", "balance": balance, "cost": cost},
            )
            raise BrowserError("insufficient_flux_credits", "Not enough Flux credits to provision the account sandbox.", status=HTTPStatus.PAYMENT_REQUIRED)
        ledger_id = f"flux_{next_snowflake_id():x}"
        conn.execute(
            """
            INSERT INTO flux_credit_ledger_tb (
              id, user_id, actor_user_id, amount, kind, reason, idempotency_key, target, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, 'provision', ?, ?, ?, ?, ?)
            """,
            (
                ledger_id,
                uid,
                uid,
                -cost,
                f"Provision main sandbox {node_id}",
                idempotency_key,
                f"node:{node_id}",
                int(time.time()),
                json.dumps(
                    {
                        "provider": FLUX_MAIN_NODE_PROVIDER,
                        "model": FLUX_MAIN_NODE_MODEL,
                        "node_state": "4",
                        "agent_name": str(body.get("agent_name") or body.get("agentName") or "My agent").strip()[:80] or "My agent",
                        "agent_type": str(body.get("agent_type") or "hermes").strip().lower() or "hermes",
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                ),
            ),
        )
        node = ensure_main_fleet_node_in_conn(conn, user, node_id)
        try:
            bridge_result = bridge_proxy(server, "POST", "/nodes", bridge_payload, timeout=120)
        except Exception as create_exc:
            recovered_sandbox = wait_for_live_account_sandbox(server, node_id) if should_probe_late_sandbox_after_create_error(create_exc) else {}
            if not recovered_sandbox:
                raise
            recovered_after = create_exc.code if isinstance(create_exc, BrowserError) else type(create_exc).__name__
            bridge_result = account_sandbox_bridge_result(
                node_id,
                recovered_sandbox,
                source="late_account_sandbox_recovery",
                recovered_after=recovered_after,
            )
        append_instance_audit(
            conn,
            actor_user_id=uid,
            action="fleet.provision_main",
            target=f"node:{node_id}",
            metadata={
                "cost": cost,
                "ledger_id": ledger_id,
                "provider": FLUX_MAIN_NODE_PROVIDER,
                "model": FLUX_MAIN_NODE_MODEL,
                "bridge_result": compact_json(sanitize_room_event_payload(bridge_result), 1200),
            },
        )
        row = conn.execute("SELECT * FROM flux_credit_ledger_tb WHERE id = ?", (ledger_id,)).fetchone()
        credits = {
            "balance": flux_balance(conn, uid),
            "provision_main_cost": cost,
            "ledger_row": public_flux_ledger_row(row) if row else None,
        }
        conn.execute("COMMIT")
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.DatabaseError:
            pass
        if isinstance(exc, BrowserError):
            append_instance_audit(
                None,
                actor_user_id=uid,
                action="fleet.provision_main.denied",
                target=f"node:{node_id}",
                metadata={"error": exc.code, "message": exc.message, "cost": cost},
            )
            raise
        append_instance_audit(
            None,
            actor_user_id=uid,
            action="fleet.provision_main.failed",
            target=f"node:{node_id}",
            metadata={"error": str(exc), "cost": cost},
        )
        raise
    finally:
        conn.close()

    next_readiness = agent_readiness(server, user, target_node=node_id)
    return {
        "ok": True,
        "schema": FLUX_PROVISION_SCHEMA,
        "node": node,
        "node_id": node_id,
        "provisioned": True,
        "already_provisioned": False,
        "debited": True,
        "cost": cost,
        "provider": FLUX_MAIN_NODE_PROVIDER,
        "model": FLUX_MAIN_NODE_MODEL,
        "bridge": bridge_result,
        "credits": credits,
        "readiness": next_readiness,
    }


def voice_lab_root(server: WasmAgentServer) -> Path:
    path = server.state_dir / "voice-lab"
    path.mkdir(parents=True, exist_ok=True)
    return path


def voice_lab_room_id(raw: str) -> str:
    room_id = safe_state_id(raw, "")
    if not room_id:
        raise BrowserError("invalid_voice_lab_room", "room_id is required.")
    return room_id


def voice_lab_room_dir(server: WasmAgentServer, room_id: str) -> Path:
    path = voice_lab_root(server) / voice_lab_room_id(room_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def voice_lab_presence_path(server: WasmAgentServer, room_id: str) -> Path:
    return voice_lab_room_dir(server, room_id) / "presence.json"


def voice_lab_events_path(server: WasmAgentServer, room_id: str) -> Path:
    return voice_lab_room_dir(server, room_id) / "room-events.json"


def request_voice_lab_client_id(handler: WasmAgentHandler) -> str:
    return safe_state_id(str(handler.headers.get("X-Wasm-Agent-Voice-Lab-Client-Id") or ""), "")


def request_voice_lab_device_id(user: dict[str, Any] | None, handler: WasmAgentHandler) -> str:
    explicit = safe_state_id(str(handler.headers.get("X-Wasm-Agent-Voice-Lab-Device-Id") or ""), "")
    if explicit:
        return explicit
    client_id = request_voice_lab_client_id(handler) or request_client_device_id(handler)
    if client_id:
        return safe_state_id(f"voice-lab-{client_id}", "")
    return safe_state_id(f"voice-lab-{request_account_device_id(user, handler)}", "")


def read_voice_lab_presence(server: WasmAgentServer, room_id: str) -> dict[str, Any]:
    payload = read_json_file(voice_lab_presence_path(server, room_id), {})
    return payload if isinstance(payload, dict) else {}


def prune_voice_lab_presence(payload: dict[str, Any], now: int) -> dict[str, Any]:
    entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
    live_entries = {
        key: item
        for key, item in entries.items()
        if isinstance(item, dict) and now - int(item.get("last_seen") or 0) <= VOICE_LAB_PRESENCE_TTL_SEC
    }
    return {
        "schema": VOICE_LAB_PRESENCE_SCHEMA,
        "updated_at": iso_timestamp(),
        "entries": live_entries,
    }


def touch_voice_lab_presence(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    handler: WasmAgentHandler,
    room_id: str,
) -> dict[str, Any]:
    now = int(time.time())
    presence = prune_voice_lab_presence(read_voice_lab_presence(server, room_id), now)
    user_agent = clipped(str(handler.headers.get("User-Agent") or "Browser"), 360)
    device_id = request_voice_lab_device_id(user, handler)
    client_id = request_voice_lab_client_id(handler)
    key = f"{user_id(user)}:{client_id or device_id}"
    entries = presence.get("entries") if isinstance(presence.get("entries"), dict) else {}
    entries[key] = {
        "user_id": user_id(user),
        "device_id": device_id,
        "client_id": client_id,
        "label": browser_label(user_agent),
        "user_label": public_user_label(user),
        "last_seen": now,
    }
    presence["entries"] = entries
    presence["updated_at"] = iso_timestamp()
    write_json_file(voice_lab_presence_path(server, room_id), presence)
    return presence


def public_voice_lab_presence_entries(presence: dict[str, Any], now: int | None = None) -> list[dict[str, Any]]:
    now = now or int(time.time())
    entries = presence.get("entries") if isinstance(presence.get("entries"), dict) else {}
    visible = []
    for item in entries.values():
        if not isinstance(item, dict):
            continue
        last_seen = int(item.get("last_seen") or 0)
        if now - last_seen > VOICE_LAB_PRESENCE_TTL_SEC:
            continue
        visible.append({
            "user_id": safe_state_id(str(item.get("user_id") or ""), ""),
            "device_id": safe_state_id(str(item.get("device_id") or ""), ""),
            "client_id": safe_state_id(str(item.get("client_id") or ""), ""),
            "label": clipped(str(item.get("label") or "Browser"), 80),
            "user_label": clipped(str(item.get("user_label") or item.get("user_id") or "User"), 120),
            "last_seen": last_seen,
        })
    visible.sort(key=lambda entry: (entry["user_label"].lower(), entry["device_id"], entry["client_id"]))
    return visible


def read_voice_lab_events(server: WasmAgentServer, room_id: str) -> list[dict[str, Any]]:
    payload = read_json_file(voice_lab_events_path(server, room_id), {})
    events = payload.get("events") if isinstance(payload, dict) and isinstance(payload.get("events"), list) else []
    return [event for event in events if isinstance(event, dict)][-VOICE_LAB_EVENT_LIMIT:]


def append_voice_lab_room_event(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    room_id: str,
    body: dict[str, Any],
    handler: WasmAgentHandler,
) -> dict[str, Any]:
    events = read_voice_lab_events(server, room_id)
    event_kind = safe_state_id(str(body.get("kind") or body.get("event_kind") or "voice-signal"), "voice-signal")
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    payload = {
        **payload,
        "room_id": room_id,
        "from_user_id": user_id(user),
        "from_device_id": request_voice_lab_device_id(user, handler),
        "from_client_id": request_voice_lab_client_id(handler),
    }
    event = {
        "schema": VOICE_LAB_ROOM_EVENT_SCHEMA,
        "id": f"voice_lab_evt_{next_snowflake_id():x}",
        "kind": event_kind,
        "sender_user_id": user_id(user),
        "created_at": iso_timestamp(),
        "payload": sanitize_room_event_payload(payload),
    }
    events.append(event)
    write_json_file(voice_lab_events_path(server, room_id), {
        "schema": "hermes.wasm_agent.voice_lab.room_events.v1",
        "updated_at": iso_timestamp(),
        "events": events[-VOICE_LAB_EVENT_LIMIT:],
    })
    return event


def public_voice_lab_room(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    handler: WasmAgentHandler,
    room_id: str,
    presence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rid = voice_lab_room_id(room_id)
    now = int(time.time())
    current_presence = prune_voice_lab_presence(presence or read_voice_lab_presence(server, rid), now)
    visible = public_voice_lab_presence_entries(current_presence, now)
    online_users = {entry["user_id"] for entry in visible if entry.get("user_id")}
    return {
        "schema": VOICE_LAB_ROOM_SCHEMA,
        "id": rid,
        "title": f"Voice Lab {rid}",
        "presence_ttl_sec": VOICE_LAB_PRESENCE_TTL_SEC,
        "online_count": len(online_users),
        "online_device_count": len(visible),
        "presence": visible,
        "current_user_id": user_id(user),
        "current_device_id": request_voice_lab_device_id(user, handler),
        "current_client_id": request_voice_lab_client_id(handler),
        "events": read_voice_lab_events(server, rid)[-VOICE_LAB_ROOM_PUBLIC_EVENT_LIMIT:],
    }


def voice_lab_room(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    body: dict[str, Any],
    handler: WasmAgentHandler,
) -> dict[str, Any]:
    room_id = voice_lab_room_id(str(body.get("room_id") or body.get("room") or ""))
    action = str(body.get("action") or "presence").strip().lower()
    presence = read_voice_lab_presence(server, room_id)
    if action in {"presence", "heartbeat"}:
        presence = touch_voice_lab_presence(server, user, handler, room_id)
    elif action == "signal":
        presence = touch_voice_lab_presence(server, user, handler, room_id)
        append_voice_lab_room_event(server, user, room_id, body, handler)
    elif action != "read":
        raise BrowserError("invalid_voice_lab_action", "Unsupported voice lab room action.")
    return {"ok": True, "room": public_voice_lab_room(server, user, handler, room_id, presence)}


def copy_user_wis_to_shared(server: WasmAgentServer, user: dict[str, Any] | None, space_id: str, shared_space_id: str) -> None:
    source = user_wis_dir(server, user, space_id)
    target = shared_space_dir(server, shared_space_id) / "wis"
    target.mkdir(parents=True, exist_ok=True)
    if any(target.glob("*.json")):
        return
    for item in source.glob("*.json"):
        if item.is_file():
            shutil.copy2(item, target / item.name)


def share_user_space(server: WasmAgentServer, user: dict[str, Any] | None, body: dict[str, Any]) -> dict[str, Any]:
    space_id = safe_state_id(str(body.get("space_id") or ""), "")
    if not space_id or is_reserved_user_space_id(space_id):
        raise BrowserError("invalid_space_share", "Only user-created spaces can be shared.")
    space_path = user_spaces_dir(server, user) / space_id / "space.json"
    meta = read_json_file(space_path, {})
    if not isinstance(meta, dict) or not meta:
        raise BrowserError("space_not_found", "That space was not found.", status=HTTPStatus.NOT_FOUND)
    now = iso_timestamp()
    shared_space_id = safe_state_id(str(meta.get("shared_space_id") or body.get("shared_space_id") or f"share_{next_snowflake_id():x}"), "")
    join_code = safe_state_id(str(body.get("join_code") or uuid.uuid4().hex[:12]), "")
    record = read_shared_space_record(server, shared_space_id)
    if record and not user_can_access_shared_space(record, user):
        raise BrowserError("shared_space_denied", "You cannot update that shared space.", status=HTTPStatus.FORBIDDEN)
    space_area = (
        sanitize_space_area(body.get("space_area"))
        or sanitize_space_area(meta.get("space_area"))
        or sanitize_space_area(record.get("space_area"))
    )
    members = record.get("members") if isinstance(record.get("members"), list) else []
    uid = user_id(user)
    if uid not in shared_space_member_ids({"members": members}):
        members.append({"user_id": uid, "role": "owner", "joined_at": now})
    record = {
        "schema": SHARED_SPACE_SCHEMA,
        "id": shared_space_id,
        "join_code": str(record.get("join_code") or join_code),
        "owner_user_id": str(record.get("owner_user_id") or uid),
        "source_space_id": space_id,
        "local_space_id": space_id,
        "title": clipped(str(body.get("title") or meta.get("title") or space_id), 120),
        "space_area": space_area or {},
        "members": members,
        "capabilities": ["chat", "wis-patch", "automation", "component-evolution"],
        "created_at": str(record.get("created_at") or now),
        "updated_at": now,
    }
    write_json_file(shared_space_record_path(server, shared_space_id), record)
    copy_user_wis_to_shared(server, user, space_id, shared_space_id)
    meta.update({
        "shared": True,
        "shared_space_id": shared_space_id,
        "space_area": space_area or {},
        "updated_at": now,
    })
    write_json_file(space_path, meta)
    return {"ok": True, "shared_space": public_shared_space_record(record, user, server)}


def find_shared_space_by_join(server: WasmAgentServer, token: str) -> dict[str, Any]:
    target = safe_state_id(token, "")
    for path in sorted(shared_spaces_dir(server).iterdir()):
        if not path.is_dir():
            continue
        record = read_json_file(path / "shared-space.json", {})
        if not isinstance(record, dict):
            continue
        if safe_state_id(str(record.get("id") or ""), "") == target or safe_state_id(str(record.get("join_code") or ""), "") == target:
            return record
    raise BrowserError("shared_space_not_found", "That shared space or join code was not found.", status=HTTPStatus.NOT_FOUND)


def join_token_from_text(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
        query = parse_qs(parsed.query)
        for key in ("join_space", "join_code", "shared_space"):
            values = query.get(key)
            if values:
                return str(values[0] or "").strip()
        parts = [part for part in parsed.path.split("/") if part]
        for marker in ("join", "join-space", "shared-space"):
            if marker in parts:
                index = parts.index(marker)
                if index + 1 < len(parts):
                    return parts[index + 1].strip()
    except Exception:
        pass
    return text


def join_shared_space(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    body: dict[str, Any],
    handler: WasmAgentHandler | None = None,
) -> dict[str, Any]:
    token = join_token_from_text(str(body.get("join_code") or body.get("shared_space_id") or ""))
    if not token:
        raise BrowserError("invalid_join_code", "join_code or shared_space_id is required.")
    record = find_shared_space_by_join(server, token)
    now = iso_timestamp()
    uid = user_id(user)
    members = record.get("members") if isinstance(record.get("members"), list) else []
    if uid not in shared_space_member_ids({"members": members}):
        members.append({"user_id": uid, "role": "member", "joined_at": now})
    record["members"] = members
    record["updated_at"] = now
    write_json_file(shared_space_record_path(server, str(record.get("id") or "")), record)
    local_space_id = safe_state_id(str(body.get("local_space_id") or record.get("id") or ""), "shared-space")
    write_json_file(user_space_dir(server, user, local_space_id) / "space.json", {
        "schema": "hermes.wasm_agent.space.v1",
        "id": local_space_id,
        "title": clipped(str(record.get("title") or local_space_id), 120),
        "shared": True,
        "shared_space_id": str(record.get("id") or ""),
        "space_area": sanitize_space_area(record.get("space_area")) or {},
        "created_at": now,
        "updated_at": now,
    })
    return {
        "ok": True,
        "shared_space": public_shared_space_record(record, user, server),
        "spaces": list_user_spaces(server, user, handler),
    }


def default_wis_artifact(artifact_id: str, title: str = "") -> dict[str, Any]:
    aid = safe_state_id(artifact_id, "main")
    label = clipped(title or aid.replace("-", " ").replace("_", " ").title() or "WIS Space", 120)
    return {
        "schema": WIS_SPACE_SCHEMA,
        "id": aid,
        "title": label,
        "version": 1,
        "entryDocumentId": "main",
        "sandbox": {
            "network": False,
            "iframe": False,
            "backend": False,
            "externalScripts": False,
        },
        "documents": [
            {
                "id": "main",
                "url": f"wis://local/{aid}",
                "title": label,
                "state": {},
                "tree": {
                    "id": "doc",
                    "type": "document",
                    "role": "document",
                    "children": [
                        {
                            "id": "title",
                            "type": "heading",
                            "level": 1,
                            "text": label,
                            "children": [],
                        }
                    ],
                },
            }
        ],
    }


def wis_artifact_root(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    space_id: str,
    shared_space_id: str = "",
) -> tuple[Path, str]:
    sid = safe_state_id(shared_space_id, "")
    if sid:
        record = read_shared_space_record(server, sid)
        if not record:
            raise BrowserError("shared_space_not_found", "That shared space was not found.", status=HTTPStatus.NOT_FOUND)
        if not user_can_access_shared_space(record, user):
            raise BrowserError("shared_space_denied", "You cannot mutate that shared space.", status=HTTPStatus.FORBIDDEN)
        path = shared_space_dir(server, sid) / "wis"
        path.mkdir(parents=True, exist_ok=True)
        return path, f"shared:{sid}"
    storage_id = canonical_space_storage_id(space_id, "home")
    return user_wis_dir(server, user, storage_id), f"user:{user_id(user)}:{storage_id}"


def wis_artifact_file(root: Path, artifact_id: str) -> Path:
    aid = safe_state_id(artifact_id, "main")
    return root / f"{aid}.json"


def list_wis_artifacts(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    space_id: str = "home",
    *,
    shared_space_id: str = "",
) -> dict[str, Any]:
    space_id = canonical_space_storage_id(space_id, "home")
    root, scope = wis_artifact_root(server, user, space_id, shared_space_id)
    artifacts = []
    for path in sorted(root.glob("*.json")):
        payload = read_json_file(path, {})
        if isinstance(payload, dict):
            artifacts.append({
                "id": safe_state_id(str(payload.get("id") or path.stem), path.stem),
                "title": clipped(str(payload.get("title") or path.stem), 120),
                "schema": str(payload.get("schema") or ""),
                "version": payload.get("version", 1),
                "updated_at": str(payload.get("updated_at") or ""),
            })
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.wis.artifacts.v1",
        "scope": scope,
        "space_id": safe_state_id(space_id, "home"),
        "shared_space_id": safe_state_id(shared_space_id, ""),
        "artifacts": artifacts,
    }


def read_wis_artifact(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    space_id: str,
    artifact_id: str,
    *,
    shared_space_id: str = "",
) -> dict[str, Any]:
    space_id = canonical_space_storage_id(space_id, "home")
    root, scope = wis_artifact_root(server, user, space_id, shared_space_id)
    aid = safe_state_id(artifact_id, "main")
    path = wis_artifact_file(root, aid)
    payload = read_json_file(path, {})
    if not isinstance(payload, dict) or payload.get("schema") != WIS_SPACE_SCHEMA:
        raise BrowserError("wis_artifact_not_found", "That WIS artifact was not found.", status=HTTPStatus.NOT_FOUND)
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.wis.artifact.v1",
        "scope": scope,
        "space_id": safe_state_id(space_id, "home"),
        "shared_space_id": safe_state_id(shared_space_id, ""),
        "artifact_id": aid,
        "artifact": payload,
        "path": repo_relative_string(server, path),
    }


def wis_value_set(data: dict[str, Any], key: str, value: Any) -> None:
    parts = [safe_state_id(part, "") for part in str(key or "").split(".") if safe_state_id(part, "")]
    if not parts:
        raise BrowserError("invalid_wis_patch", "State operations require a key.")
    target = data
    for part in parts[:-1]:
        existing = target.get(part)
        if not isinstance(existing, dict):
            existing = {}
            target[part] = existing
        target = existing
    target[parts[-1]] = json_clone(value)


def wis_find_node(node: dict[str, Any] | None, node_id: str) -> dict[str, Any] | None:
    if not isinstance(node, dict):
        return None
    if str(node.get("id") or "") == node_id:
        return node
    for child in node.get("children") if isinstance(node.get("children"), list) else []:
        found = wis_find_node(child, node_id)
        if found:
            return found
    return None


def wis_remove_node(node: dict[str, Any], node_id: str) -> bool:
    children = node.get("children")
    if not isinstance(children, list):
        return False
    for index, child in enumerate(children):
        if isinstance(child, dict) and str(child.get("id") or "") == node_id:
            del children[index]
            return True
        if isinstance(child, dict) and wis_remove_node(child, node_id):
            return True
    return False


def sanitize_wis_node(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise BrowserError("invalid_wis_patch", "WIS node payload must be an object.")
    node_id = safe_state_id(str(raw.get("id") or f"node_{next_snowflake_id():x}"), "")
    if not node_id:
        raise BrowserError("invalid_wis_patch", "WIS node id is required.")
    props = json_clone(raw.get("props") if isinstance(raw.get("props"), dict) else {})
    for key in ("layout", "title", "label", "url", "src", "placeholder", "className"):
        value = raw.get(key)
        if value is not None and key not in props:
            props[key] = clipped(str(value), 1000)
    style = raw.get("style")
    if "style" not in props:
        if isinstance(style, list):
            props["style"] = [clipped(str(item), 200) for item in style[:20]]
        elif isinstance(style, str):
            props["style"] = [clipped(style, 200)]
    node_text = clipped(str(raw.get("text") or ""), 1000)
    if not node_text and str(raw.get("type") or "") == "button" and props.get("label"):
        node_text = clipped(str(props.get("label") or ""), 1000)
    node = {
        "id": node_id,
        "type": safe_state_id(str(raw.get("type") or "section"), "section"),
        "role": clipped(str(raw.get("role") or ""), 80),
        "text": node_text,
        "props": props,
        "children": [],
    }
    if raw.get("level"):
        node["level"] = int(raw.get("level") or 1)
    if isinstance(raw.get("action"), dict):
        node["action"] = json_clone(raw["action"])
    children = raw.get("children")
    if isinstance(children, list):
        node["children"] = [sanitize_wis_node(child) for child in children[:80]]
    return node


def wis_title_from_node(node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return ""
    node_type = str(node.get("type") or "")
    text = clipped(str(node.get("text") or ""), 120)
    if text and node_type in {"heading", "title"}:
        return text
    props = node.get("props")
    if isinstance(props, dict) and props.get("title") and node_type in {"document", "section", "card"}:
        return clipped(str(props.get("title") or ""), 120)
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            title = wis_title_from_node(child if isinstance(child, dict) else None)
            if title:
                return title
    return ""


def wis_patch_document(definition: dict[str, Any], document_id: str) -> dict[str, Any]:
    documents = definition.setdefault("documents", [])
    if not isinstance(documents, list):
        documents = []
        definition["documents"] = documents
    doc_id = safe_state_id(document_id or definition.get("entryDocumentId") or "main", "main")
    for document in documents:
        if isinstance(document, dict) and str(document.get("id") or "") == doc_id:
            document.setdefault("state", {})
            document.setdefault("tree", {"id": "doc", "type": "document", "children": []})
            return document
    document = {
        "id": doc_id,
        "url": f"wis://local/{doc_id}",
        "title": doc_id,
        "state": {},
        "tree": {"id": "doc", "type": "document", "role": "document", "children": []},
    }
    documents.append(document)
    if not definition.get("entryDocumentId"):
        definition["entryDocumentId"] = doc_id
    return document


def apply_wis_patch_operations(definition: dict[str, Any], patch: dict[str, Any]) -> int:
    operations = patch.get("operations")
    if not isinstance(operations, list) or not operations:
        raise BrowserError("invalid_wis_patch", "WIS patch requires operations.")
    if len(operations) > 40:
        raise BrowserError("invalid_wis_patch", "WIS patch has too many operations.")
    changed = 0
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        op = str(operation.get("op") or "").strip()
        document = wis_patch_document(definition, str(operation.get("document_id") or patch.get("document_id") or definition.get("entryDocumentId") or "main"))
        tree = document.setdefault("tree", {"id": "doc", "type": "document", "children": []})
        state = document.setdefault("state", {})
        if op in {"set_title", "set_artifact_title"}:
            title = clipped(str(operation.get("title") or operation.get("value") or ""), 120)
            if title:
                definition["title"] = title
                document["title"] = title
                changed += 1
        elif op == "set_state":
            wis_value_set(state, str(operation.get("key") or ""), operation.get("value"))
            changed += 1
        elif op == "set_node_text":
            node = wis_find_node(tree, str(operation.get("node_id") or ""))
            if not node:
                raise BrowserError("invalid_wis_patch", "WIS node was not found.")
            node["text"] = clipped(str(operation.get("text") or ""), 2000)
            changed += 1
        elif op == "set_node_props":
            node = wis_find_node(tree, str(operation.get("node_id") or ""))
            if not node:
                raise BrowserError("invalid_wis_patch", "WIS node was not found.")
            props = operation.get("props")
            if not isinstance(props, dict):
                raise BrowserError("invalid_wis_patch", "set_node_props requires props.")
            current = node.get("props") if isinstance(node.get("props"), dict) else {}
            current.update(json_clone(props))
            node["props"] = current
            changed += 1
        elif op == "set_node_action":
            node = wis_find_node(tree, str(operation.get("node_id") or ""))
            if not node:
                raise BrowserError("invalid_wis_patch", "WIS node was not found.")
            action = operation.get("action")
            if not isinstance(action, dict):
                raise BrowserError("invalid_wis_patch", "set_node_action requires action.")
            node["action"] = json_clone(action)
            changed += 1
        elif op in {"append_child", "add_node"}:
            parent = wis_find_node(tree, str(operation.get("parent_id") or "doc"))
            if not parent:
                raise BrowserError("invalid_wis_patch", "WIS parent node was not found.")
            children = parent.setdefault("children", [])
            if not isinstance(children, list):
                children = []
                parent["children"] = children
            children.append(sanitize_wis_node(operation.get("node")))
            changed += 1
        elif op == "remove_node":
            node_id = str(operation.get("node_id") or "")
            if node_id == "doc" or not wis_remove_node(tree, node_id):
                raise BrowserError("invalid_wis_patch", "WIS node could not be removed.")
            changed += 1
        elif op == "replace_node":
            node_id = str(operation.get("node_id") or "")
            if node_id == "doc":
                document["tree"] = sanitize_wis_node(operation.get("node"))
                changed += 1
            elif wis_remove_node(tree, node_id):
                parent = wis_find_node(tree, str(operation.get("parent_id") or "doc")) or tree
                parent.setdefault("children", []).append(sanitize_wis_node(operation.get("node")))
                changed += 1
            else:
                raise BrowserError("invalid_wis_patch", "WIS node was not found.")
        elif op == "add_document":
            raw_node = operation.get("node")
            if isinstance(raw_node, dict):
                next_tree = sanitize_wis_node(raw_node)
                if next_tree.get("type") == "document" and not next_tree.get("role"):
                    next_tree["role"] = "document"
                document["tree"] = next_tree
                title = clipped(
                    str(operation.get("title") or patch.get("title") or wis_title_from_node(next_tree) or ""),
                    120,
                )
                if title:
                    definition["title"] = title
                    document["title"] = title
            changed += 1
        else:
            raise BrowserError("invalid_wis_patch", f"Unsupported WIS patch operation: {op}.")
    return changed


def patch_wis_artifact(server: WasmAgentServer, user: dict[str, Any] | None, body: dict[str, Any]) -> dict[str, Any]:
    patch = body.get("patch") if isinstance(body.get("patch"), dict) else body
    if not isinstance(patch, dict) or patch.get("schema") != WIS_PATCH_SCHEMA:
        raise BrowserError("invalid_wis_patch", f"WIS patch schema must be {WIS_PATCH_SCHEMA}.")
    space_id = canonical_space_storage_id(str(patch.get("space_id") or body.get("space_id") or "home"), "home")
    shared_space_id = safe_state_id(str(patch.get("shared_space_id") or body.get("shared_space_id") or ""), "")
    artifact_id = safe_state_id(str(patch.get("artifact_id") or body.get("artifact_id") or "main"), "main")
    root, scope = wis_artifact_root(server, user, space_id, shared_space_id)
    path = wis_artifact_file(root, artifact_id)
    existing = read_json_file(path, {})
    definition = existing if isinstance(existing, dict) and existing.get("schema") == WIS_SPACE_SCHEMA else default_wis_artifact(artifact_id, str(patch.get("title") or ""))
    changed = apply_wis_patch_operations(definition, patch)
    now = iso_timestamp()
    definition["id"] = artifact_id
    definition["schema"] = WIS_SPACE_SCHEMA
    definition["updated_at"] = now
    definition["version"] = int(definition.get("version") or 1) + 1
    encoded = json.dumps(definition, ensure_ascii=True).encode("utf-8")
    if not shared_space_id:
        ensure_user_quota(server, user, len(encoded))
    if len(encoded) > 512 * 1024:
        raise BrowserError("wis_artifact_too_large", "WIS artifact exceeds the 512 KB limit.")
    write_json_file(path, definition)
    try:
        print(json.dumps({
            "event": "wis.artifact.patch",
            "artifact_id": artifact_id,
            "title": str(definition.get("title") or ""),
            "schema": str(definition.get("schema") or ""),
            "space_id": space_id,
            "shared_space_id": shared_space_id,
            "scope": scope,
            "operations": changed,
        }, ensure_ascii=True), flush=True)
    except Exception:
        pass
    return {
        "schema": WIS_PATCH_RESULT_SCHEMA,
        "applied": changed > 0,
        "scope": scope,
        "space_id": space_id,
        "shared_space_id": shared_space_id,
        "artifact_id": artifact_id,
        "title": str(definition.get("title") or artifact_id),
        "artifact_schema": str(definition.get("schema") or ""),
        "operations": changed,
        "path": repo_relative_string(server, path),
        "updated_at": now,
    }


def security_loop_dir(server: WasmAgentServer) -> Path:
    path = server.state_dir / "security-loop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def security_loop_findings_path(server: WasmAgentServer) -> Path:
    return security_loop_dir(server) / "findings.jsonl"


def security_loop_current_path(server: WasmAgentServer) -> Path:
    return security_loop_dir(server) / "findings_current.json"


def security_loop_summary_path(server: WasmAgentServer) -> Path:
    return security_loop_dir(server) / "summary.json"


def security_loop_latest_run_path(server: WasmAgentServer) -> Path:
    return security_loop_dir(server) / "latest-run.json"


def security_loop_latest_run(server: WasmAgentServer) -> dict[str, Any]:
    latest = read_json_file(security_loop_latest_run_path(server), {})
    if not isinstance(latest, dict):
        return {}
    return compact_security_loop_run(latest)


def security_loop_run_summary(run: dict[str, Any]) -> str:
    surfaces = ", ".join(str(item) for item in (run.get("surfaces") if isinstance(run.get("surfaces"), list) else [])[:6]) or "default surfaces"
    value = run.get("value") if isinstance(run.get("value"), dict) else {}
    verdict = str(value.get("verdict") or "value pending")
    finding_count = int(run.get("finding_count") or 0)
    failed_probe_count = int(run.get("failed_probe_count") or 0)
    tasks = run.get("tasks") if isinstance(run.get("tasks"), list) else []
    task_bits: list[str] = []
    for item in tasks[:3]:
        if not isinstance(item, dict):
            continue
        task = item.get("task") if isinstance(item.get("task"), dict) else {}
        node = str(item.get("target_node") or task.get("target_node") or "node")
        status = str(task.get("status") or ("dry-run" if item.get("dry_run") else "unknown"))
        reason = str(task.get("reason") or "")
        task_bits.append(f"{node}:{status}{'/' + reason if reason else ''}")
    task_text = ", ".join(task_bits) or "no node task"
    return clipped(f"{surfaces}; probes failed {failed_probe_count}; findings {finding_count}; tasks {task_text}; value {verdict}", 420)


def compact_security_loop_run(latest: dict[str, Any]) -> dict[str, Any]:
    tasks = []
    for item in latest.get("tasks") if isinstance(latest.get("tasks"), list) else []:
        if not isinstance(item, dict):
            continue
        task = item.get("task") if isinstance(item.get("task"), dict) else {}
        tasks.append({
            "target_node": clipped(str(item.get("target_node") or task.get("target_node") or "node"), 80),
            "status": clipped(str(task.get("status") or ("dry-run" if item.get("dry_run") else "unknown")), 40),
            "reason": clipped(str(task.get("reason") or ""), 120),
            "clean_repeat_streak": int(task.get("clean_repeat_streak") or 0),
            "max_clean_repeat": int(task.get("max_clean_repeat") or 0),
            "run_id": clipped(str(task.get("run_id") or task.get("task_id") or ""), 120),
            "api_url": clipped(str(task.get("api_url") or ""), 180),
            "has_response": bool((task.get("result") if isinstance(task.get("result"), dict) else {}).get("response")),
            "error": clipped(str(task.get("error") or ""), 500),
            "stop_status": task.get("stop_status") if isinstance(task.get("stop_status"), dict) else {},
        })
    raw_value = latest.get("value") if isinstance(latest.get("value"), dict) else {}
    value = {
        "verdict": clipped(str(raw_value.get("verdict") or ""), 80),
        "recommendation": clipped(str(raw_value.get("recommendation") or ""), 500),
        "launch_candidate": bool(raw_value.get("launch_candidate")),
        "token_delta": int(raw_value.get("token_delta") or 0),
        "api_call_delta": int(raw_value.get("api_call_delta") or 0),
        "clean_repeat_streak_before": int(raw_value.get("clean_repeat_streak_before") or 0),
        "clean_repeat_streak_after": int(raw_value.get("clean_repeat_streak_after") or 0),
        "max_clean_repeat": int(raw_value.get("max_clean_repeat") or 0),
    } if raw_value else {}
    return {
        "run_id": clipped(str(latest.get("run_id") or ""), 120),
        "run_key": clipped(str(latest.get("run_key") or ""), 40),
        "runner_status": clipped(str(latest.get("runner_status") or ("completed" if latest.get("finished_at") else "unknown")), 40),
        "mode": clipped(str(latest.get("mode") or ""), 40),
        "delivery": clipped(str(latest.get("delivery") or ""), 40),
        "started_at": clipped(str(latest.get("started_at") or ""), 40),
        "finished_at": clipped(str(latest.get("finished_at") or ""), 40),
        "probe_count": int(latest.get("probe_count") or 0),
        "failed_probe_count": int(latest.get("failed_probe_count") or 0),
        "finding_count": int(latest.get("finding_count") or len(latest.get("findings") if isinstance(latest.get("findings"), list) else [])),
        "error_count": len(latest.get("errors") if isinstance(latest.get("errors"), list) else []),
        "errors": [clipped(str(error), 500) for error in (latest.get("errors") if isinstance(latest.get("errors"), list) else [])[:4]],
        "value": value,
        "tasks": tasks,
        "summary": security_loop_run_summary(latest),
    }


def list_security_loop_runs(server: WasmAgentServer, *, limit: int = 24) -> dict[str, Any]:
    if limit < 1 or limit > 200:
        raise BrowserError("invalid_limit", "limit must be between 1 and 200.", status=HTTPStatus.BAD_REQUEST)
    run_dir = security_loop_dir(server) / "runs"
    runs: list[dict[str, Any]] = []
    if run_dir.exists():
        for path in sorted(run_dir.glob("security-run-*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            raw = read_json_file(path, {})
            if isinstance(raw, dict):
                runs.append(compact_security_loop_run(raw))
            if len(runs) >= limit:
                break
    return {
        "ok": True,
        "schema": "hermes.security_loop.runs.v1",
        "runs": runs,
    }


def security_loop_append(server: WasmAgentServer, payload: dict[str, Any]) -> None:
    path = security_loop_findings_path(server)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n")


SECURITY_LOOP_STATUSES = {"new", "triaged", "accepted", "rejected", "mitigating", "resolved", "watching"}
SECURITY_SEVERITY_WEIGHT = {"info": 5, "low": 20, "medium": 45, "high": 75, "critical": 90}
SECURITY_SURFACE_WEIGHT = {
    "auth": 8,
    "bridge": 8,
    "browser": 7,
    "storage": 6,
    "config": 5,
    "service-worker": 4,
    "ui": 2,
}


def security_score(severity: str, confidence: float, exploitability: float, surface: str) -> int:
    base = SECURITY_SEVERITY_WEIGHT.get(severity, 20)
    surface_bonus = SECURITY_SURFACE_WEIGHT.get(surface, 3)
    confidence_bonus = max(0, min(1, confidence)) * 7
    exploit_bonus = max(0, min(1, exploitability)) * 8
    return max(0, min(100, round(base + surface_bonus + confidence_bonus + exploit_bonus)))


def bounded_float(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return max(0.0, min(1.0, number))


def positive_int(value: Any, fallback: int = 1) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = fallback
    return max(1, number)


def security_finding_fingerprint(finding: dict[str, Any]) -> str:
    parts = [
        str(finding.get("source_node") or "").strip().lower(),
        str(finding.get("target_surface") or finding.get("surface") or "").strip().lower(),
        str(finding.get("category") or "").strip().lower(),
        str(finding.get("summary") or "").strip().lower(),
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8", "replace")).hexdigest()[:24]


def security_finding_current(server: WasmAgentServer) -> dict[str, dict[str, Any]]:
    payload = read_json_file(security_loop_current_path(server), {})
    return payload if isinstance(payload, dict) else {}


def write_security_finding_current(server: WasmAgentServer, current: dict[str, dict[str, Any]]) -> None:
    write_json_file(security_loop_current_path(server), current)
    write_json_file(security_loop_summary_path(server), security_loop_status(server, current=current)["security_loop"])


def normalize_security_finding(raw: dict[str, Any], user: dict[str, Any] | None) -> dict[str, Any]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    severity = str(raw.get("severity") or "low").strip().lower()
    if severity not in SECURITY_SEVERITY_WEIGHT:
        severity = "low"
    status = str(raw.get("status") or "new").strip().lower()
    if status not in SECURITY_LOOP_STATUSES:
        status = "new"
    confidence = bounded_float(raw.get("confidence"), 0.5)
    exploitability = bounded_float(raw.get("exploitability"), 0.25)
    target_surface = safe_state_id(str(raw.get("target_surface") or raw.get("surface") or "unknown"), "unknown")
    finding_id = safe_state_id(str(raw.get("id") or raw.get("finding_id") or ""), "")
    if not finding_id:
        finding_id = f"finding-{uuid.uuid4().hex[:16]}"
    reporter = {
        "id": str((user or {}).get("id") or ""),
        "email": str((user or {}).get("email") or ""),
        "role": str((user or {}).get("role") or ""),
    } if user else None
    finding = {
        "schema": "hermes.security_loop.finding.v1",
        "id": finding_id,
        "created_at": clipped(str(raw.get("created_at") or now), 40),
        "updated_at": now,
        "source_node": safe_state_id(str(raw.get("source_node") or "hermes-attack"), "hermes-attack"),
        "target_surface": target_surface,
        "category": clipped(str(raw.get("category") or "probe"), 80),
        "severity": severity,
        "confidence": confidence,
        "exploitability": exploitability,
        "score": security_score(severity, confidence, exploitability, target_surface),
        "status": status,
        "fingerprint": clipped(str(raw.get("fingerprint") or security_finding_fingerprint(raw)), 80),
        "first_seen_at": clipped(str(raw.get("first_seen_at") or raw.get("created_at") or now), 40),
        "last_seen_at": now,
        "occurrence_count": positive_int(raw.get("occurrence_count"), 1),
        "summary": clipped(str(raw.get("summary") or "Security finding"), 360),
        "evidence_preview": clipped(str(raw.get("evidence_preview") or raw.get("evidence") or ""), 900),
        "task_id": clipped(str(raw.get("task_id") or ""), 96),
        "proposed_action": clipped(str(raw.get("proposed_action") or ""), 900),
        "decision_reason": clipped(str(raw.get("decision_reason") or ""), 500),
        "decided_by": str(raw.get("decided_by") or ""),
        "decided_at": str(raw.get("decided_at") or ""),
        "reported_by": reporter,
    }
    return finding


def save_security_loop_finding(
    server: WasmAgentServer,
    body: dict[str, Any],
    user: dict[str, Any] | None,
) -> dict[str, Any]:
    raw = body.get("finding") if isinstance(body.get("finding"), dict) else body
    finding = normalize_security_finding(raw, user)
    current = security_finding_current(server)
    raw_status_supplied = isinstance(raw, dict) and "status" in raw
    matching_id = ""
    for item_id, item in current.items():
        fingerprint = str(item.get("fingerprint") or security_finding_fingerprint(item))
        if fingerprint == finding["fingerprint"]:
            matching_id = item_id
            break
    if matching_id:
        existing = current[matching_id]
        occurrence_count = positive_int(existing.get("occurrence_count"), 1) + 1
        finding = {
            **finding,
            "id": existing.get("id") or matching_id,
            "created_at": existing.get("created_at") or finding["created_at"],
            "first_seen_at": existing.get("first_seen_at") or existing.get("created_at") or finding["first_seen_at"],
            "occurrence_count": occurrence_count,
        }
        if not raw_status_supplied and str(existing.get("status") or "") in SECURITY_LOOP_STATUSES:
            finding = {
                **finding,
                "status": existing["status"],
                "decision_reason": existing.get("decision_reason") or finding["decision_reason"],
                "decided_by": existing.get("decided_by") or finding["decided_by"],
                "decided_at": existing.get("decided_at") or finding["decided_at"],
            }
        current.pop(finding["id"], None)
    current[finding["id"]] = finding
    event = {"event": "finding_saved", "finding": finding, "recorded_at": finding["updated_at"]}
    if matching_id:
        event["deduped"] = True
        event["matched_finding_id"] = matching_id
    security_loop_append(server, event)
    write_security_finding_current(server, current)
    return {"ok": True, "finding": finding, "security_loop": security_loop_status(server, current=current)["security_loop"]}


def decide_security_loop_finding(
    server: WasmAgentServer,
    finding_id: str,
    body: dict[str, Any],
    user: dict[str, Any] | None,
) -> dict[str, Any]:
    clean_id = safe_state_id(finding_id, "")
    current = security_finding_current(server)
    finding = current.get(clean_id)
    if not finding:
        raise BrowserError("security_finding_not_found", "Security finding was not found.", status=HTTPStatus.NOT_FOUND)
    status = str(body.get("status") or body.get("decision") or "").strip().lower()
    if status not in SECURITY_LOOP_STATUSES:
        raise BrowserError("invalid_security_status", "Unsupported security finding status.")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    finding = {
        **finding,
        "status": status,
        "updated_at": now,
        "decision_reason": clipped(str(body.get("reason") or body.get("decision_reason") or ""), 500),
        "decided_by": str((user or {}).get("email") or (user or {}).get("id") or ""),
        "decided_at": now,
    }
    current[clean_id] = finding
    security_loop_append(server, {"event": "finding_decided", "finding": finding, "recorded_at": now})
    write_security_finding_current(server, current)
    return {"ok": True, "finding": finding, "security_loop": security_loop_status(server, current=current)["security_loop"]}


def list_security_loop_findings(server: WasmAgentServer, *, limit: int = 80) -> dict[str, Any]:
    current = security_finding_current(server)
    findings = sorted(
        current.values(),
        key=lambda item: (int(item.get("score") or 0), str(item.get("updated_at") or item.get("created_at") or "")),
        reverse=True,
    )[:max(1, min(200, limit))]
    return {
        "ok": True,
        "schema": "hermes.security_loop.findings.v1",
        "security_loop": security_loop_status(server, current=current)["security_loop"],
        "findings": findings,
    }


def security_loop_status(
    server: WasmAgentServer,
    *,
    current: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    findings = list((current if current is not None else security_finding_current(server)).values())
    open_statuses = {"new", "triaged", "accepted", "mitigating", "watching"}
    open_findings = [item for item in findings if str(item.get("status") or "") in open_statuses]
    latest = max((str(item.get("updated_at") or item.get("created_at") or "") for item in findings), default="")
    latest_epoch = 0.0
    if latest:
        try:
            latest_epoch = time.mktime(time.strptime(latest.replace("Z", ""), "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            latest_epoch = 0.0
    stale = not latest_epoch or time.time() - latest_epoch > SECURITY_LOOP_STALE_AFTER_SEC
    return {
        "ok": True,
        "schema": "hermes.security_loop.status.v1",
        "security_loop": {
            "actors": {"attack": "hermes-attack", "defense": "hermes-defense"},
            "latest_run": security_loop_latest_run(server),
            "latest_run_at": latest,
            "stale": stale,
            "stale_after_sec": SECURITY_LOOP_STALE_AFTER_SEC,
            "open_count": len(open_findings),
            "critical_count": sum(1 for item in open_findings if item.get("severity") == "critical"),
            "accepted_count": sum(1 for item in findings if item.get("status") == "accepted"),
            "rejected_count": sum(1 for item in findings if item.get("status") == "rejected"),
            "resolved_count": sum(1 for item in findings if item.get("status") == "resolved"),
            "top_score": max((int(item.get("score") or 0) for item in open_findings), default=0),
            "finding_count": len(findings),
        },
    }


def is_public_request(method: str, path: str) -> bool:
    method = method.upper()
    if method == "OPTIONS":
        return True
    if method == "GET":
        if path in {
            "/",
            "/home",
            "/admin",
            "/space",
            "/fleet",
            "/tasks",
            "/logs",
            "/observe",
            "/timeline",
            "/modules",
            "/composer-lab",
            "/composer-lab.html",
            "/composer-lab.js",
            "/voice-lab",
            "/voice-lab.html",
            "/voice-lab.css",
            "/voice-lab.js",
            "/index.html",
            "/styles.css",
            "/boot.js",
            "/app.js",
            "/provider-model-catalog.js",
            "/manifest.webmanifest",
            "/sw.js",
            "/config.json",
            "/auth/session",
            "/auth/google/callback",
        }:
            return True
        if path.startswith("/icons/"):
            return True
        if path.startswith("/modules/") and (path.endswith(".js") or path.endswith(".css")):
            return True
        return False
    if method == "POST":
        return path in {"/auth/google", "/auth/google/callback", "/auth/logout"}
    return False


def requires_admin_request(method: str, path: str) -> bool:
    method = method.upper()
    if path.startswith(("/bridge/", "/browser/", "/security-loop/")):
        return True
    if path.startswith("/agent/models/"):
        return True
    if path.startswith("/timeline/") and path not in {"/timeline/status", "/timeline/stepback"}:
        return True
    return False


def request_origin(handler: WasmAgentHandler) -> str:
    return str(handler.headers.get("Origin") or "").strip().rstrip("/")


def request_host_origin(handler: WasmAgentHandler) -> str:
    proto = str(handler.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip()
    if not proto:
        proto = "https" if public_origin().lower().startswith("https://") else "http"
    host = str(handler.headers.get("X-Forwarded-Host") or handler.headers.get("Host") or "").split(",", 1)[0].strip()
    return f"{proto}://{host}".rstrip("/") if host else ""


def google_login_origin(handler: WasmAgentHandler) -> str:
    return public_origin() or request_host_origin(handler)


def google_login_uri(handler: WasmAgentHandler) -> str:
    origin = google_login_origin(handler)
    return f"{origin}/auth/google/callback" if origin else "/auth/google/callback"


def same_origin_post(handler: WasmAgentHandler) -> bool:
    origin = request_origin(handler)
    if not origin:
        return True
    allowed = {item for item in {public_origin(), request_host_origin(handler)} if item}
    return origin in allowed


def same_origin_websocket(handler: WasmAgentHandler) -> bool:
    origin = request_origin(handler)
    if not origin:
        return False
    allowed = {item for item in {public_origin(), request_host_origin(handler)} if item}
    return origin in allowed


def bridge_route_allowed(method: str, path: str) -> bool:
    method = method.upper()
    if not path.startswith("/") or path.startswith("/bridge/") or "://" in path:
        return False
    if method == "GET":
        if path in {"/health", "/nodes", "/resources", "/tasks", "/capabilities", "/v1/models"}:
            return True
        if re.fullmatch(r"/nodes/[A-Za-z0-9_.-]+", path):
            return True
        if re.fullmatch(r"/nodes/[A-Za-z0-9_.-]+/logs", path):
            return True
        if re.fullmatch(r"/nodes/[A-Za-z0-9_.-]+/stats", path):
            return True
        if re.fullmatch(r"/tasks/[A-Za-z0-9_.:-]+", path):
            return True
        return False
    if method == "POST":
        if path in {"/nodes", "/task", "/tasks", "/drop-to-copy/tasks"}:
            return True
        if re.fullmatch(r"/nodes/[A-Za-z0-9_.-]+/action", path):
            return True
        if re.fullmatch(r"/nodes/[A-Za-z0-9_.-]+/prompt", path):
            return True
        if re.fullmatch(r"/tasks/[A-Za-z0-9_.:-]+/stop", path):
            return True
    return False


def bridge_proxy(
    server: WasmAgentServer,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    *,
    timeout: float = 20,
) -> dict[str, Any]:
    if not path.startswith("/"):
        path = f"/{path}"
    parsed = urlparse(path)
    path_only = parsed.path or "/"
    if not bridge_route_allowed(method, path_only):
        raise BrowserError("bridge_route_not_allowed", "Bridge route is not allowed from wasm-agent.", status=HTTPStatus.FORBIDDEN)
    url = f"{server.bridge_url}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if method.upper() == "POST":
        data = json.dumps(body or {}).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        if int(exc.code) == 403:
            raise BrowserError("bridge_forbidden", detail or "Bridge rejected this request.", status=HTTPStatus.FORBIDDEN) from exc
        raise BrowserError("bridge_http_error", detail or str(exc), status=HTTPStatus.BAD_GATEWAY) from exc
    except URLError as exc:
        raise BrowserError("bridge_unavailable", str(exc.reason), status=HTTPStatus.BAD_GATEWAY) from exc
    except TimeoutError as exc:
        raise BrowserError("bridge_timeout", f"Bridge request timed out after {timeout:g}s.", status=HTTPStatus.BAD_GATEWAY) from exc
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"raw": raw}
    return payload if isinstance(payload, dict) else {"result": payload}


def verify_google_id_token(credential: str, client_id: str) -> dict[str, Any]:
    if not client_id:
        raise BrowserError("google_login_not_configured", "Google login needs HERMES_WASM_AGENT_GOOGLE_CLIENT_ID.")
    if not credential:
        raise BrowserError("missing_google_credential", "Google credential is required.")
    request = Request(
        f"https://oauth2.googleapis.com/tokeninfo?id_token={quote(credential, safe='')}",
        headers={"Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=8) as response:
            claims = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            detail = str(payload.get("error_description") or payload.get("error") or exc.reason)
        except Exception:
            detail = str(exc.reason)
        raise BrowserError("google_token_rejected", f"Google rejected the credential: {detail}") from exc
    except URLError as exc:
        raise BrowserError(
            "google_token_verify_unavailable",
            f"Could not reach Google token verification: {exc.reason}",
            status=HTTPStatus.BAD_GATEWAY,
        ) from exc
    if str(claims.get("aud") or "") != client_id:
        raise BrowserError("google_audience_mismatch", "Google credential audience does not match this app.")
    if str(claims.get("iss") or "") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise BrowserError("google_issuer_mismatch", "Google credential issuer is not supported.")
    if not str(claims.get("sub") or "").strip():
        raise BrowserError("google_subject_missing", "Google credential did not include an account id.")
    return claims


def google_auth_login(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    claims = verify_google_id_token(str(body.get("credential") or "").strip(), google_client_id())
    now = int(time.time())
    provider_sub = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    email_verified = str(claims.get("email_verified") or "").lower() in {"1", "true", "yes"}
    if not email_verified:
        raise BrowserError(
            "google_email_unverified",
            "Google did not mark this email as verified.",
            status=HTTPStatus.FORBIDDEN,
        )
    if not is_allowed_account_email(email):
        raise BrowserError(
            "google_account_not_allowed",
            "This Google account is not allowed to access wasm-agent.",
            status=HTTPStatus.FORBIDDEN,
        )
    name = str(claims.get("name") or email or "Google User").strip()
    picture_url = str(claims.get("picture") or "").strip()
    with auth_connect() as conn:
        row = conn.execute(
            "SELECT * FROM user_tb WHERE provider = ? AND provider_sub = ?",
            ("google", provider_sub),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE user_tb
                   SET email = ?, email_verified = ?, name = ?, picture_url = ?,
                       updated_at = ?, last_login_at = ?
                 WHERE id = ?
                """,
                (email, int(email_verified), name, picture_url, now, now, int(row["id"])),
            )
            user_id = int(row["id"])
        else:
            user_id = next_snowflake_id()
            conn.execute(
                """
                INSERT INTO user_tb (
                  id, provider, provider_sub, email, email_verified, name,
                  picture_url, created_at, updated_at, last_login_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, "google", provider_sub, email, int(email_verified), name, picture_url, now, now, now),
            )
        stored = conn.execute("SELECT * FROM user_tb WHERE id = ?", (user_id,)).fetchone()
    return {"ok": True, "authenticated": True, "user": public_user(stored)}


def chromium_command() -> str:
    command = os.getenv("HERMES_WASM_AGENT_CHROMIUM", "").strip()
    if command:
        return command
    for candidate in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(candidate)
        if found:
            return found
    raise BrowserError(
        "chromium_not_found",
        "Chromium was not found. Set HERMES_WASM_AGENT_CHROMIUM to a browser binary.",
        status=HTTPStatus.SERVICE_UNAVAILABLE,
    )


def normalized_browser_url(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        raise BrowserError("missing_url", "A URL is required.")
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BrowserError("invalid_url", "Only http and https URLs are supported.")
    if not private_targets_allowed():
        reject_private_target(parsed.hostname)
    return value


def browser_dimensions(body: dict[str, Any]) -> tuple[int, int]:
    return (
        int(clamp_number(body.get("width") or 1280, 360, 1920)),
        int(clamp_number(body.get("height") or 800, 240, 1400)),
    )


def private_targets_allowed() -> bool:
    return os.getenv("HERMES_WASM_AGENT_BROWSER_ALLOW_PRIVATE", "").lower() in {"1", "true", "yes", "on"}


def reject_private_target(hostname: str) -> None:
    lowered = hostname.lower().strip("[]")
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".localhost"):
        raise BrowserError("private_url_blocked", "Localhost browser targets are disabled by default.")
    try:
        infos = socket.getaddrinfo(lowered, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BrowserError("dns_failed", f"Could not resolve browser target: {hostname}") from exc
    for info in infos:
        address = info[4][0]
        try:
            parsed = ip_address(address)
        except ValueError:
            continue
        if parsed.is_private or parsed.is_loopback or parsed.is_link_local or parsed.is_reserved:
            raise BrowserError(
                "private_url_blocked",
                "Private, loopback, link-local, and reserved browser targets are disabled by default.",
            )


def observation_path(server: WasmAgentServer, user: dict[str, Any] | None = None) -> Path:
    return user_observation_path(server, user)


def save_observation(server: WasmAgentServer, body: dict[str, Any], user: dict[str, Any] | None = None) -> dict[str, Any]:
    schema = str(body.get("schema") or "")
    if schema != "hermes.space_os.observation.v1":
        raise BrowserError("invalid_observation", "Observation payload schema is not supported.")
    payload = dict(body)
    payload["received_at"] = int(time.time())
    ensure_user_quota(server, user, len(json.dumps(payload, ensure_ascii=True).encode("utf-8")))
    path = observation_path(server, user)
    write_json_file(path, payload)
    last_event = (payload.get("user_events") or [{}])[0]
    return {
        "schema": schema,
        "stored": True,
        "received_at": payload["received_at"],
        "event_count": payload.get("analytics", {}).get("event_count", 0),
        "last_event": last_event if isinstance(last_event, dict) else {},
    }


def latest_observation(server: WasmAgentServer, user: dict[str, Any] | None = None) -> dict[str, Any]:
    path = observation_path(server, user)
    if not path.exists():
        return {"ok": True, "observation": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BrowserError("observation_read_failed", f"Could not read latest observation: {exc}") from exc
    return {"ok": True, "observation": payload}


def clamp_client_snapshot_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return clipped(str(value), 400)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(float(value)) else 0
    if isinstance(value, str):
        return clipped(value, 12000 if depth <= 4 else 2000)
    if isinstance(value, list):
        limit = 80 if depth <= 2 else 40
        return [clamp_client_snapshot_value(item, depth=depth + 1) for item in value[:limit]]
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        limit = 120 if depth <= 2 else 80
        for key, item in list(value.items())[:limit]:
            clean_key = clipped(str(key), 120)
            if clean_key.lower() in {"apikey", "api_key", "authorization", "password", "secret", "token"}:
                output[clean_key] = "[redacted]"
            else:
                output[clean_key] = clamp_client_snapshot_value(item, depth=depth + 1)
        return output
    return clipped(str(value), 1200)


def prune_client_snapshots(root: Path) -> None:
    snapshots = []
    for path in root.glob("snapshot_*.json"):
        try:
            snapshots.append((path.stat().st_mtime, path))
        except OSError:
            continue
    for _mtime, path in sorted(snapshots, reverse=True)[CLIENT_SNAPSHOT_HISTORY_LIMIT:]:
        try:
            path.unlink()
        except OSError:
            continue


def save_client_snapshot(
    server: WasmAgentServer,
    body: dict[str, Any],
    user: dict[str, Any] | None = None,
    handler: WasmAgentHandler | None = None,
) -> dict[str, Any]:
    schema = str(body.get("schema") or "")
    if schema != CLIENT_SNAPSHOT_SCHEMA:
        raise BrowserError("invalid_client_snapshot", "Client snapshot payload schema is not supported.")
    snapshot_id = safe_state_id(str(body.get("snapshot_id") or f"snapshot_{next_snowflake_id():x}"), "snapshot")
    payload = clamp_client_snapshot_value(body)
    if not isinstance(payload, dict):
        raise BrowserError("invalid_client_snapshot", "Client snapshot payload must be an object.")
    received_at = iso_timestamp()
    device_id = request_account_device_id(user, handler) if handler else ""
    payload.update({
        "schema": CLIENT_SNAPSHOT_SCHEMA,
        "snapshot_id": snapshot_id,
        "server_received_at": received_at,
        "server_user_id": user_id(user),
        "server_device_id": device_id,
    })
    encoded = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    if len(encoded) > CLIENT_SNAPSHOT_MAX_STORED_BYTES:
        raise BrowserError(
            "client_snapshot_too_large",
            "Client snapshot exceeds the 1 MB stored debug limit.",
            status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        )
    ensure_user_quota(server, user, len(encoded))
    root = user_client_snapshot_dir(server, user)
    snapshot_path = root / f"snapshot_{snapshot_id}.json"
    latest_path = user_client_snapshot_latest_path(server, user)
    write_json_file(snapshot_path, payload)
    write_json_file(latest_path, payload)
    prune_client_snapshots(root)
    sessions = payload.get("sessions") if isinstance(payload.get("sessions"), list) else []
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.client_snapshot.result.v1",
        "stored": True,
        "snapshot_id": snapshot_id,
        "received_at": received_at,
        "device_id": device_id,
        "session_count": len(sessions),
        "active_session_id": str(payload.get("active_session_id") or ""),
        "path": repo_relative_string(server, snapshot_path),
        "latest_path": repo_relative_string(server, latest_path),
        "bytes": len(encoded),
    }


def latest_client_snapshot(server: WasmAgentServer, user: dict[str, Any] | None = None) -> dict[str, Any]:
    path = user_client_snapshot_latest_path(server, user)
    if not path.exists():
        return {"ok": True, "schema": CLIENT_SNAPSHOT_SCHEMA, "snapshot": None}
    payload = read_json_file(path, {})
    if not isinstance(payload, dict):
        raise BrowserError("client_snapshot_read_failed", "Could not read latest client snapshot.")
    return {
        "ok": True,
        "schema": CLIENT_SNAPSHOT_SCHEMA,
        "snapshot": payload,
        "path": repo_relative_string(server, path),
    }


def normalize_client_snapshot_scope(value: Any) -> str:
    scope = str(value or "all").strip().lower()
    return scope if scope in {"context", "tokens", "state", "all"} else "all"


def create_client_snapshot_request(
    server: WasmAgentServer,
    body: dict[str, Any],
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_id = safe_state_id(str(body.get("request_id") or body.get("requestId") or f"req_{next_snowflake_id():x}"), "request")
    now = iso_timestamp()
    request = {
        "schema": CLIENT_SNAPSHOT_REQUEST_SCHEMA,
        "type": "client.snapshot.request",
        "request_id": request_id,
        "scope": normalize_client_snapshot_scope(body.get("scope")),
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "server_user_id": user_id(user),
        "source": clipped(str(body.get("source") or "server"), 120),
        "target_device_id": clipped(str(body.get("target_device_id") or body.get("device_id") or ""), 120),
    }
    write_json_file(client_snapshot_request_path(server, user, request_id), request)
    return {"ok": True, "schema": CLIENT_SNAPSHOT_REQUEST_SCHEMA, "request": request}


def list_client_snapshot_requests(
    server: WasmAgentServer,
    user: dict[str, Any] | None = None,
    *,
    status: str = "pending",
) -> dict[str, Any]:
    wanted = str(status or "pending").strip().lower()
    requests: list[dict[str, Any]] = []
    for path in sorted(user_client_snapshot_request_dir(server, user).glob("request_*.json")):
        payload = read_json_file(path, {})
        if not isinstance(payload, dict):
            continue
        if wanted and str(payload.get("status") or "").lower() != wanted:
            continue
        requests.append(payload)
    requests.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {
        "ok": True,
        "schema": CLIENT_SNAPSHOT_REQUEST_SCHEMA,
        "requests": requests[:20],
    }


def save_client_snapshot_response(
    server: WasmAgentServer,
    body: dict[str, Any],
    user: dict[str, Any] | None = None,
    handler: WasmAgentHandler | None = None,
) -> dict[str, Any]:
    schema = str(body.get("schema") or "")
    if schema and schema != CLIENT_SNAPSHOT_RESPONSE_SCHEMA:
        raise BrowserError("invalid_client_snapshot_response", "Client snapshot response schema is not supported.")
    request_id = safe_state_id(str(body.get("request_id") or body.get("requestId") or ""), "")
    if not request_id:
        raise BrowserError("invalid_client_snapshot_response", "Client snapshot response requires request_id.")
    now = iso_timestamp()
    ok = bool(body.get("ok"))
    request_path = client_snapshot_request_path(server, user, request_id)
    request = read_json_file(request_path, {})
    if not isinstance(request, dict):
        request = {}
    snapshot_result: dict[str, Any] | None = None
    if ok:
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise BrowserError("invalid_client_snapshot_response", "Successful client snapshot response requires a payload.")
        payload = dict(payload)
        payload["request_id"] = request_id
        payload["request_scope"] = normalize_client_snapshot_scope(request.get("scope") or payload.get("scope"))
        snapshot_result = save_client_snapshot(server, payload, user=user, handler=handler)
    response = {
        "schema": CLIENT_SNAPSHOT_RESPONSE_SCHEMA,
        "type": "client.snapshot.response",
        "request_id": request_id,
        "ok": ok,
        "received_at": now,
        "server_user_id": user_id(user),
        "device_id": request_account_device_id(user, handler) if handler else "",
        "snapshot_id": snapshot_result.get("snapshot_id", "") if snapshot_result else "",
        "error": clamp_client_snapshot_value(body.get("error") if isinstance(body.get("error"), dict) else {}),
    }
    response_path = user_client_snapshot_response_dir(server, user) / f"response_{request_id}.json"
    write_json_file(response_path, response)
    if request:
        request.update({
            "status": "responded" if ok else "failed",
            "updated_at": now,
            "responded_at": now,
            "response_path": repo_relative_string(server, response_path),
            "snapshot_id": response["snapshot_id"],
        })
        write_json_file(request_path, request)
    return {
        "ok": True,
        "schema": CLIENT_SNAPSHOT_RESPONSE_SCHEMA,
        "request_id": request_id,
        "stored": ok,
        "snapshot": snapshot_result,
        "bytes": snapshot_result.get("bytes", 0) if snapshot_result else 0,
        "response_path": repo_relative_string(server, response_path),
    }


def git_run(
    server: WasmAgentServer,
    args: list[str],
    *,
    timeout: float = 8,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        ["git", "-C", str(repo_root(server)), *args],
        text=True,
        capture_output=True,
        timeout=timeout,
        env=run_env,
        check=False,
    )


def git_output(server: WasmAgentServer, args: list[str], *, timeout: float = 8) -> str:
    proc = git_run(server, args, timeout=timeout)
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def timeline_ref_name(raw: str) -> str:
    base = "".join(ch.lower() if ch.isalnum() else "-" for ch in raw.strip())[:48].strip("-")
    return base or f"checkpoint-{int(time.time())}"


def timeline_metadata_by_ref(metadata_dir: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not metadata_dir.exists():
        return records
    for path in sorted(metadata_dir.glob("*.json"), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)[:240]:
        if path.name == "auto-latest.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        ref = str(payload.get("ref") or "")
        if ref:
            records[ref] = payload
    return records


def timeline_status(server: WasmAgentServer, user: dict[str, Any] | None = None, *, space_id: str = "home") -> dict[str, Any]:
    branch = git_output(server, ["branch", "--show-current"]) or "detached"
    head = git_output(server, ["rev-parse", "--short", "HEAD"])
    head_full = git_output(server, ["rev-parse", "HEAD"])
    status = git_output(server, ["status", "--short"], timeout=5)
    recent_raw = git_output(server, ["log", "--oneline", "--decorate", "-8"], timeout=5)
    branches_raw = git_output(server, ["branch", "--format=%(refname:short)|%(objectname:short)|%(committerdate:relative)"], timeout=5)
    timeline_id = safe_state_id(space_id, "home")
    timeline_root = user_timeline_dir(server, user, timeline_id)
    metadata_by_ref = timeline_metadata_by_ref(timeline_root)
    checkpoints_raw = git_output(
        server,
        [
            "for-each-ref",
            f"refs/wasm-agent-timeline/{user_id(user)}/{timeline_id}",
            "--sort=-creatordate",
            "--format=%(refname)|%(refname:short)|%(objectname:short)|%(creatordate:iso8601)|%(subject)",
        ],
        timeout=5,
    )
    checkpoints: list[dict[str, Any]] = []
    for item in checkpoints_raw.splitlines() if checkpoints_raw else []:
        parts = item.split("|")
        if len(parts) < 5:
            continue
        ref, short_ref, object_head, created_at = parts[:4]
        subject = "|".join(parts[4:])
        metadata = metadata_by_ref.get(ref, {})
        checkpoints.append(
            {
                "ref": ref,
                "name": short_ref.replace(f"wasm-agent-timeline/{user_id(user)}/{timeline_id}/", "", 1),
                "head": object_head,
                "created_at": created_at,
                "subject": subject,
                "phase": metadata.get("phase") or "checkpoint",
                "before_ref": metadata.get("before_ref") or "",
                "after_ref": metadata.get("after_ref") or "",
                "changed_count": len(metadata.get("changed_files") or []),
                "scope": metadata.get("scope") or "",
            }
        )
    return {
        "schema": "hermes.wasm_agent.timeline.v1",
        "branch": branch,
        "head": head,
        "head_full": head_full,
        "user_id": user_id(user),
        "timeline_id": timeline_id,
        "storage_root": str(timeline_root),
        "dirty": bool(status),
        "dirty_count": len(status.splitlines()) if status else 0,
        "status_preview": status.splitlines()[:16],
        "recent": recent_raw.splitlines() if recent_raw else [],
        "branches": [
            {"name": item.split("|")[0], "head": item.split("|")[1], "updated": item.split("|")[2]}
            for item in branches_raw.splitlines()
            if item.count("|") >= 2
        ][:12],
        "checkpoints": checkpoints[:24],
        "actions": [
            {
                "id": "auto_checkpoint_on_change",
                "label": "Auto",
                "enabled": True,
                "description": "Chat turns create named git timeline refs automatically when the worktree changes.",
            },
            {
                "id": "branch_from_checkpoint",
                "label": "Branch",
                "enabled": False,
                "description": "Planned confirmation-gated action: create a branch from a selected checkpoint.",
            },
            {
                "id": "merge_checkpoint",
                "label": "Merge",
                "enabled": False,
                "description": "Planned confirmation-gated action: merge a selected branch/checkpoint.",
            },
            {
                "id": "restore_checkpoint",
                "label": "Stepback",
                "enabled": True,
                "description": "Confirmation-gated action: restore the workspace to the selected run's before-checkpoint.",
            },
        ],
    }


def timeline_checkpoint(server: WasmAgentServer, body: dict[str, Any], user: dict[str, Any] | None = None) -> dict[str, Any]:
    label = timeline_ref_name(str(body.get("label") or "manual-checkpoint"))
    message = clipped(str(body.get("message") or f"wasm-agent timeline checkpoint: {label}"), 180)
    space_id = safe_state_id(str(body.get("space_id") or "home"), "home")
    return create_timeline_checkpoint(server, label=label, message=message, automatic=False, user=user, space_id=space_id)


def checkpoint_tree(server: WasmAgentServer, metadata_dir: Path) -> tuple[str, Path]:
    temp_index = metadata_dir / f"checkpoint-{uuid.uuid4().hex}.index"
    index_env = {"GIT_INDEX_FILE": str(temp_index)}
    read_tree = git_run(server, ["read-tree", "HEAD"], timeout=8, env=index_env)
    if read_tree.returncode != 0:
        raise BrowserError("timeline_checkpoint_failed", clipped(read_tree.stderr or "Could not seed temporary git index."))
    add_proc = git_run(server, ["add", "-A"], timeout=20, env=index_env)
    if add_proc.returncode != 0:
        raise BrowserError("timeline_checkpoint_failed", clipped(add_proc.stderr or "Could not stage temporary checkpoint."))
    tree_proc = git_run(server, ["write-tree"], timeout=8, env=index_env)
    tree_sha = (tree_proc.stdout or "").strip()
    if tree_proc.returncode != 0 or not tree_sha:
        raise BrowserError("timeline_checkpoint_failed", clipped(tree_proc.stderr or "Could not write checkpoint tree."))
    return tree_sha, temp_index


def create_timeline_checkpoint(
    server: WasmAgentServer,
    *,
    label: str,
    message: str,
    automatic: bool,
    user: dict[str, Any] | None = None,
    space_id: str = "home",
    tree_sha: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dirty = git_output(server, ["status", "--short"], timeout=5)
    untracked = [line for line in dirty.splitlines() if line.startswith("?? ")]
    timeline_id = safe_state_id(space_id, "home")
    metadata_dir = user_timeline_dir(server, user, timeline_id)
    ensure_user_quota(server, user)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    temp_index: Path | None = None
    if tree_sha:
        verify_tree = git_run(server, ["cat-file", "-e", f"{tree_sha}^{{tree}}"], timeout=5)
        if verify_tree.returncode != 0:
            raise BrowserError("timeline_checkpoint_failed", "Timeline checkpoint tree does not exist.")
    else:
        tree_sha, temp_index = checkpoint_tree(server, metadata_dir)
    commit_proc = git_run(server, ["commit-tree", tree_sha, "-p", "HEAD", "-m", message], timeout=8)
    sha = (commit_proc.stdout or "").strip()
    if commit_proc.returncode != 0 or not sha:
        raise BrowserError("timeline_checkpoint_failed", clipped(commit_proc.stderr or "Could not create checkpoint commit."))
    ref = f"refs/wasm-agent-timeline/{user_id(user)}/{timeline_id}/{label}-{int(time.time())}"
    update_proc = git_run(server, ["update-ref", ref, sha], timeout=8)
    if update_proc.returncode != 0:
        raise BrowserError("timeline_checkpoint_failed", clipped(update_proc.stderr or "Could not write timeline ref."))
    if temp_index:
        try:
            temp_index.unlink(missing_ok=True)
        except Exception:
            pass
    metadata = {
        "schema": "hermes.wasm_agent.timeline_checkpoint.v1",
        "ref": ref,
        "sha": sha,
        "tree": tree_sha,
        "label": label,
        "user_id": user_id(user),
        "timeline_id": timeline_id,
        "storage_root": str(metadata_dir),
        "message": message,
        "created_at": int(time.time()),
        "automatic": automatic,
        "tracked_only": False,
        "untracked_count": len(untracked),
        "untracked_note": "Checkpoint uses a temporary git index and captures untracked non-ignored files without changing the real index.",
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    (metadata_dir / f"{label}-{metadata['created_at']}.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return metadata


def auto_checkpoint_state_path(server: WasmAgentServer, user: dict[str, Any] | None = None, space_id: str = "home") -> Path:
    return user_timeline_dir(server, user, space_id) / "auto-latest.json"


def timeline_auto_checkpoint(
    server: WasmAgentServer,
    reason: str,
    *,
    message: str | None = None,
    tree_sha: str | None = None,
    before_tree: str | None = None,
    before_ref: str | None = None,
    changed_files: list[dict[str, Any]] | None = None,
    user: dict[str, Any] | None = None,
    space_id: str = "home",
) -> dict[str, Any] | None:
    dirty = git_output(server, ["status", "--short"], timeout=5)
    if not dirty and (not tree_sha or before_tree == tree_sha):
        return None
    metadata_dir = user_timeline_dir(server, user, space_id)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    if tree_sha is None:
        tree_sha = worktree_tree_sha(server)
    state_path = auto_checkpoint_state_path(server, user, space_id)
    previous: dict[str, Any] = {}
    if state_path.exists():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    if previous.get("tree") == tree_sha:
        return None
    label = timeline_ref_name(f"auto-{reason}")
    metadata = create_timeline_checkpoint(
        server,
        label=label,
        message=message or f"wasm-agent auto checkpoint: {reason}",
        automatic=True,
        user=user,
        space_id=space_id,
        tree_sha=tree_sha,
        extra_metadata={
            "phase": "after_run",
            "before_tree": before_tree or "",
            "before_ref": before_ref or "",
            "after_tree": tree_sha,
            "changed_files": changed_files or [],
            "scope": timeline_scope_for_paths(server, [str(item.get("path") or "") for item in (changed_files or [])], user),
        },
    )
    state_path.write_text(
        json.dumps(
            {
                "schema": "hermes.wasm_agent.timeline_auto_checkpoint.v1",
                "tree": metadata.get("tree"),
                "sha": metadata.get("sha"),
                "ref": metadata.get("ref"),
                "reason": reason,
                "created_at": metadata.get("created_at"),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return metadata


def timeline_scope_for_paths(server: WasmAgentServer, paths: list[str], user: dict[str, Any] | None = None) -> str:
    clean_paths = [str(path or "").lstrip("/") for path in paths if str(path or "").strip()]
    if any(path_has_prefix(path, CORE_FIRMWARE_PREFIXES) for path in clean_paths):
        return "core-firmware"
    if user is not None:
        sandbox_prefix = user_sandbox_prefix(server, user)
        if clean_paths and all(path_has_prefix(path, [sandbox_prefix]) for path in clean_paths):
            return "user-sandbox"
    return "global"


def ensure_timeline_paths_allowed(server: WasmAgentServer, user: dict[str, Any] | None, paths: list[str]) -> str:
    scope = timeline_scope_for_paths(server, paths, user)
    if user_is_admin(user):
        return scope
    sandbox_prefix = user_sandbox_prefix(server, user)
    blocked = [path for path in paths if not path_has_prefix(path, [sandbox_prefix])]
    if blocked:
        raise BrowserError(
            "timeline_stepback_denied",
            "Only an admin orchestrator can step back core firmware or shared repository paths.",
            status=HTTPStatus.FORBIDDEN,
        )
    return "user-sandbox"


def resolve_timeline_ref(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    space_id: str,
    raw_ref: str,
) -> str:
    value = str(raw_ref or "").strip()
    if not value:
        raise BrowserError("timeline_missing_ref", "Timeline stepback needs a checkpoint ref.")
    if value.startswith("wasm-agent-timeline/"):
        value = f"refs/{value}"
    timeline_id = safe_state_id(space_id, "home")
    namespace = f"refs/wasm-agent-timeline/{user_id(user)}/{timeline_id}/"
    if not value.startswith(namespace):
        value = f"{namespace}{timeline_ref_name(value)}"
    verify = git_run(server, ["rev-parse", "--verify", value], timeout=5)
    if verify.returncode != 0:
        raise BrowserError("timeline_ref_not_found", "Timeline checkpoint was not found.", status=HTTPStatus.NOT_FOUND)
    return value


def checkpoint_metadata_for_ref(server: WasmAgentServer, user: dict[str, Any] | None, space_id: str, ref: str) -> dict[str, Any]:
    return timeline_metadata_by_ref(user_timeline_dir(server, user, space_id)).get(ref, {})


def commit_tree_sha(server: WasmAgentServer, ref: str) -> str:
    tree = git_output(server, ["show", "-s", "--format=%T", ref], timeout=5)
    if not tree:
        raise BrowserError("timeline_ref_invalid", "Timeline checkpoint does not point to a valid tree.")
    return tree


def diff_name_status(server: WasmAgentServer, before_tree: str, after_tree: str) -> list[tuple[str, list[str]]]:
    proc = git_run(server, ["diff", "--name-status", before_tree, after_tree], timeout=8)
    if proc.returncode != 0:
        raise BrowserError("timeline_diff_failed", clipped(proc.stderr or "Could not compare checkpoint trees."))
    rows: list[tuple[str, list[str]]] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append((parts[0], parts[1:]))
    return rows


def safe_delete_repo_path(server: WasmAgentServer, rel_path: str) -> None:
    root = repo_root(server).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise BrowserError("timeline_stepback_denied", "Restore path escaped the repository.", status=HTTPStatus.FORBIDDEN) from exc
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    else:
        try:
            target.unlink()
        except FileNotFoundError:
            pass


def restore_paths_from_tree(server: WasmAgentServer, target_tree: str, rows: list[tuple[str, list[str]]]) -> dict[str, Any]:
    restore_paths: list[str] = []
    delete_paths: list[str] = []
    for status, paths in rows:
        if not paths:
            continue
        code = status[:1]
        if code == "A":
            delete_paths.append(paths[-1])
        elif code == "R":
            if len(paths) >= 2:
                delete_paths.append(paths[-1])
                restore_paths.append(paths[0])
            else:
                restore_paths.append(paths[-1])
        else:
            restore_paths.append(paths[-1])
    for rel_path in sorted(set(delete_paths), key=lambda value: value.count("/"), reverse=True):
        safe_delete_repo_path(server, rel_path)
    restored = 0
    unique_restore_paths = sorted(set(restore_paths))
    for offset in range(0, len(unique_restore_paths), 80):
        batch = unique_restore_paths[offset:offset + 80]
        if not batch:
            continue
        proc = git_run(server, ["restore", "--source", target_tree, "--", *batch], timeout=20)
        if proc.returncode != 0:
            raise BrowserError("timeline_stepback_failed", clipped(proc.stderr or "Could not restore checkpoint paths."))
        restored += len(batch)
    return {"restored_paths": restored, "deleted_paths": len(set(delete_paths))}


def timeline_stepback(server: WasmAgentServer, body: dict[str, Any], user: dict[str, Any] | None = None) -> dict[str, Any]:
    space_id = safe_state_id(str(body.get("space_id") or body.get("timeline_id") or "home"), "home")
    requested_ref = str(body.get("ref") or body.get("checkpoint") or "")
    selected_ref = resolve_timeline_ref(server, user, space_id, requested_ref)
    selected_metadata = checkpoint_metadata_for_ref(server, user, space_id, selected_ref)
    target_ref = selected_ref
    if body.get("before_run", True) and selected_metadata.get("before_ref"):
        target_ref = resolve_timeline_ref(server, user, space_id, str(selected_metadata.get("before_ref")))
    target_tree = commit_tree_sha(server, target_ref)
    current_tree = worktree_tree_sha(server)
    rows = diff_name_status(server, target_tree, current_tree)
    paths = sorted({path for _, row_paths in rows for path in row_paths if path})
    scope = ensure_timeline_paths_allowed(server, user, paths)
    changed = changed_files_between_trees(server, target_tree, current_tree)
    if body.get("preview"):
        return {
            "schema": "hermes.wasm_agent.timeline_stepback.v1",
            "preview": True,
            "selected_ref": selected_ref,
            "target_ref": target_ref,
            "target_tree": target_tree,
            "scope": scope,
            "changed_files": changed,
            "path_count": len(paths),
        }
    if not paths:
        return {
            "schema": "hermes.wasm_agent.timeline_stepback.v1",
            "preview": False,
            "selected_ref": selected_ref,
            "target_ref": target_ref,
            "target_tree": target_tree,
            "after_tree": current_tree,
            "scope": scope,
            "changed_files": [],
            "path_count": 0,
            "restored_paths": 0,
            "deleted_paths": 0,
            "no_op": True,
        }
    before_restore = create_timeline_checkpoint(
        server,
        label=timeline_ref_name(f"before-stepback-{space_id}"),
        message=f"wasm-agent before stepback for {space_id}",
        automatic=True,
        user=user,
        space_id=space_id,
        tree_sha=current_tree,
        extra_metadata={
            "phase": "before_stepback",
            "target_ref": target_ref,
            "selected_ref": selected_ref,
            "changed_files": changed,
            "scope": scope,
        },
    )
    applied = restore_paths_from_tree(server, target_tree, rows)
    after_tree = worktree_tree_sha(server)
    return {
        "schema": "hermes.wasm_agent.timeline_stepback.v1",
        "preview": False,
        "selected_ref": selected_ref,
        "target_ref": target_ref,
        "target_tree": target_tree,
        "after_tree": after_tree,
        "scope": scope,
        "changed_files": changed,
        "path_count": len(paths),
        "before_restore_checkpoint": before_restore,
        **applied,
    }


def worktree_tree_sha(server: WasmAgentServer) -> str:
    metadata_dir = server.state_dir / "timeline"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    tree_sha, temp_index = checkpoint_tree(server, metadata_dir)
    try:
        temp_index.unlink(missing_ok=True)
    except Exception:
        pass
    return tree_sha


def safe_worktree_tree_sha(server: WasmAgentServer) -> str:
    try:
        return worktree_tree_sha(server)
    except Exception:
        return ""


def changed_files_between_trees(server: WasmAgentServer, before_tree: str, after_tree: str) -> list[dict[str, Any]]:
    if not before_tree or not after_tree or before_tree == after_tree:
        return []
    root = repo_root(server)
    status_proc = git_run(server, ["diff", "--name-status", before_tree, after_tree], timeout=8)
    numstat_proc = git_run(server, ["diff", "--numstat", before_tree, after_tree], timeout=8)
    if status_proc.returncode != 0:
        return []
    numstat: dict[str, tuple[int | None, int | None]] = {}
    if numstat_proc.returncode == 0:
        for row in (numstat_proc.stdout or "").splitlines():
            parts = row.split("\t")
            if len(parts) < 3:
                continue
            added = None if parts[0] == "-" else int(parts[0])
            deleted = None if parts[1] == "-" else int(parts[1])
            numstat[parts[-1]] = (added, deleted)
    files: list[dict[str, Any]] = []
    for line in (status_proc.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        path = parts[-1]
        additions, deletions = numstat.get(path, (None, None))
        patch_proc = git_run(
            server,
            ["diff", "--unified=3", "--no-ext-diff", before_tree, after_tree, "--", path],
            timeout=8,
        )
        patch_text = clipped(patch_proc.stdout, 24000) if patch_proc.returncode == 0 else ""
        files.append(
            {
                "status": status,
                "path": path,
                "full_path": str((root / path).resolve()),
                "additions": additions,
                "deletions": deletions,
                "diff": f"+{additions or 0} -{deletions or 0}" if additions is not None or deletions is not None else "",
                "diff_patch": patch_text,
            }
        )
    return files


def run_checkpoint_summary(message: str) -> str:
    text = " ".join(str(message or "").split())
    if not text:
        return "chat turn"
    if len(text) > 72:
        return text[:71].rstrip() + "..."
    return text


def attachment_dir(server: WasmAgentServer, user: dict[str, Any] | None = None) -> Path:
    return user_attachment_dir(server, user)


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def attachment_store_max_bytes() -> int:
    return env_int(
        "HERMES_WASM_AGENT_ATTACHMENT_STORE_MAX_BYTES",
        DEFAULT_AGENT_ATTACHMENT_STORE_MAX_BYTES,
        1024 * 1024,
        1024 * 1024 * 1024,
    )


def attachment_store_max_files() -> int:
    return env_int(
        "HERMES_WASM_AGENT_ATTACHMENT_STORE_MAX_FILES",
        DEFAULT_AGENT_ATTACHMENT_STORE_MAX_FILES,
        2,
        10000,
    )


def attachment_max_age_sec() -> int:
    return env_int(
        "HERMES_WASM_AGENT_ATTACHMENT_MAX_AGE_SEC",
        DEFAULT_AGENT_ATTACHMENT_MAX_AGE_SEC,
        0,
        365 * 24 * 60 * 60,
    )


def attachment_records(root: Path) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for path in root.iterdir():
        if not path.is_file() or path.name.startswith("."):
            continue
        digest = path.stem if path.suffix == ".json" else path.stem
        stat = path.stat()
        record = grouped.setdefault(digest, {"digest": digest, "paths": [], "size": 0, "mtime": 0.0})
        record["paths"].append(path)
        record["size"] += stat.st_size
        record["mtime"] = max(float(record["mtime"]), stat.st_mtime)
    return list(grouped.values())


def prune_agent_attachments(
    server: WasmAgentServer,
    keep_hashes: set[str] | None = None,
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = attachment_dir(server, user)
    keep_hashes = keep_hashes or set()
    max_bytes = attachment_store_max_bytes()
    max_files = attachment_store_max_files()
    max_age = attachment_max_age_sec()
    records = attachment_records(root)
    total_bytes = sum(int(record["size"]) for record in records)
    total_files = sum(len(record["paths"]) for record in records)
    to_delete: set[str] = set()
    now = time.time()
    if max_age > 0:
        for record in records:
            if record["digest"] not in keep_hashes and float(record["mtime"]) < now - max_age:
                to_delete.add(str(record["digest"]))

    def survivor_totals() -> tuple[int, int]:
        return (
            sum(int(record["size"]) for record in records if record["digest"] not in to_delete),
            sum(len(record["paths"]) for record in records if record["digest"] not in to_delete),
        )

    total_bytes, total_files = survivor_totals()
    for record in sorted(records, key=lambda item: (float(item["mtime"]), str(item["digest"]))):
        if total_bytes <= max_bytes and total_files <= max_files:
            break
        if record["digest"] in keep_hashes or record["digest"] in to_delete:
            continue
        to_delete.add(str(record["digest"]))
        total_bytes -= int(record["size"])
        total_files -= len(record["paths"])

    deleted_files = 0
    deleted_bytes = 0
    for record in records:
        if record["digest"] not in to_delete:
            continue
        for path in record["paths"]:
            try:
                deleted_bytes += path.stat().st_size
                path.unlink()
                deleted_files += 1
            except FileNotFoundError:
                pass
            except Exception:
                continue
    final_records = attachment_records(root)
    return {
        "schema": "hermes.wasm_agent.attachment_retention.v1",
        "max_bytes": max_bytes,
        "max_files": max_files,
        "max_age_sec": max_age,
        "deleted_records": len(to_delete),
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
        "bytes_before": sum(int(record["size"]) for record in records),
        "bytes_after": sum(int(record["size"]) for record in final_records),
        "files_after": sum(len(record["paths"]) for record in final_records),
    }


def image_extension(mime_type: str) -> str:
    normalized = mime_type.lower().split(";", 1)[0].strip()
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(normalized, ".img")


def parse_image_data_url(data_url: str) -> tuple[str, bytes]:
    if not data_url.startswith("data:image/"):
        raise BrowserError("invalid_attachment", "Attachment must be an image data URL.")
    header, sep, encoded = data_url.partition(",")
    if not sep or ";base64" not in header:
        raise BrowserError("invalid_attachment", "Attachment data URL must be base64 encoded.")
    mime_type = header.removeprefix("data:").split(";", 1)[0].lower()
    try:
        payload = base64.b64decode(encoded.encode("ascii"), validate=True)
    except Exception as exc:
        raise BrowserError("invalid_attachment", "Attachment base64 payload is invalid.") from exc
    if len(payload) > DEFAULT_AGENT_ATTACHMENT_MAX_BYTES:
        raise BrowserError(
            "attachment_too_large",
            "Attachment is too large for the local asset store.",
            status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        )
    return mime_type, payload


def compact_image_evidence(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compacted: list[dict[str, Any]] = []
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        facts = item.get("facts") if isinstance(item.get("facts"), list) else []
        values = item.get("values") if isinstance(item.get("values"), dict) else {}
        compacted.append({
            "module": clipped(str(item.get("module") or ""), 80),
            "title": clipped(str(item.get("title") or ""), 80),
            "status": clipped(str(item.get("status") or ""), 40),
            "summary": clipped(str(item.get("summary") or ""), 180),
            "confidence": item.get("confidence") if isinstance(item.get("confidence"), (int, float)) else None,
            "facts": [clipped(str(fact), 160) for fact in facts[:8]],
            "values": values,
            "reason": clipped(str(item.get("reason") or ""), 180),
            "duration_ms": item.get("duration_ms") if isinstance(item.get("duration_ms"), int) else None,
            "cached": bool(item.get("cached")),
        })
    return compacted


def compact_image_module_results(results: Any) -> dict[str, Any]:
    if not isinstance(results, dict):
        return {}
    compacted: dict[str, Any] = {}
    for key, value in list(results.items())[:8]:
        if not isinstance(value, dict):
            continue
        evidence = compact_image_evidence([value])
        if evidence:
            compacted[clipped(str(key), 80)] = evidence[0]
    return compacted


def compact_image_analyzer_modules(modules: Any) -> list[dict[str, Any]]:
    if not isinstance(modules, list):
        return []
    compacted: list[dict[str, Any]] = []
    for module in modules[:8]:
        if not isinstance(module, dict):
            continue
        compacted.append({
            "id": clipped(str(module.get("id") or ""), 80),
            "title": clipped(str(module.get("title") or ""), 80),
            "enabled": bool(module.get("enabled")),
            "status": clipped(str(module.get("status") or ""), 80),
            "mode": clipped(str(module.get("mode") or ""), 80),
            "evidence": clipped(str(module.get("evidence") or ""), 80),
            "cached": bool(module.get("cached")),
        })
    return compacted


def rounded_metric(value: float, digits: int = 3) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return 0
    return round(float(value), digits)


def luminance_word(value: float) -> str:
    if value < 0.12:
        return "very dark"
    if value < 0.28:
        return "dark"
    if value < 0.45:
        return "dim"
    if value < 0.65:
        return "medium"
    if value < 0.82:
        return "bright"
    return "very bright"


def server_text_like_region_signals(luma: list[float], mask: list[int], width: int, height: int, avg_luma: float) -> dict[str, Any]:
    rows = 6
    cols = 4
    cells = [
        {
            "row": index // cols,
            "col": index % cols,
            "count": 0,
            "dark": 0,
            "bright": 0,
            "transitions": 0,
            "comparisons": 0,
        }
        for index in range(rows * cols)
    ]
    dark_threshold = max(42, min(125, avg_luma * 0.78))
    bright_threshold = max(dark_threshold + 28, min(210, avg_luma + 24))
    for y in range(height):
        for x in range(width):
            index = y * width + x
            if not mask[index]:
                continue
            cell_col = min(cols - 1, int((x / max(1, width)) * cols))
            cell_row = min(rows - 1, int((y / max(1, height)) * rows))
            cell = cells[cell_row * cols + cell_col]
            lum = luma[index]
            cell["count"] += 1
            if lum <= dark_threshold:
                cell["dark"] += 1
            if lum >= bright_threshold:
                cell["bright"] += 1
            if x > 0:
                previous = index - 1
                if mask[previous]:
                    cell["comparisons"] += 1
                    if abs(lum - luma[previous]) > 18:
                        cell["transitions"] += 1
            if y > 0:
                previous = index - width
                if mask[previous]:
                    cell["comparisons"] += 1
                    if abs(lum - luma[previous]) > 18:
                        cell["transitions"] += 1
    scored: list[dict[str, Any]] = []
    for cell in cells:
        dark_ratio = cell["dark"] / max(1, cell["count"])
        bright_ratio = cell["bright"] / max(1, cell["count"])
        transition_density = cell["transitions"] / max(1, cell["comparisons"])
        has_ink_and_surface = dark_ratio > 0.035 and dark_ratio < 0.62 and bright_ratio > 0.08
        center_bias = 1.18 if cell["col"] > 0 and cell["col"] < cols - 1 and cell["row"] > 0 and cell["row"] < rows - 1 else 1
        score = min(
            1,
            (
                transition_density * 2.2
                + min(dark_ratio, 0.34) * 0.9
                + min(bright_ratio, 0.5) * 0.2
            )
            * center_bias
            * (1 if has_ink_and_surface else 0.45),
        )
        scored.append({
            "row": cell["row"],
            "col": cell["col"],
            "score": rounded_metric(score),
            "dark_ratio": rounded_metric(dark_ratio),
            "bright_ratio": rounded_metric(bright_ratio),
            "transition_density": rounded_metric(transition_density),
        })
    scored.sort(key=lambda cell: cell["score"], reverse=True)
    active = [cell for cell in scored if cell["score"] > 0.18]
    active_rows = {cell["row"] for cell in active}
    active_cols = {cell["col"] for cell in active}
    regions: list[str] = []
    if active:
        row_avg = sum(cell["row"] for cell in active) / len(active)
        col_avg = sum(cell["col"] for cell in active) / len(active)
        vertical = "upper" if row_avg < 1.8 else "lower" if row_avg > 3.8 else "middle"
        horizontal = "left" if col_avg < 1.1 else "right" if col_avg > 1.9 else "center"
        regions.append(f"{vertical} {horizontal}".strip())
    top_score = sum(cell["score"] for cell in scored[:4]) / max(1, min(4, len(scored)))
    return {
        "score": rounded_metric(top_score),
        "horizontal_band_estimate": len(active_rows),
        "active_cell_count": len(active),
        "active_row_count": len(active_rows),
        "active_col_count": len(active_cols),
        "regions": regions,
        "cells": scored[:5],
    }


def server_scene_hints(analysis: dict[str, Any], text_signals: dict[str, Any]) -> dict[str, Any]:
    text_score = float(text_signals.get("score") or 0)
    sharpness = float(analysis.get("sharpness") or 0)
    contrast = float(analysis.get("contrast") or 0)
    avg_luma = float(analysis.get("average_luminance") or 0)
    center_edge_delta = float(analysis.get("center_edge_delta") or 0)
    edge_density = float(analysis.get("edge_density") or 0)
    uneven_lighting = min(1.0, abs(center_edge_delta) * 3.8)
    low_sharpness = max(0.0, min(1.0, (0.09 - sharpness) / 0.09))
    not_bright_document = 1.0 if avg_luma < 0.58 else max(0.0, (0.72 - avg_luma) / 0.14)
    physical_photo = max(0.0, min(1.0, (uneven_lighting * 0.38) + (low_sharpness * 0.34) + (not_bright_document * 0.28)))
    printed_object = max(0.0, min(1.0, (text_score * 0.62) + (physical_photo * 0.38)))
    screenshot = max(0.0, min(1.0, (sharpness * 2.2 + contrast * 0.8 + edge_density * 0.9) - uneven_lighting * 0.75))
    document = max(0.0, min(1.0, ((avg_luma - 0.42) * 1.4) + (text_score * 0.35) - uneven_lighting * 0.45))
    reasons = []
    if text_score > 0.32:
        reasons.append("strong text-like bands")
    if low_sharpness > 0.45:
        reasons.append("soft camera-like capture")
    if uneven_lighting > 0.35:
        reasons.append("uneven lighting/gradient")
    if not_bright_document > 0.55:
        reasons.append("not a bright flat document field")
    return {
        "physical_photo_likelihood": rounded_metric(physical_photo),
        "printed_object_or_label_likelihood": rounded_metric(printed_object),
        "document_likelihood": rounded_metric(document),
        "screenshot_likelihood": rounded_metric(screenshot),
        "reason": reasons[:6],
    }


def server_shape_hints(
    luma: list[float],
    mask: list[int],
    width: int,
    height: int,
    avg_luma: float,
    text_signals: dict[str, Any],
    scene_hints: dict[str, Any],
) -> dict[str, Any]:
    central_left = int(width * 0.12)
    central_right = max(central_left + 1, int(width * 0.88))
    dark_threshold = max(36, min(105, avg_luma * 0.72))
    best_rim = {
        "row": 0,
        "score": 0.0,
        "max_run_ratio": 0.0,
        "dark_ratio": 0.0,
        "edge_density": 0.0,
    }
    for y in range(int(height * 0.12), max(int(height * 0.42), int(height * 0.12) + 1)):
        max_run = 0
        current_run = 0
        dark_count = 0
        edges = 0
        comparisons = 0
        previous_dark = False
        for x in range(central_left, central_right):
            index = y * width + x
            if not mask[index]:
                current_run = 0
                previous_dark = False
                continue
            dark = luma[index] <= dark_threshold
            if dark:
                dark_count += 1
                current_run += 1
                max_run = max(max_run, current_run)
            else:
                current_run = 0
            if x > central_left:
                comparisons += 1
                if dark != previous_dark:
                    edges += 1
            previous_dark = dark
        row_width = max(1, central_right - central_left)
        run_ratio = max_run / row_width
        dark_ratio = dark_count / row_width
        edge_density = edges / max(1, comparisons)
        # Rim-like bands are long and continuous; text strokes are usually more fragmented.
        score = min(1.0, (run_ratio * 1.35) + (dark_ratio * 0.22) - (edge_density * 0.18))
        if score > best_rim["score"]:
            best_rim = {
                "row": y,
                "score": score,
                "max_run_ratio": run_ratio,
                "dark_ratio": dark_ratio,
                "edge_density": edge_density,
            }
    physical_photo = float(scene_hints.get("physical_photo_likelihood") or 0)
    printed_object = float(scene_hints.get("printed_object_or_label_likelihood") or 0)
    text_score = float(text_signals.get("score") or 0)
    rim_score = best_rim["score"]
    rounded_container = max(0.0, min(1.0, rim_score * 0.48 + physical_photo * 0.28 + printed_object * 0.18 + text_score * 0.06))
    cylindrical_surface = max(0.0, min(1.0, rounded_container * 0.72 + min(1.0, text_score) * 0.18 + physical_photo * 0.1))
    reasons = []
    if rim_score > 0.42:
        reasons.append("long dark rim-like band in upper portion")
    if physical_photo > 0.5:
        reasons.append("camera-photo lighting")
    if printed_object > 0.5:
        reasons.append("printed markings on physical surface")
    if text_score > 0.32:
        reasons.append("text bands across central surface")
    return {
        "rounded_container_likelihood": rounded_metric(rounded_container),
        "cylindrical_surface_likelihood": rounded_metric(cylindrical_surface),
        "rim_like_band": {
            "row_ratio": rounded_metric(best_rim["row"] / max(1, height)),
            "score": rounded_metric(rim_score),
            "max_run_ratio": rounded_metric(best_rim["max_run_ratio"]),
            "dark_ratio": rounded_metric(best_rim["dark_ratio"]),
            "edge_density": rounded_metric(best_rim["edge_density"]),
        },
        "reason": reasons[:6],
    }


def server_enrich_stale_image_card(card: dict[str, Any], payload: bytes) -> dict[str, Any]:
    revision = str(card.get("analyzer_revision") or "")
    analysis_source = card.get("analysis") if isinstance(card.get("analysis"), dict) else {}
    composition_source = card.get("composition") if isinstance(card.get("composition"), dict) else {}
    has_current_text_signals = (
        (revision == IMAGE_CARD_ANALYZER_REVISION or revision.startswith(f"{IMAGE_CARD_ANALYZER_REVISION}+"))
        and analysis_source.get("text_like_score") is not None
    )
    has_server_hints = isinstance(composition_source.get("scene_hints"), dict) and isinstance(
        composition_source.get("shape_hints"), dict
    )
    if has_current_text_signals and has_server_hints:
        return card
    if Image is None:
        return card
    try:
        with Image.open(io.BytesIO(payload)) as image:
            source_width, source_height = image.size
            image = image.convert("RGBA")
            scale = min(1.0, 128 / max(1, source_width, source_height))
            width = max(1, round(source_width * scale))
            height = max(1, round(source_height * scale))
            image = image.resize((width, height), Image.Resampling.LANCZOS)
            pixels = list(image.getdata())
    except Exception:
        return card
    luma = [0.0] * (width * height)
    mask = [0] * (width * height)
    count = 0
    luma_sum = 0.0
    luma_sq = 0.0
    edge_count = 0
    comparisons = 0
    center_sum = 0.0
    center_count = 0
    edge_sum = 0.0
    edge_pixels = 0
    center_left = width * 0.3
    center_right = width * 0.7
    center_top = height * 0.3
    center_bottom = height * 0.7
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[y * width + x]
            if alpha < 16:
                continue
            lum = red * 0.299 + green * 0.587 + blue * 0.114
            index = y * width + x
            luma[index] = lum
            mask[index] = 1
            count += 1
            luma_sum += lum
            luma_sq += lum * lum
            if center_left <= x <= center_right and center_top <= y <= center_bottom:
                center_sum += lum
                center_count += 1
            else:
                edge_sum += lum
                edge_pixels += 1
            if x > 0 and mask[index - 1]:
                comparisons += 1
                if abs(lum - luma[index - 1]) > 32:
                    edge_count += 1
            if y > 0 and mask[index - width]:
                comparisons += 1
                if abs(lum - luma[index - width]) > 32:
                    edge_count += 1
    if not count:
        return card
    avg_luma = luma_sum / count
    contrast = math.sqrt(max(0, (luma_sq / count) - (avg_luma * avg_luma)))
    center_luma = center_sum / max(1, center_count)
    edge_luma = edge_sum / max(1, edge_pixels)
    text_signals = server_text_like_region_signals(luma, mask, width, height, avg_luma)
    analysis = {
        **analysis_source,
        "average_luminance": rounded_metric(avg_luma / 255),
        "contrast": rounded_metric(contrast / 255),
        "edge_density": rounded_metric(edge_count / max(1, comparisons)),
        "center_luminance": rounded_metric(center_luma / 255),
        "edge_luminance": rounded_metric(edge_luma / 255),
        "center_edge_delta": rounded_metric((center_luma - edge_luma) / 255),
        "text_like_score": text_signals["score"],
        "text_band_estimate": text_signals["horizontal_band_estimate"],
        "text_active_cell_count": text_signals["active_cell_count"],
        "sample_size": f"{width}x{height}",
    }
    scene_hints = server_scene_hints(analysis, text_signals)
    shape_hints = server_shape_hints(luma, mask, width, height, avg_luma, text_signals, scene_hints)
    composition = {
        **composition_source,
        "text_regions": text_signals,
        "scene_hints": scene_hints,
        "shape_hints": shape_hints,
        "server_brightness": {
            "center_label": luminance_word(center_luma / 255),
            "edge_label": luminance_word(edge_luma / 255),
        },
    }
    visual_notes = card.get("visual_notes") if isinstance(card.get("visual_notes"), list) else []
    visual_notes = [str(note) for note in visual_notes[:12]]
    if text_signals["score"] > 0.32 and "strong text-like dark strokes on lighter regions" not in visual_notes:
        visual_notes.insert(0, "strong text-like dark strokes on lighter regions")
    elif text_signals["score"] > 0.2 and "possible printed text or label-like markings" not in visual_notes:
        visual_notes.insert(0, "possible printed text or label-like markings")
    if text_signals["horizontal_band_estimate"] >= 2:
        band_note = f"{text_signals['horizontal_band_estimate']} horizontal text-like bands"
        if band_note not in visual_notes:
            visual_notes.insert(1, band_note)
    if scene_hints["printed_object_or_label_likelihood"] > 0.58 and "likely printed label or markings on a physical photographed surface" not in visual_notes:
        visual_notes.insert(0, "likely printed label or markings on a physical photographed surface")
    if shape_hints["cylindrical_surface_likelihood"] > 0.58 and "rounded or cylindrical container-like photographed surface" not in visual_notes:
        visual_notes.insert(0, "rounded or cylindrical container-like photographed surface")
    evidence = card.get("evidence") if isinstance(card.get("evidence"), list) else []
    enrichment_source = "server_hints" if has_current_text_signals else "server_fallback"
    enrichment_revision = (
        f"{IMAGE_CARD_ANALYZER_REVISION}+server-hints"
        if has_current_text_signals
        else f"{IMAGE_CARD_ANALYZER_REVISION}+server-fallback"
    )
    enrichment_reason = (
        "browser_image_card_missing_scene_shape_hints"
        if has_current_text_signals
        else "browser_image_card_stale_or_missing_revision"
    )
    enrichment_summary = (
        "Server added scene and shape hints to a current browser image card before model inference."
        if has_current_text_signals
        else "Server enriched a stale browser image card before model inference."
    )
    server_result = {
        "module": "server-image-card-core",
        "title": "Server Image Card Core",
        "status": "active",
        "summary": enrichment_summary,
        "confidence": 0.86,
        "facts": [
            f"{width}x{height} server sample",
            f"text-like score {text_signals['score']}",
            f"{text_signals['horizontal_band_estimate']} text-like bands",
            f"printed-object label likelihood {scene_hints['printed_object_or_label_likelihood']}",
            f"cylindrical surface likelihood {shape_hints['cylindrical_surface_likelihood']}",
        ],
        "values": {
            "sample_size": f"{width}x{height}",
            "text_like_score": text_signals["score"],
            "text_band_estimate": text_signals["horizontal_band_estimate"],
            "scene_hints": scene_hints,
            "shape_hints": shape_hints,
            "source": enrichment_source,
        },
        "reason": enrichment_reason,
        "duration_ms": None,
        "cached": False,
    }
    module_results = card.get("module_results") if isinstance(card.get("module_results"), dict) else {}
    module_results = {**module_results, "server-image-card-core": server_result}
    return {
        **card,
        "analyzer_revision": enrichment_revision,
        "analysis": analysis,
        "composition": composition,
        "visual_notes": visual_notes[:12],
        "evidence": [*evidence, server_result][:8],
        "module_results": module_results,
    }


def compact_image_card(card: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    source = card if isinstance(card, dict) else {}
    fallback = fallback or {}
    palette = source.get("palette") if isinstance(source.get("palette"), list) else []
    palette_hex = source.get("palette_hex") if isinstance(source.get("palette_hex"), list) else []
    visual_notes = source.get("visual_notes") if isinstance(source.get("visual_notes"), list) else []
    analysis = source.get("analysis") if isinstance(source.get("analysis"), dict) else {}
    composition = source.get("composition") if isinstance(source.get("composition"), dict) else {}
    return {
        "schema": "hermes.wasm_agent.image_card.v1",
        "analyzer_revision": clipped(str(source.get("analyzer_revision") or ""), 80),
        "name": clipped(str(source.get("name") or fallback.get("name") or "image"), 120),
        "size": source.get("size") if isinstance(source.get("size"), int) else fallback.get("size"),
        "dimensions": clipped(str(source.get("dimensions") or ""), 80),
        "width": source.get("width") if isinstance(source.get("width"), int) else fallback.get("width"),
        "height": source.get("height") if isinstance(source.get("height"), int) else fallback.get("height"),
        "palette": [clipped(str(item), 40) for item in palette[:6]],
        "palette_hex": [clipped(str(item), 16) for item in palette_hex[:6]],
        "visual_notes": [clipped(str(item), 120) for item in visual_notes[:12]],
        "perceptual_hash": clipped(str(source.get("perceptual_hash") or ""), 120),
        "rendered_dimensions": clipped(str(source.get("rendered_dimensions") or ""), 80),
        "analysis": analysis,
        "composition": composition,
        "evidence": compact_image_evidence(source.get("evidence")),
        "module_results": compact_image_module_results(source.get("module_results")),
        "analyzer_modules": compact_image_analyzer_modules(source.get("analyzer_modules")),
        "local_url": clipped(str(source.get("local_url") or ""), 240),
        "hash": clipped(str(source.get("hash") or ""), 120),
    }


def save_agent_attachment(server: WasmAgentServer, body: dict[str, Any], user: dict[str, Any] | None = None) -> dict[str, Any]:
    image = body.get("image") if isinstance(body.get("image"), dict) else body
    data_url = str(image.get("data_url") or "")
    mime_type, payload = parse_image_data_url(data_url)
    ensure_user_quota(server, user, len(payload))
    digest = hashlib.sha256(payload).hexdigest()
    ext = image_extension(mime_type)
    basename = f"{digest}{ext}"
    path = attachment_dir(server, user) / basename
    if not path.exists():
        path.write_bytes(payload)
    size = image.get("size") if isinstance(image.get("size"), int) else len(payload)
    card = compact_image_card(
        image.get("image_card"),
        {
            "name": image.get("name"),
            "size": size,
            "width": image.get("width") if isinstance(image.get("width"), int) else None,
            "height": image.get("height") if isinstance(image.get("height"), int) else None,
        },
    )
    card = compact_image_card(server_enrich_stale_image_card(card, payload), {
        "name": image.get("name"),
        "size": size,
        "width": image.get("width") if isinstance(image.get("width"), int) else None,
        "height": image.get("height") if isinstance(image.get("height"), int) else None,
    })
    card["local_url"] = f"/agent/attachments/{basename}"
    card["hash"] = digest
    metadata = {
        "schema": "hermes.wasm_agent.attachment_asset.v1",
        "hash": digest,
        "local_url": card["local_url"],
        "name": clipped(str(image.get("name") or "image"), 120),
        "type": mime_type,
        "size": len(payload),
        "declared_size": size,
        "width": image.get("width") if isinstance(image.get("width"), int) else None,
        "height": image.get("height") if isinstance(image.get("height"), int) else None,
        "original_type": clipped(str(image.get("original_type") or ""), 80),
        "original_size": image.get("original_size") if isinstance(image.get("original_size"), int) else None,
        "stored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "image_card": card,
    }
    meta_path = attachment_dir(server, user) / f"{digest}.json"
    tmp = meta_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8")
    tmp.replace(meta_path)
    metadata["retention"] = prune_agent_attachments(server, keep_hashes={digest}, user=user)
    return metadata


def serve_agent_attachment(handler: WasmAgentHandler, path: str, user: dict[str, Any] | None = None) -> None:
    filename = path.rsplit("/", 1)[-1]
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_")
    if not filename or any(char not in allowed for char in filename):
        raise BrowserError("attachment_not_found", "Attachment was not found.", status=HTTPStatus.NOT_FOUND)
    root = attachment_dir(handler.server, user).resolve()
    resolved = (root / filename).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise BrowserError("attachment_not_found", "Attachment was not found.", status=HTTPStatus.NOT_FOUND) from exc
    if not resolved.is_file() or resolved.suffix == ".json":
        raise BrowserError("attachment_not_found", "Attachment was not found.", status=HTTPStatus.NOT_FOUND)
    content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
    data = resolved.read_bytes()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "private, max-age=86400")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def repo_root(server: WasmAgentServer) -> Path:
    return server.plugin_root.parents[1]


def clipped(value: str, limit: int = 6000) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[clipped {len(text) - limit} chars]"


def clipped_verbatim(value: str, limit: int = 6000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit]


def text_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=True)) if not isinstance(value, str) else len(value)


def tool_preview(tool: dict[str, Any]) -> dict[str, Any]:
    content = str(tool.get("content") or tool.get("output") or "")
    return {
        "tool": tool.get("tool"),
        "path": tool.get("path"),
        "query": tool.get("query"),
        "returncode": tool.get("returncode"),
        "bytes": tool.get("bytes"),
        "preview": clipped(content, 900) if content else clipped(json.dumps(tool, ensure_ascii=True), 900),
    }


def compact_json(value: Any, limit: int = 900) -> str:
    return clipped(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True), limit)


def tool_output_text(tool: dict[str, Any]) -> str:
    return str(tool.get("content") or tool.get("output") or "")


def first_nonempty_line(value: str, fallback: str = "") -> str:
    for line in value.splitlines():
        text = line.strip()
        if text:
            return clipped(text, 160)
    return fallback


def parsed_tool_content(tool: dict[str, Any]) -> dict[str, Any]:
    raw = str(tool.get("content") or "")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def tool_action_label(tool: dict[str, Any]) -> str:
    name = str(tool.get("tool") or "tool")
    labels = {
        "current_turn_observation": "Inspect current UI",
        "observation_latest": "Read latest observation",
        "app_map": "Map wasm-agent surface",
        "ui_symbol_resolver": "Resolve UI symbols",
        "git_status": "Check worktree status",
        "git_diff_stat": "Summarize source diff",
        "timeline_status": "Read Timeline state",
        "user_scope_status": "Read user sandbox policy",
        "attachment_manifest": "Build attachment cards",
        "read_file": "Read file",
        "search": "Search repository",
        "doctor": "Run wasm-agent doctor",
    }
    return labels.get(name, f"Run {name}")


def tool_action_kind(tool: dict[str, Any]) -> str:
    name = str(tool.get("tool") or "tool")
    wasm_tools = {
        "current_turn_observation",
        "observation_latest",
        "app_map",
        "ui_symbol_resolver",
        "git_status",
        "git_diff_stat",
        "timeline_status",
        "user_scope_status",
        "attachment_manifest",
        "read_file",
        "search",
        "doctor",
    }
    return "run-wasm" if name in wasm_tools else "tool"


def tool_action_topic(tool: dict[str, Any]) -> str:
    return "run-wasm" if tool_action_kind(tool) == "run-wasm" else "run-wasm"


def tool_action_detail(tool: dict[str, Any]) -> str:
    name = str(tool.get("tool") or "tool")
    content = parsed_tool_content(tool)
    output = tool_output_text(tool)
    if name == "current_turn_observation":
        workspace = tool.get("workspace") if isinstance(tool.get("workspace"), dict) else {}
        events = tool.get("recent_events") if isinstance(tool.get("recent_events"), list) else []
        active_space = workspace.get("active_space") if isinstance(workspace.get("active_space"), dict) else {}
        space_name = active_space.get("display_name") or active_space.get("name") or workspace.get("active_space_name") or workspace.get("active_panel", "workspace")
        return f"{space_name} / {len(events)} recent events"
    if name == "observation_latest":
        workspace = tool.get("workspace") if isinstance(tool.get("workspace"), dict) else {}
        fleet = tool.get("fleet") if isinstance(tool.get("fleet"), dict) else {}
        active_space = workspace.get("active_space") if isinstance(workspace.get("active_space"), dict) else {}
        space_name = active_space.get("display_name") or active_space.get("name") or workspace.get("active_space_name") or workspace.get("active_panel", "workspace")
        return f"{space_name} / node {fleet.get('selected_node') or '-'}"
    if name == "app_map":
        files = content.get("primary_files") if isinstance(content.get("primary_files"), list) else []
        return f"{len(files)} files / {content.get('write_boundary', 'local boundary')}"
    if name == "ui_symbol_resolver":
        symbols = content.get("symbols") if isinstance(content.get("symbols"), list) else []
        matches = sum(len(item.get("matches") or []) for item in symbols if isinstance(item, dict))
        return f"{len(symbols)} symbols / {matches} matches"
    if name == "git_status":
        lines = [line for line in output.splitlines() if line.strip()]
        return "clean" if not lines else f"{len(lines)} changed paths"
    if name == "git_diff_stat":
        return first_nonempty_line(output, "no tracked diff")
    if name == "timeline_status":
        return f"{content.get('branch', '-')} / {content.get('dirty_count', 0)} dirty / {content.get('checkpoint_count', 0)} checkpoints"
    if name == "user_scope_status":
        policy = content.get("policy") if isinstance(content.get("policy"), dict) else {}
        return f"{policy.get('scope', 'scope')} / user {policy.get('user_id', '-')}"
    if name == "attachment_manifest":
        received = content.get("received_count", 0)
        forwarded = content.get("forwarded_count", 0)
        summarized = content.get("summarized_count", 0)
        cards = content.get("image_card_count", 0)
        videos = content.get("video_attachment_count", 0)
        return f"{received} received / {cards} image cards / {videos} videos / {forwarded} raw to bridge / {summarized} summarized"
    if name == "read_file":
        return f"{tool.get('path') or '-'} / {tool.get('bytes') or 0} bytes"
    if name == "search":
        lines = [line for line in output.splitlines() if line.strip()]
        return f"{tool.get('query') or '-'} / {len(lines)} matches"
    if name == "doctor":
        return f"exit {tool.get('returncode', 0)} / {first_nonempty_line(output, 'no output')}"
    detail = str(tool.get("path") or tool.get("query") or tool.get("returncode") or "")
    return clipped(detail, 180)


def tool_action_arguments(tool: dict[str, Any]) -> dict[str, Any]:
    name = str(tool.get("tool") or "tool")
    args: dict[str, Any] = {"tool": name}
    if tool.get("path"):
        args["path"] = tool.get("path")
    if tool.get("query"):
        args["query"] = tool.get("query")
    if name in {"current_turn_observation", "observation_latest"}:
        args["source"] = "workspace observation snapshot"
    if name == "attachment_manifest":
        args["bridge_image_budget_bytes"] = tool.get("bridge_image_budget_bytes")
        args["forwarded_count"] = tool.get("forwarded_count")
        args["summarized_count"] = tool.get("summarized_count")
        args["image_card_count"] = tool.get("image_card_count")
        args["video_attachment_count"] = tool.get("video_attachment_count")
    if name == "search":
        args["command"] = f"rg -n {tool.get('query') or ''} /local"
    if name == "ui_symbol_resolver":
        args["query"] = tool.get("query")
        args["files"] = ["public/index.html", "public/app.js", "public/styles.css"]
    if name == "git_status":
        args["command"] = "git -C /local status --short"
    if name == "git_diff_stat":
        args["command"] = "git -C /local diff --stat"
    if name == "doctor":
        args["command"] = "scripts/doctor.sh"
    return args


def tool_action_preview(tool: dict[str, Any]) -> str:
    name = str(tool.get("tool") or "tool")
    if name in {"current_turn_observation", "observation_latest"}:
        payload = {
            "timestamp": tool.get("timestamp"),
            "workspace": tool.get("workspace"),
            "fleet": tool.get("fleet"),
            "requested_click_context": tool.get("requested_click_context"),
            "last_event": tool.get("last_event"),
            "recent_events": tool.get("recent_events"),
        }
        compact_payload = {
            key: value for key, value in payload.items()
            if value is not None and value != "" and value != []
        }
        return compact_json(compact_payload, 900)
    output = tool_output_text(tool)
    if output:
        return clipped(output, 900)
    return compact_json(tool, 900)


def tool_action_event(tool: dict[str, Any], index: int) -> dict[str, Any]:
    name = str(tool.get("tool") or "tool")
    returncode = tool.get("returncode")
    status = "done"
    if isinstance(returncode, int) and returncode != 0 and name != "search":
        status = "error"
    return {
        "id": f"tool_{index}_{name}",
        "topic": tool_action_topic(tool),
        "kind": "tool",
        "label": tool_action_label(tool),
        "status": status,
        "detail": tool_action_detail(tool),
        "meta": name,
        "arguments": tool_action_arguments(tool),
        "preview": tool_action_preview(tool),
    }


def final_agent_action_status(status: Any) -> str:
    value = str(status or "done").lower()
    if value in {"running", "queued", "submitted", "pending", "in_progress", "working"}:
        return "done"
    if value in {"failed", "failure"}:
        return "error"
    return value or "done"


def finalize_agent_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    finalized: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        finalized.append({
            **action,
            "status": final_agent_action_status(action.get("status")),
        })
    return finalized


def action_denial_detail(result: dict[str, Any] | None, fallback: str) -> str:
    errors = result.get("errors") if isinstance(result, dict) and isinstance(result.get("errors"), list) else []
    for error in errors:
        text = str(error or "").strip()
        if text:
            return clipped(text, 180)
    return fallback


def token_int_value(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value)) if math.isfinite(value) else None
    if isinstance(value, str):
        clean = value.strip().replace(",", "").replace("_", "")
        if re.fullmatch(r"\d+(?:\.\d+)?", clean):
            return max(0, int(float(clean)))
    return None


def first_token_int(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = token_int_value(payload.get(key))
        if value is not None:
            return value
    return None


def normalize_token_usage(usage: Any, source: str = "") -> dict[str, Any] | None:
    if not isinstance(usage, dict):
        return None
    prompt = first_token_int(
        usage,
        "prompt_tokens",
        "input_tokens",
        "input_token_count",
        "inputTokenCount",
        "tokens_in",
        "prompt",
    )
    completion = first_token_int(
        usage,
        "completion_tokens",
        "output_tokens",
        "output_token_count",
        "outputTokenCount",
        "candidatesTokenCount",
        "tokens_out",
        "completion",
    )
    total = first_token_int(
        usage,
        "total_tokens",
        "total_token_count",
        "totalTokenCount",
        "tokens",
        "total",
    )
    if total is None and (prompt is not None or completion is not None):
        total = int(prompt or 0) + int(completion or 0)
    if prompt is None and total is not None and completion is not None:
        prompt = max(0, total - completion)
    if completion is None and total is not None and prompt is not None:
        completion = max(0, total - prompt)
    if prompt is None and completion is None and total is None:
        return None
    normalized = {
        "prompt_tokens": int(prompt or 0),
        "completion_tokens": int(completion or 0),
        "input_tokens": int(prompt or 0),
        "output_tokens": int(completion or 0),
        "total_tokens": int(total or 0),
    }
    usage_source = source or str(usage.get("source") or usage.get("provider") or "")
    if usage_source:
        normalized["source"] = usage_source
    return normalized


def token_usage_candidates(payload: Any, *, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 3 or not isinstance(payload, dict):
        return []
    candidates = [payload]
    for key in (
        "token_usage",
        "usage",
        "usage_metadata",
        "usageMetadata",
        "metadata",
        "metrics",
        "stats",
        "totals",
        "model_usage",
        "token_counts",
    ):
        child = payload.get(key)
        if isinstance(child, dict):
            candidates.extend(token_usage_candidates(child, depth=depth + 1))
    return candidates


def token_usage_from_payloads(*payloads: Any, source: str = "") -> dict[str, Any] | None:
    seen: set[int] = set()
    for payload in payloads:
        for candidate in token_usage_candidates(payload):
            ident = id(candidate)
            if ident in seen:
                continue
            seen.add(ident)
            usage = normalize_token_usage(candidate, source=source)
            if usage is not None:
                return usage
    return None


def agent_action_events(
    tools: list[dict[str, Any]],
    *,
    mode: str,
    target_node: str,
    transcript_turns: int,
    image_count: int,
    source: str,
    duration_ms: int,
    token_usage: dict[str, Any] | None,
    auto_checkpoint: dict[str, Any] | None,
    before_checkpoint: dict[str, Any] | None,
    changed: list[dict[str, Any]],
    bridge_trace: dict[str, Any] | None,
    readiness: dict[str, Any] | None,
    node_config: dict[str, Any] | None,
    space_context: dict[str, Any] | None,
    mutation_policy: dict[str, Any] | None,
    wis_patch_result: dict[str, Any] | None,
    mutation_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [
        {
            "id": "turn_intake",
            "topic": "run-wasm",
            "kind": "turn",
            "label": "Receive chat turn",
            "status": "done",
            "detail": f"{target_node} / {mode}",
            "meta": f"{transcript_turns} transcript turns / {image_count} images",
        }
    ]
    if mutation_policy:
        actions.append({
            "id": "mutation_policy",
            "topic": "run-wasm",
            "kind": "policy",
            "label": "Apply mutation policy",
            "status": "done",
            "detail": str(mutation_policy.get("scope") or "scope"),
            "meta": "write boundary",
            "preview": compact_json(mutation_policy, 900),
        })
    if readiness:
        ready = bool(readiness.get("ready"))
        actions.append({
            "id": "agent_readiness",
            "topic": "run-hermes",
            "kind": "model",
            "label": "Agent readiness",
            "status": "done" if ready else "error",
            "detail": str(readiness.get("missing_dependency") or readiness.get("status") or ""),
            "meta": str(readiness.get("message") or ""),
            "preview": compact_json(readiness, 1200),
        })
    if node_config:
        safe_node_config = {k: v for k, v in node_config.items() if k != "instructions"}
        safe_node_config["has_instructions"] = bool(node_config.get("instructions"))
        actions.append({
            "id": "node_config",
            "topic": "run-hermes",
            "kind": "trace",
            "label": "Node config",
            "status": "done",
            "detail": f"{node_config.get('name') or target_node} / {node_config.get('type') or 'hermes'}",
            "meta": str(node_config.get("instruction_source") or "none"),
            "preview": compact_json(safe_node_config, 1200),
        })
    if space_context:
        actions.append({
            "id": "space_context",
            "topic": "run-wasm",
            "kind": "context",
            "label": "Current space",
            "status": "done",
            "detail": f"{space_context.get('name') or space_context.get('id')} / {space_context.get('id')}",
            "meta": str(space_context.get("display_name") or ""),
            "preview": compact_json(space_context, 900),
        })
    for index, tool in enumerate(tools, 1):
        actions.append(tool_action_event(tool, index))
    actions.extend(bridge_trace_action_events(bridge_trace))
    if wis_patch_result:
        applied = bool(wis_patch_result.get("applied"))
        patches = wis_patch_result.get("patches") if isinstance(wis_patch_result.get("patches"), list) else []
        actions.append({
            "id": "apply_wis_patch",
            "topic": "run-wasm",
            "kind": "mutation",
            "label": "Apply WIS/userland patch",
            "status": "done" if applied else "error",
            "detail": f"{len(patches)} artifacts / {wis_patch_result.get('operations', 0)} operations" if applied else action_denial_detail(wis_patch_result, "patch denied"),
            "meta": "adapter",
            "preview": compact_json(wis_patch_result, 1200),
            "arguments": {"schema": WIS_PATCH_SCHEMA},
        })
    if mutation_result:
        applied = bool(mutation_result.get("applied"))
        files = mutation_result.get("files") if isinstance(mutation_result.get("files"), list) else []
        errors = mutation_result.get("errors") if isinstance(mutation_result.get("errors"), list) else []
        actions.append({
            "id": "apply_source_mutation",
            "topic": "run-wasm",
            "kind": "mutation",
            "label": "Apply source mutation",
            "status": "done" if applied else "error",
            "detail": f"{len(files)} files / {mutation_result.get('operations', 0)} operations" if applied else action_denial_detail(mutation_result, "mutation denied"),
            "meta": "adapter",
            "preview": compact_json(mutation_result, 1200),
            "arguments": {"schema": "hermes.wasm_agent.mutation.v1"},
        })
    normalized_usage = normalize_token_usage(token_usage)
    total_tokens = normalized_usage.get("total_tokens") if isinstance(normalized_usage, dict) else None
    token_detail = f"{total_tokens} tokens" if isinstance(total_tokens, int) else "tokens unknown"
    actions.append({
        "id": "node_reply",
        "topic": "run-hermes",
        "kind": "model",
        "label": "Final response",
        "status": "done",
        "detail": f"{source} / {duration_ms} ms",
        "meta": token_detail,
    })
    if changed:
        actions.append({
            "id": "changed_files",
            "kind": "timeline",
            "label": "Capture changed files",
            "status": "done",
            "detail": f"{len(changed)} paths",
            "preview": compact_json(changed[:12], 900),
        })
    if before_checkpoint:
        actions.append({
            "id": "timeline_before_checkpoint",
            "kind": "timeline",
            "label": "Timeline before-run point",
            "status": "done",
            "detail": clipped(str(before_checkpoint.get("label") or ""), 160),
            "meta": str(before_checkpoint.get("sha") or "")[:7],
            "preview": compact_json(before_checkpoint, 900),
        })
    if auto_checkpoint:
        actions.append({
            "id": "timeline_checkpoint",
            "kind": "timeline",
            "label": "Timeline checkpoint",
            "status": "done",
            "detail": clipped(str(auto_checkpoint.get("label") or ""), 160),
            "meta": str(auto_checkpoint.get("sha") or "")[:7],
            "preview": compact_json(auto_checkpoint, 900),
        })
    return finalize_agent_actions(actions)


def relative_repo_path(server: WasmAgentServer, raw: str) -> Path:
    root = repo_root(server).resolve()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise BrowserError("agent_path_denied", "Tool path must stay inside /local.") from exc
    return resolved


def agent_read_file(server: WasmAgentServer, path: str) -> dict[str, Any]:
    resolved = relative_repo_path(server, path)
    if not resolved.is_file():
        raise BrowserError("agent_file_not_found", f"File was not found: {path}", status=HTTPStatus.NOT_FOUND)
    text = resolved.read_text(encoding="utf-8", errors="replace")
    return {
        "tool": "read_file",
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "content": clipped(text),
    }


def agent_search(server: WasmAgentServer, query: str) -> dict[str, Any]:
    pattern = str(query or "").strip()
    if not pattern:
        raise BrowserError("agent_missing_query", "Search query is required.")
    root = repo_root(server)
    proc = subprocess.run(
        ["rg", "-n", "--glob", "!plugins/wasm-agent/state/**", "--glob", "!logs/**", pattern, str(root)],
        text=True,
        capture_output=True,
        timeout=8,
        check=False,
    )
    output = proc.stdout or proc.stderr
    return {"tool": "search", "query": pattern, "returncode": proc.returncode, "output": clipped(output, 5000)}


def agent_git_status(server: WasmAgentServer) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root(server)), "status", "--short"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    return {"tool": "git_status", "returncode": proc.returncode, "output": clipped(proc.stdout or proc.stderr, 4000)}


def changed_files(server: WasmAgentServer) -> list[dict[str, Any]]:
    root = repo_root(server)
    proc = git_run(server, ["status", "--short", "-uall"], timeout=5)
    if proc.returncode != 0:
        return []
    numstat_proc = git_run(server, ["diff", "HEAD", "--numstat"], timeout=5)
    numstat: dict[str, tuple[int | None, int | None]] = {}
    if numstat_proc.returncode == 0:
        for row in (numstat_proc.stdout or "").splitlines():
            parts = row.split("\t")
            if len(parts) < 3:
                continue
            added = None if parts[0] == "-" else int(parts[0])
            deleted = None if parts[1] == "-" else int(parts[1])
            numstat[parts[2]] = (added, deleted)
    files: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        if not line:
            continue
        status = line[:2].strip() or "?"
        path = line[3:] if len(line) > 3 else line[2:].strip()
        stat_path = path.split(" -> ", 1)[-1]
        additions, deletions = numstat.get(stat_path, (None, None))
        full_path = str((root / stat_path).resolve())
        if additions is None and deletions is None and status == "??":
            candidate = root / stat_path
            if candidate.is_file() and candidate.stat().st_size <= 1024 * 1024:
                try:
                    additions = len(candidate.read_text(encoding="utf-8", errors="replace").splitlines())
                    deletions = 0
                except OSError:
                    additions = None
                    deletions = None
        files.append(
            {
                "status": status,
                "path": stat_path,
                "full_path": full_path,
                "additions": additions,
                "deletions": deletions,
                "diff": f"+{additions or 0} -{deletions or 0}" if additions is not None or deletions is not None else "",
            }
        )
    return files


def agent_git_diff_stat(server: WasmAgentServer) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root(server)), "diff", "--stat"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    return {"tool": "git_diff_stat", "returncode": proc.returncode, "output": clipped(proc.stdout or proc.stderr, 4000)}


def agent_timeline_status(server: WasmAgentServer, user: dict[str, Any] | None = None) -> dict[str, Any]:
    timeline = timeline_status(server, user)
    return {
        "tool": "timeline_status",
        "content": json.dumps(
            {
                "branch": timeline.get("branch"),
                "head": timeline.get("head"),
                "dirty": timeline.get("dirty"),
                "dirty_count": timeline.get("dirty_count"),
                "checkpoint_count": len(timeline.get("checkpoints") or []),
                "latest_checkpoint": (timeline.get("checkpoints") or [{}])[0],
                "actions": timeline.get("actions") or [],
            },
            ensure_ascii=True,
        ),
    }


def agent_user_scope_status(server: WasmAgentServer, user: dict[str, Any] | None, target_node: str = "") -> dict[str, Any]:
    policy = agent_mutation_policy(server, user, target_node or "sandboxed-node")
    storage = user_storage(server, user)
    return {
        "tool": "user_scope_status",
        "content": json.dumps(
            {
                "policy": policy,
                "storage": {
                    "used_bytes": storage.get("used_bytes"),
                    "limit_bytes": storage.get("limit_bytes"),
                    "unlimited": storage.get("unlimited"),
                },
                "shared_spaces": list_shared_spaces(server, user).get("spaces", []),
                "wis_patch_schema": WIS_PATCH_SCHEMA,
            },
            ensure_ascii=True,
        ),
    }


def agent_doctor(server: WasmAgentServer) -> dict[str, Any]:
    proc = subprocess.run(
        [str(server.plugin_root / "scripts" / "doctor.sh")],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    return {"tool": "doctor", "returncode": proc.returncode, "output": clipped((proc.stdout or "") + (proc.stderr or ""), 4000)}


def agent_app_map(server: WasmAgentServer) -> dict[str, Any]:
    files = [
        "plugins/wasm-agent/public/app.js",
        "plugins/wasm-agent/public/index.html",
        "plugins/wasm-agent/public/styles.css",
        "plugins/wasm-agent/server/static_server.py",
        "plugins/wasm-agent/tests/wasm_agent_smoke.test.js",
        "plugins/wasm-agent/README.md",
        "docs/roadmap/space-os/embedded-agent-path.md",
    ]
    root = repo_root(server)
    entries = []
    for item in files:
        path = root / item
        if path.exists():
            entries.append({"path": item, "bytes": path.stat().st_size})
    return {
        "tool": "app_map",
        "content": json.dumps(
            {
                "goal": "Evolve wasm-agent as the active WASM harness: embedded chat, observation, Timeline recovery, Host Browser stream, and image-card perception.",
                "write_boundary": "Orchestrator/admin turns may modify wasm-agent globally; sandboxed nodes must only modify the mounted account-owned wasm-user state and ask orchestrator for core firmware/source changes.",
                "primary_files": entries,
                "current_chat_contract": {
                    "endpoint": "/agent/session/message",
                    "modes": ["auto", "local", "bridge"],
                    "tools": [
                        "observation_latest",
                        "ui_symbol_resolver",
                        "read_file",
                        "search",
                        "git_status",
                        "git_diff_stat",
                        "timeline_status",
                        "doctor",
                        "app_map",
                        "attachment_manifest",
                    ],
                    "symbol_resolution": "Before saying a UI selector or component is missing, use ui_symbol_resolver. It maps camelCase handles such as agentModelSelect to DOM ids, els.* handles, and kebab-case CSS selectors.",
                    "userland_patch_schema": WIS_PATCH_SCHEMA,
                    "share_endpoints": ["/spaces/share", "/spaces/join", "/spaces/shared", "/wis/artifacts/patch"],
                },
            },
            ensure_ascii=True,
        ),
    }


UI_SYMBOL_FILES = [
    "plugins/wasm-agent/public/index.html",
    "plugins/wasm-agent/public/app.js",
    "plugins/wasm-agent/public/styles.css",
]


def camel_to_kebab(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value.replace("_", "-"))
    return re.sub(r"-+", "-", text).lower()


def kebab_to_camel(value: str) -> str:
    parts = [part for part in re.split(r"[-_\s]+", value) if part]
    if not parts:
        return value
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def ui_symbol_queries(message: str) -> list[str]:
    found: list[str] = []
    for item in re.findall(r"`([^`]{3,80})`", message):
        found.append(item.strip())
    for item in re.findall(r"[#.]?[A-Za-z][A-Za-z0-9_]*(?:[A-Z][A-Za-z0-9_]*)+|[#.]?[a-z][a-z0-9]*(?:-[a-z0-9]+)+", message):
        found.append(item.strip())
    queries: list[str] = []
    seen: set[str] = set()
    for item in found:
        clean = item.strip().strip("`'\"")
        if not clean or len(clean) > 80:
            continue
        if not re.search(r"[A-Za-z]", clean):
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(clean)
    return queries[:8]


def ui_symbol_aliases(query: str) -> list[str]:
    raw = query.strip()
    base = raw[1:] if raw.startswith(("#", ".")) else raw
    variants = [raw, base]
    kebab = camel_to_kebab(base)
    camel = kebab_to_camel(base)
    variants.extend([kebab, camel, f"#{base}", f".{base}", f"#{kebab}", f".{kebab}", f"els.{base}", f"els.{camel}"])
    aliases: list[str] = []
    seen: set[str] = set()
    for item in variants:
        clean = item.strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        aliases.append(clean)
    return aliases[:14]


def agent_ui_symbol_resolver(server: WasmAgentServer, message: str) -> dict[str, Any] | None:
    queries = ui_symbol_queries(message)
    if not queries:
        return None
    root = repo_root(server)
    symbols: list[dict[str, Any]] = []
    for query in queries:
        aliases = ui_symbol_aliases(query)
        matches: list[dict[str, Any]] = []
        for rel in UI_SYMBOL_FILES:
            path = root / rel
            if not path.exists():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            file_match_count = 0
            for lineno, line in enumerate(lines, 1):
                line_lower = line.lower()
                matched_alias = next(
                    (
                        alias
                        for alias in sorted(aliases, key=len, reverse=True)
                        if alias in line or alias.lower() in line_lower
                    ),
                    "",
                )
                if not matched_alias:
                    continue
                matches.append({
                    "path": rel,
                    "line": lineno,
                    "alias": matched_alias,
                    "text": clipped(line.strip(), 220),
                })
                file_match_count += 1
                if file_match_count >= 4:
                    break
        if matches:
            symbols.append({
                "query": query,
                "aliases": aliases,
                "matches": matches,
            })
    if not symbols:
        return None
    return {
        "tool": "ui_symbol_resolver",
        "query": clipped(message, 240),
        "content": json.dumps(
            {
                "schema": "hermes.wasm_agent.ui_symbol_resolution.v1",
                "rule": "Do not answer that a UI symbol is missing when this resolver has matches. Prefer exact path+line evidence and the matched selector/id/handle.",
                "symbols": symbols,
            },
            ensure_ascii=True,
        ),
    }


def negative_symbol_claim(reply: str) -> bool:
    text = reply.lower()
    return any(
        phrase in text
        for phrase in (
            "cannot find",
            "can't find",
            "could not find",
            "couldn't find",
            "not find",
            "no matches",
            "does not exist",
            "don't see",
        )
    )


def symbol_resolution_summary(tool: dict[str, Any] | None) -> str:
    if not tool:
        return ""
    content = parsed_tool_content(tool)
    symbols = content.get("symbols") if isinstance(content.get("symbols"), list) else []
    lines: list[str] = []
    for symbol in symbols[:4]:
        if not isinstance(symbol, dict):
            continue
        matches = symbol.get("matches") if isinstance(symbol.get("matches"), list) else []
        if not matches:
            continue
        rendered = []
        used_paths: set[str] = set()
        sampled_matches: list[dict[str, Any]] = []
        for match in matches:
            if not isinstance(match, dict):
                continue
            path = str(match.get("path") or "")
            if path and path not in used_paths:
                sampled_matches.append(match)
                used_paths.add(path)
            if len(sampled_matches) >= 4:
                break
        if len(sampled_matches) < 4:
            for match in matches:
                if isinstance(match, dict) and match not in sampled_matches:
                    sampled_matches.append(match)
                if len(sampled_matches) >= 4:
                    break
        for match in sampled_matches[:4]:
            if isinstance(match, dict):
                rendered.append(f"{match.get('path')}:{match.get('line')} ({match.get('alias')})")
        if rendered:
            lines.append(f"- `{symbol.get('query')}` -> " + ", ".join(rendered))
    return "\n".join(lines)


def correct_negative_symbol_reply(server: WasmAgentServer, message: str, reply: str) -> str:
    if not negative_symbol_claim(reply):
        return reply
    tool = agent_ui_symbol_resolver(server, message)
    summary = symbol_resolution_summary(tool)
    if not summary:
        return reply
    return clipped(
        reply
        + "\n\nAdapter symbol check: local source lookup found likely UI symbol matches, so the symbol should not be treated as missing:\n"
        + summary
        + "\nUse those paths/selectors for the next patch.",
        8000,
    )


def agent_latest_observation(server: WasmAgentServer, user: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = latest_observation(server, user).get("observation") or {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "tool": "observation_latest",
        "timestamp": payload.get("timestamp", ""),
        "workspace": payload.get("workspace", {}),
        "fleet": {
            "selected_node": payload.get("fleet", {}).get("selected_node"),
            "node_count": payload.get("fleet", {}).get("node_count"),
            "bridge_ready": payload.get("fleet", {}).get("bridge_ready"),
        },
        "requested_click_context": payload.get("requested_click_context") or payload.get("analytics", {}).get("last_non_agent_click"),
        "last_event": (payload.get("user_events") or [{}])[0],
    }


def agent_latest_client_snapshot(server: WasmAgentServer, user: dict[str, Any] | None = None) -> dict[str, Any]:
    result = latest_client_snapshot(server, user)
    payload = result.get("snapshot") or {}
    if not isinstance(payload, dict):
        payload = {}
    wis = payload.get("wis") if isinstance(payload.get("wis"), dict) else {}
    agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
    return {
        "tool": "client_snapshot_latest",
        "path": result.get("path", ""),
        "snapshot_id": payload.get("snapshot_id", ""),
        "created_at": payload.get("created_at", ""),
        "reason": payload.get("reason", ""),
        "scope": payload.get("scope", ""),
        "active_space": payload.get("active_space", {}),
        "agent": {
            "target_node": agent.get("target_node", ""),
            "selected_node": agent.get("selected_node", ""),
            "model": agent.get("model"),
            "direct_provider": agent.get("direct_provider"),
        },
        "wis": {
            "active_artifact": wis.get("active_artifact"),
            "artifact_count": wis.get("artifact_count"),
            "camera_configs": wis.get("camera_configs", []),
            "camera_runtime": wis.get("camera_runtime", []),
            "camera_debug_events": wis.get("camera_debug_events", []),
        },
    }


def infer_agent_tools(
    server: WasmAgentServer,
    message: str,
    *,
    user: dict[str, Any] | None = None,
    action_callback: Any | None = None,
    action_offset: int = 0,
) -> list[dict[str, Any]]:
    lowered = message.lower()
    tools: list[dict[str, Any]] = []
    seen = set()

    def add_tool(tool: dict[str, Any]) -> None:
        if len(tools) >= 6:
            return
        key = (tool.get("tool"), tool.get("path"), tool.get("query"))
        if key in seen:
            return
        seen.add(key)
        tools.append(tool)
        if action_callback:
            action_callback(tool_action_event(tool, action_offset + len(tools)))

    add_tool(agent_latest_observation(server, user))
    add_tool(agent_latest_client_snapshot(server, user))
    admin_context_allowed = user_is_admin(user)
    wants_evolution_context = any(
        phrase in lowered
        for phrase in (
            "evolve the app",
            "evolve app",
            "from chat",
            "from there",
            "cheaper",
            "chat",
            "adapter",
            "ui",
            "patch proposal",
            "real patch",
            "proposal",
            "patch",
        )
    )
    if wants_evolution_context:
        if admin_context_allowed:
            add_tool(agent_app_map(server))
            symbol_tool = agent_ui_symbol_resolver(server, message)
            if symbol_tool:
                add_tool(symbol_tool)
            add_tool(agent_git_status(server))
            add_tool(agent_git_diff_stat(server))
        else:
            add_tool(agent_user_scope_status(server, user))
        add_tool(agent_timeline_status(server, user))
    if "read /local/readme.md" in lowered or "read readme" in lowered or "resume our work" in lowered:
        if admin_context_allowed:
            add_tool(agent_read_file(server, "/local/README.md"))
            roadmap = repo_root(server) / "docs" / "roadmap" / "space-os" / "embedded-agent-path.md"
            if roadmap.exists():
                add_tool(agent_read_file(server, str(roadmap)))
        else:
            add_tool(agent_user_scope_status(server, user))
    if "git status" in lowered or "worktree" in lowered:
        if admin_context_allowed:
            add_tool(agent_git_status(server))
        else:
            add_tool(agent_user_scope_status(server, user))
    if "doctor" in lowered or "health" in lowered:
        if admin_context_allowed:
            add_tool(agent_doctor(server))
    if lowered.startswith("search ") or "\nsearch " in lowered:
        if admin_context_allowed:
            query = message.split("search ", 1)[1].splitlines()[0]
            add_tool(agent_search(server, query))
    return tools


def compact_transcript(body: dict[str, Any]) -> list[dict[str, str]]:
    transcript = body.get("transcript")
    if not isinstance(transcript, list):
        return []
    compact: list[dict[str, str]] = []
    seed_message = "I can see this workspace snapshot and help evolve the app from here."
    current_message = str(body.get("message") or "").strip()
    for item in transcript[-6:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")[:20]
        content = clipped(str(item.get("content") or ""), 600)
        if content == seed_message or (role == "user" and content == current_message):
            continue
        if role in {"user", "assistant"} and content:
            compact.append({"role": role, "content": content})
    return compact


def compact_agent_images(images: Any) -> list[dict[str, Any]] | None:
    if not isinstance(images, list):
        return None
    compact: list[dict[str, Any]] = []
    for item in images[:DEFAULT_AGENT_IMAGE_LIMIT]:
        if not isinstance(item, dict):
            continue
        data_url = str(item.get("data_url") or "")
        if not data_url.startswith("data:image/"):
            continue
        approx_bytes = len(data_url.encode("utf-8"))
        if approx_bytes > DEFAULT_AGENT_IMAGE_MAX_BYTES * 2:
            continue
        compact.append({
            "data_url": data_url,
            "name": clipped(str(item.get("name") or "image"), 120),
            "type": clipped(str(item.get("type") or ""), 80),
            "size": item.get("size") if isinstance(item.get("size"), int) else approx_bytes,
            "width": item.get("width") if isinstance(item.get("width"), int) else None,
            "height": item.get("height") if isinstance(item.get("height"), int) else None,
            "image_card": compact_image_card(item.get("image_card"), item),
            "asset": item.get("asset") if isinstance(item.get("asset"), dict) else None,
        })
    return compact or None


def compact_agent_attachment_summaries(attachments: Any) -> list[dict[str, Any]]:
    if not isinstance(attachments, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in attachments[:DEFAULT_AGENT_IMAGE_LIMIT]:
        if not isinstance(item, dict):
            continue
        media_type = str(item.get("type") or item.get("original_type") or "")
        media_kind = str(item.get("media_kind") or "")
        is_video = media_type.startswith("video/") or media_kind == "video"
        image_card = (
            compact_image_card(item.get("image_card"), item)
            if (isinstance(item.get("image_card"), dict) or not is_video)
            else None
        )
        compact.append({
            "name": clipped(str(item.get("name") or "attachment"), 120),
            "type": clipped(media_type, 80),
            "size": item.get("size") if isinstance(item.get("size"), int) else None,
            "width": item.get("width") if isinstance(item.get("width"), int) else None,
            "height": item.get("height") if isinstance(item.get("height"), int) else None,
            "original_type": clipped(str(item.get("original_type") or ""), 80),
            "original_size": item.get("original_size") if isinstance(item.get("original_size"), int) else None,
            "image_card": image_card,
            "video_card": compact_video_card(item.get("video_card"), item),
            "media_kind": clipped(media_kind, 40),
            "duration_sec": item.get("duration_sec") if isinstance(item.get("duration_sec"), (int, float)) else None,
            "asset": item.get("asset") if isinstance(item.get("asset"), dict) else None,
            "reason": clipped(str(item.get("reason") or "summarized"), 120),
        })
    return compact


def compact_video_card(card: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any] | None:
    source = card if isinstance(card, dict) else {}
    fallback = fallback or {}
    media_type = str(source.get("type") or fallback.get("type") or fallback.get("original_type") or "")
    media_kind = str(source.get("media_kind") or fallback.get("media_kind") or "")
    if not (media_type.startswith("video/") or media_kind == "video" or source):
        return None
    duration = source.get("duration_sec", fallback.get("duration_sec"))
    return {
        "schema": "hermes.wasm_agent.video_card.v1",
        "name": clipped(str(source.get("name") or fallback.get("name") or "video"), 120),
        "type": clipped(media_type, 80),
        "size": source.get("size") if isinstance(source.get("size"), int) else fallback.get("size"),
        "width": source.get("width") if isinstance(source.get("width"), int) else fallback.get("width"),
        "height": source.get("height") if isinstance(source.get("height"), int) else fallback.get("height"),
        "duration_sec": duration if isinstance(duration, (int, float)) else None,
    }


def agent_image_data_url_bytes(image: dict[str, Any]) -> int:
    return len(str(image.get("data_url") or "").encode("utf-8"))


def agent_image_descriptor(
    image: dict[str, Any],
    *,
    raw_included: bool,
    forwarded_to_bridge: bool,
    reason: str = "",
) -> dict[str, Any]:
    image_card = compact_image_card(image.get("image_card"), image)
    asset = image.get("asset") if isinstance(image.get("asset"), dict) else {}
    local_url = str(asset.get("local_url") or image_card.get("local_url") or "")
    digest = str(asset.get("hash") or image_card.get("hash") or "")
    if local_url:
        image_card["local_url"] = clipped(local_url, 240)
    if digest:
        image_card["hash"] = clipped(digest, 120)
    return {
        "name": clipped(str(image.get("name") or "image"), 120),
        "type": clipped(str(image.get("type") or image.get("original_type") or ""), 80),
        "size": image.get("size") if isinstance(image.get("size"), int) else agent_image_data_url_bytes(image),
        "width": image.get("width") if isinstance(image.get("width"), int) else None,
        "height": image.get("height") if isinstance(image.get("height"), int) else None,
        "original_type": clipped(str(image.get("original_type") or ""), 80),
        "original_size": image.get("original_size") if isinstance(image.get("original_size"), int) else None,
        "local_url": local_url,
        "hash": digest,
        "image_card": image_card,
        "raw_included": raw_included,
        "forwarded_to_bridge": forwarded_to_bridge,
        "reason": reason,
    }


def agent_file_descriptor(
    item: dict[str, Any],
    *,
    reason: str = "",
) -> dict[str, Any]:
    video_card = compact_video_card(item.get("video_card"), item)
    media_type = str(item.get("type") or item.get("original_type") or "")
    media_kind = str(item.get("media_kind") or ("video" if media_type.startswith("video/") else "file"))
    return {
        "name": clipped(str(item.get("name") or "attachment"), 120),
        "type": clipped(media_type, 80),
        "size": item.get("size") if isinstance(item.get("size"), int) else None,
        "width": item.get("width") if isinstance(item.get("width"), int) else None,
        "height": item.get("height") if isinstance(item.get("height"), int) else None,
        "original_type": clipped(str(item.get("original_type") or ""), 80),
        "original_size": item.get("original_size") if isinstance(item.get("original_size"), int) else None,
        "media_kind": clipped(media_kind, 40),
        "duration_sec": item.get("duration_sec") if isinstance(item.get("duration_sec"), (int, float)) else None,
        "video_card": video_card,
        "raw_included": False,
        "forwarded_to_bridge": False,
        "reason": reason,
    }


def agent_bridge_forwards_image_urls() -> bool:
    raw = os.getenv(
        "HERMES_WASM_AGENT_FORWARD_IMAGE_URLS",
        "1" if DEFAULT_AGENT_BRIDGE_FORWARD_IMAGE_URLS else "0",
    ).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def plan_bridge_attachments(
    images: list[dict[str, Any]] | None,
    summaries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    forwarded: list[dict[str, Any]] = []
    descriptors: list[dict[str, Any]] = []
    forwarded_bytes = 0
    may_forward_image_urls = agent_bridge_forwards_image_urls()
    for image in images or []:
        data_url_bytes = agent_image_data_url_bytes(image)
        can_forward = (
            may_forward_image_urls
            and data_url_bytes > 0
            and data_url_bytes <= DEFAULT_AGENT_BRIDGE_IMAGE_SINGLE_BYTES
            and forwarded_bytes + data_url_bytes <= DEFAULT_AGENT_BRIDGE_IMAGE_BYTES
        )
        if can_forward:
            forwarded.append(image)
            forwarded_bytes += data_url_bytes
        descriptors.append(agent_image_descriptor(
            image,
            raw_included=True,
            forwarded_to_bridge=can_forward,
            reason="" if can_forward else (
                "bridge_image_url_forwarding_disabled"
                if not may_forward_image_urls
                else "summarized_to_keep_bridge_request_small"
            ),
        ))
    for item in summaries:
        media_type = str(item.get("type") or item.get("original_type") or "")
        is_video = media_type.startswith("video/") or str(item.get("media_kind") or "") == "video"
        reason = str(item.get("reason") or ("video_metadata_only" if is_video else "summarized"))
        if is_video and not isinstance(item.get("image_card"), dict):
            descriptors.append(agent_file_descriptor(item, reason=reason))
        else:
            descriptors.append({
                **agent_image_descriptor(
                    item,
                    raw_included=False,
                    forwarded_to_bridge=False,
                    reason=reason,
                ),
                "size": item.get("size") if isinstance(item.get("size"), int) else None,
            })
    if not descriptors:
        return forwarded, None
    manifest = {
        "attachments": descriptors,
        "received_count": len(descriptors),
        "forwarded_count": len(forwarded),
        "summarized_count": len(descriptors) - len(forwarded),
        "image_card_count": sum(1 for item in descriptors if item.get("image_card")),
        "video_attachment_count": sum(1 for item in descriptors if item.get("video_card")),
        "bridge_image_bytes": forwarded_bytes,
        "bridge_image_budget_bytes": DEFAULT_AGENT_BRIDGE_IMAGE_BYTES,
        "image_url_forwarding_enabled": may_forward_image_urls,
        "policy": (
            "Forward raw image_url parts only when HERMES_WASM_AGENT_FORWARD_IMAGE_URLS is enabled "
            "and the bridge request stays under its size budget; always preserve compact browser-built "
            "image_card metadata for text-only providers. Treat filenames, local URLs, and surrounding "
            "workspace state as context, not visual proof. Do not claim object identity, wallpaper/background "
            "role, OCR text, UI placement, or video contents unless raw vision/video analysis or user-provided "
            "context establishes it. Video files are represented as metadata only in this adapter."
        ),
        "semantic_limits": [
            "image_card is browser pixel metadata, not full object recognition",
            "video_card is filename, type, size, duration, and dimensions metadata only",
            "filename and local_url are not visual evidence",
            "shape hints are not object identity",
            "do not infer wallpaper/background role from a name like bg",
        ],
    }
    return forwarded, {
        "tool": "attachment_manifest",
        "received_count": manifest["received_count"],
        "forwarded_count": manifest["forwarded_count"],
        "summarized_count": manifest["summarized_count"],
        "image_card_count": manifest["image_card_count"],
        "video_attachment_count": manifest["video_attachment_count"],
        "bridge_image_budget_bytes": DEFAULT_AGENT_BRIDGE_IMAGE_BYTES,
        "content": json.dumps(manifest, ensure_ascii=True),
    }


def redact_image_card_focus_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("tool") != "attachment_manifest":
            sanitized.append(tool)
            continue
        try:
            manifest = json.loads(str(tool.get("content") or "{}"))
        except json.JSONDecodeError:
            sanitized.append(tool)
            continue
        if not isinstance(manifest, dict):
            sanitized.append(tool)
            continue
        attachments = manifest.get("attachments")
        if not isinstance(attachments, list):
            sanitized.append(tool)
            continue
        redacted_attachments: list[Any] = []
        for index, item in enumerate(attachments):
            if not isinstance(item, dict):
                redacted_attachments.append(item)
                continue
            label = f"attachment-{index + 1}"
            clean_item = {**item, "name": label, "local_url": "", "hash": ""}
            image_card = clean_item.get("image_card") if isinstance(clean_item.get("image_card"), dict) else None
            if image_card:
                clean_item["image_card"] = {**image_card, "name": label, "local_url": "", "hash": ""}
            redacted_attachments.append(clean_item)
        policy = str(manifest.get("policy") or "")
        manifest = {
            **manifest,
            "attachments": redacted_attachments,
            "policy": (
                f"{policy} Attachment names, hashes, and local URLs are redacted from image-card-only "
                "model context because they are bookkeeping, not visual evidence."
            ).strip(),
        }
        sanitized.append({**tool, "content": json.dumps(manifest, ensure_ascii=True)})
    return sanitized


def agent_bridge_timeout_sec() -> float:
    raw = os.getenv("HERMES_WASM_AGENT_CHAT_TIMEOUT_SEC", str(DEFAULT_AGENT_BRIDGE_TIMEOUT_SEC))
    try:
        value = float(raw)
    except ValueError:
        value = DEFAULT_AGENT_BRIDGE_TIMEOUT_SEC
    return max(30.0, min(6 * 60 * 60.0, value))


def requested_agent_model(body: dict[str, Any]) -> dict[str, str] | None:
    model_id = str(body.get("model") or "").strip()
    provider = str(body.get("model_provider") or "").strip()
    if not model_id and not provider:
        return None
    if provider and model_id and "/" not in model_id:
        label = f"{provider}/{model_id}"
    else:
        label = model_id or provider
    return {
        "id": clipped(label, 180),
        "provider": clipped(provider, 80),
    }


def _safe_agent_node_id(raw: Any) -> str:
    node_id = str(raw or "orchestrator").strip() or "orchestrator"
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", node_id):
        raise BrowserError("invalid_node", "Node id contains unsupported characters.")
    return node_id


def _node_env_root(server: WasmAgentServer) -> Path:
    return Path(os.getenv("HERMES_AGENTS_ENVS_ROOT", str(repo_root(server) / "agents" / "envs"))).resolve()


def _node_env_path(server: WasmAgentServer, node_id: str) -> Path:
    root = _node_env_root(server)
    path = (root / f"{node_id}.env").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise BrowserError("invalid_node", "Node env path escapes the configured env root.") from exc
    if not path.exists():
        raise BrowserError("node_env_missing", f"Node env file was not found for {node_id}.", status=HTTPStatus.NOT_FOUND)
    return path


def _node_config_path(server: WasmAgentServer, node_id: str) -> Path:
    return (repo_root(server) / "agents" / "nodes" / node_id / ".hermes" / "config.yaml").resolve()


def _parse_env_text(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            env[key] = value
    return env


def _shell_env_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@+=-]*", value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _replace_or_append_env_value(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    replacement = f"{key}={_shell_env_value(value)}"
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        existing_key = stripped.split("=", 1)[0].strip()
        if existing_key == key:
            lines[index] = replacement
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(replacement)
    return "\n".join(lines).rstrip() + "\n"


def _parse_setup_model(raw_model: Any, env: dict[str, str]) -> dict[str, str]:
    raw = str(raw_model or "").strip()
    raw = re.sub(r"\s+", "", raw)
    if not raw:
        raise BrowserError("missing_model", "Model id is required.")
    if not re.fullmatch(r"[A-Za-z0-9._:/@+=-]{2,180}", raw):
        raise BrowserError("invalid_model", "Model id contains unsupported characters.")
    if "/" in raw:
        provider, model_name = raw.split("/", 1)
    else:
        provider = (
            env.get("NODE_AGENT_DEFAULT_MODEL_PROVIDER")
            or env.get("DEFAULT_MODEL_PROVIDER")
            or env.get("HERMES_INFERENCE_PROVIDER")
            or ""
        ).strip()
        model_name = raw
    if not provider or not model_name:
        raise BrowserError("invalid_model", "Use a provider/model id, for example opencode-go/kimi-k2.6.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{2,80}", provider):
        raise BrowserError("invalid_model_provider", "Model provider contains unsupported characters.")
    if not re.fullmatch(r"[A-Za-z0-9._:/@+=-]{1,160}", model_name):
        raise BrowserError("invalid_model_name", "Model name contains unsupported characters.")
    model_id = f"{provider}/{model_name}"
    return {
        "id": clipped(model_id, 180),
        "provider": clipped(provider, 80),
        "name": clipped(model_name, 160),
        "label": clipped(model_id, 180),
    }


def _write_node_model_env(env_path: Path, text: str, model: dict[str, str]) -> None:
    updated = text
    provider = model["provider"]
    model_name = model["name"]
    model_id = model["id"]
    for key, value in (
        ("NODE_AGENT_DEFAULT_MODEL_PROVIDER", provider),
        ("NODE_AGENT_DEFAULT_MODEL", model_name),
        ("HERMES_INFERENCE_PROVIDER", provider),
        ("API_SERVER_MODEL_NAME", model_id),
    ):
        updated = _replace_or_append_env_value(updated, key, value)
    env_path.write_text(updated, encoding="utf-8")


def _write_node_model_config(config_path: Path, model: dict[str, str]) -> bool:
    if not config_path.exists():
        return False
    try:
        import yaml  # type: ignore
    except Exception as exc:
        raise BrowserError("yaml_unavailable", "PyYAML is required to update the node model config.") from exc
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        loaded = {}
    model_cfg = loaded.get("model")
    if not isinstance(model_cfg, dict):
        model_cfg = {}
    previous_provider = str(model_cfg.get("provider") or loaded.get("provider") or "").strip()
    model_cfg["default"] = model["name"]
    model_cfg["provider"] = model["provider"]
    if previous_provider and previous_provider != model["provider"]:
        model_cfg.pop("base_url", None)
        model_cfg.pop("api_mode", None)
    loaded["model"] = model_cfg
    loaded["provider"] = model["provider"]
    config_path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
    return True


def _setup_step(steps: list[dict[str, str]], label: str, status: str, detail: str = "") -> None:
    steps.append({"label": label, "status": status, "detail": clipped(detail, 240)})


def _fail_model_setup(
    code: str,
    message: str,
    steps: list[dict[str, str]],
    *,
    status: HTTPStatus = HTTPStatus.BAD_GATEWAY,
) -> None:
    for step in reversed(steps):
        if step.get("status") == "running":
            step["status"] = "failed"
            break
    raise AgentModelSetupError(code, message, steps=steps, status=status)


def _request_node_restart(server: WasmAgentServer, node_id: str) -> dict[str, Any]:
    return bridge_proxy(
        server,
        "POST",
        f"/nodes/{quote(node_id, safe='')}/action",
        {"action": "restart_node", "payload": {}},
    )


def _bridge_node_payload(server: WasmAgentServer, node_id: str) -> dict[str, Any]:
    payload = bridge_proxy(server, "GET", f"/nodes/{quote(node_id, safe='')}", None)
    node = payload.get("node") if isinstance(payload.get("node"), dict) else payload
    return node if isinstance(node, dict) else {}


def _node_reports_model(server: WasmAgentServer, node_id: str, model: dict[str, str]) -> bool:
    node = _bridge_node_payload(server, node_id)
    raw = node.get("raw") if isinstance(node.get("raw"), dict) else {}
    model_name = str(raw.get("default_model_env") or node.get("default_model_env") or "").strip()
    provider = str(raw.get("default_model_provider_env") or node.get("default_model_provider_env") or "").strip()
    return model_name == model["name"] and provider == model["provider"]


def _node_api_base_url(server: WasmAgentServer, node_id: str) -> str:
    env_key = f"HERMES_WASM_AGENT_BRIDGE_API_SERVER_{node_id.upper().replace('-', '_')}_URL"
    explicit = str(os.getenv(env_key) or os.getenv("HERMES_WASM_AGENT_BRIDGE_API_SERVER_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    env = _parse_env_text(_node_env_path(server, node_id).read_text(encoding="utf-8"))
    port = str(env.get("API_SERVER_PORT") or "").strip()
    host = str(env.get("API_SERVER_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    if not port and node_id == "orchestrator":
        port = "8642"
    if not port:
        raise BrowserError("api_server_url_not_configured", "No native Hermes API server port is configured for this node.")
    return f"http://{host}:{port}".rstrip("/")


def _node_api_key(server: WasmAgentServer, node_id: str) -> str:
    env_key = f"HERMES_WASM_AGENT_BRIDGE_API_SERVER_{node_id.upper().replace('-', '_')}_KEY"
    explicit = str(os.getenv(env_key) or os.getenv("HERMES_WASM_AGENT_BRIDGE_API_SERVER_KEY") or "").strip()
    if explicit:
        return explicit
    env = _parse_env_text(_node_env_path(server, node_id).read_text(encoding="utf-8"))
    return str(env.get("API_SERVER_KEY") or "").strip()


def _node_api_json(
    server: WasmAgentServer,
    node_id: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 20,
) -> dict[str, Any]:
    base_url = _node_api_base_url(server, node_id)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    key = _node_api_key(server, node_id)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = Request(f"{base_url}{path}", data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        raise BrowserError("api_server_http_error", detail or str(exc), status=HTTPStatus.BAD_GATEWAY) from exc
    except URLError as exc:
        raise BrowserError("api_server_unreachable", str(exc.reason), status=HTTPStatus.BAD_GATEWAY) from exc
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise BrowserError("api_server_non_json", raw[:600], status=HTTPStatus.BAD_GATEWAY) from exc
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def _node_api_models_include(server: WasmAgentServer, node_id: str, model_id: str) -> bool:
    payload = _node_api_json(server, node_id, "GET", "/v1/models", timeout=8)
    data = payload.get("data") if isinstance(payload.get("data"), list) else []
    ids = {str(item.get("id") or "").strip() for item in data if isinstance(item, dict)}
    return model_id in ids


def _wait_for_model_runtime(server: WasmAgentServer, node_id: str, model: dict[str, str], deadline: float) -> None:
    last_error = ""
    while time.monotonic() < deadline:
        try:
            if not _node_reports_model(server, node_id, model):
                last_error = "node status has not reported the requested default model yet"
            elif _node_api_models_include(server, node_id, model["id"]):
                return
            else:
                last_error = "native /v1/models has not advertised the requested model yet"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1.5)
    raise BrowserError("model_runtime_not_ready", last_error or "Hermes runtime did not report the requested model.")


def _probe_agent_model(server: WasmAgentServer, node_id: str, model: dict[str, str]) -> dict[str, Any]:
    timeout_sec = min(DEFAULT_AGENT_MODEL_SETUP_TIMEOUT_SEC, max(60.0, agent_bridge_timeout_sec()))
    payload = {
        "model": model["id"],
        "stream": False,
        "target_node": node_id,
        "messages": [
            {"role": "system", "content": "Reply with exactly MODEL_VALIDATION_OK."},
            {"role": "user", "content": "MODEL_VALIDATION_OK"},
        ],
        "timeout_sec": timeout_sec,
    }
    request = Request(
        f"{server.bridge_url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        raise BrowserError("model_probe_http_error", detail or str(exc), status=HTTPStatus.BAD_GATEWAY) from exc
    except Exception as exc:
        raise BrowserError("model_probe_failed", str(exc), status=HTTPStatus.BAD_GATEWAY) from exc
    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
    message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
    content = str(message.get("content") or "").strip()
    if not content:
        raise BrowserError("model_probe_unexpected", "Validation returned an empty assistant response.")
    return {
        "reply": clipped(content, 240),
        "usage": data.get("usage") if isinstance(data.get("usage"), dict) else None,
    }


def setup_agent_model(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    target_node = _safe_agent_node_id(body.get("target_node") or body.get("node_id") or "orchestrator")
    env_path = _node_env_path(server, target_node)
    original_env = env_path.read_text(encoding="utf-8")
    env = _parse_env_text(original_env)
    model = _parse_setup_model(body.get("model") or body.get("id") or body.get("name"), env)
    config_path = _node_config_path(server, target_node)
    original_config = config_path.read_text(encoding="utf-8") if config_path.exists() else None
    steps: list[dict[str, str]] = []
    wrote_runtime = False

    _setup_step(steps, "Validate model id", "done", model["id"])
    try:
        _setup_step(steps, "Write node default", "running", target_node)
        _write_node_model_env(env_path, original_env, model)
        wrote_runtime = True
        config_changed = _write_node_model_config(config_path, model)
        steps[-1]["status"] = "done"
        steps[-1]["detail"] = "env + config" if config_changed else "env"

        _setup_step(steps, "Restart Hermes node", "running", target_node)
        try:
            restart_payload = _request_node_restart(server, target_node)
            steps[-1]["status"] = "done"
            steps[-1]["detail"] = str(restart_payload.get("status") or restart_payload.get("action") or "restart requested")
        except Exception as exc:
            if target_node != "orchestrator":
                raise
            steps[-1]["status"] = "done"
            steps[-1]["detail"] = f"restart requested; bridge reconnected after: {clipped(str(exc), 120)}"

        _setup_step(steps, "Wait for runtime model", "running", model["id"])
        _wait_for_model_runtime(server, target_node, model, time.monotonic() + DEFAULT_AGENT_MODEL_SETUP_TIMEOUT_SEC)
        steps[-1]["status"] = "done"

        _setup_step(steps, "Probe model response", "running", model["id"])
        probe = _probe_agent_model(server, target_node, model)
        steps[-1]["status"] = "done"
        steps[-1]["detail"] = probe.get("reply", "")
    except Exception as exc:
        if wrote_runtime:
            env_path.write_text(original_env, encoding="utf-8")
            if original_config is not None:
                config_path.write_text(original_config, encoding="utf-8")
            try:
                _request_node_restart(server, target_node)
            except Exception:
                pass
        message = f"Model setup failed and was rolled back: {exc}"
        _fail_model_setup("model_setup_failed", clipped(message, 700), steps)

    return {
        "target_node": target_node,
        "model": model,
        "steps": steps,
    }


def provider_text_field(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def compact_bridge_tool_call(raw: Any, index: int = 0) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"id": f"tool_call_{index + 1}", "name": "tool_call", "arguments": clipped(str(raw), 600)}
    function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
    name = str(function.get("name") or raw.get("name") or raw.get("type") or "tool_call")
    arguments = function.get("arguments", raw.get("arguments", raw.get("input", {})))
    if isinstance(arguments, str):
        arguments_text = clipped(arguments, 900)
    else:
        arguments_text = compact_json(arguments, 900)
    return {
        "id": str(raw.get("id") or f"tool_call_{index + 1}"),
        "name": name,
        "type": str(raw.get("type") or "tool_call"),
        "arguments": arguments_text,
    }


def collect_bridge_tool_calls(*sources: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for source in sources:
        items = source if isinstance(source, list) else []
        for item in items:
            calls.append(compact_bridge_tool_call(item, len(calls)))
    return calls[:24]


def bridge_task_usage(task: dict[str, Any]) -> dict[str, Any] | None:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    return token_usage_from_payloads(result, task, source="bridge_runs")


def bridge_event_name(event: dict[str, Any]) -> str:
    return str(event.get("event") or event.get("type") or "run.event")


def bridge_event_summary(event: dict[str, Any]) -> str:
    return clipped(
        str(event.get("summary") or "")
        or str(event.get("result_preview") or "")
        or str(event.get("arguments_preview") or "")
        or str(event.get("details") or "")
        or str(event.get("preview") or "")
        or str(event.get("message") or "")
        or str(event.get("status") or "")
        or str(event.get("error") or "")
        or str(event.get("delta") or event.get("text") or "")
        or str(event.get("tool") or ""),
        360,
    )


def bridge_event_tool_key(event: dict[str, Any], fallback_index: int = 0) -> str:
    tool = str(event.get("tool") or "tool").strip() or "tool"
    call_id = str(
        event.get("tool_call_id")
        or event.get("toolCallId")
        or event.get("call_id")
        or event.get("callId")
        or event.get("id")
        or ""
    ).strip()
    return call_id or tool or f"tool_{fallback_index + 1}"


def bridge_event_tool_status(event: dict[str, Any]) -> str:
    name = bridge_event_name(event)
    raw_status = str(event.get("status") or "").lower()
    if event.get("error") is True or raw_status in {"error", "failed", "failure"}:
        return "error"
    if name == "tool.started":
        return "running"
    if name == "tool.completed":
        return "done"
    if raw_status in {"completed", "complete", "succeeded", "success"}:
        return "done"
    return raw_status or "done"


def bridge_event_tool_arguments(event: dict[str, Any]) -> Any:
    for key in ("args", "arguments", "arguments_preview"):
        value = event.get(key)
        if isinstance(value, dict):
            return value
    return None


def bridge_event_preview(event: dict[str, Any]) -> str:
    for key in ("output", "result_preview", "preview", "summary", "details", "text", "message"):
        value = event.get(key)
        if value:
            return clipped(str(value), 900)
    return ""


def bridge_event_status(event: dict[str, Any]) -> str:
    event_name = bridge_event_name(event)
    raw_status = str(event.get("status") or "").lower()
    if event.get("error") is True or raw_status in {"error", "failed", "failure"} or event_name.endswith(".failed"):
        return "error"
    if event_name.endswith(".completed") or raw_status in {"completed", "complete", "succeeded", "success"}:
        return "done"
    if raw_status in {"queued", "submitted", "pending"}:
        return "queued"
    if event_name.endswith(".started") or raw_status in {"running", "in_progress", "working"}:
        return "running"
    return raw_status or "done"


def bridge_event_source_layer(event: dict[str, Any]) -> str:
    source = str(event.get("source") or "").strip().lower()
    event_name = bridge_event_name(event)
    if source in {"run_status", "status", "poll"}:
        return "backend"
    if event_name in {"reasoning.available", "reasoning.delta", "thinking.delta"}:
        return "model"
    if event_name.startswith("run.events"):
        return "bridge"
    if event_name.startswith("run."):
        return "backend"
    return "backend"


def bridge_lifecycle_event_name(event: dict[str, Any]) -> str:
    event_name = bridge_event_name(event)
    if event_name == "thinking.delta":
        return "model.reasoning.delta"
    if event_name == "reasoning.delta":
        return "model.reasoning.delta"
    if event_name == "reasoning.available":
        return "model.reasoning.available"
    if event_name == "run.events_unavailable":
        return "bridge.run.events_unavailable"
    if event_name.startswith("run."):
        suffix = event_name.split(".", 1)[1] or "event"
        if suffix in {"running", "in_progress", "working"}:
            suffix = "started"
        if suffix in {"complete", "succeeded", "success"}:
            suffix = "completed"
        if suffix in {"submitted", "pending"}:
            suffix = "queued"
        return f"{bridge_event_source_layer(event)}.run.{suffix}"
    return f"{bridge_event_source_layer(event)}.{event_name}"


def bridge_trace_step_key(step: dict[str, Any]) -> str:
    kind = str(step.get("kind") or "")
    if kind in {"backend.run.queued", "backend.run.started", "backend.run.completed", "bridge.run.started", "bridge.run.completed"}:
        return kind
    return f"{kind}:{str(step.get('status') or '').lower()}:{str(step.get('tool') or '')}"


def bridge_trace_step_score(step: dict[str, Any]) -> int:
    summary = str(step.get("summary") or "").strip().lower()
    status = str(step.get("status") or "").strip().lower()
    score = 0
    if summary and summary != status:
        score += 4
    if str(step.get("source") or "") != "run_status":
        score += 2
    if step.get("timestamp"):
        score += 1
    return score


def append_bridge_trace_step(steps: list[dict[str, Any]], seen: dict[str, int], step: dict[str, Any]) -> None:
    key = bridge_trace_step_key(step)
    existing_index = seen.get(key)
    if existing_index is None:
        seen[key] = len(steps)
        steps.append(step)
        return
    existing = steps[existing_index]
    merged_sources = sorted({str(existing.get("source") or ""), str(step.get("source") or "")} - {""})
    replacement = step if bridge_trace_step_score(step) > bridge_trace_step_score(existing) else existing
    steps[existing_index] = {
        **replacement,
        "sources": merged_sources,
    }


def bridge_run_event_action(event: dict[str, Any], index: int = 0) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    event_name = bridge_event_name(event)
    if event_name in {"message.delta", "response.output_text.delta"}:
        return None
    has_tool_identity = bool(
        event.get("tool")
        or event.get("tool_call_id")
        or event.get("toolCallId")
        or event.get("call_id")
        or event.get("callId")
    )
    if (event_name in {"tool.started", "tool.completed"} and has_tool_identity) or event.get("tool"):
        tool = str(event.get("tool") or "tool").strip() or "tool"
        return {
            "id": f"bridge_tool_{timeline_ref_name(bridge_event_tool_key(event, index))}",
            "topic": "run-hermes",
            "kind": "tool",
            "label": tool,
            "status": bridge_event_tool_status(event),
            "detail": bridge_event_summary(event) or event_name,
            "meta": event_name,
            "arguments": bridge_event_tool_arguments(event),
            "preview": bridge_event_preview(event),
        }
    status = bridge_event_status(event)
    label = bridge_lifecycle_event_name(event)
    return {
        "id": f"bridge_event_{timeline_ref_name(label)}",
        "topic": "run-hermes",
        "kind": "trace",
        "label": label,
        "status": status,
        "detail": bridge_event_summary(event),
        "meta": str(event.get("source") or event.get("status") or event.get("timestamp") or ""),
        "preview": compact_json(event, 900),
    }


def bridge_trace_from_task(task: dict[str, Any]) -> dict[str, Any]:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    events = result.get("events") if isinstance(result.get("events"), list) else []
    compact_steps: list[dict[str, Any]] = []
    seen_steps: dict[str, int] = {}
    tools_by_key: dict[str, dict[str, Any]] = {}
    reasoning_text = str(result.get("thinking_stream") or "")
    for index, event in enumerate(events[:36], 1):
        if not isinstance(event, dict):
            continue
        event_name = bridge_event_name(event)
        if event_name in {"message.delta", "response.output_text.delta"}:
            continue
        if event_name in {"tool.started", "tool.completed"} or event.get("tool"):
            key = bridge_event_tool_key(event, index)
            tools_by_key[key] = {
                "id": key,
                "name": str(event.get("tool") or "tool"),
                "type": event_name,
                "status": bridge_event_tool_status(event),
                "arguments": compact_json(event.get("args") or event.get("arguments") or event.get("preview") or {}, 900),
                "summary": bridge_event_summary(event),
            }
            continue
        append_bridge_trace_step(compact_steps, seen_steps, {
            "index": index,
            "kind": bridge_lifecycle_event_name(event),
            "raw_event": event_name,
            "status": str(event.get("status") or bridge_event_status(event)),
            "summary": bridge_event_summary(event),
            "tool": str(event.get("tool") or ""),
            "source": str(event.get("source") or "event_stream"),
            "timestamp": event.get("timestamp") or "",
        })
        if event_name in {"reasoning.available", "reasoning.delta", "thinking.delta"}:
            reasoning_text += str(event.get("text") or event.get("delta") or "")
    if not compact_steps and result.get("last_event"):
        compact_steps.append({
            "index": 1,
            "kind": str(result.get("last_event")),
            "status": str(result.get("run_status") or task.get("status") or ""),
            "summary": str(result.get("response") or "")[:240],
            "tool": "",
            "timestamp": task.get("updated_at") or "",
        })
    return {
        "schema": "hermes.wasm_agent.bridge_trace.v1",
        "id": str(result.get("run_id") or task.get("task_id") or ""),
        "model": str(result.get("model_request") or ""),
        "finish_reason": str(task.get("status") or result.get("run_status") or ""),
        "reasoning_summary": summarize_reasoning_surface(reasoning_text, ""),
        "tool_calls": list(tools_by_key.values())[:24],
        "steps": compact_steps[:24],
    }


def summarize_reasoning_surface(raw_reasoning: str, explicit_summary: str = "") -> str:
    if explicit_summary:
        return clipped(explicit_summary, 900)
    if raw_reasoning:
        return (
            f"Provider returned {len(raw_reasoning)} characters of reasoning content. "
            "Raw hidden reasoning is not replayed here; use the bridge tool-call rows and final answer trace for the operational path."
        )
    return ""


def bridge_trace_from_response(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message_obj = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    raw_reasoning = (
        provider_text_field(message_obj, ("reasoning", "reasoning_content", "thoughts"))
        or provider_text_field(choice, ("reasoning", "reasoning_content", "thoughts"))
        or provider_text_field(data, ("reasoning", "reasoning_content", "thoughts"))
    )
    explicit_summary = (
        provider_text_field(message_obj, ("reasoning_summary", "summary"))
        or provider_text_field(choice, ("reasoning_summary", "summary"))
        or provider_text_field(data, ("reasoning_summary", "summary"))
    )
    steps = data.get("steps") if isinstance(data.get("steps"), list) else []
    compact_steps: list[dict[str, Any]] = []
    step_tool_calls: list[Any] = []
    for index, step in enumerate(steps[:18], 1):
        if not isinstance(step, dict):
            compact_steps.append({"index": index, "kind": "step", "summary": clipped(str(step), 240)})
            continue
        step_calls = step.get("tool_calls") if isinstance(step.get("tool_calls"), list) else []
        step_tool_calls.extend(step_calls)
        compact_steps.append(
            {
                "index": index,
                "kind": str(step.get("type") or step.get("kind") or "step"),
                "status": str(step.get("status") or ""),
                "summary": clipped(str(step.get("summary") or step.get("message") or step.get("name") or ""), 360),
                "tool_call_count": len(step_calls),
            }
        )
    tool_calls = collect_bridge_tool_calls(
        message_obj.get("tool_calls"),
        choice.get("tool_calls"),
        data.get("tool_calls"),
        step_tool_calls,
    )
    return {
        "schema": "hermes.wasm_agent.bridge_trace.v1",
        "id": str(data.get("id") or ""),
        "model": str(data.get("model") or message_obj.get("model") or ""),
        "finish_reason": str(choice.get("finish_reason") or ""),
        "reasoning_summary": summarize_reasoning_surface(raw_reasoning, explicit_summary),
        "tool_calls": tool_calls,
        "steps": compact_steps,
    }


def bridge_trace_action_events(trace: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not trace:
        return []
    actions: list[dict[str, Any]] = []
    steps = trace.get("steps") if isinstance(trace.get("steps"), list) else []
    if steps:
        actions.append({
            "id": "bridge_steps",
            "topic": "run-hermes",
            "kind": "trace",
            "label": "Hermes backend lifecycle",
            "status": "done",
            "detail": f"{len(steps)} lifecycle events",
            "meta": trace.get("model") or "bridge",
            "preview": compact_json(steps, 1200),
        })
        for index, step in enumerate(steps[:12], 1):
            if not isinstance(step, dict):
                continue
            kind = str(step.get("kind") or "event")
            step_status = str(step.get("status") or "")
            row_status = "error" if step_status.lower() in {"error", "failed", "failure"} else "done"
            source = step.get("source") or "/".join(str(item) for item in step.get("sources", []) if item)
            actions.append({
                "id": f"bridge_event_{index}_{timeline_ref_name(kind)}",
                "topic": "run-hermes",
                "kind": "trace",
                "label": kind,
                "status": row_status,
                "detail": clipped(str(step.get("summary") or step.get("status") or ""), 180),
                "meta": str(source or step.get("tool") or step.get("timestamp") or ""),
                "preview": compact_json(step, 900),
            })
    tool_calls = trace.get("tool_calls") if isinstance(trace.get("tool_calls"), list) else []
    for index, call in enumerate(tool_calls[:12], 1):
        call_id = str(call.get("id") or call.get("name") or f"tool_{index}")
        actions.append({
            "id": f"bridge_tool_{timeline_ref_name(call_id)}",
            "topic": "run-hermes",
            "kind": "tool",
            "label": str(call.get("name") or "tool"),
            "status": str(call.get("status") or "done"),
            "detail": str(call.get("type") or "tool_call"),
            "meta": call_id,
            "arguments": {"tool": call.get("name"), "source": "target node trace"},
            "preview": str(call.get("summary") or call.get("arguments") or ""),
        })
    reasoning_summary = str(trace.get("reasoning_summary") or "")
    if reasoning_summary:
        actions.append({
            "id": "bridge_reasoning_summary",
            "topic": "run-hermes",
            "kind": "trace",
            "label": "Bridge reasoning summary",
            "status": "done",
            "detail": trace.get("finish_reason") or "provider trace",
            "meta": trace.get("model") or "bridge",
            "preview": reasoning_summary,
        })
    return actions


def latest_public_harness_for_node(user: dict[str, Any] | None, node_id: str) -> dict[str, Any]:
    uid = user_id(user)
    with auth_connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM agent_harness_tb
             WHERE user_id = ? AND node_id = ? AND lifecycle_state != 'archived'
             ORDER BY lifecycle_state = 'ready' DESC, created_at DESC, id DESC
             LIMIT 1
            """,
            (uid, node_id),
        ).fetchone()
    return public_agent_harness(row) if row else {}


def embedded_node_config_from_body(
    body: dict[str, Any],
    *,
    user: dict[str, Any] | None,
    target_node: str,
    selected_model: dict[str, str] | None,
) -> dict[str, str]:
    raw = body.get("node_config") if isinstance(body.get("node_config"), dict) else {}
    harness = latest_public_harness_for_node(user, target_node) if user and target_node else {}
    name = clipped(str(raw.get("name") or harness.get("harness_name") or harness.get("node_name") or target_node or "Embedded agent").strip(), 120)
    node_type = clipped(str(raw.get("type") or harness.get("harness_type") or "hermes").strip(), 80)
    raw_instructions = str(raw.get("instructions") or "").strip()
    harness_instructions = str(harness.get("instructions") or (harness.get("metadata") or {}).get("instructions") or "").strip()
    instructions = clipped(raw_instructions or harness_instructions, 4000)
    instruction_source = clipped(
        str(raw.get("instruction_source") or ("browser-local node form" if raw_instructions else "account harness metadata" if harness_instructions else "none")).strip(),
        120,
    )
    provider = clipped(str((selected_model or {}).get("provider") or raw.get("provider") or "").strip(), 120)
    model = clipped(str((selected_model or {}).get("id") or raw.get("model") or "").strip(), 180)
    provider_model_source = clipped(
        str(raw.get("provider_model_source") or ("chat model selector" if (selected_model or {}).get("id") else "node runtime default")).strip(),
        120,
    )
    return {
        "schema": "hermes.wasm_agent.node_run_config.v1",
        "node_id": clipped(str(target_node or raw.get("node_id") or "").strip(), 120),
        "name": name,
        "type": node_type,
        "instructions": instructions,
        "instruction_source": instruction_source,
        "config_source": clipped(str(raw.get("config_source") or ("account fleet harness" if harness else "node runtime")).strip(), 120),
        "provider": provider,
        "model": model,
        "provider_model_source": provider_model_source,
    }


def embedded_space_context_from_body(body: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    workspace = observation.get("workspace") if isinstance(observation.get("workspace"), dict) else {}
    body_space = body.get("active_space") if isinstance(body.get("active_space"), dict) else {}
    observed_space = workspace.get("active_space") if isinstance(workspace.get("active_space"), dict) else {}
    merged_space = {**observed_space, **body_space}
    raw_space_id = (
        body.get("space_id")
        or merged_space.get("id")
        or merged_space.get("space_id")
        or merged_space.get("storage_id")
        or workspace.get("active_space_id")
        or workspace.get("active_panel")
        or "home"
    )
    space_id = canonical_space_storage_id(str(raw_space_id or ""), "home")
    raw_panel = str(merged_space.get("panel") or workspace.get("active_panel") or space_id).strip()
    panel = clipped(str(canonical_space_storage_id(raw_panel, space_id) if is_reserved_user_space_id(raw_panel) else raw_panel or space_id), 120)
    name = clipped(str(
        body.get("space_name")
        or merged_space.get("name")
        or merged_space.get("title")
        or workspace.get("active_space_name")
        or merged_space.get("display_name")
        or space_id
    ).strip(), 160)
    display_name = clipped(str(
        body.get("space_display_name")
        or merged_space.get("display_name")
        or workspace.get("active_space_display_name")
        or name
    ).strip(), 160)
    kind = clipped(str(
        merged_space.get("kind")
        or ("home" if space_id == "home" else "admin" if space_id == "admin" else "user")
    ).strip(), 60)
    shared_space_id = safe_state_id(str(merged_space.get("shared_space_id") or workspace.get("shared_space_id") or ""), "")
    room = merged_space.get("room") if isinstance(merged_space.get("room"), dict) else {}
    def room_count(key: str) -> int:
        try:
            return max(0, int(float(room.get(key) or 0)))
        except (TypeError, ValueError, OverflowError):
            return 0
    return {
        "schema": "hermes.wasm_agent.active_space.v1",
        "id": space_id,
        "storage_id": space_id,
        "panel": panel,
        "kind": kind,
        "name": name or space_id,
        "title": name or space_id,
        "display_name": display_name or name or space_id,
        "shared": bool(merged_space.get("shared") or shared_space_id),
        "shared_space_id": shared_space_id,
        "room": {
            "id": str(room.get("id") or shared_space_id),
            "online_count": room_count("online_count"),
            "member_count": room_count("member_count"),
            "online_device_count": room_count("online_device_count"),
        } if room or shared_space_id else None,
    }


def embedded_space_context_prompt(space_context: dict[str, Any]) -> str:
    if not space_context:
        return ""
    lines = [
        "Current wasm-agent space:",
        f"- space id: {space_context.get('id') or ''}",
        f"- current space name: {space_context.get('name') or ''}",
        f"- display name: {space_context.get('display_name') or space_context.get('name') or ''}",
        f"- panel: {space_context.get('panel') or ''}",
        f"- kind: {space_context.get('kind') or ''}",
    ]
    if space_context.get("shared_space_id"):
        lines.append(f"- shared space id: {space_context.get('shared_space_id')}")
    lines.append("Use the current space name when the user asks where they are or which space is active.")
    return "\n".join(lines).strip()


def embedded_node_config_prompt(node_config: dict[str, str]) -> str:
    name = str(node_config.get("name") or "Embedded agent")
    node_type = str(node_config.get("type") or "hermes")
    lines = [
        f"You are `{name}`, the configured `{node_type}` agent for this wasm-agent run.",
        "Active node configuration:",
        f"- node id: {node_config.get('node_id') or ''}",
        f"- node name: {name}",
        f"- node type: {node_type}",
        f"- instruction source: {node_config.get('instruction_source') or 'none'}",
        f"- provider/model source: {node_config.get('provider_model_source') or 'node runtime default'}",
    ]
    if node_config.get("provider") or node_config.get("model"):
        lines.append(f"- provider/model: {node_config.get('provider') or 'default'} / {node_config.get('model') or 'default'}")
    instructions = str(node_config.get("instructions") or "").strip()
    if instructions:
        lines.extend(["", "Configured instructions:", instructions])
    return "\n".join(lines).strip()


def call_agent_bridge_runs(
    server: WasmAgentServer,
    *,
    system_content: str,
    text_content: str,
    target_node: str,
    model_id: str,
    selected_model: dict[str, str] | None,
    timeout_sec: float,
    action_callback: Any | None = None,
) -> tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]:
    prompt = f"{system_content}\n\n{text_content}".strip()
    body: dict[str, Any] = {
        "prompt": prompt,
        "model": model_id,
        "timeout_sec": timeout_sec,
        "stream_events": True,
    }
    provider = str((selected_model or {}).get("provider") or "").strip()
    if provider:
        body["provider"] = provider
    if action_callback:
        action_callback({
            "id": "bridge_run",
            "topic": "run-hermes",
            "kind": "model",
            "label": "bridge.run.started",
            "status": "running",
            "detail": f"{target_node} / {model_id}",
            "meta": "Runs API",
        })
    request = Request(
        f"{server.bridge_url}/nodes/{quote(target_node, safe='')}/prompt",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_sec + 15) as response:
        data = json.loads(response.read().decode("utf-8"))
    task = data.get("task") if isinstance(data.get("task"), dict) else {}
    if not task:
        raise BrowserError("bridge_runs_empty", "The bridge did not return a Hermes task.")
    task_id = str(task.get("task_id") or "").strip()
    if task_id and str(task.get("status") or "").lower() in {"running", "queued", "submitted"}:
        seen_events = 0
        deadline = time.monotonic() + timeout_sec
        poll_delay = 0.35
        while time.monotonic() < deadline:
            poll_request = Request(
                f"{server.bridge_url}/tasks/{quote(task_id, safe='')}",
                headers={"Accept": "application/json"},
                method="GET",
            )
            with urlopen(poll_request, timeout=min(12.0, max(3.0, deadline - time.monotonic()))) as poll_response:
                poll_data = json.loads(poll_response.read().decode("utf-8"))
            polled_task = poll_data.get("task") if isinstance(poll_data.get("task"), dict) else {}
            if polled_task:
                task = polled_task
            result = task.get("result") if isinstance(task.get("result"), dict) else {}
            events = result.get("events") if isinstance(result.get("events"), list) else []
            if action_callback:
                for event_index, event in enumerate(events[seen_events:], seen_events):
                    action = bridge_run_event_action(event, event_index)
                    if action:
                        action_callback(action)
                seen_events = len(events)
                run_status = str(result.get("run_status") or task.get("status") or "running")
                action_callback({
                    "id": "bridge_run",
                    "topic": "run-hermes",
                    "kind": "model",
                    "label": "bridge.run.poll",
                    "status": "done" if str(task.get("status") or "").lower() in {"completed", "succeeded"} else "running",
                    "detail": f"{run_status} / {len(events)} events",
                    "meta": str(result.get("last_event") or task_id),
                })
            if str(task.get("status") or "").lower() not in {"running", "queued", "submitted"}:
                break
            time.sleep(poll_delay)
            poll_delay = min(1.4, poll_delay * 1.25)
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    if str(task.get("status") or "").lower() not in {"completed", "succeeded"}:
        error = task.get("error") if isinstance(task.get("error"), dict) else {}
        if action_callback:
            action_callback({
                "id": "bridge_run",
                "topic": "run-hermes",
                "kind": "model",
                "label": "bridge.run.failed",
                "status": "error",
                "detail": str(error.get("message") or "Hermes Runs API task did not complete."),
                "meta": task_id,
            })
        raise BrowserError(
            str(error.get("code") or "bridge_runs_failed"),
            str(error.get("message") or "Hermes Runs API task did not complete."),
            status=HTTPStatus.BAD_GATEWAY,
        )
    reply = str(result.get("response") or result.get("output") or result.get("final_response") or "").strip()
    if not reply:
        reply = "The Hermes Runs API returned an empty assistant response."
    if action_callback:
        action_callback({
            "id": "bridge_run",
            "topic": "run-hermes",
            "kind": "model",
            "label": "bridge.run.completed",
            "status": "done",
            "detail": str(result.get("last_event") or "completed"),
            "meta": task_id,
        })
    return reply, "bridge_runs", bridge_task_usage(task), bridge_trace_from_task(task)


def call_agent_bridge(
    server: WasmAgentServer,
    message: str,
    tools: list[dict[str, Any]],
    transcript: list[dict[str, str]],
    target_node: str,
    selected_model: dict[str, str] | None = None,
    images: list[dict[str, Any]] | None = None,
    image_card_focus: bool = False,
    mutation_policy: dict[str, Any] | None = None,
    node_config: dict[str, str] | None = None,
    space_context: dict[str, Any] | None = None,
    action_callback: Any | None = None,
) -> tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]:
    timeout_sec = agent_bridge_timeout_sec()
    model_id = str((selected_model or {}).get("id") or "embedded-hermes")
    context_label = "Image-card tool results" if image_card_focus else "Tool results"
    text_content = (
        f"Recent transcript:\n{json.dumps(transcript, ensure_ascii=True)}\n\n"
        f"{context_label}:\n{json.dumps(tools, ensure_ascii=True)}\n\n"
        f"Mutation block spec:\n{json.dumps(mutation_block_spec(), ensure_ascii=True)}\n\n"
        f"WIS/userland patch spec:\n{json.dumps(wis_patch_block_spec(), ensure_ascii=True)}\n\n"
        f"User message:\n{message}"
    )
    if images:
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": text_content}]
        for img in images:
            data_url = str(img.get("data_url") or "")
            if data_url:
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": data_url},
                })
        user_content = content_parts
    else:
        user_content = text_content
    node_config = node_config or {"node_id": target_node, "name": "Embedded agent", "type": "hermes"}
    system_content = (
        f"{embedded_node_config_prompt(node_config)}\n\n"
        f"{embedded_space_context_prompt(space_context or {})}\n\n"
        f"You are talking through target node `{target_node}`. "
        f"The selected chat model is `{model_id}`. "
        "Use compact tool results to answer briefly. You may inspect context, "
        "but do not claim you executed mutations or shell actions beyond listed tools. "
        "If the current user message is ambiguous and includes attachments, treat words like 'it' or 'this' "
        "as referring to the attachment unless the user explicitly asks about the workspace or app. "
        "Attachment image_card data is cheap browser pixel metadata, not full vision. "
        "When raw image_url parts were not forwarded, say what the image_card supports and avoid claims "
        "about object identity, wallpaper/background role, OCR text, or UI placement. "
        "Do not treat filenames, local URLs, or surrounding workspace state as visual proof. "
        "There is no vision_analyze tool in this adapter; never offer or name fake vision tools. "
        "When the user asks about the last clicked UI button, use observation.requested_click_context.last_non_agent_click "
        "instead of assistant open/send events. "
        "Client cap p=wa1 can be invoked by appending a hidden fenced block ```wa1\nar W H\n``` for wasm-agent-chat resize. "
        "When the user asks to evolve the app, produce a concrete, small implementation brief: "
        "files, behavior, verification, and whether it needs adapter-applied mutation."
    )
    if mutation_policy:
        scope = str(mutation_policy.get("scope") or "")
        system_content += (
            " Mutation policy for this turn: "
            f"{json.dumps(mutation_policy, ensure_ascii=True)}. "
            "Respect this boundary exactly. Do not invent source filenames; use app_map paths when present. "
        )
        if scope == "global-orchestrator":
            system_content += (
                " For small wasm-agent core/source edits, request the change by appending one fenced json block with schema "
                "`hermes.wasm_agent.mutation.v1` using only exact `replace` or anchored `append` operations. "
                "Append operations must include a non-empty `insert` string, and may include an `after` anchor. "
                "Never send an append operation without `insert`; use `replace` when changing existing text. "
                "For userland components, spaces, automations, dashboards, or games, prefer a fenced json block with schema "
                f"`{WIS_PATCH_SCHEMA}` so the adapter patches a WIS artifact instead of core firmware. "
            )
        else:
            system_content += (
                " Do not emit core source mutations. For userland components, spaces, automations, dashboards, or games, "
                f"append one fenced json block with schema `{WIS_PATCH_SCHEMA}`. "
                "If the user asks for core wasm-agent behavior, explain that it must be delegated to the admin orchestrator. "
            )
        system_content += (
            " Do not say the change was applied; the adapter will append an applied-or-denied summary after validating the block. "
            "If exact source text or artifact structure is unknown, ask for the smallest next inspect step instead of guessing."
        )
    if image_card_focus:
        system_content += (
            " This is an attached-image interpretation turn. Use the image_card metadata as the primary source. "
            "Give the best minimal interpretation the metadata supports, with uncertainty. "
            "You may infer broad visual character from dimensions, palette, luminance, contrast, edge density, "
            "sharpness, entropy, saturation, transparency, visual_notes, and composition fields such as "
            "brightness_distribution, gradient, symmetry, text_regions, scene_hints, shape_hints, and analysis fields like text_like_score. "
            "Text-like scores support claims about likely printed/label-like markings, not exact transcription. "
            "Only quote OCR text when an OCR evidence item has status detected and includes text facts. "
            "OCR text is evidence for readable words only; it does not identify the object carrying those words. "
            "Do not mention attachment filenames, hashes, or local URLs in image-card-only answers unless the user asks about file bookkeeping. "
            "When scene_hints suggests a physical photographed surface, prefer wording like printed label/markings on a photographed object "
            "over document, receipt, or screenshot unless the card specifically supports those categories. "
            "When shape_hints suggests a rounded container or cylindrical surface, say photographed rounded/cylindrical "
            "container-like object or surface rather than generic package/box/sign; do not narrow it to mug, cup, can, "
            "bottle, packaged product, or another object identity unless raw vision or user context supports it. "
            "If examples are useful, label them as examples of the shape class, not the likely identity. "
            "When there is no raw image_url part, avoid identity words like mug, cup, can, bottle, "
            "package, packaged product, drink can, or product label; use rounded/cylindrical physical object or surface "
            "with printed markings instead. "
            "Use evidence, module_results, and analyzer_modules as provenance; "
            "distinguish detected, not_detected, disabled, unsupported, not_loaded, timeout, and error statuses. "
            "If analyzer_revision is missing or older than image-card-text-v2, mention that the browser is likely still using a stale image-card runtime. "
            "Do not infer from workspace observations because they were intentionally omitted. "
            "Do not assert wallpaper/background role, object identity, OCR text, or exact scene content unless the "
            "image_card explicitly supports it. Do not offer to run raw vision analysis from this adapter; "
            "when raw image_url parts were not forwarded, simply say exact recognition would require an explicitly "
            "vision-capable provider path. Keep the answer short and useful."
        )

    def build_payload(content: str | list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "model": model_id,
            "stream": False,
            "target_node": target_node,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": content},
            ],
            "timeout_sec": timeout_sec,
        }

    payload = build_payload(user_content)
    payload_data = json.dumps(payload).encode("utf-8")
    if images and len(payload_data) > DEFAULT_AGENT_BRIDGE_REQUEST_BYTES:
        user_content = (
            text_content
            + "\n\nRaw attachment payloads were omitted because the bridge request budget would be exceeded. "
            "Use the attachment_manifest tool result above for image-card metadata."
        )
        payload = build_payload(user_content)
        payload_data = json.dumps(payload).encode("utf-8")
    if not images:
        try:
            return call_agent_bridge_runs(
                server,
                system_content=system_content,
                text_content=text_content,
                target_node=target_node,
                model_id=model_id,
                selected_model=selected_model,
                timeout_sec=timeout_sec,
                action_callback=action_callback,
            )
        except Exception:
            pass
    request = Request(
        f"{server.bridge_url}/v1/chat/completions",
        data=payload_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return deterministic_agent_reply(message, tools, f"Bridge model did not answer within budget: {exc}"), "local_fallback", {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "source": "local_fallback",
        }, None
    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
    usage = token_usage_from_payloads(data, source="bridge_model")
    if not choices:
        return "The bridge returned no assistant choices.", "bridge_empty", usage, bridge_trace_from_response(data)
    message_obj = choices[0].get("message") if isinstance(choices[0], dict) else {}
    return str(message_obj.get("content") or "The bridge returned an empty assistant response."), "bridge_model", usage, bridge_trace_from_response(data)


def attachment_cards_from_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("tool") != "attachment_manifest":
            continue
        content = parsed_tool_content(tool)
        attachments = content.get("attachments") if isinstance(content.get("attachments"), list) else []
        for item in attachments:
            if not isinstance(item, dict):
                continue
            card = item.get("image_card") if isinstance(item.get("image_card"), dict) else {}
            if not card:
                continue
            cards.append({
                "analyzer_revision": card.get("analyzer_revision") or "",
                "name": item.get("name") or card.get("name") or "image",
                "dimensions": card.get("dimensions") or (
                    f"{item.get('width')}x{item.get('height')}"
                    if item.get("width") and item.get("height")
                    else ""
                ),
                "size": item.get("size") or card.get("size"),
                "palette": card.get("palette") if isinstance(card.get("palette"), list) else [],
                "visual_notes": card.get("visual_notes") if isinstance(card.get("visual_notes"), list) else [],
                "analysis": card.get("analysis") if isinstance(card.get("analysis"), dict) else {},
                "composition": card.get("composition") if isinstance(card.get("composition"), dict) else {},
                "evidence": card.get("evidence") if isinstance(card.get("evidence"), list) else [],
                "module_results": card.get("module_results") if isinstance(card.get("module_results"), dict) else {},
                "analyzer_modules": card.get("analyzer_modules") if isinstance(card.get("analyzer_modules"), list) else [],
                "local_url": item.get("local_url") or card.get("local_url") or "",
                "hash": item.get("hash") or card.get("hash") or card.get("perceptual_hash") or "",
                "forwarded_to_bridge": item.get("forwarded_to_bridge"),
            })
    return cards


def image_question_hint(message: str) -> bool:
    lowered = message.lower().strip()
    if not lowered:
        return True
    image_terms = (
        "what is it",
        "what's this",
        "what is this",
        "what am i looking",
        "describe",
        "attached",
        "attachment",
        "image",
        "picture",
        "photo",
        "screenshot",
    )
    if any(term in lowered for term in image_terms):
        return True
    words = lowered.replace("?", "").split()
    return len(words) <= 5 and any(word in {"it", "this", "that"} for word in words)


def asks_about_attached_image(message: str, cards: list[dict[str, Any]]) -> bool:
    return bool(cards) and image_question_hint(message)


def image_card_reply(cards: list[dict[str, Any]], reason: str) -> str:
    lines = [
        f"{reason}. I only have the browser-built image card for this turn, not full object recognition.",
        "",
        "What I can safely say:",
    ]
    for card in cards[:3]:
        palette = ", ".join(str(item) for item in card.get("palette", [])[:4]) or "unknown palette"
        notes = ", ".join(str(item) for item in card.get("visual_notes", [])[:5]) or "no visual notes"
        analysis = card.get("analysis") if isinstance(card.get("analysis"), dict) else {}
        composition = card.get("composition") if isinstance(card.get("composition"), dict) else {}
        gradient = composition.get("gradient") if isinstance(composition.get("gradient"), dict) else {}
        gradient_text = f" Gradient: {gradient.get('kind')} ({gradient.get('strength')})." if gradient.get("kind") else ""
        text_like = analysis.get("text_like_score")
        text_text = f" Text-like score: {text_like}." if isinstance(text_like, (int, float)) else ""
        revision = str(card.get("analyzer_revision") or "")
        revision_text = f" Analyzer revision: `{clipped(revision, 80)}`." if revision else ""
        evidence = card.get("evidence") if isinstance(card.get("evidence"), list) else []
        evidence_text = "; ".join(
            f"{item.get('module')}: {item.get('status')}"
            for item in evidence[:4]
            if isinstance(item, dict) and item.get("module")
        )
        size = f"{card.get('size')} bytes" if isinstance(card.get("size"), int) else "unknown size"
        local_url = str(card.get("local_url") or "")
        lines.append(
            f"- `{clipped(str(card.get('name') or 'image'), 80)}`: "
            f"{card.get('dimensions') or 'unknown dimensions'}, {size}, palette {palette}; notes: {notes}.{gradient_text}{text_text}"
        )
        if evidence_text:
            lines.append(f"  Analyzer evidence: {clipped(evidence_text, 180)}.")
        if local_url:
            lines.append(f"  Local asset: `{clipped(local_url, 120)}`.")
        if revision_text:
            lines.append(f"  {revision_text}")
    lines.extend([
        "",
        "What I should not claim from this metadata alone: object identity, OCR text, or that it is the workspace background/wallpaper. A filename like `bg` is only a hint, not visual proof.",
    ])
    return "\n".join(lines)


def deterministic_agent_reply(message: str, tools: list[dict[str, Any]], reason: str) -> str:
    tool_names = ", ".join(str(tool.get("tool")) for tool in tools)
    lowered = message.lower()
    cards = attachment_cards_from_tools(tools)
    if asks_about_attached_image(message, cards):
        return image_card_reply(cards, reason)
    if "space" in lowered and ("name" in lowered or "current" in lowered or "where" in lowered):
        for tool in tools:
            workspace = tool.get("workspace") if isinstance(tool.get("workspace"), dict) else {}
            active_space = workspace.get("active_space") if isinstance(workspace.get("active_space"), dict) else {}
            name = str(active_space.get("name") or workspace.get("active_space_name") or "").strip()
            display = str(active_space.get("display_name") or workspace.get("active_space_display_name") or name).strip()
            space_id = str(active_space.get("id") or workspace.get("active_space_id") or workspace.get("active_panel") or "").strip()
            if name or display or space_id:
                return (
                    f"The current wasm-agent space is `{display or name or space_id}`"
                    f"{f' (`{space_id}`)' if space_id and space_id != (display or name) else ''}. "
                    f"{reason}."
                )
    if "last" in lowered and ("click" in lowered or "button" in lowered):
        click = {}
        for tool in tools:
            context = tool.get("requested_click_context") if isinstance(tool.get("requested_click_context"), dict) else {}
            candidate = context.get("last_non_agent_click") if isinstance(context.get("last_non_agent_click"), dict) else None
            if candidate:
                click = candidate
                break
            candidate = tool.get("last_event") if isinstance(tool.get("last_event"), dict) else None
            if candidate and candidate.get("type") == "workspace.click":
                click = candidate
                break
        if click:
            target = click.get("target") or "unknown"
            detail = click.get("data", {}).get("target", {}) if isinstance(click.get("data"), dict) else {}
            classes = " ".join(detail.get("classes") or [])
            title = detail.get("title") or detail.get("aria_label") or target
            return (
                f"The last non-chat UI click I can see was `{target}` at `{click.get('timestamp', '')}`. "
                f"It was the `{title}` button"
                f"{f' with classes `{classes}`' if classes else ''}."
            )
        return "I do not have a non-chat button click in the current observation yet."
    if "resume our work" in lowered or "read /local/readme.md" in lowered:
        return (
            "I read the available local context with inspect-only tools. "
            f"{reason}.\n\n"
            "Current direction: resume from the WASM harness saga. Keep Hermes Orchestrator and wasm-agent "
            "aligned with performance, efficiency, and simplicity. The active work is the in-workspace harness: "
            "Host Browser stream, Observation, embedded assistant, Timeline recovery, and browser-built image cards "
            "that let text-only nodes reason over compact visual facts.\n\n"
            "What I can do from inside the app now: inspect the latest observation, read allowlisted files, "
            "search the repo, check git status, run the wasm-agent doctor, and request guarded exact-match "
            "source mutations through the adapter mutation block.\n\n"
            f"Tools used: {tool_names}."
        )
    if (
        "evolve" in lowered
        or "chat" in lowered
        or "cheaper" in lowered
        or "from there" in lowered
        or "proposal" in lowered
        or "patch" in lowered
    ):
        if "checkpoint" in lowered and ("already exists" in lowered or "exists" in lowered or "show whether" in lowered):
            return (
                f"I gathered compact app-evolution context with: {tool_names}. {reason}.\n\n"
                "Implementation brief:\n"
                "- Files: `plugins/wasm-agent/public/app.js`, `plugins/wasm-agent/public/styles.css`, "
                "`plugins/wasm-agent/tests/wasm_agent_smoke.test.js`, `plugins/wasm-agent/README.md`.\n"
                "- Behavior: remove manual proposal cards and let Timeline record named recovery points automatically "
                "only when a chat turn actually changes the worktree.\n"
                "- UI details: keep checkpoint evidence in the Timeline road, not inside assistant message chrome.\n"
                "- Verification: run `/local/plugins/wasm-agent/scripts/doctor.sh`, `git diff --check`, and probe "
                "`/agent/session/message` with a no-op greeting to confirm `changed_files` is empty.\n"
                "- Apply path: let the selected node answer the turn; the local adapter records a timeline point only if files changed."
            )
        return (
            f"I gathered compact app-evolution context with: {tool_names}. {reason}.\n\n"
            "Implementation brief:\n"
            "- Files: `plugins/wasm-agent/public/app.js`, `plugins/wasm-agent/public/styles.css`, "
            "`plugins/wasm-agent/tests/wasm_agent_smoke.test.js`, `plugins/wasm-agent/README.md`.\n"
            "- Behavior: keep app-evolution turns on a compact tool path, send the selected target node in the bridge payload, "
            "and leave filesystem mutation recovery to automatic Timeline points.\n"
            "- Verification: run `/local/plugins/wasm-agent/scripts/doctor.sh`, `git diff --check`, and probe "
            "`/agent/session/message` with `mode:auto` plus a selected `target_node`.\n"
            "- Apply path: the selected node handles the turn; the adapter names any resulting checkpoint after the target and prompt."
        )
    return (
        f"I gathered inspect-only context with: {tool_names}. {reason}. "
        "The local adapter is alive, but the model backend was unavailable or slow for this turn."
    )


def readiness_blocked_agent_reply(message: str, tools: list[dict[str, Any]], readiness: dict[str, Any]) -> str:
    missing = str(readiness.get("missing_dependency") or readiness.get("status") or "agent_readiness").strip()
    status = str(readiness.get("status") or AGENT_READINESS_BACKEND_UNAVAILABLE)
    readable = str(readiness.get("message") or "Agent is not ready.").strip()
    local = deterministic_agent_reply(
        message,
        tools,
        f"Answered locally because `{missing}` is not available",
    )
    return (
        f"{readable}\n\n"
        f"Missing dependency: `{missing}`. Readiness status: `{status}`.\n\n"
        f"{local}"
    ).strip()


def embedded_agent_message(
    server: WasmAgentServer,
    body: dict[str, Any],
    *,
    user: dict[str, Any] | None = None,
    action_callback: Any | None = None,
) -> dict[str, Any]:
    message = str(body.get("message") or "").strip()
    if not message:
        raise BrowserError("agent_missing_message", "Message is required.")
    mode = str(body.get("mode") or "auto").strip().lower()
    if mode not in {"auto", "local", "bridge"}:
        raise BrowserError("agent_invalid_mode", "Agent mode must be auto, local, or bridge.")
    requested_target_node = _safe_agent_node_id(body.get("target_node") or body.get("node_id") or default_agent_target_node(user))
    ensure_agent_target_allowed(user, requested_target_node)
    target_node = (
        resolve_account_main_node_id(server, user)
        if not user_is_admin(user) and requested_target_node == AGENT_DEFAULT_SANDBOX_NODE_ID
        else requested_target_node
    )
    selected_model = requested_agent_model(body)
    node_config = embedded_node_config_from_body(body, user=user, target_node=target_node, selected_model=selected_model)
    readiness_result: dict[str, Any] | None = None
    mutation_policy = agent_mutation_policy(server, user, target_node)
    def emit_step(
        action_id: str,
        label: str,
        status: str,
        detail: str = "",
        *,
        topic: str = "run-wasm",
        kind: str = "step",
        meta: str = "",
        preview: str = "",
    ) -> None:
        if action_callback:
            action_callback({
                "id": action_id,
                "topic": topic,
                "kind": kind,
                "label": label,
                "status": status,
                "detail": detail,
                "meta": meta,
                "preview": preview,
            })

    def ensure_bridge_readiness() -> dict[str, Any]:
        nonlocal target_node, readiness_result, mutation_policy, node_config
        if readiness_result is None:
            readiness_result = agent_readiness(server, user, target_node=requested_target_node)
            resolved = str(readiness_result.get("target_node") or target_node)
            if resolved and resolved != target_node:
                target_node = resolved
                mutation_policy = agent_mutation_policy(server, user, target_node)
                node_config = embedded_node_config_from_body(body, user=user, target_node=target_node, selected_model=selected_model)
            emit_step(
                "agent_readiness",
                "Agent readiness",
                "done" if readiness_result.get("ready") else "error",
                str(readiness_result.get("missing_dependency") or readiness_result.get("status") or ""),
                topic="run-hermes",
                kind="model",
                meta=str(readiness_result.get("message") or ""),
                preview=compact_json(readiness_result, 1200),
            )
            emit_step(
                "node_config",
                "Node config",
                "done",
                f"{node_config.get('name') or target_node} / {node_config.get('type') or 'hermes'}",
                topic="run-hermes",
                kind="trace",
                meta=str(node_config.get("instruction_source") or "none"),
                preview=compact_json({k: v for k, v in node_config.items() if k != "instructions"} | {"has_instructions": bool(node_config.get("instructions"))}, 1200),
            )
        return readiness_result

    emit_step("turn_intake", "Receive chat turn", "done", f"{target_node} / {mode}", kind="turn")
    emit_step(
        "mutation_policy",
        "Apply mutation policy",
        "done",
        str(mutation_policy.get("scope") or "scope"),
        kind="policy",
        meta="write boundary",
        preview=compact_json(mutation_policy, 900),
    )
    emit_step("collect_context", "Collect context", "running", "observation, tools, transcript", kind="context")
    raw_attachment_present = bool(body.get("images") or body.get("attachments"))
    image_focused_turn = raw_attachment_present and image_question_hint(message)
    before_tree = safe_worktree_tree_sha(server)
    started = time.monotonic()
    observation = body.get("observation") if isinstance(body.get("observation"), dict) else {}
    space_context = embedded_space_context_from_body(body, observation)
    workspace = observation.get("workspace") if isinstance(observation.get("workspace"), dict) else {}
    workspace = {
        **workspace,
        "active_space_id": space_context.get("id") or "",
        "active_space_name": space_context.get("name") or "",
        "active_space_display_name": space_context.get("display_name") or space_context.get("name") or "",
        "active_space": space_context,
    }
    observation = {**observation, "workspace": workspace}
    emit_step(
        "space_context",
        "Current space",
        "done",
        f"{space_context.get('name') or space_context.get('id')} / {space_context.get('id')}",
        kind="context",
        meta=str(space_context.get("display_name") or ""),
        preview=compact_json(space_context, 900),
    )
    tools: list[dict[str, Any]] = []
    if observation and not image_focused_turn:
        current_observation_tool = {
            "tool": "current_turn_observation",
            "timestamp": observation.get("timestamp", ""),
            "cap": observation.get("cap", {}),
            "workspace": workspace,
            "requested_click_context": observation.get("requested_click_context", {}),
            "recent_events": observation.get("recent_events", [])[:6],
        }
        tools.append(current_observation_tool)
        if action_callback:
            action_callback(tool_action_event(current_observation_tool, 1))
    if not image_focused_turn:
        tools.extend(infer_agent_tools(
            server,
            message,
            user=user,
            action_callback=action_callback,
            action_offset=len(tools),
        ))
    transcript = compact_transcript(body)
    images = body.get("images")
    images = compact_agent_images(images)
    attachment_summaries = compact_agent_attachment_summaries(body.get("attachments"))
    bridge_images, attachment_manifest = plan_bridge_attachments(images, attachment_summaries)
    if attachment_manifest:
        tools.append(attachment_manifest)
        if action_callback:
            action_callback(tool_action_event(attachment_manifest, len(tools)))
    emit_step("collect_context", "Collect context", "done", f"{len(tools)} tools / {len(compact_transcript(body))} transcript turns", kind="context")
    image_count = len(images or []) + len(attachment_summaries)
    lowered = message.lower()
    bridge_trace: dict[str, Any] | None = None
    if mode == "local":
        reply = deterministic_agent_reply(message, tools, "Answered in local-only mode")
        source = "local_deterministic"
        token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "source": "local_deterministic",
        }
    elif mode == "auto" and asks_about_attached_image(message, attachment_cards_from_tools(tools)):
        if action_callback:
            action_callback({
                "id": "node_reply",
                "kind": "model",
                "label": "Infer from image card",
                "status": "running",
                "detail": f"{target_node} / image_card",
                "meta": (selected_model or {}).get("id") or "waiting",
            })
        focus_tools = redact_image_card_focus_tools([attachment_manifest] if attachment_manifest else tools)
        readiness = ensure_bridge_readiness()
        if not readiness.get("ready"):
            reply = readiness_blocked_agent_reply(message, tools, readiness)
            source = "local_readiness_fallback"
            token_usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "source": "local_readiness_fallback",
            }
        else:
            reply, source, token_usage, bridge_trace = call_agent_bridge(
                server,
                message,
                focus_tools,
                transcript,
                target_node,
                selected_model=selected_model,
                images=None,
                image_card_focus=True,
                mutation_policy=mutation_policy,
                node_config=node_config,
                space_context=space_context,
                action_callback=action_callback,
            )
        if source.startswith("local_") and source != "local_readiness_fallback":
            reply = deterministic_agent_reply(
                message,
                tools,
                "Answered locally from image-card metadata because the bridge image-card inference path was unavailable",
            )
            source = "local_image_card_fallback"
            token_usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "source": "local_image_card_fallback",
            }
        elif source == "bridge_model":
            source = "bridge_image_card"
    elif mode == "auto" and (
        "resume our work" in lowered
        or "read /local/readme.md" in lowered
    ):
        reply = deterministic_agent_reply(message, tools, "Answered locally for this known inspect/resume request")
        source = "local_deterministic"
        token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "source": "local_deterministic",
        }
    else:
        if action_callback:
            action_callback({
                "id": "node_reply",
                "topic": "run-hermes",
                "kind": "model",
                "label": "Final response",
                "status": "running",
                "detail": f"{target_node} / {mode}",
                "meta": (selected_model or {}).get("id") or "waiting",
            })
        readiness = ensure_bridge_readiness()
        if not readiness.get("ready"):
            reply = readiness_blocked_agent_reply(message, tools, readiness)
            source = "local_readiness_fallback"
            token_usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "source": "local_readiness_fallback",
            }
        else:
            reply, source, token_usage, bridge_trace = call_agent_bridge(
                server,
                message,
                tools,
                transcript,
                target_node,
                selected_model=selected_model,
                images=bridge_images,
                mutation_policy=mutation_policy,
                node_config=node_config,
                space_context=space_context,
                action_callback=action_callback,
            )
    reply = correct_negative_symbol_reply(server, message, reply)
    emit_step("decode_hermes_response", "Decode Hermes response", "done", source, topic="run-hermes", kind="trace")
    space_id = safe_state_id(str(space_context.get("id") or body.get("space_id") or observation.get("workspace", {}).get("active_panel") or "home"), "home")
    wis_patch_result: dict[str, Any] | None = None
    reply, wis_patch_result = apply_agent_wis_patches_from_reply(
        server,
        reply,
        user=user,
        space_id=space_id,
        shared_space_id=safe_state_id(str(space_context.get("shared_space_id") or ""), ""),
    )
    if action_callback and wis_patch_result:
        applied = bool(wis_patch_result.get("applied"))
        patches = wis_patch_result.get("patches") if isinstance(wis_patch_result.get("patches"), list) else []
        action_callback({
            "id": "apply_wis_patch",
            "topic": "run-wasm",
            "kind": "mutation",
            "label": "Apply WIS/userland patch",
            "status": "done" if applied else "error",
            "detail": (
                f"{len(patches)} artifacts / {wis_patch_result.get('operations', 0)} operations"
                if applied
                else action_denial_detail(wis_patch_result, "patch denied")
            ),
            "meta": "adapter",
            "preview": compact_json(wis_patch_result, 1200),
            "arguments": {"schema": WIS_PATCH_SCHEMA},
        })
    mutation_result: dict[str, Any] | None = None
    reply, mutation_result = apply_agent_mutations_from_reply(
        server,
        reply,
        user=user,
        mutation_policy=mutation_policy,
    )
    if action_callback and mutation_result:
        applied = bool(mutation_result.get("applied"))
        action_callback({
            "id": "apply_source_mutation",
            "topic": "run-wasm",
            "kind": "mutation",
            "label": "Apply source mutation",
            "status": "done" if applied else "error",
            "detail": (
                f"{len(mutation_result.get('files') if isinstance(mutation_result.get('files'), list) else [])} files / "
                f"{mutation_result.get('operations', 0)} operations"
                if applied
                else action_denial_detail(mutation_result, "mutation denied")
            ),
            "meta": "adapter",
            "preview": compact_json(mutation_result, 1200),
            "arguments": {"schema": "hermes.wasm_agent.mutation.v1"},
        })
    duration_ms = int((time.monotonic() - started) * 1000)
    token_usage = normalize_token_usage(token_usage, source=source) or token_usage
    context_bytes = sum(text_size(tool) for tool in tools)
    after_tree = safe_worktree_tree_sha(server)
    files = changed_files_between_trees(server, before_tree, after_tree)
    checkpoint_summary = run_checkpoint_summary(message)
    before_checkpoint = (
        create_timeline_checkpoint(
            server,
            label=timeline_ref_name(f"before-chat-{target_node}-{checkpoint_summary}"),
            message=f"wasm-agent before chat on {target_node}: {checkpoint_summary}",
            automatic=True,
            user=user,
            space_id=space_id,
            tree_sha=before_tree,
            extra_metadata={
                "phase": "before_run",
                "after_tree": after_tree,
                "changed_files": files,
                "scope": timeline_scope_for_paths(server, [str(item.get("path") or "") for item in files], user),
            },
        )
        if files and before_tree
        else None
    )
    auto_checkpoint = (
        timeline_auto_checkpoint(
            server,
            f"chat-{target_node}-{checkpoint_summary}",
            message=f"wasm-agent chat on {target_node}: {checkpoint_summary}",
            tree_sha=after_tree,
            before_tree=before_tree,
            before_ref=before_checkpoint.get("ref") if before_checkpoint else None,
            changed_files=files,
            user=user,
            space_id=space_id,
        )
        if files
        else None
    )
    return {
        "schema": "hermes.wasm_agent.embedded_agent.message.v1",
        "session_id": str(body.get("session_id") or "local"),
        "target_node": target_node,
        "reply": clipped(reply, 8000),
        "tools": [{"tool": tool.get("tool"), "path": tool.get("path"), "returncode": tool.get("returncode")} for tool in tools],
        "duration_ms": duration_ms,
        "actions": agent_action_events(
            tools,
            mode=mode,
            target_node=target_node,
            transcript_turns=len(transcript),
            image_count=image_count,
            source=source,
            duration_ms=duration_ms,
            token_usage=token_usage,
            auto_checkpoint=auto_checkpoint,
            before_checkpoint=before_checkpoint,
            changed=files,
            bridge_trace=bridge_trace,
            readiness=readiness_result,
            node_config=node_config,
            space_context=space_context,
            mutation_policy=mutation_policy,
            wis_patch_result=wis_patch_result,
            mutation_result=mutation_result,
        ),
        "diagnostics": {
            "source": source,
            "mode": mode,
            "target_node": target_node,
            "duration_ms": duration_ms,
            "tool_count": len(tools),
            "tools": [str(tool.get("tool")) for tool in tools],
            "transcript_turns": len(transcript),
            "context_bytes": context_bytes,
            "context_estimated_tokens": max(1, context_bytes // 4),
            "token_usage": token_usage,
            "selected_model": selected_model,
            "node_config": {k: v for k, v in node_config.items() if k != "instructions"} | {"has_instructions": bool(node_config.get("instructions"))},
            "space_context": space_context,
            "model_tokens_avoided": source.startswith("local_"),
            "bridge_trace": bridge_trace,
            "readiness": readiness_result,
            "missing_dependency": (readiness_result or {}).get("missing_dependency") or "",
            "mutation_policy": mutation_policy,
            "wis_patch_result": wis_patch_result,
            "mutation_result": mutation_result,
            "changed_files_complete": True,
            "attachments": {
                "received": image_count,
                "raw_forwarded_to_bridge": len(bridge_images),
                "summarized": max(0, image_count - len(bridge_images)),
            },
            "before_checkpoint": {
                "ref": before_checkpoint.get("ref"),
                "sha": str(before_checkpoint.get("sha") or "")[:7],
                "label": before_checkpoint.get("label"),
            } if before_checkpoint else None,
            "auto_checkpoint": {
                "ref": auto_checkpoint.get("ref"),
                "sha": str(auto_checkpoint.get("sha") or "")[:7],
                "label": auto_checkpoint.get("label"),
                "before_ref": auto_checkpoint.get("before_ref"),
            } if auto_checkpoint else None,
        },
        "changed_files": files,
        "context_preview": [tool_preview(tool) for tool in tools],
    }


def write_ndjson(handler: WasmAgentHandler, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8") + b"\n"
    handler.wfile.write(body)
    handler.wfile.flush()


def stream_embedded_agent_message(
    handler: WasmAgentHandler,
    body: dict[str, Any],
    *,
    user: dict[str, Any] | None = None,
) -> None:
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()

    events: "queue.Queue[dict[str, Any]]" = queue.Queue()
    started = time.monotonic()
    last_action_label = "Receive chat turn"

    def emit_action(action: dict[str, Any]) -> None:
        events.put({"type": "action", "action": action})

    def run_turn() -> None:
        try:
            result = embedded_agent_message(handler.server, body, user=user, action_callback=emit_action)
            events.put({"type": "final", "agent": result})
        except BrowserError as exc:
            events.put({"type": "error", "error": {"code": exc.code, "message": exc.message}})
        except Exception as exc:
            events.put({"type": "error", "error": {"code": "agent_error", "message": str(exc)}})

    worker = threading.Thread(target=run_turn, name="wasm-agent-chat-turn", daemon=True)
    worker.start()

    while True:
        try:
            payload = events.get(timeout=15)
        except queue.Empty:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            payload = {
                "type": "heartbeat",
                "phase": "Hermes bridge active",
                "message": f"Hermes is still working after {elapsed_ms // 1000}s. Latest step: {last_action_label}.",
                "elapsed_ms": elapsed_ms,
                "action": {
                    "id": "node_reply",
                    "topic": "run-hermes",
                    "kind": "model",
                    "label": "Hermes bridge active",
                    "status": "running",
                    "detail": f"{elapsed_ms // 1000}s elapsed / latest: {last_action_label}",
                    "meta": "bridge active",
                },
            }
        else:
            action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
            if action.get("label"):
                last_action_label = clipped(str(action.get("label") or ""), 80)
        try:
            write_ndjson(handler, payload)
        except (BrokenPipeError, ConnectionResetError):
            return
        if payload.get("type") in {"final", "error"}:
            return


def dev_hmr_files(server: WasmAgentServer) -> list[Path]:
    roots = [server.public_root, server.plugin_root / "server"]
    suffixes = {".html", ".css", ".js", ".webmanifest", ".py"}
    files: list[Path] = []
    for root in roots:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                files.append(path)
    return files


def dev_hmr_snapshot(server: WasmAgentServer) -> dict[str, float]:
    snapshot: dict[str, float] = {}
    for path in dev_hmr_files(server):
        try:
            relative = str(path.relative_to(server.plugin_root))
            snapshot[relative] = path.stat().st_mtime
        except OSError:
            continue
    return snapshot


def dev_hmr_revision(snapshot: dict[str, float]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def serve_dev_hmr_events(handler: WasmAgentHandler) -> None:
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()

    query = parse_qs(urlparse(handler.path).query)
    client_revision = str((query.get("client") or [""])[0])
    previous = dev_hmr_snapshot(handler.server)
    revision = dev_hmr_revision(previous)
    handler.wfile.write(b"event: ready\n")
    ready_payload = json.dumps({
        "ok": True,
        "module": "dev-hmr",
        "revision": revision,
        "client": client_revision,
    }, separators=(",", ":")).encode("utf-8")
    handler.wfile.write(b"data: " + ready_payload + b"\n\n")
    handler.wfile.flush()
    if not client_revision:
        legacy_payload = json.dumps({
            "changed": ["public/modules/hmr/dev-hmr.js"],
            "removed": [],
            "timestamp": int(time.time()),
            "revision": revision,
            "reason": "hmr_client_stale",
        }, separators=(",", ":")).encode("utf-8")
        try:
            handler.wfile.write(b"event: change\n")
            handler.wfile.write(b"data: " + legacy_payload + b"\n\n")
            handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    while True:
        time.sleep(0.6)
        current = dev_hmr_snapshot(handler.server)
        changed = sorted(path for path, mtime in current.items() if previous.get(path) != mtime)
        removed = sorted(path for path in previous if path not in current)
        if not changed and not removed:
            continue
        previous = current
        revision = dev_hmr_revision(current)
        payload = json.dumps({
            "changed": changed,
            "removed": removed,
            "timestamp": int(time.time()),
            "revision": revision,
        }, separators=(",", ":")).encode("utf-8")
        try:
            handler.wfile.write(b"event: change\n")
            handler.wfile.write(b"data: " + payload + b"\n\n")
            handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            break


def capture_browser(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    url = normalized_browser_url(body.get("url"))
    width, height = browser_dimensions(body)
    cdp_url = os.getenv("HERMES_WASM_AGENT_BROWSER_CDP_URL", "http://127.0.0.1:9233").strip()
    if cdp_url:
        try:
            return capture_browser_cdp(server, url, width, height, cdp_url.rstrip("/"))
        except BrowserError:
            raise
        except Exception:
            # Fall back to one-shot Chromium only when CDP is not reachable.
            if cdp_available(cdp_url.rstrip("/")):
                raise

    return capture_browser_cli(server, url, width, height)


def cdp_available(cdp_url: str) -> bool:
    try:
        with urlopen(f"{cdp_url}/json/version", timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def capture_browser_cdp(
    server: WasmAgentServer,
    url: str,
    width: int,
    height: int,
    cdp_url: str,
) -> dict[str, Any]:
    target: dict[str, Any] | None = None
    try:
        create_req = Request(f"{cdp_url}/json/new?{quote(url, safe='')}", method="PUT")
        with urlopen(create_req, timeout=3) as response:
            target = json.loads(response.read().decode("utf-8"))
        ws_url = str(target.get("webSocketDebuggerUrl") or "")
        if not ws_url:
            raise BrowserError("cdp_target_failed", "CDP target did not expose a websocket URL.")
        image = capture_cdp_screenshot(
            ws_url,
            width,
            height,
            server.browser_timeout_sec,
            navigate_url=url,
        )
    except BrowserError:
        raise
    except Exception as exc:
        raise BrowserError("cdp_capture_failed", f"CDP browser capture failed: {exc}") from exc

    image_bytes = base64.b64decode(image.encode("ascii"))
    session_id = uuid.uuid4().hex
    with server.browser_sessions_lock:
        server.browser_sessions[session_id] = {
            "session_id": session_id,
            "target_id": target.get("id") if target else "",
            "ws_url": ws_url,
            "cdp_url": cdp_url,
            "url": url,
            "width": width,
            "height": height,
            "created_at": time.time(),
            "last_access": time.time(),
        }
        prune_browser_sessions(server)
    return {
        "schema": "hermes.wasm_agent.browser_capture.v1",
        "session_id": session_id,
        "interactive": True,
        "url": url,
        "width": width,
        "height": height,
        "bytes": len(image_bytes),
        "captured_at": int(time.time()),
        "image": "data:image/png;base64," + image,
        "mode": "host_chromium_cdp_pixels",
        "iframe": False,
    }


def capture_browser_cli(server: WasmAgentServer, url: str, width: int, height: int) -> dict[str, Any]:
    browser_root = server.state_dir / "browser"
    capture_root = browser_root / "captures"
    profile_root = browser_root / "profile"
    capture_root.mkdir(parents=True, exist_ok=True)
    profile_root.mkdir(parents=True, exist_ok=True)
    capture_path = capture_root / f"{int(time.time())}-{uuid.uuid4().hex[:8]}.png"

    cmd = [
        chromium_command(),
        "--headless",
        "--no-sandbox",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--user-data-dir={profile_root}",
        f"--window-size={width},{height}",
        f"--screenshot={capture_path}",
        url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False,
            timeout=server.browser_timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise BrowserError(
            "browser_timeout",
            f"Chromium capture timed out after {server.browser_timeout_sec:.0f}s.",
            status=HTTPStatus.GATEWAY_TIMEOUT,
        ) from exc

    if proc.returncode != 0 or not capture_path.exists():
        stderr = (proc.stderr or proc.stdout or "Chromium capture failed.").strip()
        raise BrowserError(
            "browser_capture_failed",
            stderr[-900:],
            status=HTTPStatus.BAD_GATEWAY,
        )

    image_bytes = capture_path.read_bytes()
    image = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    return {
        "schema": "hermes.wasm_agent.browser_capture.v1",
        "session_id": "",
        "interactive": False,
        "url": url,
        "width": width,
        "height": height,
        "bytes": len(image_bytes),
        "captured_at": int(time.time()),
        "image": image,
        "mode": "chromium_screenshot_pixels",
        "iframe": False,
    }


def browser_session_ttl_sec() -> float:
    raw = os.getenv("HERMES_WASM_AGENT_BROWSER_SESSION_TTL_SEC")
    if raw in {None, ""}:
        return DEFAULT_BROWSER_SESSION_TTL_SEC
    return clamp_number(raw, 60, 24 * 60 * 60)


def prune_browser_sessions(server: WasmAgentServer, *, keep: int = 8) -> None:
    now = time.time()
    ttl_sec = browser_session_ttl_sec()
    for session_id, session in list(server.browser_sessions.items()):
        last_access = float(session.get("last_access") or session.get("created_at") or 0)
        if last_access and now - last_access > ttl_sec:
            server.browser_sessions.pop(session_id, None)
            close_cdp_target(str(session.get("cdp_url") or ""), str(session.get("target_id") or ""))

    sessions = sorted(
        server.browser_sessions.values(),
        key=lambda item: float(item.get("last_access") or item.get("created_at") or 0),
        reverse=True,
    )
    for session in sessions[keep:]:
        server.browser_sessions.pop(str(session.get("session_id")), None)
        close_cdp_target(str(session.get("cdp_url") or ""), str(session.get("target_id") or ""))


def close_cdp_target(cdp_url: str, target_id: str) -> None:
    if not cdp_url or not target_id:
        return
    try:
        with urlopen(f"{cdp_url}/json/close/{target_id}", timeout=2):
            pass
    except Exception:
        pass


def browser_input(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    session_id = str(body.get("session_id") or "").strip()
    if not session_id:
        raise BrowserError("missing_session", "A browser session_id is required.")
    with server.browser_sessions_lock:
        session = dict(server.browser_sessions.get(session_id) or {})
        if not session:
            raise BrowserError("browser_session_not_found", "Browser session was not found.", status=HTTPStatus.NOT_FOUND)
        session["last_access"] = time.time()
        server.browser_sessions[session_id] = session

    action = str(body.get("action") or "").strip().lower()
    width = int(session.get("width") or 1280)
    height = int(session.get("height") or 800)
    ws_url = str(session.get("ws_url") or "")
    url = str(session.get("url") or "")
    action_result = perform_browser_action(ws_url, action, body, width, height, server.browser_timeout_sec)
    image = action_result["image"]
    current_url = str(action_result.get("url") or "")
    if action == "navigate":
        url = current_url or normalized_browser_url(body.get("url"))
        session["url"] = url
        with server.browser_sessions_lock:
            server.browser_sessions[session_id] = session
    elif current_url:
        url = current_url
        session["url"] = url
        with server.browser_sessions_lock:
            server.browser_sessions[session_id] = session

    image_bytes = base64.b64decode(image.encode("ascii"))
    return {
        "schema": "hermes.wasm_agent.browser_capture.v1",
        "session_id": session_id,
        "interactive": True,
        "url": url,
        "width": width,
        "height": height,
        "bytes": len(image_bytes),
        "captured_at": int(time.time()),
        "image": "data:image/png;base64," + image,
        "mode": "host_chromium_cdp_interactive_pixels",
        "action": action,
        "iframe": False,
    }


def close_browser_session(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    session_id = str(body.get("session_id") or "").strip()
    if not session_id:
        raise BrowserError("missing_session", "A browser session_id is required.")
    with server.browser_sessions_lock:
        session = server.browser_sessions.pop(session_id, None)
    if not session:
        return {"session_id": session_id, "closed": False}
    close_cdp_target(str(session.get("cdp_url") or ""), str(session.get("target_id") or ""))
    return {"session_id": session_id, "closed": True}


def serve_browser_stream(handler: WasmAgentHandler) -> None:
    key = handler.headers.get("Sec-WebSocket-Key", "").strip()
    upgrade = handler.headers.get("Upgrade", "").lower()
    if upgrade != "websocket" or not key:
        handler.send_error(HTTPStatus.UPGRADE_REQUIRED, "WebSocket upgrade required")
        return

    accept = base64.b64encode(
        hashlib.sha1((key + WEBSOCKET_GUID).encode("ascii"), usedforsecurity=False).digest()
    ).decode("ascii")
    handler.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()
    handler.close_connection = True

    client_ws = BrowserClientWebSocket(handler)
    try:
        handle_browser_stream(handler.server, client_ws)
    finally:
        client_ws.close()


class BrowserClientWebSocket:
    def __init__(self, handler: WasmAgentHandler) -> None:
        self.sock = handler.connection
        self.reader = handler.rfile
        self.send_lock = threading.Lock()
        self.closed = False

    def send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_frame(0x1, data)

    def send_frame(self, opcode: int, payload: bytes = b"") -> None:
        if self.closed:
            return
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", length))
        with self.send_lock:
            self.sock.sendall(bytes(header) + payload)

    def recv_message(self, *, wait: float | None = None) -> tuple[int, bytes]:
        previous_timeout = self.sock.gettimeout()
        self.sock.settimeout(wait)
        try:
            while True:
                opcode, payload = self.recv_frame()
                if opcode == 0x8:
                    raise BrowserError("browser_ws_closed", "Browser websocket closed.")
                if opcode == 0x9:
                    self.send_frame(0xA, payload)
                    continue
                if opcode == 0xA:
                    continue
                if opcode in {0x1, 0x2, 0x0}:
                    return opcode, payload
        except socket.timeout as exc:
            raise BrowserError("browser_ws_timeout", "Timed out waiting for browser stream input.") from exc
        finally:
            self.sock.settimeout(previous_timeout)

    def recv_json(self, *, wait: float | None = None) -> dict[str, Any]:
        while True:
            opcode, payload = self.recv_message(wait=wait)
            if opcode in {0x1, 0x0}:
                return json.loads(payload.decode("utf-8"))

    def recv_frame(self) -> tuple[int, bytes]:
        first = self._recv_exact(2)
        opcode = first[0] & 0x0F
        masked = bool(first[1] & 0x80)
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def close(self) -> None:
        if self.closed:
            return
        try:
            self.send_frame(0x8)
        except Exception:
            pass
        self.closed = True

    def _recv_exact(self, length: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            chunk = self.reader.read(length - len(chunks))
            if not chunk:
                raise BrowserError("browser_ws_closed", "Browser websocket closed.")
            chunks.extend(chunk)
        return bytes(chunks)


def serve_shared_space_room_live(handler: WasmAgentHandler, user: dict[str, Any] | None) -> None:
    if not user:
        handler._json(
            HTTPStatus.UNAUTHORIZED,
            {"ok": False, "error": {"code": "auth_required", "message": "Account sign-in is required."}},
        )
        return
    query = parse_qs(urlparse(handler.path).query)
    shared_space_id = safe_state_id(str((query.get("shared_space_id") or query.get("shared_space") or [""])[0] or ""), "")
    if not shared_space_id:
        handler._json(
            HTTPStatus.BAD_REQUEST,
            {"ok": False, "error": {"code": "invalid_shared_space", "message": "shared_space_id is required."}},
        )
        return
    record = read_shared_space_record(handler.server, shared_space_id)
    if not record:
        handler._json(
            HTTPStatus.NOT_FOUND,
            {"ok": False, "error": {"code": "shared_space_not_found", "message": "That shared space was not found."}},
        )
        return
    if not user_can_access_shared_space(record, user):
        handler._json(
            HTTPStatus.FORBIDDEN,
            {"ok": False, "error": {"code": "shared_space_denied", "message": "You cannot access that shared space."}},
        )
        return
    key = handler.headers.get("Sec-WebSocket-Key", "").strip()
    upgrade = handler.headers.get("Upgrade", "").lower()
    if upgrade != "websocket" or not key:
        handler.send_error(HTTPStatus.UPGRADE_REQUIRED, "WebSocket upgrade required")
        return

    accept = base64.b64encode(
        hashlib.sha1((key + WEBSOCKET_GUID).encode("ascii"), usedforsecurity=False).digest()
    ).decode("ascii")
    handler.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()
    handler.close_connection = True

    client_ws = BrowserClientWebSocket(handler)
    shared_space_live_register(handler.server, shared_space_id, client_ws)
    try:
        client_ws.send_json({
            "type": "ready",
            "schema": "hermes.wasm_agent.shared_space.live.v1",
            "shared_space_id": shared_space_id,
            "user_id": user_id(user),
        })
        handle_shared_space_room_live(handler.server, client_ws, user, shared_space_id)
    finally:
        shared_space_live_unregister(handler.server, shared_space_id, client_ws)
        client_ws.close()


def shared_space_live_register(server: WasmAgentServer, shared_space_id: str, client_ws: BrowserClientWebSocket) -> None:
    with server.shared_space_live_clients_lock:
        server.shared_space_live_clients.setdefault(shared_space_id, set()).add(client_ws)


def shared_space_live_unregister(server: WasmAgentServer, shared_space_id: str, client_ws: BrowserClientWebSocket) -> None:
    with server.shared_space_live_clients_lock:
        clients = server.shared_space_live_clients.get(shared_space_id)
        if not clients:
            return
        clients.discard(client_ws)
        if not clients:
            server.shared_space_live_clients.pop(shared_space_id, None)


def shared_space_live_broadcast(
    server: WasmAgentServer,
    shared_space_id: str,
    event: dict[str, Any],
    *,
    source: BrowserClientWebSocket | None = None,
) -> None:
    sid = safe_state_id(shared_space_id, "")
    if not sid or not event:
        return
    payload = {"type": "event", "shared_space_id": sid, "event": event}
    stale: list[BrowserClientWebSocket] = []
    with server.shared_space_live_clients_lock:
        targets = [
            client
            for client in server.shared_space_live_clients.get(sid, set())
            if client is not source
        ]
    for client in targets:
        try:
            client.send_json(payload)
        except Exception:
            stale.append(client)
    for client in stale:
        shared_space_live_unregister(server, sid, client)


def shared_space_pointer_hash(value: Any) -> int:
    result = 0x811C9DC5
    for byte in str(value or "").encode("utf-8"):
        result ^= byte
        result = (result * 0x01000193) & 0xFFFFFFFF
    return result


def shared_space_pointer_user_number(user: dict[str, Any] | None) -> int:
    uid = user_id(user)
    try:
        number = int(uid)
        if 0 <= number <= 0xFFFFFFFF:
            return number
    except (TypeError, ValueError):
        pass
    return shared_space_pointer_hash(uid)


def shared_space_pointer_binary_allowed(payload: bytes, user: dict[str, Any] | None) -> bool:
    if len(payload) < SHARED_SPACE_POINTER_BINARY_HEADER_BYTES:
        return False
    if payload[:4] != SHARED_SPACE_POINTER_BINARY_MAGIC:
        return False
    version = payload[4]
    packet_type = payload[5]
    count = payload[7]
    if version != 1 or packet_type != 1 or count > SHARED_SPACE_POINTER_BINARY_MAX_SAMPLES:
        return False
    expected_length = SHARED_SPACE_POINTER_BINARY_HEADER_BYTES + count * SHARED_SPACE_POINTER_BINARY_SAMPLE_BYTES
    if len(payload) != expected_length:
        return False
    try:
        packet_user = struct.unpack_from("<I", payload, 8)[0]
    except struct.error:
        return False
    return packet_user == shared_space_pointer_user_number(user)


def shared_space_live_broadcast_binary(
    server: WasmAgentServer,
    shared_space_id: str,
    payload: bytes,
    *,
    source: BrowserClientWebSocket | None = None,
) -> None:
    sid = safe_state_id(shared_space_id, "")
    if not sid or not payload:
        return
    stale: list[BrowserClientWebSocket] = []
    with server.shared_space_live_clients_lock:
        targets = [
            client
            for client in server.shared_space_live_clients.get(sid, set())
            if client is not source
        ]
    for client in targets:
        try:
            client.send_frame(0x2, payload)
        except Exception:
            stale.append(client)
    for client in stale:
        shared_space_live_unregister(server, sid, client)


def shared_space_live_error(
    client_ws: BrowserClientWebSocket,
    request_id: str,
    code: str,
    message: str,
) -> None:
    client_ws.send_json({
        "type": "ack",
        "ok": False,
        "request_id": request_id,
        "error": {"code": code, "message": message},
    })


def handle_shared_space_room_live(
    server: WasmAgentServer,
    client_ws: BrowserClientWebSocket,
    user: dict[str, Any],
    shared_space_id: str,
) -> None:
    while True:
        try:
            if hasattr(client_ws, "recv_message"):
                opcode, payload = client_ws.recv_message(wait=25)
            else:
                message = client_ws.recv_json(wait=25)
                opcode = 0x1
                payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        except BrowserError as exc:
            if exc.code == "browser_ws_timeout":
                client_ws.send_json({"type": "ping", "ts": int(time.time() * 1000)})
                continue
            if exc.code == "browser_ws_closed":
                break
            raise
        if opcode == 0x2:
            record = read_shared_space_record(server, shared_space_id)
            if record and user_can_access_shared_space(record, user) and shared_space_pointer_binary_allowed(payload, user):
                shared_space_live_broadcast_binary(server, shared_space_id, payload, source=client_ws)
            continue
        if opcode not in {0x1, 0x0}:
            continue
        try:
            message = json.loads(payload.decode("utf-8"))
        except Exception:
            shared_space_live_error(client_ws, "", "invalid_shared_space_live_json", "Live shared-space message was not valid JSON.")
            continue
        if not isinstance(message, dict):
            continue
        message_type = str(message.get("type") or "").strip()
        request_id = safe_state_id(str(message.get("request_id") or ""), "")
        if message_type in {"pong", "hello"}:
            continue
        if message_type != "event":
            shared_space_live_error(client_ws, request_id, "unsupported_shared_space_live_message", "Unsupported shared-space live message.")
            continue
        body = message.get("body") if isinstance(message.get("body"), dict) else {}
        body_sid = safe_state_id(str(body.get("shared_space_id") or body.get("shared_space") or shared_space_id), "")
        if body_sid != shared_space_id:
            shared_space_live_error(client_ws, request_id, "shared_space_mismatch", "Live shared-space events must target the connected room.")
            continue
        record = read_shared_space_record(server, shared_space_id)
        if not record or not user_can_access_shared_space(record, user):
            shared_space_live_error(client_ws, request_id, "shared_space_denied", "You cannot access that shared space.")
            continue
        try:
            live_only = body.get("live_only") is True or str(body.get("live_only") or "").strip().lower() in {"1", "true", "yes"}
            event_kind = safe_state_id(str(body.get("kind") or body.get("event_kind") or "space-event"), "space-event")
            if live_only and event_kind != "space-pointer":
                shared_space_live_error(client_ws, request_id, "unsupported_live_only_kind", "Only shared-space pointer events can be live-only.")
                continue
            event = build_shared_space_room_event(user, body) if live_only else append_shared_space_room_event(server, user, shared_space_id, body)
            client_ws.send_json({"type": "ack", "ok": True, "request_id": request_id, "event": event})
            shared_space_live_broadcast(server, shared_space_id, event, source=client_ws)
        except BrowserError as exc:
            shared_space_live_error(client_ws, request_id, exc.code, exc.message)
        except Exception as exc:
            shared_space_live_error(client_ws, request_id, "shared_space_live_error", str(exc))


def serve_remote_control_live(handler: WasmAgentHandler, user: dict[str, Any] | None) -> None:
    if not user:
        handler._json(
            HTTPStatus.UNAUTHORIZED,
            {"ok": False, "error": {"code": "auth_required", "message": "Account sign-in is required."}},
        )
        return
    key = handler.headers.get("Sec-WebSocket-Key", "").strip()
    upgrade = handler.headers.get("Upgrade", "").lower()
    if upgrade != "websocket" or not key:
        handler.send_error(HTTPStatus.UPGRADE_REQUIRED, "WebSocket upgrade required")
        return

    accept = base64.b64encode(
        hashlib.sha1((key + WEBSOCKET_GUID).encode("ascii"), usedforsecurity=False).digest()
    ).decode("ascii")
    handler.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()
    handler.close_connection = True

    client_ws = BrowserClientWebSocket(handler)
    uid = user_id(user)
    remote_control_live_register(handler.server, uid, client_ws)
    try:
        client_ws.send_json({
            "type": "ready",
            "schema": "hermes.wasm_agent.remote_control.live.v1",
            "user_id": uid,
        })
        handle_remote_control_live(handler.server, client_ws, user)
    finally:
        remote_control_live_unregister(handler.server, uid, client_ws)
        client_ws.close()


def remote_control_live_register(server: WasmAgentServer, uid: str, client_ws: BrowserClientWebSocket) -> None:
    with server.remote_control_live_clients_lock:
        server.remote_control_live_clients.setdefault(uid, set()).add(client_ws)


def remote_control_live_unregister(server: WasmAgentServer, uid: str, client_ws: BrowserClientWebSocket) -> None:
    with server.remote_control_live_clients_lock:
        clients = server.remote_control_live_clients.get(uid)
        if not clients:
            return
        clients.discard(client_ws)
        if not clients:
            server.remote_control_live_clients.pop(uid, None)


def remote_control_live_conversation_user_ids(conversation_id: str) -> list[str]:
    conv_id = safe_state_id(conversation_id, "")
    if not conv_id:
        return []
    with auth_connect() as conn:
        rows = conn.execute(
            """
            SELECT user_id FROM conversation_member_tb
             WHERE conversation_id = ?
             ORDER BY user_id ASC
            """,
            (conv_id,),
        ).fetchall()
    return [str(row["user_id"]) for row in rows]


def remote_control_live_broadcast(
    server: WasmAgentServer,
    event: dict[str, Any],
    *,
    source: BrowserClientWebSocket | None = None,
) -> None:
    if not event or not remote_control_kind_allowed(event.get("kind")):
        return
    user_ids = remote_control_live_conversation_user_ids(str(event.get("conversation_id") or ""))
    author_id = str(event.get("author_user_id") or "")
    if author_id and author_id not in user_ids:
        user_ids.append(author_id)
    payload = {"type": "event", "event": event}
    stale: list[tuple[str, BrowserClientWebSocket]] = []
    with server.remote_control_live_clients_lock:
        targets = [
            (uid, client)
            for uid in user_ids
            for client in server.remote_control_live_clients.get(uid, set())
            if client is not source
        ]
    for uid, client in targets:
        try:
            client.send_json(payload)
        except Exception:
            stale.append((uid, client))
    for uid, client in stale:
        remote_control_live_unregister(server, uid, client)


def remote_control_live_broadcast_async(
    server: WasmAgentServer,
    event: dict[str, Any],
    *,
    source: BrowserClientWebSocket | None = None,
) -> None:
    if not event or not remote_control_kind_allowed(event.get("kind")):
        return
    worker = threading.Thread(
        target=remote_control_live_broadcast,
        args=(server, event),
        kwargs={"source": source},
        name="wasm-agent-remote-control-live-broadcast",
        daemon=True,
    )
    worker.start()


def remote_control_live_ephemeral_event(
    server: WasmAgentServer,
    user: dict[str, Any] | None,
    body: dict[str, Any],
) -> dict[str, Any]:
    uid = user_id(user)
    kind = sync_event_kind(body.get("kind"))
    if kind != "remote-control-frame":
        raise BrowserError("unsupported_live_frame_kind", "Only remote-control viewport frames can use the latest-frame live channel.")
    payload = normalize_sync_event_payload(user, kind, body.get("payload"))
    # Reuse the durable payload guard so live frames cannot exceed the same relay budget.
    sync_event_payload(payload, kind)
    with auth_connect() as conn:
        conversation_id = ensure_sync_conversation(server, conn, user, body)
        ensure_direct_conversation_send_allowed(conn, conversation_id, user, kind)
    now = int(time.time())
    client_event_id = safe_state_id(str(body.get("client_event_id") or ""), "") or f"client-{next_snowflake_id():x}"
    return {
        "schema": SYNC_EVENT_SCHEMA,
        "id": str(next_snowflake_id()),
        "client_event_id": client_event_id,
        "conversation_id": conversation_id,
        "space_id": safe_state_id(str(body.get("space_id") or body.get("space") or ""), ""),
        "shared_space_id": safe_state_id(str(body.get("shared_space_id") or body.get("shared_space") or ""), ""),
        "author_user_id": uid,
        "kind": kind,
        "payload": payload,
        "created_at": now,
        "updated_at": now,
        "ephemeral": True,
    }


def remote_control_kind_allowed(kind: Any) -> bool:
    return sync_event_kind(kind) in REMOTE_CONTROL_EVENT_KINDS


def remote_control_live_error(
    client_ws: BrowserClientWebSocket,
    request_id: str,
    code: str,
    message: str,
) -> None:
    client_ws.send_json({
        "type": "ack",
        "ok": False,
        "request_id": request_id,
        "error": {"code": code, "message": message},
    })


def handle_remote_control_live(
    server: WasmAgentServer,
    client_ws: BrowserClientWebSocket,
    user: dict[str, Any],
) -> None:
    while True:
        try:
            message = client_ws.recv_json(wait=25)
        except BrowserError as exc:
            if exc.code == "browser_ws_timeout":
                client_ws.send_json({"type": "ping", "ts": int(time.time() * 1000)})
                continue
            if exc.code == "browser_ws_closed":
                break
            raise
        if not isinstance(message, dict):
            continue
        message_type = str(message.get("type") or "").strip()
        request_id = safe_state_id(str(message.get("request_id") or ""), "")
        if message_type in {"pong", "hello"}:
            continue
        if message_type == "frame":
            body = message.get("body") if isinstance(message.get("body"), dict) else {}
            try:
                event = remote_control_live_ephemeral_event(server, user, body)
                if request_id:
                    client_ws.send_json({
                        "type": "ack",
                        "ok": True,
                        "request_id": request_id,
                        "event": {
                            "id": event["id"],
                            "conversation_id": event["conversation_id"],
                            "kind": event["kind"],
                            "ephemeral": True,
                        },
                    })
                remote_control_live_broadcast_async(server, event, source=client_ws)
            except BrowserError as exc:
                remote_control_live_error(client_ws, request_id, exc.code, exc.message)
            except Exception as exc:
                remote_control_live_error(client_ws, request_id, "remote_control_live_frame_error", str(exc))
            continue
        if message_type != "append":
            remote_control_live_error(client_ws, request_id, "unsupported_live_message", "Unsupported remote-control live message.")
            continue
        body = message.get("body") if isinstance(message.get("body"), dict) else {}
        kind = sync_event_kind(body.get("kind"))
        if kind not in REMOTE_CONTROL_EVENT_KINDS:
            remote_control_live_error(client_ws, request_id, "unsupported_live_kind", "Only remote-control events can use the live channel.")
            continue
        try:
            result = append_sync_event(server, user, body)
            event = result.get("event") if isinstance(result.get("event"), dict) else {}
            client_ws.send_json({"type": "ack", "ok": True, "request_id": request_id, "event": event})
            remote_control_live_broadcast(server, event, source=client_ws)
        except BrowserError as exc:
            remote_control_live_error(client_ws, request_id, exc.code, exc.message)
        except Exception as exc:
            remote_control_live_error(client_ws, request_id, "remote_control_live_error", str(exc))


class CdpWebSocket:
    def __init__(self, ws_url: str, timeout: float) -> None:
        parsed = urlparse(ws_url)
        if parsed.scheme != "ws" or not parsed.hostname:
            raise BrowserError("cdp_ws_unsupported", "Only ws:// CDP websocket URLs are supported.")
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        self.sock = socket.create_connection((parsed.hostname, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = self._recv_until(b"\r\n\r\n")
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise BrowserError("cdp_ws_handshake_failed", "CDP websocket handshake failed.")
        accept = base64.b64encode(
            hashlib.sha1(
                (key + WEBSOCKET_GUID).encode("ascii"),
                usedforsecurity=False,
            ).digest()
        ).decode("ascii")
        if f"sec-websocket-accept: {accept}".encode("ascii").lower() not in response.lower():
            raise BrowserError("cdp_ws_handshake_failed", "CDP websocket accept key did not match.")

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

    def send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = secrets.token_bytes(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_json(self) -> dict[str, Any]:
        while True:
            message = self._recv_frame()
            if message is None:
                continue
            return json.loads(message.decode("utf-8"))

    def _recv_frame(self) -> bytes | None:
        first = self._recv_exact(2)
        opcode = first[0] & 0x0F
        masked = bool(first[1] & 0x80)
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        data = self._recv_exact(length) if length else b""
        if masked:
            data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        if opcode == 0x8:
            raise BrowserError("cdp_ws_closed", "CDP websocket closed.")
        if opcode == 0x9:
            self._send_pong(data)
            return None
        if opcode not in {0x1, 0x0}:
            return None
        return data

    def _send_pong(self, payload: bytes) -> None:
        header = bytearray([0x8A])
        length = len(payload)
        header.append(0x80 | length)
        mask = secrets.token_bytes(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv_exact(self, length: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            chunk = self.sock.recv(length - len(chunks))
            if not chunk:
                raise BrowserError("cdp_ws_closed", "CDP websocket closed.")
            chunks.extend(chunk)
        return bytes(chunks)

    def _recv_until(self, marker: bytes) -> bytes:
        chunks = bytearray()
        while marker not in chunks:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise BrowserError("cdp_ws_closed", "CDP websocket closed.")
            chunks.extend(chunk)
        return bytes(chunks)


class CdpClient:
    def __init__(self, ws_url: str, timeout: float) -> None:
        self.ws = CdpWebSocket(ws_url, timeout)
        self.timeout = timeout
        self.next_id = 0

    def close(self) -> None:
        self.ws.close()

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        wait: float | None = None,
    ) -> dict[str, Any]:
        self.next_id += 1
        message_id = self.next_id
        timeout = wait or self.timeout
        self.ws.sock.settimeout(timeout)
        self.ws.send_json({"id": message_id, "method": method, "params": params or {}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            payload = self.ws.recv_json()
            if payload.get("id") != message_id:
                continue
            if "error" in payload:
                raise BrowserError("cdp_command_failed", json.dumps(payload["error"])[:700])
            return payload.get("result", {})
        raise BrowserError("cdp_timeout", f"Timed out waiting for {method}.", status=HTTPStatus.GATEWAY_TIMEOUT)

    def wait_for_load(self, timeout: float) -> None:
        deadline = time.time() + timeout
        self.ws.sock.settimeout(0.75)
        while time.time() < deadline:
            try:
                payload = self.ws.recv_json()
            except socket.timeout:
                continue
            if payload.get("method") == "Page.loadEventFired":
                break
        self.ws.sock.settimeout(self.timeout)


class CdpStreamClient:
    def __init__(
        self,
        ws_url: str,
        timeout: float,
        browser_ws: BrowserClientWebSocket,
        *,
        width: int,
        height: int,
        url: str,
        stream_id: str,
    ) -> None:
        self.ws = CdpWebSocket(ws_url, timeout)
        self.ws.sock.settimeout(0.5)
        self.timeout = timeout
        self.browser_ws = browser_ws
        self.width = width
        self.height = height
        self.url = url
        self.stream_id = stream_id
        self.next_id = 0
        self.frame_count = 0
        self.last_browser_frame_at = 0.0
        self.stream_fps = browser_stream_fps()
        self.pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self.pending_lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.load_events: queue.Queue[bool] = queue.Queue(maxsize=4)
        self.reader_thread = threading.Thread(target=self._read_loop, name=f"browser-stream-{stream_id}", daemon=True)

    def start(self) -> None:
        self.reader_thread.start()

    def close(self) -> None:
        self.stop_event.set()
        try:
            self.ws.close()
        except Exception:
            pass

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        wait: float | None = None,
    ) -> dict[str, Any]:
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self.send_lock:
            self.next_id += 1
            message_id = self.next_id
            with self.pending_lock:
                self.pending[message_id] = response_queue
            self.ws.send_json({"id": message_id, "method": method, "params": params or {}})
        timeout = wait or self.timeout
        try:
            payload = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            with self.pending_lock:
                self.pending.pop(message_id, None)
            raise BrowserError("cdp_timeout", f"Timed out waiting for {method}.", status=HTTPStatus.GATEWAY_TIMEOUT) from exc
        if "error" in payload:
            raise BrowserError("cdp_command_failed", json.dumps(payload["error"])[:700])
        return payload.get("result", {})

    def send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> int:
        with self.send_lock:
            self.next_id += 1
            message_id = self.next_id
            self.ws.send_json({"id": message_id, "method": method, "params": params or {}})
        return message_id

    def wait_for_load(self, timeout: float) -> None:
        try:
            self.load_events.get(timeout=timeout)
        except queue.Empty:
            pass

    def send_browser(self, payload: dict[str, Any]) -> None:
        if self.stop_event.is_set():
            return
        try:
            self.browser_ws.send_json(payload)
        except Exception:
            self.stop_event.set()

    def _read_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                payload = self.ws.recv_json()
            except socket.timeout:
                continue
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.send_browser({"type": "error", "code": "cdp_stream_closed", "message": str(exc)})
                self.stop_event.set()
                break

            message_id = payload.get("id")
            if message_id is not None:
                with self.pending_lock:
                    response_queue = self.pending.pop(int(message_id), None)
                if response_queue is not None:
                    response_queue.put(payload)
                continue

            method = str(payload.get("method") or "")
            params = payload.get("params") or {}
            if method == "Page.screencastFrame":
                self._handle_screencast_frame(params)
            elif method == "Page.loadEventFired":
                try:
                    self.load_events.put_nowait(True)
                except queue.Full:
                    pass
            elif method == "Page.frameNavigated":
                frame = params.get("frame") or {}
                if not frame.get("parentId"):
                    url = str(frame.get("url") or "")
                    if url:
                        self.url = url
                        self.send_browser({"type": "state", "stream_id": self.stream_id, "url": url})

    def _handle_screencast_frame(self, params: dict[str, Any]) -> None:
        data = str(params.get("data") or "")
        if not data:
            return
        metadata = params.get("metadata") or {}
        session_id = params.get("sessionId")
        if session_id is not None:
            self.send_command("Page.screencastFrameAck", {"sessionId": session_id})
        now = time.monotonic()
        min_interval = 1.0 / max(1.0, self.stream_fps)
        if now - self.last_browser_frame_at < min_interval:
            return
        self.last_browser_frame_at = now
        self.frame_count += 1
        self.send_browser({
            "type": "frame",
            "stream_id": self.stream_id,
            "url": self.url,
            "width": self.width,
            "height": self.height,
            "image": "data:image/jpeg;base64," + data,
            "frame": self.frame_count,
            "timestamp": metadata.get("timestamp"),
            "mode": "host_chromium_cdp_screencast",
        })

    def send_snapshot_frame(self) -> None:
        result = self.call("Page.captureScreenshot", {
            "format": "jpeg",
            "quality": browser_stream_quality(),
            "fromSurface": True,
            "captureBeyondViewport": False,
        }, wait=min(self.timeout, 6))
        data = str(result.get("data") or "")
        if not data:
            return
        self.frame_count += 1
        self.last_browser_frame_at = time.monotonic()
        self.send_browser({
            "type": "frame",
            "stream_id": self.stream_id,
            "url": self.url,
            "width": self.width,
            "height": self.height,
            "image": "data:image/jpeg;base64," + data,
            "frame": self.frame_count,
            "timestamp": time.time(),
            "mode": "host_chromium_cdp_snapshot",
        })


def setup_cdp_page(client: CdpClient, width: int, height: int) -> None:
    client.call("Page.enable")
    client.call("Runtime.enable")
    set_cdp_viewport(client, width, height)


def set_cdp_viewport(client: CdpClient, width: int, height: int) -> None:
    client.call("Emulation.setDeviceMetricsOverride", {
        "width": width,
        "height": height,
        "deviceScaleFactor": 1,
        "mobile": False,
    })


def start_cdp_screencast(client: CdpStreamClient, width: int, height: int) -> None:
    client.call("Page.startScreencast", {
        "format": "jpeg",
        "quality": browser_stream_quality(),
        "maxWidth": width,
        "maxHeight": height,
        "everyNthFrame": browser_stream_every_nth_frame(),
    })


def browser_stream_fps() -> float:
    raw = os.getenv("HERMES_WASM_AGENT_BROWSER_STREAM_FPS")
    if raw in {None, ""}:
        return DEFAULT_BROWSER_STREAM_FPS
    return clamp_number(raw, 1, 12)


def browser_stream_quality() -> int:
    raw = os.getenv("HERMES_WASM_AGENT_BROWSER_STREAM_QUALITY")
    if raw in {None, ""}:
        return DEFAULT_BROWSER_STREAM_QUALITY
    return int(clamp_number(raw, 35, 85))


def browser_stream_every_nth_frame() -> int:
    raw = os.getenv("HERMES_WASM_AGENT_BROWSER_STREAM_EVERY_NTH_FRAME")
    if raw in {None, ""}:
        return DEFAULT_BROWSER_STREAM_EVERY_NTH_FRAME
    return int(clamp_number(raw, 1, 12))


def cdp_screenshot(client: CdpClient) -> str:
    result = client.call("Page.captureScreenshot", {
        "format": "png",
        "fromSurface": True,
        "captureBeyondViewport": False,
    })
    image = str(result.get("data") or "")
    if not image:
        raise BrowserError("cdp_screenshot_empty", "CDP returned an empty screenshot.")
    return image


def capture_cdp_screenshot(
    ws_url: str,
    width: int,
    height: int,
    timeout: float,
    *,
    navigate_url: str | None = None,
) -> dict[str, str]:
    client = CdpClient(ws_url, timeout)
    try:
        setup_cdp_page(client, width, height)
        if navigate_url:
            client.call("Page.navigate", {"url": navigate_url}, wait=min(timeout, 6))
            client.wait_for_load(min(timeout, 8))
        return cdp_screenshot(client)
    finally:
        client.close()


def perform_browser_action(
    ws_url: str,
    action: str,
    body: dict[str, Any],
    width: int,
    height: int,
    timeout: float,
) -> str:
    if action not in {"click", "type", "key", "scroll", "navigate", "screenshot", "back", "forward", "reload"}:
        raise BrowserError("unsupported_browser_action", "Unsupported browser action.")
    client = CdpClient(ws_url, timeout)
    try:
        setup_cdp_page(client, width, height)
        if action == "click":
            x = clamp_number(body.get("x"), 0, width)
            y = clamp_number(body.get("y"), 0, height)
            client.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none"})
            client.call("Input.dispatchMouseEvent", {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
            })
            client.call("Input.dispatchMouseEvent", {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
            })
            time.sleep(0.15)
        elif action == "type":
            text = str(body.get("text") or "")
            if text:
                client.call("Input.insertText", {"text": text})
        elif action == "key":
            key = str(body.get("key") or "")
            dispatch_key(client, key)
            if key == "Enter":
                client.wait_for_load(min(timeout, 4))
            else:
                time.sleep(0.2)
        elif action == "scroll":
            x = clamp_number(body.get("x"), 0, width)
            y = clamp_number(body.get("y"), 0, height)
            delta_x = float(body.get("delta_x") or 0)
            delta_y = float(body.get("delta_y") or 0)
            client.call("Input.dispatchMouseEvent", {
                "type": "mouseWheel",
                "x": x,
                "y": y,
                "deltaX": delta_x,
                "deltaY": delta_y,
            })
            time.sleep(0.15)
        elif action == "navigate":
            url = normalized_browser_url(body.get("url"))
            client.call("Page.navigate", {"url": url}, wait=min(timeout, 6))
            client.wait_for_load(min(timeout, 8))
        elif action in {"back", "forward"}:
            navigate_history(client, direction=action, timeout=timeout)
        elif action == "reload":
            client.call("Page.reload", {"ignoreCache": False}, wait=min(timeout, 6))
            client.wait_for_load(min(timeout, 8))
        return {"image": cdp_screenshot(client), "url": current_cdp_url(client)}
    finally:
        client.close()


def clamp_number(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))


def dispatch_key(client: CdpClient, key: str) -> None:
    key_map = {
        "Enter": ("Enter", "Enter", 13),
        "Backspace": ("Backspace", "Backspace", 8),
        "Tab": ("Tab", "Tab", 9),
        "Escape": ("Escape", "Escape", 27),
        "ArrowLeft": ("ArrowLeft", "ArrowLeft", 37),
        "ArrowUp": ("ArrowUp", "ArrowUp", 38),
        "ArrowRight": ("ArrowRight", "ArrowRight", 39),
        "ArrowDown": ("ArrowDown", "ArrowDown", 40),
    }
    normalized = key_map.get(key)
    if not normalized and len(key) == 1:
        client.call("Input.insertText", {"text": key})
        return
    if not normalized:
        return
    key_name, code, vk = normalized
    payload = {
        "key": key_name,
        "code": code,
        "windowsVirtualKeyCode": vk,
        "nativeVirtualKeyCode": vk,
    }
    client.call("Input.dispatchKeyEvent", {"type": "keyDown", **payload})
    client.call("Input.dispatchKeyEvent", {"type": "keyUp", **payload})


def navigate_history(client: CdpClient, *, direction: str, timeout: float) -> None:
    history = client.call("Page.getNavigationHistory", wait=3)
    entries = history.get("entries") or []
    index = int(history.get("currentIndex") or 0)
    target_index = index - 1 if direction == "back" else index + 1
    if target_index < 0 or target_index >= len(entries):
        return
    entry_id = entries[target_index].get("id")
    if entry_id is None:
        return
    client.call("Page.navigateToHistoryEntry", {"entryId": entry_id}, wait=min(timeout, 6))
    client.wait_for_load(min(timeout, 8))


def current_cdp_url(client: CdpClient) -> str:
    try:
        result = client.call("Runtime.evaluate", {
            "expression": "location.href",
            "returnByValue": True,
        }, wait=2)
        return str(result.get("result", {}).get("value") or "")
    except Exception:
        return ""


def create_cdp_target(cdp_url: str, initial_url: str = "about:blank") -> dict[str, Any]:
    create_req = Request(f"{cdp_url}/json/new?{quote(initial_url, safe='')}", method="PUT")
    with urlopen(create_req, timeout=3) as response:
        target = json.loads(response.read().decode("utf-8"))
    ws_url = str(target.get("webSocketDebuggerUrl") or "")
    if not ws_url:
        raise BrowserError("cdp_target_failed", "CDP target did not expose a websocket URL.")
    return target


def handle_browser_stream(server: WasmAgentServer, browser_ws: BrowserClientWebSocket) -> None:
    stream: CdpStreamClient | None = None
    target: dict[str, Any] | None = None
    cdp_url = os.getenv("HERMES_WASM_AGENT_BROWSER_CDP_URL", "http://127.0.0.1:9233").strip().rstrip("/")
    try:
        hello = browser_ws.recv_json(wait=8)
        if str(hello.get("type") or "").lower() != "open":
            raise BrowserError("browser_stream_expected_open", "First browser stream message must be type=open.")
        url = normalized_browser_url(hello.get("url"))
        width, height = browser_dimensions(hello)
        if not cdp_url:
            raise BrowserError("cdp_stream_unavailable", "Browser streaming requires HERMES_WASM_AGENT_BROWSER_CDP_URL.")
        if not cdp_available(cdp_url):
            raise BrowserError("cdp_stream_unavailable", f"CDP is not reachable at {cdp_url}.")

        target = create_cdp_target(cdp_url)
        stream_id = uuid.uuid4().hex
        stream = CdpStreamClient(
            str(target["webSocketDebuggerUrl"]),
            server.browser_timeout_sec,
            browser_ws,
            width=width,
            height=height,
            url=url,
            stream_id=stream_id,
        )
        stream.start()
        setup_cdp_page(stream, width, height)
        start_cdp_screencast(stream, width, height)
        browser_ws.send_json({
            "type": "ready",
            "stream_id": stream_id,
            "url": url,
            "width": width,
            "height": height,
            "mode": "host_chromium_cdp_screencast",
            "iframe": False,
        })
        stream.call("Page.navigate", {"url": url}, wait=min(server.browser_timeout_sec, 6))
        stream.wait_for_load(min(server.browser_timeout_sec, 6))
        stream.send_snapshot_frame()

        while not stream.stop_event.is_set():
            try:
                message = browser_ws.recv_json()
            except BrowserError as exc:
                if exc.code == "browser_ws_closed":
                    break
                raise
            perform_browser_stream_action(stream, message, server.browser_timeout_sec)
    except BrowserError as exc:
        try:
            browser_ws.send_json({"type": "error", "code": exc.code, "message": exc.message})
        except Exception:
            pass
    except Exception as exc:
        try:
            browser_ws.send_json({"type": "error", "code": "browser_stream_error", "message": str(exc)})
        except Exception:
            pass
    finally:
        if stream is not None:
            try:
                stream.call("Page.stopScreencast", wait=1)
            except Exception:
                pass
            stream.close()
        if target is not None:
            close_cdp_target(cdp_url, str(target.get("id") or ""))


def perform_browser_stream_action(client: CdpStreamClient, body: dict[str, Any], timeout: float) -> None:
    message_type = str(body.get("type") or "").strip().lower()
    action = str(body.get("action") or message_type).strip().lower()
    if action not in {"click", "type", "key", "scroll", "navigate", "resize", "back", "forward", "reload", "ping"}:
        raise BrowserError("unsupported_browser_stream_action", "Unsupported browser stream action.")
    if action == "ping":
        client.send_browser({"type": "pong", "stream_id": client.stream_id, "url": client.url})
        return
    if action == "click":
        x = clamp_number(body.get("x"), 0, client.width)
        y = clamp_number(body.get("y"), 0, client.height)
        client.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none"}, wait=2)
        client.call("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        }, wait=2)
        client.call("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        }, wait=2)
    elif action == "type":
        text = str(body.get("text") or "")
        if text:
            client.call("Input.insertText", {"text": text}, wait=2)
    elif action == "key":
        dispatch_key(client, str(body.get("key") or ""))
    elif action == "scroll":
        x = clamp_number(body.get("x"), 0, client.width)
        y = clamp_number(body.get("y"), 0, client.height)
        client.call("Input.dispatchMouseEvent", {
            "type": "mouseWheel",
            "x": x,
            "y": y,
            "deltaX": float(body.get("delta_x") or 0),
            "deltaY": float(body.get("delta_y") or 0),
        }, wait=2)
    elif action == "navigate":
        url = normalized_browser_url(body.get("url"))
        client.url = url
        client.send_browser({"type": "state", "stream_id": client.stream_id, "url": url, "status": "navigating"})
        try:
            client.call("Page.stopScreencast", wait=1)
        except Exception:
            pass
        client.call("Page.navigate", {"url": url}, wait=min(timeout, 6))
        client.wait_for_load(min(timeout, 6))
        start_cdp_screencast(client, client.width, client.height)
        client.send_snapshot_frame()
    elif action in {"back", "forward"}:
        navigate_history(client, direction=action, timeout=timeout)
    elif action == "reload":
        client.call("Page.reload", {"ignoreCache": False}, wait=min(timeout, 6))
    elif action == "resize":
        width, height = browser_dimensions(body)
        client.width = width
        client.height = height
        try:
            client.call("Page.stopScreencast", wait=1)
        except Exception:
            pass
        set_cdp_viewport(client, width, height)
        start_cdp_screencast(client, width, height)
        client.send_snapshot_frame()

    should_sync_url = action in {"navigate", "back", "forward", "reload"} or (
        action == "key" and str(body.get("key") or "") == "Enter"
    )
    if should_sync_url:
        url = current_cdp_url(client)
        if url:
            client.url = url
            client.send_browser({"type": "state", "stream_id": client.stream_id, "url": url})
    client.send_browser({"type": "ack", "stream_id": client.stream_id, "action": action, "url": client.url})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the wasm-agent shadow PWA")
    parser.add_argument("--host", default=os.getenv("HERMES_WASM_AGENT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("HERMES_WASM_AGENT_PORT", "8877")))
    parser.add_argument(
        "--bridge-url",
        default=os.getenv("HERMES_WASM_AGENT_BRIDGE_URL", "http://127.0.0.1:8790"),
        help="Hermes bridge URL exposed to the PWA",
    )
    parser.add_argument(
        "--browser-timeout-sec",
        type=float,
        default=float(os.getenv("HERMES_WASM_AGENT_BROWSER_TIMEOUT_SEC", "20")),
        help="Maximum Chromium browser capture or stream command time",
    )
    return parser


def wasm_agent_startup_banner(*, host: str, port: int, state_dir: Path, bridge_url: str) -> str:
    mode = wasm_agent_deployment_mode()
    cloud_root = cloud_state_root()
    private_state = "cloud-private" if mode == DEPLOYMENT_MODE_CLOUD else "local-private"
    if mode == DEPLOYMENT_MODE_CLOUD and cloud_root:
        private_state = f"cloud-private:{cloud_root}"
    parsed_bridge = urlparse(bridge_url)
    bridge_host = parsed_bridge.hostname or bridge_url.rstrip("/")
    if parsed_bridge.port:
        bridge_host = f"{bridge_host}:{parsed_bridge.port}"
    bridge_mode = "local-bridge" if bridge_host.startswith(("127.0.0.1", "localhost")) else "remote-bridge"
    return "\n".join(
        [
            "   .-=-.  HERMES WASM CONTROL SURFACE  .-=-.",
            "  /  _  \\     _._    alien uplink online",
            "  \\_/ \\_/  __/   \\__  node harness bay armed",
            f"  mode={mode} host={host} port={port}",
            f"  state_root={state_dir}",
            f"  bridge={bridge_mode} target={bridge_host}",
            f"  private_state={private_state}",
        ]
    )


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    public_root = plugin_root / "public"
    state_dir = resolve_wasm_agent_state_dir(plugin_root)
    ensure_cloud_private_paths(plugin_root, state_dir, auth_db_path(), auth_secret_path(), wa_env_path())
    state_dir.mkdir(parents=True, exist_ok=True)
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    mimetypes.add_type("application/wasm", ".wasm")

    args = build_parser().parse_args()
    with auth_connect():
        pass
    auth_secret()

    def handler(*handler_args: Any, **handler_kwargs: Any) -> WasmAgentHandler:
        return WasmAgentHandler(*handler_args, directory=str(public_root), **handler_kwargs)

    server = WasmAgentServer(
        (args.host, args.port),
        handler,
        plugin_root=plugin_root,
        public_root=public_root,
        state_dir=state_dir,
        bridge_url=args.bridge_url,
        browser_timeout_sec=args.browser_timeout_sec,
    )
    print(wasm_agent_startup_banner(host=args.host, port=args.port, state_dir=state_dir, bridge_url=args.bridge_url), flush=True)
    print(f"wasm-agent listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("wasm-agent stopping", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
