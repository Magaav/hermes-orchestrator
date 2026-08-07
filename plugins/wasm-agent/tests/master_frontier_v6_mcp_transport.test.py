#!/usr/bin/env python3
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest


SERVER = Path(__file__).resolve().parents[1] / "server"
import sys
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import mcp_transport  # noqa: E402


STDIO_SERVER = r'''
import json, os, sys
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if "id" not in message:
        continue
    if method == "initialize":
        result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [
            {"name": "echo", "description": "Echo arguments", "inputSchema": {"type": "object"}},
            {"name": "alpha", "description": "Alphabetical first", "inputSchema": {"type": "object"}}
        ]}
    elif method == "tools/call":
        result = {"structuredContent": {"arguments": message.get("params", {}).get("arguments", {}), "secretPresent": bool(os.environ.get("FIXTURE_TOKEN"))}}
    else:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "missing"}}) + "\n")
        sys.stdout.flush()
        continue
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}, separators=(",", ":")) + "\n")
    sys.stdout.flush()
'''


class HttpFixture(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen_session = []

    def log_message(self, _format, *_args):
        return None

    def do_POST(self):  # noqa: N802 - stdlib handler contract.
        length = int(self.headers.get("Content-Length") or 0)
        message = json.loads(self.rfile.read(length))
        method = message.get("method")
        if method == "notifications/initialized":
            self.__class__.seen_session.append(self.headers.get("MCP-Session-Id"))
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        request_id = message["id"]
        if method == "initialize":
            result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "http-fixture", "version": "1"}}
            content_type = "application/json"
        elif method == "tools/list":
            self.__class__.seen_session.append(self.headers.get("MCP-Session-Id"))
            result = {"tools": [{"name": "read", "inputSchema": {"type": "object"}}]}
            content_type = "text/event-stream"
        else:
            self.__class__.seen_session.append(self.headers.get("MCP-Session-Id"))
            result = {"structuredContent": {"ok": True, "arguments": message["params"]["arguments"]}}
            content_type = "application/json"
        response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        if content_type == "text/event-stream":
            raw = ("event: message\ndata: " + json.dumps(response, separators=(",", ":")) + "\n\n").encode()
        else:
            raw = json.dumps(response, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("MCP-Session-Id", "fixture-session")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class V6McpTransportTests(unittest.TestCase):
    def test_persistent_stdio_catalog_and_call(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mf6-mcp-") as directory:
            script = Path(directory) / "server.py"
            script.write_text(STDIO_SERVER, encoding="utf-8")
            config = {"servers": [{
                "id": "fixture", "transport": "stdio",
                "command": [sys.executable, "-u", str(script)],
                "env": {"FIXTURE_TOKEN": "${FIXTURE_TOKEN}"}, "catalog_ttl_sec": 60,
            }]}
            host = mcp_transport.Host({
                mcp_transport.CONFIG_JSON_ENV: json.dumps(config),
                "FIXTURE_TOKEN": "server-owned-secret",
            })
            try:
                tools = host.tools("fixture")
                result = host.call("fixture", "echo", {"value": 7})
            finally:
                host.close()
        self.assertEqual([item["name"] for item in tools], ["alpha", "echo"])
        self.assertEqual(result["structuredContent"], {"arguments": {"value": 7}, "secretPresent": True})

    def test_streamable_http_json_sse_and_session_header(self) -> None:
        HttpFixture.seen_session = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), HttpFixture)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = {"servers": [{
            "id": "http-fixture", "transport": "streamable-http",
            "url": f"http://127.0.0.1:{server.server_port}/mcp",
            "allow_insecure_loopback": True,
        }]}
        host = mcp_transport.Host({mcp_transport.CONFIG_JSON_ENV: json.dumps(config)})
        try:
            tools = host.tools("http-fixture")
            result = host.call("http-fixture", "read", {"id": "a"})
        finally:
            host.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual([item["name"] for item in tools], ["read"])
        self.assertEqual(result["structuredContent"]["arguments"], {"id": "a"})
        self.assertEqual(HttpFixture.seen_session, ["fixture-session", "fixture-session", "fixture-session"])

    def test_cloud_rejects_plain_http_and_missing_secret(self) -> None:
        insecure = {"servers": [{
            "id": "remote", "transport": "streamable-http", "url": "http://127.0.0.1:9/mcp",
            "allow_insecure_loopback": True,
        }]}
        host = mcp_transport.Host({
            mcp_transport.CONFIG_JSON_ENV: json.dumps(insecure),
            mcp_transport.DEPLOYMENT_MODE_ENV: "cloud",
        })
        with self.assertRaisesRegex(mcp_transport.McpTransportError, "mcp_http_url_invalid"):
            host.tools("remote")

        missing = {"servers": [{
            "id": "fixture", "transport": "stdio", "command": [sys.executable, "-u", "missing.py"],
            "env": {"TOKEN": "${MISSING_TOKEN}"},
        }]}
        host = mcp_transport.Host({mcp_transport.CONFIG_JSON_ENV: json.dumps(missing)})
        with self.assertRaisesRegex(mcp_transport.McpTransportError, "mcp_config_secret_missing"):
            host.tools("fixture")


if __name__ == "__main__":
    unittest.main()
