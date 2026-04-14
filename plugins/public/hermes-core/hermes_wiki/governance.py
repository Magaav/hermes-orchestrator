from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .compression import build_compression_artifacts
from .config import WikiSettings
from .coordination import coordinated_commit, dedupe_proposals, ordered_proposals
from .graph import compile_graph
from .markdown import WikiPage, discover_pages, merge_unique, parse_page, render_page
from .utils import append_jsonl, atomic_write_json, atomic_write_text, normalize_text, sha256_file, utc_now


PROPOSAL_STATUSES = (
    "pending",
    "approved",
    "rejected",
    "executed",
    "archived",
    "review_needed",
)

TRUST_ORDER = {
    "provisional": 1,
    "validated": 2,
    "canonical": 3,
}

BANNED_SIGNAL_TYPES = {
    "scratch",
    "debug",
    "temporary_debug",
    "chat",
    "transcript",
    "chain_of_thought",
    "attempt",
}

DIR_BY_TYPE = {
    "concept": "global",
    "procedure": "global",
    "decision": "global",
    "incident": "global",
    "entity": "global",
    "source": "global",
    "index": "indexes",
}


def _status_dir(settings: WikiSettings, status: str) -> Path:
    return settings.proposals_root / status


def ensure_proposal_layout(settings: WikiSettings) -> None:
    for status in PROPOSAL_STATUSES:
        _status_dir(settings, status).mkdir(parents=True, exist_ok=True)


def _proposal_path(settings: WikiSettings, proposal_id: str, status: str) -> Path:
    return _status_dir(settings, status) / f"{proposal_id}.json"


def _stage_event(proposal: dict[str, Any], stage: str, detail: str = "") -> None:
    proposal.setdefault("stage_history", []).append(
        {
            "stage": stage,
            "at": utc_now(),
            "detail": detail,
        }
    )


def _load_proposal_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def list_proposals(settings: WikiSettings, statuses: tuple[str, ...] = PROPOSAL_STATUSES) -> list[dict[str, Any]]:
    ensure_proposal_layout(settings)
    proposals: list[dict[str, Any]] = []
    for status in statuses:
        for path in sorted(_status_dir(settings, status).glob("*.json")):
            try:
                proposal = _load_proposal_file(path)
            except Exception:
                continue
            proposal["_path"] = str(path)
            proposal["_status"] = status
            proposals.append(proposal)
    return proposals


def _write_proposal(settings: WikiSettings, proposal: dict[str, Any], status: str) -> Path:
    ensure_proposal_layout(settings)
    proposal["status"] = status
    proposal["updated_at"] = utc_now()
    path = _proposal_path(settings, str(proposal["proposal_id"]), status)
    atomic_write_json(path, proposal)
    for other in PROPOSAL_STATUSES:
        other_path = _proposal_path(settings, str(proposal["proposal_id"]), other)
        if other != status and other_path.exists():
            other_path.unlink()
    return path


def _refresh_queue_manifests(settings: WikiSettings) -> None:
    pending = [
        {
            "proposal_id": proposal["proposal_id"],
            "proposal_type": proposal.get("proposal_type"),
            "title": proposal.get("title"),
            "status": proposal.get("status"),
            "classification": proposal.get("classification", {}),
            "risk_level": proposal.get("risk_level"),
            "created_at": proposal.get("created_at"),
        }
        for proposal in list_proposals(settings, ("pending", "review_needed"))
    ]
    atomic_write_json(settings.queues_root / "pending.json", pending)


def _trust_weight(value: str) -> int:
    return TRUST_ORDER.get(str(value or "provisional").lower(), 0)


def _page_similarity(proposal_title: str, page: WikiPage) -> float:
    left = {token for token in normalize_text(proposal_title).split() if token}
    right = {token for token in normalize_text(page.title).split() if token}
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    union = len(left | right)
    return intersection / union if union else 0.0


def _page_lookup(pages: list[WikiPage]) -> dict[str, WikiPage]:
    lookup: dict[str, WikiPage] = {}
    for page in pages:
        for key in [page.node_id, page.title, page.relative_path.replace(".md", ""), Path(page.relative_path).stem, *page.aliases]:
            normalized = normalize_text(key)
            if not normalized:
                continue
            existing = lookup.get(normalized)
            if existing is None or _trust_weight(page.trust_tier) > _trust_weight(existing.trust_tier):
                lookup[normalized] = page
    return lookup


