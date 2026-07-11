from __future__ import annotations

import hashlib
import json
import shlex
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable


SCHEMA = "hermes.wasm_agent.master_frontier.v3"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "public" / "modules" / "master-frontier" / "cyphers-v3.json"
SYSTEM_PROMPT = (
    "You are wasm-agent's model-led execution head. Use only the supplied compact context. "
    "Return either a complete plain-text answer or exactly one declared @operation line. "
    "Never emit internal tool names, one-character cyphers, action JSON, or prose around an operation. "
    "The host enforces route, read, write, and proof contracts and returns semantic evidence for your next decision."
)


def clipped(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + "..."


@lru_cache(maxsize=1)
def registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def registry_digest() -> str:
    encoded = json.dumps(registry(), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def is_v3(envelope: dict[str, Any] | None) -> bool:
    return isinstance(envelope, dict) and str(envelope.get("schema") or "").strip() == SCHEMA


def reverse_map(name: str) -> dict[str, str]:
    values = registry().get(name) if isinstance(registry().get(name), dict) else {}
    return {str(value): str(key) for key, value in values.items()}


def code_for(name: str, value: str, fallback: str = "_") -> str:
    return reverse_map(name).get(str(value or ""), fallback)


def tool_name(code: str) -> str:
    tools = registry().get("tools") if isinstance(registry().get("tools"), dict) else {}
    return str(tools.get(str(code or "")) or "")


def tool_code(name: str) -> str:
    return code_for("tools", name)


def resolve_tool(value: Any) -> tuple[str, str]:
    candidate = str(value or "").strip()
    mapped = tool_name(candidate)
    if mapped:
        return mapped, candidate
    tools = registry().get("tools") if isinstance(registry().get("tools"), dict) else {}
    if candidate in tools.values():
        return candidate, tool_code(candidate)
    return "", ""


def dictionary_line() -> str:
    data = registry()
    groups: list[str] = []
    for prefix, key in (("v", "protocols"), ("t", "tools"), ("a", "arguments"), ("z", "statuses"), ("p", "proof")):
        values = data.get(key) if isinstance(data.get(key), dict) else {}
        groups.append(prefix + ":" + ",".join(f"{code}={value}" for code, value in values.items()))
    return ";".join(groups)


def operations() -> dict[str, dict[str, Any]]:
    values = registry().get("operations") if isinstance(registry().get("operations"), dict) else {}
    return {str(name): spec for name, spec in values.items() if isinstance(spec, dict)}


def operation_name(tool: str) -> str:
    for name, spec in operations().items():
        if str(spec.get("tool") or "") == str(tool or ""):
            return name
    return ""


def operation_contract_line() -> str:
    signatures: list[str] = []
    for name, spec in operations().items():
        args = spec.get("args") if isinstance(spec.get("args"), dict) else {}
        signatures.append(f"{name}({','.join(str(key) for key in args)})")
    return " ".join(signatures)


def compact_json(value: Any, limit: int = 1200) -> str:
    try:
        text = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        text = str(value or "")
    return clipped(text, limit)


def _continuity(envelope: dict[str, Any]) -> tuple[str, str]:
    state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    continuity = state.get("continuity") if isinstance(state.get("continuity"), dict) else {}
    csc = clipped(continuity.get("csc"), 1200)
    handle = clipped(continuity.get("handle"), 240)
    return csc, handle


def _continuity_line(csc: str) -> str:
    if not csc:
        return ""
    payload = csc[len("CSC/1"):].strip() if csc.startswith("CSC/1") else csc
    return f"c:CSC/1 {payload}".rstrip()


def _resume(envelope: dict[str, Any]) -> str:
    state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    resume = state.get("continuation_context") if isinstance(state.get("continuation_context"), dict) else {}
    if not resume:
        return ""
    return compact_json({
        "r": resume.get("previous_run_id"),
        "o": resume.get("original_objective"),
        "s": resume.get("previous_status"),
        "h": resume.get("resume_key"),
    }, 700)


def _history(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    raw = envelope.get("cypher_history") if isinstance(envelope.get("cypher_history"), list) else []
    limit = int((registry().get("limits") or {}).get("history_steps") or 8)
    return [item for item in raw[-limit:] if isinstance(item, dict)]


def bootstrap(envelope: dict[str, Any], *, receiver: str = "") -> str:
    route = envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else {}
    route_id = str(envelope.get("route_id") or route.get("route_id") or "")
    surface = str(envelope.get("surface") or route.get("surface") or "")
    root = clipped(route.get("workspace_root"), 500)
    csc, continuity_handle = _continuity(envelope)
    history = _history(envelope)
    lines = [
        f"I e:C3 g:{registry_digest()}",
        f"O {clipped(envelope.get('objective'), 2000)}",
        f"R {code_for('routes', route_id)}={route_id}@{root}",
        f"S {code_for('surfaces', surface)}={surface}",
        f"T {operation_contract_line()}",
        "Y final text OR one operation line only; e.g. @search query='term'",
        "P choose semantic operations; host scopes+executes+proves; use returned paths with @read; never claim unseen evidence; inspect kinds=route|files|symbols|proof|cost|transcript|diff|capabilities|runtime_entity; source objects require search/symbol/read",
    ]
    if receiver:
        lines.insert(1, f"V {clipped(receiver, 40)}")
    state_summary = clipped(envelope.get("state_summary"), 500)
    if state_summary:
        lines.append(f"M {state_summary}")
    if csc:
        lines.append(f"C {_continuity_line(csc)}")
    elif continuity_handle:
        lines.append(f"C @{continuity_handle}")
    resume = _resume(envelope)
    if resume:
        lines.append(f"U {resume}")
    for item in history:
        line = clipped(item.get("model_line") or item.get("line"), 500)
        if line:
            lines.append(f"H {line}")
    evidence_limit = int((registry().get("limits") or {}).get("evidence_context_chars") or 20000)
    remaining = evidence_limit
    selected: list[tuple[str, str]] = []
    for item in reversed(history):
        detail = str(item.get("detail") or "").strip()
        if not detail or remaining <= 0:
            continue
        bounded = clipped(detail, remaining)
        selected.append((str(item.get("handle") or "")[:12], bounded))
        remaining -= len(bounded)
    for handle, detail in reversed(selected):
        lines.append(f"E h={handle}\n{detail}")
    return "\n".join(line for line in lines if line.rsplit(" ", 1)[-1].strip())


def transport_text(
    envelope: dict[str, Any],
    *,
    receiver: str,
    render: Callable[..., str],
    limit: int,
    project_task: Callable[[dict[str, Any]], dict[str, Any]],
) -> str:
    if is_v3(envelope):
        return bootstrap(envelope, receiver=receiver)
    provider_envelope = dict(envelope)
    if isinstance(provider_envelope.get("task_contract"), dict):
        task = project_task(provider_envelope)
        task.pop("p", None)
        task.pop("h", None)
        provider_envelope.pop("task_contract", None)
        provider_envelope["p"] = f"{task.get('i')}>{task.get('x')}:{','.join(str(item) for item in task.get('t', [])[:5])}"
    return f"ENV agent-envelope-v1\nRECEIVER {receiver}\nRAW true\n{render(provider_envelope, limit=limit)}"


def decode_args(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    mapping = registry().get("arguments") if isinstance(registry().get("arguments"), dict) else {}
    return {str(mapping.get(str(key)) or key): value for key, value in raw.items()}


def decode_semantic_action(value: Any, *, route_id: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    operation = str(value.get("op") or value.get("operation") or "").strip()
    spec = operations().get(operation)
    if not spec:
        return None
    mapping = spec.get("args") if isinstance(spec.get("args"), dict) else {}
    raw_args = value.get("args") if isinstance(value.get("args"), dict) else {}
    if any(str(key) not in mapping for key in raw_args):
        return None
    args = {str(mapping[key]): item for key, item in raw_args.items()}
    args.setdefault("route_id", route_id)
    tool = str(spec.get("tool") or "")
    if not tool:
        return None
    return {"action": tool, "args": args, "cypher": tool_code(tool), "operation": operation}


def decode_action(value: Any, *, route_id: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    selector = value.get("c") or value.get("action") or value.get("id")
    raw_args = value.get("a") if isinstance(value.get("a"), dict) else value.get("args")
    raw_args = dict(raw_args) if isinstance(raw_args, dict) else {}
    name, code = resolve_tool(selector)
    if not name:
        return None
    args = decode_args(raw_args)
    args.setdefault("route_id", route_id)
    return {"action": name, "args": args, "cypher": code, "operation": operation_name(name)}


def _parsed_json(reply: str) -> dict[str, Any] | None:
    text = str(reply or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0].strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _line_value(value: str) -> Any:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _parsed_operation_line(reply: str) -> dict[str, Any] | None:
    lines = [line.strip() for line in str(reply or "").splitlines() if line.strip().startswith("@")]
    if len(lines) != 1:
        return None
    try:
        parts = shlex.split(lines[0])
    except ValueError:
        return None
    operation = parts[0][1:].strip() if parts else ""
    if operation.endswith("()"):
        operation = operation[:-2].strip()
    if not operation:
        return None
    args: dict[str, Any] = {}
    for field in parts[1:]:
        key, separator, value = field.partition("=")
        if not separator or not key:
            return None
        args[key] = _line_value(value)
    return {"op": operation, "args": args}


def _parsed_cypher_line(reply: str) -> dict[str, Any] | None:
    lines = [line.strip() for line in str(reply or "").splitlines() if line.strip().startswith(">")]
    if len(lines) != 1:
        return None
    text = lines[0]
    try:
        parts = shlex.split(text)
    except ValueError:
        return None
    code = parts[0][1:].strip() if parts else ""
    if not code:
        return None
    args: dict[str, Any] = {}
    for field in parts[1:]:
        key, separator, value = field.partition("=")
        if not separator or not key:
            return None
        args[key] = _line_value(value)
    return {"c": code, "a": args}


def decision(result: dict[str, Any], *, route_id: str) -> dict[str, Any]:
    reply = str(result.get("reply") or "").strip()
    parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else _parsed_operation_line(reply) or _parsed_cypher_line(reply) or _parsed_json(reply)
    parsed = parsed if isinstance(parsed, dict) else {}
    semantic_action = decode_semantic_action(parsed, route_id=route_id)
    if semantic_action:
        return {"kind": "tool", "action": semantic_action, "answer": ""}
    compact_action = decode_action(parsed, route_id=route_id)
    if compact_action:
        return {"kind": "tool", "action": compact_action, "answer": ""}
    actions = parsed.get("actions") if isinstance(parsed.get("actions"), list) else []
    for raw_action in actions[:1]:
        action = decode_semantic_action(raw_action, route_id=route_id) or decode_action(raw_action, route_id=route_id)
        if action:
            return {"kind": "tool", "action": action, "answer": ""}
    raw_tool_shaped = any(line.strip().startswith(("@", ">")) for line in reply.splitlines()) or (
        reply.startswith("{")
        and any(f'"{key}"' in reply for key in ("op", "operation", "c", "a", "action", "id", "actions", "args"))
    )
    tool_shaped = raw_tool_shaped or any(key in parsed for key in ("op", "operation", "c", "a", "action", "id", "actions", "args"))
    if tool_shaped:
        return {"kind": "invalid", "action": None, "answer": "", "code": "cypher_action_invalid"}
    answer = str(parsed.get("f") or parsed.get("answer") or reply).strip()
    return {"kind": "final", "action": None, "answer": answer}


def _payload(tool_result: dict[str, Any]) -> dict[str, Any]:
    result = tool_result.get("result") if isinstance(tool_result.get("result"), dict) else tool_result
    return result if isinstance(result, dict) else {}


def _semantic_value(value: Any) -> str:
    if isinstance(value, str):
        return shlex.quote(value)
    return compact_json(value, 500)


def semantic_action_line(action: dict[str, Any]) -> str:
    operation = str(action.get("operation") or operation_name(str(action.get("action") or "")) or action.get("action") or "tool")
    spec = operations().get(operation) if isinstance(operations().get(operation), dict) else {}
    mapping = spec.get("args") if isinstance(spec.get("args"), dict) else {}
    reverse_args = {str(host): str(semantic) for semantic, host in mapping.items()}
    args = action.get("args") if isinstance(action.get("args"), dict) else {}
    fields = [
        f"{reverse_args.get(str(key), str(key))}={_semantic_value(value)}"
        for key, value in args.items()
        if key != "route_id"
    ]
    return " ".join([operation, *fields])


def observation(tool_result: dict[str, Any]) -> dict[str, Any]:
    name = str(tool_result.get("tool") or tool_result.get("action") or "")
    code = tool_code(name)
    operation = operation_name(name) or name
    payload = _payload(tool_result)
    ok = bool(tool_result.get("ok", True)) and payload.get("ok", True) is not False
    status = "o"
    satisfying = ok
    detail = ""
    count = 0
    payload_code = str(payload.get("code") or tool_result.get("code") or "")
    evidence_class = "found"
    conclusive = False
    if not ok:
        status = "m" if payload_code in {
            "capability_missing",
            "code_memory_stale",
            "code_memory_unavailable",
            "route_contract_missing",
            "unsupported",
        } else "x"
        satisfying = False
        detail = compact_json(payload.get("error") or tool_result.get("error") or payload, 1600)
        evidence_class = (
            "capability_unavailable"
            if payload_code in {"capability_missing", "code_memory_stale", "code_memory_unavailable", "unsupported"}
            else "scope_missing"
            if payload_code in {"route_contract_missing", "scope_missing", "runtime_scope_missing"}
            else "execution_error"
        )
    elif name == "code.memory.search":
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        count = len(items)
        status, satisfying = ("o", True) if items else ("e", False)
        evidence_class = "found" if items else "not_found_trusted"
        conclusive = True
        lines: list[str] = []
        for item in items[:12]:
            if not isinstance(item, dict):
                continue
            path = item.get("file_path") or item.get("file") or item.get("path") or ""
            label = str(item.get("label") or "result").lower()
            fields = [f"{label} path={_semantic_value(path)}"]
            if item.get("line") not in (None, ""):
                fields.append(f"line={item.get('line')}")
            if item.get("name") and str(item.get("name")) != str(path):
                fields.append(f"name={_semantic_value(item.get('name'))}")
            lines.append(" ".join(fields))
        detail = "\n".join(lines)
    elif name in {"lookup.symbol", "lookup.files"}:
        items = payload.get("matches") if isinstance(payload.get("matches"), list) else payload.get("files") if isinstance(payload.get("files"), list) else []
        count = len(items)
        status, satisfying = ("o", True) if items else ("e", False)
        evidence_class = "found" if items else "not_found_trusted"
        conclusive = name == "lookup.symbol"
        lines = []
        for item in items[:20]:
            if not isinstance(item, dict):
                continue
            path = item.get("path") or item.get("file_path") or ""
            fields = [f"path={_semantic_value(path)}"]
            if item.get("line") not in (None, ""):
                fields.append(f"line={item.get('line')}")
            if item.get("text"):
                fields.append(f"text={_semantic_value(clipped(item.get('text'), 300))}")
            if "exists" in item:
                fields.append(f"exists={str(bool(item.get('exists'))).lower()}")
            lines.append(" ".join(fields))
        detail = "\n".join(lines)
    elif name == "file.read_bounded":
        text = str(payload.get("text") or "")
        satisfying = bool(text)
        status = "o" if satisfying else "e"
        evidence_class = "found" if text else "not_found_trusted"
        conclusive = True
        count = len(text)
        file_limit = int((registry().get("limits") or {}).get("file_observation_chars") or 12000)
        detail = clipped(f"{payload.get('path') or ''}\n{text}".strip(), file_limit)
    elif name == "kernel.inspect":
        observations = payload.get("observations") if isinstance(payload.get("observations"), list) else []
        unknowns = payload.get("unknowns") if isinstance(payload.get("unknowns"), list) else []
        count = len(observations)
        satisfying = bool(observations)
        status = "o" if satisfying else "m"
        if unknowns:
            unknown_codes = {str(item.get("code") or "") for item in unknowns if isinstance(item, dict)}
            payload_code = next(iter(sorted(unknown_codes)), "inspect_capability_blocked")
            if observations:
                evidence_class = "ambiguous"
            elif unknown_codes & {"scope_missing", "runtime_scope_missing", "query_missing"}:
                evidence_class = "scope_missing"
            else:
                evidence_class = "capability_unavailable"
            conclusive = False
        detail = compact_json({"observations": observations, "unknowns": unknowns}, 6000)
    elif name == "patch.apply_scoped":
        changed = payload.get("changed_files") if isinstance(payload.get("changed_files"), list) else []
        satisfying = bool(payload.get("applied") and changed)
        status = "o" if satisfying else "e"
        count = len(changed)
        detail = compact_json(payload, 8000)
    elif name == "git.diff_summary":
        changed = payload.get("changed_files") if isinstance(payload.get("changed_files"), list) else []
        satisfying = bool(changed)
        status = "o" if satisfying else "e"
        count = len(changed)
        detail = compact_json(payload, 8000)
    elif name == "proof.collect" or name == "checkpoint.resume":
        events = payload.get("events") if isinstance(payload.get("events"), list) else []
        runs = payload.get("runs") if isinstance(payload.get("runs"), list) else []
        satisfying = bool(events or runs or payload.get("token_ledger"))
        status = "o" if satisfying else "e"
        count = len(events) or len(runs)
        detail = compact_json(payload, 8000)
    elif name == "skill.select":
        skill = payload.get("skill") if isinstance(payload.get("skill"), dict) else payload
        satisfying = bool(skill.get("available"))
        status = "o" if satisfying else "m"
        count = 1 if satisfying else 0
        detail = compact_json({"skill": skill}, 2400)
    else:
        missing = payload.get("missing") if isinstance(payload.get("missing"), list) else []
        if missing or str(payload.get("code") or "") in {"unsupported", "capability_missing", "route_contract_missing"}:
            status, satisfying = "m", False
        changed = payload.get("changed_files") if isinstance(payload.get("changed_files"), list) else []
        count = len(changed) or int(payload.get("count") or 0)
        detail = compact_json(payload, 8000)
        material_fields = (
            "applied",
            "capabilities",
            "changed_files",
            "checks",
            "diff",
            "entity",
            "events",
            "files",
            "items",
            "matches",
            "observations",
            "proof",
            "reply",
            "route_contract",
            "runs",
            "skill",
            "stat",
            "test_results",
            "text",
            "token_ledger",
        )
        has_material = any(bool(payload.get(field)) for field in material_fields)
        if name == "test.run_focused":
            has_material = payload.get("returncode") == 0 and bool(payload.get("check_id"))
        if status == "o" and not has_material:
            status, satisfying = "e", False
    if payload.get("ambiguous") is True or payload_code in {"ambiguous", "multiple_matches"}:
        evidence_class = "ambiguous"
        conclusive = True
    proof_material = compact_json({"t": name, "s": status, "d": detail}, 20000)
    handle = hashlib.sha256(proof_material.encode("utf-8")).hexdigest()[:12]
    line = f"{code}:{status}:n{count}:h{handle}"
    status_name = {"o": "ok", "e": "empty", "m": "missing", "x": "error"}.get(status, status)
    model_line = f"{operation} {status_name} n={count} h={handle} evidence={evidence_class}"
    return {
        "schema": "hermes.wasm_agent.cypher_observation.v3",
        "tool": name,
        "operation": operation,
        "code": code,
        "status": status,
        "satisfying": satisfying,
        "count": count,
        "handle": handle,
        "line": line,
        "model_line": model_line,
        "detail": clipped(detail, int((registry().get("limits") or {}).get("observation_chars") or 18000)),
        "failure_code": payload_code,
        "evidence_class": evidence_class,
        "conclusive": conclusive,
    }


def history_item(action: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    args = action.get("args") if isinstance(action.get("args"), dict) else {}
    compact_args = {code_for("arguments", key, key): value for key, value in args.items() if key != "route_id"}
    return {
        "line": f"{action.get('cypher') or tool_code(str(action.get('action') or ''))}{compact_json(compact_args, 500)}>{observed.get('line')}",
        "model_line": f"{semantic_action_line(action)} -> {observed.get('model_line') or observed.get('line')}",
        "detail": observed.get("detail") or "",
        "operation": action.get("operation") or operation_name(str(action.get("action") or "")),
        "tool": action.get("action") or "",
        "status": observed.get("status") or "",
        "satisfying": bool(observed.get("satisfying")),
        "handle": observed.get("handle") or "",
        "evidence_class": observed.get("evidence_class") or "",
        "conclusive": bool(observed.get("conclusive")),
    }


def with_history(envelope: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    return {**envelope, "cypher_history": history}


def resume_checkpoint(
    envelope: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    code: str,
    calls_used: int,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    remaining = 8000
    for item in reversed([entry for entry in history if isinstance(entry, dict)]):
        if remaining <= 0 or len(evidence) >= 8:
            break
        detail = clipped(item.get("detail"), min(2000, remaining))
        evidence.append({
            "operation": clipped(item.get("operation"), 80),
            "status": clipped(item.get("status"), 20),
            "satisfying": bool(item.get("satisfying")),
            "handle": clipped(item.get("handle"), 40),
            "summary": clipped(item.get("model_line") or item.get("line"), 500),
            "detail": detail,
        })
        remaining -= len(detail)
    evidence.reverse()
    trace_id = clipped(envelope.get("trace_id"), 160)
    return {
        "schema": "hermes.wasm_agent.checkpoint.v3",
        "original_objective": clipped(envelope.get("objective"), 2000),
        "route_id": clipped(envelope.get("route_id"), 160),
        "previous_turn_id": trace_id,
        "resume_key": trace_id or hashlib.sha256(str(envelope.get("objective") or "").encode("utf-8")).hexdigest()[:16],
        "previous_status": "interrupted",
        "failure_code": clipped(code, 120),
        "provider_calls_used": max(0, int(calls_used)),
        "evidence": evidence,
        "instruction": "Resume from these receipts; inspect persisted proof before repeating any side effect.",
    }


def estimate_tokens(text: str) -> int:
    return max(1, (len(str(text or "").encode("utf-8")) + 3) // 4)


def budget_limits(envelope: dict[str, Any]) -> dict[str, int]:
    task = envelope.get("task_contract") if isinstance(envelope.get("task_contract"), dict) else {}
    task_budget = task.get("budget") if isinstance(task.get("budget"), dict) else {}
    request_budget = envelope.get("budget") if isinstance(envelope.get("budget"), dict) else {}
    route = envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else {}
    route_budget = route.get("budget") if isinstance(route.get("budget"), dict) else {}
    if is_v3(envelope):
        total = int(route_budget.get("provider_tokens_max") or task_budget.get("provider_tokens_max") or 8000)
        output = int(request_budget.get("max_output_tokens") or route_budget.get("max_output_tokens") or 32768)
        calls = int(route_budget.get("api_calls_max") or task_budget.get("api_calls_max") or 6)
        absolute_calls = int(
            request_budget.get("api_calls_absolute_max")
            or route_budget.get("api_calls_absolute_max")
            or max(24, calls * 4)
        )
        enforcement = str(
            request_budget.get("enforcement")
            or request_budget.get("mode")
            or task_budget.get("enforcement")
            or task_budget.get("mode")
            or "soft"
        ).strip().lower()
        objective_kind = str(task.get("intent") or envelope.get("objective_kind") or "").strip().lower()
        hard_tokens = enforcement == "hard" or request_budget.get("hard") is True or task_budget.get("hard") is True or objective_kind == "source-investigation"
    else:
        budget = task_budget or request_budget
        total = int(budget.get("provider_tokens_max") or 8000)
        output = int(budget.get("max_output_tokens") or budget.get("head_tokens_max") or 8192)
        calls = int(budget.get("api_calls_max") or 6)
        absolute_calls = int(budget.get("api_calls_absolute_max") or max(24, calls * 4))
        enforcement = str(budget.get("enforcement") or budget.get("mode") or "soft").strip().lower()
        hard_tokens = enforcement == "hard" or budget.get("hard") is True
    call_target = max(1, min(calls, 24))
    return {
        "total": max(1000, total),
        "output": max(256, min(output, 65536)),
        "calls": call_target,
        "absolute_calls": max(call_target, min(absolute_calls, 64)),
        "hard_tokens": hard_tokens,
    }


def usage_total(usages: list[dict[str, Any]]) -> int:
    return sum(int(item.get("total_tokens") or 0) for item in usages if isinstance(item, dict))


def admission(envelope: dict[str, Any], usages: list[dict[str, Any]], prompt: str, *, calls_used: int) -> dict[str, Any]:
    limits = budget_limits(envelope)
    estimated_input = estimate_tokens(prompt)
    reserve_floor = int((registry().get("limits") or {}).get("minimum_output_reserve") or 600)
    reserve = min(limits["output"], max(reserve_floor, estimated_input // 2))
    used = usage_total(usages)
    over_target = used + estimated_input + reserve > limits["total"]
    calls_over_target = calls_used >= limits["calls"]
    calls_available = calls_used < limits["absolute_calls"]
    hard_target_exceeded = limits["hard_tokens"] and (over_target or calls_over_target)
    ok = calls_available and not hard_target_exceeded
    code = (
        "api_call_safety_ceiling"
        if not calls_available
        else "api_call_budget_exhausted"
        if limits["hard_tokens"] and calls_over_target
        else "provider_token_budget_exhausted"
        if over_target and limits["hard_tokens"]
        else "call_target_exceeded"
        if calls_over_target
        else "token_target_exceeded"
        if over_target
        else "ok"
    )
    return {
        "ok": ok,
        "code": code,
        "used": used,
        "estimated_input": estimated_input,
        "reserve": reserve,
        "over_target": over_target,
        "calls_over_target": calls_over_target,
        **limits,
    }
