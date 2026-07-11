from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import route_contracts


SCHEMA = "hermes.wasm_agent.entity_resolution.v1"
QUEST_STATE_SCHEMA = "hermes.wasm_agent.quest_state.v1"

KIND_TERMS = (
    "widget",
    "component",
    "module",
    "function",
    "class",
    "route",
    "endpoint",
    "screen",
    "view",
    "panel",
    "tool",
    "code",
    "implementation",
)

QUESTION_TERMS = (
    "what",
    "where",
    "which",
    "show",
    "find",
    "check",
    "describe",
    "list",
    "locate",
)

STOP_WORDS = {
    "a",
    "amazing",
    "an",
    "and",
    "are",
    "can",
    "check",
    "could",
    "criticize",
    "describe",
    "does",
    "for",
    "great",
    "inside",
    "in",
    "into",
    "is",
    "it",
    "list",
    "locate",
    "of",
    "on",
    "out",
    "please",
    "show",
    "the",
    "this",
    "ui",
    "us",
    "what",
    "where",
    "which",
    "with",
    "you",
}


def clipped(value: Any, limit: int = 160) -> str:
    return route_contracts.clipped(str(value or "").strip(), limit)


def normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def singular(value: str) -> str:
    text = str(value or "").lower()
    if text.endswith("ies") and len(text) > 4:
        return f"{text[:-3]}y"
    if text.endswith("s") and len(text) > 4:
        return text[:-1]
    return text


