from __future__ import annotations

import json
import importlib.util
import os
import re
import shutil
import sqlite3
import socket
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from auth import is_authorized
from schemas import (
    ALLOWED_ACTIONS,
    JSON_SCHEMAS,
    MISSING_TASK_HOOK,
    PLUGIN_NAME,
    PLUGIN_VERSION,
    action_result,
    dashboard_layout,
    error_payload,
    logs_panel,
    node_card,
    success,
    task_status,
    utc_now,
)


VALID_NODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"}
TERMINAL_TASK_STATUSES = {"cancelled", "completed", "failed", "succeeded", "unsupported"}
NODE_ENV_SOURCE_ENV = "HERMES_WASM_AGENT_BRIDGE_NODE_ENV_SOURCE"
NODE_ENV_RUNTIME_SOURCE_ENV = "HERMES_WASM_AGENT_BRIDGE_NODE_RUNTIME_SOURCE"
NODE_ENV_PRIMARY_ORDER = [
    "NODE_STATE",
    "NODE_STATE_FROM_BACKUP_PATH",
    "NODE_STATE_FROM_BACKUP_NODE",
    "NODE_RESEED",
    "NODE_NAME",
    "NODE_AGENT_DEFAULT_MODEL_PROVIDER",
    "NODE_AGENT_DEFAULT_MODEL",
    "NODE_AGENT_FALLBACK_MODEL_PROVIDER",
    "NODE_AGENT_FALLBACK_MODEL",
    "NODE_TIME_ZONE",
    "HERMES_EPHEMERAL_SYSTEM_PROMPT",
]
NODE_ENV_FORM_OVERRIDES = [
    "DISCORD_BOT_TOKEN",
    "DISCORD_APP_ID",
    "DISCORD_SERVER_ID",
    "DISCORD_GUILD_ID",
    "DISCORD_HOME_CHANNEL",
    "DISCORD_ALLOWED_USERS",
    "DISCORD_REQUIRE_MENTION",
    "DISCORD_REQUIRE_MENTION_CHANNELS",
    "DISCORD_FREE_RESPONSE_CHANNELS",
    "DISCORD_IGNORED_CHANNELS",
    "DISCORD_AUTO_THREAD",
    "DISCORD_AUTO_THREAD_IGNORE_CHANNELS",
    "NVIDIA_API_KEY",
    "OPENROUTER_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_GROUP_ID",
]
NODE_ENV_RUNTIME_COPY_KEYS = list(NODE_ENV_FORM_OVERRIDES)
NODE_ENV_PLACEHOLDERS = {"", "CHANGEME", "CHANGE_ME", "TODO", "NONE", "NULL"}


class BridgeError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: HTTPStatus = HTTPStatus.BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


@dataclass(frozen=True)
class BridgeSettings:
    plugin_root: Path
    repo_root: Path
    host: str
    port: int
    token: str
    horc_path: str
    agents_root: Path
    state_dir: Path
    timeout_sec: float
    space_agent_url: str
    space_agent_repo: str
    agent_root: Path
    agent_env_path: Path
    agent_python: Path
    api_server_url: str
    api_server_key: str
    api_server_timeout_sec: float
    api_server_poll_interval_sec: float

    @classmethod
    def from_env(cls, plugin_root: Path) -> "BridgeSettings":
        repo_root = Path(os.getenv("HERMES_ORCHESTRATOR_ROOT", "/local")).resolve()
        agents_root = Path(os.getenv("HERMES_AGENTS_ROOT", "/local/agents")).resolve()
        default_horc = repo_root / "scripts" / "public" / "clone" / "horc.sh"
        state_dir = Path(
            os.getenv(
                "HERMES_WASM_AGENT_BRIDGE_STATE_DIR",
                str(repo_root / "plugins" / "wasm-agent" / "state" / "bridge"),
            )
        ).resolve()
        return cls(
            plugin_root=plugin_root,
            repo_root=repo_root,
            host=str(os.getenv("HERMES_WASM_AGENT_BRIDGE_HOST", "127.0.0.1") or "127.0.0.1"),
            port=int(str(os.getenv("HERMES_WASM_AGENT_BRIDGE_PORT", "8790") or "8790")),
            token=str(os.getenv("HERMES_WASM_AGENT_BRIDGE_TOKEN", "") or "").strip(),
            horc_path=str(os.getenv("HERMES_WASM_AGENT_BRIDGE_HORC", str(default_horc)) or default_horc),
            agents_root=agents_root,
            state_dir=state_dir,
            timeout_sec=float(str(os.getenv("HERMES_WASM_AGENT_BRIDGE_TIMEOUT_SEC", "120") or "120")),
            space_agent_url="",
            space_agent_repo="",
            agent_root=Path(
                os.getenv(
                    "HERMES_WASM_AGENT_BRIDGE_AGENT_ROOT",
                    str(repo_root / "agents" / "nodes" / "orchestrator" / "hermes-agent"),
                )
            ).resolve(),
            agent_env_path=Path(
                os.getenv(
                    "HERMES_WASM_AGENT_BRIDGE_AGENT_ENV",
                    str(repo_root / "agents" / "envs" / "orchestrator.env"),
                )
            ).resolve(),
            agent_python=Path(
                os.getenv(
                    "HERMES_WASM_AGENT_BRIDGE_AGENT_PYTHON",
                    str(
                        repo_root
                        / "agents"
                        / "nodes"
                        / "orchestrator"
                        / "hermes-agent"
                        / ".venv"
                        / "bin"
                        / "python"
                    ),
                )
            ),
            api_server_url=str(os.getenv("HERMES_WASM_AGENT_BRIDGE_API_SERVER_URL", "") or "").strip(),
            api_server_key=str(os.getenv("HERMES_WASM_AGENT_BRIDGE_API_SERVER_KEY", "") or "").strip(),
            api_server_timeout_sec=float(
                str(os.getenv("HERMES_WASM_AGENT_BRIDGE_API_SERVER_TIMEOUT_SEC", "900") or "900")
            ),
            api_server_poll_interval_sec=float(
                str(os.getenv("HERMES_WASM_AGENT_BRIDGE_API_SERVER_POLL_INTERVAL_SEC", "1") or "1")
            ),
        )


