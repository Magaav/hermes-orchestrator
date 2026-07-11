from __future__ import annotations

import json
import hashlib
import os
import fnmatch
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
DEFAULT_TIMEOUT_SEC = 20
DEFAULT_INDEX_TIMEOUT_SEC = 120
DOCKER_IMAGE = "codebase-memory-mcp:local"
DIRECT_EXEC_ENV = "WASM_AGENT_CODE_MEMORY_ALLOW_DIRECT"
CACHE_DIR_ENV = "WASM_AGENT_CODE_MEMORY_CACHE_DIR"
MCP_CACHE_DIR_ENV = "CBM_CACHE_DIR"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "state" / "code-memory-cache"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
ROUTE_CONTRACTS_ENV = "WASM_AGENT_ROUTE_CONTRACTS_PATH"
DEFAULT_ROUTE_CONTRACTS_PATH = PLUGIN_ROOT / "server" / "agent_route_contracts.json"
DEFAULT_EXCLUDE_GLOBS = [
    "public/modules/**/onnx/**",
    "public/modules/**/*.wasm",
    "public/modules/**/tokenizer*.json",
    "public/modules/**/vocab.json",
    "public/modules/**/merges.txt",
    "tools/vendor/**",
    "../../tools/vendor/**",
    "reports/**",
    "../../reports/**",
    "state/**",
    "../../state/**",
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/*.onnx",
    "**/*.wasm",
    "**/*.tar.gz",
    "**/*.zip",
]

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
    source = env if env is not None else os.environ
    return bool((source.get(DIRECT_EXEC_ENV) == "1" and shutil.which(binary_path(env))) or docker_image_available())


def docker_image_available(runner: Runner = default_runner) -> bool:
    if not shutil.which("docker"):
        return False
    try:
        returncode, _stdout, _stderr = runner(["docker", "image", "inspect", DOCKER_IMAGE], Path("/"), 5)
    except Exception:
        return False
    return returncode == 0


def cache_dir() -> Path:
    configured = str(os.environ.get(CACHE_DIR_ENV) or "").strip()
    path = Path(configured).expanduser() if configured else DEFAULT_CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def workspace_fingerprint(contract: dict[str, Any]) -> str:
    root = workspace_root(contract)
    if root is None:
        return ""
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return hashlib.sha256(f"{root}\n{head}\n{dirty}".encode("utf-8", errors="ignore")).hexdigest()


def freshness_marker_path(contract: dict[str, Any]) -> Path:
    root = workspace_root(contract) or Path("workspace")
    return cache_dir() / f"{project_name_for_root(root)}.fingerprint.json"


def freshness(contract: dict[str, Any]) -> dict[str, Any]:
    current = workspace_fingerprint(contract)
    indexed = ""
    try:
        payload = json.loads(freshness_marker_path(contract).read_text(encoding="utf-8"))
        indexed = str(payload.get("workspace_fingerprint") or "") if isinstance(payload, dict) else ""
    except (OSError, json.JSONDecodeError):
        pass
    state = "fresh" if current and indexed == current else "stale" if current and indexed else "unknown"
    return {
        "state": state,
        "trusted": state == "fresh",
        "workspace_fingerprint": current,
        "indexed_fingerprint": indexed,
    }


