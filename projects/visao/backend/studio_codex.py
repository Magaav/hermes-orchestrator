#!/usr/bin/env python3
"""Redacted Codex account status and device-code login for Visão Studio."""

from __future__ import annotations

import argparse
import json
import selectors
import subprocess
import sys
import time
from typing import Any

from studio_runtime import CodexCredentialsError, codex_credentials, codex_environment


MAX_EVENT_BYTES = 64 * 1024
STATUS_TIMEOUT_SECONDS = 20
LOGIN_TIMEOUT_SECONDS = 10 * 60


class CodexRuntimeError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class CodexConnection:
    def __init__(self, timeout_seconds: int):
        binary, environment = codex_environment()
        self.deadline = time.monotonic() + timeout_seconds
        self.process = subprocess.Popen(
            [binary, "app-server", "--stdio"],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self.selector = selectors.DefaultSelector()
        if self.process.stdout is None:
            raise CodexRuntimeError("runtime_unavailable")
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def send(self, payload: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise CodexRuntimeError("runtime_closed")
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def event(self) -> dict[str, Any]:
        while time.monotonic() < self.deadline:
            if self.process.poll() is not None:
                raise CodexRuntimeError("runtime_exited")
            ready = self.selector.select(timeout=min(0.5, max(0.0, self.deadline - time.monotonic())))
            if not ready:
                continue
            line = self.process.stdout.readline(MAX_EVENT_BYTES + 1) if self.process.stdout else ""
            if len(line.encode("utf-8")) > MAX_EVENT_BYTES:
                raise CodexRuntimeError("runtime_event_too_large")
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                return event
        raise CodexRuntimeError("runtime_timeout")

    def request(self, request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.send({"method": method, "id": request_id, "params": params})
        while True:
            event = self.event()
            if event.get("id") != request_id:
                continue
            if event.get("error"):
                raise CodexRuntimeError("runtime_request_failed")
            result = event.get("result")
            if not isinstance(result, dict):
                raise CodexRuntimeError("runtime_invalid_response")
            return result

    def initialize(self) -> None:
        self.request(
            1,
            "initialize",
            {
                "clientInfo": {
                    "name": "visao_studio",
                    "title": "Visao Studio",
                    "version": "1.0.0",
                }
            },
        )
        self.send({"method": "initialized", "params": {}})

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def status() -> int:
    connection: CodexConnection | None = None
    try:
        connection = CodexConnection(STATUS_TIMEOUT_SECONDS)
        connection.initialize()
        result = connection.request(2, "account/read", {"refreshToken": True})
        account = result.get("account") if isinstance(result.get("account"), dict) else None
        connected = account is not None
        envelope_ready = False
        if connected:
            try:
                codex_credentials()
                envelope_ready = True
            except CodexCredentialsError:
                envelope_ready = False
        emit(
            {
                "account": {
                    "state": "connected" if connected else "disconnected",
                    "authMode": str(account.get("type") or "") if account else "",
                    "planType": str(account.get("planType") or "") if account else "",
                },
                "runtime": {"state": "ready"},
                "datacenter": {"state": "ready" if envelope_ready else "unavailable"},
            }
        )
        return 0
    except (CodexRuntimeError, FileNotFoundError, OSError) as error:
        error_class = error.code if isinstance(error, CodexRuntimeError) else "runtime_unavailable"
        emit(
            {
                "account": {"state": "unknown", "authMode": "", "planType": ""},
                "runtime": {"state": "unavailable", "errorClass": error_class},
                "datacenter": {"state": "unavailable"},
            }
        )
        return 0
    finally:
        if connection:
            connection.close()


def login() -> int:
    connection: CodexConnection | None = None
    login_id = ""
    try:
        connection = CodexConnection(LOGIN_TIMEOUT_SECONDS)
        connection.initialize()
        result = connection.request(2, "account/login/start", {"type": "chatgptDeviceCode"})
        login_id = str(result.get("loginId") or "")
        verification_url = str(result.get("verificationUrl") or "")
        user_code = str(result.get("userCode") or "")
        if not login_id or not verification_url or not user_code:
            raise CodexRuntimeError("login_invalid_response")
        emit(
            {
                "event": "login-started",
                "loginId": login_id,
                "verificationUrl": verification_url,
                "userCode": user_code,
            }
        )
        while True:
            event = connection.event()
            if event.get("method") != "account/login/completed":
                continue
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            if str(params.get("loginId") or "") != login_id:
                continue
            success = params.get("success") is True
            emit({"event": "login-completed", "success": success})
            return 0 if success else 1
    except (CodexRuntimeError, FileNotFoundError, OSError):
        emit({"event": "login-failed", "success": False, "errorClass": "login_unavailable"})
        return 1
    finally:
        if connection:
            connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "login"))
    args = parser.parse_args()
    return status() if args.command == "status" else login()


if __name__ == "__main__":
    raise SystemExit(main())