class OrchestratorClient:
    """Stable boundary adapter: call horc with fixed argument vectors only."""

    def __init__(self, settings: BridgeSettings, task_store: "TaskStore") -> None:
        self.settings = settings
        self.task_store = task_store

    def _command(self) -> list[str]:
        horc = self.settings.horc_path
        path = Path(horc)
        if path.exists() and path.is_file() and not os.access(path, os.X_OK):
            return ["bash", str(path)]
        return [horc]

    def _run_horc(self, args: list[str]) -> dict[str, Any]:
        cmd = [*self._command(), *args]
        try:
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                check=False,
                timeout=self.settings.timeout_sec,
            )
        except FileNotFoundError as exc:
            raise BridgeError(
                "horc_not_found",
                "Hermes Orchestrator CLI was not found.",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
                details={"horc_path": self.settings.horc_path},
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise BridgeError(
                "horc_timeout",
                "Hermes Orchestrator CLI timed out.",
                status=HTTPStatus.GATEWAY_TIMEOUT,
                details={"args": args, "timeout_sec": self.settings.timeout_sec},
            ) from exc

        raw_stdout = (proc.stdout or "").strip()
        raw_stderr = (proc.stderr or "").strip()
        try:
            payload = json.loads(raw_stdout) if raw_stdout else {}
        except json.JSONDecodeError as exc:
            raise BridgeError(
                "horc_non_json",
                "Hermes Orchestrator CLI returned non-JSON output.",
                status=HTTPStatus.BAD_GATEWAY,
                details={"stdout": raw_stdout[:1000], "stderr": raw_stderr[:1000]},
            ) from exc

        if proc.returncode != 0 or not bool(payload.get("ok")):
            raise BridgeError(
                "horc_failed",
                str(payload.get("error") or raw_stderr or "Hermes Orchestrator command failed."),
                status=HTTPStatus.BAD_GATEWAY,
                details={"args": args, "payload": payload, "stderr": raw_stderr[:1000]},
            )
        return payload

    def list_nodes(self) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for node_id in discover_nodes(self.settings):
            try:
                cards.append(node_card(node_id, self.get_node_status(node_id)))
            except BridgeError as exc:
                cards.append(
                    {
                        "schema": "hermes.space_ui.node_card.v1",
                        "id": node_id,
                        "title": node_id,
                        "status": "unknown",
                        "running": False,
                        "runtime": {"type": "unknown", "state_mode": "unknown", "state_code": None},
                        "health": {"error": exc.code},
                        "paths": {"logs": {}},
                        "actions": [],
                        "raw": {"error": exc.message, "details": exc.details},
                    }
                )
        return cards

    def get_node_status(self, node_id: str) -> dict[str, Any]:
        node = validate_node_id(node_id)
        payload = self._run_horc(["status", node])
        activity = node_activity_snapshot(self.settings, node)
        running_task = self.task_store.latest_running_for_node(node)
        if running_task:
            activity.update(activity_from_running_task(running_task))
        payload["_space_ui_activity"] = activity
        payload["_space_ui_hermes"] = node_hermes_runtime_snapshot(self.settings, node)
        return payload

    def tail_node_logs(self, node_id: str, *, lines: int = 80) -> dict[str, Any]:
        node = validate_node_id(node_id)
        safe_lines = max(10, min(int(lines), 500))
        return self._run_horc(["logs", node, "--lines", str(safe_lines)])

    def run_node_action(self, node_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        node = validate_node_id(node_id)
        safe_action = validate_action(action)

        if safe_action == "inspect_node":
            return action_result(
                node,
                safe_action,
                accepted=True,
                result={"node": node_card(node, self.get_node_status(node))},
            )

        if safe_action == "tail_logs":
            lines = int(payload.get("lines") or 80)
            return action_result(
                node,
                safe_action,
                accepted=True,
                result={"logs": logs_panel(node, self.tail_node_logs(node, lines=lines))},
            )

        if safe_action == "open_dashboard":
            cards = self.list_nodes()
            return action_result(
                node,
                safe_action,
                accepted=True,
                result={"dashboard": dashboard_layout(cards, focused_node=node)},
            )

        if safe_action == "run_prompt":
            prompt = str(payload.get("prompt") or "").strip()
            task = self.submit_task(prompt=prompt, target_node=node, run_options=run_options_from_payload(payload))
            return action_result(node, safe_action, accepted=True, result={"task": task})

        before = node_card(node, self.get_node_status(node))
        if safe_action == "restart_node":
            command_result = self._run_horc(["restart", node])
        elif safe_action == "stop_node":
            command_result = self._run_horc(["stop", node])
        elif safe_action == "start_node":
            command_result = self._run_horc(["start", node])
        else:
            raise BridgeError("unknown_action", f"Unknown action: {safe_action}")
        after = node_card(node, self.get_node_status(node))
        return action_result(
            node,
            safe_action,
            accepted=True,
            before=before,
            after=after,
            result={"orchestrator": command_result},
        )

    def create_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        node = validate_node_id(payload.get("node_id") or payload.get("name"))
        if node == "orchestrator":
            raise BridgeError(
                "reserved_node_id",
                "Use the existing orchestrator profile instead of creating a second orchestrator node.",
                status=HTTPStatus.CONFLICT,
            )

        env_root = self.settings.agents_root / "envs"
        env_path = env_root / f"{node}.env"
        env_exists = env_path.exists()
        existing_env = load_env_file(env_path) if env_exists else {}
        existing_status: dict[str, Any] | None = None
        if env_exists:
            if not is_space_ui_generated_env(env_path, node):
                raise BridgeError(
                    "node_env_exists",
                    "A node env profile already exists for this id.",
                    status=HTTPStatus.CONFLICT,
                    details={"node_id": node, "env_path": str(env_path)},
                )
            try:
                existing_status = self.get_node_status(node)
            except BridgeError as exc:
                raise BridgeError(
                    "node_env_exists",
                    "A generated node env profile already exists, but its status could not be verified.",
                    status=HTTPStatus.CONFLICT,
                    details={
                        "node_id": node,
                        "env_path": str(env_path),
                        "cause": {"code": exc.code, "message": exc.message, "details": exc.details},
                    },
                ) from exc
            if not is_resumable_space_ui_draft(existing_status):
                raise BridgeError(
                    "node_env_exists",
                    "A generated node env profile already exists and is not a resumable Add Node draft.",
                    status=HTTPStatus.CONFLICT,
                    details={"node_id": node, "env_path": str(env_path), "status": node_card(node, existing_status)},
                )

        state_code = normalize_node_state(
            payload.get("node_state") or payload.get("NODE_STATE") or existing_env.get("NODE_STATE")
        )
        if state_code == "1":
            raise BridgeError(
                "invalid_node_state",
                "Add Node creates worker nodes; use NODE_STATE 2, 3, or 4.",
                details={"node_id": node, "node_state": state_code},
            )

        backup_path = str(
            payload.get("node_state_from_backup_path")
            or payload.get("NODE_STATE_FROM_BACKUP_PATH")
            or ""
        ).strip()
        if state_code == "3" and not backup_path:
            raise BridgeError(
                "missing_backup_path",
                "NODE_STATE=3 requires NODE_STATE_FROM_BACKUP_PATH.",
            )

        base_env, base_env_path = load_node_env_source(self.settings, payload, node)
        base_node = base_env_path.stem if base_env_path.name.endswith(".env") else ""
        env = {
            key: retarget_node_env_value(value, base_node, node)
            for key, value in base_env.items()
            if key and key != "NODE_STATE_FROM_BACKUP_NODE"
        }
        env.update({key: value for key, value in existing_env.items() if key and key != "NODE_STATE_FROM_BACKUP_NODE"})

        default_provider = (
            optional_text(payload, "default_model_provider", "NODE_AGENT_DEFAULT_MODEL_PROVIDER")
            or env.get("NODE_AGENT_DEFAULT_MODEL_PROVIDER")
            or ""
        )
        default_model = (
            optional_text(payload, "default_model", "NODE_AGENT_DEFAULT_MODEL")
            or env.get("NODE_AGENT_DEFAULT_MODEL")
            or ""
        )
        if not default_provider:
            raise BridgeError(
                "missing_required_field",
                "Missing required field: default_model_provider.",
                details={"accepted_keys": ["default_model_provider", "NODE_AGENT_DEFAULT_MODEL_PROVIDER"]},
            )
        if not default_model:
            raise BridgeError(
                "missing_required_field",
                "Missing required field: default_model.",
                details={"accepted_keys": ["default_model", "NODE_AGENT_DEFAULT_MODEL"]},
            )

        fallback_provider = optional_text(
            payload,
            "fallback_model_provider",
            "NODE_AGENT_FALLBACK_MODEL_PROVIDER",
        )
        fallback_model = optional_text(payload, "fallback_model", "NODE_AGENT_FALLBACK_MODEL")
        time_zone = optional_text(payload, "time_zone", "NODE_TIME_ZONE") or env.get("NODE_TIME_ZONE") or "UTC"
        personality = optional_text(payload, "personality", "role", "HERMES_EPHEMERAL_SYSTEM_PROMPT")
        start_immediately = coerce_bool(payload.get("start_immediately", True), default=True)

        env["NODE_STATE"] = state_code
        env["NODE_NAME"] = node
        env["NODE_RESEED"] = str(env.get("NODE_RESEED") or "false")
        env["NODE_AGENT_DEFAULT_MODEL_PROVIDER"] = default_provider
        env["NODE_AGENT_DEFAULT_MODEL"] = default_model
        env["NODE_TIME_ZONE"] = time_zone
        if state_code == "3":
            env["NODE_STATE_FROM_BACKUP_PATH"] = backup_path
        elif backup_path:
            env["NODE_STATE_FROM_BACKUP_PATH"] = backup_path
        else:
            env["NODE_STATE_FROM_BACKUP_PATH"] = ""
        if fallback_provider:
            env["NODE_AGENT_FALLBACK_MODEL_PROVIDER"] = fallback_provider
        if fallback_model:
            env["NODE_AGENT_FALLBACK_MODEL"] = fallback_model
        if personality:
            env["HERMES_EPHEMERAL_SYSTEM_PROMPT"] = personality
        for key in NODE_ENV_FORM_OVERRIDES:
            value = optional_text(payload, key.lower(), key)
            if value:
                env[key] = value

        runtime_fill: dict[str, Any] = {}
        if start_immediately:
            runtime_fill = hydrate_node_runtime_values(
                self.settings,
                payload,
                node,
                env,
                base_env_path,
            )
            ensure_node_env_can_start(node, env, base_env_path)

        text = render_node_env(node, env)
        env_root.mkdir(parents=True, exist_ok=True)
        if env_exists:
            env_path.write_text(text, encoding="utf-8")
            try:
                env_path.chmod(0o600)
            except Exception:
                pass
        else:
            try:
                fd = os.open(str(env_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError as exc:
                raise BridgeError(
                    "node_env_exists",
                    "A node env profile already exists for this id.",
                    status=HTTPStatus.CONFLICT,
                    details={"node_id": node, "env_path": str(env_path)},
                ) from exc
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text)
            except Exception:
                try:
                    env_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise

        start_result: dict[str, Any] = {
            "requested": start_immediately,
            "ok": False,
            "skipped": not start_immediately,
        }
        status_card: dict[str, Any] | None = None
        if start_immediately:
            start_payload: dict[str, Any] | None = None
            try:
                start_payload = self._run_horc(["start", node])
                status_card = node_card(node, self.get_node_status(node))
                if not bool(status_card.get("running")):
                    raise BridgeError(
                        "node_start_not_running",
                        "Node start completed but the node is not running.",
                        status=HTTPStatus.BAD_GATEWAY,
                        details={"node_id": node, "status": status_card},
                    )
                start_result = {
                    "requested": True,
                    "ok": True,
                    "verified_running": True,
                    "result": start_payload,
                }
            except BridgeError as exc:
                env_removed = False
                if start_payload is None and not env_exists:
                    try:
                        env_path.unlink(missing_ok=True)
                        env_removed = True
                    except Exception:
                        env_removed = False
                raise BridgeError(
                    "node_start_failed",
                    "Node profile was created, but the node did not start successfully.",
                    status=exc.status,
                    details={
                        "node_id": node,
                        "env_path": str(env_path),
                        "env_removed": env_removed,
                        "cause": {"code": exc.code, "message": exc.message, "details": exc.details},
                    },
                ) from exc
        else:
            try:
                status_card = node_card(node, self.get_node_status(node))
            except BridgeError:
                status_card = None

        return {
            "schema": "hermes.space_ui.node_create_result.v1",
            "node_id": node,
            "env_path": str(env_path),
            "env_source_path": str(base_env_path),
            "env_created": not env_exists,
            "env_updated": env_exists,
            "runtime_fill": runtime_fill,
            "start": start_result,
            "node": status_card,
        }

    def node_stats(self, node_id: str, *, days: int = 30, bucket: str = "daily") -> dict[str, Any]:
        node = validate_node_id(node_id)
        safe_bucket = normalize_bucket(bucket)
        safe_days = stats_window_days(safe_bucket)
        raw_status: dict[str, Any] = {}
        status_card: dict[str, Any] | None = None
        try:
            raw_status = self.get_node_status(node)
            status_card = node_card(node, raw_status)
        except BridgeError as exc:
            status_card = {
                "schema": "hermes.space_ui.node_card.v1",
                "id": node,
                "title": node,
                "status": "unknown",
                "running": False,
                "runtime": {"type": "unknown", "state_mode": "unknown", "state_code": None},
                "health": {"error": exc.code},
                "paths": {"logs": {}},
                "actions": [],
                "raw": {"error": exc.message, "details": exc.details},
            }
        usage = read_node_usage_stats(self.settings, node, days=safe_days, bucket=safe_bucket)
        activity = read_node_activity_stats(self.settings, node, days=safe_days, bucket=safe_bucket)
        logs = read_node_log_stats(raw_status)
        return {
            "schema": "hermes.space_ui.node_stats.v1",
            "node_id": node,
            "timestamp": utc_now(),
            "window": {
                "days": safe_days,
                "bucket": safe_bucket,
                "points": stats_window_points(safe_bucket),
                "requested_days": max(1, min(int(days), 366)),
            },
            "status": status_card,
            "usage": usage,
            "activity": activity,
            "logs": logs,
        }

    def submit_task(
        self,
        *,
        prompt: str,
        target_node: str | None,
        run_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt_text = str(prompt or "").strip()
        if not prompt_text:
            raise BridgeError("invalid_prompt", "Prompt must not be empty.")
        node = validate_node_id(target_node) if target_node else None
        if not node:
            raise BridgeError("invalid_node_id", "target_node is required for prompt submission.")
        prepared_prompt = self._prepare_prompt_for_node(prompt_text, node)
        task = self.task_store.create_running(prepared_prompt, node)
        return self._finish_prompt_task(task["task_id"], node, prepared_prompt, run_options)

    def start_task(
        self,
        *,
        prompt: str,
        target_node: str | None,
        run_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt_text = str(prompt or "").strip()
        if not prompt_text:
            raise BridgeError("invalid_prompt", "Prompt must not be empty.")
        node = validate_node_id(target_node) if target_node else None
        if not node:
            raise BridgeError("invalid_node_id", "target_node is required for prompt submission.")
        prepared_prompt = self._prepare_prompt_for_node(prompt_text, node)
        task = self.task_store.create_running(prepared_prompt, node)
        thread = threading.Thread(
            target=self._finish_prompt_task,
            args=(task["task_id"], node, prepared_prompt, run_options),
            daemon=True,
            name=f"prompt-task-{task['task_id'][-6:]}",
        )
        thread.start()
        return task

    def _prepare_prompt_for_node(self, prompt: str, node: str) -> str:
        return rewrite_exhaust_slash_prompt(
            prompt,
            node=node,
            agents_root=self.settings.agents_root,
        )

    def _finish_prompt_task(
        self,
        task_id: str,
        node: str,
        prompt_text: str,
        run_options: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            response = self._run_node_api_server(
                node,
                prompt_text,
                run_options=run_options,
                task_id=task_id,
            )
        except BridgeError as exc:
            current = self.task_store.get(task_id) or {}
            if current.get("status") == "cancelled":
                return current
            current_result = current.get("result") if isinstance(current.get("result"), dict) else {}
            cancel_requested = bool(current_result.get("cancel_requested"))
            status = "cancelled" if cancel_requested or exc.code == "api_server_run_cancelled" else "failed"
            error = (
                {"code": "task_cancelled", "message": "Task cancelled from wasm-agent bridge.", "details": current_result}
                if status == "cancelled"
                else {"code": exc.code, "message": exc.message, "details": exc.details}
            )
            return self.task_store.finish(
                task_id,
                status=status,
                result=current_result,
                error=error,
            )
        except Exception as exc:
            current = self.task_store.get(task_id) or {}
            if current.get("status") == "cancelled":
                return current
            current_result = current.get("result") if isinstance(current.get("result"), dict) else {}
            return self.task_store.finish(
                task_id,
                status="failed",
                result=current_result,
                error={"code": "prompt_task_failed", "message": str(exc), "details": {}},
            )
        current = self.task_store.get(task_id) or {}
        if current.get("status") == "cancelled":
            return current
        current_result = current.get("result") if isinstance(current.get("result"), dict) else {}
        result: dict[str, Any] = {**current_result, "response": response, "node_id": node}
        if run_options:
            result["run_options"] = run_options
        return self.task_store.finish(task_id, status="completed", result=result)

    def stop_task(self, task_id: str, *, reason: str = "Stop requested from wasm-agent bridge.") -> dict[str, Any]:
        task = self.task_store.get(str(task_id or ""))
        if not task:
            raise BridgeError("task_not_found", "Task was not found.", status=HTTPStatus.NOT_FOUND)
        if str(task.get("status") or "") in TERMINAL_TASK_STATUSES:
            return task

        requested = self.task_store.request_cancel(str(task["task_id"]), reason=reason)
        task = requested or task
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        run_id = str(result.get("run_id") or "").strip()
        node = validate_node_id(task.get("target_node")) if task.get("target_node") else ""
        if not node or not run_id:
            return task

        try:
            stop_status = self._stop_node_run(node, run_id)
        except BridgeError as exc:
            updated = self.task_store.update_running(
                str(task["task_id"]),
                result={
                    "cancel_requested": True,
                    "cancel_reason": reason,
                    "run_status": "stop_failed",
                    "stop_status": {"error": exc.code, "message": exc.message, "details": exc.details},
                },
            )
            return updated or self.task_store.get(str(task["task_id"])) or task

        return self.task_store.finish(
            str(task["task_id"]),
            status="cancelled",
            result={
                "cancel_requested": True,
                "cancel_reason": reason,
                "run_status": "cancelled",
                "stop_status": stop_status,
            },
            error={"code": "task_cancelled", "message": "Task cancelled from wasm-agent bridge.", "details": {}},
        )

    def start_drop_to_copy_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        repo_url = str(payload.get("repo_url") or "").strip()
        legacy_wish = str(payload.get("wish") or "").strip()
        app_name = str(
            payload.get("app_name")
            or payload.get("appName")
            or payload.get("name")
            or payload.get("title")
            or ""
        ).strip()
        instructions = str(payload.get("instructions") or legacy_wish).strip()
        if not app_name and legacy_wish and not payload.get("instructions"):
            app_name = "Generated Widget"
        dropped_text = str(payload.get("dropped_text") or "").strip()
        space_id = str(payload.get("space_id") or "hermes-os").strip() or "hermes-os"
        build_widget_id = str(payload.get("build_widget_id") or "").strip()
        target_node = str(
            payload.get("target_node")
            or os.getenv("HERMES_WASM_AGENT_BRIDGE_DROP_TO_COPY_NODE", "orchestrator")
            or "orchestrator"
        ).strip()
        node = validate_node_id(target_node)
        if not repo_url and not dropped_text:
            raise BridgeError("missing_drop_source", "Provide a GitHub repo URL or dropped input.")
        if not app_name:
            raise BridgeError("missing_drop_app_name", "Provide the app name to create.")
        if not instructions:
            raise BridgeError("missing_drop_instructions", "Describe the app you want to build.")

        prompt = build_drop_to_copy_prompt(
            repo_url=repo_url,
            app_name=app_name,
            instructions=instructions,
            dropped_text=dropped_text[:50000],
            space_id=space_id,
            build_widget_id=build_widget_id,
        )
        task = self.task_store.create_running(prompt, node)
        thread = threading.Thread(
            target=self._run_drop_to_copy_task,
            args=(task["task_id"], node, prompt),
            daemon=True,
            name=f"drop-to-copy-{task['task_id'][-6:]}",
        )
        thread.start()
        return task

    def _run_drop_to_copy_task(self, task_id: str, node: str, prompt: str) -> None:
        try:
            response = self._run_node_api_server(
                node,
                prompt,
                run_options=self._drop_to_copy_run_options(),
                task_id=task_id,
            )
        except BridgeError as exc:
            self.task_store.finish(
                task_id,
                status="failed",
                error={"code": exc.code, "message": exc.message, "details": exc.details},
            )
            return
        except Exception as exc:
            self.task_store.finish(
                task_id,
                status="failed",
                error={"code": "drop_to_copy_failed", "message": str(exc), "details": {}},
            )
            return
        self.task_store.finish(
            task_id,
            status="completed",
            result={
                "response": response,
                "node_id": node,
                "model_request": {
                    "model": os.getenv("HERMES_WASM_AGENT_BRIDGE_DROP_TO_COPY_MODEL", "gpt-5.5"),
                    "reasoning_effort": os.getenv("HERMES_WASM_AGENT_BRIDGE_DROP_TO_COPY_REASONING_EFFORT", "xhigh"),
                },
            },
        )

    def _drop_to_copy_run_options(self) -> dict[str, Any]:
        model = str(os.getenv("HERMES_WASM_AGENT_BRIDGE_DROP_TO_COPY_MODEL", "gpt-5.5") or "gpt-5.5").strip()
        reasoning_effort = str(
            os.getenv("HERMES_WASM_AGENT_BRIDGE_DROP_TO_COPY_REASONING_EFFORT", "xhigh")
            or "xhigh"
        ).strip()
        provider = str(os.getenv("HERMES_WASM_AGENT_BRIDGE_DROP_TO_COPY_PROVIDER", "openai-codex") or "openai-codex").strip()
        return {
            "provider": provider,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "reasoning": {"effort": reasoning_effort},
            "timeout_sec": float(
                str(os.getenv("HERMES_WASM_AGENT_BRIDGE_DROP_TO_COPY_TIMEOUT_SEC", "900") or "900")
            ),
            "metadata": {
                "hermes_space_ui": "drop_to_copy",
                "requested_provider": provider,
                "requested_model": model,
                "requested_reasoning_effort": reasoning_effort,
            },
            "instructions": (
                "You are the Hermes Drop to Copy frontier builder. Use the requested "
                f"frontier model {model} with reasoning effort {reasoning_effort} when "
                "the active Hermes Runs API/runtime supports per-run model selection. "
                "If the runtime cannot enforce that selection, say so briefly in the "
                "final notes and continue using the best available official Hermes Agent path."
            ),
        }

    def _api_server_url_for_node(self, node_id: str) -> str:
        node = validate_node_id(node_id)
        settings = self.settings
        env_key = f"HERMES_WASM_AGENT_BRIDGE_API_SERVER_{node.upper().replace('-', '_')}_URL"
        explicit = str(os.getenv(env_key, "") or "").strip()
        if explicit:
            return explicit.rstrip("/")
        if settings.api_server_url:
            return settings.api_server_url.rstrip("/")

        env = load_env_file(settings.agents_root / "envs" / f"{node}.env")
        port = str(env.get("API_SERVER_PORT") or "").strip()
        host = str(env.get("API_SERVER_HOST") or "127.0.0.1").strip() or "127.0.0.1"
        if port:
            return f"http://{host}:{port}".rstrip("/")
        if node == "orchestrator":
            return "http://127.0.0.1:8642"
        raise BridgeError(
            "api_server_url_not_configured",
            "No official Hermes API server URL is configured for this node.",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            details={
                "node_id": node,
                "env": env_key,
                "fallback_env": "HERMES_WASM_AGENT_BRIDGE_API_SERVER_URL",
            },
        )

    def _api_server_key_for_node(self, node_id: str) -> str:
        node = validate_node_id(node_id)
        env_key = f"HERMES_WASM_AGENT_BRIDGE_API_SERVER_{node.upper().replace('-', '_')}_KEY"
        explicit = str(os.getenv(env_key, "") or "").strip()
        if explicit:
            return explicit
        if self.settings.api_server_key:
            return self.settings.api_server_key
        env = load_env_file(self.settings.agents_root / "envs" / f"{node}.env")
        return str(env.get("API_SERVER_KEY") or "").strip()

    def _capabilities_advertise_runs_api(self, capabilities: dict[str, Any]) -> bool:
        """Accept both current and legacy Hermes Runs API capability shapes."""
        features = capabilities.get("features") if isinstance(capabilities.get("features"), dict) else {}
        endpoints = capabilities.get("endpoints") if isinstance(capabilities.get("endpoints"), dict) else {}

        if bool(features.get("runs")):
            return True
        if bool(features.get("run_submission")) and bool(features.get("run_status")):
            return True

        run_create = endpoints.get("runs") or endpoints.get("run_create")
        run_status = endpoints.get("run_status")
        return bool(run_create and run_status)

    def _api_request(
        self,
        node_id: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        base_url = self._api_server_url_for_node(node_id)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        key = self._api_server_key_for_node(node_id)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request = Request(f"{base_url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout or self.settings.api_server_timeout_sec) as response:
                text = response.read().decode("utf-8")
        except HTTPError as exc:
            details: dict[str, Any] = {"node_id": node_id, "status": exc.code, "url": f"{base_url}{path}"}
            try:
                details["body"] = exc.read().decode("utf-8")[:2000]
            except Exception:
                pass
            raise BridgeError(
                "api_server_http_error",
                "Hermes API server rejected the request.",
                status=HTTPStatus.BAD_GATEWAY,
                details=details,
            ) from exc
        except URLError as exc:
            raise BridgeError(
                "api_server_unreachable",
                "Hermes API server is not reachable for this node.",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
                details={"node_id": node_id, "url": base_url, "error": str(exc.reason)},
            ) from exc
        except TimeoutError as exc:
            raise BridgeError(
                "api_server_timeout",
                "Hermes API server did not respond before the bridge timeout.",
                status=HTTPStatus.GATEWAY_TIMEOUT,
                details={"node_id": node_id, "url": base_url},
            ) from exc

        try:
            return json.loads(text) if text.strip() else {}
        except json.JSONDecodeError as exc:
            raise BridgeError(
                "api_server_non_json",
                "Hermes API server returned non-JSON output.",
                status=HTTPStatus.BAD_GATEWAY,
                details={"node_id": node_id, "url": base_url, "body": text[:2000]},
            ) from exc

    def _api_event_stream(self, node_id: str, path: str):
        node = validate_node_id(node_id)
        base_url = self._api_server_url_for_node(node)
        headers = {"Accept": "text/event-stream"}
        key = self._api_server_key_for_node(node)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request = Request(f"{base_url}{path}", headers=headers, method="GET")
        try:
            with urlopen(request, timeout=45) as response:
                data_lines: list[str] = []
                event_type = ""
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                        continue
                    if line.strip():
                        continue
                    if not data_lines:
                        continue
                    payload = "\n".join(data_lines).strip()
                    data_lines = []
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        if event_type:
                            yield {
                                "event": event_type,
                                "timestamp": time.time(),
                                "delta": payload,
                                "text": payload,
                            }
                        event_type = ""
                        continue
                    if isinstance(event, dict):
                        if event_type and not event.get("event") and not event.get("type"):
                            event["event"] = event_type
                        yield event
                    event_type = ""
        except HTTPError as exc:
            details: dict[str, Any] = {"node_id": node, "status": exc.code, "url": f"{base_url}{path}"}
            try:
                details["body"] = exc.read().decode("utf-8")[:2000]
            except Exception:
                pass
            raise BridgeError(
                "api_server_events_http_error",
                "Hermes API server rejected the run event stream request.",
                status=HTTPStatus.BAD_GATEWAY,
                details=details,
            ) from exc
        except URLError as exc:
            raise BridgeError(
                "api_server_events_unreachable",
                "Hermes API server run events are not reachable for this node.",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
                details={"node_id": node, "url": base_url, "error": str(exc.reason)},
            ) from exc
        except TimeoutError as exc:
            raise BridgeError(
                "api_server_events_timeout",
                "Hermes API server run event stream timed out.",
                status=HTTPStatus.GATEWAY_TIMEOUT,
                details={"node_id": node, "url": base_url},
            ) from exc

    def _collect_run_events(self, node: str, run_id: str, task_id: str) -> None:
        try:
            events = self._api_event_stream(node, f"/v1/runs/{run_id}/events")
            for event in events:
                self.task_store.record_event(task_id, event)
        except BridgeError as exc:
            self.task_store.record_event(
                task_id,
                {
                    "event": "run.events_unavailable",
                    "timestamp": time.time(),
                    "error": exc.code,
                    "message": exc.message,
                },
            )
            return
        except Exception as exc:
            self.task_store.record_event(
                task_id,
                {
                    "event": "run.events_unavailable",
                    "timestamp": time.time(),
                    "error": "run_events_failed",
                    "message": str(exc),
                },
            )
            return

    def _start_run_event_collector(self, node: str, run_id: str, task_id: str) -> None:
        thread = threading.Thread(
            target=self._collect_run_events,
            args=(node, run_id, task_id),
            daemon=True,
            name=f"run-events-{task_id[-6:]}",
        )
        thread.start()

    def _stop_node_run(self, node: str, run_id: str) -> dict[str, Any]:
        return self._api_request(
            node,
            "POST",
            f"/v1/runs/{run_id}/stop",
            timeout=5,
        )

    def _raise_if_task_cancelled(self, task_id: str | None, node: str, run_id: str) -> None:
        if not task_id or not self.task_store.cancel_requested(task_id):
            return
        stop_status: dict[str, Any] | None = None
        try:
            stop_status = self._stop_node_run(node, run_id)
        except BridgeError as exc:
            stop_status = {"error": exc.code, "message": exc.message, "details": exc.details}
        self.task_store.update_running(
            task_id,
            result={
                "cancel_requested": True,
                "run_status": "stopping",
                "stop_status": stop_status,
            },
        )
        raise BridgeError(
            "api_server_run_cancelled",
            "Hermes API server run was cancelled from wasm-agent bridge.",
            status=HTTPStatus.CONFLICT,
            details={"node_id": node, "run_id": run_id, "stop_status": stop_status},
        )

    def _run_node_api_server(
        self,
        node_id: str,
        prompt: str,
        *,
        run_options: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> str:
        node = validate_node_id(node_id)
        try:
            capabilities = self._api_request(node, "GET", "/v1/capabilities", timeout=5)
        except BridgeError as exc:
            if exc.code not in {"api_server_http_error"}:
                raise
            capabilities = {}
        if capabilities and not self._capabilities_advertise_runs_api(capabilities):
            raise BridgeError(
                "api_server_runs_unsupported",
                "Hermes API server does not advertise Runs API support.",
                status=HTTPStatus.BAD_GATEWAY,
                details={"node_id": node, "capabilities": capabilities},
            )

        session_id = f"space-ui-{node}-{uuid.uuid4().hex[:12]}"
        run_payload = {"input": prompt, "session_id": session_id}
        if run_options:
            run_payload.update(
                {
                    key: value
                    for key, value in run_options.items()
                    if key not in {"timeout", "timeout_sec"}
                }
            )

        created = self._api_request(
            node,
            "POST",
            "/v1/runs",
            payload=run_payload,
        )
        run_id = str(created.get("run_id") or created.get("id") or "").strip()
        if not run_id:
            raise BridgeError(
                "api_server_missing_run_id",
                "Hermes API server did not return a run_id.",
                status=HTTPStatus.BAD_GATEWAY,
                details={"node_id": node, "response": created},
            )
        if task_id:
            created_usage = token_usage_from_payload(created)
            initial_result: dict[str, Any] = {
                "node_id": node,
                "run_id": run_id,
                "session_id": session_id,
                "model_request": run_payload.get("model"),
                "run_status": "running",
            }
            if usage_has_signal(created_usage):
                initial_result["token_usage"] = created_usage
            self.task_store.update_running(
                task_id,
                result=initial_result,
            )
            self._start_run_event_collector(node, run_id, task_id)
            self._raise_if_task_cancelled(task_id, node, run_id)

        deadline = time.monotonic() + run_timeout_sec(run_options, self.settings.api_server_timeout_sec)
        last_status: dict[str, Any] = created
        while time.monotonic() < deadline:
            self._raise_if_task_cancelled(task_id, node, run_id)
            status = self._api_request(node, "GET", f"/v1/runs/{run_id}", timeout=10)
            last_status = status
            state = str(status.get("status") or "").lower()
            if task_id:
                status_usage = token_usage_from_payload(status)
                running_result: dict[str, Any] = {
                    "node_id": node,
                    "run_id": run_id,
                    "session_id": session_id,
                    "model_request": run_payload.get("model"),
                    "run_status": state or "running",
                    "last_event": status.get("last_event"),
                }
                if usage_has_signal(status_usage):
                    running_result["token_usage"] = status_usage
                self.task_store.update_running(
                    task_id,
                    result=running_result,
                )
                self.task_store.record_status_event(task_id, status)
            if state == "completed":
                output = status.get("output") or status.get("result") or status.get("final_response")
                if isinstance(output, dict):
                    output = output.get("text") or output.get("content") or json.dumps(output)
                return str(output or "").strip()
            if state in {"failed", "cancelled"}:
                raise BridgeError(
                    f"api_server_run_{state}",
                    f"Hermes API server run {state}.",
                    status=HTTPStatus.BAD_GATEWAY,
                    details={"node_id": node, "run_id": run_id, "status": status},
                )
            time.sleep(max(0.1, self.settings.api_server_poll_interval_sec))

        stop_status: dict[str, Any] | None = None
        try:
            stop_status = self._api_request(node, "POST", f"/v1/runs/{run_id}/stop", timeout=5)
        except BridgeError as exc:
            stop_status = {"error": exc.code, "message": exc.message}
        if task_id:
            last_usage = token_usage_from_payload(last_status)
            timeout_result: dict[str, Any] = {
                "node_id": node,
                "run_id": run_id,
                "session_id": session_id,
                "model_request": run_payload.get("model"),
                "run_status": "timeout",
                "last_event": last_status.get("last_event"),
            }
            if usage_has_signal(last_usage):
                timeout_result["token_usage"] = last_usage
            self.task_store.update_running(
                task_id,
                result=timeout_result,
            )
        raise BridgeError(
            "api_server_run_timeout",
            "Hermes API server run did not complete before the bridge timeout.",
            status=HTTPStatus.GATEWAY_TIMEOUT,
            details={
                "node_id": node,
                "run_id": run_id,
                "last_status": last_status,
                "stop_status": stop_status,
            },
        )

    def run_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        node = str(payload.get("target_node") or os.getenv("HERMES_WASM_AGENT_BRIDGE_DEFAULT_API_NODE", "orchestrator"))
        forwarded = dict(payload)
        forwarded["stream"] = False
        completion = self._api_request(node, "POST", "/v1/chat/completions", payload=forwarded)
        choices = completion.get("choices") if isinstance(completion.get("choices"), list) else []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            if "content" in message:
                message["content"] = sanitize_space_agent_response(str(message.get("content") or ""))
        return completion


def compact_run_event(event: dict[str, Any]) -> dict[str, Any]:
    nested: dict[str, Any] = {}
    for nested_key in ("payload", "data"):
        value = event.get(nested_key)
        if isinstance(value, dict):
            nested.update(value)
    merged = {**nested, **event}

    def text_field(key: str, limit: int) -> str:
        value = str(merged.get(key) or "")
        return value[:limit]

    name = str(merged.get("event") or merged.get("type") or merged.get("event_type") or "run.event").strip() or "run.event"
    payload: dict[str, Any] = {
        "event": name,
        "timestamp": merged.get("timestamp") or time.time(),
        "received_at": utc_now(),
    }

    tool_value = (
        merged.get("tool")
        or merged.get("tool_name")
        or merged.get("name")
        or merged.get("function_name")
    )
    if tool_value:
        payload["tool"] = str(tool_value).strip()[:200]

    call_id = (
        merged.get("tool_call_id")
        or merged.get("toolCallId")
        or merged.get("call_id")
        or merged.get("callId")
    )
    if call_id:
        payload["tool_call_id"] = str(call_id).strip()[:200]

    for key in ("run_id", "status", "state", "source", "sequence"):
        value = str(merged.get(key) or "").strip()
        if value:
            payload["status" if key == "state" else key] = value[:200]

    args = merged.get("args")
    if args is None:
        args = merged.get("arguments")
    if args is None:
        args = merged.get("arguments_preview")
    if isinstance(args, str):
        try:
            parsed_args = json.loads(args)
            args = parsed_args if isinstance(parsed_args, dict) else {"value": args}
        except json.JSONDecodeError:
            args = {"value": args}
    if isinstance(args, dict):
        compact_args: dict[str, Any] = {}
        for key, value in list(args.items())[:24]:
            if isinstance(value, (str, int, float, bool)) or value is None:
                compact_args[str(key)[:80]] = str(value)[:2000] if isinstance(value, str) else value
            elif isinstance(value, (list, dict)):
                compact_args[str(key)[:80]] = json.dumps(value, ensure_ascii=False, default=str)[:2000]
            else:
                compact_args[str(key)[:80]] = str(value)[:2000]
        if compact_args:
            payload["args"] = compact_args

    command = (
        merged.get("command")
        or (args.get("command") if isinstance(args, dict) else None)
        or (args.get("cmd") if isinstance(args, dict) else None)
    )
    if command:
        payload["command"] = str(command)[:4000]

    text_aliases = {
        "preview": ("preview", "summary", "label"),
        "text": ("text", "thinking", "reasoning", "content"),
        "delta": ("delta", "content_delta", "text_delta"),
        "output": ("output", "stdout", "stderr", "result", "result_preview"),
        "message": ("message", "detail", "details"),
        "error": ("error", "exception"),
    }
    limits = {
        "preview": 500,
        "text": 4000,
        "delta": 4000,
        "output": 4000,
        "message": 1000,
        "error": 1000,
    }
    for target, aliases in text_aliases.items():
        if target in payload and isinstance(payload.get(target), bool):
            continue
        for alias in aliases:
            value = text_field(alias, limits[target])
            if value:
                payload[target] = value
                break

    if not payload.get("preview") and command:
        payload["preview"] = str(command)[:500]

    for key, limit in (
        ("preview", 500),
        ("text", 4000),
        ("delta", 4000),
        ("output", 4000),
        ("message", 1000),
        ("error", 1000),
    ):
        value = str(payload.get(key) or "")[:limit]
        if value and not isinstance(payload.get(key), bool):
            payload[key] = value
    if "duration" in merged or "elapsed" in merged:
        try:
            payload["duration"] = round(float(merged.get("duration") or merged.get("elapsed") or 0), 3)
        except (TypeError, ValueError):
            pass
    usage = token_usage_from_payload(merged)
    if usage_has_signal(usage):
        payload["usage"] = usage
    if "error" in merged and isinstance(merged.get("error"), bool):
        payload["error"] = bool(merged.get("error"))
    return payload


class TaskStore:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.path = state_dir / "tasks.json"
        self._lock = threading.RLock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    self._tasks = {
                        str(key): value
                        for key, value in payload.items()
                        if isinstance(value, dict)
                    }
        except Exception:
            self._tasks = {}

    def _save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._tasks, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def create_unsupported(self, prompt: str, target_node: str | None) -> dict[str, Any]:
        now = utc_now()
        task_id = f"space-ui-{uuid.uuid4().hex[:12]}"
        task = task_status(
            task_id,
            prompt=prompt,
            target_node=target_node,
            status="unsupported",
            created_at=now,
            updated_at=now,
            error=MISSING_TASK_HOOK,
        )
        with self._lock:
            self._tasks[task_id] = task
            self._save()
        return task

    def create_running(self, prompt: str, target_node: str | None) -> dict[str, Any]:
        now = utc_now()
        task_id = f"space-ui-{uuid.uuid4().hex[:12]}"
        task = task_status(
            task_id,
            prompt=prompt,
            target_node=target_node,
            status="running",
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._tasks[task_id] = task
            self._save()
        return task

    def finish(
        self,
        task_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            existing = self._tasks.get(task_id)
            if not existing:
                raise BridgeError("task_not_found", "Task was not found.", status=HTTPStatus.NOT_FOUND)
            existing_result = existing.get("result") if isinstance(existing.get("result"), dict) else {}
            task = {
                **existing,
                "status": status,
                "updated_at": utc_now(),
                "result": {**existing_result, **(result or {})},
                "error": error,
            }
            self._tasks[task_id] = task
            self._save()
        return task

    def update_running(self, task_id: str, *, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self._lock:
            existing = self._tasks.get(task_id)
            if not existing or existing.get("status") != "running":
                return existing
            existing_result = existing.get("result") if isinstance(existing.get("result"), dict) else {}
            merged_result = {
                **existing_result,
                **(result or {}),
            }
            incoming_usage = None
            if isinstance(result, dict):
                incoming_usage = result.get("token_usage") or result.get("usage")
            if usage_has_signal(token_usage_from_payload(incoming_usage)):
                merged_result["token_usage"] = merge_token_usage(
                    token_usage_from_payload(existing_result.get("token_usage")),
                    token_usage_from_payload(incoming_usage),
                )
            task = {
                **existing,
                "updated_at": utc_now(),
                "result": merged_result,
            }
            self._tasks[task_id] = task
            self._save()
            return task

    def request_cancel(self, task_id: str, *, reason: str) -> dict[str, Any] | None:
        return self.update_running(
            task_id,
            result={
                "cancel_requested": True,
                "cancel_reason": str(reason or "Stop requested from wasm-agent bridge.")[:500],
                "cancel_requested_at": utc_now(),
                "run_status": "stopping",
            },
        )

    def cancel_requested(self, task_id: str) -> bool:
        with self._lock:
            existing = self._tasks.get(task_id)
            result = existing.get("result") if isinstance(existing, dict) and isinstance(existing.get("result"), dict) else {}
        return bool(result.get("cancel_requested"))

    def record_status_event(self, task_id: str, status: dict[str, Any]) -> dict[str, Any] | None:
        event_name = str(status.get("last_event") or "").strip()
        run_id = str(status.get("run_id") or status.get("id") or "").strip()
        run_status = str(status.get("status") or "").strip()
        usage = token_usage_from_payload(status)
        if not event_name and not usage_has_signal(usage):
            return None
        marker = f"{run_id}:{event_name}:{run_status}:{usage.get('total_tokens') or 0}"
        with self._lock:
            existing = self._tasks.get(task_id)
            result = existing.get("result") if isinstance(existing, dict) and isinstance(existing.get("result"), dict) else {}
            if result.get("status_event_marker") == marker:
                return existing
            if existing and existing.get("status") == "running":
                result = dict(result)
                result["status_event_marker"] = marker
                self._tasks[task_id] = {**existing, "result": result}
        return self.record_event(
            task_id,
            {
                "event": event_name or "run.status",
                "run_id": run_id,
                "status": run_status,
                "source": "run_status",
                "timestamp": status.get("updated_at") or time.time(),
                "usage": usage,
            },
        )

    def record_event(self, task_id: str, event: dict[str, Any]) -> dict[str, Any] | None:
        compact = compact_run_event(event if isinstance(event, dict) else {})
        event_name = str(compact.get("event") or "run.event")
        with self._lock:
            existing = self._tasks.get(task_id)
            if not existing:
                return None
            result = dict(existing.get("result") if isinstance(existing.get("result"), dict) else {})
            try:
                event_count = int(result.get("event_count") or 0) + 1
            except (TypeError, ValueError):
                event_count = 1
            result["event_count"] = event_count
            result["last_event"] = event_name
            usage = token_usage_from_payload(compact)
            if usage_has_signal(usage):
                result["token_usage"] = merge_token_usage(
                    token_usage_from_payload(result.get("token_usage")),
                    usage,
                )

            if event_name in {"message.delta", "response.output_text.delta"}:
                delta = str(compact.get("delta") or compact.get("text") or "")
                if delta:
                    result["response_stream"] = (str(result.get("response_stream") or "") + delta)[-120000:]
            elif event_name in {"thinking.delta", "reasoning.delta"}:
                delta = str(compact.get("delta") or compact.get("text") or "")
                if delta:
                    result["thinking_stream"] = (str(result.get("thinking_stream") or "") + delta)[-120000:]
                events = result.get("events") if isinstance(result.get("events"), list) else []
                events = [item for item in events if isinstance(item, dict)]
                events.append(compact)
                result["events"] = events[-240:]
            else:
                events = result.get("events") if isinstance(result.get("events"), list) else []
                events = [item for item in events if isinstance(item, dict)]
                events.append(compact)
                result["events"] = events[-240:]

            task = {
                **existing,
                "updated_at": utc_now(),
                "result": result,
            }
            self._tasks[task_id] = task
            if event_name not in {"message.delta", "response.output_text.delta"} or usage_has_signal(usage):
                self._save()
            return task

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self._lock:
            tasks = list(self._tasks.values())
        tasks.sort(key=lambda task: str(task.get("updated_at") or task.get("created_at") or ""), reverse=True)
        return tasks[:safe_limit]

    def latest_running_for_node(self, node_id: str) -> dict[str, Any] | None:
        node = validate_node_id(node_id)
        with self._lock:
            running = [
                task
                for task in self._tasks.values()
                if task.get("status") == "running" and task.get("target_node") == node
            ]
        if not running:
            return None
        return max(running, key=lambda task: str(task.get("updated_at") or task.get("created_at") or ""))


class BridgeContext:
    def __init__(self, settings: BridgeSettings) -> None:
        self.settings = settings
        self.task_store = TaskStore(settings.state_dir)
        self.orchestrator = OrchestratorClient(settings, self.task_store)


class SpaceUIServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        context: BridgeContext,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.context = context


class SpaceUIHandler(BaseHTTPRequestHandler):
    server: SpaceUIServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.getenv("HERMES_WASM_AGENT_BRIDGE_ACCESS_LOG", "").lower() in {"1", "true", "yes", "on"}:
            super().log_message(fmt, *args)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_common_headers()
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type,X-Hermes-Space-Ui-Token")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._handle_get()
        except BridgeError as exc:
            self._json_error(exc.status, exc.code, exc.message, exc.details)
        except Exception as exc:
            self._json_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "unexpected_error",
                "Unexpected bridge error.",
                {"error": str(exc)},
            )

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._handle_post()
        except BridgeError as exc:
            self._json_error(exc.status, exc.code, exc.message, exc.details)
        except Exception as exc:
            self._json_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "unexpected_error",
                "Unexpected bridge error.",
                {"error": str(exc)},
            )

    def _handle_get(self) -> None:
        parsed = urlparse(self.path)
        path = normalize_bridge_path(parsed.path.rstrip("/") or "/")
        if path == "/health":
            self._health()
            return
        self._require_auth()

        if path == "/capabilities":
            self._capabilities()
            return
        if path == "/resources":
            resources = host_resources_snapshot(self.server.context.settings)
            self._json_response(HTTPStatus.OK, success({"resources": resources}))
            return
        if path == "/v1/models":
            self._json_response(
                HTTPStatus.OK,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "hermes-orchestrator",
                            "object": "model",
                            "created": 0,
                            "owned_by": "hermes-orchestrator",
                        }
                    ],
                },
            )
            return
        if path == "/v1/capabilities":
            self._json_response(
                HTTPStatus.OK,
                {
                    "object": "hermes.capabilities",
                    "model": "hermes-orchestrator",
                    "streaming": True,
                    "backend": "hermes-api-server-runs",
                    "safe_actions": sorted(ALLOWED_ACTIONS),
                },
            )
            return
        if path == "/nodes":
            cards = self.server.context.orchestrator.list_nodes()
            self._json_response(HTTPStatus.OK, success({"nodes": cards}))
            return
        if path.startswith("/nodes/"):
            parts = path.strip("/").split("/")
            if len(parts) == 2:
                node_id = validate_node_id(parts[1])
                raw = self.server.context.orchestrator.get_node_status(node_id)
                self._json_response(HTTPStatus.OK, success({"node": node_card(node_id, raw)}))
                return
            if len(parts) == 3 and parts[2] == "logs":
                node_id = validate_node_id(parts[1])
                query = parse_qs(parsed.query)
                lines = int((query.get("lines") or ["80"])[0])
                raw = self.server.context.orchestrator.tail_node_logs(node_id, lines=lines)
                self._json_response(HTTPStatus.OK, success({"logs": logs_panel(node_id, raw)}))
                return
            if len(parts) == 3 and parts[2] == "stats":
                node_id = validate_node_id(parts[1])
                query = parse_qs(parsed.query)
                days = int((query.get("days") or ["30"])[0])
                bucket = str((query.get("bucket") or ["daily"])[0])
                stats = self.server.context.orchestrator.node_stats(node_id, days=days, bucket=bucket)
                self._json_response(HTTPStatus.OK, success({"stats": stats}))
                return
        if path == "/tasks":
            tasks = self.server.context.task_store.list_recent()
            self._json_response(HTTPStatus.OK, success({"tasks": tasks}))
            return
        if path.startswith("/tasks/"):
            parts = path.strip("/").split("/")
            if len(parts) == 2:
                task = self.server.context.task_store.get(parts[1])
                if not task:
                    raise BridgeError("task_not_found", "Task was not found.", status=HTTPStatus.NOT_FOUND)
                self._json_response(HTTPStatus.OK, success({"task": task}))
                return
        raise BridgeError("not_found", "Endpoint was not found.", status=HTTPStatus.NOT_FOUND)

    def _handle_post(self) -> None:
        parsed = urlparse(self.path)
        path = normalize_bridge_path(parsed.path.rstrip("/") or "/")
        self._require_auth()

        if path == "/drop-to-copy/tasks":
            body = self._read_json_body(max_bytes=512 * 1024)
            task = self.server.context.orchestrator.start_drop_to_copy_task(body)
            self._json_response(HTTPStatus.ACCEPTED, success({"task": task}))
            return

        if path in {"/task", "/tasks"}:
            body = self._read_json_body()
            prompt = str(body.get("prompt") or "").strip()
            target_node = body.get("target_node")
            runner = (
                self.server.context.orchestrator.start_task
                if wants_async_task(body)
                else self.server.context.orchestrator.submit_task
            )
            task = runner(
                prompt=prompt,
                target_node=str(target_node) if target_node else None,
                run_options=run_options_from_payload(body),
            )
            self._json_response(HTTPStatus.ACCEPTED if task.get("status") == "running" else HTTPStatus.OK, success({"task": task}))
            return

        if path.startswith("/tasks/") and path.endswith("/stop"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                body = self._read_json_body(max_bytes=32 * 1024)
                reason = str(body.get("reason") or "Stop requested from wasm-agent bridge.").strip()
                task = self.server.context.orchestrator.stop_task(parts[1], reason=reason)
                self._json_response(HTTPStatus.OK, success({"task": task}))
                return

        if path == "/nodes":
            body = self._read_json_body(max_bytes=128 * 1024)
            result = self.server.context.orchestrator.create_node(body)
            self._json_response(HTTPStatus.OK, success({"node_create": result}))
            return

        if path.startswith("/nodes/") and path.endswith("/prompt"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                node_id = validate_node_id(parts[1])
                body = self._read_json_body(max_bytes=2 * 1024 * 1024)
                prompt = str(body.get("prompt") or "").strip()
                runner = (
                    self.server.context.orchestrator.start_task
                    if wants_async_task(body)
                    else self.server.context.orchestrator.submit_task
                )
                task = runner(
                    prompt=prompt,
                    target_node=node_id,
                    run_options=run_options_from_payload(body),
                )
                self._json_response(HTTPStatus.ACCEPTED if task.get("status") == "running" else HTTPStatus.OK, success({"task": task}))
                return

        if path == "/v1/chat/completions":
            body = self._read_json_body(max_bytes=2 * 1024 * 1024)
            completion = self.server.context.orchestrator.run_chat_completion(body)
            if bool(body.get("stream")):
                self._sse_chat_response(completion)
            else:
                self._json_response(HTTPStatus.OK, completion)
            return

        if path.startswith("/nodes/") and path.endswith("/action"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                node_id = validate_node_id(parts[1])
                body = self._read_json_body()
                action = str(body.get("action") or "").strip()
                payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
                result = self.server.context.orchestrator.run_node_action(node_id, action, payload)
                self._json_response(HTTPStatus.OK, success({"action_result": result}))
                return
        raise BridgeError("not_found", "Endpoint was not found.", status=HTTPStatus.NOT_FOUND)

    def _health(self) -> None:
        settings = self.server.context.settings
        horc_path = Path(settings.horc_path)
        horc_available = horc_path.exists() or bool(shutil.which(settings.horc_path))
        payload = {
            "name": PLUGIN_NAME,
            "version": PLUGIN_VERSION,
            "status": "ok",
            "auth_required": bool(settings.token),
            "horc_path": settings.horc_path,
            "horc_available": horc_available,
            "bridge_owner": "wasm-agent",
            "task_submission": "official_api_server_runs",
        }
        self._json_response(HTTPStatus.OK, success({"health": payload}))

    def _capabilities(self) -> None:
        settings = self.server.context.settings
        payload = {
            "schema": "hermes.space_ui.capabilities.v1",
            "plugin": {"name": PLUGIN_NAME, "version": PLUGIN_VERSION},
            "auth_required": bool(settings.token),
            "safe_actions": sorted(ALLOWED_ACTIONS),
            "endpoints": [
                "GET /health",
                "GET /nodes",
                "GET /nodes/{node_id}",
                "GET /nodes/{node_id}/logs",
                "GET /nodes/{node_id}/stats",
                "GET /resources",
                "POST /drop-to-copy/tasks",
                "POST /nodes",
                "POST /nodes/{node_id}/prompt",
                "POST /nodes/{node_id}/action",
                "POST /task",
                "POST /tasks",
                "POST /tasks/{task_id}/stop",
                "GET /tasks",
                "GET /tasks/{task_id}",
                "GET|POST /api/* aliases for widget compatibility",
                "GET /capabilities",
            ],
            "integration": {
                "source_of_truth": "horc CLI",
                "horc_path": settings.horc_path,
                "task_submission": "official Hermes API server Runs API",
                "task_events": "Hermes Runs API event stream copied into GET /tasks/{task_id}",
                "raw_shell_passthrough": False,
                "agent_core_patches": False,
            },
            "workspace": {
                "owner": "wasm-agent",
                "role": "fleet workspace bridge",
            },
            "schemas": JSON_SCHEMAS,
            "required_node_api": {
                "capabilities": "GET /v1/capabilities",
                "run_create": "POST /v1/runs",
                "run_status": "GET /v1/runs/{run_id}",
                "run_events": "GET /v1/runs/{run_id}/events",
                "run_stop": "POST /v1/runs/{run_id}/stop",
            },
        }
        self._json_response(HTTPStatus.OK, success({"capabilities": payload}))

    def _require_auth(self) -> None:
        settings = self.server.context.settings
        if not is_authorized(self.headers, settings.token):
            raise BridgeError(
                "unauthorized",
                "Missing or invalid wasm-agent bridge token.",
                status=HTTPStatus.UNAUTHORIZED,
            )

    def _read_json_body(self, *, max_bytes: int = 65536) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise BridgeError("invalid_content_length", "Invalid Content-Length header.") from exc
        if length > max_bytes:
            raise BridgeError("payload_too_large", "Request body is too large.", status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BridgeError("invalid_json", "Request body must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise BridgeError("invalid_json", "Request body must be a JSON object.")
        return payload

    def _send_common_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")

    def _json_response(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        for key, value in JSON_HEADERS.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _sse_chat_response(self, completion: dict[str, Any]) -> None:
        completion_id = str(completion.get("id") or f"chatcmpl-hermes-{uuid.uuid4().hex[:12]}")
        created = int(completion.get("created") or time.time())
        model = str(completion.get("model") or "hermes-orchestrator")
        content = str(completion.get("choices", [{}])[0].get("message", {}).get("content") or "")

        def chunk(delta: dict[str, Any], finish_reason: str | None = None) -> bytes:
            payload = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": finish_reason,
                    }
                ],
            }
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

        self.send_response(HTTPStatus.OK)
        self._send_common_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Connection", "close")
        self.end_headers()
        for frame in (
            chunk({"role": "assistant"}),
            chunk({"content": content}),
            chunk({}, "stop"),
            b"data: [DONE]\n\n",
        ):
            self.wfile.write(frame)
            self.wfile.flush()

    def _json_error(
        self,
        status: HTTPStatus,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._json_response(status, error_payload(code, message, details=details))


def validate_node_id(node_id: str | None) -> str:
    normalized = str(node_id or "").strip().lower()
    if not VALID_NODE_RE.fullmatch(normalized):
        raise BridgeError("invalid_node_id", "Node id is invalid.", details={"node_id": node_id})
    return normalized


def normalize_bridge_path(path: str) -> str:
    normalized = str(path or "/").rstrip("/") or "/"
    if normalized == "/api":
        return "/"
    if normalized.startswith("/api/"):
        return normalized[4:] or "/"
    return normalized


def rewrite_exhaust_slash_prompt(prompt: str, *, node: str, agents_root: Path) -> str:
    text = str(prompt or "").strip()
    if not text.startswith("/"):
        return prompt

    parts = text.split(maxsplit=1)
    first = parts[0] if parts else ""
    rest = parts[1] if len(parts) > 1 else ""
    command = first.lstrip("/").split("@", 1)[0].strip().lower().replace("_", "-")
    aliases = {
        "exhaust": "/exhaust",
        "exaust": "/exaust",
        "bruteforce": "/bruteforce",
    }
    if command not in aliases:
        return prompt

    task = rest.strip()
    if not task:
        raise BridgeError(
            "missing_exhaust_task",
            f"Usage: {aliases[command]} <task>",
        )

    env = load_env_file(agents_root / "envs" / f"{node}.env")
    if not coerce_bool(env.get("PLUGINS_EXHAUST"), default=False):
        raise BridgeError(
            "exhaust_plugin_disabled",
            "The exhaust plugin is not enabled for this Hermes node.",
            status=HTTPStatus.CONFLICT,
            details={
                "node_id": node,
                "env_path": str(agents_root / "envs" / f"{node}.env"),
                "required": "PLUGINS_EXHAUST=true",
            },
        )

    runtime_path = Path(os.getenv("HERMES_WASM_AGENT_BRIDGE_EXHAUST_RUNTIME", "/local/plugins/exhaust/runtime.py"))
    if runtime_path.exists():
        previous: dict[str, str | None] = {}
        for key in (
            "PLUGINS_EXHAUST",
            "PLUGINS_EXHAUST_MAX_ATTEMPTS",
            "PLUGINS_EXHAUST_MAX_SECONDS",
            "PLUGINS_EXHAUST_MAX_TOOL_NUDGES",
            "PLUGINS_EXHAUST_PASSIVE",
            "HERMES_EXHAUST_LOG",
            "NODE_NAME",
        ):
            previous[key] = os.environ.get(key)
            if key in env:
                os.environ[key] = env[key]
        os.environ["NODE_NAME"] = node
        try:
            spec = importlib.util.spec_from_file_location("hermes_space_ui_exhaust_runtime", runtime_path)
            module = importlib.util.module_from_spec(spec) if spec and spec.loader else None
            if module is not None:
                spec.loader.exec_module(module)
                build = getattr(module, "_build_exhaust_prompt", None)
                if callable(build):
                    return str(build(task, trigger=aliases[command]))
        except Exception:
            pass
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    return build_exhaust_prompt_fallback(task, trigger=aliases[command])


def build_exhaust_prompt_fallback(task: str, *, trigger: str) -> str:
    cdp_url = str(os.getenv("HERMES_EXHAUST_BROWSER_CDP_URL", "http://127.0.0.1:9222") or "").strip()
    needs_web_route = bool(
        re.search(
            r"\b(youtube|youtu\.be|video|browser|chrome|web|website|page|url|transcript|rss|search)\b",
            str(task or ""),
            re.IGNORECASE,
        )
    )
    route_guidance = ""
    if cdp_url and needs_web_route:
        verify_url = cdp_url.rstrip("/") + "/json/version"
        route_guidance = f"""
Task-aware access route:
- For YouTube or other IP/anti-bot blocked sites, evaluate the user Chrome CDP
  reverse tunnel before declaring the web path blocked.
- Verify the route: `curl -fsS {verify_url}`.
- Connect route: `/browser connect {cdp_url}`. If slash commands are not
  available in this API turn, use browser tools after `BROWSER_CDP_URL` or
  `browser.cdp_url` is set to `{cdp_url}`.
- Retry the site through browser tools using the user's Chrome session, not the
  Oracle Cloud egress path.
- Do not mark the browser/web path exhausted until this route has either been
  attempted or proven unreachable.
- If unreachable, ask the user to start or keep open the SSH reverse tunnel
  window and report this exact missing route.
"""
    return f"""\
HERMES_EXHAUST_MODE=active
Trigger: {trigger}
Task: {task}

Run this task in structured capability-exhaustion mode.

Before declaring failure, inspect the available capability surface, call
exhaust_inventory early when available, build distinct fallback paths, try
materially different safe routes, and stop only on success, safety/policy
boundary, missing required input, missing credentials, or budget exhaustion.
{route_guidance}

Final answer format:
- Outcome: success, partial, blocked, or exhausted
- Attempts: concise ledger of distinct fallback paths
- Result or artifact
- Remaining blocker and cleanest next architecture/API/hook change if needed
"""


def slugify_for_prompt(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug or "generated-widget"


def build_drop_to_copy_prompt(
    *,
    repo_url: str,
    app_name: str,
    instructions: str,
    dropped_text: str,
    space_id: str,
    build_widget_id: str,
) -> str:
    frontier_provider = os.getenv("HERMES_WASM_AGENT_BRIDGE_DROP_TO_COPY_PROVIDER", "openai-codex")
    frontier_model = os.getenv("HERMES_WASM_AGENT_BRIDGE_DROP_TO_COPY_MODEL", "gpt-5.5")
    reasoning_effort = os.getenv("HERMES_WASM_AGENT_BRIDGE_DROP_TO_COPY_REASONING_EFFORT", "xhigh")
    widget_id = slugify_for_prompt(app_name)
    app_name_json = json.dumps(app_name)
    enforced = """using `/local/plugins/wasm-agent/`
check the wasm-agent Admin workspace
Use wasm-agent module/artifact boundaries and Hermes Orchestrator bridge APIs before proposing shared source changes. Do not patch Hermes Agent internals for UI behavior. If a missing interface blocks the work, state the smallest generic bridge/module seam that would unblock it."""
    return f"""
{enforced}

Drop to Copy job:
- Requested frontier provider: {frontier_provider}
- Requested frontier model: {frontier_model}
- Requested reasoning effort: {reasoning_effort}
- Target Space Agent space id: {space_id}
- Build/status widget id already created by the UI: {build_widget_id or "not provided"}
- GitHub repo or URL: {repo_url or "not provided"}
- App name to create: {app_name}
- User instructions: {instructions}

Dropped input:
```text
{dropped_text or "not provided"}
```

Mission:
1. Inspect the target repository and `/local/plugins/wasm-agent/` before proposing changes.
2. Create a portable wasm-agent artifact named exactly `{app_name}`. Use a widget/app id derived from that name in short kebab-case.
3. Prefer WIS/artifact/module contracts over source edits when the request is userland UI or workspace behavior.
4. Treat the repo as source inspiration and interface context. Do not try to install legacy Space Agent customware unless a task explicitly requests a compatibility migration.
5. Use Hermes Agent through official bridge/API interfaces only. Do not import Hermes Agent internals or write directly into gateway state.
6. Build a usable artifact for the current wasm-agent space. Keep the implementation self-contained and future-proof against Hermes Agent and wasm-agent module updates.
7. If a required capability is missing from the current interfaces, state the exact missing seam and the smallest generic PR that would unblock it.

Output contract:
- First provide a concise implementation note and any interface limitations.
- Then include one fenced JSON block with this shape so the Drop to Copy widget can install it:

```json
{{
  "schema": "hermes.space_ui.generated_widget.v1",
  "widget": {{
    "widgetId": "{widget_id}",
    "name": {app_name_json},
    "cols": 5,
    "rows": 5,
    "metadata": {{ "icon": "extension" }},
    "renderer": "async (parent, space, context) => {{ /* complete Space Agent widget renderer */ }}"
  }}
}}
```

Renderer requirements:
- The renderer must be a complete async JavaScript function source string.
- It must use stable skeleton sizing and update text/values in place for polling surfaces.
- It must call the wasm-agent bridge bridge through `space.fetchExternal(...)` when host or node data is needed.
- Use the literal bridge URL shown in this prompt or the `__HERMES_SPACE_URL__` placeholder only; Drop to Copy will replace placeholders before install.
- Use only documented bridge paths: `GET /resources`, `GET /nodes`, `GET /nodes/{node_id}`, `POST /task` or `POST /tasks`, and `GET /tasks/{task_id}`. Do not invent `/api/...` paths; compatibility aliases exist only as a fallback.
- If the widget submits future build/edit prompts, wrap the user's text with explicit instructions to update the named widget/app in the `{space_id}` space through plugin-interface-safe files/APIs, and include `target_node: "orchestrator"`, `provider: "{frontier_provider}"`, `model: "{frontier_model}"`, `reasoning_effort: "{reasoning_effort}"`, and `timeout_sec: 900` in the bridge request body.
- It must not require external build tooling to run inside Space Agent.
- Keep UI compact, accessible, and consistent with the Hermes OS widgets.
""".strip()


def validate_action(action: str | None) -> str:
    normalized = str(action or "").strip()
    if normalized not in ALLOWED_ACTIONS:
        raise BridgeError(
            "unknown_action",
            "Action is not allowlisted.",
            details={"action": action, "allowed_actions": sorted(ALLOWED_ACTIONS)},
        )
    return normalized


def normalize_node_state(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized not in {"1", "2", "3", "4"}:
        raise BridgeError(
            "invalid_node_state",
            "NODE_STATE must be one of 1, 2, 3, or 4.",
            details={"node_state": value},
        )
    return normalized


def required_text(payload: dict[str, Any], *keys: str, max_len: int = 4096) -> str:
    value = optional_text(payload, *keys, max_len=max_len)
    if value:
        return value
    raise BridgeError(
        "missing_required_field",
        f"Missing required field: {keys[0]}.",
        details={"accepted_keys": list(keys)},
    )


def optional_text(payload: dict[str, Any], *keys: str, max_len: int = 8192) -> str:
    for key in keys:
        if key not in payload:
            continue
        text = str(payload.get(key) or "").strip()
        if not text:
            continue
        if len(text) > max_len:
            raise BridgeError(
                "field_too_long",
                f"Field is too long: {key}.",
                details={"field": key, "max_len": max_len},
            )
        return text
    return ""


def coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    return default


def node_env_source_path(settings: BridgeSettings, source: str) -> Path:
    raw = str(source or "").strip()
    if not raw:
        raise BridgeError("missing_env_source", "Node env source is empty.")

    if "/" in raw or ".env" in raw or raw.startswith("."):
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = settings.agents_root / "envs" / path
        return path.resolve()

    source_node = validate_node_id(raw)
    return (settings.agents_root / "envs" / f"{source_node}.env").resolve()


def load_node_env_source(
    settings: BridgeSettings,
    payload: dict[str, Any],
    node_id: str,
) -> tuple[dict[str, str], Path]:
    explicit_source = optional_text(
        payload,
        "source_node",
        "base_node",
        "template_node",
        "source_env",
        "source_env_path",
    )
    configured_source = str(os.getenv(NODE_ENV_SOURCE_ENV, "") or "").strip()
    candidates: list[Path] = []
    requested_source = explicit_source or configured_source

    if requested_source:
        path = node_env_source_path(settings, requested_source)
        env = load_env_file(path)
        if env:
            return env, path
        raise BridgeError(
            "node_env_source_not_found",
            "The requested node env source profile was not found or is empty.",
            status=HTTPStatus.BAD_REQUEST,
            details={
                "node_id": node_id,
                "requested_source": requested_source,
                "env": NODE_ENV_SOURCE_ENV,
                "checked": [str(path)],
            },
        )

    env_root = settings.agents_root / "envs"
    target_env_path = (env_root / f"{node_id}.env").resolve()
    candidates.extend(
        [
            env_root / "node.env",
            env_root / "node.env.example",
            env_root / "orchestrator.env",
        ]
    )

    seen: set[Path] = set()
    for raw_path in candidates:
        path = raw_path.resolve()
        if path in seen:
            continue
        seen.add(path)
        if path == target_env_path:
            continue
        env = load_env_file(path)
        if env:
            return env, path

    raise BridgeError(
        "node_env_source_not_found",
        "No usable node env source profile was found.",
        status=HTTPStatus.BAD_REQUEST,
        details={
            "node_id": node_id,
            "requested_source": requested_source,
            "env": NODE_ENV_SOURCE_ENV,
            "checked": [str(path) for path in candidates],
        },
    )


def is_space_ui_generated_env(path: Path, node_id: str) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[:4]
    except OSError:
        return False
    return (
        any(line.strip() == "# Generated by wasm-agent-bridge." for line in lines)
        and any(line.strip() == f"# Node: {node_id}" for line in lines)
    )


def is_resumable_space_ui_draft(raw_status: dict[str, Any]) -> bool:
    state = raw_status.get("container_state")
    container_state = state if isinstance(state, dict) else {}
    return (
        not bool(raw_status.get("clone_root_exists"))
        and not bool(container_state.get("exists"))
        and not bool(container_state.get("running"))
    )


def hydrate_node_runtime_values(
    settings: BridgeSettings,
    payload: dict[str, Any],
    node_id: str,
    env: dict[str, str],
    base_env_path: Path,
) -> dict[str, Any]:
    missing_before = missing_node_start_values(env)
    if not missing_before:
        return {
            "requested": False,
            "source_path": "",
            "inherited_keys": [],
            "missing_before": [],
            "missing_after": [],
        }

    source_path, inherited_keys, missing_after, explicit = select_runtime_source(
        settings,
        payload,
        node_id,
        env,
        base_env_path,
    )
    if not source_path:
        return {
            "requested": True,
            "source_path": "",
            "inherited_keys": [],
            "missing_before": missing_before,
            "missing_after": missing_after,
        }

    return {
        "requested": True,
        "auto": not explicit,
        "source_path": str(source_path),
        "inherited_keys": inherited_keys,
        "missing_before": missing_before,
        "missing_after": missing_after,
        "warning": "runtime values were inherited from an existing local env profile",
    }


def select_runtime_source(
    settings: BridgeSettings,
    payload: dict[str, Any],
    node_id: str,
    env: dict[str, str],
    base_env_path: Path,
) -> tuple[Path | None, list[str], list[str], bool]:
    explicit_source = optional_text(
        payload,
        "runtime_source_node",
        "credential_source_node",
        "credentials_source_node",
        "runtime_env_source",
        "runtime_env_path",
        "credential_env_path",
        "credentials_env_path",
    )
    if explicit_source.strip().lower() == "auto":
        explicit_source = ""
    configured_source = str(os.getenv(NODE_ENV_RUNTIME_SOURCE_ENV, "") or "").strip()
    if configured_source.lower() == "auto":
        configured_source = ""

    env_root = settings.agents_root / "envs"
    target_env_path = (env_root / f"{node_id}.env").resolve()
    candidate_paths: list[Path] = []
    explicit = bool(explicit_source)

    if explicit_source:
        candidate_paths.append(node_env_source_path(settings, explicit_source))
    elif configured_source:
        explicit = True
        candidate_paths.append(node_env_source_path(settings, configured_source))
    else:
        candidate_paths.append(base_env_path)
        candidate_paths.extend(sorted(env_root.glob("*.env")))

    seen: set[Path] = set()
    candidates: list[tuple[int, int, str, Path, dict[str, str], list[str], list[str]]] = []
    best_missing = missing_node_start_values(env)
    for raw_path in candidate_paths:
        path = raw_path.resolve()
        if path in seen or path == target_env_path:
            continue
        seen.add(path)
        source_env = load_env_file(path)
        if not source_env:
            if explicit:
                raise BridgeError(
                    "node_runtime_source_not_found",
                    "The requested node runtime source profile was not found or is empty.",
                    status=HTTPStatus.BAD_REQUEST,
                    details={
                        "node_id": node_id,
                        "requested_source": explicit_source or configured_source,
                        "env": NODE_ENV_RUNTIME_SOURCE_ENV,
                        "checked": [str(path)],
                    },
                )
            continue
        inherited_keys, simulated = runtime_inherited_keys(env, source_env)
        if not inherited_keys:
            continue
        missing_after = missing_node_start_values(simulated)
        if len(missing_after) < len(best_missing):
            best_missing = missing_after
        score = runtime_source_score(path, source_env, env, base_env_path)
        candidates.append((len(missing_after), -score, str(path), path, source_env, inherited_keys, missing_after))

    if not candidates:
        return None, [], best_missing, explicit

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    _, _, _, source_path, source_env, inherited_keys, missing_after = candidates[0]
    for key in inherited_keys:
        env[key] = str(source_env.get(key) or "")
    return source_path, inherited_keys, missing_after, explicit


def runtime_inherited_keys(target_env: dict[str, str], source_env: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    simulated = dict(target_env)
    inherited_keys: list[str] = []
    for key in NODE_ENV_RUNTIME_COPY_KEYS:
        if not env_value_is_placeholder(simulated.get(key)):
            continue
        value = source_env.get(key)
        if env_value_is_placeholder(value):
            continue
        simulated[key] = str(value)
        inherited_keys.append(key)
    return inherited_keys, simulated


def runtime_source_score(
    path: Path,
    source_env: dict[str, str],
    target_env: dict[str, str],
    base_env_path: Path,
) -> int:
    score = 0
    if path == base_env_path:
        score += 50
    source_provider = str(source_env.get("NODE_AGENT_DEFAULT_MODEL_PROVIDER") or "").strip().lower()
    target_provider = str(target_env.get("NODE_AGENT_DEFAULT_MODEL_PROVIDER") or "").strip().lower()
    source_model = str(source_env.get("NODE_AGENT_DEFAULT_MODEL") or "").strip().lower()
    target_model = str(target_env.get("NODE_AGENT_DEFAULT_MODEL") or "").strip().lower()
    if source_provider and source_provider == target_provider:
        score += 40
    if source_model and source_model == target_model:
        score += 30
    if path.name == "orchestrator.env":
        score -= 10
    else:
        score += 10
    score += sum(1 for key in NODE_ENV_RUNTIME_COPY_KEYS if not env_value_is_placeholder(source_env.get(key)))
    return score


def retarget_node_env_value(raw: str, source_node: str, target_node: str) -> str:
    value = str(raw or "")
    source = str(source_node or "").strip()
    target = str(target_node or "").strip()
    if not source or not target or source == target:
        return value

    replacements = [
        (f"/{source}.json", f"/{target}.json"),
        (f"/{source}_acl.json", f"/{target}_acl.json"),
        (f"/{source}_models.json", f"/{target}_models.json"),
        (f"/{source}/", f"/{target}/"),
    ]
    for needle, replacement in replacements:
        value = value.replace(needle, replacement)
    return target if value == source else value


def env_value_is_placeholder(value: Any) -> bool:
    text = str(value or "").strip().strip("\"'")
    if not text:
        return True
    if text.upper() in NODE_ENV_PLACEHOLDERS:
        return True
    digits = re.sub(r"\D", "", text)
    return bool(digits and len(digits) >= 12 and set(digits) == {"0"})


def missing_node_start_values(env: dict[str, str]) -> list[str]:
    missing: list[str] = []
    for key in [
        "NODE_AGENT_DEFAULT_MODEL_PROVIDER",
        "NODE_AGENT_DEFAULT_MODEL",
        "DISCORD_BOT_TOKEN",
        "DISCORD_APP_ID",
    ]:
        if env_value_is_placeholder(env.get(key)):
            missing.append(key)

    if env_value_is_placeholder(env.get("DISCORD_SERVER_ID")) and env_value_is_placeholder(env.get("DISCORD_GUILD_ID")):
        missing.append("DISCORD_SERVER_ID or DISCORD_GUILD_ID")

    provider = str(env.get("NODE_AGENT_DEFAULT_MODEL_PROVIDER") or "").strip().lower()
    provider_requirements = {
        "minimax": ["MINIMAX_API_KEY", "MINIMAX_GROUP_ID"],
        "openrouter": ["OPENROUTER_API_KEY"],
        "nvidia": ["NVIDIA_API_KEY"],
    }
    for needle, keys in provider_requirements.items():
        if needle not in provider:
            continue
        for key in keys:
            if env_value_is_placeholder(env.get(key)):
                missing.append(key)
        break
    return missing


def ensure_node_env_can_start(node_id: str, env: dict[str, str], source_path: Path) -> None:
    missing = missing_node_start_values(env)
    if missing:
        raise BridgeError(
            "node_env_not_startable",
            "Cannot start node because the generated env profile is missing required runtime values.",
            status=HTTPStatus.BAD_REQUEST,
            details={
                "node_id": node_id,
                "env_source_path": str(source_path),
                "missing_or_placeholder": missing,
            },
        )


def env_quote(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=True)


def render_node_env(node_id: str, values: dict[str, str]) -> str:
    lines = [
        "# Generated by wasm-agent-bridge.",
        f"# Node: {node_id}",
        f"# Created: {utc_now()}",
        "# Contract: /local/agents/envs/README.md",
        "",
    ]
    for key in NODE_ENV_PRIMARY_ORDER:
        if key in values:
            lines.append(f"{key}={env_quote(values[key])}")
    for key in sorted(set(values) - set(NODE_ENV_PRIMARY_ORDER)):
        lines.append(f"{key}={env_quote(values[key])}")
    return "\n".join(lines).rstrip() + "\n"


def normalize_bucket(value: Any) -> str:
    normalized = str(value or "daily").strip().lower()
    aliases = {
        "day": "daily",
        "daily": "daily",
        "week": "weekly",
        "weekly": "weekly",
        "month": "monthly",
        "monthly": "monthly",
    }
    if normalized not in aliases:
        raise BridgeError(
            "invalid_bucket",
            "Stats bucket must be daily, weekly, or monthly.",
            details={"bucket": value},
        )
    return aliases[normalized]


def stats_window_points(bucket: str) -> int:
    if bucket == "weekly":
        return 7
    if bucket == "monthly":
        return 30
    return 24


def stats_window_days(bucket: str) -> int:
    if bucket == "weekly":
        return 7
    if bucket == "monthly":
        return 30
    return 1


def iso_timestamp(timestamp: float | int | None) -> str:
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(float(timestamp), timezone.utc).isoformat().replace("+00:00", "Z")


def stats_label(timestamp: float, bucket: str) -> str:
    dt = datetime.fromtimestamp(float(timestamp), timezone.utc)
    if bucket == "daily":
        return dt.strftime("%H:%M")
    return dt.strftime("%m-%d")


def build_stats_bucket_specs(bucket: str, *, now_ts: float | None = None) -> list[dict[str, Any]]:
    safe_bucket = normalize_bucket(bucket)
    count = stats_window_points(safe_bucket)
    span_seconds = 3600 if safe_bucket == "daily" else 86400
    end_ts = float(now_ts if now_ts is not None else time.time())
    start_ts = end_ts - (count * span_seconds)
    specs: list[dict[str, Any]] = []
    for index in range(count):
        item_start = start_ts + (index * span_seconds)
        item_end = item_start + span_seconds
        if index == count - 1:
            item_end = end_ts
        specs.append(
            {
                "label": stats_label(item_start, safe_bucket),
                "end_label": stats_label(item_end, safe_bucket),
                "start_ts": item_start,
                "end_ts": item_end,
                "start_at": iso_timestamp(item_start),
                "end_at": iso_timestamp(item_end),
                "span_seconds": span_seconds,
            }
        )
    return specs


def bucket_index_for_timestamp(timestamp: Any, specs: list[dict[str, Any]]) -> int | None:
    if not specs:
        return None
    ts = numeric(timestamp)
    first = float(specs[0]["start_ts"])
    last = float(specs[-1]["end_ts"])
    if ts < first or ts > last:
        return None
    span = max(1.0, float(specs[0].get("span_seconds") or 1))
    index = int((ts - first) // span)
    if index >= len(specs) and ts <= last:
        index = len(specs) - 1
    if index < 0 or index >= len(specs):
        return None
    return index


def bucket_label(timestamp: float, bucket: str) -> str:
    dt = datetime.fromtimestamp(float(timestamp), timezone.utc)
    if bucket == "weekly":
        iso = dt.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if bucket == "monthly":
        return dt.strftime("%Y-%m")
    return dt.strftime("%Y-%m-%d")


def numeric(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def integer(value: Any) -> int:
    return int(numeric(value))


def parse_iso_timestamp(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def token_usage_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    usage_keys = {
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "api_calls",
        "api_call_count",
    }
    nested_keys = ("usage", "token_usage", "tokenUsage", "metrics", "resource_usage")
    candidates: list[dict[str, Any]] = []

    def visit(value: Any, depth: int = 0) -> None:
        if depth > 2 or not isinstance(value, dict):
            return
        if any(key in value for key in usage_keys):
            candidates.append(value)
        for key in nested_keys:
            nested = value.get(key)
            if isinstance(nested, dict):
                visit(nested, depth + 1)

    visit(payload)
    merged: dict[str, Any] = {}
    for candidate in candidates:
        merged = merge_token_usage(merged, normalize_token_usage(candidate))
    return merged


def normalize_token_usage(usage: dict[str, Any]) -> dict[str, Any]:
    input_tokens = integer(usage.get("input_tokens") or usage.get("prompt_tokens"))
    output_tokens = integer(usage.get("output_tokens") or usage.get("completion_tokens"))
    cache_read_tokens = integer(usage.get("cache_read_tokens"))
    cache_write_tokens = integer(usage.get("cache_write_tokens"))
    reasoning_tokens = integer(usage.get("reasoning_tokens"))
    total_tokens = integer(
        usage.get("total_tokens")
        or usage.get("total")
        or usage.get("tokens")
    )
    component_total = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens + reasoning_tokens
    if total_tokens <= 0:
        total_tokens = component_total
    return {
        "input_tokens": max(0, input_tokens),
        "output_tokens": max(0, output_tokens),
        "cache_read_tokens": max(0, cache_read_tokens),
        "cache_write_tokens": max(0, cache_write_tokens),
        "reasoning_tokens": max(0, reasoning_tokens),
        "total_tokens": max(0, total_tokens),
        "api_calls": max(0, integer(usage.get("api_calls") or usage.get("api_call_count"))),
        "source": str(usage.get("source") or usage.get("provider") or "").strip()[:120],
        "model": str(usage.get("model") or "").strip()[:160],
    }


def usage_has_signal(usage: dict[str, Any]) -> bool:
    return any(
        integer(usage.get(key)) > 0
        for key in (
            "total_tokens",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
            "api_calls",
        )
    )


def merge_token_usage(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    current_usage = normalize_token_usage(current) if isinstance(current, dict) else {}
    incoming_usage = normalize_token_usage(incoming) if isinstance(incoming, dict) else {}
    if not usage_has_signal(current_usage):
        return incoming_usage if usage_has_signal(incoming_usage) else {}
    if not usage_has_signal(incoming_usage):
        return current_usage
    merged: dict[str, Any] = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "total_tokens",
        "api_calls",
    ):
        merged[key] = max(integer(current_usage.get(key)), integer(incoming_usage.get(key)))
    component_total = (
        merged["input_tokens"]
        + merged["output_tokens"]
        + merged["cache_read_tokens"]
        + merged["cache_write_tokens"]
        + merged["reasoning_tokens"]
    )
    merged["total_tokens"] = max(integer(merged.get("total_tokens")), component_total)
    merged["source"] = str(incoming_usage.get("source") or current_usage.get("source") or "")
    merged["model"] = str(incoming_usage.get("model") or current_usage.get("model") or "")
    return merged


def task_token_usage(task: dict[str, Any]) -> dict[str, Any]:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    usage = token_usage_from_payload(result.get("token_usage"))
    usage = merge_token_usage(usage, token_usage_from_payload(result.get("usage")))
    events = result.get("events") if isinstance(result.get("events"), list) else []
    for event in events:
        usage = merge_token_usage(usage, token_usage_from_payload(event))
    return usage


def node_hermes_runtime_snapshot(settings: BridgeSettings, node_id: str) -> dict[str, Any]:
    node = validate_node_id(node_id)
    root = settings.agents_root / "nodes" / node / "hermes-agent"
    env = load_env_file(settings.agents_root / "envs" / f"{node}.env")
    version = ""
    release_date = ""
    source = ""

    init_path = root / "hermes_cli" / "__init__.py"
    if init_path.exists():
        try:
            text = init_path.read_text(encoding="utf-8", errors="replace")
            version_match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
            release_match = re.search(r"__release_date__\s*=\s*['\"]([^'\"]+)['\"]", text)
            if version_match:
                version = version_match.group(1).strip()
                source = str(init_path)
            if release_match:
                release_date = release_match.group(1).strip()
        except OSError:
            pass

    pyproject_path = root / "pyproject.toml"
    if not version and pyproject_path.exists():
        try:
            text = pyproject_path.read_text(encoding="utf-8", errors="replace")
            project_match = re.search(r"(?m)^version\s*=\s*['\"]([^'\"]+)['\"]", text)
            if project_match:
                version = project_match.group(1).strip()
                source = str(pyproject_path)
        except OSError:
            pass

    return {
        "schema": "hermes.space_ui.node_hermes_runtime.v1",
        "available": bool(root.exists()),
        "version": version,
        "release_date": release_date,
        "source": source,
        "root": str(root),
        "api_model": str(env.get("API_SERVER_MODEL_NAME") or ""),
        "inference_provider": str(env.get("HERMES_INFERENCE_PROVIDER") or ""),
    }


def node_activity_snapshot(settings: BridgeSettings, node_id: str) -> dict[str, Any]:
    node = validate_node_id(node_id)
    now_ts = time.time()
    try:
        configured_window = float(str(os.getenv("HERMES_WASM_AGENT_BRIDGE_LLM_ACTIVE_WINDOW_SEC", "30") or "30"))
    except ValueError:
        configured_window = 30.0
    window = max(5.0, min(configured_window, 600.0))
    db_path = settings.agents_root / "nodes" / node / ".hermes" / "state.db"
    payload: dict[str, Any] = {
        "schema": "hermes.space_ui.node_activity.v1",
        "llm_active": False,
        "state": "idle",
        "confidence": "conservative",
        "source": "state_db",
        "active_window_sec": window,
        "last_signal_at": "",
        "last_signal_age_sec": None,
        "session_id": "",
        "platform": "",
        "model": "",
        "api_calls": 0,
        "total_tokens": 0,
        "reason": "",
    }

    status_file = read_activity_status_file(settings, node, now_ts=now_ts)
    if status_file:
        payload.update(status_file)
        return payload

    if not db_path.exists():
        payload["source"] = str(db_path)
        payload["reason"] = "state database not found"
        return payload

    try:
        uri = f"file:{db_path}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=2)
        con.row_factory = sqlite3.Row
        latest_message = con.execute(
            """
            SELECT session_id, role, timestamp
              FROM messages
             ORDER BY timestamp DESC
             LIMIT 1
            """
        ).fetchone()
        latest_session = None
        if latest_message and latest_message["session_id"]:
            latest_session = con.execute(
                """
                SELECT id, source, model, started_at, ended_at, input_tokens,
                       output_tokens, cache_read_tokens, cache_write_tokens,
                       reasoning_tokens, api_call_count
                  FROM sessions
                 WHERE id = ?
                 LIMIT 1
                """,
                (latest_message["session_id"],),
            ).fetchone()
        if latest_session is None:
            latest_session = con.execute(
                """
                SELECT id, source, model, started_at, ended_at, input_tokens,
                       output_tokens, cache_read_tokens, cache_write_tokens,
                       reasoning_tokens, api_call_count
                  FROM sessions
                 ORDER BY COALESCE(ended_at, started_at) DESC, started_at DESC
                 LIMIT 1
                """
            ).fetchone()
        con.close()
    except Exception as exc:
        payload["source"] = str(db_path)
        payload["reason"] = str(exc)
        return payload

    if latest_session is None:
        payload["source"] = str(db_path)
        payload["reason"] = "no recorded sessions"
        return payload

    message_ts = numeric(latest_message["timestamp"]) if latest_message else 0.0
    started_ts = numeric(latest_session["started_at"])
    ended_ts = numeric(latest_session["ended_at"])
    last_signal_ts = max(message_ts, started_ts, ended_ts)
    age = max(0.0, now_ts - last_signal_ts) if last_signal_ts else None
    total_tokens = (
        integer(latest_session["input_tokens"])
        + integer(latest_session["output_tokens"])
        + integer(latest_session["cache_read_tokens"])
        + integer(latest_session["cache_write_tokens"])
        + integer(latest_session["reasoning_tokens"])
    )
    open_session = not bool(latest_session["ended_at"])
    has_llm_shape = bool(str(latest_session["model"] or "").strip()) or integer(
        latest_session["api_call_count"]
    ) > 0
    active = bool(open_session and has_llm_shape and age is not None and age <= window)

    payload.update(
        {
            "llm_active": active,
            "state": "working" if active else "idle",
            "source": str(db_path),
            "last_signal_at": iso_timestamp(last_signal_ts) if last_signal_ts else "",
            "last_signal_age_sec": round(age, 1) if age is not None else None,
            "session_id": str(latest_session["id"] or ""),
            "platform": str(latest_session["source"] or ""),
            "model": str(latest_session["model"] or ""),
            "api_calls": integer(latest_session["api_call_count"]),
            "total_tokens": total_tokens,
            "reason": (
                "recent open LLM session"
                if active
                else "no fresh open LLM activity signal"
            ),
        }
    )
    return payload


def activity_from_running_task(task: dict[str, Any]) -> dict[str, Any]:
    updated_ts = parse_iso_timestamp(task.get("updated_at")) or parse_iso_timestamp(task.get("created_at"))
    age = max(0.0, time.time() - updated_ts) if updated_ts else None
    prompt = str(task.get("prompt") or "")
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    usage = task_token_usage(task)
    run_id = str(result.get("run_id") or "")
    api_calls = integer(usage.get("api_calls"))
    if run_id and api_calls <= 0:
        api_calls = 1
    return {
        "llm_active": True,
        "state": "working",
        "confidence": "exact",
        "source": "wasm-agent-bridge task store",
        "last_signal_at": iso_timestamp(updated_ts) if updated_ts else "",
        "last_signal_age_sec": round(age, 1) if age is not None else None,
        "session_id": str(task.get("task_id") or ""),
        "platform": "space-ui",
        "model": str(usage.get("model") or result.get("model_request") or ""),
        "api_calls": api_calls,
        "total_tokens": integer(usage.get("total_tokens")),
        "input_tokens": integer(usage.get("input_tokens")),
        "output_tokens": integer(usage.get("output_tokens")),
        "cache_read_tokens": integer(usage.get("cache_read_tokens")),
        "cache_write_tokens": integer(usage.get("cache_write_tokens")),
        "reasoning_tokens": integer(usage.get("reasoning_tokens")),
        "token_usage": usage,
        "reason": "running wasm-agent bridge task",
        "task_id": str(task.get("task_id") or ""),
        "run_id": run_id,
        "run_status": str(result.get("run_status") or ""),
        "last_event": str(result.get("last_event") or ""),
        "task_preview": prompt[:160],
    }


def read_activity_status_file(
    settings: BridgeSettings,
    node_id: str,
    *,
    now_ts: float,
) -> dict[str, Any] | None:
    paths = [
        settings.agents_root / "nodes" / node_id / ".hermes" / "space_ui_activity.json",
        settings.repo_root / "logs" / "nodes" / "activities" / f"{node_id}.status.json",
    ]
    for path in paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        updated_ts = parse_iso_timestamp(data.get("updated_at")) or numeric(data.get("updated_ts"))
        if not updated_ts:
            try:
                updated_ts = path.stat().st_mtime
            except OSError:
                updated_ts = 0.0
        age = max(0.0, now_ts - updated_ts) if updated_ts else None
        active = bool(data.get("llm_active")) and age is not None and age <= 600
        return {
            "llm_active": active,
            "state": "working" if active else "idle",
            "confidence": "exact",
            "source": str(path),
            "last_signal_at": iso_timestamp(updated_ts) if updated_ts else "",
            "last_signal_age_sec": round(age, 1) if age is not None else None,
            "session_id": str(data.get("session_id") or ""),
            "platform": str(data.get("platform") or ""),
            "model": str(data.get("model") or ""),
            "api_calls": integer(data.get("api_calls")),
            "total_tokens": integer(data.get("total_tokens")),
            "reason": str(data.get("reason") or "activity status file"),
        }
    return None


def new_usage_bucket(label: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "label": label,
        "end_label": str((spec or {}).get("end_label") or ""),
        "start_at": str((spec or {}).get("start_at") or ""),
        "end_at": str((spec or {}).get("end_at") or ""),
    }
    payload.update(
        {
            "sessions": 0,
            "api_calls": 0,
            "message_count": 0,
            "tool_call_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
        }
    )
    return {
        **payload,
    }


def read_node_usage_stats(
    settings: BridgeSettings,
    node_id: str,
    *,
    days: int,
    bucket: str,
) -> dict[str, Any]:
    db_path = settings.agents_root / "nodes" / node_id / ".hermes" / "state.db"
    specs = build_stats_bucket_specs(bucket)
    bucket_items = [new_usage_bucket(str(spec["label"]), spec) for spec in specs]
    payload: dict[str, Any] = {
        "source": str(db_path),
        "available": db_path.exists(),
        "totals": new_usage_bucket("total"),
        "buckets": bucket_items,
        "recent_sessions": [],
        "error": "",
    }
    if not db_path.exists():
        return payload

    since = float(specs[0]["start_ts"]) if specs else (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    until = float(specs[-1]["end_ts"]) if specs else time.time()
    try:
        uri = f"file:{db_path}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=2)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT id, source, model, started_at, ended_at, message_count, tool_call_count,
                   input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                   reasoning_tokens, estimated_cost_usd, api_call_count
              FROM sessions
             WHERE started_at >= ? AND started_at <= ?
             ORDER BY started_at ASC
            """,
            (since, until),
        ).fetchall()
        con.close()
    except Exception as exc:
        payload["available"] = False
        payload["error"] = str(exc)
        return payload

    totals = payload["totals"]
    recent: list[dict[str, Any]] = []
    for row in rows:
        index = bucket_index_for_timestamp(row["started_at"], specs)
        if index is None:
            continue
        item = bucket_items[index]
        input_tokens = integer(row["input_tokens"])
        output_tokens = integer(row["output_tokens"])
        cache_read = integer(row["cache_read_tokens"])
        cache_write = integer(row["cache_write_tokens"])
        reasoning = integer(row["reasoning_tokens"])
        total_tokens = input_tokens + output_tokens + cache_read + cache_write + reasoning
        for target in (item, totals):
            target["sessions"] += 1
            target["api_calls"] += integer(row["api_call_count"])
            target["message_count"] += integer(row["message_count"])
            target["tool_call_count"] += integer(row["tool_call_count"])
            target["input_tokens"] += input_tokens
            target["output_tokens"] += output_tokens
            target["cache_read_tokens"] += cache_read
            target["cache_write_tokens"] += cache_write
            target["reasoning_tokens"] += reasoning
            target["total_tokens"] += total_tokens
            target["estimated_cost_usd"] += numeric(row["estimated_cost_usd"])
        recent.append(
            {
                "id": str(row["id"]),
                "source": str(row["source"] or ""),
                "model": str(row["model"] or ""),
                "started_at": datetime.fromtimestamp(
                    float(row["started_at"]), timezone.utc
                ).isoformat().replace("+00:00", "Z"),
                "total_tokens": total_tokens,
                "estimated_cost_usd": numeric(row["estimated_cost_usd"]),
            }
        )

    totals["estimated_cost_usd"] = round(float(totals["estimated_cost_usd"]), 6)
    for item in bucket_items:
        item["estimated_cost_usd"] = round(float(item["estimated_cost_usd"]), 6)
    payload["buckets"] = bucket_items
    payload["recent_sessions"] = recent[-8:][::-1]
    return payload


def new_activity_bucket(label: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "label": label,
        "end_label": str((spec or {}).get("end_label") or ""),
        "start_at": str((spec or {}).get("start_at") or ""),
        "end_at": str((spec or {}).get("end_at") or ""),
        "events": 0,
        "tool_count": 0,
        "api_call_count": 0,
        "completed": 0,
        "failed": 0,
    }


def read_node_activity_stats(
    settings: BridgeSettings,
    node_id: str,
    *,
    days: int,
    bucket: str,
) -> dict[str, Any]:
    path = settings.repo_root / "logs" / "nodes" / "activities" / f"{node_id}.jsonl"
    db_path = settings.agents_root / "nodes" / node_id / ".hermes" / "state.db"
    specs = build_stats_bucket_specs(bucket)
    bucket_items = [new_activity_bucket(str(spec["label"]), spec) for spec in specs]
    payload: dict[str, Any] = {
        "source": str(path),
        "fallback_source": str(db_path),
        "source_type": "activity_jsonl" if path.exists() else "state_db_sessions",
        "available": path.exists() or db_path.exists(),
        "totals": new_activity_bucket("total"),
        "buckets": bucket_items,
        "recent_events": [],
        "last_activity": None,
        "error": "",
    }
    since = float(specs[0]["start_ts"]) if specs else (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    recent: list[dict[str, Any]] = []

    if path.exists():
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = parse_iso_timestamp(entry.get("ts"))
                    index = bucket_index_for_timestamp(ts, specs) if ts is not None else None
                    if index is None or ts is None or ts < since:
                        continue
                    item = bucket_items[index]
                    tools = entry.get("tool_usage") if isinstance(entry.get("tool_usage"), dict) else {}
                    outcome = str(entry.get("cycle_outcome") or "").lower()
                    for target in (item, payload["totals"]):
                        target["events"] += 1
                        target["tool_count"] += integer(tools.get("tool_count"))
                        target["api_call_count"] += integer(tools.get("api_call_count"))
                        if "complete" in outcome:
                            target["completed"] += 1
                        if "fail" in outcome or "error" in outcome:
                            target["failed"] += 1
                    recent.append(
                        {
                            "ts": str(entry.get("ts") or ""),
                            "session_id": str(entry.get("session_id") or ""),
                            "source": str(entry.get("interaction_source") or entry.get("platform") or ""),
                            "outcome": str(entry.get("cycle_outcome") or ""),
                            "message_preview": str(entry.get("message_preview") or "")[:240],
                            "response_preview": str(entry.get("response_preview") or "")[:240],
                            "tool_count": integer(tools.get("tool_count")),
                        }
                    )
        except Exception as exc:
            payload["error"] = str(exc)

    if not recent:
        payload["source_type"] = "state_db_sessions"
        recent = read_state_db_activity_events(settings, node_id, specs, payload)

    payload["buckets"] = bucket_items
    payload["recent_events"] = recent[-8:][::-1]
    payload["last_activity"] = recent[-1] if recent else None
    return payload


def read_state_db_activity_events(
    settings: BridgeSettings,
    node_id: str,
    specs: list[dict[str, Any]],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    db_path = settings.agents_root / "nodes" / node_id / ".hermes" / "state.db"
    if not db_path.exists():
        return []
    since = float(specs[0]["start_ts"]) if specs else 0.0
    until = float(specs[-1]["end_ts"]) if specs else time.time()
    recent: list[dict[str, Any]] = []
    try:
        uri = f"file:{db_path}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=2)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT id, source, model, started_at, ended_at, end_reason,
                   message_count, tool_call_count, input_tokens, output_tokens,
                   cache_read_tokens, cache_write_tokens, reasoning_tokens,
                   api_call_count
              FROM sessions
             WHERE started_at >= ? AND started_at <= ?
             ORDER BY started_at ASC
            """,
            (since, until),
        ).fetchall()
        con.close()
    except Exception as exc:
        payload["available"] = False
        payload["error"] = str(exc)
        return []

    bucket_items = payload["buckets"]
    totals = payload["totals"]
    for row in rows:
        index = bucket_index_for_timestamp(row["started_at"], specs)
        if index is None:
            continue
        item = bucket_items[index]
        end_reason = str(row["end_reason"] or "").lower()
        failed = any(token in end_reason for token in ("fail", "error", "interrupt", "cancel"))
        completed = bool(row["ended_at"]) and not failed
        tool_count = integer(row["tool_call_count"])
        api_calls = integer(row["api_call_count"])
        total_tokens = (
            integer(row["input_tokens"])
            + integer(row["output_tokens"])
            + integer(row["cache_read_tokens"])
            + integer(row["cache_write_tokens"])
            + integer(row["reasoning_tokens"])
        )
        for target in (item, totals):
            target["events"] += 1
            target["tool_count"] += tool_count
            target["api_call_count"] += api_calls
            if completed:
                target["completed"] += 1
            if failed:
                target["failed"] += 1
        outcome = "failed" if failed else "completed" if completed else "open"
        recent.append(
            {
                "ts": iso_timestamp(float(row["started_at"])),
                "session_id": str(row["id"]),
                "source": str(row["source"] or ""),
                "outcome": outcome,
                "message_preview": (
                    f"{str(row['source'] or 'session')} via "
                    f"{str(row['model'] or 'unknown model')}"
                )[:240],
                "response_preview": f"{total_tokens} tokens, {api_calls} API calls",
                "tool_count": tool_count,
            }
        )
    return recent


def tail_file_text(path: Path, *, max_bytes: int = 128 * 1024) -> str:
    with path.open("rb") as handle:
        try:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes), os.SEEK_SET)
        except OSError:
            pass
        return handle.read(max_bytes).decode("utf-8", errors="replace")


def read_node_log_stats(raw_status: dict[str, Any]) -> dict[str, Any]:
    channels = {
        "attention": raw_status.get("attention_log_file"),
        "hermes_errors": raw_status.get("hermes_errors_log_file"),
        "hermes_gateway": raw_status.get("hermes_gateway_log_file"),
        "hermes_agent": raw_status.get("hermes_agent_log_file"),
        "runtime": raw_status.get("runtime_log_file"),
        "management": raw_status.get("log_file"),
    }
    result: dict[str, Any] = {
        "channels": {},
        "totals": {"warnings": 0, "errors": 0, "tracebacks": 0},
    }
    for name, raw_path in channels.items():
        path_text = str(raw_path or "").strip()
        channel = {
            "path": path_text,
            "available": False,
            "warnings": 0,
            "errors": 0,
            "tracebacks": 0,
            "last_line": "",
        }
        if path_text:
            path = Path(path_text)
            if path.exists() and path.is_file():
                try:
                    text = tail_file_text(path)
                    lines = [line for line in text.splitlines() if line.strip()]
                    channel["available"] = True
                    channel["warnings"] = sum(1 for line in lines if "WARNING" in line)
                    channel["errors"] = sum(1 for line in lines if "ERROR" in line)
                    channel["tracebacks"] = sum(1 for line in lines if "Traceback" in line)
                    channel["last_line"] = lines[-1][-240:] if lines else ""
                except Exception as exc:
                    channel["error"] = str(exc)
        for key in ("warnings", "errors", "tracebacks"):
            result["totals"][key] += int(channel[key])
        result["channels"][name] = channel
    return result


def discover_nodes(settings: BridgeSettings) -> list[str]:
    names: set[str] = set()
    registry_path = settings.agents_root / "registry.json"
    if registry_path.exists() and registry_path.is_file():
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            clones = payload.get("clones") if isinstance(payload, dict) else None
            if isinstance(clones, dict):
                for key, value in clones.items():
                    if isinstance(key, str):
                        names.add(key)
                    if isinstance(value, dict) and isinstance(value.get("clone_name"), str):
                        names.add(value["clone_name"])
        except Exception:
            pass

    env_root = settings.agents_root / "envs"
    if env_root.exists():
        for path in env_root.glob("*.env"):
            names.add(path.stem)

    nodes_root = settings.agents_root / "nodes"
    if nodes_root.exists():
        for path in nodes_root.iterdir():
            if path.is_dir():
                names.add(path.name)

    normalized: list[str] = []
    for raw in sorted(names):
        try:
            normalized.append(validate_node_id(raw))
        except BridgeError:
            continue
    if "orchestrator" in normalized:
        normalized.remove("orchestrator")
        normalized.insert(0, "orchestrator")
    return normalized


def build_prompt_from_chat_payload(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise BridgeError("invalid_chat_payload", "Chat completion payload must include messages.")

    lines: list[str] = [
        "You are serving Space Agent through the Hermes Orchestrator bridge.",
        "Answer the user's latest request using Hermes Agent capabilities.",
        "",
        "Space Agent browser execution protocol:",
        "- To run browser JavaScript, output one short staging sentence, then a line exactly _____javascript, then JavaScript only.",
        "- Do not wrap executable JavaScript in Markdown fences.",
        "- For new widgets, use exactly: return await space.current.renderWidget({ id, name, cols, rows, renderer })",
        "- The renderer must be an async function receiving parent, for example renderer: async (parent) => { ... }.",
        "- Do not use title/render keys for renderWidget; use id/name/cols/rows/renderer.",
        "- Inside renderer, use DOM APIs on parent; do not invent space.onUnload or other unlisted Space APIs.",
        "- Stop at the final JavaScript character after an execution block.",
        "",
        "Conversation:",
    ]
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip() or "user"
        content = normalize_chat_content(message.get("content"))
        if content:
            lines.append(f"{role}: {content}")
    prompt = "\n".join(lines).strip()
    if not prompt:
        raise BridgeError("invalid_chat_payload", "Chat completion payload did not contain readable text.")
    return prompt


def normalize_chat_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text") or "").strip())
                elif "text" in item:
                    parts.append(str(item.get("text") or "").strip())
            elif item is not None:
                parts.append(str(item).strip())
        return "\n".join(part for part in parts if part)
    if content is None:
        return ""
    return str(content).strip()


def run_options_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    options: dict[str, Any] = {}
    provider = str(payload.get("provider") or "").strip()
    if provider:
        options["provider"] = provider
    model = str(payload.get("model") or "").strip()
    if model:
        options["model"] = model
    reasoning_effort = str(payload.get("reasoning_effort") or "").strip()
    if reasoning_effort:
        options["reasoning_effort"] = reasoning_effort
        options["reasoning"] = {"effort": reasoning_effort}
    timeout_raw = payload.get("timeout_sec")
    if timeout_raw is None:
        timeout_raw = payload.get("timeout")
    if timeout_raw is not None:
        try:
            options["timeout_sec"] = max(1.0, float(timeout_raw))
        except (TypeError, ValueError):
            pass
    return options or None


def wants_async_task(payload: dict[str, Any]) -> bool:
    return any(
        coerce_bool(payload.get(key), default=False)
        for key in ("async", "background", "stream_events")
    )


def run_timeout_sec(run_options: dict[str, Any] | None, fallback: float) -> float:
    if isinstance(run_options, dict):
        raw = run_options.get("timeout_sec") or run_options.get("timeout")
        if raw is not None:
            try:
                return max(1.0, float(raw))
            except (TypeError, ValueError):
                pass
    return fallback


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        env[key] = value
    return env


def host_resources_snapshot(settings: BridgeSettings) -> dict[str, Any]:
    """Read a lightweight, dependency-free snapshot of the bridge host VM."""
    memory = read_meminfo()
    disk = shutil.disk_usage(settings.repo_root)
    uptime_seconds = read_uptime_seconds()
    load1, load5, load15 = read_load_average()
    network = read_network_totals()
    total_disk = int(disk.total)
    used_disk = int(disk.used)
    return {
        "schema": "hermes.space_ui.host_resources.v1",
        "timestamp": utc_now(),
        "source": "wasm-agent-bridge bridge host",
        "host": {
            "hostname": socket.gethostname(),
            "root": str(settings.repo_root),
        },
        "cpu": {
            "percent": sample_cpu_percent(),
            "cores": os.cpu_count() or 1,
            "load_avg": {
                "1m": load1,
                "5m": load5,
                "15m": load15,
            },
        },
        "memory": memory["memory"],
        "swap": memory["swap"],
        "disk": {
            "path": str(settings.repo_root),
            "total_bytes": total_disk,
            "used_bytes": used_disk,
            "free_bytes": int(disk.free),
            "percent": percent(used_disk, total_disk),
        },
        "processes": {
            "count": count_processes(),
        },
        "uptime": {
            "seconds": uptime_seconds,
            "display": format_duration(uptime_seconds),
        },
        "network": network,
    }


def read_cpu_totals() -> tuple[int, int] | None:
    try:
        line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
    except Exception:
        return None
    parts = line.split()
    if not parts or parts[0] != "cpu":
        return None
    try:
        values = [int(value) for value in parts[1:]]
    except ValueError:
        return None
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return idle, total


def sample_cpu_percent() -> float | None:
    before = read_cpu_totals()
    if before is None:
        return None
    time.sleep(0.1)
    after = read_cpu_totals()
    if after is None:
        return None
    idle_delta = after[0] - before[0]
    total_delta = after[1] - before[1]
    if total_delta <= 0:
        return None
    busy_delta = max(0, total_delta - idle_delta)
    return percent(busy_delta, total_delta)


def read_meminfo() -> dict[str, dict[str, int | float | None]]:
    values: dict[str, int] = {}
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
    except Exception:
        lines = []
    for line in lines:
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        raw = rest.strip().split()
        if not raw:
            continue
        try:
            values[key] = int(raw[0]) * 1024
        except ValueError:
            continue

    mem_total = values.get("MemTotal", 0)
    mem_available = values.get("MemAvailable", values.get("MemFree", 0))
    mem_used = max(0, mem_total - mem_available)
    swap_total = values.get("SwapTotal", 0)
    swap_free = values.get("SwapFree", 0)
    swap_used = max(0, swap_total - swap_free)
    return {
        "memory": {
            "total_bytes": mem_total,
            "available_bytes": mem_available,
            "used_bytes": mem_used,
            "percent": percent(mem_used, mem_total),
        },
        "swap": {
            "total_bytes": swap_total,
            "free_bytes": swap_free,
            "used_bytes": swap_used,
            "percent": percent(swap_used, swap_total),
        },
    }


def read_uptime_seconds() -> int | None:
    try:
        text = Path("/proc/uptime").read_text(encoding="utf-8").split()[0]
        return int(float(text))
    except Exception:
        return None


def read_load_average() -> tuple[float | None, float | None, float | None]:
    try:
        load1, load5, load15 = os.getloadavg()
        return round(load1, 2), round(load5, 2), round(load15, 2)
    except OSError:
        return None, None, None


def count_processes() -> int:
    proc = Path("/proc")
    try:
        return sum(1 for path in proc.iterdir() if path.name.isdigit())
    except Exception:
        return 0


def read_network_totals() -> dict[str, int]:
    rx_bytes = 0
    tx_bytes = 0
    try:
        lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
    except Exception:
        lines = []
    for line in lines:
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        if name.strip() == "lo":
            continue
        parts = rest.split()
        if len(parts) < 16:
            continue
        try:
            rx_bytes += int(parts[0])
            tx_bytes += int(parts[8])
        except ValueError:
            continue
    return {
        "rx_bytes": rx_bytes,
        "tx_bytes": tx_bytes,
    }


def percent(used: int | float, total: int | float) -> float | None:
    if not total:
        return None
    return round(max(0.0, min(100.0, float(used) * 100.0 / float(total))), 1)


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    remaining = max(0, int(seconds))
    days, remaining = divmod(remaining, 86400)
    hours, remaining = divmod(remaining, 3600)
    minutes, _ = divmod(remaining, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def sanitize_space_agent_response(content: str) -> str:
    """Keep Space Agent execution blocks in its native, non-Markdown format."""
    text = str(content or "").strip()
    if not text:
        return text

    if "_____javascript" in text:
        lines = text.splitlines()
        cleaned = [
            line
            for line in lines
            if line.strip() not in {"```", "```javascript", "```js", "```Javascript", "```JavaScript"}
        ]
        return "\n".join(cleaned).strip()

    fenced = re.search(r"```(?:javascript|js)?\s*\n(?P<code>[\s\S]*?)\n```", text, re.IGNORECASE)
    if fenced:
        code = fenced.group("code").strip()
        if "space.current." in code or "space.api." in code or "space.spaces." in code:
            leading = text[: fenced.start()].strip() or "Running this in Space now..."
            return f"{leading}\n_____javascript\n{code}".strip()

    return text
