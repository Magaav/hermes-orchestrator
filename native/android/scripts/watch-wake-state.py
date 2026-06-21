#!/usr/bin/env python3
import argparse
import json
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CONTROL_ROOT = ROOT / "plugins" / "wasm-agent" / "state" / "native-control"


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def newest(paths):
    items = [path for path in paths if path.exists()]
    return max(items, key=lambda path: path.stat().st_mtime) if items else None


def latest_device_id(explicit: str = "") -> str:
    if explicit:
        return explicit
    heartbeat = newest((CONTROL_ROOT / "heartbeats").glob("android-*.json"))
    if not heartbeat:
        return ""
    data = read_json(heartbeat)
    return str(data.get("device_id") or heartbeat.stem)


def latest_result(device_id: str) -> dict:
    result_dir = CONTROL_ROOT / "results" / device_id
    result_path = newest(result_dir.glob("*.json"))
    return read_json(result_path) if result_path else {}


def nested_state(result: dict) -> tuple[dict, dict]:
    state = result.get("state")
    if not isinstance(state, dict):
        wrapped = result.get("result")
        state = wrapped.get("state") if isinstance(wrapped, dict) else {}
    if not isinstance(state, dict):
        state = {}
    voice = state.get("voice_wake")
    return state, voice if isinstance(voice, dict) else {}


def merged_get(state: dict, voice: dict, key: str, default=""):
    return voice.get(key, state.get(key, default))


def clipped(value, width: int = 24) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ")
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def diagnostics_summary(state: dict, voice: dict) -> str:
    diag = merged_get(state, voice, "last_asr_diagnostics", {})
    if not isinstance(diag, dict):
        return ""
    schema = str(diag.get("schema") or "")
    if "android_speech" in schema:
        return "speech lang={} dev={} err={} rms={} partials={}".format(
            diag.get("language", ""),
            diag.get("device_locale", ""),
            diag.get("error_name") or diag.get("error", ""),
            diag.get("max_rms_db", ""),
            diag.get("partial_count", ""),
        )
    if "vosk" in schema or "local_command_capture" in schema:
        final = diag.get("final_result")
        text = final.get("text", "") if isinstance(final, dict) else diag.get("text", "")
        return "vosk text={} peak={} rms={} samples={}".format(
            clipped(text, 18),
            diag.get("capture_peak", diag.get("peak", "")),
            round(float(diag.get("capture_rms", diag.get("rms", 0.0)) or 0.0), 1),
            diag.get("capture_sample_count", diag.get("sample_count", "")),
        )
    return clipped(json.dumps(diag, sort_keys=True), 80)


def row(device_id: str) -> str:
    result = latest_result(device_id)
    heartbeat = read_json(CONTROL_ROOT / "heartbeats" / f"{device_id}.json")
    state, voice = nested_state(result)
    build = str(merged_get(state, voice, "android_build_id", heartbeat.get("build_id", ""))).replace("android-universal-", "")
    listener = "ready" if merged_get(state, voice, "listener_ready", False) is True or merged_get(state, voice, "wake_service_ready", False) is True else "not-ready"
    audio = "live" if merged_get(state, voice, "audio_record_active", False) is True or merged_get(state, voice, "audio_capture_alive", False) is True else "off"
    inference = "live" if merged_get(state, voice, "inference_running", False) is True else "off"
    wake_count = merged_get(state, voice, "wake_detection_count", 0)
    asr = clipped(merged_get(state, voice, "local_asr_engine", merged_get(state, voice, "last_asr_engine", "")), 34)
    result_text = clipped(merged_get(state, voice, "last_transcript_result", ""), 28)
    status = clipped(merged_get(state, voice, "last_transcript_status", ""), 12)
    diag = diagnostics_summary(state, voice)
    reads = merged_get(state, voice, "audio_record_read_count", merged_get(state, voice, "audio_read_calls", 0))
    inf_count = merged_get(state, voice, "inference_count", 0)
    return "{:<16} {:<9} {:<5} {:<5} reads={:<6} inf={:<6} wake={:<4} {:<34} {:<12} {:<28} {}".format(
        clipped(build, 16),
        listener,
        audio,
        inference,
        reads,
        inf_count,
        wake_count,
        asr,
        status,
        result_text,
        clipped(diag, 100),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Flatten latest Android wake/ASR state.")
    parser.add_argument("--device-id", default="", help="native-control Android device id")
    parser.add_argument("--watch", action="store_true", help="poll continuously")
    parser.add_argument("--interval", type=float, default=2.0, help="watch interval seconds")
    args = parser.parse_args()
    device_id = latest_device_id(args.device_id)
    if not device_id:
        print("No Android native-control heartbeat found.")
        return 2
    header = "build            listener  audio inf   reads      infer      wake asr                                status       result                       diagnostics"
    if args.watch:
        print(header)
        while True:
            print(row(device_id), flush=True)
            time.sleep(max(0.25, args.interval))
    print(header)
    print(row(device_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
