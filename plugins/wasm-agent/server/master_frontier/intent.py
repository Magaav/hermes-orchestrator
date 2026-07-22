from __future__ import annotations

import json
import re
from typing import Any


IMPLEMENTATION_CAPS = {"repo.edit", "kernel.act", "test.run", "docs.update", "proof.report"}
DIAGNOSIS_RE = re.compile(
    r"\b(?:why|fail(?:ed|ure|ing)?|error|bug|diagnos\w*|inspect\w*|investigat\w*|audit\w*|review\w*|crit\w*|root[- ]cause)\b",
    re.IGNORECASE,
)
SOURCE_OBJECT_RE = re.compile(
    r"\b(?:code|codebase|component|file|function|implementation|module|repo(?:sitory)?|route|source|ui|widget)\b",
    re.IGNORECASE,
)
SOURCE_QUESTION_RE = re.compile(
    r"\b(?:check|describe|explain|find|how|identify|inspect|locate|show|what|where|which|why)\b",
    re.IGNORECASE,
)


def _compact_json(value: Any, *, limit: int = 3000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    except (TypeError, ValueError):
        text = str(value or "")
    return text[:limit]


def goal_completion_text(envelope: dict[str, Any]) -> str:
    parts = [
        str(envelope.get("objective") or ""),
        str(envelope.get("intent") or ""),
        str(envelope.get("state_summary") or ""),
    ]
    compact_state = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    if compact_state:
        parts.append(_compact_json(compact_state, limit=3000))
    constraints = envelope.get("constraints")
    if constraints not in (None, "", [], {}):
        parts.append(_compact_json(constraints, limit=1600))
    return " ".join(part for part in parts if part).lower()


def text_is_capability_inquiry(text: str) -> bool:
    clean = f" {str(text or '').lower()} "
    hard_commit_patterns = (
        r"\bgo\s+ahead\b",
        r"\bdo\s+it\b",
        r"\bstart\b",
        r"\bship\s+it\b",
        r"\bimplement\s+it\b",
        r"\bbuild\s+it\b",
        r"\bmake\s+it\b",
    )
    if any(re.search(pattern, clean) for pattern in hard_commit_patterns):
        return False
    self_capability_patterns = (
        r"\bwhat\s+(?:you|we|it|the system)\s+can\s+do\b",
        r"\bwhat\s+can\s+(?:you|we|it|the system)\s+do\b",
        r"\bwhere\s+are\s+you\b",
        r"\btest\s+(?:your|the system'?s?)\s+(?:power|capabilit(?:y|ies))\b",
    )
    if any(re.search(pattern, clean) for pattern in self_capability_patterns):
        return True
    inquiry_patterns = (
        r"\bavailability\b",
        r"\bavailable\b",
        r"\bcapabilit(?:y|ies)\b",
        r"\bcan\s+(?:you|we|it|the system)\b",
        r"\bcould\s+(?:you|we|it|the system)\b",
        r"\bwhether\b",
        r"\bif\s+(?:you|we|it|the system)\s+can\b",
        r"\bpossib(?:le|ility)\b",
        r"\bviab(?:le|ility)\b",
        r"\bcheck\b.*\b(?:availability|capabilit|possible|viab|support|possibility)\b",
    )
    if not any(re.search(pattern, clean) for pattern in inquiry_patterns):
        return False
    # These inquiry forms stay questions even when the object contains verbs like build/ship/make.
    if re.search(r"\b(can|could)\s+(?:you|we|it|the system)\b", clean):
        return True
    if re.search(r"\b(?:whether|if)\s+(?:you|we|it|the system)\s+can\b", clean):
        return True
    if re.search(r"\bpossib(?:le|ility)\s+to\b", clean):
        return True
    explicit_commit_patterns = (
        r"\bimplement\b",
        r"\bbuild\b",
        r"\bcreate\b",
        r"\badd\b",
        r"\bapply\b",
        r"\bpatch\b",
        r"\bfix\b",
        r"\bwire\b",
        r"\bupdate\b",
        r"\bchange\b",
    )
    return not any(re.search(pattern, clean) for pattern in explicit_commit_patterns)


def objective_is_implementation_intent(envelope: dict[str, Any]) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            envelope.get("objective"),
            envelope.get("intent"),
            envelope.get("state_summary"),
            _compact_json(envelope.get("compact_state"), limit=2400) if isinstance(envelope.get("compact_state"), dict) else "",
        )
    ).lower()
    if not text or text_is_capability_inquiry(text):
        return False
    implementation_terms = (
        "add",
        "apply",
        "build",
        "change",
        "create",
        "edit",
        "fix",
        "generate",
        "implement",
        "make",
        "patch",
        "refactor",
        "ship",
        "update",
    )
    if not any(re.search(rf"\b{re.escape(term)}\b", text) for term in implementation_terms):
        return False
    route_contract = envelope.get("route_contract") if isinstance(envelope.get("route_contract"), dict) else {}
    caps: list[str] = []
    for source in (envelope.get("capabilities"), route_contract.get("caps")):
        if isinstance(source, list):
            caps.extend(str(item or "") for item in source)
    return any(cap in IMPLEMENTATION_CAPS for cap in caps)


def objective_is_diagnosis_intent(envelope: dict[str, Any]) -> bool:
    objective_kind = str(envelope.get("objective_kind") or "").strip().lower()
    if objective_kind == "diagnosis":
        return True
    if objective_kind in {"conversation", "implementation"}:
        return False
    return bool(DIAGNOSIS_RE.search(str(envelope.get("objective") or "")))


def objective_requires_source_evidence(envelope: dict[str, Any]) -> bool:
    objective = str(envelope.get("objective") or "")
    # Evidence modality is a property of the target plus the declared speech
    # act.  A diagnosis of a repository object still needs source evidence even
    # when it is phrased as an imperative critique instead of a wh-question.
    return bool(
        SOURCE_OBJECT_RE.search(objective)
        and (SOURCE_QUESTION_RE.search(objective) or objective_is_diagnosis_intent(envelope))
    )


def goal_requires_change_artifact(envelope: dict[str, Any]) -> bool:
    if objective_is_implementation_intent(envelope):
        return True
    text = f" {goal_completion_text(envelope)} "
    if not text.strip() or text_is_capability_inquiry(text):
        return False
    continuation_terms = ("continue", "continuation", "previous goal", "resume")
    implementation_terms = (
        "add",
        "apply",
        "build",
        "change",
        "code",
        "create",
        "edit",
        "fix",
        "implement",
        "patch",
        "ship",
        "update",
        "widget",
        "wire",
    )
    has_continuation = any(re.search(rf"\b{re.escape(term)}\b", text) for term in continuation_terms)
    has_implementation = any(re.search(rf"\b{re.escape(term)}\b", text) for term in implementation_terms)
    return has_continuation and has_implementation


def changed_file_artifacts(change_proof: dict[str, Any], dispatch_result: dict[str, Any] | None) -> list[Any]:
    changed = change_proof.get("changed_files") if isinstance(change_proof.get("changed_files"), list) else []
    artifacts: list[Any] = list(changed)
    if isinstance(dispatch_result, dict):
        trace = dispatch_result.get("bridge_trace") if isinstance(dispatch_result.get("bridge_trace"), dict) else {}
        trace_changed = trace.get("changed_files") if isinstance(trace.get("changed_files"), list) else []
        artifacts.extend(trace_changed)
        dispatch_changed = dispatch_result.get("changed_files") if isinstance(dispatch_result.get("changed_files"), list) else []
        artifacts.extend(dispatch_changed)
    return [item for item in artifacts if item]
