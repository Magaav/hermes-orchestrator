from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
import json
import mimetypes

from .broker import EventBroker
from .clone_manager import (
    ALLOWED_ACTIONS,
    CloneManagerClient,
    CloneManagerError,
    discover_nodes,
    validate_action,
    validate_node_name,
)
from .guard import read_activity_entries, read_guard_node_detail, read_guard_status
from .contracts import (
    FleetActionRequest,
    FleetActionResult,
    FleetCapabilities,
    FleetNodeStatus,
    FleetNodeSummary,
)
from .logs import (
    allowed_channels,
    count_attention_events,
    node_log_paths,
    read_channel_events,
)
from .monitor import FleetMonitor
from .rate_limit import SlidingWindowRateLimiter
from .settings import GatewaySettings, load_settings


JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"}


class GatewayContext:
    def __init__(self, settings: GatewaySettings) -> None:
        self.settings = settings
        self.client = CloneManagerClient(
            script_path=settings.clone_manager_script,
            python_bin=settings.python_bin,
        )
        self.broker = EventBroker()
        self.rate_limiter = SlidingWindowRateLimiter()
        self.monitor = FleetMonitor(
            settings=settings,
            client=self.client,
            broker=self.broker,
        )

    def start(self) -> None:
        if not self.monitor.is_alive():
            self.monitor.start()

    def shutdown(self) -> None:
        self.monitor.shutdown()
        if self.monitor.is_alive():
            self.monitor.join(timeout=5)



def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")



def build_capabilities(context: GatewayContext) -> FleetCapabilities:
    settings = context.settings
    wasm_worker_candidate = settings.ui_root / "wasm" / "pkg" / "log_worker_bg.wasm"
    rust_source_exists = (settings.ui_root / "wasm" / "log-worker" / "src" / "lib.rs").exists()

    core = {
        "health": True,
        "nodes": True,
        "status": True,
        "logs": True,
        "guard": True,
        "activity_timeline": True,
        "sse": True,
        "safe_actions": sorted(ALLOWED_ACTIONS),
        "auth_required": bool(settings.api_token),
        "experimental_gate": "WASM_UI_EXPERIMENTAL",
        "experimental_active": settings.experimental,
        "source_of_truth": "scripts/clone/clone_manager.py",
    }

    enhanced = {
        "wasm_worker_rust_source": rust_source_exists,
        "wasm_worker_built": wasm_worker_candidate.exists(),
        "wasm_runtime_switch": True,
        "js_fallback": True,
        "terminal_passthrough": False,
    }

    return FleetCapabilities(
        core=core,
        enhanced=enhanced,
        experimental_enabled=settings.experimental,
    )



def _status_contract(node: str, payload: dict[str, Any], settings: GatewaySettings) -> FleetNodeStatus:
    container_state = payload.get("container_state") or {}
    running = bool(container_state.get("running"))
    status = str(container_state.get("status") or "unknown")

    logs = {
        "management": str(payload.get("log_file") or node_log_paths(node, settings)["management"]),
        "runtime": str(payload.get("runtime_log_file") or node_log_paths(node, settings)["runtime"]),
        "attention": str(payload.get("attention_log_file") or node_log_paths(node, settings)["attention"]),
        "hermes_errors": str(payload.get("hermes_errors_log_file") or node_log_paths(node, settings)["hermes_errors"]),
        "hermes_gateway": str(payload.get("hermes_gateway_log_file") or node_log_paths(node, settings)["hermes_gateway"]),
        "hermes_agent": str(payload.get("hermes_agent_log_file") or node_log_paths(node, settings)["hermes_agent"]),
    }

    return FleetNodeStatus(
        node=node,
        running=running,
        status=status,
        runtime_type=str(payload.get("runtime_type") or "unknown"),
        state_mode=str(payload.get("state_mode") or "unknown"),
        state_code=payload.get("state_code") if isinstance(payload.get("state_code"), int) else None,
        env_path=str(payload.get("env_path") or ""),
        clone_root=str(payload.get("clone_root") or ""),
        required_mounts_ok=payload.get("required_mounts_ok") if isinstance(payload.get("required_mounts_ok"), bool) else None,
        logs=logs,
        raw=payload,
    )



