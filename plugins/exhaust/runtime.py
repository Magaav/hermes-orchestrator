"""Runtime for the Hermes exhaust plugin.

This plugin stays inside the public Hermes plugin interface:

- ctx.register_command for /exhaust and /bruteforce
- ctx.register_tool for capability inventory
- pre_gateway_dispatch for gateway command-to-agent rewrite
- pre_llm_call / transform_tool_result / post_tool_call observers

It does not patch Hermes core and does not mutate runtime state outside logs.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


PLUGIN_NAME = "exhaust"
ENABLE_ENV = "PLUGINS_EXHAUST"
PASSIVE_ENV = "PLUGINS_EXHAUST_PASSIVE"
MAX_ATTEMPTS_ENV = "PLUGINS_EXHAUST_MAX_ATTEMPTS"
MAX_NUDGES_ENV = "PLUGINS_EXHAUST_MAX_TOOL_NUDGES"
MAX_SECONDS_ENV = "PLUGINS_EXHAUST_MAX_SECONDS"

EXHAUST_MARKER = "HERMES_EXHAUST_MODE=active"
TRUTHY = {"1", "true", "yes", "on"}
FALSY = {"0", "false", "no", "off", ""}

DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_MAX_TOOL_NUDGES = 3
DEFAULT_MAX_SECONDS = 900

logger = logging.getLogger("hermes.plugins.exhaust")
_LOG_CONFIGURED = False
_STATE_LOCK = threading.RLock()
_SESSION_STATE: dict[str, dict[str, Any]] = {}


def _is_truthy(value: object) -> bool:
    return str(value or "").strip().lower() in TRUTHY


def _is_falsy(value: object) -> bool:
    return str(value or "").strip().lower() in FALSY


def plugin_enabled() -> bool:
    return _is_truthy(os.getenv(ENABLE_ENV, ""))


def passive_enabled() -> bool:
    raw = os.getenv(PASSIVE_ENV)
    if raw is None:
        return True
    return not _is_falsy(raw)


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 99) -> int:
    try:
        value = int(str(os.getenv(name, "")).strip())
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def max_attempts() -> int:
    return _env_int(MAX_ATTEMPTS_ENV, DEFAULT_MAX_ATTEMPTS, minimum=1, maximum=10)


def max_tool_nudges() -> int:
    return _env_int(MAX_NUDGES_ENV, DEFAULT_MAX_TOOL_NUDGES, minimum=0, maximum=10)


def max_seconds() -> int:
    return _env_int(MAX_SECONDS_ENV, DEFAULT_MAX_SECONDS, minimum=60, maximum=7200)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _node_name() -> str:
    raw = str(os.getenv("NODE_NAME", "") or "").strip()
    if raw:
        return raw
    hermes_home = Path(os.getenv("HERMES_HOME", "") or "")
    parts = hermes_home.parts
    if "nodes" in parts:
        idx = parts.index("nodes")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return "unknown"


def _log_path() -> Path:
    explicit = str(os.getenv("HERMES_EXHAUST_LOG", "") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    node = _node_name()
    if node and node != "unknown":
        return Path("/local/logs/nodes") / node / "plugins" / "exhaust.log"
    return Path("/local/logs/plugins/exhaust.log")


def _configure_logging() -> None:
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        _LOG_CONFIGURED = True
    except Exception:
        logger.debug("exhaust logging setup failed", exc_info=True)


def _session_key(session_id: str = "", task_id: str = "") -> str:
    return str(session_id or task_id or "default").strip() or "default"


def _state_for(session_id: str = "", task_id: str = "") -> dict[str, Any]:
    key = _session_key(session_id, task_id)
    with _STATE_LOCK:
        return _SESSION_STATE.setdefault(
            key,
            {
                "active": False,
                "started_at": "",
                "tool_nudges": 0,
                "tool_calls": [],
                "failures": [],
                "fallback_classes": [],
            },
        )


def _reset_state(session_id: str = "", task_id: str = "") -> dict[str, Any]:
    key = _session_key(session_id, task_id)
    with _STATE_LOCK:
        _SESSION_STATE[key] = {
            "active": True,
            "started_at": _utc_now(),
            "tool_nudges": 0,
            "tool_calls": [],
            "failures": [],
            "fallback_classes": [],
        }
        return _SESSION_STATE[key]


def _classify_tool(tool_name: str) -> str:
    name = str(tool_name or "").lower()
    toolset = ""
    try:
        from tools.registry import registry

        toolset = str(registry.get_toolset_for_tool(name) or "").lower()
    except Exception:
        toolset = ""

    joined = f"{toolset}:{name}"
    if any(token in joined for token in ("browser", "cdp", "playwright")):
        return "browser_or_manual_workflow"
    if "image_generate" in joined or ("image" in joined and any(token in joined for token in ("gen", "generate"))):
        return "image_generation_route"
    if any(token in joined for token in ("web", "search", "http", "fetch")):
        return "web_or_api_retrieval"
    if any(token in joined for token in ("terminal", "shell", "script", "exec")):
        return "command_or_script_route"
    if any(token in joined for token in ("read_file", "search_files", "list", "grep", "skill")):
        return "local_docs_or_skills"
    if any(token in joined for token in ("mcp", "plugin")):
        return "plugin_or_mcp_route"
    if "delegate" in joined or "subagent" in joined:
        return "delegation_route"
    return toolset or "tool_route"


def _looks_like_error_result(result: Any) -> bool:
    if isinstance(result, dict):
        if result.get("error"):
            return True
        if result.get("success") is False or result.get("ok") is False:
            return True
        if result.get("blocked") is True:
            return True
        status = str(result.get("status") or "").strip().lower()
        if status in {"error", "failed", "failure", "blocked"}:
            return True
        return False

    text = str(result or "").strip().lower()
    if not text:
        return False
    return any(
        token in text
        for token in (
            '"error"',
            "tool execution failed",
            "permission denied",
            "authentication required",
            "missing required",
            "does not exist",
            "not available",
            "unavailable",
            "not in my available function set",
            "no api key",
            "no api keys",
            "not found",
            "timed out",
            "timeout",
            "blocked",
        )
    )


def _loads_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _truncate(text: str, limit: int = 400) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _record_tool_observation(
    *,
    tool_name: str,
    args: Dict[str, Any] | None,
    result: Any,
    session_id: str = "",
    task_id: str = "",
    tool_call_id: str = "",
    duration_ms: int = 0,
) -> None:
    state = _state_for(session_id, task_id)
    cls = _classify_tool(tool_name)
    parsed = _loads_json(result) if isinstance(result, str) else result
    is_error = _looks_like_error_result(parsed if parsed is not None else result)
    with _STATE_LOCK:
        state.setdefault("tool_calls", []).append(
            {
                "at": _utc_now(),
                "tool": str(tool_name or ""),
                "class": cls,
                "tool_call_id": str(tool_call_id or ""),
                "duration_ms": int(duration_ms or 0),
                "error": bool(is_error),
            }
        )
        if cls not in state.setdefault("fallback_classes", []):
            state["fallback_classes"].append(cls)
        if is_error:
            state.setdefault("failures", []).append(
                {
                    "at": _utc_now(),
                    "tool": str(tool_name or ""),
                    "class": cls,
                    "tool_call_id": str(tool_call_id or ""),
                    "result_preview": _truncate(str(result), 500),
                }
            )
    logger.info(
        "tool_observed session=%s tool=%s class=%s error=%s duration_ms=%s",
        _session_key(session_id, task_id),
        tool_name,
        cls,
        is_error,
        duration_ms,
    )


def _fallback_classes() -> list[str]:
    return [
        "use a different tool or toolset",
        "use a different plugin or MCP route",
        "use browser/manual workflow instead of an API",
        "use an API or HTTP route instead of browser/manual workflow",
        "search local docs, wiki, skills, or README files before retrying",
        "inspect available commands, scripts, harnesses, and tests",
        "reduce scope and complete a useful partial result",
        "generate a human-escalation artifact with exact missing inputs",
    ]


def _build_exhaust_prompt(task: str, *, trigger: str) -> str:
    task = str(task or "").strip()
    attempts = max_attempts()
    seconds = max_seconds()
    classes = "\n".join(f"- {item}" for item in _fallback_classes())
    return f"""\
{EXHAUST_MARKER}
Trigger: {trigger}
Task: {task}

