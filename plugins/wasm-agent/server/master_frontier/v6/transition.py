"""One-shot semantic post-state or recovery projections for V6 operations."""
from __future__ import annotations

from typing import Any

from . import contracts


RAW_RESULT_CHARS = 4_000
MODEL_PROJECTION_CHARS = 12_000


def _failure_view(receipt: dict[str, Any], detail_ref: str) -> dict[str, Any]:
    observed = receipt.get("observed") if isinstance(receipt.get("observed"), dict) else {}
    compact_observed = {
        key: observed[key]
        for key in (
            "failureClassification", "code", "failedStepIndex", "failedAction",
            "failedLocator", "cause", "recovery", "url", "title", "postcondition",
        )
        if key in observed
    }
    content = contracts.canonical({
        "id": receipt.get("id"), "op": receipt.get("op"), "ok": False,
        "state": receipt.get("state"), "error": receipt.get("error") or {},
        "observed": compact_observed,
    })[:MODEL_PROJECTION_CHARS]
    return {
        "schema": "master.frontier.v6.evidence.view.v1", "trust": "untrusted-data",
        "detail_ref": detail_ref, "pointer": "/recovery", "encoding": "canonical-json",
        "offset": 0, "end": len(content), "total_chars": len(content),
        "truncated": False, "next_offset": None, "content": content,
    }


def project(
    kernel: Any,
    operations: list[dict[str, Any]],
    receipts: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return each operation's smallest complete post-state or recovery receipt once."""
    projected = []
    for operation, receipt, evidence_item in zip(operations, receipts, evidence_items):
        detail_ref = str(evidence_item.get("detail_ref") or "")
        if receipt.get("ok") is not True:
            view = _failure_view(receipt, detail_ref)
        else:
            view = kernel.evidence.view(detail_ref, max_chars=RAW_RESULT_CHARS)
            if view is None or view.get("truncated") is True:
                try:
                    view = kernel.evidence.view(
                        detail_ref, pointer="/observed/model_projection",
                        max_chars=MODEL_PROJECTION_CHARS,
                    )
                except contracts.ContractError:
                    view = None
                if view is None or view.get("truncated") is True:
                    continue
        projected.append({
            **evidence_item,
            "kind": "operation.transition",
            "summary": (
                f"One-shot post-state for {str(operation.get('id') or '')[:160]}."
                if receipt.get("ok") is True
                else f"One-shot recovery receipt for {str(operation.get('id') or '')[:160]}."
            ),
            "payload": view,
        })
    return projected


def consume(active_details: dict[str, dict[str, Any]]) -> int:
    """Discard one-shot evidence while retaining already-loaded capability schemas."""
    retained = {
        key: item for key, item in active_details.items()
        if str(item.get("kind") or "") == "capability.detail"
    }
    consumed = len(active_details) - len(retained)
    active_details.clear()
    active_details.update(retained)
    return consumed


def key(item: dict[str, Any]) -> str:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return contracts.digest({
        "id": item.get("id"), "detail_ref": payload.get("detail_ref"),
        "pointer": payload.get("pointer"), "offset": payload.get("offset"),
    })