def _summary_contract(node: str, payload: dict[str, Any], settings: GatewaySettings) -> FleetNodeSummary:
    status_obj = _status_contract(node, payload, settings)
    return FleetNodeSummary(
        node=node,
        runtime_type=status_obj.runtime_type,
        running=status_obj.running,
        status=status_obj.status,
        state_mode=status_obj.state_mode,
        state_code=status_obj.state_code,
        attention_events_last_200=count_attention_events(node, settings, window_lines=200),
        log_paths=status_obj.logs,
    )



class FleetGatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        context: GatewayContext,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.context = context


class FleetGatewayHandler(BaseHTTPRequestHandler):
    server: FleetGatewayServer
    protocol_version = "HTTP/1.1"

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api_get(parsed)
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self._json_error(HTTPStatus.NOT_FOUND, "not_found")
            return
        self._handle_api_post(parsed)

    def _handle_api_get(self, parsed: Any) -> None:
        if parsed.path == "/api/fleet/capabilities":
            if not self._rate_limit(write=False):
                return
            caps = build_capabilities(self.server.context)
            self._json_response(HTTPStatus.OK, {"ok": True, "capabilities": caps.to_dict()})
            return

        if not self._require_auth(write=False):
            return
        if not self._rate_limit(write=False):
            return

        if not self.server.context.settings.experimental:
            self._json_error(
                HTTPStatus.FORBIDDEN,
                "wasm_ui_experimental_disabled",
                {
                    "hint": "Set WASM_UI_EXPERIMENTAL=1 to enable this interface.",
                },
            )
            return

        if parsed.path == "/api/fleet/nodes":
            self._list_nodes()
            return

        if parsed.path == "/api/fleet/guard/status":
            self._guard_status()
            return

        if parsed.path == "/api/fleet/stream":
            self._stream_events(parsed)
            return

        if parsed.path.startswith("/api/fleet/nodes/"):
            self._handle_node_get(parsed)
            return

        self._json_error(HTTPStatus.NOT_FOUND, "not_found")

    def _handle_api_post(self, parsed: Any) -> None:
        if not self._require_auth(write=True):
            return
        if not self._rate_limit(write=True):
            return

        if not self.server.context.settings.experimental:
            self._json_error(
                HTTPStatus.FORBIDDEN,
                "wasm_ui_experimental_disabled",
                {
                    "hint": "Set WASM_UI_EXPERIMENTAL=1 to enable this interface.",
                },
            )
            return

        if parsed.path.startswith("/api/fleet/nodes/") and parsed.path.endswith("/actions"):
            self._handle_node_action(parsed)
            return

        self._json_error(HTTPStatus.NOT_FOUND, "not_found")

    def _list_nodes(self) -> None:
        settings = self.server.context.settings
        nodes = discover_nodes(settings)
        summaries: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for node in nodes:
            try:
                payload = self.server.context.client.status(node)
                summaries.append(_summary_contract(node, payload, settings).to_dict())
            except CloneManagerError as exc:
                errors.append({"node": node, "error": str(exc)})
        self._json_response(
            HTTPStatus.OK,
            {
                "ok": True,
                "count": len(summaries),
                "nodes": summaries,
                "errors": errors,
            },
        )

    def _guard_status(self) -> None:
        payload = read_guard_status(self.server.context.settings)
        self._json_response(
            HTTPStatus.OK,
            {
                "ok": True,
                "guard": payload,
            },
        )

    def _handle_node_get(self, parsed: Any) -> None:
        settings = self.server.context.settings
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) < 4:
            self._json_error(HTTPStatus.NOT_FOUND, "not_found")
            return

        node_raw = path_parts[3]
        try:
            node = validate_node_name(node_raw)
        except CloneManagerError as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc))
            return

        if len(path_parts) == 5 and path_parts[4] == "status":
            try:
                payload = self.server.context.client.status(node)
                contract = _status_contract(node, payload, settings)
            except CloneManagerError as exc:
                self._json_error(HTTPStatus.BAD_GATEWAY, str(exc))
                return
            self._json_response(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "node": node,
                    "status": contract.to_dict(),
                },
            )
            return

        if len(path_parts) == 5 and path_parts[4] == "logs":
            query = parse_qs(parsed.query)
            channel = str((query.get("channel") or ["runtime"])[0] or "runtime").strip().lower()
            tail_raw = str((query.get("tail") or ["120"])[0] or "120")
            try:
                tail = max(1, min(int(tail_raw), self.server.context.settings.max_tail_lines))
            except Exception:
                self._json_error(HTTPStatus.BAD_REQUEST, "invalid tail value")
                return

            if channel not in allowed_channels():
                self._json_error(
                    HTTPStatus.BAD_REQUEST,
                    f"unsupported channel '{channel}'",
                    {"allowed": sorted(allowed_channels())},
                )
                return

            channels = [channel] if channel != "all" else sorted(ch for ch in allowed_channels() if ch != "all")
            events: list[dict[str, Any]] = []
            for selected in channels:
                events.extend(
                    event.to_dict()
                    for event in read_channel_events(node, selected, tail, settings)
                )

            events.sort(key=lambda item: str(item.get("ts") or ""))
            self._json_response(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "node": node,
                    "channel": channel,
                    "tail": tail,
                    "events": events,
                    "channels": channels,
                },
            )
            return

        if len(path_parts) == 5 and path_parts[4] == "guard":
            query = parse_qs(parsed.query)
            limit_raw = str((query.get("limit") or ["12"])[0] or "12")
            try:
                limit = max(1, min(int(limit_raw), 80))
            except Exception:
                self._json_error(HTTPStatus.BAD_REQUEST, "invalid limit value")
                return

            self._json_response(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "node": node,
                    "guard": read_guard_node_detail(node, settings, limit=limit),
                },
            )
            return

        if len(path_parts) == 5 and path_parts[4] == "activity":
            query = parse_qs(parsed.query)
            limit_raw = str((query.get("limit") or ["40"])[0] or "40")
            try:
                limit = max(1, min(int(limit_raw), 200))
            except Exception:
                self._json_error(HTTPStatus.BAD_REQUEST, "invalid limit value")
                return

            self._json_response(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "node": node,
                    "activity": read_activity_entries(node, settings, limit=limit),
                },
            )
            return

        self._json_error(HTTPStatus.NOT_FOUND, "not_found")

    def _handle_node_action(self, parsed: Any) -> None:
        settings = self.server.context.settings
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) != 5 or path_parts[4] != "actions":
            self._json_error(HTTPStatus.NOT_FOUND, "not_found")
            return

        node_raw = path_parts[3]
        try:
            node = validate_node_name(node_raw)
        except CloneManagerError as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc))
            return

        body = self._read_json_body()
        action_raw = str(body.get("action") or "")
        try:
            action = validate_action(action_raw)
        except CloneManagerError as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc))
            return

        started_at = _utc_now()
        try:
            before = self.server.context.client.status(node)
            if action == "start":
                action_payload = self.server.context.client.start(node)
            elif action == "stop":
                action_payload = self.server.context.client.stop(node)
            else:
                action_payload = {
                    "stop": self.server.context.client.stop(node),
                    "start": self.server.context.client.start(node),
                }
            after = self.server.context.client.status(node)
        except CloneManagerError as exc:
            self._json_error(HTTPStatus.BAD_GATEWAY, str(exc))
            return

        result = FleetActionResult(
            request=FleetActionRequest(node=node, action=action),
            accepted=True,
            started_at=started_at,
            finished_at=_utc_now(),
            before=_status_contract(node, before, settings).to_dict(),
            after=_status_contract(node, after, settings).to_dict(),
            action_payload=action_payload,
        )
        payload = result.to_dict()
        self.server.context.broker.publish("action", payload)

        self._json_response(
            HTTPStatus.OK,
            {
                "ok": True,
                "result": payload,
            },
        )

    def _stream_events(self, parsed: Any) -> None:
        node_filter = str((parse_qs(parsed.query).get("node") or [""])[0] or "").strip().lower()

        subscriber = self.server.context.broker.subscribe()
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            self._write_sse(
                "connected",
                {
                    "ok": True,
                    "node_filter": node_filter or None,
                    "server_time": _utc_now(),
                },
            )

            while True:
                try:
                    evt = subscriber.get(timeout=20)
                    if node_filter:
                        evt_node = str(evt.data.get("node") or "").strip().lower()
                        if evt_node and evt_node != node_filter:
                            continue
                    self._write_sse(evt.event, evt.data)
                except Empty:
                    self._write_sse("heartbeat", {"ts": _utc_now()})
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            self.server.context.broker.unsubscribe(subscriber)

    def _serve_static(self, raw_path: str) -> None:
        settings = self.server.context.settings
        path = raw_path or "/"
        if path == "/":
            path = "/index.html"

        rel = unquote(path).lstrip("/")
        target = (settings.ui_root / rel).resolve()
        ui_root = settings.ui_root.resolve()

        if not str(target).startswith(str(ui_root)):
            self.send_error(HTTPStatus.FORBIDDEN)
            return

        if target.is_dir():
            target = target / "index.html"

        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type, _ = mimetypes.guess_type(str(target))
        if target.suffix == ".wasm":
            content_type = "application/wasm"

        payload = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _require_auth(self, *, write: bool) -> bool:
        token = self.server.context.settings.api_token
        if not token:
            return True

        auth = str(self.headers.get("Authorization") or "").strip()
        if auth == f"Bearer {token}":
            return True

        # EventSource cannot set custom Authorization headers. Allow a token query
        # parameter only for the SSE route.
        parsed = urlparse(self.path)
        if parsed.path == "/api/fleet/stream":
            query_token = str((parse_qs(parsed.query).get("token") or [""])[0] or "").strip()
            if query_token and query_token == token:
                return True

        self._json_error(HTTPStatus.UNAUTHORIZED, "unauthorized")
        return False

    def _rate_limit(self, *, write: bool) -> bool:
        ip = str(self.client_address[0] if self.client_address else "unknown")
        settings = self.server.context.settings
        limit = settings.write_limit_per_minute if write else settings.read_limit_per_minute
        bucket = "write" if write else "read"

        result = self.server.context.rate_limiter.allow(
            f"{bucket}:{ip}",
            limit=limit,
            window_sec=60.0,
        )
        if result.allowed:
            return True

        self._json_error(
            HTTPStatus.TOO_MANY_REQUESTS,
            "rate_limited",
            {
                "retry_after_sec": round(result.retry_after_sec, 3),
            },
        )
        return False

    def _read_json_body(self) -> dict[str, Any]:
        try:
            length = int(str(self.headers.get("Content-Length") or "0"))
        except Exception:
            return {}
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _json_error(self, status: HTTPStatus, error: str, extra: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"ok": False, "error": error}
        if extra:
            payload.update(extra)
        self._json_response(status, payload)

    def _json_response(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", JSON_HEADERS["Content-Type"])
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_sse(self, event: str, data: dict[str, Any]) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        self.wfile.write(payload.encode("utf-8"))
        self.wfile.flush()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        # Keep stdout mostly clean; fleet events are available via /api/fleet/stream.
        return



def run_gateway(settings: GatewaySettings | None = None) -> None:
    resolved = settings or load_settings()

    if not resolved.clone_manager_script.exists():
        raise RuntimeError(f"clone_manager script not found: {resolved.clone_manager_script}")
    if not resolved.ui_root.exists():
        raise RuntimeError(f"UI root not found: {resolved.ui_root}")

    context = GatewayContext(resolved)
    context.start()

    server = FleetGatewayServer((resolved.host, resolved.port), FleetGatewayHandler, context)

    try:
        print(
            f"[wasm-ui] serving http://{resolved.host}:{resolved.port} "
            f"(experimental={'on' if resolved.experimental else 'off'})"
        )
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        context.shutdown()
