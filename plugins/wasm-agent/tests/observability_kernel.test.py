#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import threading
import urllib.request
import unittest
from pathlib import Path
from types import SimpleNamespace


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN_ROOT / "server" / "static_server.py"

spec = importlib.util.spec_from_file_location("wasm_agent_static_server", SERVER_PATH)
assert spec and spec.loader
server_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_mod)


def fake_server(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        plugin_root=PLUGIN_ROOT,
        public_root=PLUGIN_ROOT / "public",
        state_dir=root / "state",
        bridge_url="http://127.0.0.1:8790",
        browser_timeout_sec=1.0,
    )


def start_test_server(root: Path) -> tuple[server_mod.WasmAgentServer, threading.Thread]:
    def handler(*handler_args: object, **handler_kwargs: object) -> server_mod.WasmAgentHandler:
        return server_mod.WasmAgentHandler(
            *handler_args,
            directory=str(PLUGIN_ROOT / "public"),
            **handler_kwargs,
        )

    httpd = server_mod.WasmAgentServer(
        ("127.0.0.1", 0),
        handler,
        plugin_root=PLUGIN_ROOT,
        public_root=PLUGIN_ROOT / "public",
        state_dir=root / "state",
        bridge_url="http://127.0.0.1:8790",
        browser_timeout_sec=1.0,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


class ObservabilityKernelTest(unittest.TestCase):
    def test_wao_frame_round_trips_tlv_values_and_skips_unknowns(self) -> None:
        frame = server_mod.wao_encode_frame(
            "EVENT",
            {
                "device_id": "android-build-install",
                "stream": "wake",
                "type": "state",
                "ts_ms": 1781880000000,
                "payload_json": {
                    "last_confidence": 0.72,
                    "threshold_crossed": True,
                    "wake_hit_count": 1,
                },
            },
            seq=42,
        )
        decoded = server_mod.wao_decode_frame(frame)
        self.assertEqual(decoded["magic"], "WAO1")
        self.assertEqual(decoded["type"], "EVENT")
        self.assertEqual(decoded["seq"], 42)
        self.assertEqual(decoded["fields"]["device_id"], "android-build-install")
        self.assertEqual(decoded["fields"]["payload_json"]["wake_hit_count"], 1)

        unknown = frame + server_mod.WAO_TLV_HEADER.pack(65000, server_mod.WAO_TLV_UTF8, 0, 3) + b"new"
        decoded_unknown = server_mod.wao_decode_frame(unknown)
        self.assertEqual(decoded_unknown["fields"]["field_65000"], "new")

    def test_observability_hub_uses_sqlite_wal_and_agent_view(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            server = fake_server(Path(tempdir))
            hub = server_mod.ObservabilityHub(server)
            try:
                event = hub.record_event(
                    "android-build-install",
                    "wake",
                    "state",
                    {
                        "status": "listening",
                        "last_confidence": 0.31,
                        "wake_word": "hey jarvis",
                    },
                    latest_key="wake.latest",
                )
                hub.record_command(
                    {
                        "id": "cmd-test",
                        "device_id": "android-build-install",
                        "type": "start_voice_wake",
                        "payload": {"priority": 7},
                    },
                    status="pending",
                )
                query = hub.query_events({"device_id": "android-build-install", "after_seq": 0})
                view = hub.agent_view({"device_id": "android-build-install", "topics": ["wake"], "token_budget": 512})
                self.assertEqual(query["count"], 1)
                self.assertEqual(query["events"][0]["seq"], event["seq"])
                self.assertIn("wake.state", "\n".join(view["l1"]))
                self.assertEqual(view["commands"][0]["command_id"], "cmd-test")
            finally:
                hub.close()

            db_path = server_mod.observability_db_path(server)
            with sqlite3.connect(db_path) as conn:
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(journal_mode.lower(), "wal")
                latest = conn.execute("SELECT key FROM obs_latest WHERE device_id = ?", ("android-build-install",)).fetchall()
                self.assertEqual([row[0] for row in latest], ["wake.latest"])

    def test_agent_view_endpoint_reads_from_hub(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            httpd, thread = start_test_server(Path(tempdir))
            try:
                httpd.observability_hub.record_event("android-test", "wake", "wake_hit", {"wake_word": "hey jarvis"})
                port = httpd.server_address[1]
                body = json.dumps({"device_id": "android-test", "topics": ["wake"], "token_budget": 512}).encode("utf-8")
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/native/obs/agent-view",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertIn("wake.wake_hit", "\n".join(payload["l1"]))
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=3)

    def test_native_control_command_response_exposes_flat_command_id(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            httpd, thread = start_test_server(Path(tempdir))
            try:
                port = httpd.server_address[1]
                body = json.dumps({
                    "device_id": "android-test",
                    "type": "start_voice_wake",
                    "payload": {"reason": "test"},
                }).encode("utf-8")
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/native/control/command",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["command_id"], payload["commandId"])
                self.assertEqual(payload["command_id"], payload["command"]["id"])
                self.assertEqual(payload["device_id"], payload["deviceId"])
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=3)

    def test_wake_diagnosis_accepts_foreground_audio_inference_as_listener_alive(self) -> None:
        state = {
            "wake_service_ready": False,
            "foreground_service_active": True,
            "service_running": True,
            "voice_service_running": True,
            "audio_record_started": True,
            "audio_capture_alive": True,
            "audio_read_calls": 89959,
            "wake_engine_ready": True,
            "inference_count": 89959,
            "wake_hit_count": 0,
            "max_confidence_since_start": 0.12,
            "threshold": 0.99,
        }

        diagnosis = server_mod.android_wake_word_diagnosis(state)

        self.assertTrue(server_mod.android_wake_word_listener_active(state))
        self.assertNotEqual(diagnosis["label"], "listener_not_running")
        self.assertEqual(diagnosis["label"], "wake_threshold_not_crossed")

    def test_wake_diagnosis_classifies_empty_transcript_plan_as_no_transcript(self) -> None:
        diagnosis = server_mod.android_wake_word_diagnosis({
            "foreground_service_active": True,
            "wake_engine_ready": True,
            "wake_hit_count": 1,
            "transcript_gate_last_result": "transcript_plan_empty",
        })

        self.assertEqual(diagnosis["label"], "wake_heard_no_transcript")

    def test_wake_state_merges_newer_native_control_command_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            server = fake_server(Path(tempdir))
            diagnostics_dir = server_mod.native_diagnostics_dir(server)
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            server_mod.write_json_file(diagnostics_dir / "latest.json", {
                "received_at": "2026-06-19T18:59:55Z",
                "payload": {
                    "voice_wake": {
                        "wake_word_schema": "hermes.wasm_agent.android_wake_word_state.v1",
                        "wake_word": "alexa",
                        "wake_threshold": 0.99,
                        "wake_cooldown_ms": 2500,
                        "wake_engine_ready": True,
                        "foreground_service_active": True,
                        "audio_record_started": True,
                        "inference_count": 10,
                        "false_wake_count": 0,
                    },
                },
            })
            command_path = server_mod.native_control_command_path(
                server,
                "android-android-universal-test",
                "cmd-refresh",
            )
            server_mod.write_json_file(command_path, {
                "status": "finished",
                "finished_at": "2026-06-19T19:01:12Z",
                "result": {
                    "ok": True,
                    "state": {
                        "wake_threshold": None,
                        "transcript_engine": "auto",
                        "wake_cooldown_ms": 12000,
                        "inference_count": 42,
                        "false_wake_count": 7,
                    },
                },
            })

            payload = server_mod.latest_native_android_wake_word_state(server)
            state = payload["state"]

            self.assertEqual(state["received_at"], "2026-06-19T19:01:12Z")
            self.assertEqual(state["wake_word"], "alexa")
            self.assertEqual(state["wake_threshold"], 0.99)
            self.assertEqual(state["wake_cooldown_ms"], 12000)
            self.assertEqual(state["transcript_engine"], "auto")
            self.assertEqual(state["inference_count"], 42)
            self.assertEqual(state["false_wake_count"], 7)
            self.assertEqual(state["state_overlay_source"], "native_control_command_result")

    def test_wake_state_ignores_older_command_overlay_after_new_build_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            server = fake_server(Path(tempdir))
            diagnostics_dir = server_mod.native_diagnostics_dir(server)
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            server_mod.write_json_file(diagnostics_dir / "latest.json", {
                "received_at": "2026-06-19T19:17:49Z",
                "build_id": "android-universal-old",
                "payload": {
                    "voice_wake": {
                        "wake_word_schema": "hermes.wasm_agent.android_wake_word_state.v1",
                        "android_build_id": "android-universal-old",
                        "wake_threshold": 0.99,
                        "wake_engine_ready": True,
                        "foreground_service_started": True,
                        "audio_record_started": True,
                        "inference_count": 476,
                        "wake_hit_count": 4,
                        "false_wake_count": 4,
                        "last_error": "unknown_command",
                    },
                },
            })
            server_mod.write_json_file(diagnostics_dir / "android-universal-new-device.json", {
                "received_at": "2026-06-19T19:35:48Z",
                "build_id": "android-universal-new",
                "payload": {
                    "voice_wake": {
                        "schema": "hermes.wasm_agent.android_voice_wake.v1",
                        "android_build_id": "android-universal-new",
                        "wake_threshold": 0.99,
                        "wake_engine_ready": True,
                        "foreground_service_started": True,
                        "audio_record_started": True,
                        "audio_capture_alive": True,
                        "inference_count": 3551,
                        "wake_detection_count": 3,
                        "last_voice_command": "",
                        "last_emitted_voice_event": {
                            "type": "voice_command",
                            "transcript": "can you hear me",
                            "command": "",
                        },
                    },
                },
            })
            command_path = server_mod.native_control_command_path(
                server,
                "android-android-universal-old-device",
                "cmd-old-refresh",
            )
            server_mod.write_json_file(command_path, {
                "status": "finished",
                "finished_at": "2026-06-19T19:17:49Z",
                "result": {
                    "ok": True,
                    "state": {
                        "android_build_id": "android-universal-old",
                        "inference_count": 476,
                        "wake_hit_count": 4,
                        "false_wake_count": 4,
                        "last_error": "unknown_command",
                    },
                },
            })

            state = server_mod.latest_native_android_wake_word_state(server)["state"]

            self.assertEqual(state["received_at"], "2026-06-19T19:35:48Z")
            self.assertEqual(state["android_build_id"], "android-universal-new")
            self.assertEqual(state["inference_count"], 3551)
            self.assertEqual(state["wake_hit_count"], 3)
            self.assertEqual(state["false_wake_count"], 0)
            self.assertEqual(state["last_error"], "")
            self.assertNotIn("state_overlay_source", state)

    def test_wake_state_merges_nested_probe_status_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            server = fake_server(Path(tempdir))
            diagnostics_dir = server_mod.native_diagnostics_dir(server)
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            server_mod.write_json_file(diagnostics_dir / "latest.json", {
                "received_at": "2026-06-19T19:05:37Z",
                "payload": {
                    "voice_wake": {
                        "wake_word_schema": "hermes.wasm_agent.android_wake_word_state.v1",
                        "wake_word": "alexa",
                        "wake_threshold": 0.99,
                        "wake_engine_ready": True,
                        "foreground_service_active": True,
                        "inference_count": 0,
                    },
                },
            })
            command_path = server_mod.native_control_command_path(
                server,
                "android-android-universal-test",
                "cmd-tts-probe",
            )
            server_mod.write_json_file(command_path, {
                "status": "finished",
                "finished_at": "2026-06-19T19:11:30Z",
                "result": {
                    "nativePlayback": {
                        "ok": False,
                        "error": "tts_timeout",
                        "status": {
                            "inference_count": 5,
                            "false_wake_count": 0,
                            "last_confidence": 0.01,
                            "max_observed_confidence": 0.48,
                        },
                    },
                },
            })

            state = server_mod.latest_native_android_wake_word_state(server)["state"]

            self.assertEqual(state["received_at"], "2026-06-19T19:11:30Z")
            self.assertEqual(state["inference_count"], 5)
            self.assertEqual(state["last_confidence"], 0.01)
            self.assertEqual(state["max_confidence_since_start"], 0.48)


if __name__ == "__main__":
    unittest.main()