def _classification_target(
    proposal: dict[str, Any],
    pages: list[WikiPage],
) -> tuple[str, str]:
    lookup = _page_lookup(pages)
    explicit_target = str(proposal.get("target_page") or proposal.get("target_path") or "").strip()
    if explicit_target:
        candidate = lookup.get(normalize_text(explicit_target))
        if candidate is not None:
            return "update_existing", candidate.relative_path

    title = str(proposal.get("title") or "").strip()
    if title:
        candidate = lookup.get(normalize_text(title))
        if candidate is not None:
            return "update_existing", candidate.relative_path

    if title:
        scored = sorted(
            ((page, _page_similarity(title, page)) for page in pages),
            key=lambda item: (-item[1], -_trust_weight(item[0].trust_tier), item[0].relative_path),
        )
        if scored and scored[0][1] >= 0.6:
            return "update_existing", scored[0][0].relative_path
        if scored and scored[0][1] >= 0.35 and proposal.get("append_section"):
            return "append_subsection", scored[0][0].relative_path

    return "create_new", ""


def _evaluate_durability(proposal: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    signal_type = str(proposal.get("signal_type") or proposal.get("proposal_type") or "").strip().lower()
    if signal_type in BANNED_SIGNAL_TYPES:
        reasons.append(f"signal_type_not_allowed:{signal_type}")
    if proposal.get("ephemeral") is True:
        reasons.append("explicitly_marked_ephemeral")

    durability_days = int(proposal.get("durability_days", 30) or 0)
    if durability_days < 30:
        reasons.append("durability_window_below_threshold")

    confidence = float(proposal.get("confidence", 0.5) or 0.0)
    if confidence < 0.35:
        reasons.append("confidence_too_low")

    frequency = int(proposal.get("frequency", 1) or 1)
    detection_source = str(proposal.get("detection_source") or "").strip().lower()
    if detection_source in {"doctrine", "incident_log", "transcript", "debug_session"} and frequency < 2:
        reasons.append("insufficient_repetition")

    content = str(proposal.get("details") or proposal.get("content") or "").strip()
    if len(content) < 20 and not proposal.get("section_updates"):
        reasons.append("content_too_thin")

    return not reasons, reasons


def _scope_directory(proposal: dict[str, Any]) -> str:
    scope = str(proposal.get("scope") or "global").strip().strip("/")
    if not scope or scope == "global":
        return "global"
    if scope.startswith("projects/") or scope.startswith("agents/") or scope.startswith("archive/") or scope.startswith("indexes/"):
        return scope
    if scope.startswith("project:"):
        return f"projects/{normalize_text(scope.split(':', 1)[1]).replace(' ', '-')}"
    if scope.startswith("agent:"):
        return f"agents/{normalize_text(scope.split(':', 1)[1]).replace(' ', '-')}"
    return scope


def _default_target_path(proposal: dict[str, Any]) -> str:
    page_type = str(proposal.get("page_type") or proposal.get("type") or "concept").strip() or "concept"
    scope_dir = _scope_directory(proposal)
    if scope_dir == "global":
        scope_dir = DIR_BY_TYPE.get(page_type, "global")
    title_slug = normalize_text(str(proposal.get("title") or "untitled")).replace(" ", "-") or "untitled"
    return f"{scope_dir}/{title_slug}.md"


def _proposal_id(payload: dict[str, Any]) -> str:
    title = str(payload.get("title") or payload.get("proposal_type") or "proposal").strip() or "proposal"
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:10]
    return f"proposal-{normalize_text(title).replace(' ', '-')}-{digest}"


