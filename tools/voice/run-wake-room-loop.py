#!/usr/bin/env python3
"""Run one closed-loop wake-word room trial through native control.

The loop is intentionally small:
- choose Windows and Android native clients from /native/control/clients,
- optionally trigger a bounded Windows audio stimulus,
- poll Android wake-word state,
- print a compact proof tuple with before/after counter deltas.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def request_json(method: str, url: str, body: dict[str, Any] | None = None, *, key: str = "", timeout: int = 10) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["X-Wasm-Agent-Native-Control-Key"] = key
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}
        return {"ok": False, "status": error.code, "error": payload}


def native_clients(origin: str, key: str = "") -> list[dict[str, Any]]:
    payload = request_json("GET", f"{origin.rstrip('/')}/native/control/clients", key=key, timeout=8)
    return payload.get("clients") if isinstance(payload.get("clients"), list) else []


def pick_device(clients: list[dict[str, Any]], wanted: str, role: str) -> str:
    if wanted and wanted != "auto":
        return wanted
    for client in clients:
        device_id = str(client.get("device_id") or "")
        heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
        haystack = f"{device_id} {heartbeat.get('runtime', '')} {heartbeat.get('route', '')}".lower()
        if role == "windows" and ("win-" in device_id.lower() or "electron" in haystack):
            return device_id
        if role == "android" and device_id.lower().startswith("android-"):
            return device_id
    return ""


def wake_state(origin: str, key: str = "") -> dict[str, Any]:
    payload = request_json("GET", f"{origin.rstrip('/')}/native/android/wake-word-state", key=key, timeout=8)
    state = payload.get("state") if isinstance(payload.get("state"), dict) else payload
    return state if isinstance(state, dict) else {}


def command_wake_state(record: dict[str, Any]) -> dict[str, Any]:
    result = record.get("result") if isinstance(record.get("result"), dict) else record
    nested = result.get("result") if isinstance(result.get("result"), dict) else {}
    for candidate in (
        nested.get("state"),
        result.get("state"),
        (result.get("queued") if isinstance(result.get("queued"), dict) else {}).get("state"),
        result.get("wake_word_state"),
        result.get("wakeWordState"),
    ):
        if isinstance(candidate, dict):
            return candidate
    return {}


def counters(state: dict[str, Any]) -> dict[str, Any]:
    voice = state.get("voice_wake") if isinstance(state.get("voice_wake"), dict) else state
    wake_confirmation = voice.get("wake_confirmation") if isinstance(voice.get("wake_confirmation"), dict) else {}
    return {
        "build_id": str(voice.get("build_id") or state.get("build_id") or ""),
        "wake_hit_count": int(voice.get("wake_hit_count") or voice.get("wake_detection_count") or 0),
        "has_raw_wake_detection_count": "raw_wake_detection_count" in voice,
        "raw_wake_detection_count": int(voice.get("raw_wake_detection_count") or 0),
        "false_wake_count": int(voice.get("false_wake_count") or 0),
        "inference_count": int(voice.get("inference_count") or 0),
        "last_confidence": float(voice.get("last_confidence") or 0),
        "max_confidence": float(voice.get("max_confidence_since_start") or voice.get("max_observed_confidence") or 0),
        "listener_mode": str(voice.get("listener_mode") or ""),
        "last_transcript": str(voice.get("last_transcript") or voice.get("last_transcript_result") or ""),
        "rejection_reason": str(voice.get("last_rejection_reason") or voice.get("rejection_reason") or ""),
        "has_wake_confirmation": bool(wake_confirmation),
        "wake_confirmation": wake_confirmation,
    }


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def device_matches(event_device_id: str, wanted_device_id: str) -> bool:
    event_device_id = event_device_id.lower()
    wanted_device_id = wanted_device_id.lower()
    return bool(event_device_id) and (
        event_device_id == wanted_device_id
        or wanted_device_id.startswith(f"{event_device_id}-")
        or event_device_id.startswith(wanted_device_id)
    )


def timeline_events_since(state_dir: Path | None, android_device_id: str, since_iso: str) -> list[dict[str, Any]]:
    if state_dir is None:
        return []
    path = state_dir / "native-events" / "voice-command-timeline.jsonl"
    since = parse_iso_timestamp(since_iso)
    if since is None or not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        received_at = parse_iso_timestamp(event.get("received_at"))
        if received_at is None or received_at < since:
            continue
        if android_device_id and not device_matches(str(event.get("device_id") or ""), android_device_id):
            continue
        events.append(event)
    return events


def summarize_timeline(events: list[dict[str, Any]]) -> dict[str, Any]:
    wake_events = [event for event in events if event.get("type") == "wake_detected"]
    command_events = [event for event in events if event.get("type") == "voice_command"]
    routed_commands = [
        event for event in command_events
        if str(event.get("command") or "").strip()
    ]
    usable_transcripts = [
        event for event in command_events
        if str(event.get("normalized_transcript") or event.get("transcript") or "").strip()
    ]
    return {
        "wake_detected_count": len(wake_events),
        "voice_command_count": len(command_events),
        "routed_command_count": len(routed_commands),
        "usable_transcript_count": len(usable_transcripts),
        "latest_wake": wake_events[-1] if wake_events else None,
        "latest_voice_command": command_events[-1] if command_events else None,
        "latest_routed_command": routed_commands[-1] if routed_commands else None,
    }


def native_event_records_since(state_dir: Path | None, android_device_id: str, since_iso: str, kind: str = "") -> list[dict[str, Any]]:
    if state_dir is None:
        return []
    since = parse_iso_timestamp(since_iso)
    if since is None:
        return []
    events_root = state_dir / "native-events"
    candidates = []
    exact = events_root / f"{android_device_id}.json"
    if exact.exists():
        candidates.append(exact)
    for path in events_root.glob("android-*.json"):
        if path not in candidates and device_matches(path.stem, android_device_id):
            candidates.append(path)
    records: list[dict[str, Any]] = []
    for path in candidates:
        try:
            bundle = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        items = bundle.get("events") if isinstance(bundle, dict) else []
        if not isinstance(items, list):
            continue
        for record in items:
            if not isinstance(record, dict):
                continue
            if kind and str(record.get("kind") or "") != kind:
                continue
            received_at = parse_iso_timestamp(record.get("received_at"))
            if received_at is None or received_at < since:
                continue
            if android_device_id and not device_matches(str(record.get("device_id") or ""), android_device_id):
                continue
            records.append(record)
    return records


def summarize_responsiveness(records: list[dict[str, Any]]) -> dict[str, Any]:
    payloads = []
    for record in records:
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        nested = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
        if isinstance(nested, dict):
            payloads.append(nested)
    latest = payloads[-1] if payloads else None
    overloaded = [item for item in payloads if item.get("overloaded") is True]
    return {
        "sample_count": len(payloads),
        "overloaded_count": len(overloaded),
        "latest": latest,
        "latest_overloaded": bool(latest and latest.get("overloaded") is True),
        "latest_overload_reasons": latest.get("overload_reasons", []) if isinstance(latest, dict) else [],
    }


def stimulus_error(stimulus_result: dict[str, Any]) -> str:
    result_probe = stimulus_result.get("result_probe") if isinstance(stimulus_result.get("result_probe"), dict) else {}
    nested = result_probe.get("result") if isinstance(result_probe.get("result"), dict) else {}
    return str(nested.get("error") or result_probe.get("error") or stimulus_result.get("error") or "")


def classify_trial(
    stimulus: str,
    stimulus_result: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    deltas: dict[str, int],
    timeline: dict[str, Any],
) -> str:
    error = stimulus_error(stimulus_result)
    if "unsupported_command" in error:
        return "windows_bridge_update_required"
    if stimulus != "none" and stimulus_result.get("queued") is False:
        return "stimulus_queue_failed"
    if timeline.get("routed_command_count", 0) > 0:
        return "voice_command_routed"
    if timeline.get("usable_transcript_count", 0) > 0:
        return "voice_command_transcribed"
    if timeline.get("wake_detected_count", 0) > 0:
        return "wake_detected_timeline_only"
    if stimulus != "none" and stimulus_result.get("queued") is True:
        return "no_wake_timeline_evidence"
    if not after.get("has_wake_confirmation") or not after.get("has_raw_wake_detection_count"):
        return "android_confirmation_gate_update_required"
    if deltas.get("wake_hit_count", 0) > 0:
        return "wake_confirmed"
    if deltas.get("raw_wake_detection_count", 0) > 0:
        return "raw_rejected"
    return "no_wake_evidence"


def queue_command(origin: str, key: str, device_id: str, command_type: str, payload: dict[str, Any], reason: str) -> dict[str, Any]:
    return request_json("POST", f"{origin.rstrip('/')}/native/control/command", {
        "device_id": device_id,
        "type": command_type,
        "payload": payload,
        "reason": reason,
    }, key=key, timeout=10)


def wait_command_result(origin: str, key: str, command_id: str, timeout_sec: int, state_dir: Path | None = None) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if state_dir is not None:
            for path in (state_dir / "native-control" / "results").glob(f"*/{command_id}.json"):
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception as error:
                    return {"ok": False, "error": str(error), "path": str(path)}
        clients = native_clients(origin, key)
        # The server does not expose a direct result lookup, so use the command
        # proof returned by later state polling when direct lookup is absent.
        for client in clients:
            latest = client.get("latest_event") if isinstance(client.get("latest_event"), dict) else {}
            payload = latest.get("payload") if isinstance(latest.get("payload"), dict) else {}
            if payload.get("command_id") == command_id:
                return {"ok": True, "latest_event": latest}
        time.sleep(0.5)
    return {"ok": False, "error": "result_lookup_timeout", "command_id": command_id}


def refresh_wake_state_via_command(origin: str, key: str, android_device_id: str, state_dir: Path | None, timeout_sec: int = 8) -> dict[str, Any]:
    if not android_device_id:
        return {}
    # Android's fetch operation reads the latest service status file. A duplicate
    # start is the current low-impact way to ask the foreground service to write
    # a fresh status packet before we read it.
    start = queue_command(origin, key, android_device_id, "start_voice_wake", {}, "wake room loop live status write")
    start_command_id = start.get("command_id") or start.get("commandId") or ""
    if start_command_id:
        wait_command_result(origin, key, start_command_id, timeout_sec, state_dir)
        time.sleep(1.2)
    queued = queue_command(origin, key, android_device_id, "refresh_wake_word_state", {}, "wake room loop state refresh")
    command_id = queued.get("command_id") or queued.get("commandId") or ""
    if not command_id:
        return {}
    record = wait_command_result(origin, key, command_id, timeout_sec, state_dir)
    return command_wake_state(record)


def resolved_wake_state(origin: str, key: str, android_device_id: str, state_dir: Path | None, source: str) -> dict[str, Any]:
    if source == "command":
        return refresh_wake_state_via_command(origin, key, android_device_id, state_dir) or wake_state(origin, key)
    endpoint_state = wake_state(origin, key)
    endpoint_counters = counters(endpoint_state)
    if source == "endpoint" or (
        endpoint_counters.get("has_wake_confirmation")
        and endpoint_counters.get("has_raw_wake_detection_count")
    ):
        return endpoint_state
    command_state = refresh_wake_state_via_command(origin, key, android_device_id, state_dir)
    return command_state or endpoint_state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:8877")
    parser.add_argument("--windows-origin", default="")
    parser.add_argument("--android-origin", default="")
    parser.add_argument("--control-key", default=os.getenv("WASM_AGENT_NATIVE_CONTROL_KEY", ""))
    parser.add_argument("--windows-device-id", default="auto")
    parser.add_argument("--android-device-id", default="auto")
    parser.add_argument("--label", default="wake-room-loop")
    parser.add_argument("--stimulus", choices=["none", "speech", "system_sound", "beep", "silence"], default="none")
    parser.add_argument("--phrase", default="alexa")
    parser.add_argument("--observe-sec", type=float, default=12.0)
    parser.add_argument("--settle-sec", type=float, default=0.8)
    parser.add_argument("--volume", type=int, default=80)
    parser.add_argument("--rate", type=int, default=-1)
    parser.add_argument("--state-dir", default="/local/plugins/wasm-agent/state")
    parser.add_argument("--state-source", choices=["auto", "endpoint", "command"], default="auto")
    args = parser.parse_args()

    origin = args.origin.rstrip("/")
    windows_origin = (args.windows_origin or origin).rstrip("/")
    android_origin = (args.android_origin or origin).rstrip("/")
    control_key = args.control_key or ""
    state_dir = Path(args.state_dir) if args.state_dir else None
    windows_device_id = pick_device(native_clients(windows_origin, control_key), args.windows_device_id, "windows")
    android_device_id = pick_device(native_clients(android_origin, control_key), args.android_device_id, "android")
    trial_started_at = iso_now()
    before_state = resolved_wake_state(android_origin, control_key, android_device_id, state_dir, args.state_source)
    before = counters(before_state)

    stimulus_result: dict[str, Any] = {"ok": True, "skipped": args.stimulus == "none"}
    if args.stimulus != "none":
        if not windows_device_id:
            stimulus_result = {"ok": False, "error": "windows_device_missing"}
        else:
            if args.stimulus == "speech":
                command_type = "play_wake_phrase_probe"
                payload = {
                    "phrase": args.phrase,
                    "volume": args.volume,
                    "rate": args.rate,
                    "nativeControlTimeoutSec": 20,
                }
            else:
                command_type = "play_audio_stimulus"
                payload = {
                    "kind": args.stimulus,
                    "label": args.label,
                    "volume": args.volume,
                    "nativeControlTimeoutSec": 20,
                }
            queued = queue_command(windows_origin, control_key, windows_device_id, command_type, payload, f"wake room loop stimulus {args.label}")
            command_id = queued.get("command_id") or queued.get("commandId") or ""
            stimulus_result = {
                "queued": queued.get("ok") is True,
                "command_id": command_id,
                "command_type": command_type,
                "device_id": windows_device_id,
            }
            if command_id:
                stimulus_result["result_probe"] = wait_command_result(windows_origin, control_key, command_id, 25, state_dir)

    time.sleep(max(0.0, args.settle_sec))
    samples: list[dict[str, Any]] = []
    deadline = time.time() + max(0.0, args.observe_sec)
    while time.time() < deadline:
        samples.append(counters(resolved_wake_state(android_origin, control_key, android_device_id, state_dir, args.state_source)))
        time.sleep(0.5)
    after = samples[-1] if samples else counters(wake_state(android_origin, control_key))
    timeline_events = timeline_events_since(state_dir, android_device_id, trial_started_at)
    timeline = summarize_timeline(timeline_events)
    responsiveness = summarize_responsiveness(
        native_event_records_since(state_dir, android_device_id, trial_started_at, "app.responsiveness")
    )
    deltas = {
        key: after.get(key, 0) - before.get(key, 0)
        for key in ("wake_hit_count", "raw_wake_detection_count", "false_wake_count", "inference_count")
        if isinstance(after.get(key), int) and isinstance(before.get(key), int)
    }
    classification = classify_trial(args.stimulus, stimulus_result, before, after, deltas, timeline)
    result = {
        "ok": True,
        "schema": "hermes.wasm_agent.wake_room_loop.v1",
        "label": args.label,
        "stimulus": args.stimulus,
        "phrase": args.phrase if args.stimulus == "speech" else "",
        "windows_origin": windows_origin,
        "android_origin": android_origin,
        "windows_device_id": windows_device_id,
        "android_device_id": android_device_id,
        "stimulus_result": stimulus_result,
        "before": before,
        "after": after,
        "deltas": deltas,
        "trial_started_at": trial_started_at,
        "timeline": timeline,
        "responsiveness": responsiveness,
        "classification": classification,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
