"""Bounded omission-aware integrity experiment for Master:frontier run events.

This module is deliberately not wired into persistence.  It tests whether an
externally anchored chain/count/withheld contract detects failures that the
current ``event_count == len(events)`` projection cannot distinguish.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


SCHEMA = "hermes.wasm_agent.master_frontier.event_integrity.v1"
ANCHOR_SCHEMA = "hermes.wasm_agent.master_frontier.event_anchor.v1"
ALGORITHM = "sha256-chain-count-withheld.v1"
MAX_EVENTS = 256
MAX_TEXT_CHARS = 512
ZERO_HEAD = "0" * 64


class EventIntegrityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    return str(value or "")[:limit]


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")


def _event(event: dict[str, Any], fallback_seq: int) -> dict[str, Any]:
    try:
        seq = int(event.get("seq") if event.get("seq") is not None else fallback_seq)
    except (TypeError, ValueError) as exc:
        raise EventIntegrityError("event_seq_invalid", "Run-event sequence must be an integer.") from exc
    if seq <= 0:
        raise EventIntegrityError("event_seq_invalid", "Run-event sequence must be positive.")
    event_type = _text(event.get("type"), 120)
    if not event_type:
        raise EventIntegrityError("event_type_missing", "Run events require a type.")
    result = {
        "seq": seq,
        "type": event_type,
        "summary": _text(event.get("summary")),
        "created_at": int(event.get("created_at") or 0),
    }
    payload_digest = _text(event.get("payload_digest") or event.get("payload_sha256"), 64)
    if payload_digest:
        if len(payload_digest) != 64 or any(char not in "0123456789abcdef" for char in payload_digest.lower()):
            raise EventIntegrityError("event_payload_digest_invalid", "Event payload digest must be SHA-256 hex.")
        result["payload_digest"] = payload_digest.lower()
    return result


def _events(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    source = list(values)
    if not source:
        raise EventIntegrityError("event_ledger_empty", "At least one event is required.")
    if len(source) > MAX_EVENTS:
        raise EventIntegrityError(
            "event_ledger_bound_exceeded",
            f"Run-event integrity is bounded to {MAX_EVENTS} events.",
        )
    result = [_event(value, index) for index, value in enumerate(source, start=1)]
    sequences = [item["seq"] for item in result]
    if len(set(sequences)) != len(sequences):
        raise EventIntegrityError("event_seq_duplicate", "Run-event sequence values must be unique.")
    if sequences != list(range(1, len(result) + 1)):
        raise EventIntegrityError("event_seq_gap", "Run-event sequence must be contiguous from one.")
    return result


def _withheld_marker(run_id: str, seq: int, event_digest: str) -> str:
    raw = f"WASM-AGENT-WITHHELD\0{run_id}\0{seq}\0{event_digest}".encode()
    return _sha(raw)


def _link(previous: str, seq: int, status: str, event_digest: str, marker: str) -> str:
    return _sha(_canonical({
        "event": event_digest,
        "marker": marker,
        "previous": previous,
        "seq": seq,
        "status": status,
    }))


def seal(
    run_id: str,
    events: Iterable[dict[str, Any]],
    *,
    withheld_sequences: Iterable[int] = (),
) -> dict[str, Any]:
    """Seal a contiguous event sequence; withheld slots retain digest commitments."""
    clean_run_id = _text(run_id, 160)
    if not clean_run_id:
        raise EventIntegrityError("event_run_id_missing", "Run-event integrity requires run_id.")
    normalized = _events(events)
    withheld = {int(value) for value in withheld_sequences}
    if withheld - {item["seq"] for item in normalized}:
        raise EventIntegrityError("event_withheld_seq_missing", "A withheld sequence is outside the event ledger.")
    previous = ZERO_HEAD
    slots: list[dict[str, Any]] = []
    for event in normalized:
        seq = event["seq"]
        event_digest = _sha(_canonical(event))
        is_withheld = seq in withheld
        marker = _withheld_marker(clean_run_id, seq, event_digest) if is_withheld else ""
        head = _link(previous, seq, "withheld" if is_withheld else "present", event_digest, marker)
        slot = {
            "seq": seq,
            "status": "withheld" if is_withheld else "present",
            "event_digest": event_digest,
            "previous": previous,
            "head": head,
        }
        if is_withheld:
            slot["marker"] = marker
        else:
            slot["event"] = event
        slots.append(slot)
        previous = head
    return {
        "schema": SCHEMA,
        "algorithm": ALGORITHM,
        "run_id": clean_run_id,
        "declared": len(slots),
        "produced": len(slots) - len(withheld),
        "withheld": len(withheld),
        "head": previous,
        "slots": slots,
    }


def anchor(ledger: dict[str, Any]) -> dict[str, Any]:
    """Return the small commitment that must be stored outside the mutable ledger."""
    return {
        "schema": ANCHOR_SCHEMA,
        "algorithm": ALGORITHM,
        "run_id": _text(ledger.get("run_id"), 160),
        "declared": int(ledger.get("declared") or 0),
        "head": _text(ledger.get("head"), 64),
    }


def legacy_projection(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Model the current proof.collect count surface without claiming integrity."""
    rows = list(events)
    return {"event_count": len(rows), "events": rows}


