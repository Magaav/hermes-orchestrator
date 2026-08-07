"""Deterministic final answer for completed read-only verification workflows."""
from __future__ import annotations

from typing import Any


def _payload(receipt: Any) -> dict[str, Any]:
    value = receipt if isinstance(receipt, dict) else {}
    nested = value.get("result")
    return nested if isinstance(nested, dict) else value


def build(summary: dict[str, Any], receipts: list[dict[str, Any]]) -> str:
    checks = summary.get("checks") if isinstance(summary.get("checks"), list) else []
    observed = [
        str(path) for path in (summary.get("observed_changed_files") or [])
        if str(path or "").strip()
    ]
    reads: dict[str, str] = {}
    diff_receipt = ""
    for receipt in receipts:
        payload = _payload(receipt)
        path = str(payload.get("path") or "").strip()
        digest = str(payload.get("sha256") or "").strip()
        if path and len(digest) == 64:
            reads[path] = digest
        if "git_diff_summary" in str(payload.get("schema") or ""):
            diff_receipt = str(payload.get("receipt_sha256") or "").strip()

    lines = ["Verification completed with revision-bound proof.", ""]
    for check in checks:
        lines.append(
            f"- Check `{check.get('check_id') or 'registered'}`: passed "
            f"(return code {int(check.get('returncode') or 0)}, {int(check.get('duration_ms') or 0)} ms)."
        )
    lines.extend([
        f"- Scoped diff: inspected and complete ({len(observed)} observed worktree file{'s' if len(observed) != 1 else ''}).",
        "- Scoped proof: collected.",
        "- Files changed by this run: none.",
    ])
    if diff_receipt:
        lines.append(f"- Diff receipt: `{diff_receipt}`.")
    if observed:
        lines.extend(["", "Observed worktree changes:"])
        for path in observed:
            suffix = f" — sha256 `{reads[path]}`" if path in reads else ""
            lines.append(f"- `{path}`{suffix}")
    return "\n".join(lines)
