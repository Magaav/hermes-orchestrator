"""Revision-bound mutation and proof ledger for V5.

The ledger stores compact causal receipts only.  A later mutation advances the
revision, naturally invalidating checks, diff inspection, and proof collected
for an older revision.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


SCHEMA = "master.frontier.v5.operations.v1"
CHECKPOINT_ENCODING = "front-coded-postimages.v1"
MAX_MUTATIONS = 24
MAX_TRACKED_PATHS = 128
MAX_PATH_CHARS = 4096
MAX_CHECKPOINT_LEDGER_CHARS = 14_000


class OperationLedgerError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def new(route_id: str = "") -> dict[str, Any]:
    return {
        "schema": SCHEMA, "route_id": str(route_id or ""), "sequence": 0,
        "revision": 0, "mutations": [], "changed_files": [], "postimages": {},
        "check": None, "diff": None, "proof": None,
    }


def _path(value: Any) -> str:
    path = str(value or "")
    if not path or len(path) > MAX_PATH_CHARS:
        raise OperationLedgerError(
            "operation_ledger_path_bound_exceeded",
            f"A mutation path exceeds the durable {MAX_PATH_CHARS}-character ledger bound.",
        )
    return path


def _paths(values: Any) -> list[str]:
    result = sorted({_path(item) for item in (values or []) if str(item or "")})
    if len(result) > MAX_TRACKED_PATHS:
        raise OperationLedgerError(
            "operation_ledger_file_bound_exceeded",
            f"A mutation would exceed the durable {MAX_TRACKED_PATHS}-file ledger bound.",
        )
    return result


def _decode_postimages(value: dict[str, Any]) -> dict[str, str]:
    rows = value.get("postimages") if isinstance(value.get("postimages"), list) else []
    if len(rows) > MAX_TRACKED_PATHS:
        raise OperationLedgerError(
            "operation_ledger_file_bound_exceeded",
            f"A checkpoint exceeds the durable {MAX_TRACKED_PATHS}-file ledger bound.",
        )
    result: dict[str, str] = {}
    previous = ""
    for row in rows:
        if not isinstance(row, list) or len(row) != 3:
            raise OperationLedgerError("operation_ledger_checkpoint_invalid", "A compact postimage row is invalid.")
        try:
            prefix = int(row[0])
        except (TypeError, ValueError) as exc:
            raise OperationLedgerError("operation_ledger_checkpoint_invalid", "A compact path prefix is invalid.") from exc
        suffix = str(row[1] or "")
        if prefix < 0 or prefix > len(previous):
            raise OperationLedgerError("operation_ledger_checkpoint_invalid", "A compact path prefix is out of range.")
        path = _path(previous[:prefix] + suffix)
        digest = str(row[2] or "")
        if path in result or (digest not in {"deleted", "unverified"} and len(digest) != 64):
            raise OperationLedgerError("operation_ledger_checkpoint_invalid", "A compact postimage receipt is invalid.")
        result[path] = digest
        previous = path
    return result


def _checkpoint_value(value: dict[str, Any]) -> dict[str, Any]:
    proof_rows = value.get("receipts") if isinstance(value.get("receipts"), dict) else {}
    expanded = {
        "schema": SCHEMA,
        "route_id": str(value.get("route_id") or ""),
        "sequence": value.get("sequence"),
        "revision": value.get("revision"),
        "mutations": [
            {
                "seq": row[0], "from": row[1], "to": row[2],
                "action": row[3], "receipt": row[4],
            }
            for row in (value.get("mutations") or [])
            if isinstance(row, list) and len(row) == 5
        ],
        "postimages": _decode_postimages(value),
        "check": proof_rows.get("check"),
        "diff": proof_rows.get("diff"),
        "proof": proof_rows.get("proof"),
    }
    expanded["changed_files"] = sorted(expanded["postimages"])
    return expanded


def normalize(value: Any, *, route_id: str = "") -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        return new(route_id)
    if value.get("encoding") == CHECKPOINT_ENCODING:
        value = _checkpoint_value(value)
    result = new(route_id or str(value.get("route_id") or ""))
    try:
        result["sequence"] = max(0, min(int(value.get("sequence") or 0), 10000))
        result["revision"] = max(0, min(int(value.get("revision") or 0), 10000))
    except (TypeError, ValueError):
        pass
    result["mutations"] = [
        {
            key: item.get(key)
            for key in ("seq", "from", "to", "files", "action", "receipt")
            if item.get(key) not in (None, "", [])
        }
        for item in (value.get("mutations") or [])[-MAX_MUTATIONS:]
        if isinstance(item, dict)
    ]
    postimages = value.get("postimages") if isinstance(value.get("postimages"), dict) else {}
    result["postimages"] = {
        _path(path): str(digest)
        for path, digest in postimages.items()
        if str(path) and (str(digest) in {"deleted", "unverified"} or len(str(digest)) == 64)
    }
    changed = _paths(list(value.get("changed_files") or []) + list(result["postimages"]))
    for path in changed:
        result["postimages"].setdefault(path, "unverified")
    if len(result["postimages"]) > MAX_TRACKED_PATHS:
        raise OperationLedgerError(
            "operation_ledger_file_bound_exceeded",
            f"A mutation would exceed the durable {MAX_TRACKED_PATHS}-file ledger bound.",
        )
    result["changed_files"] = sorted(result["postimages"])
    for key in ("check", "diff", "proof"):
        result[key] = dict(value[key]) if isinstance(value.get(key), dict) else None
    return result


def _front_coded_postimages(postimages: dict[str, str]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    previous = ""
    for path, digest in sorted(postimages.items()):
        prefix = 0
        limit = min(len(previous), len(path))
        while prefix < limit and previous[prefix] == path[prefix]:
            prefix += 1
        rows.append([prefix, path[prefix:], digest])
        previous = path
    return rows


def _proof_receipt(value: Any, *, kind: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    keys = ("seq", "rev", "ok", "worktree", "receipt") + (("id",) if kind == "check" else ())
    return {key: value.get(key) for key in keys if value.get(key) not in (None, "")}


def checkpoint(value: Any, *, route_id: str = "") -> dict[str, Any]:
    """Return one reversible checkpoint representation without derived path copies."""
    ledger = normalize(value, route_id=route_id)
    return {
        "schema": SCHEMA,
        "encoding": CHECKPOINT_ENCODING,
        "route_id": ledger["route_id"],
        "sequence": ledger["sequence"],
        "revision": ledger["revision"],
        "postimages": _front_coded_postimages(ledger["postimages"]),
        "mutations": [
            [
                item.get("seq"), item.get("from"), item.get("to"),
                str(item.get("action") or "")[:80], str(item.get("receipt") or "")[:24],
            ]
            for item in ledger["mutations"]
        ],
        "receipts": {
            key: receipt
            for key in ("check", "diff", "proof")
            if (receipt := _proof_receipt(ledger.get(key), kind=key)) is not None
        },
    }


def ensure_mutation_capacity(value: Any, paths: Any, *, route_id: str = "") -> dict[str, int]:
    """Fail before execution when exact paths cannot fit the reserved ledger budget."""
    ledger = normalize(value, route_id=route_id)
    planned = _paths(list(ledger["postimages"]) + list(paths or []))
    trial = normalize(ledger, route_id=route_id)
    for path in planned:
        trial["postimages"].setdefault(path, "unverified")
    trial["changed_files"] = sorted(trial["postimages"])
    encoded = json.dumps(checkpoint(trial), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_CHECKPOINT_LEDGER_CHARS:
        raise OperationLedgerError(
            "operation_checkpoint_budget_exceeded",
            "The declared mutation paths cannot fit the reserved restart checkpoint ledger budget.",
        )
    return {"files": len(planned), "checkpoint_chars": len(encoded)}


def _payload(item: dict[str, Any]) -> dict[str, Any]:
    result = item.get("result") if isinstance(item.get("result"), dict) else item
    return result.get("result") if isinstance(result.get("result"), dict) else result


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]


def worktree_digest(ledger: dict[str, Any]) -> str:
    value = normalize(ledger)
    raw = json.dumps(value["postimages"], ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def verification_receipt_satisfied(ledger: dict[str, Any], tool: str) -> bool:
    key = {"test": "check", "diff": "diff", "prove": "proof"}.get(str(tool or ""))
    if key is None:
        return True
    value = normalize(ledger)
    receipt = value.get(key) if isinstance(value.get(key), dict) else {}
    return receipt.get("rev") == value["revision"] and receipt.get("ok") is True


def _changed(payload: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for value in payload.get("changed_files") or []:
        if isinstance(value, dict):
            for key in ("path", "old_path"):
                if value.get(key):
                    result.append(str(value[key])[:300])
        elif value:
            result.append(str(value)[:300])
    return sorted(set(result))


def record(ledger: dict[str, Any], tool: str, observed: dict[str, Any], *, action_id: str = "") -> dict[str, Any]:
    ledger = normalize(ledger)
    ledger["sequence"] += 1
    if observed.get("ok") is not True:
        return ledger
    payload = _payload(observed)
    action = str(observed.get("local_action") or payload.get("local_action") or "")
    if tool == "edit" or action == "patch.apply_scoped":
        clean_action_id = str(action_id or "")[:80]
        if clean_action_id and any(item.get("action") == clean_action_id for item in ledger["mutations"]):
            return ledger
        changed = _changed(payload)
        if not changed or payload.get("dry_run") is True or payload.get("applied") is not True:
            return ledger
        before = ledger["revision"]
        ledger["revision"] += 1
        ledger["changed_files"] = sorted(set(ledger["changed_files"]) | set(changed))
        postimages = payload.get("postimage_sha256") if isinstance(payload.get("postimage_sha256"), dict) else {}
        for path in changed:
            value = str(postimages.get(path) or "")
            if value == "deleted" or len(value) == 64:
                ledger["postimages"][path] = value
            else:
                ledger["postimages"][path] = "unverified"
        ledger["mutations"].append({
            "seq": ledger["sequence"], "from": before, "to": ledger["revision"],
            "files": changed, "action": clean_action_id,
            "receipt": _digest({"changed": changed, "post": payload.get("postimage_sha256")}),
        })
        ledger["mutations"] = ledger["mutations"][-MAX_MUTATIONS:]
        return ledger
    if tool == "test" or action == "test.run_focused":
        ok = (
            "returncode" in payload
            and int(payload.get("returncode") or 0) == 0
            and str(payload.get("code") or "ok") == "ok"
        )
        ledger["check"] = {
            "seq": ledger["sequence"], "rev": ledger["revision"], "ok": ok,
            "id": str(payload.get("check_id") or "")[:120],
            "worktree": str(observed.get("worktree_sha256") or payload.get("worktree_sha256") or "")[:64],
            "receipt": _digest(payload),
        }
        return ledger
    schema = str(payload.get("schema") or "")
    if tool == "diff" or action == "git.diff_summary" or "git_diff_summary" in schema:
        files = _changed(payload)
        covers = set(ledger["changed_files"]).issubset(files)
        stat = payload.get("stat") if isinstance(payload.get("stat"), dict) else {}
        truncation = payload.get("truncation") if isinstance(payload.get("truncation"), dict) else {}
        complete = stat.get("complete") is True
        untruncated = not any(bool(value) for value in truncation.values())
        ledger["diff"] = {
            "seq": ledger["sequence"], "rev": ledger["revision"],
            "ok": (
                payload.get("ok") is True
                and str(payload.get("code") or "") == "ok"
                and int(payload.get("returncode") or 0) == 0
                and complete and untruncated and covers
            ),
            "files": files, "receipt": _digest(payload),
            "worktree": str(observed.get("worktree_sha256") or payload.get("worktree_sha256") or "")[:64],
        }
        return ledger
    if tool == "prove" or observed.get("primitive") == "kernel.prove" or "kernel.prove" in schema:
        current_worktree = str(observed.get("worktree_sha256") or payload.get("worktree_sha256") or "")[:64]
        gaps = missing(ledger, include_proof=False, worktree=current_worktree or None)
        ledger["proof"] = {
            "seq": ledger["sequence"], "rev": ledger["revision"], "ok": not gaps,
            "requirements": ["mutation", "passing_check", "diff"], "gaps": gaps,
            "worktree": current_worktree,
            "receipt": _digest({"rev": ledger["revision"], "gaps": gaps, "provider": payload}),
        }
    return ledger


def missing(
    ledger: dict[str, Any], *, include_proof: bool = True, worktree: str | None = None,
) -> list[str]:
    value = normalize(ledger)
    if not value["mutations"]:
        return []
    revision = value["revision"]
    if not worktree:
        worktree = next((
            str((value.get(key) or {}).get("worktree") or "")
            for key in ("proof", "diff", "check")
            if str((value.get(key) or {}).get("worktree") or "")
        ), worktree_digest(value))
    gaps: list[str] = []
    check = value.get("check") or {}
    if check.get("rev") != revision or check.get("ok") is not True or check.get("worktree") != worktree:
        gaps.append("passing focused test at current revision")
    diff = value.get("diff") or {}
    if diff.get("rev") != revision or diff.get("ok") is not True or diff.get("worktree") != worktree:
        gaps.append("diff inspection at current revision")
    if include_proof:
        proof = value.get("proof") or {}
        if proof.get("rev") != revision or proof.get("ok") is not True or proof.get("worktree") != worktree:
            gaps.append("scoped proof at current revision")
    return gaps


def verification_missing(ledger: dict[str, Any]) -> list[str]:
    """Return proof gaps for a read-only verification workflow."""
    value = normalize(ledger)
    revision = value["revision"]
    gaps: list[str] = []
    check = value.get("check") or {}
    if check.get("rev") != revision or check.get("ok") is not True:
        gaps.append("passing focused test")
    proof = value.get("proof") or {}
    if proof.get("rev") != revision or proof.get("ok") is not True:
        gaps.append("scoped proof")
    return gaps


def project(ledger: dict[str, Any]) -> dict[str, Any]:
    value = normalize(ledger)
    return {
        "rev": value["revision"], "mutations": len(value["mutations"]),
        "changed": value["changed_files"], "gaps": missing(value),
    }