def legacy_projection_self_consistent(projection: dict[str, Any]) -> bool:
    """The current count only confirms the response length it was derived from."""
    events = projection.get("events") if isinstance(projection.get("events"), list) else []
    return int(projection.get("event_count") or 0) == len(events)


def verify(ledger: dict[str, Any], *, trusted_anchor: dict[str, Any] | None = None) -> dict[str, Any]:
    failures: list[str] = []
    run_id = _text(ledger.get("run_id"), 160)
    slots = ledger.get("slots") if isinstance(ledger.get("slots"), list) else []
    if ledger.get("schema") != SCHEMA or ledger.get("algorithm") != ALGORITHM:
        failures.append("contract")
    if not run_id:
        failures.append("run_id")
    if len(slots) > MAX_EVENTS:
        failures.append("bound")
        slots = slots[:MAX_EVENTS]
    previous = ZERO_HEAD
    produced = 0
    withheld = 0
    for expected_seq, raw_slot in enumerate(slots, start=1):
        slot = raw_slot if isinstance(raw_slot, dict) else {}
        try:
            seq = int(slot.get("seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        if seq != expected_seq:
            failures.append(f"seq:{expected_seq}")
        status = _text(slot.get("status"), 20)
        event_digest = _text(slot.get("event_digest"), 64)
        marker = _text(slot.get("marker"), 64)
        if _text(slot.get("previous"), 64) != previous:
            failures.append(f"previous:{expected_seq}")
        if status == "present":
            produced += 1
            event = slot.get("event") if isinstance(slot.get("event"), dict) else None
            if event is None or _sha(_canonical(event)) != event_digest:
                failures.append(f"event:{expected_seq}")
            if marker:
                failures.append(f"unexpected_marker:{expected_seq}")
        elif status == "withheld":
            withheld += 1
            if slot.get("event") is not None:
                failures.append(f"withheld_content:{expected_seq}")
            if marker != _withheld_marker(run_id, expected_seq, event_digest):
                failures.append(f"marker:{expected_seq}")
        else:
            failures.append(f"status:{expected_seq}")
        computed = _link(previous, expected_seq, status, event_digest, marker)
        if _text(slot.get("head"), 64) != computed:
            failures.append(f"head:{expected_seq}")
        previous = computed
    declared = int(ledger.get("declared") or 0)
    if declared != len(slots):
        failures.append("declared")
    if int(ledger.get("produced") or 0) != produced:
        failures.append("produced")
    if int(ledger.get("withheld") or 0) != withheld:
        failures.append("withheld")
    if _text(ledger.get("head"), 64) != previous:
        failures.append("terminal_head")
    anchor_checked = isinstance(trusted_anchor, dict)
    if anchor_checked:
        expected_anchor = anchor(ledger)
        for key in ("schema", "algorithm", "run_id", "declared", "head"):
            if trusted_anchor.get(key) != expected_anchor.get(key):
                failures.append(f"anchor:{key}")
    unique_failures = list(dict.fromkeys(failures))
    return {
        "schema": f"{SCHEMA}.verification",
        "status": "pass" if not unique_failures else "fail",
        "ok": not unique_failures,
        "anchor_checked": anchor_checked,
        "declared": declared,
        "produced": produced,
        "withheld": withheld,
        "failures": unique_failures,
        "summary": (
            f"event-integrity pass {produced}/{declared}/{withheld}"
            if not unique_failures
            else f"event-integrity fail: {','.join(unique_failures[:6])}"
        ),
    }
