"""Minimal persistent CDP websocket client for browser-plus."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import ssl
import struct
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import urlparse

try:  # pragma: no cover - optional dependency
    import websockets  # type: ignore[import-not-found]
    from websockets.exceptions import ConnectionClosed  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - stdlib fallback path
    websockets = None

    class ConnectionClosed(Exception):
        """Fallback close signal when the external websockets package is absent."""


EventHandler = Callable[[str, Dict[str, Any], Optional[str]], Awaitable[None] | None]


class _StdlibWebSocket:
    """Small asyncio websocket client for CDP text traffic."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        self._closed = False

    @classmethod
    async def connect(cls, url: str, *, open_timeout: float = 20.0) -> "_StdlibWebSocket":
        parsed = urlparse(url)
        if parsed.scheme not in {"ws", "wss"}:
            raise RuntimeError(f"Unsupported websocket scheme in {url!r}")
        host = parsed.hostname or ""
        if not host:
            raise RuntimeError(f"Websocket URL is missing a hostname: {url!r}")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        ssl_ctx = ssl.create_default_context() if parsed.scheme == "wss" else None
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl_ctx),
            timeout=open_timeout,
        )

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        host_header = host if parsed.port is None else f"{host}:{port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "User-Agent: browser-plus\r\n"
            "\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()

        response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=open_timeout)
        header_text = response.decode("latin-1", errors="replace")
        lines = header_text.split("\r\n")
        status_line = lines[0] if lines else ""
        if " 101 " not in f" {status_line} ":
            raise RuntimeError(f"Websocket handshake failed: {status_line or header_text.strip()}")

        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            key_name, value = line.split(":", 1)
            headers[key_name.strip().lower()] = value.strip()

        expected_accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if headers.get("sec-websocket-accept") != expected_accept:
            raise RuntimeError("Websocket handshake failed: invalid Sec-WebSocket-Accept")

        return cls(reader, writer)

    async def send(self, text: str) -> None:
        payload = text.encode("utf-8")
        await self._write_frame(0x1, payload)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._write_frame(0x8, b"")
        except Exception:
            pass
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except Exception:
            pass

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        try:
            return await self.recv()
        except ConnectionClosed:
            raise StopAsyncIteration

    async def recv(self) -> str:
        chunks: list[bytes] = []
        message_opcode: int | None = None
        while True:
            fin, opcode, payload = await self._read_frame()
            if opcode == 0x8:
                self._closed = True
                raise ConnectionClosed("Websocket closed by remote peer")
            if opcode == 0x9:
                await self._write_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in {0x1, 0x2}:
                message_opcode = opcode
                chunks.append(payload)
                if fin:
                    break
                continue
            if opcode == 0x0:
                if message_opcode is None:
                    continue
                chunks.append(payload)
                if fin:
                    break
                continue

        data = b"".join(chunks)
        return data.decode("utf-8", errors="replace")

    async def _write_frame(self, opcode: int, payload: bytes) -> None:
        if self._writer.is_closing():
            raise ConnectionClosed("Websocket writer is closed")
        header = bytearray()
        header.append(0x80 | (opcode & 0x0F))
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[idx % 4] for idx, byte in enumerate(payload))
        self._writer.write(bytes(header) + masked)
        await self._writer.drain()

    async def _read_frame(self) -> tuple[bool, int, bytes]:
        try:
            first, second = await self._reader.readexactly(2)
        except asyncio.IncompleteReadError as exc:
            raise ConnectionClosed("Websocket closed during frame read") from exc

        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", await self._reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", await self._reader.readexactly(8))[0]

        mask = await self._reader.readexactly(4) if masked else b""
        payload = await self._reader.readexactly(length)
        if masked:
            payload = bytes(byte ^ mask[idx % 4] for idx, byte in enumerate(payload))
        return fin, opcode, payload


class CDPConnection:
    """Small CDP websocket client with persistent receive-loop dispatch."""

    def __init__(self, url: str, event_handler: EventHandler | None = None):
        self.url = url
        self._event_handler = event_handler
        self._ws = None
        self._recv_task: asyncio.Task | None = None
        self._next_id = 1
        self._pending: Dict[int, asyncio.Future] = {}
        self._closed = False

    async def start(self) -> None:
        if self._ws is not None:
            return
        if websockets is not None:
            self._ws = await websockets.connect(  # type: ignore[union-attr]
                self.url,
                max_size=None,
                open_timeout=20,
                close_timeout=5,
                ping_interval=None,
            )
        else:
            self._ws = await _StdlibWebSocket.connect(self.url, open_timeout=20)
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        recv_task = self._recv_task
        self._recv_task = None
        ws = self._ws
        self._ws = None
        if ws is not None:
            await ws.close()
        if recv_task is not None:
            try:
                await recv_task
            except Exception:
                pass
        self._fail_pending(RuntimeError("CDP connection closed"))

    async def send_raw(
        self,
        method: str,
        params: Dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        if self._closed:
            raise RuntimeError("CDP connection is closed")
        if self._ws is None:
            await self.start()
        assert self._ws is not None

        loop = asyncio.get_running_loop()
        call_id = self._next_id
        self._next_id += 1
        future = loop.create_future()
        self._pending[call_id] = future

        payload: Dict[str, Any] = {
            "id": call_id,
            "method": method,
            "params": params or {},
        }
        if session_id:
            payload["sessionId"] = session_id

        try:
            await self._ws.send(json.dumps(payload))
            message = await asyncio.wait_for(future, timeout=timeout)
        except Exception:
            self._pending.pop(call_id, None)
            raise

        if "error" in message:
            error = message["error"]
            if isinstance(error, dict):
                raise RuntimeError(error.get("message") or json.dumps(error, ensure_ascii=False))
            raise RuntimeError(str(error))
        return message.get("result", {})

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                message = json.loads(raw)
                call_id = message.get("id")
                if call_id is not None:
                    future = self._pending.pop(int(call_id), None)
                    if future is not None and not future.done():
                        future.set_result(message)
                    continue
                handler = self._event_handler
                if handler is None:
                    continue
                ret = handler(
                    str(message.get("method") or ""),
                    message.get("params") or {},
                    message.get("sessionId"),
                )
                if asyncio.iscoroutine(ret):
                    await ret
        except ConnectionClosed as exc:
            self._fail_pending(RuntimeError(f"CDP websocket closed: {exc}"))
        except Exception as exc:
            self._fail_pending(exc)

    def _fail_pending(self, exc: Exception) -> None:
        pending = list(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(exc)
