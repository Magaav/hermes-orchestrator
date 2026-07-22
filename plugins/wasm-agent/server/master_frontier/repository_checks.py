"""Bounded execution for route-registered repository checks.

The caller owns registry lookup and route authorization. This module executes
only the already-resolved argv, cwd, and timeout without a shell or inherited
environment.
"""
from __future__ import annotations

import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time
from typing import Literal, Sequence, TypedDict


SCHEMA = "master.frontier.repository_check.v1"
DEFAULT_PREVIEW_BYTES = 32 * 1024
MAX_PREVIEW_BYTES = 256 * 1024
MAX_ARGV_ITEMS = 64
MAX_ARGV_BYTES = 32 * 1024
MAX_TIMEOUT_SEC = 3_600.0
TERMINATE_GRACE_SEC = 0.5
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"

CheckStatus = Literal["passed", "failed", "timeout", "process_leak", "invalid", "spawn_error"]
CheckCode = Literal[
    "ok",
    "check_failed",
    "check_timeout",
    "check_process_leak",
    "check_invalid_argv",
    "check_invalid_cwd",
    "check_invalid_timeout",
    "check_invalid_preview_limit",
    "check_spawn_failed",
]
Termination = Literal["none", "term", "kill"]


class OutputPreview(TypedDict):
    bytes: int
    shown_bytes: int
    omitted_bytes: int
    truncated: bool
    head: str
    tail: str


class CheckResult(TypedDict):
    schema: str
    ok: bool
    code: CheckCode
    status: CheckStatus
    argv: list[str]
    cwd: str
    returncode: int | None
    duration_ms: int
    timed_out: bool
    termination: Termination
    stdout: OutputPreview
    stderr: OutputPreview
    error: str


def _empty_preview() -> OutputPreview:
    return {
        "bytes": 0,
        "shown_bytes": 0,
        "omitted_bytes": 0,
        "truncated": False,
        "head": "",
        "tail": "",
    }


