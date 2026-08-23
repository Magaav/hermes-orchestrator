#!/usr/bin/env python3
"""Prove native-control reachability from the authoritative production registry."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV = ROOT / "plugins/wasm-agent/conf/wa.env"
DEFAULT_REPORT = ROOT / "reports/context/latest/production-native-control-authority.json"
LOCAL_HEARTBEATS = ROOT / "plugins/wasm-agent/state/native-control/heartbeats"


def control_key(path: Path) -> str:
    prefix = "WASM_AGENT_NATIVE_CONTROL_KEY="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(prefix):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def compact_client(client: dict) -> dict:
    return {
        "deviceId": client.get("device_id"),
        "runtimeType": client.get("runtime_type") or "unknown",
        "buildId": client.get("build_id") or "",
        "route": client.get("route") or "",
        "ageSec": client.get("age_sec"),
        "transport": client.get("transport") or "",
        "capabilities": client.get("capabilities") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="https://wa.colmeio.com")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    key = control_key(args.env_file)
    if not key:
        result = {"status": "blocked", "promiseId": "production-native-control-authority", "failureClass": "control_key_missing"}
    else:
        request = urllib.request.Request(
            f"{args.origin.rstrip('/')}/native/control/clients",
            headers={"Accept": "application/json", "X-Wasm-Agent-Native-Control-Key": key},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.load(response)
            live = [client for client in payload.get("clients", []) if client.get("live")]
            live_electron = [client for client in live if client.get("runtime_type") == "electron"]
            compact = [compact_client(client) for client in live]
            compact_electron = [client for client in compact if client["runtimeType"] == "electron"]
            runtime_counts = {
                runtime: sum(client["runtimeType"] == runtime for client in compact)
                for runtime in sorted({client["runtimeType"] for client in compact})
            }
            local_files = list(LOCAL_HEARTBEATS.glob("*.json")) if LOCAL_HEARTBEATS.exists() else []
            local_mtime = max((item.stat().st_mtime for item in local_files), default=0)
            local_age = max(0, int(datetime.now(timezone.utc).timestamp() - local_mtime)) if local_mtime else None
            passed = bool(live_electron) and all(isinstance(item.get("age_sec"), (int, float)) and item["age_sec"] <= 90 for item in live_electron)
            result = {
                "status": "pass" if passed else "fail",
                "promiseId": "production-native-control-authority",
                "claim": "Production native-control authority is queried before local mirrors",
                "authority": "authenticated-production-api",
                "origin": args.origin,
                "liveClients": compact,
                "runtimeCounts": runtime_counts,
                "liveElectronClients": compact_electron,
                "localMirror": {
                    "authority": "non-authoritative",
                    "newestHeartbeatAt": iso_from_timestamp(local_mtime) if local_mtime else "",
                    "ageSec": local_age,
                    "stale": local_age is None or local_age > 90,
                },
                "summary": f"{len(live)} live production client(s) across {runtime_counts}; local mirror age={local_age}s",
                "failureClass": None if passed else "production_electron_client_not_live",
                "nextSuggestedSteps": [] if passed else ["Restore production polling before queueing restart or install commands."],
            }
        except Exception as error:
            result = {
                "status": "blocked",
                "promiseId": "production-native-control-authority",
                "authority": "authenticated-production-api",
                "failureClass": "production_client_registry_unreachable",
                "summary": str(error),
                "nextSuggestedSteps": ["Restore the control credential or production client-registry endpoint."],
            }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result.get("status") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
