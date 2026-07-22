from __future__ import annotations

import re
from typing import Any, Callable

from .. import authority, code_memory, evidence, repository_reads
from . import decision_record, executive, policy, task_policy


SYMBOL_RE = re.compile(r"^(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)|^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=")


def _source_focus(matches: list[dict[str, Any]], route: dict[str, Any]) -> dict[str, Any]:
    if not matches:
        return {}
    owner = str(matches[0].get("path") or "")
    try:
        file_path, relative_path = repository_reads.resolve(route, owner)
    except repository_reads.RepositoryReadError:
        return {}
    policy = route.get("source_index") if isinstance(route.get("source_index"), dict) else {}
    try:
        total_limit = max(1024, min(64_000_000, int(policy.get("max_total_bytes") or 8_000_000)))
        scan_limit = max(1024, min(total_limit, int(
            policy.get("max_scan_bytes_per_file") or policy.get("max_file_bytes") or 262144,
        )))
    except (TypeError, ValueError):
        scan_limit = 262144
    file_bytes = file_path.stat().st_size
    scan: dict[str, Any] = {}
    symbols = []
    with file_path.open("rb") as handle:
        for index, raw_line, _line_clipped in repository_reads.iter_bounded_lines(
            handle, max_bytes=None if file_bytes <= scan_limit else scan_limit,
            max_line_bytes=evidence.MAX_SEARCH_LINE_BYTES, stats=scan,
        ):
            if len(symbols) >= 16:
                continue
            found = SYMBOL_RE.match(raw_line.decode("utf-8", "replace"))
            name = (found.group(1) or found.group(2)) if found else ""
            if name:
                symbols.append({"name": name, "line": index})
    scan_truncated = file_bytes > int(scan.get("bytes_scanned") or 0)
    line_count = int(scan.get("lines_scanned") or 0) if not scan_truncated else 0
    hit_lines = sorted({int(item.get("line") or 1) for item in matches if item.get("path") == owner})
    ranges = []
    for line in hit_lines[:8]:
        start = max(1, line - 20)
        end = min(line_count, line + 60) if line_count else line + 60
        if ranges and start <= ranges[-1]["end_line"] + 10:
            ranges[-1]["end_line"] = max(ranges[-1]["end_line"], end)
        else:
            ranges.append({"start_line": start, "end_line": end})
    related = sorted({str(item.get("path")) for item in matches if item.get("path") != owner and ("test" in str(item.get("path")).lower() or "spec" in str(item.get("path")).lower())})[:6]
    return {
        "owner_file": relative_path,
        "line_count": line_count,
        "key_symbols": symbols,
        "suggested_ranges": ranges[:5],
        "related_tests": related,
        "scan_truncated": scan_truncated,
    }