def _rate_limit_reasons(settings: WikiSettings, proposal: dict[str, Any], classification: dict[str, Any]) -> list[str]:
    agent_id = str(proposal.get("agent_id") or proposal.get("proposed_by") or "unknown").strip() or "unknown"
    executed_log = settings.history_root / "executions.jsonl"
    if not executed_log.exists():
        return []

    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    one_day_ago = now - timedelta(days=1)
    writes_per_hour = 0
    new_pages_per_day = 0

    for raw_line in executed_log.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except Exception:
            continue
        if str(event.get("agent_id") or "") != agent_id:
            continue
        try:
            when = datetime.strptime(str(event.get("executed_at") or ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if when >= one_hour_ago:
            writes_per_hour += 1
        if when >= one_day_ago and str(event.get("action") or "") == "create_new":
            new_pages_per_day += 1

    reasons: list[str] = []
    if writes_per_hour >= settings.max_writes_per_agent_per_hour:
        reasons.append("write_rate_limit_exceeded")
    if classification.get("action") == "create_new" and new_pages_per_day >= settings.max_new_pages_per_day:
        reasons.append("new_page_rate_limit_exceeded")
    return reasons


def classify_proposal(settings: WikiSettings, proposal: dict[str, Any], pages: list[WikiPage] | None = None) -> dict[str, Any]:
    page_list = pages or discover_pages(settings.wiki_root)
    durable, reasons = _evaluate_durability(proposal)
    action, target_path = _classification_target(proposal, page_list)
    classification = {
        "action": "reject" if not durable else action,
        "target_path": target_path,
        "reasons": reasons,
    }
    if classification["action"] == "create_new":
        classification["target_path"] = str(proposal.get("suggested_path") or _default_target_path(proposal))
    return classification


def submit_proposal(settings: WikiSettings, payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "proposal_id": "",
            "reason": "NODE_WIKI_ENABLED is false",
        }

    ensure_proposal_layout(settings)
    with coordinated_commit(settings):
        pages = discover_pages(settings.wiki_root) if settings.wiki_root.exists() else []
        proposal = dict(payload)
        proposal_id = _proposal_id(proposal)
        proposal["proposal_id"] = proposal_id
        proposal.setdefault("proposal_type", "knowledge_write")
        proposal.setdefault("page_type", proposal.get("type", "concept"))
        proposal.setdefault("risk_level", "medium" if proposal.get("page_type") == "index" else "low")
        proposal.setdefault("detection_source", "agent")
        proposal.setdefault("agent_id", settings.current_node or "unknown")
        proposal.setdefault("trust_tier", "provisional")
        proposal.setdefault("confidence", 0.5)
        proposal.setdefault("frequency", 1)
        proposal.setdefault("durability_days", 30)
        proposal.setdefault("source_signals", [])
        proposal.setdefault("affected_pages", [])
        proposal.setdefault("execution_status", "staged")
        proposal["created_at"] = utc_now()
        proposal["updated_at"] = proposal["created_at"]
        proposal["classification"] = classify_proposal(settings, proposal, pages)
        target_rel = str(proposal["classification"].get("target_path") or "")
        if target_rel and proposal["classification"]["action"] in {"update_existing", "append_subsection"}:
            target_path = settings.wiki_root / target_rel
            if target_path.exists():
                proposal["base_hash"] = sha256_file(target_path)
        dedupe_key = "|".join(
            [
                str(proposal.get("proposal_type") or ""),
                str(proposal["classification"].get("action") or ""),
                str(proposal["classification"].get("target_path") or ""),
                normalize_text(str(proposal.get("title") or "")),
            ]
        )
        proposal["dedupe_key"] = dedupe_key
        _stage_event(proposal, "detection", str(proposal.get("detection_source") or "agent"))
        _stage_event(proposal, "proposal_generation", proposal["proposal_type"])
        _stage_event(proposal, "staging", proposal["classification"]["action"])

        durable, reasons = _evaluate_durability(proposal)
        rate_limit_reasons = _rate_limit_reasons(settings, proposal, proposal["classification"])
        if not durable:
            proposal.setdefault("moderation_notes", []).extend(reasons)
            status = "rejected"
        elif rate_limit_reasons:
            proposal.setdefault("moderation_notes", []).extend(rate_limit_reasons)
            status = "rejected"
        else:
            status = "pending"
        path = _write_proposal(settings, proposal, status)
        append_jsonl(
            settings.queues_root / "incoming.jsonl",
            {
                "proposal_id": proposal_id,
                "status": status,
                "queued_at": utc_now(),
                "title": proposal.get("title"),
                "agent_id": proposal.get("agent_id"),
            },
        )
        _refresh_queue_manifests(settings)
        proposal["_path"] = str(path)
        return proposal


def _snapshot_existing_page(settings: WikiSettings, target_path: Path, proposal_id: str) -> str:
    relative = target_path.relative_to(settings.wiki_root)
    snapshot_dir = settings.history_root / relative.parent / relative.stem
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_name = f"{utc_now().replace(':', '').replace('-', '')}__{proposal_id}.md"
    snapshot_path = snapshot_dir / snapshot_name
    snapshot_path.write_text(target_path.read_text(encoding="utf-8"), encoding="utf-8")
    return str(snapshot_path.relative_to(settings.wiki_root))


def _merge_section(existing: str, addition: str) -> str:
    base = str(existing or "").strip()
    extra = str(addition or "").strip()
    if not extra:
        return base
    if not base:
        return extra
    if extra in base:
        return base
    return f"{base}\n\n{extra}".strip()


def _merge_page_payload(existing: WikiPage | None, proposal: dict[str, Any]) -> str:
    now = utc_now()
    metadata: dict[str, Any] = dict(existing.metadata) if existing is not None else {}
    sections: dict[str, str] = dict(existing.sections) if existing is not None else {}

    metadata["type"] = str(proposal.get("page_type") or proposal.get("type") or metadata.get("type") or "concept")
    metadata["title"] = str(proposal.get("title") or metadata.get("title") or "Untitled").strip()
    metadata["node_id"] = str(metadata.get("node_id") or proposal.get("node_id") or normalize_text(metadata["title"]).replace(" ", "-"))
    metadata["trust_tier"] = str(proposal.get("trust_tier") or metadata.get("trust_tier") or "provisional")
    metadata["confidence"] = float(proposal.get("confidence", metadata.get("confidence", 0.5)) or 0.5)
    metadata["validation_status"] = str(proposal.get("validation_status") or metadata.get("validation_status") or "pending")
    metadata["last_validated_at"] = str(proposal.get("last_validated_at") or metadata.get("last_validated_at") or "")
    metadata["validated_by"] = merge_unique(
        list(metadata.get("validated_by", []) or []),
        [str(value) for value in proposal.get("validated_by", []) or []],
    )
    metadata["updated"] = now

    for field in ("aliases", "tags", "related", "children", "depends_on", "used_by", "caused_by", "owned_by", "decision_for", "incident_of", "sources"):
        metadata[field] = merge_unique(
            list(metadata.get(field, []) or []),
            [str(value) for value in proposal.get(field, []) or []],
        )
    metadata["parent"] = str(proposal.get("parent") or metadata.get("parent") or "").strip()
    metadata["source_count"] = max(
        int(metadata.get("source_count", 0) or 0),
        len(list(metadata.get("sources", []) or [])),
    )

    if proposal.get("one_line_summary"):
        sections["one_line_summary"] = str(proposal["one_line_summary"]).strip()
    if proposal.get("short_summary"):
        sections["short_summary"] = str(proposal["short_summary"]).strip()
    if proposal.get("details"):
        sections["details"] = _merge_section(sections.get("details", ""), str(proposal["details"]))
    if proposal.get("content") and not proposal.get("details"):
        sections["details"] = _merge_section(sections.get("details", ""), str(proposal["content"]))
    if proposal.get("related_pages"):
        sections["related_pages"] = _merge_section(sections.get("related_pages", ""), str(proposal["related_pages"]))
    if proposal.get("evidence"):
        evidence_lines = proposal["evidence"]
        if isinstance(evidence_lines, list):
            addition = "\n".join(f"- {line}" for line in evidence_lines if str(line).strip())
        else:
            addition = str(evidence_lines)
        sections["evidence"] = _merge_section(sections.get("evidence", ""), addition)
    if proposal.get("open_questions"):
        questions = proposal["open_questions"]
        if isinstance(questions, list):
            addition = "\n".join(f"- {line}" for line in questions if str(line).strip())
        else:
            addition = str(questions)
        sections["open_questions"] = _merge_section(sections.get("open_questions", ""), addition)

    for raw_name, raw_content in (proposal.get("section_updates") or {}).items():
        section_name = normalize_text(str(raw_name)).replace(" ", "_")
        sections[section_name] = _merge_section(sections.get(section_name, ""), str(raw_content))

    if proposal.get("append_section") and proposal.get("append_content"):
        section_name = normalize_text(str(proposal["append_section"])).replace(" ", "_")
        sections[section_name] = _merge_section(sections.get(section_name, ""), str(proposal["append_content"]))

    if not sections.get("one_line_summary"):
        sections["one_line_summary"] = str(metadata["title"])
    if not sections.get("short_summary"):
        sections["short_summary"] = sections["one_line_summary"]
    for key in ("details", "related_pages", "evidence", "open_questions"):
        sections.setdefault(key, "")

    rendered = render_page(metadata, sections)
    if len(rendered.encode("utf-8")) > proposal.get("_max_page_bytes", 120_000):
        raise ValueError("page_size_limit_exceeded")
    return rendered


def _execute_proposal(settings: WikiSettings, proposal: dict[str, Any]) -> dict[str, Any]:
    classification = proposal.get("classification", {})
    action = str(classification.get("action") or "reject")
    target_rel = str(classification.get("target_path") or "")
    if action == "reject":
        raise ValueError("proposal_rejected_by_classification")
    if not target_rel:
        raise ValueError("missing_target_path")

    target_path = settings.wiki_root / target_rel
    target_path.parent.mkdir(parents=True, exist_ok=True)
    proposal["_max_page_bytes"] = settings.max_page_bytes

    snapshot_rel = ""
    existing_page: WikiPage | None = None
    base_hash = ""
    if target_path.exists():
        snapshot_rel = _snapshot_existing_page(settings, target_path, str(proposal["proposal_id"]))
        existing_page = parse_page(target_path, settings.wiki_root)
        base_hash = sha256_file(target_path)
        proposed_base_hash = str(proposal.get("base_hash") or "").strip()
        if proposed_base_hash and proposed_base_hash != base_hash:
            raise ValueError("base_hash_conflict")

    rollback_snapshot = str(proposal.get("rollback_snapshot_path") or "").strip()
    if rollback_snapshot:
        snapshot_path = settings.wiki_root / rollback_snapshot
        if not snapshot_path.exists():
            raise ValueError("rollback_snapshot_missing")
        content = snapshot_path.read_text(encoding="utf-8")
    else:
        content = _merge_page_payload(existing_page, proposal)
    atomic_write_text(target_path, content)

    return {
        "action": action,
        "target_path": target_rel,
        "snapshot_path": snapshot_rel,
        "base_hash": base_hash,
        "result_hash": sha256_file(target_path),
    }


def _log_execution(settings: WikiSettings, proposal: dict[str, Any], execution: dict[str, Any]) -> None:
    event = {
        "proposal_id": proposal["proposal_id"],
        "agent_id": proposal.get("agent_id"),
        "title": proposal.get("title"),
        "action": execution.get("action"),
        "target_path": execution.get("target_path"),
        "snapshot_path": execution.get("snapshot_path"),
        "executed_at": utc_now(),
    }
    append_jsonl(settings.history_root / "executions.jsonl", event)
    append_jsonl(settings.observability_root / "governance_events.jsonl", event)


def process_pending_proposals(settings: WikiSettings) -> dict[str, Any]:
    if not settings.enabled:
        return {
            "executed": [],
            "rejected": [],
            "review_needed": [],
            "duplicates_rejected": [],
            "graph_nodes": 0,
            "graph_edges": 0,
            "enabled": False,
        }

    ensure_proposal_layout(settings)
    with coordinated_commit(settings):
        pending = list_proposals(settings, ("pending",))
        keepers, duplicates = dedupe_proposals(pending)
        for duplicate, winner in duplicates:
            duplicate.setdefault("moderation_notes", []).append(
                f"duplicate_of:{winner.get('proposal_id')}"
            )
            _stage_event(duplicate, "arbitration", "duplicate_rejected")
            _write_proposal(settings, duplicate, "rejected")

        executed: list[str] = []
        rejected: list[str] = []
        review_needed: list[str] = []

        for proposal in ordered_proposals(keepers):
            pages = discover_pages(settings.wiki_root)
            proposal["classification"] = classify_proposal(settings, proposal, pages)
            _stage_event(proposal, "evaluation", proposal["classification"]["action"])

            rate_limit_reasons = _rate_limit_reasons(settings, proposal, proposal["classification"])
            if rate_limit_reasons:
                proposal.setdefault("moderation_notes", []).extend(rate_limit_reasons)
                _stage_event(proposal, "moderation", "rate_limited")
                _write_proposal(settings, proposal, "rejected")
                rejected.append(str(proposal["proposal_id"]))
                continue

            if proposal["classification"]["action"] == "reject":
                proposal.setdefault("moderation_notes", []).extend(proposal["classification"].get("reasons", []))
                _stage_event(proposal, "moderation", "rejected")
                _write_proposal(settings, proposal, "rejected")
                rejected.append(str(proposal["proposal_id"]))
                continue

            _stage_event(proposal, "moderation", "approved")
            _write_proposal(settings, proposal, "approved")
            try:
                execution = _execute_proposal(settings, proposal)
            except ValueError as exc:
                proposal.setdefault("moderation_notes", []).append(str(exc))
                _stage_event(proposal, "execution", f"review_needed:{exc}")
                _write_proposal(settings, proposal, "review_needed")
                review_needed.append(str(proposal["proposal_id"]))
                continue

            proposal["execution_status"] = "executed"
            proposal["execution"] = execution
            _stage_event(proposal, "execution", execution["action"])
            _write_proposal(settings, proposal, "executed")
            _log_execution(settings, proposal, execution)
            executed.append(str(proposal["proposal_id"]))

        graph_payload = compile_graph(settings)
        build_compression_artifacts(settings, graph_payload=graph_payload)
        from .observability import build_lint_report, build_observability_snapshot

        lint = build_lint_report(settings, graph_payload=graph_payload)
        build_observability_snapshot(settings, graph_payload=graph_payload, lint_report=lint)
        _refresh_queue_manifests(settings)

        return {
            "executed": executed,
            "rejected": rejected,
            "review_needed": review_needed,
            "duplicates_rejected": [str(proposal["proposal_id"]) for proposal, _ in duplicates],
            "graph_nodes": graph_payload["metrics"]["node_count"],
            "graph_edges": graph_payload["metrics"]["edge_count"],
        }


def queue_rollback_proposal(
    settings: WikiSettings,
    *,
    target_path: str,
    snapshot_path: str = "",
    agent_id: str = "",
) -> dict[str, Any]:
    if not settings.enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "proposal_id": "",
            "reason": "NODE_WIKI_ENABLED is false",
        }

    target = settings.wiki_root / target_path
    if not target.exists():
        return {
            "enabled": True,
            "status": "missing_target",
            "proposal_id": "",
            "reason": f"target page not found: {target_path}",
        }

    snapshot_rel = snapshot_path.strip()
    if not snapshot_rel:
        history_dir = settings.history_root / Path(target_path).parent / Path(target_path).stem
        candidates = sorted(history_dir.glob("*.md"))
        if not candidates:
            return {
                "enabled": True,
                "status": "missing_snapshot",
                "proposal_id": "",
                "reason": f"no snapshots available for: {target_path}",
            }
        snapshot_rel = str(candidates[-1].relative_to(settings.wiki_root))

    page = parse_page(target, settings.wiki_root)
    return submit_proposal(
        settings,
        {
            "proposal_type": "rollback",
            "page_type": page.page_type,
            "title": page.title,
            "target_page": target_path,
            "target_path": target_path,
            "short_summary": f"Rollback {target_path} to snapshot {snapshot_rel}.",
            "details": f"Restore canonical markdown from {snapshot_rel}.",
            "confidence": 1.0,
            "frequency": 2,
            "durability_days": 90,
            "detection_source": "rollback",
            "agent_id": agent_id or settings.current_node or "unknown",
            "rollback_snapshot_path": snapshot_rel,
        },
    )
