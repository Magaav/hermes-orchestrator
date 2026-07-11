from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable

from .. import code_memory, evidence
from . import policy


SYMBOL_RE = re.compile(r"^(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)|^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=")


def _source_focus(matches: list[dict[str, Any]], route: dict[str, Any]) -> dict[str, Any]:
    if not matches:
        return {}
    owner = str(matches[0].get("path") or "")
    root = Path(str(route.get("workspace_root") or "")).resolve(); file_path = (root / owner).resolve()
    if not owner or not file_path.is_file() or not (file_path == root or root in file_path.parents):
        return {}
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    symbols = []
    for index, line in enumerate(lines, 1):
        found = SYMBOL_RE.match(line)
        name = (found.group(1) or found.group(2)) if found else ""
        if name: symbols.append({"name": name, "line": index})
        if len(symbols) >= 16: break
    hit_lines = sorted({int(item.get("line") or 1) for item in matches if item.get("path") == owner})
    ranges = []
    for line in hit_lines[:8]:
        start, end = max(1, line - 20), min(len(lines), line + 60)
        if ranges and start <= ranges[-1]["end_line"] + 10:
            ranges[-1]["end_line"] = max(ranges[-1]["end_line"], end)
        else:
            ranges.append({"start_line": start, "end_line": end})
    related = sorted({str(item.get("path")) for item in matches if item.get("path") != owner and ("test" in str(item.get("path")).lower() or "spec" in str(item.get("path")).lower())})[:6]
    return {"owner_file": owner, "line_count": len(lines), "key_symbols": symbols, "suggested_ranges": ranges[:5], "related_tests": related}


def execute(name: str, arguments: dict[str, Any], route: dict[str, Any], *, invoke: Callable[[str, dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    if not policy.allowed(name):
        return {"ok": False, "code": "tool_not_allowed", "summary": f"V5 read-only does not allow {name}."}
    if name == "search":
        query = str(arguments.get("query") or "").strip()
        if not query:
            return {"ok": False, "code": "search_query_missing", "summary": "search requires query."}
        packet = evidence.compound_discover({
            "operation_id": "v5-search", "request_id": "v5-search",
            "query": query, "max_results": min(30, max(1, int(arguments.get("limit") or 20))),
        }, route, semantic_search=lambda request: code_memory.execute("code.memory.search", route, request))
        matches = [{"path": item.get("file"), "line": item.get("line"), "symbol": item.get("symbol"), "excerpt": item.get("excerpt")} for item in packet["matches"]]
        return {"ok": True, "code": "ok", "summary": f"Found {len(matches)} bounded source matches.", "focus": _source_focus(matches, route), "matches": matches, "coverage": packet["coverage"], "limitations": packet["limitations"]}
    if name == "read":
        raw_path = str(arguments.get("path") or "").strip()
        root = Path(str(route.get("workspace_root") or "")).resolve()
        path = (root / raw_path).resolve()
        allowed = [Path(str(item)).resolve() for item in route.get("allowed_read_roots") or [root]]
        if not raw_path or not any(path == item or item in path.parents for item in allowed):
            return {"ok": False, "code": "file_read_scope_denied", "summary": "Requested path is outside the routed workspace."}
        if not path.is_file():
            return {"ok": False, "code": "file_read_missing", "summary": "Requested route file does not exist."}
        relative_path = str(path.relative_to(root)).replace("\\", "/") if path == root or root in path.parents else raw_path
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(arguments.get("start_line") or 1)); end = max(start, int(arguments.get("end_line") or min(len(lines), start + 499)))
        bounded_end = min(len(lines), end, start + 999)
        content = "\n".join(f"{index}: {lines[index - 1]}" for index in range(start, bounded_end + 1))
        return {"ok": True, "code": "ok", "summary": f"Read {relative_path} lines {start}-{bounded_end}.", "path": relative_path, "start_line": start, "end_line": bounded_end, "line_count": len(lines), "content": content, "truncated": bounded_end < end or bounded_end < len(lines)}
    target = str(arguments.get("target") or "")
    if target not in {"run", "service", "device", "application", "runtime_entity"}:
        return {"ok": False, "code": "inspect_target_unsupported", "summary": "inspect supports run, service, device, application, or runtime_entity."}
    return invoke("kernel.inspect", {"kind": "runtime_entity", "entity": arguments.get("id") or target, "fields": arguments.get("fields") or []})