class _Capture:
    """Continuously drain output while retaining only a bounded head/tail."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.total = 0
        self.buffer = bytearray()
        self.head = bytearray()
        self.tail = bytearray()
        self.clipped = False

    def feed(self, data: bytes) -> None:
        self.total += len(data)
        if not self.clipped and len(self.buffer) + len(data) <= self.limit:
            self.buffer.extend(data)
            return
        head_limit = (self.limit + 1) // 2
        tail_limit = self.limit - head_limit
        if not self.clipped:
            combined = bytes(self.buffer) + data
            self.head.extend(combined[:head_limit])
            if tail_limit:
                self.tail.extend(combined[-tail_limit:])
            self.buffer.clear(); self.clipped = True
            return
        if tail_limit:
            self.tail[:] = (self.tail + data)[-tail_limit:]

    def preview(self) -> OutputPreview:
        if not self.clipped:
            shown = bytes(self.buffer); head = shown; tail = b""
        else:
            head = bytes(self.head); tail = bytes(self.tail); shown = head + tail
        return {
            "bytes": self.total, "shown_bytes": len(shown),
            "omitted_bytes": max(0, self.total - len(shown)),
            "truncated": self.total > len(shown),
            "head": head.decode("utf-8", "replace"), "tail": tail.decode("utf-8", "replace"),
        }


def _result(
    *,
    code: CheckCode,
    status: CheckStatus,
    argv: list[str],
    cwd: str,
    started_ns: int,
    returncode: int | None = None,
    timed_out: bool = False,
    termination: Termination = "none",
    stdout: OutputPreview | None = None,
    stderr: OutputPreview | None = None,
    error: str = "",
) -> CheckResult:
    return {
        "schema": SCHEMA,
        "ok": status == "passed",
        "code": code,
        "status": status,
        "argv": argv,
        "cwd": cwd,
        "returncode": returncode,
        "duration_ms": max(0, round((time.monotonic_ns() - started_ns) / 1_000_000)),
        "timed_out": timed_out,
        "termination": termination,
        "stdout": stdout or _empty_preview(),
        "stderr": stderr or _empty_preview(),
        "error": error[:500],
    }


def _validated_argv(argv: Sequence[str]) -> list[str] | None:
    if isinstance(argv, (str, bytes)):
        return None
    try:
        clean = list(argv)
    except TypeError:
        return None
    if not clean or len(clean) > MAX_ARGV_ITEMS:
        return None
    if any(not isinstance(item, str) or not item or "\x00" in item for item in clean):
        return None
    if sum(len(item.encode("utf-8")) for item in clean) > MAX_ARGV_BYTES:
        return None
    return clean


def _terminate_process_group(proc: subprocess.Popen[bytes], grace_sec: float) -> Termination:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return "none"
    try:
        proc.wait(timeout=grace_sec)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, 0)
    except ProcessLookupError:
        return "term"
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return "term"
    proc.wait()
    return "kill"


def run(
    argv: Sequence[str],
    *,
    cwd: str | Path,
    timeout_sec: int | float,
    preview_bytes: int = DEFAULT_PREVIEW_BYTES,
) -> CheckResult:
    """Execute one pre-authorized check and return a bounded typed receipt."""
    started_ns = time.monotonic_ns()
    clean_argv = _validated_argv(argv)
    try:
        cwd_path = Path(cwd)
        cwd_text = str(cwd_path)
    except (TypeError, ValueError):
        cwd_path = Path()
        cwd_text = ""
    if clean_argv is None:
        return _result(code="check_invalid_argv", status="invalid", argv=[], cwd=cwd_text, started_ns=started_ns)
    if not cwd_path.is_absolute() or not cwd_path.is_dir():
        return _result(code="check_invalid_cwd", status="invalid", argv=clean_argv, cwd=cwd_text, started_ns=started_ns)
    if isinstance(timeout_sec, bool):
        valid_timeout = False
    else:
        try:
            timeout_sec = float(timeout_sec)
            valid_timeout = 0 < timeout_sec <= MAX_TIMEOUT_SEC
        except (TypeError, ValueError):
            valid_timeout = False
    if not valid_timeout:
        return _result(code="check_invalid_timeout", status="invalid", argv=clean_argv, cwd=cwd_text, started_ns=started_ns)
    if isinstance(preview_bytes, bool) or not isinstance(preview_bytes, int) or not 1 <= preview_bytes <= MAX_PREVIEW_BYTES:
        return _result(code="check_invalid_preview_limit", status="invalid", argv=clean_argv, cwd=cwd_text, started_ns=started_ns)

    with tempfile.TemporaryDirectory(prefix="mf-repository-check-") as raw_temp:
        temp_root = Path(raw_temp)
        home = temp_root / "home"
        child_tmp = temp_root / "tmp"
        home.mkdir()
        child_tmp.mkdir()
        env = {
            "PATH": SAFE_PATH,
            "LANG": "C.UTF-8",
            "HOME": str(home),
            "TMPDIR": str(child_tmp),
        }
        try:
            proc = subprocess.Popen(
                clean_argv, cwd=cwd_path, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                close_fds=True, start_new_session=True,
            )
        except OSError as exc:
            return _result(
                code="check_spawn_failed",
                status="spawn_error",
                argv=clean_argv,
                cwd=cwd_text,
                started_ns=started_ns,
                error=f"{type(exc).__name__}: {exc}",
            )

        assert proc.stdout is not None and proc.stderr is not None
        streams = selectors.DefaultSelector()
        stdout_fd, stderr_fd = proc.stdout.fileno(), proc.stderr.fileno()
        captures = {stdout_fd: _Capture(preview_bytes), stderr_fd: _Capture(preview_bytes)}
        for stream in (proc.stdout, proc.stderr):
            os.set_blocking(stream.fileno(), False)
            streams.register(stream, selectors.EVENT_READ)
        deadline = time.monotonic() + float(timeout_sec)
        hard_deadline = deadline + TERMINATE_GRACE_SEC
        timed_out = False
        leaked = False
        termination: Termination = "none"
        cleaned = False
        pipe_deadline: float | None = None
        while streams.get_map():
            now = time.monotonic()
            if not timed_out and proc.poll() is None and now >= deadline:
                timed_out = True
                termination = _terminate_process_group(proc, TERMINATE_GRACE_SEC)
                cleaned = True
                pipe_deadline = hard_deadline
            if proc.poll() is not None and not cleaned:
                cleanup = _terminate_process_group(proc, TERMINATE_GRACE_SEC)
                if cleanup != "none":
                    leaked = True; termination = cleanup
                cleaned = True
                # A descendant may have escaped the original process group with
                # setsid() while retaining these pipes. Never let its descriptor
                # lifetime turn a bounded check into an unbounded server wait.
                pipe_deadline = min(hard_deadline, time.monotonic() + TERMINATE_GRACE_SEC)
            now = time.monotonic()
            if pipe_deadline is not None and now >= pipe_deadline:
                leaked = True
                for key in list(streams.get_map().values()):
                    try: streams.unregister(key.fileobj)
                    except (KeyError, ValueError): pass
                    key.fileobj.close()
                break
            wait_for = 0.05
            if pipe_deadline is not None:
                wait_for = max(0.0, min(wait_for, pipe_deadline - now))
            for key, _mask in streams.select(wait_for):
                try:
                    data = os.read(key.fd, 64 * 1024)
                except BlockingIOError:
                    continue
                if data:
                    captures[key.fd].feed(data)
                else:
                    streams.unregister(key.fileobj); key.fileobj.close()
        streams.close()
        if proc.poll() is None:
            termination = _terminate_process_group(proc, TERMINATE_GRACE_SEC)
        else:
            proc.wait()
        stdout = captures[stdout_fd].preview()
        stderr = captures[stderr_fd].preview()
        if timed_out:
            return _result(
                code="check_timeout",
                status="timeout",
                argv=clean_argv,
                cwd=cwd_text,
                started_ns=started_ns,
                returncode=proc.returncode,
                timed_out=True,
                termination=termination,
                stdout=stdout,
                stderr=stderr,
            )
        if leaked:
            return _result(
                code="check_process_leak", status="process_leak", argv=clean_argv, cwd=cwd_text,
                started_ns=started_ns, returncode=proc.returncode, termination=termination,
                stdout=stdout, stderr=stderr,
                error="The registered check left a descendant process running after its parent exited.",
            )
        return _result(
            code="ok" if proc.returncode == 0 else "check_failed",
            status="passed" if proc.returncode == 0 else "failed",
            argv=clean_argv,
            cwd=cwd_text,
            started_ns=started_ns,
            returncode=int(proc.returncode),
            stdout=stdout,
            stderr=stderr,
        )
