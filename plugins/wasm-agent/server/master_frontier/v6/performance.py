"""Compact, non-overlapping latency and projection accounting for V6 runs."""
from __future__ import annotations

import json
import time
from typing import Any, Callable


SCHEMA = "master.frontier.v6.performance.v1"


def _bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


class Trace:
    def __init__(
        self, *, started_monotonic: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.monotonic = monotonic
        self.entered = monotonic()
        self.started = min(self.entered, float(started_monotonic or self.entered))
        self.provider_calls: list[dict[str, Any]] = []
        self.checkpoint_count = 0
        self.checkpoint_ms = 0

    def provider_started(self, body: dict[str, Any], decision: int) -> dict[str, Any]:
        messages = body.get("messages") if isinstance(body.get("messages"), list) else []
        tools = body.get("tools") if isinstance(body.get("tools"), list) else []
        return {
            "decision": max(1, int(decision)), "started": self.monotonic(),
            "projection": {
                "body_bytes": _bytes(body),
                "messages_bytes": _bytes(messages),
                "tools_bytes": _bytes(tools),
                "message_content_bytes": sum(
                    len(str(item.get("content") or "").encode("utf-8"))
                    for item in messages if isinstance(item, dict)
                ),
            },
        }

    def provider_finished(self, call: dict[str, Any], *, ok: bool) -> None:
        ended = self.monotonic()
        self.provider_calls.append({
            **call, "ended": ended, "duration_ms": max(0, round((ended - call["started"]) * 1000)),
            "ok": bool(ok),
        })

    def checkpoint_finished(self, started: float) -> None:
        self.checkpoint_count += 1
        self.checkpoint_ms += max(0, round((self.monotonic() - started) * 1000))

    def snapshot(self) -> dict[str, Any]:
        ended = self.monotonic()
        calls = sorted(self.provider_calls, key=lambda item: item["started"])
        provider_ms = sum(int(item["duration_ms"]) for item in calls)
        if calls:
            before_ms = max(0, round((calls[0]["started"] - self.entered) * 1000))
            between_ms = sum(
                max(0, round((current["started"] - previous["ended"]) * 1000))
                for previous, current in zip(calls, calls[1:])
            )
            after_ms = max(0, round((ended - calls[-1]["ended"]) * 1000))
        else:
            before_ms = max(0, round((ended - self.entered) * 1000))
            between_ms = 0
            after_ms = 0
        projections = [item["projection"] for item in calls]
        public_calls = [{key: value for key, value in item.items() if key not in {"started", "ended"}} for item in calls]
        return {
            "schema": SCHEMA,
            "total_ms": max(0, round((ended - self.started) * 1000)),
            "v6_internal_ms": max(0, round((ended - self.entered) * 1000)),
            "phases": {
                "ingress_to_v6_ms": max(0, round((self.entered - self.started) * 1000)),
                "host_before_first_provider_ms": before_ms,
                "provider_ms": provider_ms,
                "host_between_providers_ms": between_ms,
                "host_after_last_provider_ms": after_ms,
            },
            "checkpoint": {"count": self.checkpoint_count, "duration_ms": self.checkpoint_ms},
            "projection": {
                "calls": len(projections),
                "body_bytes": sum(item["body_bytes"] for item in projections),
                "messages_bytes": sum(item["messages_bytes"] for item in projections),
                "tools_bytes": sum(item["tools_bytes"] for item in projections),
                "message_content_bytes": sum(item["message_content_bytes"] for item in projections),
            },
            "provider_calls": public_calls,
        }
