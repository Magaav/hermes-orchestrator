#!/usr/bin/env python3
"""Thin OpenViking adapter for Hermes memory/retrieval integration.

This module is intentionally standalone (stdlib-only) so it can be imported by
gateway hooks, cron jobs, or test scripts without extra dependencies.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


LOG_PATH = Path("/local/logs/openviking/adapter.log")


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _log(level: str, event: str, **extra: Any) -> None:
    payload: Dict[str, Any] = {"ts": _utc_now(), "level": level, "event": event}
    payload.update(extra)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _is_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class OpenVikingAdapterError(RuntimeError):
    pass


class OpenVikingAdapter:
    """HTTP adapter used by Hermes hooks/tools to interact with OpenViking."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        account: Optional[str] = None,
        user: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_sec: float = 20.0,
        retries: int = 3,
    ) -> None:
        self.endpoint = str(endpoint or os.getenv("OPENVIKING_ENDPOINT", "http://127.0.0.1:1933")).rstrip("/")
        self.account = str(account or os.getenv("OPENVIKING_ACCOUNT", "colmeio")).strip() or "colmeio"
        self.user = str(user or os.getenv("OPENVIKING_USER", "default")).strip() or "default"
        self.api_key = str(api_key or os.getenv("OPENVIKING_API_KEY", "")).strip()
        self.timeout_sec = float(timeout_sec)
        self.retries = max(1, int(retries))

    # ---------------------------------------------------------------------
    # HTTP primitives
    # ---------------------------------------------------------------------

    def _headers(self, *, json_body: bool = True) -> Dict[str, str]:
        headers = {
            "X-OpenViking-Account": self.account,
            "X-OpenViking-User": self.user,
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
        timeout_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        url = f"{self.endpoint}{path}"
        if query:
            clean_query = {k: v for k, v in query.items() if v is not None}
            url += "?" + urllib.parse.urlencode(clean_query, doseq=True)

        raw_body: Optional[bytes] = None
        if payload is not None:
            raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        timeout = float(timeout_sec if timeout_sec is not None else self.timeout_sec)
        last_error: Optional[str] = None
        for attempt in range(1, self.retries + 1):
            req = urllib.request.Request(
                url=url,
                data=raw_body,
                headers=self._headers(json_body=True),
                method=method.upper(),
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
                    raw = resp.read().decode("utf-8", errors="replace")
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = f"HTTP {exc.code}: {detail[:400]}"
                if attempt >= self.retries:
                    break
                time.sleep(min(0.2 * attempt, 1.0))
            except Exception as exc:
                last_error = str(exc)
                if attempt >= self.retries:
                    break
                time.sleep(min(0.2 * attempt, 1.0))

        raise OpenVikingAdapterError(last_error or f"request failed: {method} {url}")

    # ---------------------------------------------------------------------
    # Core operations
    # ---------------------------------------------------------------------

    def health(self) -> bool:
        try:
            self._request_json("GET", "/health", timeout_sec=3.0)
            return True
        except Exception as exc:
            _log("warning", "health.failed", error=str(exc), endpoint=self.endpoint)
            return False

    def recall(self, query: str, *, target_uri: str = "", limit: int = 6) -> List[Dict[str, Any]]:
        payload = {
            "query": query,
            "target_uri": target_uri or "",
            "limit": max(1, int(limit)),
            "include_provenance": True,
            "telemetry": True,
        }
        data = self._request_json("POST", "/api/v1/search/search", payload=payload)
        result = data.get("result") if isinstance(data, dict) else {}
        resources = result.get("resources") if isinstance(result, dict) else []
        memories = result.get("memories") if isinstance(result, dict) else []
        skills = result.get("skills") if isinstance(result, dict) else []
        merged: List[Dict[str, Any]] = []
        for item in memories + resources + skills:
            if isinstance(item, dict):
                merged.append(item)
        _log(
            "info",
            "recall.ok",
            query=query,
            target_uri=target_uri,
            count=len(merged),
        )
        return merged

    def commit_memory(
        self,
        content: str,
        *,
        category: str = "events",
        namespace_user: Optional[str] = None,
    ) -> str:
        user_id = str(namespace_user or self.user).strip() or self.user
        safe_category = "".join(ch for ch in str(category or "events").lower() if ch.isalnum() or ch in {"-", "_"})
        if not safe_category:
            safe_category = "events"
        ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        # `/api/v1/resources` accepts resources scope targets. Keep per-user
        # isolation under a stable memory namespace:
        #   viking://resources/memory/<user>/<category>/<timestamp>.md
        uri = f"viking://resources/memory/{user_id}/{safe_category}/{ts}.md"

        parent_uri = f"viking://resources/memory/{user_id}/{safe_category}"
        try:
            self._request_json("POST", "/api/v1/fs/mkdir", payload={"uri": parent_uri})
        except OpenVikingAdapterError as exc:
            # OpenViking may return INTERNAL/500 when mkdir is called on an
            # existing directory. Treat this as idempotent success.
            lowered = str(exc).lower()
            if "already exists" not in lowered and "directory exists" not in lowered:
                raise
            _log("info", "commit_memory.mkdir_exists", parent_uri=parent_uri)

        # content/write requires an existing file. We add via temp_upload + resources.
        tmp_path = Path(f"/tmp/ov-memory-{ts}.md")
        tmp_path.write_text(content.strip() + "\n", encoding="utf-8")
        try:
            temp_file_id = self._temp_upload(tmp_path)
            self._request_json(
                "POST",
                "/api/v1/resources",
                payload={
                    "temp_file_id": temp_file_id,
                    "to": uri,
                    "wait": True,
                    "timeout": 60,
                },
            )
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass

        _log("info", "commit_memory.ok", uri=uri, category=safe_category)
        return uri

    def build_context_block(self, query: str, *, target_uri: str = "", limit: int = 6) -> str:
        items = self.recall(query, target_uri=target_uri, limit=limit)
        if not items:
            return ""
        lines = ["## OpenViking Context"]
        for item in items[:limit]:
            uri = str(item.get("uri", "") or "")
            score = item.get("score")
            abstract = str(item.get("abstract", "") or "").strip()
            prefix = f"- [{score:.3f}] " if isinstance(score, (float, int)) else "- "
            lines.append(f"{prefix}{abstract or '(no abstract)'} ({uri})")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Multipart upload helper
    # ------------------------------------------------------------------

    def _temp_upload(self, file_path: Path) -> str:
        boundary = f"ov_{int(time.time() * 1000)}"
        data = file_path.read_bytes()
        body = b"".join(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                b'Content-Disposition: form-data; name="file"; filename="memory.md"\r\n',
                b"Content-Type: text/markdown\r\n\r\n",
                data,
                b"\r\n",
                f"--{boundary}--\r\n".encode("utf-8"),
            ]
        )

        url = f"{self.endpoint}/api/v1/resources/temp_upload"
        req = urllib.request.Request(url=url, data=body, method="POST")
        for key, value in self._headers(json_body=False).items():
            req.add_header(key, value)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

        with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:  # nosec B310
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        temp_file_id = str((payload.get("result") or {}).get("temp_file_id") or "").strip()
        if not temp_file_id:
            raise OpenVikingAdapterError("temp_upload did not return temp_file_id")
        return temp_file_id


def _cmd_recall(adapter: OpenVikingAdapter, args: argparse.Namespace) -> int:
    rows = adapter.recall(args.query, target_uri=args.target_uri, limit=args.limit)
    print(json.dumps({"ok": True, "count": len(rows), "items": rows}, ensure_ascii=False))
    return 0


def _cmd_commit(adapter: OpenVikingAdapter, args: argparse.Namespace) -> int:
    uri = adapter.commit_memory(args.content, category=args.category)
    print(json.dumps({"ok": True, "uri": uri}, ensure_ascii=False))
    return 0


def _cmd_context(adapter: OpenVikingAdapter, args: argparse.Namespace) -> int:
    block = adapter.build_context_block(args.query, target_uri=args.target_uri, limit=args.limit)
    print(block or "(no context)")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenViking adapter CLI")
    parser.add_argument("--endpoint", default=os.getenv("OPENVIKING_ENDPOINT", "http://127.0.0.1:1933"))
    parser.add_argument("--account", default=os.getenv("OPENVIKING_ACCOUNT", "colmeio"))
    parser.add_argument("--user", default=os.getenv("OPENVIKING_USER", "default"))
    parser.add_argument("--api-key", default=os.getenv("OPENVIKING_API_KEY", ""))
    parser.add_argument("--timeout-sec", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=3)

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_recall = sub.add_parser("recall", help="Run semantic recall")
    p_recall.add_argument("--query", required=True)
    p_recall.add_argument("--target-uri", default="")
    p_recall.add_argument("--limit", type=int, default=6)

    p_commit = sub.add_parser("commit", help="Commit a memory note")
    p_commit.add_argument("--content", required=True)
    p_commit.add_argument("--category", default="events")

    p_context = sub.add_parser("context", help="Build Hermes-ready context block")
    p_context.add_argument("--query", required=True)
    p_context.add_argument("--target-uri", default="")
    p_context.add_argument("--limit", type=int, default=6)

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    adapter = OpenVikingAdapter(
        endpoint=args.endpoint,
        account=args.account,
        user=args.user,
        api_key=args.api_key,
        timeout_sec=args.timeout_sec,
        retries=args.retries,
    )

    if args.cmd == "recall":
        return _cmd_recall(adapter, args)
    if args.cmd == "commit":
        return _cmd_commit(adapter, args)
    if args.cmd == "context":
        return _cmd_context(adapter, args)
    raise OpenVikingAdapterError(f"unsupported command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
