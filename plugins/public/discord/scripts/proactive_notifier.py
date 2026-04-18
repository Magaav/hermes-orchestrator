#!/usr/bin/env python3
"""Proactive Discord notifier (Colmeio/Hermes).

Goal:
- Send IMMEDIATE alerts to the master channel when relevant events happen.
- Send a daily DIGEST with insights when there is useful signal (without spam).

Main config:
- /local/plugins/private/discord/discord_users.json

Run:
  python3 discord/scripts/proactive_notifier.py immediate
  python3 discord/scripts/proactive_notifier.py digest
  python3 discord/scripts/proactive_notifier.py immediate --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

def _resolve_project_dir() -> Path:
    explicit = str(os.getenv("COLMEIO_PROJECT_DIR", "") or "").strip()
    if explicit:
        return Path(explicit).resolve()

    workspace = Path("/local/workspace").resolve()
    if workspace.exists():
        return workspace

    canonical = Path("/local").resolve()
    return canonical


def _resolve_acl_path(project_dir: Path) -> Path:
    configured = str(os.getenv("DISCORD_USERS_DB", "") or "").strip()
    if configured:
        return Path(configured).resolve()

    candidates = [
        Path("/local/plugins/private/discord/discord_users.json"),
        project_dir / "plugins" / "private" / "discord" / "discord_users.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


PROJECT_DIR = _resolve_project_dir()
ACL_PATH = _resolve_acl_path(PROJECT_DIR)
STATE_PATH = Path(
    os.getenv(
        "PROACTIVE_NOTIFIER_STATE",
        str(PROJECT_DIR / "data" / ".proactive_notifier_state.json"),
    )
).resolve()
ENV_PATH = PROJECT_DIR / ".env"

def _resolve_skill_dir(skill_name: str) -> Path:
    configured = str(os.getenv("COLMEIO_SKILL_DIR", "") or "").strip()
    if configured:
        return Path(configured).resolve().parent / skill_name
    return Path("/local/skills/custom/colmeio") / skill_name


_FALTAS_SKILL_DIR = _resolve_skill_dir("colmeio-lista-de-faltas")
PIPELINE_LOG = (
    _FALTAS_SKILL_DIR / "logs" / "pipeline.log"
)
PIPELINE_ERROR_LOG = (
    _FALTAS_SKILL_DIR / "logs" / "pipeline.error.log"
)


@dataclass
class RuntimeConfig:
    channel_id: str
    timezone_name: str
    only_if_matters_digest: bool


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Supports Z suffix
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return default.copy() if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default.copy() if default is not None else {}


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        val = v.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        env[key] = val
    return env


def resolve_runtime_config(acl: dict[str, Any]) -> RuntimeConfig:
    proactive = (acl.get("proactive") or {})
    delivery = str(proactive.get("delivery_target") or "").strip()
    channel_id = ""
    if delivery.startswith("discord:"):
        channel_id = delivery.split(":", 1)[1].strip()

    if not channel_id:
        master = (acl.get("channels") or {}).get("master") or {}
        channel_id = str(master.get("discord_channel_id") or "").strip()

    digest = proactive.get("digest") or {}
    timezone_name = str(digest.get("timezone") or "UTC").strip() or "UTC"
    only_if_matters = bool(digest.get("only_if_matters", True))

    return RuntimeConfig(
        channel_id=channel_id,
        timezone_name=timezone_name,
        only_if_matters_digest=only_if_matters,
    )


def read_jsonl_since(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0

    current_size = path.stat().st_size
    if offset < 0 or offset > current_size:
        offset = 0

    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        fh.seek(offset)
        for line in fh:
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    out.append(obj)
            except Exception:
                continue
        new_offset = fh.tell()
    return out, new_offset


def read_jsonl_all(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    out.append(obj)
            except Exception:
                continue
    return out


def format_error_summary(error_texts: list[str], limit: int = 3) -> list[str]:
    counts = Counter([e.strip() for e in error_texts if str(e).strip()])
    lines: list[str] = []
    for msg, cnt in counts.most_common(limit):
        short = msg if len(msg) <= 140 else msg[:137] + "..."
        lines.append(f"- ({cnt}x) {short}")
    return lines


def chunk_discord_message(text: str, max_len: int = 1900) -> list[str]:
    s = text.strip()
    if len(s) <= max_len:
        return [s]
    parts: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for line in s.splitlines():
        extra = len(line) + 1
        if cur and cur_len + extra > max_len:
            parts.append("\n".join(cur).strip())
            cur = [line]
            cur_len = len(line) + 1
        else:
            cur.append(line)
            cur_len += extra
    if cur:
        parts.append("\n".join(cur).strip())
    return [p for p in parts if p]


def send_discord_message(channel_id: str, token: str, content: str) -> tuple[bool, str]:
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    chunks = chunk_discord_message(content)
    for chunk in chunks:
        resp = requests.post(url, headers=headers, json={"content": chunk}, timeout=20)
        if not (200 <= resp.status_code < 300):
            return False, f"HTTP {resp.status_code}: {resp.text[:300]}"
    return True, "ok"


def build_immediate_message(
    acl: dict[str, Any],
    state: dict[str, Any],
    max_errors: int = 5,
) -> tuple[str | None, dict[str, Any]]:
    changed = False

    pending_requests = acl.get("pending_requests") or []
    notified_pending_ids = set(state.get("notified_pending_request_ids") or [])

    new_pending: list[dict[str, Any]] = []
    for req in pending_requests:
        if str(req.get("status")) != "pending":
            continue
        rid = str(req.get("request_id") or "").strip()
        if not rid or rid in notified_pending_ids:
            continue
        new_pending.append(req)
        notified_pending_ids.add(rid)
        changed = True

    state["notified_pending_request_ids"] = sorted(notified_pending_ids)

    err_offset = int(state.get("error_log_offset") or 0)
    new_error_logs, new_err_offset = read_jsonl_since(PIPELINE_ERROR_LOG, err_offset)
    if new_err_offset != err_offset:
        state["error_log_offset"] = new_err_offset
        changed = True

    pipeline_offset = int(state.get("pipeline_log_offset") or 0)
    new_pipeline_logs, new_pipeline_offset = read_jsonl_since(PIPELINE_LOG, pipeline_offset)
    if new_pipeline_offset != pipeline_offset:
        state["pipeline_log_offset"] = new_pipeline_offset
        changed = True

    blocked_errors: list[str] = []
    generic_errors: list[str] = []
    for row in new_error_logs:
        extra = row.get("extra") or {}
        err = str(extra.get("error") or row.get("message") or "").strip()
        low = err.lower()
        if any(
            k in low
            for k in [
                "blocked",
                "bloqueado",
                "not authorized",
                "nao autorizado",
                "não autorizado",
                "required",
                "obrigatorio",
                "obrigatório",
            ]
        ):
            blocked_errors.append(err)
        else:
            generic_errors.append(err)

    risky_clears = [
        r
        for r in new_pipeline_logs
        if str(r.get("action")) == "clear" and str(r.get("message")) == "success"
    ]

    if not new_pending and not blocked_errors and not generic_errors and not risky_clears:
        return None, state

    lines: list[str] = ["🚨 **Hermes - Immediate alert**"]

    if new_pending:
        lines.append(f"\n📝 **New pending approvals:** {len(new_pending)}")
        for req in new_pending[:4]:
            rid = req.get("request_id")
            requester = (req.get("requester") or {}).get("name") or "(unnamed)"
            scope = req.get("intent_scope") or "(no scope)"
            text = str(req.get("intent_text") or "").strip()
            text = text if len(text) <= 120 else text[:117] + "..."
            lines.append(f"- `{rid}` • {requester} • `{scope}` • {text}")
        if len(new_pending) > 4:
            lines.append(f"- ... +{len(new_pending) - 4} more request(s)")

    if blocked_errors:
        lines.append(f"\n⛔ **New blocked operations:** {len(blocked_errors)}")
        lines.extend(format_error_summary(blocked_errors, limit=max_errors))

    if generic_errors:
        lines.append(f"\n❌ **New errors:** {len(generic_errors)}")
        lines.extend(format_error_summary(generic_errors, limit=max_errors))

    if risky_clears:
        lines.append(f"\n⚠️ **Sensitive actions completed:** clear executed {len(risky_clears)}x")

    lines.append("\n_Use the approval flow to allow requests outside the skill scope._")
    return "\n".join(lines).strip(), state if changed else state


def filter_last_hours(rows: list[dict[str, Any]], hours: int) -> list[dict[str, Any]]:
    cutoff = utc_now() - timedelta(hours=hours)
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = parse_ts(str(row.get("ts") or ""))
        if ts and ts >= cutoff:
            out.append(row)
    return out


def build_digest_message(acl: dict[str, Any]) -> str | None:
    last24_pipeline = filter_last_hours(read_jsonl_all(PIPELINE_LOG), 24)
    last24_errors = filter_last_hours(read_jsonl_all(PIPELINE_ERROR_LOG), 24)

    if not last24_pipeline and not last24_errors:
        return None

    success_actions = Counter(
        str(r.get("action"))
        for r in last24_pipeline
        if str(r.get("level")) == "info" and str(r.get("message")) == "success"
    )
    confirmations = sum(
        1
        for r in last24_pipeline
        if str(r.get("action")) == "clear" and str(r.get("message")) == "confirmation_required"
    )
    clears = int(success_actions.get("clear", 0))
    adds = int(success_actions.get("add", 0))
    removes = int(success_actions.get("remove", 0))
    lists = int(success_actions.get("list", 0))
    syncs = int(success_actions.get("sync", 0))

    pending = [r for r in (acl.get("pending_requests") or []) if str(r.get("status")) == "pending"]

    err_texts = [str((r.get("extra") or {}).get("error") or r.get("message") or "") for r in last24_errors]

    lines: list[str] = ["📊 **Hermes - Daily digest (last 24h)**"]
    lines.append(
        f"- Completed operations: list={lists}, add={adds}, remove={removes}, sync={syncs}, clear={clears}"
    )

    if confirmations:
        lines.append(f"- Clear guardrail triggered (confirmation_required): {confirmations}x")

    if last24_errors:
        lines.append(f"- Errors: {len(last24_errors)}")
        lines.extend(format_error_summary(err_texts, limit=3))
    else:
        lines.append("- Errors: 0 ✅")

    if pending:
        lines.append(f"- Current pending approvals: {len(pending)}")
    else:
        lines.append("- Current pending approvals: 0 ✅")

    # Lightweight trend insights (without inventing metrics)
    if adds >= 8 and adds > (removes * 2):
        lines.append("\n💡 Insight: add volume is high vs remove; review replenishment/out-of-stock by store.")
    if clears >= 2:
        lines.append("💡 Insight: multiple clears happened today; verify whether this was planned or an unintended reset.")
    if len(last24_errors) >= 3:
        lines.append("💡 Insight: error rate is high in the last 24h; investigate recurring causes.")

    return "\n".join(lines).strip()


def run_immediate(dry_run: bool = False) -> int:
    acl = load_json(ACL_PATH, default={})
    cfg = resolve_runtime_config(acl)
    state = load_json(
        STATE_PATH,
        default={
            "error_log_offset": 0,
            "pipeline_log_offset": 0,
            "notified_pending_request_ids": [],
        },
    )

    message, new_state = build_immediate_message(acl, state)
    save_json(STATE_PATH, new_state)

    if not message:
        print(json.dumps({"ok": True, "sent": False, "reason": "no_new_relevant_events"}, ensure_ascii=False))
        return 0

    if dry_run:
        print(json.dumps({"ok": True, "sent": False, "dry_run": True, "message": message}, ensure_ascii=False, indent=2))
        return 0

    env = read_env(ENV_PATH)
    token = str(env.get("DISCORD_BOT_TOKEN") or "").strip()
    if not cfg.channel_id:
        print(json.dumps({"ok": False, "sent": False, "error": "missing channel_id in ACL config"}, ensure_ascii=False))
        return 1
    if not token:
        print(json.dumps({"ok": False, "sent": False, "error": "missing DISCORD_BOT_TOKEN in .env"}, ensure_ascii=False))
        return 1

    ok, status = send_discord_message(cfg.channel_id, token, message)
    print(json.dumps({"ok": ok, "sent": ok, "status": status, "channel_id": cfg.channel_id}, ensure_ascii=False))
    return 0 if ok else 1


def run_digest(dry_run: bool = False) -> int:
    acl = load_json(ACL_PATH, default={})
    cfg = resolve_runtime_config(acl)
    msg = build_digest_message(acl)

    if not msg:
        print(json.dumps({"ok": True, "sent": False, "reason": "no_activity_last_24h"}, ensure_ascii=False))
        return 0

    if cfg.only_if_matters_digest:
        # Lightweight anti-noise filter: requires at least one explicit signal
        interesting = any(x in msg for x in ["Errors:", "pending", "Insight", "clear="])
        if not interesting:
            print(json.dumps({"ok": True, "sent": False, "reason": "digest_not_interesting"}, ensure_ascii=False))
            return 0

    if dry_run:
        print(json.dumps({"ok": True, "sent": False, "dry_run": True, "message": msg}, ensure_ascii=False, indent=2))
        return 0

    env = read_env(ENV_PATH)
    token = str(env.get("DISCORD_BOT_TOKEN") or "").strip()
    if not cfg.channel_id:
        print(json.dumps({"ok": False, "sent": False, "error": "missing channel_id in ACL config"}, ensure_ascii=False))
        return 1
    if not token:
        print(json.dumps({"ok": False, "sent": False, "error": "missing DISCORD_BOT_TOKEN in .env"}, ensure_ascii=False))
        return 1

    ok, status = send_discord_message(cfg.channel_id, token, msg)
    print(json.dumps({"ok": ok, "sent": ok, "status": status, "channel_id": cfg.channel_id}, ensure_ascii=False))
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Colmeio proactive notifier")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_immediate = sub.add_parser("immediate", help="Check immediate events and notify when needed")
    p_immediate.add_argument("--dry-run", action="store_true")

    p_digest = sub.add_parser("digest", help="Send daily digest with insights")
    p_digest.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if args.mode == "immediate":
        return run_immediate(dry_run=args.dry_run)
    if args.mode == "digest":
        return run_digest(dry_run=args.dry_run)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