def execute(name: str, arguments: dict[str, Any], route: dict[str, Any], *, invoke: Callable[[str, dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    if not policy.allowed(name):
        return {"ok": False, "code": "tool_not_allowed", "summary": f"V5 does not recognize {name}."}
    if not policy.allowed(name, route):
        required = authority.required_capability(name)
        return {
            "ok": False,
            "code": "capability_denied",
            "summary": f"The resolved route and task do not authorize {name}.",
            "tool": name,
            "required_capability": required,
        }
    if name == "checkpoint":
        available = {item["name"] for item in policy.descriptors_for(route)}
        capsule = executive.reconcile(arguments, available_tools=available)
        if not executive.project(capsule):
            return {
                "ok": False,
                "code": "checkpoint_empty",
                "tool": name,
                "summary": "checkpoint requires at least one durable executive field or outcome.",
            }
        if task_policy.requires_decision(route):
            _record, missing = decision_record.validate(capsule.get("decision"))
            if missing:
                return {
                    "ok": False, "code": "decision_record_invalid", "tool": name,
                    "missing": missing,
                    "summary": "Planning checkpoint lacks required operational decision fields: " + ", ".join(missing) + ".",
                }
        return {"ok": True, "code": "ok", "tool": name, "executive": capsule, "summary": "Updated the model-owned executive capsule."}
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
        try:
            result = repository_reads.read_lines(
                route, str(arguments.get("path") or ""),
                start_line=int(arguments.get("start_line") or 1),
                end_line=int(arguments["end_line"]) if arguments.get("end_line") is not None else None,
            )
        except (TypeError, ValueError) as exc:
            return {"ok": False, "code": "file_read_range_invalid", "summary": "Read line bounds must be integers."}
        except repository_reads.RepositoryReadError as exc:
            return {"ok": False, "code": exc.code, "summary": str(exc)}
        return {
            **result,
            "summary": f"Read {result['path']} lines {result['start_line']}-{result['end_line']}.",
        }
    if name == "edit":
        operations = arguments.get("operations") if isinstance(arguments.get("operations"), list) else []
        if task_policy.llm_autonomous(route) and task_policy.requires_mutation(route) and arguments.get("dry_run") is True:
            return {
                "ok": False,
                "code": "implementation_dry_run_redundant",
                "summary": "Autonomous implementation edits are already validated atomically; apply the intended durable edit directly.",
            }
        preconditioned_paths: set[str] = set()
        for operation in operations:
            if not isinstance(operation, dict):
                return {"ok": False, "code": "patch_operation_invalid", "summary": "Every edit operation must be an object."}
            op = str(operation.get("op") or "replace").strip().lower()
            path = str(operation.get("path") or "")
            path_parts = [part.lower() for part in path.replace("\\", "/").split("/") if part]
            basename = path_parts[-1] if path_parts else ""
            if op == "create" and (basename.startswith(".tmp") or basename.endswith((".tmp", ".temp"))):
                return {
                    "ok": False,
                    "code": "implementation_artifact_not_durable",
                    "summary": "Autonomous implementation cannot count an explicitly temporary file as a repository mutation.",
                }
            if op == "create" and task_policy.llm_autonomous(route) and task_policy.requires_mutation(route):
                content = str(operation.get("content") or operation.get("text") or "").strip().lower()
                if any(part in {"tmp", "temp"} for part in path_parts[:-1]):
                    return {
                        "ok": False,
                        "code": "implementation_artifact_not_durable",
                        "summary": "Autonomous implementation cannot count a file under an explicitly temporary directory as a repository mutation.",
                    }
                if not content or content in {"placeholder", "todo", "todo.", "tbd", "fixme"}:
                    return {
                        "ok": False,
                        "code": "implementation_placeholder_not_durable",
                        "summary": "An empty or placeholder-only file is not a durable implementation mutation.",
                    }
            if path not in preconditioned_paths:
                if op == "create" and operation.get("expected_absent") is not True:
                    return {"ok": False, "code": "patch_precondition_required", "summary": "Create operations require expected_absent=true."}
                if op != "create" and not re.fullmatch(r"[0-9a-f]{64}", str(operation.get("expected_sha256") or "")):
                    return {"ok": False, "code": "patch_precondition_required", "summary": "Mutating an existing file requires its observed expected_sha256."}
                preconditioned_paths.add(path)
        return invoke("kernel.act", {"local_action": "patch.apply_scoped", "args": {"operations": operations, "dry_run": bool(arguments.get("dry_run"))}})
    if name == "test":
        return invoke("kernel.act", {"local_action": "test.run_focused", "args": {"check_id": str(arguments.get("check_id") or "")}})
    if name == "diff":
        return invoke("kernel.act", {"local_action": "git.diff_summary", "args": {}})
    if name == "prove":
        return invoke("kernel.prove", {})
    target = str(arguments.get("target") or "")
    if target not in {"run", "service", "device", "application", "runtime_entity"}:
        return {"ok": False, "code": "inspect_target_unsupported", "summary": "inspect supports run, service, device, application, or runtime_entity."}
    entity_id = str(arguments.get("id") or "").strip()
    if not entity_id:
        return {"ok": False, "code": "inspect_entity_missing", "summary": "inspect requires an exact routed entity id."}
    route_id = str(route.get("route_id") or "")
    proof_id = str(arguments.get("proof_id") or "").strip()
    action = "runtime.proof.get" if proof_id else "runtime.snapshot.get"
    action_arguments = {"route_id": route_id, "entity_id": entity_id}
    if proof_id:
        action_arguments["proof_id"] = proof_id
    observed = invoke("kernel.inspect", {
        "inspect": ["runtime"],
        "entity": entity_id,
        "runtime_action": {"name": action, "arguments": action_arguments},
    })
    observations = observed.get("observations") if isinstance(observed.get("observations"), list) else []
    runtime_observation = next((item for item in observations if isinstance(item, dict) and item.get("kind") == "runtime_entity"), None)
    runtime_result = runtime_observation.get("result") if isinstance(runtime_observation, dict) and isinstance(runtime_observation.get("result"), dict) else {}
    action_result = runtime_result.get("action_result") if isinstance(runtime_result.get("action_result"), dict) else None
    if action_result is None:
        return observed
    if not action_result.get("ok"):
        return {"ok": False, "code": str(action_result.get("code") or "runtime_action_failed"), "summary": "Bounded runtime evidence is unavailable."}
    compact = action_result.get("snapshot") if action == "runtime.snapshot.get" else action_result.get("proof")
    return {
        "ok": True,
        "code": "ok",
        "summary": "Collected a bounded redacted runtime snapshot." if action == "runtime.snapshot.get" else "Resolved one scoped redacted runtime proof.",
        "runtime": {"action": action, "result": compact if isinstance(compact, dict) else {}},
    }
