"""ChatGPT-authenticated Codex decision head for the Master:frontier V5 loop."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import hashlib
import atexit
import select
from pathlib import Path
from typing import Any

import codex_conversation_state


class CodexAppServerFailure(RuntimeError):
    pass


class CodexDecisionContractFailure(CodexAppServerFailure):
    """A model decision that can be safely replayed on a fresh worker."""

    code = "codex_decision_contract_invalid"


MODEL_CONTEXT_WINDOWS = {
    "gpt-5.6-luna": 258_400,
    "gpt-5.6-terra": 258_000,
}
PRIMARY_ATTEMPT_MAX_SEC = 30
STATUS_TELEMETRY_SCHEMA = "hermes.wasm_agent.provider_status.v1"
LUNA_RECOVERY_MODEL = "gpt-5.6-terra"
COMPACTION_RATIO = 0.72


def _enforce_status_telemetry(
    usage: dict[str, Any], model: str, rate_limits: dict[str, Any], *,
    context_window_source: str = "",
) -> dict[str, Any]:
    resolved_model = str(model or usage.get("model") or "").strip()
    if not resolved_model:
        raise CodexAppServerFailure("Provider status contract is missing the resolved model.")
    context_window = usage.get("context_window_tokens")
    if context_window is None:
        context_window = MODEL_CONTEXT_WINDOWS.get(resolved_model)
        if context_window is not None:
            usage["context_window_tokens"] = context_window
            context_window_source = "model_capability_registry"
    if not isinstance(context_window, (int, float)) or isinstance(context_window, bool) or int(context_window) <= 0:
        raise CodexAppServerFailure("Provider status contract is missing the context window.")
    weekly = rate_limits.get("seven_day") if isinstance(rate_limits.get("seven_day"), dict) else None
    seven_day = {
        "status": "reported" if weekly else "provider_omitted",
        "source": "codex_app_server.account_rate_limits",
    }
    if weekly:
        seven_day.update(weekly)
    usage["model"] = resolved_model
    if rate_limits:
        usage["rate_limits"] = rate_limits
    usage["status_telemetry"] = {
        "schema": STATUS_TELEMETRY_SCHEMA,
        "captured_at": int(time.time()),
        "model": {"status": "reported", "value": resolved_model, "source": "resolved_request"},
        "context_window": {
            "status": "reported", "tokens": int(context_window),
            "source": context_window_source or "codex_app_server.token_usage",
        },
        "seven_day": seven_day,
    }
    return usage


def resolve_codex_executable(configured: str = "") -> str:
    candidates = [configured.strip(), shutil.which("codex") or ""]
    extensions = Path.home() / ".vscode-server" / "extensions"
    candidates.extend(str(path) for path in sorted(
        extensions.glob("openai.chatgpt-*/bin/linux-*/codex"), reverse=True,
    ))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return ""


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
        f"{mode} Follow the supplied messages and tool schemas exactly. "
        "Every arguments_json value must be one complete valid JSON object, never a fragment.\n\n"
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


def _tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise CodexDecisionContractFailure("Codex emitted invalid native-tool arguments.")
    try:
        decoded = json.loads(value or "{}")
    except ValueError as exc:
        raise CodexDecisionContractFailure("Codex emitted invalid native-tool argument JSON.") from exc
    if not isinstance(decoded, dict):
        raise CodexDecisionContractFailure("Codex emitted non-object native-tool arguments.")
    return decoded


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
    def __init__(self, executable: str, model: str, session_key: str, tool_digest: str, state_key: str) -> None:
        self.model = model
        self.session_key = session_key
        self.tool_digest = tool_digest
        self.state_key = state_key
        self.lock = threading.Lock()
        self.request_id = 0
        self.thread_id = ""
        self.turn_count = 0
        self.compaction_generation = 0
        self.compaction_status = "none"
        self.resumed = False
        self.fork_reason = ""
        self.notifications: list[dict[str, Any]] = []
        self.rate_limits: dict[str, Any] = {}
        self.root = codex_conversation_state.decision_cwd()
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
                [executable, "app-server", "--stdio"], cwd=str(self.root), env=env,
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
            raise

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()

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
        persisted = codex_conversation_state.load(self.state_key)
        persisted_thread = str(persisted.get("thread_id") or "")
        persisted_digest = str(persisted.get("tool_digest") or "")
        self.turn_count = max(0, int(persisted.get("turn_count") or 0))
        self.compaction_generation = max(0, int(persisted.get("compaction_generation") or 0))
        thread_params = {
            "model": self.model, "cwd": str(self.root), "approvalPolicy": "never",
            "sandbox": "read-only",
            "baseInstructions": (
                "You are the decision head inside an external deterministic tool loop. "
                "Never inspect files, execute commands, browse, call MCP, or use Codex-owned tools. "
                "Return only the structured decision requested by the host."
            ),
        }
        result: dict[str, Any] = {}
        if persisted_thread and persisted_digest == self.tool_digest:
            try:
                request_id = self._send("thread/resume", {"threadId": persisted_thread, **thread_params})
                result = self._response(request_id, deadline)
                self.resumed = True
            except CodexAppServerFailure:
                self.turn_count = 0
                self.fork_reason = "resume_unavailable"
        elif persisted_thread:
            self.turn_count = 0
            self.compaction_generation = 0
            self.fork_reason = "tool_contract_changed"
        if not result:
            request_id = self._send("thread/start", {
                **thread_params, "ephemeral": False, "serviceName": "wasm-agent-master-frontier",
            })
            result = self._response(request_id, deadline)
        self.thread_id = str((result.get("thread") or {}).get("id") or "")
        if not self.thread_id:
            raise CodexAppServerFailure("Codex app-server did not create a thread.")
        request_id = self._send("account/rateLimits/read", {})
        self.rate_limits = _rate_limits_from_app_server(self._response(request_id, deadline))
        self._persist()

    def _persist(self) -> None:
        codex_conversation_state.save(self.state_key, {
            "thread_id": self.thread_id, "tool_digest": self.tool_digest, "model": self.model,
            "turn_count": self.turn_count, "compaction_generation": self.compaction_generation,
            "compaction_status": self.compaction_status, "fork_reason": self.fork_reason,
        })

    def _compact(self, deadline: float) -> None:
        request_id = self._send("thread/compact/start", {"threadId": self.thread_id})
        self._response(request_id, deadline)
        self.compaction_generation += 1
        self.compaction_status = "requested"
        self._persist()

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
                if method == "item/completed" and item_type == "contextCompaction":
                    self.compaction_status = "completed"
                    self._persist()
                if method == "item/started" and item_type not in {"", "userMessage", "agentMessage", "reasoning", "contextCompaction"}:
                    violations.append(item_type)
                if method == "thread/tokenUsage/updated":
                    token_usage = params.get("tokenUsage") if isinstance(params.get("tokenUsage"), dict) else {}
                    last = token_usage.get("last") if isinstance(token_usage.get("last"), dict) else {}
                    usage = _usage_from_app_server(last, self.model)
                    if token_usage.get("modelContextWindow") is not None:
                        usage["context_window_tokens"] = int(token_usage["modelContextWindow"])
                        usage["context_window_source"] = "codex_app_server.token_usage"
                    elif self.model in MODEL_CONTEXT_WINDOWS:
                        usage["context_window_tokens"] = MODEL_CONTEXT_WINDOWS[self.model]
                        usage["context_window_source"] = "model_capability_registry"
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
            usage["provider_thread_turn"] = self.turn_count + 1
            usage["stable_context_mode"] = "thread_continuation"
            usage["stable_context_reused"] = self.turn_count > 0
            self.turn_count += 1
            usage["provider_thread_id"] = self.thread_id
            usage["provider_thread_resumed"] = self.resumed
            usage["provider_thread_fork_reason"] = self.fork_reason
            context_window = int(usage.get("context_window_tokens") or MODEL_CONTEXT_WINDOWS.get(self.model) or 0)
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            if (
                context_window and prompt_tokens / context_window >= COMPACTION_RATIO
                and self.compaction_status != "requested"
            ):
                self._compact(deadline)
            self._persist()
            usage["provider_compaction_generation"] = self.compaction_generation
            usage["provider_compaction_status"] = self.compaction_status
            _enforce_status_telemetry(
                usage, self.model, self.rate_limits,
                context_window_source=str(usage.pop("context_window_source", "")),
            )
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
                arguments = _tool_arguments(call.get("arguments_json") or {})
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


def _tool_digest(tools: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(tools, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _worker_key(session_key: str, route_id: str, model: str, tools: list[dict[str, Any]]) -> str:
    del tools
    return hashlib.sha256(f"{session_key}\0{route_id}\0{model}".encode()).hexdigest()


def _worker(executable: str, session_key: str, route_id: str, model: str, tools: list[dict[str, Any]]) -> _AppServerWorker:
    key = _worker_key(session_key, route_id, model, tools)
    tool_digest = _tool_digest(tools)
    with _WORKERS_LOCK:
        existing = _WORKERS.get(key)
        if existing is not None and existing.process.poll() is None and existing.tool_digest == tool_digest:
            return existing
        while len(_WORKERS) >= _MAX_WORKERS:
            _, stale = _WORKERS.pop(next(iter(_WORKERS)))
            stale.close()
        if existing is not None:
            existing.close()
            _WORKERS.pop(key, None)
        created = _AppServerWorker(executable, model, session_key, tool_digest, key)
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
    model: str = "gpt-5.6-luna", session_key: str = "default", route_id: str = "",
) -> dict[str, Any]:
    executable = resolve_codex_executable(os.environ.get("MF5_CODEX_EXECUTABLE", ""))
    if not executable:
        raise CodexAppServerFailure("Codex app-server executable is unavailable on the trusted host.")
    deadline = time.monotonic() + max(1, min(int(timeout), 300))
    for attempt in range(2):
        worker: _AppServerWorker | None = None
        attempt_model = LUNA_RECOVERY_MODEL if attempt and model == "gpt-5.6-luna" else model
        key = _worker_key(session_key, route_id, attempt_model, tools)
        try:
            worker = _worker(executable, session_key, route_id, attempt_model, tools)
            remaining = max(1, int(deadline - time.monotonic()))
            attempt_timeout = min(remaining, PRIMARY_ATTEMPT_MAX_SEC) if attempt == 0 else remaining
            return worker.complete(
                messages, tools, completion_only=completion_only, require_tool=require_tool,
                timeout=attempt_timeout,
            )
        except (CodexAppServerFailure, OSError) as exc:
            recoverable_timeout = bool(
                attempt == 0 and worker is not None
                and isinstance(exc, CodexAppServerFailure) and "response timed out" in str(exc).lower()
                and deadline - time.monotonic() >= 1
            )
            recoverable_decision = bool(
                attempt == 0 and worker is not None
                and isinstance(exc, CodexDecisionContractFailure)
                and deadline - time.monotonic() >= 1
            )
            if worker is not None:
                _discard_worker(key, worker)
            if recoverable_timeout or recoverable_decision:
                continue
            if isinstance(exc, CodexAppServerFailure):
                raise
            raise CodexAppServerFailure("Codex app-server could not be started.") from exc
    raise CodexAppServerFailure("Codex app-server response timed out after one worker recovery.")