Run this task in structured capability-exhaustion mode.

This is not blind retry spam. Before declaring failure, prove that you inspected
the available capability surface and attempted meaningfully distinct recovery
paths inside the configured budget.

Budget and stop rules:
- Maximum distinct fallback attempts: {attempts}
- Soft wall-clock budget: {seconds} seconds, unless the host/task budget is lower
- Stop only on success, safety/policy boundary, missing required user input,
  missing required credentials, or budget exhaustion
- Do not retry destructive operations unless the user explicitly authorized the
  operation and the retry changes the approach safely
- Do not guess credentials, bypass permissions, or weaken Hermes safety policy

Protocol:
1. Detect the current blocker or likely failure mode. Summarize it in one short paragraph.
2. Call exhaust_inventory before the first fallback unless you already have a
   fresh inventory from this turn.
3. Build a compact fallback graph with distinct fallback classes. Include why
   each path is different.
4. Try up to {attempts} paths. Each path must change a material dimension:
   tool, plugin, route, data source, scope, or human-escalation artifact.
5. Keep a visible attempt ledger: attempted class, action, result, next decision.
6. If blocked by missing credentials or private access, ask for only the exact
   missing input after proving no credential-free route exists.
7. If full success is impossible, deliver the best safe partial result and a
   reproducible next-step plan.

