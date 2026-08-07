"""Server-owned MCP tool transport ports for Master:frontier V6.

Configuration is server-side and separate from route authority. Routes name and
allowlist MCP servers/tools; this module resolves those names to either a
persistent stdio session or a Streamable HTTP session. No transport credential
or command is projected to the model or browser.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import threading
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import contracts


CONFIG_FILE_ENV = "WASM_AGENT_MCP_SERVERS_FILE"
CONFIG_JSON_ENV = "WASM_AGENT_MCP_SERVERS_JSON"
DEPLOYMENT_MODE_ENV = "HERMES_WASM_AGENT_DEPLOYMENT_MODE"
PROTOCOL_VERSION = "2025-11-25"
MAX_CONFIG_BYTES = 1_000_000
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_TOOLS = 512
MAX_PAGES = 32
SERVER_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
ENV_REF = re.compile(r"^\$\{([A-Z_][A-Z0-9_]*)\}$")


class McpTransportError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def _bounded_json(raw: bytes) -> Any:
    if len(raw) > MAX_MESSAGE_BYTES:
        raise McpTransportError("mcp_response_too_large")
    try:
        return contracts.decode(raw.decode("utf-8"), max_bytes=MAX_MESSAGE_BYTES)
    except (UnicodeDecodeError, contracts.ContractError) as exc:
        raise McpTransportError("mcp_response_invalid") from exc


def _secret_value(value: Any, environ: Mapping[str, str]) -> str:
    text = str(value or "")
    match = ENV_REF.fullmatch(text)
    if not match:
        return text
    resolved = str(environ.get(match.group(1)) or "")
    if not resolved:
        raise McpTransportError("mcp_config_secret_missing")
    return resolved


def _load_config(environ: Mapping[str, str]) -> tuple[str, dict[str, dict[str, Any]]]:
    inline = str(environ.get(CONFIG_JSON_ENV) or "").strip()
    configured_file = str(environ.get(CONFIG_FILE_ENV) or "").strip()
    if inline and configured_file:
        raise McpTransportError("mcp_config_ambiguous")
    try:
        if inline:
            raw = inline.encode("utf-8")
        elif configured_file:
            path = Path(configured_file).expanduser().resolve(strict=True)
            if not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
                raise McpTransportError("mcp_config_file_invalid")
            raw = path.read_bytes()
        else:
            raw = b'{"servers":[]}'
    except OSError as exc:
        raise McpTransportError("mcp_config_file_unavailable") from exc
    if len(raw) > MAX_CONFIG_BYTES:
        raise McpTransportError("mcp_config_too_large")
    decoded = _bounded_json(raw)
    if not isinstance(decoded, dict) or not isinstance(decoded.get("servers"), list):
        raise McpTransportError("mcp_config_invalid")
    servers: dict[str, dict[str, Any]] = {}
    for item in decoded["servers"][:64]:
        if not isinstance(item, dict):
            raise McpTransportError("mcp_server_config_invalid")
        server_id = str(item.get("id") or "")
        if not SERVER_ID.fullmatch(server_id) or server_id in servers:
            raise McpTransportError("mcp_server_id_invalid")
        transport = str(item.get("transport") or "")
        if transport not in {"stdio", "streamable-http"}:
            raise McpTransportError("mcp_transport_invalid")
        servers[server_id] = item
    if len(decoded["servers"]) > 64:
        raise McpTransportError("mcp_server_count_exceeded")
    return hashlib.sha256(raw).hexdigest(), servers


def _timeout(config: dict[str, Any]) -> float:
    try:
        return max(0.25, min(float(config.get("timeout_sec") or 30), 120.0))
    except (TypeError, ValueError) as exc:
        raise McpTransportError("mcp_timeout_invalid") from exc


def _result(response: Any, request_id: int) -> dict[str, Any]:
    if not isinstance(response, dict) or response.get("jsonrpc") != "2.0" or response.get("id") != request_id:
        raise McpTransportError("mcp_response_mismatch")
    if isinstance(response.get("error"), dict):
        error = response["error"]
        raise McpTransportError("mcp_rpc_error", str(error.get("message") or "MCP request failed.")[:500])
    result = response.get("result")
    if not isinstance(result, dict):
        raise McpTransportError("mcp_result_invalid")
    return result


class _Session:
    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def close(self) -> None:
        return None


class _StdioSession(_Session):
    def __init__(self, config: dict[str, Any], environ: Mapping[str, str]) -> None:
        command = config.get("command")
        if not isinstance(command, list) or not command or len(command) > 64:
            raise McpTransportError("mcp_stdio_command_invalid")
        self.command = [str(item) for item in command]
        if any(not item or "\x00" in item for item in self.command):
            raise McpTransportError("mcp_stdio_command_invalid")
        raw_cwd = str(config.get("cwd") or "").strip()
        self.cwd = Path(raw_cwd).expanduser().resolve(strict=True) if raw_cwd else None
        if self.cwd is not None and not self.cwd.is_dir():
            raise McpTransportError("mcp_stdio_cwd_invalid")
        raw_env = config.get("env") if isinstance(config.get("env"), dict) else {}
        self.env = {
            key: value for key, value in os.environ.items()
            if key in {"PATH", "HOME", "SYSTEMROOT", "WINDIR", "PATHEXT", "TMPDIR", "TEMP", "TMP", "LANG"}
        }
        for key, value in raw_env.items():
            if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", str(key)):
                raise McpTransportError("mcp_stdio_env_invalid")
            self.env[str(key)] = _secret_value(value, environ)
        self.timeout = _timeout(config)
        self.lock = threading.RLock()
        self.process: subprocess.Popen[bytes] | None = None
        self.buffer = bytearray()
        self.next_id = 0
        self.initialized = False
        self.protocol_version = PROTOCOL_VERSION

    def _send(self, value: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None or self.process.poll() is not None:
            raise McpTransportError("mcp_stdio_process_unavailable")
        raw = contracts.canonical(value).encode("utf-8") + b"\n"
        if len(raw) > MAX_MESSAGE_BYTES:
            raise McpTransportError("mcp_request_too_large")
        try:
            self.process.stdin.write(raw)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise McpTransportError("mcp_stdio_write_failed") from exc

    def _receive(self, request_id: int) -> dict[str, Any]:
        if self.process is None or self.process.stdout is None:
            raise McpTransportError("mcp_stdio_process_unavailable")
        descriptor = self.process.stdout.fileno()
        deadline = time.monotonic() + self.timeout
        with selectors.DefaultSelector() as selected:
            selected.register(descriptor, selectors.EVENT_READ)
            while True:
                while b"\n" in self.buffer:
                    raw, _separator, remainder = self.buffer.partition(b"\n")
                    self.buffer = bytearray(remainder)
                    if not raw:
                        continue
                    message = _bounded_json(bytes(raw))
                    if isinstance(message, dict) and message.get("id") == request_id and ("result" in message or "error" in message):
                        return message
                    if isinstance(message, dict) and "id" in message and isinstance(message.get("method"), str):
                        reply = {"jsonrpc": "2.0", "id": message["id"]}
                        if message["method"] == "ping":
                            reply["result"] = {}
                        else:
                            reply["error"] = {"code": -32601, "message": "Client method not supported"}
                        self._send(reply)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise McpTransportError("mcp_stdio_timeout")
                if not selected.select(remaining):
                    raise McpTransportError("mcp_stdio_timeout")
                try:
                    chunk = os.read(descriptor, 65_536)
                except OSError as exc:
                    raise McpTransportError("mcp_stdio_read_failed") from exc
                if not chunk:
                    raise McpTransportError("mcp_stdio_eof")
                self.buffer.extend(chunk)
                if len(self.buffer) > MAX_MESSAGE_BYTES:
                    raise McpTransportError("mcp_response_too_large")

    def _raw_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.next_id += 1
        request_id = self.next_id
        request = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            request["params"] = params
        self._send(request)
        return _result(self._receive(request_id), request_id)

    def _ensure(self) -> None:
        if self.initialized and self.process is not None and self.process.poll() is None:
            return
        self.close()
        try:
            self.process = subprocess.Popen(
                self.command, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False,
                close_fds=True, start_new_session=os.name == "posix",
            )
        except OSError as exc:
            raise McpTransportError("mcp_stdio_spawn_failed") from exc
        try:
            initialized = self._raw_request("initialize", {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "wasm-agent-master-frontier", "version": "6"},
            })
        except Exception:
            self.close()
            raise
        negotiated = str(initialized.get("protocolVersion") or "")
        if not negotiated:
            self.close()
            raise McpTransportError("mcp_initialize_invalid")
        self.protocol_version = negotiated
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.initialized = True

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.lock:
            self._ensure()
            return self._raw_request(method, params)

    def close(self) -> None:
        process, self.process = self.process, None
        self.initialized = False
        self.buffer.clear()
        if process is None:
            return
        try:
            if process.poll() is None:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGTERM)
                    else:  # pragma: no cover - production server is POSIX.
                        process.terminate()
                    process.wait(timeout=0.5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    if process.poll() is None:
                        process.kill()
                        process.wait()
        finally:
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()


def _sse_messages(raw: bytes) -> list[Any]:
    messages: list[Any] = []
    data: list[str] = []
    try:
        lines = raw.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as exc:
        raise McpTransportError("mcp_response_invalid") from exc
    for raw_line in lines + [""]:
        if raw_line == "":
            if data:
                messages.append(_bounded_json("\n".join(data).encode("utf-8")))
                data = []
            continue
        if raw_line.startswith("data:"):
            data.append(raw_line[5:].lstrip(" "))
    return messages


class _HttpSession(_Session):
    def __init__(self, config: dict[str, Any], environ: Mapping[str, str]) -> None:
        self.url = str(config.get("url") or "").strip()
        try:
            parsed = urlparse(self.url)
            port = parsed.port
        except ValueError as exc:
            raise McpTransportError("mcp_http_url_invalid") from exc
        loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        deployment = str(environ.get(DEPLOYMENT_MODE_ENV) or "local").lower()
        insecure_dev = config.get("allow_insecure_loopback") is True and loopback and deployment != "cloud"
        if parsed.scheme != "https" and not (parsed.scheme == "http" and insecure_dev):
            raise McpTransportError("mcp_http_url_invalid")
        if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise McpTransportError("mcp_http_url_invalid")
        self.origin = (parsed.scheme.lower(), parsed.hostname.lower(), port)
        raw_headers = config.get("headers") if isinstance(config.get("headers"), dict) else {}
        self.headers: dict[str, str] = {}
        for key, value in raw_headers.items():
            name = str(key)
            if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", name) or name.lower() in {"host", "content-length", "mcp-session-id", "mcp-protocol-version"}:
                raise McpTransportError("mcp_http_header_invalid")
            self.headers[name] = _secret_value(value, environ)
        self.timeout = _timeout(config)
        self.lock = threading.RLock()
        self.next_id = 0
        self.session_id = ""
        self.protocol_version = PROTOCOL_VERSION
        self.initialized = False

    def _post(self, message: dict[str, Any], *, request_id: int | None) -> Any:
        raw = contracts.canonical(message).encode("utf-8")
        if len(raw) > MAX_MESSAGE_BYTES:
            raise McpTransportError("mcp_request_too_large")
        headers = {
            **self.headers, "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.protocol_version,
        }
        if self.session_id:
            headers["MCP-Session-Id"] = self.session_id
        request = Request(self.url, data=raw, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - URL is server-owned and HTTPS-validated above.
                final = urlparse(response.geturl())
                if (final.scheme.lower(), (final.hostname or "").lower(), final.port) != self.origin:
                    raise McpTransportError("mcp_http_redirect_denied")
                assigned = str(response.headers.get("MCP-Session-Id") or "")
                if assigned:
                    if any(ord(char) < 0x21 or ord(char) > 0x7E for char in assigned):
                        raise McpTransportError("mcp_http_session_invalid")
                    self.session_id = assigned
                body = response.read(MAX_MESSAGE_BYTES + 1)
                if len(body) > MAX_MESSAGE_BYTES:
                    raise McpTransportError("mcp_response_too_large")
                if response.status == 202 and request_id is None:
                    return None
                content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        except HTTPError as exc:
            raise McpTransportError("mcp_http_status", f"MCP HTTP status {exc.code}") from exc
        except URLError as exc:
            raise McpTransportError("mcp_http_unavailable") from exc
        if request_id is None:
            return None
        if content_type == "application/json":
            return _bounded_json(body)
        if content_type == "text/event-stream":
            return next((item for item in _sse_messages(body) if isinstance(item, dict) and item.get("id") == request_id), None)
        raise McpTransportError("mcp_http_content_type_invalid")

    def _raw_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.next_id += 1
        request_id = self.next_id
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        return _result(self._post(message, request_id=request_id), request_id)

    def _ensure(self) -> None:
        if self.initialized:
            return
        initialized = self._raw_request("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "wasm-agent-master-frontier", "version": "6"},
        })
        negotiated = str(initialized.get("protocolVersion") or "")
        if not negotiated:
            raise McpTransportError("mcp_initialize_invalid")
        self.protocol_version = negotiated
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, request_id=None)
        self.initialized = True

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.lock:
            self._ensure()
            return self._raw_request(method, params)

    def close(self) -> None:
        self.initialized = False
        self.session_id = ""


class Host:
    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self.environ = os.environ if environ is None else environ
        self.lock = threading.RLock()
        self.digest = ""
        self.configs: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, _Session] = {}
        self.catalog_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def _refresh(self) -> None:
        digest, configs = _load_config(self.environ)
        if digest == self.digest:
            return
        for session in self.sessions.values():
            session.close()
        self.digest, self.configs = digest, configs
        self.sessions.clear()
        self.catalog_cache.clear()

    def _session(self, server_id: str) -> tuple[_Session, dict[str, Any]]:
        with self.lock:
            self._refresh()
            config = self.configs.get(str(server_id))
            if config is None:
                raise McpTransportError("mcp_server_config_missing")
            session = self.sessions.get(server_id)
            if session is None:
                session = _StdioSession(config, self.environ) if config["transport"] == "stdio" else _HttpSession(config, self.environ)
                self.sessions[server_id] = session
            return session, config

    def tools(self, server_id: str) -> list[dict[str, Any]]:
        session, config = self._session(server_id)
        try:
            ttl = max(0.0, min(float(config.get("catalog_ttl_sec") or 60), 3600.0))
        except (TypeError, ValueError) as exc:
            raise McpTransportError("mcp_catalog_ttl_invalid") from exc
        with self.lock:
            cached = self.catalog_cache.get(server_id)
            if cached and time.monotonic() - cached[0] <= ttl:
                return contracts.decode(contracts.canonical(cached[1]))
        tools: list[dict[str, Any]] = []
        cursor = ""
        seen_cursors: set[str] = set()
        for _page in range(MAX_PAGES):
            result = session.request("tools/list", {"cursor": cursor} if cursor else None)
            values = result.get("tools")
            if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
                raise McpTransportError("mcp_tools_invalid")
            tools.extend(values)
            if len(tools) > MAX_TOOLS:
                raise McpTransportError("mcp_tools_exceeded")
            cursor = str(result.get("nextCursor") or "")
            if not cursor:
                break
            if cursor in seen_cursors:
                raise McpTransportError("mcp_cursor_cycle")
            seen_cursors.add(cursor)
        else:
            raise McpTransportError("mcp_pages_exceeded")
        names = [str(item.get("name") or "") for item in tools]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise McpTransportError("mcp_tool_name_invalid")
        ordered = sorted(tools, key=lambda item: str(item.get("name") or ""))
        with self.lock:
            self.catalog_cache[server_id] = (time.monotonic(), ordered)
        return contracts.decode(contracts.canonical(ordered))

    def call(self, server_id: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        session, _config = self._session(server_id)
        if not isinstance(arguments, dict):
            raise McpTransportError("mcp_arguments_invalid")
        return session.request("tools/call", {"name": str(tool), "arguments": arguments})

    def close(self) -> None:
        with self.lock:
            for session in self.sessions.values():
                session.close()
            self.sessions.clear()
            self.catalog_cache.clear()


_HOST = Host()


def catalog(_server: Any, _user: dict[str, Any] | None, route: dict[str, Any]) -> list[dict[str, Any]]:
    declared = route.get("mcp") if isinstance(route.get("mcp"), dict) else {}
    server_ids = [
        str(item.get("id") or "")
        for item in (declared.get("servers") or [])[:64]
        if isinstance(item, dict) and str(item.get("id") or "")
    ]
    return [{"id": server_id, "tools": _HOST.tools(server_id)} for server_id in server_ids]


def call(
    _server: Any, _user: dict[str, Any] | None, _route: dict[str, Any],
    server_id: str, tool: str, arguments: dict[str, Any],
) -> dict[str, Any]:
    return _HOST.call(server_id, tool, arguments)


def reset_for_tests() -> None:
    global _HOST
    _HOST.close()
    _HOST = Host()
