from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from . import route_contracts


SCHEMA = "hermes.wasm_agent.code_memory.v1"
DEFAULT_BINARY = "codebase-memory-mcp"
REPO_LOCAL_BINARY = Path(__file__).resolve().parents[4] / "tools" / "vendor" / "codebase-memory-mcp" / "v0.8.1" / "codebase-memory-mcp"
MAX_QUERY_CHARS = 500
MAX_RESULTS = 20

Runner = Callable[[list[str], Path, int], tuple[int, str, str]]


def clipped(value: str, limit: int) -> str:
    return route_contracts.clipped(value, limit)


def binary_path(env: dict[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    configured = str(source.get("WASM_AGENT_CODE_MEMORY_BIN") or source.get("CODEBASE_MEMORY_MCP_BIN") or "").strip()
    if configured:
        return configured
    if REPO_LOCAL_BINARY.exists():
        return str(REPO_LOCAL_BINARY)
    return DEFAULT_BINARY


def default_runner(argv: list[str], cwd: Path, timeout_sec: int) -> tuple[int, str, str]:
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout_sec,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def tool_available(env: dict[str, str] | None = None) -> bool:
    return bool(shutil.which(binary_path(env)))


def route_id(contract: dict[str, Any]) -> str:
    return clipped(str(contract.get("route_id") or ""), 160)


def workspace_root(contract: dict[str, Any]) -> Path | None:
    raw = str(contract.get("workspace_root") or contract.get("cwd") or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw).expanduser().resolve()
    except OSError:
        return None
    return path if path.exists() and path.is_dir() else None


def project_name_for_root(root: Path) -> str:
    raw = str(root).strip().strip("/")
    return clipped(raw.replace("/", "-") or root.name, 240)


def parse_cli_output(stdout: str, stderr: str) -> Any:
    text = stdout.strip()
    if not text:
        return {"stderr": clipped(stderr.strip(), 2000)} if stderr.strip() else {}
    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if not candidate.startswith(("{", "[")):
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": clipped(text, 4000)}


def compact_items(value: Any, *, limit: int) -> list[dict[str, Any]]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, dict):
        for key in ("results", "nodes", "items", "matches", "changes", "affected"):
            if isinstance(value.get(key), list):
                raw_items = value[key]
                break
        else:
            raw_items = []
    else:
        raw_items = []
    items: list[dict[str, Any]] = []
    for raw in raw_items[:limit]:
        if isinstance(raw, dict):
            item: dict[str, Any] = {}
            for key in ("label", "kind", "type", "name", "qualified_name", "file", "file_path", "path", "line", "risk", "score"):
                if key in raw and raw[key] not in (None, "", [], {}):
                    item[key] = raw[key] if isinstance(raw[key], (int, float, bool)) else clipped(str(raw[key]), 240)
            if not item:
                item["summary"] = clipped(json.dumps(raw, ensure_ascii=True, sort_keys=True), 500)
            items.append(item)
        elif str(raw or "").strip():
            items.append({"summary": clipped(str(raw), 500)})
    return items


def result(
    *,
    ok: bool,
    code: str,
    contract: dict[str, Any],
    primitive: str,
    detail: dict[str, Any] | None = None,
    message: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "code": code,
        "schema": SCHEMA,
        "primitive": primitive,
        "route_id": route_id(contract),
    }
    if message:
        payload["message"] = clipped(message, 500)
    if detail:
        payload.update(detail)
    return payload


def cli_call(
    contract: dict[str, Any],
    command: str,
    payload: dict[str, Any],
    *,
    primitive: str,
    runner: Runner = default_runner,
    timeout_sec: int = 20,
) -> dict[str, Any]:
    root = workspace_root(contract)
    if root is None:
        return result(ok=False, code="route_workspace_missing", contract=contract, primitive=primitive)
    binary = binary_path()
    if not shutil.which(binary):
        return result(
            ok=False,
            code="code_memory_unavailable",
            contract=contract,
            primitive=primitive,
            message="codebase-memory-mcp binary is not installed or not on PATH.",
        )
    body = dict(payload)
    project = project_name_for_root(root)
    body.setdefault("repo_path", str(root))
    body.setdefault("project_path", str(root))
    body.setdefault("project", project)
    body.setdefault("project_name", project)
    argv = [binary, "cli", command, json.dumps(body, ensure_ascii=True, separators=(",", ":"))]
    try:
        returncode, stdout, stderr = runner(argv, root, timeout_sec)
    except subprocess.TimeoutExpired:
        return result(ok=False, code="code_memory_timeout", contract=contract, primitive=primitive)
    except OSError as exc:
        return result(ok=False, code="code_memory_exec_failed", contract=contract, primitive=primitive, message=str(exc))
    parsed = parse_cli_output(stdout, stderr)
    if returncode != 0:
        return result(
            ok=False,
            code="code_memory_cli_failed",
            contract=contract,
            primitive=primitive,
            detail={"exit_code": returncode, "stderr": clipped(stderr.strip(), 1000), "raw": parsed},
        )
    return result(ok=True, code="ok", contract=contract, primitive=primitive, detail={"raw": parsed})


def index(contract: dict[str, Any], body: dict[str, Any], *, runner: Runner = default_runner) -> dict[str, Any]:
    return cli_call(contract, "index_repository", {}, primitive="code.memory.index", runner=runner, timeout_sec=int(body.get("timeout_sec") or 120))


def status(contract: dict[str, Any], body: dict[str, Any], *, runner: Runner = default_runner) -> dict[str, Any]:
    return cli_call(contract, "index_status", {}, primitive="code.memory.status", runner=runner, timeout_sec=int(body.get("timeout_sec") or 20))


def search(contract: dict[str, Any], body: dict[str, Any], *, runner: Runner = default_runner) -> dict[str, Any]:
    query = clipped(str(body.get("query") or body.get("name_pattern") or body.get("pattern") or "").strip(), MAX_QUERY_CHARS)
    limit = max(1, min(MAX_RESULTS, int(body.get("limit") or 8)))
    if not query:
        return result(ok=False, code="query_missing", contract=contract, primitive="code.memory.search")
    command = "search_graph" if body.get("structural", True) is not False else "search_code"
    payload = {"limit": limit}
    if command == "search_graph":
        payload["name_pattern"] = query
        if body.get("label"):
            payload["label"] = clipped(str(body.get("label")), 80)
        if body.get("file_pattern"):
            payload["file_pattern"] = clipped(str(body.get("file_pattern")), 240)
    else:
        payload["query"] = query
    called = cli_call(contract, command, payload, primitive="code.memory.search", runner=runner, timeout_sec=int(body.get("timeout_sec") or 20))
    if not called.get("ok"):
        return called
    raw = called.get("raw")
    return {
        **called,
        "query": query,
        "engine": command,
        "items": compact_items(raw, limit=limit),
        "raw": raw if bool(body.get("include_raw")) else None,
    }


def impact(contract: dict[str, Any], body: dict[str, Any], *, runner: Runner = default_runner) -> dict[str, Any]:
    limit = max(1, min(MAX_RESULTS, int(body.get("limit") or 12)))
    called = cli_call(contract, "detect_changes", {"limit": limit}, primitive="code.memory.impact", runner=runner, timeout_sec=int(body.get("timeout_sec") or 30))
    if not called.get("ok"):
        return called
    raw = called.get("raw")
    return {
        **called,
        "items": compact_items(raw, limit=limit),
        "raw": raw if bool(body.get("include_raw")) else None,
    }


TOOLS = {
    "code.memory.index": index,
    "code.memory.status": status,
    "code.memory.search": search,
    "code.memory.impact": impact,
}


def execute(tool_id: str, contract: dict[str, Any], body: dict[str, Any], *, runner: Runner = default_runner) -> dict[str, Any]:
    handler = TOOLS.get(tool_id)
    if handler is None:
        return result(ok=False, code="code_memory_tool_unknown", contract=contract, primitive=tool_id)
    return handler(contract, body, runner=runner)