Fallback classes to consider:
{classes}

Final answer format:
- Outcome: success, partial, blocked, or exhausted
- Attempts: concise ledger of distinct fallback paths
- Result or artifact
- Remaining blocker and cleanest next architecture/API/hook change if needed
"""


def _command_usage() -> str:
    return (
        "Usage: /exhaust <task>\n"
        "Alias: /bruteforce <task>\n\n"
        "Runs the task with a bounded recovery protocol: inventory capabilities, "
        "try distinct fallback paths, then stop with a clear outcome."
    )


def make_command_handler(ctx: Any, *, alias: str):
    def _handler(raw_args: str = "") -> str | None:
        if not plugin_enabled():
            return None
        task = str(raw_args or "").strip()
        if not task:
            return _command_usage()
        prompt = _build_exhaust_prompt(task, trigger=f"/{alias}")
        _configure_logging()
        logger.info("activate source=cli_command alias=%s task_preview=%s", alias, _truncate(task, 200))
        try:
            injected = bool(ctx.inject_message(prompt))
        except Exception:
            injected = False
        if injected:
            return f"Exhaust mode activated. Queued task with max_attempts={max_attempts()}."
        return (
            "Exhaust mode could not enqueue an agent turn from this surface. "
            "Resend the task as a normal message using this prompt:\n\n"
            + prompt
        )

    return _handler


def pre_gateway_dispatch(event: Any = None, **_: Any) -> dict[str, Any] | None:
    if not plugin_enabled() or event is None:
        return None
    text = str(getattr(event, "text", "") or "").strip()
    if not text.startswith("/"):
        return None

    first, _, rest = text.partition(" ")
    command = first.lstrip("/").split("@", 1)[0].strip().lower().replace("_", "-")
    if command not in {"exhaust", "bruteforce"}:
        return None
    task = rest.strip()
    if not task:
        return None

    prompt = _build_exhaust_prompt(task, trigger=f"/{command}")
    _configure_logging()
    logger.info("activate source=gateway_command alias=%s task_preview=%s", command, _truncate(task, 200))
    return {"action": "rewrite", "text": prompt}


def pre_llm_call(
    session_id: str = "",
    user_message: str = "",
    conversation_history: list | None = None,
    **_: Any,
) -> dict[str, str] | None:
    if not plugin_enabled():
        return None
    text = str(user_message or "")
    if EXHAUST_MARKER in text:
        _configure_logging()
        _reset_state(session_id=session_id)
        logger.info("activate source=pre_llm_call session=%s", _session_key(session_id))
        return {
            "context": (
                "[Exhaust plugin]\n"
                "The current turn is in exhaust mode. Use exhaust_inventory early, "
                "maintain a distinct fallback ledger, and stop only under the "
                "configured exhaust stop rules."
            )
        }

    if not passive_enabled():
        return None

    with _STATE_LOCK:
        state = dict(_SESSION_STATE.get(_session_key(session_id), {}))
    recent_failures = list(state.get("failures") or [])[-3:]
    if not recent_failures and not _looks_like_blocked_user_message(text):
        return None

    _configure_logging()
    logger.info("passive_context session=%s failures=%d", _session_key(session_id), len(recent_failures))
    return {
        "context": (
            "[Exhaust passive recovery]\n"
            "If this turn is blocked or would otherwise end in failure, inspect "
            "available capabilities with exhaust_inventory, choose a materially "
            "different fallback class, and avoid repeating the same failed path. "
            "Ask for missing credentials only after confirming no credential-free "
            "route can complete a useful partial result."
        )
    }


def _looks_like_blocked_user_message(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        phrase in lowered
        for phrase in (
            "you failed",
            "still failing",
            "try again",
            "stuck",
            "blocked",
            "doesn't work",
            "does not work",
            "couldn't",
            "could not",
            "can't",
            "cannot",
        )
    )


def post_tool_call(
    tool_name: str = "",
    args: Dict[str, Any] | None = None,
    result: Any = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    duration_ms: int = 0,
    **_: Any,
) -> None:
    if not plugin_enabled():
        return
    _configure_logging()
    _record_tool_observation(
        tool_name=tool_name,
        args=args,
        result=result,
        task_id=task_id,
        session_id=session_id,
        tool_call_id=tool_call_id,
        duration_ms=duration_ms,
    )


def transform_tool_result(
    tool_name: str = "",
    args: Dict[str, Any] | None = None,
    result: Any = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    **_: Any,
) -> str | None:
    if not plugin_enabled() or not passive_enabled() or max_tool_nudges() <= 0:
        return None

    parsed = _loads_json(result)
    probe = parsed if parsed is not None else result
    if not _looks_like_error_result(probe):
        return None

    state = _state_for(session_id=session_id, task_id=task_id)
    with _STATE_LOCK:
        if int(state.get("tool_nudges") or 0) >= max_tool_nudges():
            return None
        state["tool_nudges"] = int(state.get("tool_nudges") or 0) + 1

    hint = {
        "mode": "exhaust_passive_recovery",
        "failed_tool": str(tool_name or ""),
        "failed_class": _classify_tool(tool_name),
        "max_distinct_attempts": max_attempts(),
        "instruction": (
            "Before final failure, choose a meaningfully different fallback path. "
            "Use exhaust_inventory if capability surface is unclear. Do not repeat "
            "the same tool/arguments unless the new attempt changes a material input."
        ),
        "safe_fallback_classes": _fallback_classes(),
        "stop_conditions": [
            "success",
            "safety_or_policy_boundary",
            "missing required user input or credentials",
            "configured budget exhausted",
        ],
    }

    _configure_logging()
    logger.info(
        "passive_nudge session=%s tool=%s class=%s nudge=%s/%s",
        _session_key(session_id, task_id),
        tool_name,
        hint["failed_class"],
        state.get("tool_nudges"),
        max_tool_nudges(),
    )

    if isinstance(parsed, dict):
        if "_exhaust_recovery_hint" in parsed:
            return None
        replacement = dict(parsed)
        replacement["_exhaust_recovery_hint"] = hint
        return json.dumps(replacement, ensure_ascii=False)

    if isinstance(result, str):
        return result.rstrip() + "\n\n[exhaust recovery hint]\n" + json.dumps(hint, ensure_ascii=False)
    return None


def on_session_end(
    session_id: str = "",
    completed: bool = True,
    interrupted: bool = False,
    **_: Any,
) -> None:
    if not plugin_enabled():
        return
    key = _session_key(session_id)
    with _STATE_LOCK:
        state = _SESSION_STATE.pop(key, None)
    if not state:
        return
    _configure_logging()
    logger.info(
        "final_outcome session=%s active=%s completed=%s interrupted=%s tool_calls=%d failures=%d classes=%s",
        key,
        bool(state.get("active")),
        bool(completed),
        bool(interrupted),
        len(state.get("tool_calls") or []),
        len(state.get("failures") or []),
        ",".join(state.get("fallback_classes") or []),
    )


EXHAUST_INVENTORY_SCHEMA = {
    "name": "exhaust_inventory",
    "description": (
        "Inventory Hermes capabilities available for structured recovery: tools, "
        "toolsets, plugins, commands, skills, scripts, docs, wiki/memory hints, "
        "and fallback route classes. Use before giving up on a blocked task."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": "summary or full. Summary limits long lists.",
                "enum": ["summary", "full"],
            },
            "query": {
                "type": "string",
                "description": "Optional task or blocker summary to echo into the inventory.",
            },
        },
        "required": [],
    },
}


def exhaust_inventory(args: Dict[str, Any] | None = None, **_: Any) -> str:
    if not plugin_enabled():
        return json.dumps({"enabled": False, "reason": f"{ENABLE_ENV} is not true"})
    args = args if isinstance(args, dict) else {}
    scope = str(args.get("scope") or "summary").strip().lower()
    full = scope == "full"
    payload = {
        "enabled": True,
        "plugin": PLUGIN_NAME,
        "node": _node_name(),
        "query": str(args.get("query") or "").strip(),
        "budget": {
            "max_attempts": max_attempts(),
            "max_tool_nudges": max_tool_nudges(),
            "max_seconds": max_seconds(),
            "passive": passive_enabled(),
        },
        "tools": _inventory_tools(full=full),
        "plugins": _inventory_plugins(full=full),
        "commands": _inventory_commands(full=full),
        "skills": _inventory_skills(full=full),
        "local_routes": _inventory_local_routes(full=full),
        "memory_and_wiki": _inventory_memory_wiki(),
        "recommended_fallback_classes": _fallback_classes(),
        "guardrails": [
            "no infinite loops",
            "no destructive retry without explicit user authorization",
            "no credential guessing",
            "no permission bypass",
            "respect Hermes safety and policy behavior",
        ],
    }
    _configure_logging()
    logger.info("inventory scope=%s query_preview=%s", scope, _truncate(payload["query"], 160))
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _limit(items: list[Any], *, full: bool, n: int = 30) -> list[Any]:
    return items if full else items[:n]


def _inventory_tools(*, full: bool) -> dict[str, Any]:
    try:
        from tools.registry import registry

        toolsets = registry.get_available_toolsets()
        result = {}
        for name, meta in sorted(toolsets.items()):
            tools = sorted(str(item) for item in meta.get("tools") or [])
            result[name] = {
                "available": bool(meta.get("available")),
                "tool_count": len(tools),
                "tools": _limit(tools, full=full, n=25),
                "requirements": list(meta.get("requirements") or []),
            }
        return result
    except Exception as exc:
        return {"error": f"tool inventory unavailable: {type(exc).__name__}: {exc}"}


def _inventory_plugins(*, full: bool) -> dict[str, Any]:
    try:
        from hermes_cli.plugins import get_plugin_manager

        plugins = get_plugin_manager().list_plugins()
        enabled = [p for p in plugins if p.get("enabled")]
        return {
            "enabled_count": len(enabled),
            "discovered_count": len(plugins),
            "enabled": _limit(enabled, full=full, n=25),
            "discovered": _limit(plugins, full=full, n=25),
        }
    except Exception as exc:
        return {"error": f"plugin inventory unavailable: {type(exc).__name__}: {exc}"}


def _inventory_commands(*, full: bool) -> dict[str, Any]:
    commands: dict[str, Any] = {}
    try:
        from hermes_cli.commands import COMMAND_REGISTRY

        builtins = [
            {"name": c.name, "description": c.description, "args_hint": getattr(c, "args_hint", "")}
            for c in COMMAND_REGISTRY
        ]
        commands["builtins"] = _limit(builtins, full=full, n=40)
        commands["builtin_count"] = len(builtins)
    except Exception as exc:
        commands["builtins_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from hermes_cli.plugins import get_plugin_commands

        plugin_commands = [
            {
                "name": name,
                "description": str(meta.get("description") or ""),
                "plugin": str(meta.get("plugin") or ""),
                "args_hint": str(meta.get("args_hint") or ""),
            }
            for name, meta in sorted((get_plugin_commands() or {}).items())
        ]
        commands["plugin"] = _limit(plugin_commands, full=full, n=40)
        commands["plugin_count"] = len(plugin_commands)
    except Exception as exc:
        commands["plugin_error"] = f"{type(exc).__name__}: {exc}"

    return commands


def _inventory_skills(*, full: bool) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        from agent.skill_commands import get_skill_commands

        skill_commands = [
            {"command": key, "name": str(value.get("name") or "")}
            for key, value in sorted((get_skill_commands() or {}).items())
        ]
        result["slash_commands"] = _limit(skill_commands, full=full, n=40)
        result["slash_command_count"] = len(skill_commands)
    except Exception as exc:
        result["slash_commands_error"] = f"{type(exc).__name__}: {exc}"

    skill_roots = [Path("/local/skills"), Path(os.getenv("HERMES_HOME", "")) / "skills"]
    found: list[str] = []
    for root in skill_roots:
        if not root.is_dir():
            continue
        try:
            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / "SKILL.md").exists():
                    found.append(str(child))
        except Exception:
            pass
    result["local_skill_dirs"] = _limit(found, full=full, n=40)
    result["local_skill_dir_count"] = len(found)
    return result


def _inventory_local_routes(*, full: bool) -> dict[str, Any]:
    roots = {
        "scripts": Path("/local/scripts"),
        "plugins": Path("/local/plugins"),
        "docs": Path("/local/docs"),
        "workspace": Path(os.getenv("TERMINAL_CWD", os.getcwd())),
    }
    result: dict[str, Any] = {}
    for label, root in roots.items():
        result[label] = _summarize_root(root, full=full)
    return result


def _summarize_root(root: Path, *, full: bool) -> dict[str, Any]:
    if not root.exists():
        return {"exists": False, "path": str(root)}
    files: list[str] = []
    max_items = 120 if full else 30
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                name
                for name in dirnames
                if not name.startswith(".")
                and name not in {"__pycache__", "node_modules", ".venv", "venv"}
            )
            for filename in sorted(filenames):
                if len(files) >= max_items:
                    break
                if filename.startswith("."):
                    continue
                path = Path(dirpath) / filename
                if path.suffix.lower() not in {".md", ".py", ".sh", ".json", ".yaml", ".yml", ".toml", ".txt"}:
                    continue
                files.append(str(path))
            if len(files) >= max_items:
                break
    except Exception as exc:
        return {"exists": True, "path": str(root), "error": f"{type(exc).__name__}: {exc}"}
    return {"exists": True, "path": str(root), "files": files, "truncated": len(files) >= max_items}


def _inventory_memory_wiki() -> dict[str, Any]:
    data: dict[str, Any] = {
        "wiki_roots": {
            "/local/plugins/private/wiki": Path("/local/plugins/private/wiki").exists(),
            "/local/wiki": Path("/local/wiki").exists(),
        },
        "memory_roots": {
            "/local/memory": Path("/local/memory").exists(),
            "/local/plugins/private/memory": Path("/local/plugins/private/memory").exists(),
        },
    }
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        memory = cfg.get("memory") if isinstance(cfg, dict) else {}
        if isinstance(memory, dict):
            data["configured_memory_provider"] = str(memory.get("provider") or "")
    except Exception:
        pass
    return data


def register(ctx: Any) -> None:
    if not plugin_enabled():
        return

    _configure_logging()
    logger.info(
        "register enabled node=%s passive=%s max_attempts=%s max_tool_nudges=%s",
        _node_name(),
        passive_enabled(),
        max_attempts(),
        max_tool_nudges(),
    )

    ctx.register_tool(
        name="exhaust_inventory",
        toolset="exhaust",
        schema=EXHAUST_INVENTORY_SCHEMA,
        handler=exhaust_inventory,
        description="Inventory available Hermes capabilities for fallback planning.",
    )

    ctx.register_command(
        "exhaust",
        handler=make_command_handler(ctx, alias="exhaust"),
        description="Run a task with structured capability exhaustion.",
        args_hint="<task>",
    )
    ctx.register_command(
        "bruteforce",
        handler=make_command_handler(ctx, alias="bruteforce"),
        description="Alias for /exhaust.",
        args_hint="<task>",
    )

    ctx.register_hook("pre_gateway_dispatch", pre_gateway_dispatch)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("post_tool_call", post_tool_call)
    ctx.register_hook("transform_tool_result", transform_tool_result)
    ctx.register_hook("on_session_end", on_session_end)