def words(text: str) -> list[str]:
    return [word for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", str(text or "")) if word]


def detect_kind(text: str) -> str:
    lowered = str(text or "").lower()
    for kind in KIND_TERMS:
        if re.search(rf"(?<![a-z0-9_-]){re.escape(kind)}s?(?![a-z0-9_-])", lowered):
            return kind
    return ""


def is_repo_object_question(text: str) -> bool:
    lowered = str(text or "").lower()
    if not detect_kind(lowered):
        return False
    return any(re.search(rf"(?<![a-z0-9_-]){re.escape(term)}(?![a-z0-9_-])", lowered) for term in QUESTION_TERMS)


def envelope_is_repo_object_question(envelope: dict[str, Any]) -> bool:
    return bool(resolve(envelope).get("is_repo_object_question"))


def objective_query(envelope: dict[str, Any]) -> str:
    return clipped(str(resolve(envelope).get("query") or "repo object"), 120)


def split_scope(text: str) -> tuple[str, str]:
    match = re.search(r"\b(?:from|inside|in|within|on)\s+([A-Za-z0-9][A-Za-z0-9_-]*)\b", str(text or ""), flags=re.IGNORECASE)
    if not match:
        return str(text or ""), ""
    before = str(text or "")[: match.start()].strip()
    return before, clipped(match.group(1), 120)


def object_phrase(text: str, kind: str) -> str:
    before_scope, _scope = split_scope(text)
    raw_words = words(before_scope)
    kept: list[str] = []
    for word in raw_words:
        lower = word.lower()
        if lower in STOP_WORDS:
            continue
        if singular(lower) == kind:
            continue
        kept.append(word)
    return clipped(" ".join(kept), 160)


def object_id_from_phrase(phrase: str) -> str:
    token = normalize_token(phrase)
    return clipped(token, 120)


def query_from_parts(object_phrase_value: str, kind: str) -> str:
    object_id = object_id_from_phrase(object_phrase_value)
    if object_id in {"space", "ui", "workspace"}:
        return singular(kind)
    if object_id:
        return object_id
    return singular(kind)


def resolve(envelope: dict[str, Any]) -> dict[str, Any]:
    objective = clipped(envelope.get("objective"), 500)
    kind = detect_kind(objective)
    phrase = object_phrase(objective, kind) if kind else ""
    _before_scope, scope = split_scope(objective)
    query = query_from_parts(phrase, kind)
    object_id = object_id_from_phrase(phrase)
    needs_runtime_scope = bool(scope)
    return {
        "schema": SCHEMA,
        "objective": objective,
        "is_repo_object_question": is_repo_object_question(objective),
        "kind": kind,
        "object_phrase": phrase,
        "object_id": object_id,
        "scope_phrase": scope,
        "scope_id": normalize_token(scope),
        "route_id": clipped(envelope.get("route_id") or envelope.get("route"), 160),
        "query": query,
        "evidence_needed": ["source", "runtime_scope"] if needs_runtime_scope else ["source"],
        "next_tool": "code.memory.search" if query else "",
    }


def evidence_terms(resolved: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in ("object_id", "query", "object_phrase"):
        value = normalize_token(str(resolved.get(key) or ""))
        if value and value not in {"widget", "component", "module", "function", "class", "route", "endpoint", "screen", "view", "panel", "tool", "code", "implementation"}:
            terms.append(value)
    compact_terms: list[str] = []
    for term in terms:
        for part in (term, term.replace("-", ""), term.replace("-", "_")):
            if part and part not in compact_terms:
                compact_terms.append(part)
    return compact_terms


def evidence_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(evidence_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(evidence_text(item) for item in value)
    return normalize_token(str(value or ""))


def evidence_matches(resolved: dict[str, Any], value: Any) -> bool:
    haystack = evidence_text(value)
    if not haystack:
        return False
    terms = evidence_terms(resolved)
    if not terms:
        return True
    return any(term in haystack for term in terms)


def code_memory_result_matches(resolved: dict[str, Any], result: dict[str, Any]) -> bool:
    items = result.get("items") if isinstance(result.get("items"), list) else []
    return any(evidence_matches(resolved, item) for item in items if isinstance(item, dict))


def code_memory_has_object_evidence(envelope: dict[str, Any], local_tool_results: list[dict[str, Any]]) -> bool:
    resolved = resolve(envelope)
    for item in local_tool_results:
        if not isinstance(item, dict) or item.get("tool") != "code.memory.search":
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        if code_memory_result_matches(resolved, result):
            return True
    return False


def needs_runtime_scope_proof(envelope: dict[str, Any]) -> bool:
    resolved = resolve(envelope)
    evidence_needed = resolved.get("evidence_needed") if isinstance(resolved.get("evidence_needed"), list) else []
    return bool(resolved.get("is_repo_object_question") and "runtime_scope" in evidence_needed)


def runtime_scope_proof_satisfied(envelope: dict[str, Any], local_tool_results: list[dict[str, Any]]) -> bool:
    resolved = resolve(envelope)
    scope_id = normalize_token(str(resolved.get("scope_id") or ""))
    for item in local_tool_results:
        if not isinstance(item, dict) or item.get("tool") != "kernel.inspect":
            continue
        if not item.get("ok"):
            continue
        if not scope_id:
            return True
        if scope_id in evidence_text(item):
            return True
    return False


def quest_token(value: Any, limit: int = 120) -> str:
    text = normalize_token(str(value or ""))
    return clipped(text, limit)


def quest_state_from_evidence(
    envelope: dict[str, Any],
    local_tool_results: list[dict[str, Any]] | None = None,
    *,
    block_code: str = "",
) -> dict[str, Any]:
    local_tool_results = local_tool_results or []
    resolved = resolve(envelope)
    if not resolved.get("is_repo_object_question"):
        compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
        existing = compact_state.get("quest_state") if isinstance(compact_state.get("quest_state"), dict) else {}
        return existing
    scope_id = quest_token(resolved.get("scope_id"), 80)
    object_id = quest_token(resolved.get("object_id") or resolved.get("query"), 120)
    kind = quest_token(resolved.get("kind"), 40)
    goal_bits = [bit for bit in (scope_id, object_id, kind) if bit]
    known: list[str] = []
    missing: list[str] = []
    paths = source_paths(local_tool_results)
    if paths:
        known.append(f"src:{quest_token(Path(paths[0]).name, 80)}")
    elif code_memory_has_object_evidence(envelope, local_tool_results):
        known.append(f"src:{object_id or kind}")
    if needs_runtime_scope_proof(envelope):
        if runtime_scope_proof_satisfied(envelope, local_tool_results):
            known.append(f"rt:{scope_id or 'scope'}")
        else:
            missing.append(f"rt:{scope_id or 'scope'}")
    next_expected = ""
    if missing:
        next_expected = "answer|inspect"
    elif known:
        next_expected = "answer"
    state = {
        "schema": QUEST_STATE_SCHEMA,
        "line": "",
        "goal": "-".join(goal_bits)[:120],
        "space": scope_id,
        "object": f"{kind[:1] or 'o'}:{object_id}" if object_id else "",
        "known": known[:4],
        "missing": missing[:4],
        "next": next_expected,
        "block": quest_token(block_code, 80),
    }
    state = {key: value for key, value in state.items() if value not in ("", [], {})}
    state["line"] = quest_state_line(state)
    return state


def quest_state_line(state: dict[str, Any]) -> str:
    if not isinstance(state, dict):
        return ""
    parts = ["QS/1"]
    fields = (
        ("G", state.get("goal")),
        ("S", state.get("space")),
        ("O", state.get("object")),
        ("K", ",".join(str(item) for item in state.get("known", [])[:4]) if isinstance(state.get("known"), list) else state.get("known")),
        ("M", ",".join(str(item) for item in state.get("missing", [])[:4]) if isinstance(state.get("missing"), list) else state.get("missing")),
        ("NX", state.get("next")),
        ("BLK", state.get("block")),
    )
    for key, raw in fields:
        value = str(raw or "").strip()
        if value:
            parts.append(f"{key}:{value[:160]}")
    return " ".join(parts) if len(parts) > 1 else ""


def parse_quest_state_line(line: str) -> dict[str, Any]:
    text = str(line or "").strip()
    if not text.startswith("QS/1"):
        return {}
    state: dict[str, Any] = {"schema": QUEST_STATE_SCHEMA, "line": text}
    key_map = {"G": "goal", "S": "space", "O": "object", "K": "known", "M": "missing", "NX": "next", "BLK": "block"}
    for token in text.split()[1:]:
        if ":" not in token:
            continue
        key, value = token.split(":", 1)
        mapped = key_map.get(key)
        if not mapped:
            continue
        if mapped in {"known", "missing"}:
            state[mapped] = [item for item in value.split(",") if item]
        else:
            state[mapped] = value
    return state


def runtime_scope_missing_final(run_id: str, envelope: dict[str, Any], local_tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    quest_state = quest_state_from_evidence(envelope, local_tool_results, block_code="runtime_scope_route_missing")
    return {
        "schema": "hermes.wasm_agent.direct_head_run.final.v1",
        "run_id": run_id,
        "route_id": envelope.get("route_id") or envelope.get("route"),
        "reply": "",
        "local_tools": local_tool_results,
        "diagnostics": {
            "source": "runtime_scope_route_missing",
            "quest_state": quest_state,
            "state_writeback": {
                "schema": "hermes.wasm_agent.state_writeback.v1",
                "last_action": "block",
                "last_feedback": "unclear",
                "next": {"quest_state": quest_state},
            },
        },
    }


def source_evidence_line(local_tool_results: list[dict[str, Any]]) -> str:
    summaries = source_summaries(local_tool_results)
    paths = source_paths(local_tool_results)
    text = " ".join(summaries)
    facts: list[str] = []
    lower = text.lower()
    for path in paths[:4]:
        token = quest_token(Path(str(path or "")).stem, 80)
        if token:
            facts.append(f"src:{token}")
    if "paracelsus" in lower:
        facts.append("node:paracelsus")
    if "scientific-paper-meta-analysis" in lower:
        facts.append("wf:scientific-paper-meta-analysis")
    if "ranks a queued subject" in lower:
        facts.append("rank-subject")
    if "evidence integrity" in lower or "bias-risk" in lower:
        facts.append("integrity-bias-risk")
    if "exports findings" in lower:
        facts.append("export-report")
    if "persists" in lower:
        facts.append("persist-local")
    if not facts:
        return ""
    return "SRC/1 " + " ".join(list(dict.fromkeys(facts))[:8])


def evidence_packet(envelope: dict[str, Any], local_tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    quest_state = quest_state_from_evidence(envelope, local_tool_results)
    packet = {
        "quest_state": quest_state,
        "quest_line": quest_state.get("line") if isinstance(quest_state, dict) else "",
        "source_line": source_evidence_line(local_tool_results),
        "missing_scope": quest_state.get("missing") if isinstance(quest_state, dict) else [],
    }
    return {key: value for key, value in packet.items() if value not in ("", [], {})}


def probe_actions(envelope: dict[str, Any], local_tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(item.get("tool") in {"code.memory.search", "lookup.symbol"} for item in local_tool_results if isinstance(item, dict)):
        return []
    resolved = resolve(envelope)
    if not resolved.get("is_repo_object_question"):
        return []
    query = clipped(str(resolved.get("query") or "repo object"), 120)
    route_id = envelope.get("route_id") or envelope.get("route")
    return [
        {
            "action": "code.memory.search",
            "args": {
                "route_id": route_id,
                "query": query,
                "limit": 8,
                "entity_resolution": resolved,
            },
        },
        {
            "action": "lookup.symbol",
            "args": {"route_id": route_id, "query": query, "entity_resolution": resolved},
        },
    ]


def source_paths(local_tool_results: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for item in local_tool_results:
        if not isinstance(item, dict) or item.get("tool") not in {"code.memory.search", "lookup.symbol"}:
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        candidates = result.get("items") if item.get("tool") == "code.memory.search" else result.get("matches")
        candidates = candidates if isinstance(candidates, list) else []
        for code_item in candidates[:6]:
            if not isinstance(code_item, dict):
                continue
            path = clipped(str(code_item.get("file") or code_item.get("file_path") or code_item.get("path") or "").strip(), 500)
            if path and "." in Path(path).name and path not in paths:
                paths.append(path)
    return paths


def source_read_action(envelope: dict[str, Any], local_tool_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not resolve(envelope).get("is_repo_object_question"):
        return None
    if any(isinstance(item, dict) and item.get("tool") == "file.read_bounded" for item in local_tool_results):
        return None
    paths = source_paths(local_tool_results)
    if not paths:
        return None
    return {
        "action": "file.read_bounded",
        "args": {
            "route_id": envelope.get("route_id") or envelope.get("route"),
            "path": paths[0],
            "max_bytes": 18000,
        },
    }


def source_summary_from_text(path: str, text: str) -> str:
    facts: list[str] = []
    workflow: list[str] = []
    lowered_path = str(path or "").lower()
    widget_label = "the UI widget"
    if "meta-analysis" in lowered_path or "scientific-paper-meta-analysis" in text:
        widget_label = "the meta-analysis widget"
    if "node.chat" in text:
        facts.append("calls `node.chat`")
    if "paracelsus" in text.lower():
        facts.append("targets the `paracelsus` research node")
    if "scientific-paper-meta-analysis" in text:
        facts.append("asks for the `scientific-paper-meta-analysis` workflow")
    if "node.chat" in text and "paracelsus" in text.lower() and "scientific-paper-meta-analysis" in text:
        workflow.append("sends the subject to the `paracelsus` research node's `scientific-paper-meta-analysis` workflow")
    if "rankSubject" in text or "Rank" in text:
        facts.append("ranks a queued subject")
        workflow.append("takes a queued or typed subject as the unit of work")
    if "Evidence Integrity" in text or "assessIntegrity" in text:
        facts.append("adds an Evidence Integrity/bias-risk overlay")
        workflow.append("flags bias/integrity signals from the returned finding text")
    if "exportFindings" in text or "download" in text:
        facts.append("exports findings as a rendered report")
        workflow.append("turns saved findings into an exportable report")
    if "localStorage" in text or "persist()" in text:
        facts.append("persists the subject queue/results locally")
        workflow.append("keeps queue and result state in browser local storage")
    if facts:
        behavior = ", ".join(dict.fromkeys(workflow or facts))
        return (
            f"{widget_label[:1].upper() + widget_label[1:]} is a browser-side research workflow panel. "
            f"It {behavior}. "
            "That describes the widget's code path; live availability in a named space is separate runtime evidence."
        )
    if path:
        return f"Source `{path}` was read for bounded repo-object evidence."
    return ""


def source_summaries(local_tool_results: list[dict[str, Any]]) -> list[str]:
    summaries: list[str] = []
    for item in local_tool_results:
        if not isinstance(item, dict) or item.get("tool") != "file.read_bounded":
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        summary = source_summary_from_text(str(result.get("path") or "").strip(), str(result.get("text") or ""))
        if summary:
            summaries.append(summary)
    return summaries
