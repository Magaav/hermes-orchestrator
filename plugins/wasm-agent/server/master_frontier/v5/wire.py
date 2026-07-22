"""Compact text projection for V5 model context.

Internal state remains structured.  Only the repeated model-facing projection
uses this line protocol, avoiding duplicated JSON keys and native tool schemas.
Large primary evidence is emitted once as a length-labelled block.
"""
from __future__ import annotations

import json
import hashlib
from typing import Any


SCHEMA = "MF5/2"


def _text(value: Any, limit: int = 1200) -> str:
    raw = ("" if value is None else str(value)).replace("\\", "\\\\").replace("\t", "\\t").replace("\r", "").replace("\n", "\\n")
    return raw if len(raw) <= limit else raw[: max(0, limit - 12)] + "...[cut]"


def _json(value: Any, limit: int = 3000) -> str:
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":"), default=str)
    if len(raw) <= limit:
        return raw
    preview_limit = max(40, limit - 140)
    preview = raw[: preview_limit // 2] + "...[cut]..." + raw[-preview_limit // 2:]
    return json.dumps({
        "truncated": True, "chars": len(raw),
        "sha256": hashlib.sha256(raw.encode()).hexdigest()[:16], "preview": preview,
    }, ensure_ascii=True, separators=(",", ":"))


def _pairs(value: dict[str, Any], keys: tuple[str, ...]) -> str:
    return ";".join(f"{key}={_text(value.get(key), 500)}" for key in keys if value.get(key) not in (None, "", [], {}))


def encode(payload: dict[str, Any]) -> str:
    lines = [SCHEMA, f"O\t{_text(payload.get('objective'), 8000)}"]
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    lines.append("R\t" + _pairs(route, ("id", "root")))
    identity = payload.get("runtime_identity") if isinstance(payload.get("runtime_identity"), dict) else {}
    if identity:
        lines.append("I\t" + _pairs(identity, tuple(sorted(identity))[:8]))
    runtime_entities = payload.get("runtime_entities") if isinstance(payload.get("runtime_entities"), list) else []
    if runtime_entities:
        lines.append("E\t" + ",".join(
            f"{_text(item.get('id'), 120)}:{_text(item.get('kind'), 80)}"
            for item in runtime_entities[:8]
            if isinstance(item, dict) and item.get("id")
        ))
    tool_names = payload.get("tools") if isinstance(payload.get("tools"), list) else []
    lines.append("T\t" + ",".join(_text(item, 80) for item in tool_names))
    check_ids = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    if check_ids:
        lines.append("K\t" + ",".join(_text(item, 120) for item in check_ids))
    for pattern in payload.get("learned_patterns") if isinstance(payload.get("learned_patterns"), list) else []:
        if isinstance(pattern, dict):
            lines.append(f"G\t{_text(pattern.get('code'), 20)}\t{_text(pattern.get('rule'), 320)}\t{_text(pattern.get('digest'), 20)}")
    continuity = payload.get("continuity") if isinstance(payload.get("continuity"), dict) else {}
    if continuity:
        lines.append("C\t" + _pairs(continuity, ("schema", "covers", "truncated")))
        for turn in continuity.get("turns") if isinstance(continuity.get("turns"), list) else []:
            if not isinstance(turn, dict):
                continue
            lines.append("H\t" + "\t".join((
                _text(turn.get("anchor"), 40), _text(turn.get("relation"), 40),
                _text(turn.get("objective"), 700), _text(turn.get("answer"), 7000),
                _text(turn.get("verification"), 80),
                ",".join(_text(item, 180) for item in (turn.get("changed") or [])[:12]),
            )))
            outline = turn.get("outline") if isinstance(turn.get("outline"), list) else []
            if outline:
                lines.append("h\t" + " | ".join(_text(item, 180) for item in outline[:12]))
            decision = turn.get("decision") if isinstance(turn.get("decision"), dict) else {}
            if decision:
                lines.append("d\t" + _json(decision, 3000))
        resume = continuity.get("resume") if isinstance(continuity.get("resume"), dict) else {}
        if resume:
            lines.append("J\t" + _pairs(resume, ("resumed", "root_objective", "previous_run_id", "previous_status", "completed_action_count")))
            pending = resume.get("pending_action") if isinstance(resume.get("pending_action"), dict) else {}
            if pending:
                lines.append("U\t" + _pairs(pending, ("action_id", "tool", "status")))
    for observation in payload.get("completed") if isinstance(payload.get("completed"), list) else []:
        if not isinstance(observation, dict):
            continue
        lines.append("S\t" + "\t".join((
            _text(observation.get("tool"), 80), _text(observation.get("status"), 40),
            _text(observation.get("summary"), 500),
        )))
        result = observation.get("result") if isinstance(observation.get("result"), dict) else {}
        content = result.get("content") if isinstance(result.get("content"), str) else ""
        detail = {key: value for key, value in result.items() if key != "content"}
        if detail:
            lines.append("D\t" + _json(detail))
        if content:
            # JSON string encoding keeps source data from spoofing line records.
            lines.append("B\t" + json.dumps(content, ensure_ascii=True))
    evidence = payload.get("evidence_status") if isinstance(payload.get("evidence_status"), dict) else {}
    if evidence:
        lines.append("V\t" + _pairs(evidence, (
            "owner_file", "line_count", "read_ranges", "missing_ranges", "owner_fully_read", "instruction",
        )))
    budget = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
    if budget:
        lines.append("Y\t" + _pairs(budget, (
            "calls_used", "calls_target", "calls_remaining",
            "tokens_used", "tokens_target", "tokens_remaining", "hard",
        )))
    assessment = payload.get("completion_assessment") if isinstance(payload.get("completion_assessment"), dict) else {}
    assessment_next = assessment.get("next_actions") if isinstance(assessment.get("next_actions"), list) else []
    error = payload.get("last_error") if isinstance(payload.get("last_error"), dict) else {}
    if error:
        lines.append("X\t" + _pairs(error, ("code", "message")))
        if error.get("next_actions") and not assessment_next:
            lines.append("N\t" + _json(error["next_actions"], 1200))
    if assessment:
        lines.append("A\t" + _pairs(assessment, ("status", "reason")))
        if assessment.get("required_gaps"):
            lines.append("Q\t" + ",".join(_text(item, 120) for item in assessment["required_gaps"][:12]))
        if assessment_next:
            lines.append("N\t" + _json(assessment_next, 1200))
    reliability = payload.get("provider_reliability") if isinstance(payload.get("provider_reliability"), dict) else {}
    if reliability:
        lines.append("P\t" + _pairs(reliability, ("transient_retries", "retry_limit", "retry_active", "last_code")))
    operations = payload.get("operations") if isinstance(payload.get("operations"), dict) else {}
    if operations:
        lines.append("L\t" + _pairs(operations, ("rev", "mutations", "changed", "gaps")))
    progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
    if progress:
        lines.append("W\t" + _json(progress, 2200))
    epistemics = payload.get("epistemics") if isinstance(payload.get("epistemics"), dict) else {}
    if epistemics:
        lines.append("M\t" + _pairs(epistemics, ("universe", "claim_rule")))
    pending = payload.get("pending_action") if isinstance(payload.get("pending_action"), dict) else {}
    if pending:
        lines.append("U\t" + _pairs(pending, ("action_id", "tool", "status")))
    executive = payload.get("executive") if isinstance(payload.get("executive"), dict) else {}
    if executive:
        lines.append("F\t" + _json(executive, 8000))
    lines.append("Z\t" + _text(payload.get("rule"), 500))
    return "\n".join(lines)