def record_freshness(contract: dict[str, Any]) -> None:
    fingerprint = workspace_fingerprint(contract)
    if not fingerprint:
        return
    freshness_marker_path(contract).write_text(
        json.dumps({"workspace_fingerprint": fingerprint}, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def route_id(contract: dict[str, Any]) -> str:
    return clipped(str(contract.get("route_id") or ""), 160)


def route_contracts_path() -> Path:
    configured = str(os.environ.get(ROUTE_CONTRACTS_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_ROUTE_CONTRACTS_PATH


def full_source_index_contract(contract: dict[str, Any]) -> dict[str, Any]:
    if isinstance(contract.get("source_index"), dict):
        return contract
    current_route_id = route_id(contract)
    if not current_route_id:
        return contract
    for candidate in route_contracts.load_contracts(route_contracts_path(), PLUGIN_ROOT):
        if route_id(candidate) == current_route_id:
            return candidate
    return contract


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


def source_index_policy(contract: dict[str, Any], *, primitive: str) -> dict[str, Any] | None:
    raw = contract.get("source_index")
    if not isinstance(raw, dict):
        return None
    root = workspace_root(contract)
    if root is None:
        return None
    allowed_roots = contract.get("allowed_read_roots") if isinstance(contract.get("allowed_read_roots"), list) else []
    allowed = []
    for item in allowed_roots[:32]:
        try:
            allowed.append(Path(str(item)).expanduser().resolve())
        except OSError:
            continue
    include_roots: list[str] = []
    raw_includes = raw.get("include_roots") if isinstance(raw.get("include_roots"), list) else []
    for item in raw_includes[:24]:
        raw_item = str(item or "").strip()
        rel = "." if raw_item == "." else route_contracts.rel_path(raw_item)
        if not rel:
            continue
        path = root if rel == "." else (root / rel).resolve()
        if allowed and not any(path == base or base in path.parents for base in allowed):
            continue
        include_roots.append(rel)
    if not include_roots and primitive in {"code.memory.index", "code.memory.search", "code.memory.impact"}:
        return None
    raw_excludes = raw.get("exclude_globs") if isinstance(raw.get("exclude_globs"), list) else []
    excludes = [clipped(str(item or "").strip().replace("\\", "/"), 240) for item in raw_excludes[:80] if str(item or "").strip()]
    for item in DEFAULT_EXCLUDE_GLOBS:
        if item not in excludes:
            excludes.append(item)
    try:
        max_file_bytes = max(1024, min(2_000_000, int(raw.get("max_file_bytes") or 262144)))
    except (TypeError, ValueError):
        max_file_bytes = 262144
    try:
        max_total_bytes = max(max_file_bytes, min(64_000_000, int(raw.get("max_total_bytes") or 8_000_000)))
    except (TypeError, ValueError):
        max_total_bytes = 8_000_000
    try:
        max_results = max(1, min(MAX_RESULTS, int(raw.get("max_results") or 8)))
    except (TypeError, ValueError):
        max_results = 8
    return {
        "include_roots": include_roots,
        "exclude_globs": excludes,
        "max_file_bytes": max_file_bytes,
        "max_total_bytes": max_total_bytes,
        "max_results": max_results,
    }


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


def path_excluded(path: str, exclude_globs: list[str]) -> bool:
    normalized = str(path or "").replace("\\", "/").lstrip("./")
    if not normalized:
        return False
    return any(fnmatch.fnmatch(normalized, pattern.lstrip("./")) for pattern in exclude_globs)


def compact_items(value: Any, *, limit: int, exclude_globs: list[str] | None = None) -> list[dict[str, Any]]:
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
    excludes = exclude_globs or []
    for raw in raw_items:
        if len(items) >= limit:
            break
        if isinstance(raw, dict):
            raw_path = raw.get("file") or raw.get("file_path") or raw.get("path")
            if raw_path and path_excluded(str(raw_path), excludes):
                continue
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


def resource_limited_argv(binary: str, command: str, body: dict[str, Any], root: Path, cache_dir: Path, *, runner: Runner = default_runner) -> list[str] | None:
    if os.environ.get(DIRECT_EXEC_ENV) == "1":
        encoded = json.dumps(body, ensure_ascii=True, separators=(",", ":"))
        return [binary, "cli", command, encoded]
    if docker_image_available(runner):
        docker_body = dict(body)
        docker_body["repo_path"] = "/workspace"
        docker_body["project_path"] = "/workspace"
        docker_body["project"] = "workspace"
        docker_body["project_name"] = "workspace"
        encoded = json.dumps(docker_body, ensure_ascii=True, separators=(",", ":"))
        return [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--memory",
            "768m",
            "--cpus",
            "1.0",
            "--pids-limit",
            "128",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--mount",
            f"type=bind,src={root},dst=/workspace,readonly",
            "--mount",
            f"type=bind,src={cache_dir},dst=/cache",
            "-e",
            f"{MCP_CACHE_DIR_ENV}=/cache",
            "-w",
            "/workspace",
            DOCKER_IMAGE,
            "cli",
            command,
            encoded,
        ]
    return None


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
    policy = source_index_policy(contract, primitive=primitive)
    if primitive in {"code.memory.index", "code.memory.search", "code.memory.impact"} and policy is None:
        return result(ok=False, code="code_memory_index_contract_missing", contract=contract, primitive=primitive)
    binary = binary_path()
    if os.environ.get(DIRECT_EXEC_ENV) != "1" and not docker_image_available(runner):
        return result(
            ok=False,
            code="code_memory_unavailable",
            contract=contract,
            primitive=primitive,
            message="The code-memory Docker image is unavailable and direct code-memory execution is not explicitly enabled.",
        )
    if os.environ.get(DIRECT_EXEC_ENV) == "1" and not shutil.which(binary):
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
    if policy:
        body["source_index"] = policy
        body.setdefault("include_roots", policy["include_roots"])
        body.setdefault("exclude_globs", policy["exclude_globs"])
        body.setdefault("max_file_bytes", policy["max_file_bytes"])
        body.setdefault("max_total_bytes", policy["max_total_bytes"])
        body.setdefault("limit", min(int(body.get("limit") or policy["max_results"]), policy["max_results"]))
    try:
        cache = cache_dir()
        argv = resource_limited_argv(binary, command, body, root, cache, runner=runner)
        if argv is None:
            return result(
                ok=False,
                code="code_memory_unavailable",
                contract=contract,
                primitive=primitive,
                message="Docker is unavailable and direct code-memory execution is not explicitly enabled.",
            )
        returncode, stdout, stderr = runner(argv, root, timeout_sec)
    except subprocess.TimeoutExpired:
        return result(ok=False, code="code_memory_timeout", contract=contract, primitive=primitive)
    except OSError as exc:
        return result(ok=False, code="code_memory_exec_failed", contract=contract, primitive=primitive, message=str(exc))
    parsed = parse_cli_output(stdout, stderr)
    if returncode != 0:
        stderr_text = stderr.strip().lower()
        if returncode in {124, 125, 137, 143} or "out of memory" in stderr_text or "memory" in stderr_text:
            return result(
                ok=False,
                code="code_memory_resource_limit",
                contract=contract,
                primitive=primitive,
                detail={"exit_code": returncode, "stderr": clipped(stderr.strip(), 1000)},
            )
        return result(
            ok=False,
            code="code_memory_cli_failed",
            contract=contract,
            primitive=primitive,
            detail={"exit_code": returncode, "stderr": clipped(stderr.strip(), 1000), "raw": parsed},
        )
    return result(ok=True, code="ok", contract=contract, primitive=primitive, detail={"raw": parsed})


def index(contract: dict[str, Any], body: dict[str, Any], *, runner: Runner = default_runner) -> dict[str, Any]:
    called = cli_call(contract, "index_repository", {}, primitive="code.memory.index", runner=runner, timeout_sec=int(body.get("timeout_sec") or DEFAULT_INDEX_TIMEOUT_SEC))
    if called.get("ok"):
        record_freshness(contract)
    called["freshness"] = freshness(contract)
    return called


def status(contract: dict[str, Any], body: dict[str, Any], *, runner: Runner = default_runner) -> dict[str, Any]:
    called = cli_call(contract, "index_status", {}, primitive="code.memory.status", runner=runner, timeout_sec=int(body.get("timeout_sec") or DEFAULT_TIMEOUT_SEC))
    called["freshness"] = freshness(contract)
    if called.get("ok") and called["freshness"]["state"] != "fresh":
        called["code"] = "code_memory_freshness_unknown" if called["freshness"]["state"] == "unknown" else "code_memory_stale"
        called["ok"] = False
    return called


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
        payload["pattern"] = query
    called = cli_call(contract, command, payload, primitive="code.memory.search", runner=runner, timeout_sec=int(body.get("timeout_sec") or 20))
    if not called.get("ok"):
        return called
    called["freshness"] = freshness(contract)
    if called["freshness"]["state"] == "stale":
        called["ok"] = False
        called["code"] = "code_memory_stale"
        return called
    raw = called.get("raw")
    policy = source_index_policy(contract, primitive="code.memory.search") or {}
    exclude_globs = policy.get("exclude_globs") if isinstance(policy.get("exclude_globs"), list) else []
    items = compact_items(raw, limit=limit, exclude_globs=exclude_globs)
    return {
        **called,
        "query": query,
        "engine": command,
        "items": items,
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
    contract = full_source_index_contract(contract)
    return handler(contract, body, runner=runner)
