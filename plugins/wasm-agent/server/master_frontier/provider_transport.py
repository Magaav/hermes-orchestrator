"""Bounded provider transport policy shared by Master:frontier controllers."""
from __future__ import annotations

import json
import math
import os
import socket
import threading
import time
from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any, Iterator


DEFAULT_TIMEOUT_SEC = 90.0
MIN_TIMEOUT_SEC = 15.0
MAX_TIMEOUT_SEC = 180.0
TIMEOUT_ENV = "HERMES_WASM_AGENT_PROVIDER_TIMEOUT_SEC"


def timeout_sec(environ: Mapping[str, str] | None = None, *, requested: object = None) -> float:
    source = os.environ if environ is None else environ
    try:
        value = float(str(source.get(TIMEOUT_ENV, DEFAULT_TIMEOUT_SEC) or DEFAULT_TIMEOUT_SEC))
    except (TypeError, ValueError):
        value = DEFAULT_TIMEOUT_SEC
    if not math.isfinite(value):
        value = DEFAULT_TIMEOUT_SEC
    bounded = max(MIN_TIMEOUT_SEC, min(MAX_TIMEOUT_SEC, value))
    if requested is not None and not isinstance(requested, bool):
        try:
            requested_value = float(requested)
        except (TypeError, ValueError):
            requested_value = bounded
        if math.isfinite(requested_value):
            bounded = min(bounded, max(0.001, requested_value))
    return bounded


def deadline_at(started: float, timeout: float) -> float:
    return started + max(0.001, timeout)


def _remaining_sec(deadline: float, *, monotonic: Any = time.monotonic) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("Provider request exceeded its wall-clock deadline.")
    return remaining


def _bound_response_read(response: Any, deadline: float, *, monotonic: Any = time.monotonic) -> None:
    remaining = _remaining_sec(deadline, monotonic=monotonic)
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    if sock is not None and callable(getattr(sock, "settimeout", None)):
        sock.settimeout(remaining)


def _response_socket(response: Any) -> Any:
    return getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)


@contextmanager
def deadline_guard(response: Any, *, deadline: float) -> Iterator[None]:
    """Interrupt a blocked urllib read at the absolute provider deadline."""
    fired = threading.Event()

    def abort() -> None:
        fired.set()
        sock = _response_socket(response)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        try:
            response.close()
        except Exception:
            pass

    timer = threading.Timer(max(0.001, deadline - time.monotonic()), abort)
    timer.daemon = True
    timer.start()
    try:
        yield
        if fired.is_set():
            raise TimeoutError("Provider request exceeded its wall-clock deadline.")
    except Exception as exc:
        if fired.is_set() and not isinstance(exc, TimeoutError):
            raise TimeoutError("Provider request exceeded its wall-clock deadline.") from exc
        raise
    finally:
        timer.cancel()


def _deadline_lines(
    response: Any,
    deadline: float,
    *,
    monotonic: Any = time.monotonic,
) -> Iterator[bytes]:
    """Yield lines without letting a continuously streamed line evade the deadline."""
    buffered = bytearray()
    read_chunk = getattr(response, "read1", None)
    if not callable(read_chunk):
        read_chunk = response.readline
    while True:
        _bound_response_read(response, deadline, monotonic=monotonic)
        chunk = read_chunk(8192)
        if not chunk:
            break
        buffered.extend(chunk)
        while b"\n" in buffered:
            raw_line, _, remainder = buffered.partition(b"\n")
            buffered = bytearray(remainder)
            yield raw_line
    if buffered:
        _remaining_sec(deadline, monotonic=monotonic)
        yield bytes(buffered)


def read_bytes(
    response: Any,
    *,
    deadline: float,
    monotonic: Any = time.monotonic,
) -> bytes:
    """Read a provider body in chunks under one absolute call deadline."""
    chunks: list[bytes] = []
    read_chunk = getattr(response, "read1", None)
    if not callable(read_chunk):
        read_chunk = response.read
    while True:
        _bound_response_read(response, deadline, monotonic=monotonic)
        chunk = read_chunk(65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def iter_sse_json(
    response: Any,
    *,
    deadline: float,
    monotonic: Any = time.monotonic,
) -> Iterator[dict[str, Any]]:
    """Parse SSE while bounding every read to one absolute call deadline."""
    event_name = ""
    data_lines: list[str] = []
    for raw_line in _deadline_lines(response, deadline, monotonic=monotonic):
        line = raw_line.decode("utf-8", "replace").rstrip("\r")
        if not line:
            if data_lines:
                data = "\n".join(data_lines).strip()
                data_lines = []
                if data and data != "[DONE]":
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        payload = {"type": event_name or "message", "data": data}
                    if event_name and isinstance(payload, dict) and not payload.get("event"):
                        payload["event"] = event_name
                    yield payload
            event_name = ""
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())
    if data_lines:
        data = "\n".join(data_lines).strip()
        if data and data != "[DONE]":
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                yield {"type": event_name or "message", "data": data}
