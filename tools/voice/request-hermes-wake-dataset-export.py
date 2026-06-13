#!/usr/bin/env python3
"""Queue the Win11 bridge Hermes Wake dataset export and fetch the uploaded zip."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_ORIGIN = "https://wa.colmeio.com"
DEFAULT_OUT = "/tmp/hermes-dataset.zip"
DEFAULT_ENV_FILES = (
    "/local/plugins/wasm-agent/conf/wa.env",
    "/local/conf/wa.env",
)
DEFAULT_STATE_DIR = "/local/plugins/wasm-agent/state"


def read_env_file(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    candidate = Path(path)
    if not candidate.exists():
        return env
    for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def default_env_values(paths: tuple[str, ...] = DEFAULT_ENV_FILES) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in paths:
        values.update(read_env_file(path))
    return values


def request_json(method: str, url: str, *, key: str = "", body: dict | None = None, timeout: int = 30) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if key:
        headers["X-Wasm-Agent-Native-Control-Key"] = key
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise SystemExit(f"{method} {url} failed: HTTP {error.code}: {detail}") from error
    return json.loads(raw.decode("utf-8"))


def download(url: str, out: Path, *, key: str = "", timeout: int = 120) -> None:
    headers = {}
    if key:
        headers["X-Wasm-Agent-Native-Control-Key"] = key
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise SystemExit(f"GET {url} failed: HTTP {error.code}: {detail}") from error
    if not data.startswith(b"PK\x03\x04"):
        raise SystemExit(f"Downloaded dataset is not a zip archive: {url}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)


def is_local_origin(origin: str) -> bool:
    return origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost")


def read_json_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def local_state_dir(env: dict[str, str]) -> Path:
    return Path(env.get("HERMES_WASM_AGENT_STATE_DIR") or DEFAULT_STATE_DIR)


def local_command_result(state_dir: Path, device_id: str, command_id: str) -> dict:
    path = state_dir / "native-control" / "results" / device_id / f"{command_id}.json"
    return read_json_file(path)


def latest_local_dataset_archive(state_dir: Path) -> tuple[Path | None, dict]:
    latest = read_json_file(state_dir / "native-diagnostics" / "latest-android-hermes-wake-dataset.json")
    archive_path = Path(str(latest.get("archivePath") or latest.get("archive_path") or ""))
    root = state_dir / "native-diagnostics" / "android-hermes-wake-datasets"
    if archive_path.is_file():
        return archive_path, latest
    candidates = sorted(root.glob("*/hermes-dataset-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0], latest
    return None, latest


def copy_local_dataset(state_dir: Path, out: Path) -> dict | None:
    archive, latest = latest_local_dataset_archive(state_dir)
    if not archive or not archive.is_file() or archive.stat().st_size <= 0:
        return None
    data = archive.read_bytes()
    if not data.startswith(b"PK\x03\x04"):
        raise SystemExit(f"Local dataset is not a zip archive: {archive}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return {
        "ok": True,
        "sourcePath": str(archive),
        "sizeBytes": len(data),
        "record": latest,
    }


def choose_device(clients: dict, explicit: str = "") -> str:
    if explicit:
        return explicit
    candidates = []
    for client in clients.get("clients", []):
        heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
        runtime = str(heartbeat.get("runtime") or heartbeat.get("native_runtime") or "").lower()
        route = str(heartbeat.get("route") or "")
        device_id = str(client.get("device_id") or heartbeat.get("device_id") or "")
        if not device_id:
            continue
        score = 0
        if "electron" in runtime or "native=electron" in route:
            score += 10
        if "win" in device_id.lower() or "windows" in route.lower():
            score += 3
        candidates.append((score, device_id, client))
    if not candidates:
        raise SystemExit("No native bridge clients are currently polling. Start the installed Win11 wasm-agent app.")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default=os.getenv("WASM_AGENT_ORIGIN", DEFAULT_ORIGIN))
    parser.add_argument("--control-key", default=os.getenv("WASM_AGENT_NATIVE_CONTROL_KEY", ""))
    parser.add_argument("--env-file", default=os.getenv("WASM_AGENT_ENV_FILE", ""))
    parser.add_argument("--device-id", default=os.getenv("WASM_AGENT_NATIVE_DEVICE_ID", ""))
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--wait-sec", type=int, default=180)
    parser.add_argument("--poll-sec", type=float, default=5.0)
    parser.add_argument("--no-queue", action="store_true", help="Only download the latest uploaded dataset.")
    args = parser.parse_args()

    env_file_values = read_env_file(args.env_file) if args.env_file else default_env_values()
    origin = (args.origin or env_file_values.get("WASM_AGENT_PROD_ORIGIN") or DEFAULT_ORIGIN).rstrip("/")
    out = Path(args.out)
    key = args.control_key or env_file_values.get("WASM_AGENT_NATIVE_CONTROL_KEY", "")
    local_origin = is_local_origin(origin)
    state_dir = local_state_dir(env_file_values)
    if not key and not local_origin:
        raise SystemExit("Set WASM_AGENT_NATIVE_CONTROL_KEY or pass --control-key for cloud dataset export automation.")

    command_ids: list[tuple[str, str]] = []
    if not args.no_queue:
        clients = request_json("GET", f"{origin}/native/control/clients", key=key)
        device_id = choose_device(clients, args.device_id)
        queued = request_json(
            "POST",
            f"{origin}/native/frontier/command",
            key=key,
            body={
                "command": "export_hermes_wake_dataset",
                "device_id": device_id,
                "reason": "ship Hermes Wake: automate Win11 bridge dataset export",
                "payload": {
                    "sourcePath": "files/voice/exports/hermes-dataset.zip",
                    "uploadTimeoutMs": 120000,
                },
            },
        )
        for item in queued.get("queued", []):
            command_id = str(item.get("id") or "")
            target_id = str(item.get("device_id") or device_id)
            if command_id:
                command_ids.append((target_id, command_id))
        print(json.dumps({"queued": queued, "device_id": device_id}, indent=2))

    deadline = time.monotonic() + max(1, args.wait_sec)
    latest_url = f"{origin}/native/android/hermes-wake-dataset/latest.json"
    zip_url = f"{origin}/native/android/hermes-wake-dataset/latest.zip"
    last_error = ""
    while time.monotonic() < deadline:
        if local_origin:
            copied = copy_local_dataset(state_dir, out)
            if copied:
                print(json.dumps({"ok": True, "dataset": str(out), "latest": copied}, indent=2))
                return 0
            for target_id, command_id in command_ids:
                result = local_command_result(state_dir, target_id, command_id)
                payload = result.get("result") if isinstance(result.get("result"), dict) else {}
                if payload and payload.get("ok") is False:
                    raise SystemExit(
                        "Win11 bridge export failed: "
                        + json.dumps({k: payload.get(k) for k in ("status", "error", "message", "upload")}, sort_keys=True)
                    )
        try:
            latest = request_json("GET", latest_url, key=key, timeout=15)
            if latest.get("ok") and int(latest.get("sizeBytes") or latest.get("bytes") or 0) > 0:
                download(zip_url, out, key=key)
                print(json.dumps({"ok": True, "dataset": str(out), "latest": latest}, indent=2))
                return 0
            last_error = json.dumps(latest)
        except SystemExit as error:
            last_error = str(error)
        time.sleep(max(1.0, args.poll_sec))
    raise SystemExit(f"Timed out waiting for uploaded Hermes dataset. Last error: {last_error}")


if __name__ == "__main__":
    raise SystemExit(main())
