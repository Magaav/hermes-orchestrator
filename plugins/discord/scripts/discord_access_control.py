#!/usr/bin/env python3
"""ACL helper for Discord access control (Colmeio/Hermes).

Source of truth (runtime):
  - /local/workspace/discord/discord_users.json
Fallback (template/backward-compat):
  - /local/plugins/discord/discord_users.json

Quick usage:
  # Authorize an intent and queue approval if needed
  python3 discord/scripts/discord_access_control.py authorize \
    --user-name "Laura" --intent-scope outside_skill \
    --intent-text "I want to edit a skill"

  # List pending requests
  python3 discord/scripts/discord_access_control.py pending

  # Resolve a pending request (approve/deny)
  python3 discord/scripts/discord_access_control.py resolve \
    --request-id <id> --decision approve \
    --admin-name "Victor de Genaro" --reason "ok"
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def _default_db_path() -> Path:
    configured = str(os.getenv("DISCORD_USERS_DB", "") or "").strip()
    if configured:
        return Path(configured)
    candidates = [
        Path("/local/workspace/discord/discord_users.json"),
        Path("/local/plugins/discord/discord_users.json"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


DEFAULT_DB = _default_db_path()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_name(value: str | None) -> str:
    return (value or "").strip().lower()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_db(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"[error] ACL not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("roles", {})
    data.setdefault("users", [])
    data.setdefault("approval_flow", {"enabled": True})
    data.setdefault("pending_requests", [])
    return data


def save_db(path: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = utc_now_iso()
    atomic_write_json(path, data)


def find_user(data: dict[str, Any], discord_user_id: str | None, user_name: str | None) -> dict[str, Any] | None:
    uid = (discord_user_id or "").strip()
    uname = normalize_name(user_name)

    if uid:
        for user in data.get("users", []):
            if str(user.get("discord_user_id") or "").strip() == uid:
                return user

    if uname:
        for user in data.get("users", []):
            if normalize_name(user.get("name")) == uname:
                return user
            aliases = user.get("aliases") or []
            if any(normalize_name(a) == uname for a in aliases):
                return user

    return None


def classify_access(data: dict[str, Any], user: dict[str, Any] | None, intent_scope: str) -> tuple[str, str]:
    """Returns (decision, reason): allow|require_admin_approval|deny."""
    if user is None:
        return "require_admin_approval", "User is not mapped in ACL"

    role_name = str(user.get("role") or "").strip()
    role = (data.get("roles") or {}).get(role_name, {})
    allowed_intents = set(role.get("allowed_intents") or [])
    requires_for = set(role.get("requires_admin_approval_for") or [])

    if "*" in allowed_intents or intent_scope in allowed_intents:
        return "allow", f"role={role_name} allows intent_scope={intent_scope}"

    if "*" in requires_for or intent_scope in requires_for:
        return "require_admin_approval", f"role={role_name} requires approval for intent_scope={intent_scope}"

    return "deny", f"role={role_name} blocks intent_scope={intent_scope}"


def queue_request(
    data: dict[str, Any],
    *,
    requester: dict[str, Any] | None,
    requester_name: str | None,
    requester_id: str | None,
    intent_scope: str,
    intent_text: str,
) -> dict[str, Any]:
    req_id = str(uuid.uuid4())
    request = {
        "request_id": req_id,
        "created_at": utc_now_iso(),
        "status": "pending",
        "requester": {
            "name": requester.get("name") if requester else requester_name,
            "discord_user_id": requester.get("discord_user_id") if requester else requester_id,
            "role": requester.get("role") if requester else None,
        },
        "intent_scope": intent_scope,
        "intent_text": intent_text,
    }
    data.setdefault("pending_requests", []).append(request)
    return request


def resolve_request(
    data: dict[str, Any],
    *,
    request_id: str,
    decision: str,
    admin_user: dict[str, Any] | None,
    admin_name: str | None,
    admin_id: str | None,
    reason: str,
) -> dict[str, Any]:
    pending = data.get("pending_requests", [])
    target = None
    for req in pending:
        if req.get("request_id") == request_id:
            target = req
            break
    if target is None:
        raise SystemExit(f"[error] request_id not found: {request_id}")

    if str(target.get("status")) != "pending":
        raise SystemExit(f"[error] request_id {request_id} is already in status={target.get('status')}")

    # Validate admin
    if admin_user is None or str(admin_user.get("role")) != "admin":
        raise SystemExit("[error] Only users with role=admin can resolve requests")

    target["status"] = "approved" if decision == "approve" else "denied"
    target["resolved_at"] = utc_now_iso()
    target["resolved_by"] = {
        "name": admin_user.get("name") or admin_name,
        "discord_user_id": admin_user.get("discord_user_id") or admin_id,
        "role": admin_user.get("role") or "admin",
    }
    target["resolution_reason"] = reason or ""
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="ACL helper for Discord users")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to discord_users.json")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_auth = sub.add_parser("authorize", help="Classify a request and queue approval when needed")
    p_auth.add_argument("--discord-user-id", default=None)
    p_auth.add_argument("--user-name", default=None)
    p_auth.add_argument(
        "--intent-scope",
        required=True,
        choices=["skill_execute", "skill_manage", "memory_manage", "config_change", "outside_skill", "system_change"],
    )
    p_auth.add_argument("--intent-text", default="")
    p_auth.add_argument("--queue", action="store_true", help="Queue request when decision requires approval")

    p_pending = sub.add_parser("pending", help="List pending requests")

    p_resolve = sub.add_parser("resolve", help="Approve or deny a pending request")
    p_resolve.add_argument("--request-id", required=True)
    p_resolve.add_argument("--decision", required=True, choices=["approve", "deny"])
    p_resolve.add_argument("--admin-discord-user-id", default=None)
    p_resolve.add_argument("--admin-name", default=None)
    p_resolve.add_argument("--reason", default="")

    args = parser.parse_args()
    db_path = Path(args.db).resolve()
    data = load_db(db_path)

    if args.cmd == "authorize":
        user = find_user(data, args.discord_user_id, args.user_name)
        decision, reason = classify_access(data, user, args.intent_scope)

        out: dict[str, Any] = {
            "ok": True,
            "decision": decision,
            "reason": reason,
            "user": user,
            "intent_scope": args.intent_scope,
            "intent_text": args.intent_text,
            "db": str(db_path),
        }

        if decision == "require_admin_approval" and args.queue:
            req = queue_request(
                data,
                requester=user,
                requester_name=args.user_name,
                requester_id=args.discord_user_id,
                intent_scope=args.intent_scope,
                intent_text=args.intent_text,
            )
            save_db(db_path, data)
            out["queued"] = True
            out["request"] = req
        else:
            out["queued"] = False

        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "pending":
        pending = [r for r in data.get("pending_requests", []) if str(r.get("status")) == "pending"]
        print(json.dumps({"ok": True, "count": len(pending), "pending": pending, "db": str(db_path)}, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "resolve":
        admin_user = find_user(data, args.admin_discord_user_id, args.admin_name)
        resolved = resolve_request(
            data,
            request_id=args.request_id,
            decision=args.decision,
            admin_user=admin_user,
            admin_name=args.admin_name,
            admin_id=args.admin_discord_user_id,
            reason=args.reason,
        )
        save_db(db_path, data)
        print(json.dumps({"ok": True, "resolved": resolved, "db": str(db_path)}, ensure_ascii=False, indent=2))
        return 0

    raise SystemExit("Invalid command")


if __name__ == "__main__":
    raise SystemExit(main())
