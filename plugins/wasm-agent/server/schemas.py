from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


PLUGIN_NAME = "wasm-agent-bridge"
PLUGIN_VERSION = "0.1.0"

ALLOWED_ACTIONS = {
    "inspect_node",
    "tail_logs",
    "restart_node",
    "stop_node",
    "start_node",
    "run_prompt",
    "open_dashboard",
}

MUTATING_ACTIONS = {"restart_node", "stop_node", "start_node", "run_prompt"}

MISSING_TASK_HOOK = {
    "code": "api_server_task_submission_unavailable",
    "message": (
        "Hermes Agent now exposes stable prompt/task submission through the "
        "official API server Runs API. Configure the node API server URL when "
        "the bridge cannot discover it automatically."
    ),
    "requested_hook": (
        "Start the target node's api_server platform and expose "
        "POST /v1/runs plus GET /v1/runs/{run_id} to the bridge."
    ),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def success(data: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": True}
    if data:
        payload.update(data)
    return payload


def error_payload(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }


def node_log_paths(raw_status: dict[str, Any]) -> dict[str, str]:
    return {
        "management": str(raw_status.get("log_file") or ""),
        "runtime": str(raw_status.get("runtime_log_file") or ""),
        "attention": str(raw_status.get("attention_log_file") or ""),
        "hermes_errors": str(raw_status.get("hermes_errors_log_file") or ""),
        "hermes_gateway": str(raw_status.get("hermes_gateway_log_file") or ""),
        "hermes_agent": str(raw_status.get("hermes_agent_log_file") or ""),
        "hermes_dir": str(raw_status.get("hermes_log_dir") or ""),
    }


def action_buttons(node_id: str) -> list[dict[str, Any]]:
    labels = {
        "inspect_node": "Inspect",
        "tail_logs": "Logs",
        "restart_node": "Restart",
        "stop_node": "Stop",
        "start_node": "Start",
        "run_prompt": "Run Prompt",
        "open_dashboard": "Dashboard",
    }
    return [
        {
            "id": f"{node_id}:{action}",
            "action": action,
            "label": labels[action],
            "method": "POST",
            "endpoint": f"/nodes/{node_id}/action",
            "destructive": action in {"restart_node", "stop_node"},
            "mutates_fleet": action in MUTATING_ACTIONS,
            "enabled": True,
            "disabled_reason": "",
            "payload_template": {
                "action": action,
                "payload": {"prompt": ""} if action == "run_prompt" else {},
            },
        }
        for action in [
            "inspect_node",
            "tail_logs",
            "restart_node",
            "stop_node",
            "start_node",
            "run_prompt",
            "open_dashboard",
        ]
    ]


def node_card(node_id: str, raw_status: dict[str, Any]) -> dict[str, Any]:
    container_state = raw_status.get("container_state")
    state = container_state if isinstance(container_state, dict) else {}
    running = bool(state.get("running"))
    activity = raw_status.get("_space_ui_activity")
    if not isinstance(activity, dict):
        activity = {}
    hermes = raw_status.get("_space_ui_hermes")
    if not isinstance(hermes, dict):
        hermes = {}
    if running and bool(activity.get("llm_active")):
        status = "working"
    elif running:
        status = "running"
    else:
        status = str(state.get("status") or "unknown")
    return {
        "schema": "hermes.space_ui.node_card.v1",
        "id": node_id,
        "title": node_id,
        "status": status,
        "running": running,
        "activity": activity,
        "hermes": hermes,
        "runtime": {
            "type": str(raw_status.get("runtime_type") or "unknown"),
            "state_mode": str(raw_status.get("state_mode") or "unknown"),
            "state_code": raw_status.get("state_code"),
            "container_name": str(raw_status.get("container_name") or ""),
        },
        "health": {
            "required_mounts_ok": raw_status.get("required_mounts_ok"),
            "required_mounts_missing": raw_status.get("required_mounts_missing") or [],
            "attention_log": str(raw_status.get("attention_log_file") or ""),
        },
        "paths": {
            "env": str(raw_status.get("env_path") or ""),
            "clone_root": str(raw_status.get("clone_root") or ""),
            "logs": node_log_paths(raw_status),
        },
        "actions": action_buttons(node_id),
        "raw": raw_status,
    }


def logs_panel(node_id: str, raw_logs: dict[str, Any]) -> dict[str, Any]:
    text = str(raw_logs.get("log_text") or "")
    return {
        "schema": "hermes.space_ui.logs_panel.v1",
        "node_id": node_id,
        "lines": raw_logs.get("lines"),
        "channels": {
            "management": str(raw_logs.get("log_file") or ""),
            "runtime": str(raw_logs.get("runtime_log_file") or ""),
            "attention": str(raw_logs.get("attention_log_file") or ""),
            "hermes_errors": str(raw_logs.get("hermes_errors_log_file") or ""),
            "hermes_gateway": str(raw_logs.get("hermes_gateway_log_file") or ""),
            "hermes_agent": str(raw_logs.get("hermes_agent_log_file") or ""),
        },
        "text": text,
        "empty": not bool(text.strip()),
        "raw": raw_logs,
    }


def action_result(
    node_id: str,
    action: str,
    *,
    accepted: bool,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "hermes.space_ui.action_result.v1",
        "node_id": node_id,
        "action": action,
        "accepted": accepted,
        "timestamp": utc_now(),
        "before": before,
        "after": after,
        "result": result or {},
    }


def task_status(
    task_id: str,
    *,
    prompt: str,
    target_node: str | None,
    status: str,
    created_at: str,
    updated_at: str,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "hermes.space_ui.task_status.v1",
        "task_id": task_id,
        "status": status,
        "prompt": prompt,
        "target_node": target_node,
        "created_at": created_at,
        "updated_at": updated_at,
        "result": result or {},
        "error": error,
    }


def dashboard_layout(nodes: list[dict[str, Any]], *, focused_node: str | None = None) -> dict[str, Any]:
    return {
        "schema": "hermes.space_ui.dashboard_layout.v1",
        "title": "Hermes Fleet",
        "generated_at": utc_now(),
        "focused_node": focused_node,
        "sections": [
            {
                "id": "fleet",
                "title": "Fleet",
                "kind": "node_grid",
                "items": nodes,
            },
            {
                "id": "logs",
                "title": "Logs",
                "kind": "logs_panel",
                "source": "GET /nodes/{node_id}/logs",
            },
            {
                "id": "actions",
                "title": "Actions",
                "kind": "action_buttons",
                "source": "node_card.actions",
            },
        ],
    }


JSON_SCHEMAS: dict[str, dict[str, Any]] = {
    "node_card": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "wasm-agent bridge Node Card",
        "type": "object",
        "required": ["schema", "id", "title", "status", "running", "runtime", "actions"],
        "properties": {
            "schema": {"const": "hermes.space_ui.node_card.v1"},
            "id": {"type": "string"},
            "title": {"type": "string"},
            "status": {"type": "string"},
            "running": {"type": "boolean"},
            "activity": {"type": "object"},
            "runtime": {"type": "object"},
            "health": {"type": "object"},
            "paths": {"type": "object"},
            "actions": {"type": "array", "items": {"type": "object"}},
        },
    },
    "logs_panel": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "wasm-agent bridge Logs Panel",
        "type": "object",
        "required": ["schema", "node_id", "channels", "text", "empty"],
        "properties": {
            "schema": {"const": "hermes.space_ui.logs_panel.v1"},
            "node_id": {"type": "string"},
            "lines": {"type": ["integer", "null"]},
            "channels": {"type": "object"},
            "text": {"type": "string"},
            "empty": {"type": "boolean"},
        },
    },
    "action_button": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "wasm-agent bridge Action Button",
        "type": "object",
        "required": ["id", "action", "label", "method", "endpoint", "enabled"],
        "properties": {
            "id": {"type": "string"},
            "action": {"enum": sorted(ALLOWED_ACTIONS)},
            "label": {"type": "string"},
            "method": {"const": "POST"},
            "endpoint": {"type": "string"},
            "destructive": {"type": "boolean"},
            "mutates_fleet": {"type": "boolean"},
            "enabled": {"type": "boolean"},
        },
    },
    "task_status": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "wasm-agent bridge Task Status",
        "type": "object",
        "required": ["schema", "task_id", "status", "prompt", "created_at", "updated_at"],
        "properties": {
            "schema": {"const": "hermes.space_ui.task_status.v1"},
            "task_id": {"type": "string"},
            "status": {"enum": ["queued", "running", "succeeded", "completed", "failed", "cancelled", "unsupported"]},
            "prompt": {"type": "string"},
            "target_node": {"type": ["string", "null"]},
            "result": {"type": "object"},
            "error": {"type": ["object", "null"]},
        },
    },
    "dashboard_layout": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "wasm-agent bridge Dashboard Layout",
        "type": "object",
        "required": ["schema", "title", "generated_at", "sections"],
        "properties": {
            "schema": {"const": "hermes.space_ui.dashboard_layout.v1"},
            "title": {"type": "string"},
            "generated_at": {"type": "string"},
            "focused_node": {"type": ["string", "null"]},
            "sections": {"type": "array", "items": {"type": "object"}},
        },
    },
    "host_resources": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "wasm-agent bridge Host Resources",
        "type": "object",
        "required": ["schema", "timestamp", "host", "cpu", "memory", "disk", "uptime"],
        "properties": {
            "schema": {"const": "hermes.space_ui.host_resources.v1"},
            "timestamp": {"type": "string"},
            "source": {"type": "string"},
            "host": {"type": "object"},
            "cpu": {"type": "object"},
            "memory": {"type": "object"},
            "swap": {"type": "object"},
            "disk": {"type": "object"},
            "processes": {"type": "object"},
            "uptime": {"type": "object"},
            "network": {"type": "object"},
        },
    },
    "node_stats": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "wasm-agent bridge Node Stats",
        "type": "object",
        "required": ["schema", "node_id", "timestamp", "window", "status", "usage", "activity", "logs"],
        "properties": {
            "schema": {"const": "hermes.space_ui.node_stats.v1"},
            "node_id": {"type": "string"},
            "timestamp": {"type": "string"},
            "window": {"type": "object"},
            "status": {"type": "object"},
            "usage": {"type": "object"},
            "activity": {"type": "object"},
            "logs": {"type": "object"},
        },
    },
    "node_create_result": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "wasm-agent bridge Node Create Result",
        "type": "object",
        "required": ["schema", "node_id", "env_path", "env_created", "start"],
        "properties": {
            "schema": {"const": "hermes.space_ui.node_create_result.v1"},
            "node_id": {"type": "string"},
            "env_path": {"type": "string"},
            "env_created": {"type": "boolean"},
            "start": {"type": "object"},
            "node": {"type": ["object", "null"]},
        },
    },
}
