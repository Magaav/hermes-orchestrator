"""Content-addressed V6 evidence summaries with pull-on-demand detail."""
from __future__ import annotations

from typing import Any

from . import contracts


DEFAULT_VIEW_CHARS = 12_000
MAX_VIEW_CHARS = 64_000


def _pointer(value: Any, pointer: str) -> Any:
    if not pointer:
        return value
    if not pointer.startswith("/"):
        raise contracts.ContractError("evidence_pointer_invalid")
    current = value
    for raw in pointer[1:].split("/"):
        segment = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit() and int(segment) < len(current):
            current = current[int(segment)]
        else:
            raise contracts.ContractError("evidence_pointer_missing")
    return current


class EvidenceStore:
    def __init__(self) -> None:
        self._summaries: dict[str, dict[str, Any]] = {}
        self._details: dict[str, Any] = {}

    def put(
        self, *, kind: str, subject: str, summary: str, detail: Any,
        revision: str = "", proof: list[str] | None = None,
    ) -> dict[str, Any]:
        body = {
            "v": contracts.VERSION, "kind": str(kind)[:120], "subject": str(subject)[:500],
            "revision": str(revision)[:240], "summary": str(summary)[:1200],
            "detail": detail, "proof": [str(item)[:240] for item in (proof or [])[:32]],
        }
        evidence_id = "ev:" + contracts.digest(body).split(":", 1)[1][:32]
        detail_ref = f"{evidence_id}:detail"
        public = {
            "v": contracts.VERSION, "id": evidence_id, "kind": body["kind"],
            "subject": body["subject"], "revision": body["revision"],
            "summary": body["summary"], "detail_ref": detail_ref,
            "proof": body["proof"], "stale": False,
        }
        self._summaries[evidence_id] = public
        self._details[detail_ref] = contracts.decode(contracts.canonical(detail))
        return dict(public)

    def get(self, evidence_id: str) -> dict[str, Any] | None:
        value = self._summaries.get(str(evidence_id))
        return dict(value) if value else None

    def detail(self, detail_ref: str) -> Any:
        value = self._details.get(str(detail_ref))
        return contracts.decode(contracts.canonical(value)) if value is not None else None

    def view(
        self, detail_ref: str, *, pointer: str = "", offset: int = 0,
        max_chars: int = DEFAULT_VIEW_CHARS,
    ) -> dict[str, Any] | None:
        """Return one bounded, explicitly untrusted lens over stored evidence."""
        value = self._details.get(str(detail_ref))
        if value is None:
            return None
        try:
            start = max(0, int(offset))
            limit = max(1, min(int(max_chars), MAX_VIEW_CHARS))
        except (TypeError, ValueError) as exc:
            raise contracts.ContractError("evidence_view_bounds_invalid") from exc
        selected = _pointer(value, str(pointer or ""))
        if isinstance(selected, str):
            rendered, encoding = selected, "text"
        else:
            rendered, encoding = contracts.canonical(selected), "canonical-json"
        start = min(start, len(rendered))
        end = min(len(rendered), start + limit)
        return {
            "schema": "master.frontier.v6.evidence.view.v1",
            "trust": "untrusted-data", "detail_ref": str(detail_ref),
            "pointer": str(pointer or ""), "encoding": encoding,
            "offset": start, "end": end, "total_chars": len(rendered),
            "truncated": end < len(rendered),
            "next_offset": end if end < len(rendered) else None,
            "content": rendered[start:end],
        }

    def mark_stale(self, *, subject: str, current_revision: str) -> int:
        count = 0
        for evidence_id, value in list(self._summaries.items()):
            if value.get("subject") != subject or value.get("revision") in {"", current_revision}:
                continue
            self._summaries[evidence_id] = {**value, "stale": True, "current_revision": str(current_revision)[:240]}
            count += 1
        return count

    def list(self, *, limit: int = 64) -> list[dict[str, Any]]:
        return [dict(item) for item in list(self._summaries.values())[-max(1, min(int(limit), 256)):]]

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": "master.frontier.v6.evidence.snapshot.v1",
            "summaries": list(self._summaries.values()),
            "details": dict(self._details),
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("schema") != "master.frontier.v6.evidence.snapshot.v1":
            raise contracts.ContractError("evidence_snapshot_invalid")
        summaries = snapshot.get("summaries") if isinstance(snapshot.get("summaries"), list) else []
        details = snapshot.get("details") if isinstance(snapshot.get("details"), dict) else {}
        rebuilt: dict[str, dict[str, Any]] = {}
        for item in summaries:
            if not isinstance(item, dict) or not str(item.get("id") or "").startswith("ev:"):
                raise contracts.ContractError("evidence_snapshot_invalid")
            detail_ref = str(item.get("detail_ref") or "")
            if detail_ref not in details:
                raise contracts.ContractError("evidence_snapshot_detail_missing")
            rebuilt[str(item["id"])] = contracts.decode(contracts.canonical(item))
        self._summaries = rebuilt
        self._details = contracts.decode(contracts.canonical(details))
