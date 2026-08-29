#!/usr/bin/env python3
"""Wait for an installed Windows client to reconnect on one expected build."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/windows"))

from hot_shell_common import DEFAULT_ORIGIN, request_json, write_json  # noqa: E402

DEFAULT_REPORT = ROOT / "reports/windows/latest/windows-update-reconnect.json"
PRODUCTION_ROUTES = frozenset({
    "https://wa.colmeio.com/home?native=electron",
    "https://wa.colmeio.com/home?native=electron&companion=overlay",
})
PRODUCTION_ROUTE = min(PRODUCTION_ROUTES)


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compact_client(client: dict[str, Any]) -> dict[str, Any]:
    heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
    return {
        "deviceId": str(client.get("device_id") or heartbeat.get("device_id") or ""),
        "runtimeType": str(client.get("runtime_type") or heartbeat.get("runtimeType") or ""),
        "buildId": str(client.get("build_id") or heartbeat.get("buildId") or heartbeat.get("build_id") or ""),
        "route": str(client.get("route") or heartbeat.get("route") or ""),
        "ageSec": client.get("age_sec"),
        "transport": str(client.get("transport") or ""),
        "live": client.get("live") is True,
    }


def select_client(payload: dict[str, Any], device_id: str) -> dict[str, Any]:
    clients = payload.get("clients") if isinstance(payload.get("clients"), list) else []
    compact = [compact_client(item) for item in clients if isinstance(item, dict)]
    if device_id:
        return next((item for item in compact if item["deviceId"] == device_id), {})
    live_windows = [
        item for item in compact
        if item["live"] and item["runtimeType"] == "electron" and item["deviceId"].startswith("win-")
    ]
    return min(live_windows, key=lambda item: item["ageSec"] if isinstance(item["ageSec"], (int, float)) else float("inf"), default={})


def valid_expected_client(client: dict[str, Any], expected_build: str, max_age_sec: int) -> bool:
    age = client.get("ageSec")
    return bool(
        client.get("live")
        and client.get("runtimeType") == "electron"
        and client.get("buildId") == expected_build
        and client.get("route") in PRODUCTION_ROUTES
        and isinstance(age, (int, float))
        and 0 <= age <= max_age_sec
    )


def watch_reconnect(
    fetch: Callable[[], dict[str, Any]],
    *,
    expected_build: str,
    device_id: str = "",
    timeout_sec: float = 180,
    poll_sec: float = 2,
    max_age_sec: int = 30,
    require_transition: bool = False,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    started_at = iso_now()
    deadline = monotonic() + timeout_sec
    samples = 0
    initial_build = ""
    saw_absent_or_other_build = False
    last_client: dict[str, Any] = {}
    errors: list[str] = []

    while True:
        samples += 1
        try:
            last_client = select_client(fetch(), device_id)
            observed_build = str(last_client.get("buildId") or "")
            if samples == 1:
                initial_build = observed_build
            if not last_client or observed_build != expected_build or not last_client.get("live"):
                saw_absent_or_other_build = True
            transition_ok = not require_transition or saw_absent_or_other_build
            if valid_expected_client(last_client, expected_build, max_age_sec) and transition_ok:
                return {
                    "status": "pass",
                    "promiseId": "windows-installed-update-reconnect",
                    "startedAt": started_at,
                    "finishedAt": iso_now(),
                    "expectedBuildId": expected_build,
                    "initialBuildId": initial_build,
                    "transitionObserved": saw_absent_or_other_build,
                    "requireTransition": require_transition,
                    "samples": samples,
                    "client": last_client,
                    "failureClass": None,
                    "summary": f"Installed Windows client {last_client['deviceId']} is live on expected build {expected_build}.",
                }
        except Exception as exc:
            errors = [f"{type(exc).__name__}: {exc}"[:240]]

        if monotonic() >= deadline:
            failure = "update_transition_not_observed" if require_transition and not saw_absent_or_other_build else "expected_build_not_live"
            return {
                "status": "fail",
                "promiseId": "windows-installed-update-reconnect",
                "startedAt": started_at,
                "finishedAt": iso_now(),
                "expectedBuildId": expected_build,
                "initialBuildId": initial_build,
                "transitionObserved": saw_absent_or_other_build,
                "requireTransition": require_transition,
                "samples": samples,
                "client": last_client,
                "errors": errors,
                "failureClass": failure,
                "summary": f"Expected Windows build {expected_build} did not produce an acceptable production reconnect before timeout.",
            }
        sleep(poll_sec)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-build", required=True)
    parser.add_argument("--device-id", default="")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--poll-sec", type=float, default=2)
    parser.add_argument("--max-age-sec", type=int, default=30)
    parser.add_argument("--require-transition", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    result = watch_reconnect(
        lambda: request_json("GET", f"{args.origin.rstrip('/')}/native/control/clients", timeout=10),
        expected_build=args.expected_build,
        device_id=args.device_id,
        timeout_sec=args.timeout_sec,
        poll_sec=args.poll_sec,
        max_age_sec=args.max_age_sec,
        require_transition=args.require_transition,
    )
    result["authority"] = "authenticated-production-api"
    result["origin"] = args.origin
    write_json(args.report, result)
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
