"""ChatGPT-authenticated Codex decision head for the Master:frontier V5 loop."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import hashlib
import atexit
import select
from typing import Any


class CodexAppServerFailure(RuntimeError):
    pass


MODEL_CONTEXT_WINDOWS = {"gpt-5.6-terra": 258_000}


def _schema(tool_names: list[str]) -> dict[str, Any]:
    tool_name: dict[str, Any] = {"type": "string"}
    if tool_names:
        tool_name["enum"] = tool_names
    return {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "tool_calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": tool_name,
                        "arguments_json": {"type": "string"},
                    },
                    "required": ["name", "arguments_json"],
                    "additionalProperties": False,
                },
            },
            "finish_reason": {"type": "string"},
        },
        "required": ["reply", "tool_calls", "finish_reason"],
        "additionalProperties": False,
    }


def _prompt(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]], completion_only: bool, require_tool: bool = False,
) -> str:
    if completion_only:
        mode = "Return a final reply and no tool calls."
    elif tools and require_tool:
        mode = "V5 reports that required evidence is still incomplete. Select exactly one declared native tool and leave reply empty."
    else:
        mode = (
            "Choose zero or one declared native tool call, or return the final reply grounded in prior observations. "
            "When selecting a tool, put one concise user-visible progress update in reply before the tool call."
        )
    return (
        "You are the decision head inside an external deterministic tool loop. "
        "Do not inspect files, run commands, browse, call MCP, or use any tool from your own environment. "
        "The enclosing V5 host exclusively executes the declared native tools and will return observations. "
        f"{mode} Follow the supplied messages and tool schemas exactly.\n\n"
        + json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False, separators=(",", ":"))
    )


def _continuation_prompt(
    messages: list[dict[str, Any]], *, completion_only: bool, require_tool: bool,
) -> str:
    if completion_only:
        mode = "Return a final reply and no tool calls."
    elif require_tool:
        mode = "Required evidence is still incomplete. Select exactly one previously declared native tool and leave reply empty."
    else:
        mode = (
            "Choose zero or one previously declared native tool call, or return the final reply grounded in prior observations. "
            "When selecting a tool, put one concise user-visible progress update in reply before the tool call."
        )
    changed_messages = [message for message in messages if message.get("role") != "system"]
    return (
        "This is the next decision in the same external host loop. The latest host state below supersedes prior host state; "
        "the system contract and declared native tool schemas are unchanged. "
        f"{mode}\n\n"
        + json.dumps({"messages": changed_messages}, ensure_ascii=False, separators=(",", ":"))
    )


def _usage_from_app_server(value: dict[str, Any], model: str) -> dict[str, Any]:
    return {
        "prompt_tokens": int(value.get("inputTokens") or 0),
        "completion_tokens": int(value.get("outputTokens") or 0),
        "cached_input_tokens": int(value.get("cachedInputTokens") or 0),
        "reasoning_tokens": int(value.get("reasoningOutputTokens") or 0),
        "total_tokens": int(value.get("totalTokens") or 0),
        "model": model,
        "transport": "codex_app_server",
    }


def _rate_limits_from_app_server(value: dict[str, Any]) -> dict[str, Any]:
    snapshot = value.get("rateLimits") if isinstance(value.get("rateLimits"), dict) else value
    windows = [window for window in (snapshot.get("primary"), snapshot.get("secondary")) if isinstance(window, dict)]
    weekly = next((window for window in windows if int(window.get("windowDurationMins") or 0) == 10_080), None)
    used = max(0, min(100, int(weekly.get("usedPercent") or 0))) if weekly else None
    if used is None:
        return {}
    return {"seven_day": {
        "percent_used": used,
        "percent_left": 100 - used,
        "resets_at": weekly.get("resetsAt"),
        "window_duration_minutes": weekly.get("windowDurationMins"),
    }}


class _AppServerWorker:
    def __init__(self, executable: str, model: str, session_key: str, tool_digest: str) -> None:
        self.model = model
        self.session_key = session_key
        self.tool_digest = tool_digest
        self.lock = threading.Lock()
        self.request_id = 0
        self.thread_id = ""
        self.turn_count = 0
        self.notifications: list[dict[str, Any]] = []
        self.rate_limits: dict[str, Any] = {}
        self.root = tempfile.TemporaryDirectory(prefix="mf6-codex-app-")
        env = {
            key: value for key, value in os.environ.items()
            if key in {
                "PATH", "HOME", "CODEX_HOME", "TMPDIR", "SSL_CERT_FILE", "CODEX_CA_CERTIFICATE",
                "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "https_proxy", "http_proxy",
                "all_proxy", "no_proxy",
            }
        }
        try:
            self.process = subprocess.Popen(
                [executable, "app-server", "--stdio"], cwd=self.root.name, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
            self._initialize()
        except BaseException:
            process = getattr(self, "process", None)
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
            self.root.cleanup()
            raise

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.root.cleanup()

    def _send(self, method: str, params: dict[str, Any], *, notification: bool = False) -> int:
        if self.process.poll() is not None or self.process.stdin is None:
            raise CodexAppServerFailure("Codex app-server is unavailable.")
        self.request_id += 1
        message: dict[str, Any] = {"method": method, "params": params}
        if not notification:
            message["id"] = self.request_id
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        return self.request_id

    def _read(self, deadline: float) -> dict[str, Any]:
        if self.process.stdout is None:
            raise CodexAppServerFailure("Codex app-server stdout is unavailable.")
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([self.process.stdout], [], [], remaining)
            if not ready:
                raise CodexAppServerFailure("Codex app-server response timed out.")
            line = self.process.stdout.readline()
            if not line:
                raise CodexAppServerFailure("Codex app-server closed its output stream.")
            try:
                return json.loads(line)
            except ValueError:
                continue
        raise CodexAppServerFailure("Codex app-server response timed out.")

    def _response(self, request_id: int, deadline: float) -> dict[str, Any]:
        while True:
            message = self._read(deadline)
            if message.get("id") == request_id:
                if isinstance(message.get("error"), dict):
                    raise CodexAppServerFailure(str(message["error"].get("message") or "Codex app-server request failed."))
                return message.get("result") if isinstance(message.get("result"), dict) else {}
            if message.get("method"):
                self.notifications.append(message)

    def _notification(self, deadline: float) -> dict[str, Any]:
        if self.notifications:
            return self.notifications.pop(0)
        return self._read(deadline)

    def _initialize(self) -> None:
        deadline = time.monotonic() + 15
        request_id = self._send("initialize", {"clientInfo": {
            "name": "wasm_agent_master_frontier", "title": "WASM Agent Master Frontier", "version": "6",
        }})
        self._response(request_id, deadline)
        self._send("initialized", {}, notification=True)
        request_id = self._send("thread/start", {
            "model": self.model, "cwd": self.root.name, "approvalPolicy": "never",
            "sandbox": "read-only", "ephemeral": True, "serviceName": "wasm-agent-master-frontier",
            "baseInstructions": (
                "You are the decision head inside an external deterministic tool loop. "
                "Never inspect files, execute commands, browse, call MCP, or use Codex-owned tools. "
                "Return only the structured decision requested by the host."
            ),
        })
        result = self._response(request_id, deadline)
        self.thread_id = str((result.get("thread") or {}).get("id") or "")
        if not self.thread_id:
            raise CodexAppServerFailure("Codex app-server did not create a thread.")
        request_id = self._send("account/rateLimits/read", {})
        self.rate_limits = _rate_limits_from_app_server(self._response(request_id, deadline))

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *,
        completion_only: bool, require_tool: bool, timeout: int,
    ) -> dict[str, Any]:
        with self.lock:
            deadline = time.monotonic() + max(1, min(timeout, 300))
            prompt = (
                _prompt(messages, tools, completion_only, require_tool)
                if self.turn_count == 0
                else _continuation_prompt(
                    messages, completion_only=completion_only, require_tool=require_tool,
                )
            )
            request_id = self._send("turn/start", {
                "threadId": self.thread_id,
                "input": [{"type": "text", "text": prompt}],
                "model": self.model, "effort": "low", "summary": "none",
                "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
                "outputSchema": _schema([
                    str((item.get("function") or {}).get("name") or "")
                    for item in tools if isinstance(item, dict) and (item.get("function") or {}).get("name")
                ]),
            })
            turn_result = self._response(request_id, deadline)
            turn_id = str((turn_result.get("turn") or {}).get("id") or "")
            final_text = ""
            usage: dict[str, Any] = {}
            violations: list[str] = []
            while True:
                message = self._notification(deadline)
                method = str(message.get("method") or "")
                params = message.get("params") if isinstance(message.get("params"), dict) else {}
                event_turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
                event_turn_id = str(params.get("turnId") or event_turn.get("id") or "")
                if event_turn_id and event_turn_id != turn_id:
                    continue
                item = params.get("item") if isinstance(params.get("item"), dict) else {}
                item_type = str(item.get("type") or "")
                if method == "item/completed" and item_type == "agentMessage":
                    final_text = str(item.get("text") or "")
                if method == "item/started" and item_type not in {"", "userMessage", "agentMessage", "reasoning"}:
                    violations.append(item_type)
                if method == "thread/tokenUsage/updated":
                    token_usage = params.get("tokenUsage") if isinstance(params.get("tokenUsage"), dict) else {}
                    last = token_usage.get("last") if isinstance(token_usage.get("last"), dict) else {}
                    usage = _usage_from_app_server(last, self.model)
                    if token_usage.get("modelContextWindow") is not None:
                        usage["context_window_tokens"] = int(token_usage["modelContextWindow"])
                    elif self.model in MODEL_CONTEXT_WINDOWS:
                        usage["context_window_tokens"] = MODEL_CONTEXT_WINDOWS[self.model]
                if method == "account/rateLimits/updated":
                    update = _rate_limits_from_app_server(params)
                    if update:
                        self.rate_limits = update
                if method == "turn/completed":
                    status = str((params.get("turn") or {}).get("status") or "")
                    if status != "completed":
                        raise CodexAppServerFailure(f"Codex app-server turn ended as {status or 'unknown'}.")
                    break
                if method == "thread/status/changed" and final_text and usage:
                    break
            self.turn_count += 1
            usage["provider_thread_id"] = self.thread_id
            if self.rate_limits:
                usage["rate_limits"] = self.rate_limits
            if violations:
                raise CodexAppServerFailure("Codex crossed the decision-head boundary with items: " + ", ".join(sorted(set(violations))))
            try:
                decision = json.loads(final_text)
            except ValueError as exc:
                raise CodexAppServerFailure("Codex app-server decision was not valid JSON.") from exc
            tool_names = {
                str((item.get("function") or {}).get("name") or "")
                for item in tools if isinstance(item, dict)
            }
            normalized = []
            for index, call in enumerate((decision.get("tool_calls") or [])[:1]):
                if not isinstance(call, dict) or str(call.get("name") or "") not in tool_names:
                    raise CodexAppServerFailure("Codex selected an undeclared V6 tool.")
                try:
                    arguments = json.loads(str(call.get("arguments_json") or "{}"))
                except ValueError as exc:
                    raise CodexAppServerFailure("Codex emitted invalid native-tool argument JSON.") from exc
                normalized.append({"id": f"codex_app_{index + 1}", "name": str(call["name"]), "arguments": arguments})
            return {
                "reply": str(decision.get("reply") or "").strip(), "tool_calls": normalized,
                "usage": usage, "model": self.model,
                "finish_reason": str(decision.get("finish_reason") or "stop"),
                "transport": "codex_app_server", "provider_thread_id": self.thread_id,
            }


_WORKERS: dict[str, _AppServerWorker] = {}
_WORKERS_LOCK = threading.Lock()
_MAX_WORKERS = 8


def _worker_key(session_key: str, route_id: str, model: str, tools: list[dict[str, Any]]) -> str:
    tool_digest = hashlib.sha256(json.dumps(tools, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return hashlib.sha256(f"{session_key}\0{route_id}\0{model}\0{tool_digest}".encode()).hexdigest()


def _worker(executable: str, session_key: str, route_id: str, model: str, tools: list[dict[str, Any]]) -> _AppServerWorker:
    key = _worker_key(session_key, route_id, model, tools)
    with _WORKERS_LOCK:
        existing = _WORKERS.get(key)
        if existing is not None and existing.process.poll() is None:
            return existing
        while len(_WORKERS) >= _MAX_WORKERS:
            _, stale = _WORKERS.pop(next(iter(_WORKERS)))
            stale.close()
        tool_digest = key[-16:]
        created = _AppServerWorker(executable, model, session_key, tool_digest)
        _WORKERS[key] = created
        return created


def _close_workers() -> None:
    with _WORKERS_LOCK:
        for worker in _WORKERS.values():
            worker.close()
        _WORKERS.clear()


def _discard_worker(key: str, worker: _AppServerWorker) -> None:
    with _WORKERS_LOCK:
        if _WORKERS.get(key) is worker:
            _WORKERS.pop(key, None)
    worker.close()


atexit.register(_close_workers)


def complete(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]], *,
    completion_only: bool, require_tool: bool = False, timeout: int,
    model: str = "gpt-5.6-terra", session_key: str = "default", route_id: str = "",
) -> dict[str, Any]:
    executable = os.environ.get("MF5_CODEX_EXECUTABLE", "").strip() or shutil.which("codex") or ""
    if not executable:
        raise CodexAppServerFailure("Codex app-server executable is unavailable on the trusted host.")
    key = _worker_key(session_key, route_id, model, tools)
    worker: _AppServerWorker | None = None
    try:
        worker = _worker(executable, session_key, route_id, model, tools)
        return worker.complete(
            messages, tools, completion_only=completion_only, require_tool=require_tool, timeout=timeout,
        )
    except (CodexAppServerFailure, OSError) as exc:
        if worker is not None:
            _discard_worker(key, worker)
        if isinstance(exc, CodexAppServerFailure):
            raise
        raise CodexAppServerFailure("Codex app-server could not be started.") from exc
