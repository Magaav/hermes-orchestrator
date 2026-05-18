#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN_ROOT / "server" / "static_server.py"

spec = importlib.util.spec_from_file_location("wasm_agent_static_server", SERVER_PATH)
assert spec and spec.loader
server_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_mod)


class FakePopen:
    instances: list["FakePopen"] = []

    def __init__(self, command: list[str], **_kwargs: object) -> None:
        self.command = command
        self.pid = 4242 + len(self.instances)
        self.returncode = None
        self.terminated = False
        self.instances.append(self)

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0

    def kill(self) -> None:
        self.returncode = -9


def fake_server(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        plugin_root=PLUGIN_ROOT,
        public_root=PLUGIN_ROOT / "public",
        state_dir=root / "state",
        bridge_url="http://127.0.0.1:8790",
        browser_timeout_sec=1.0,
        camera_push_processes={},
        camera_push_processes_lock=threading.Lock(),
    )


class CameraPushIngestTest(unittest.TestCase):
    def test_push_listener_ports_use_stable_channel_offsets(self) -> None:
        self.assertEqual(server_mod.camera_push_port("cam-1"), 1935)
        self.assertEqual(server_mod.camera_push_port("cam-2"), 1936)
        self.assertEqual(server_mod.camera_push_port("front-door"), 1935)
        self.assertEqual(server_mod.camera_push_port("cam-1", {"port": "20554"}), 20554)

    def test_ffmpeg_listener_command_writes_latest_jpeg(self) -> None:
        command = server_mod.camera_push_ffmpeg_command(
            "rtmp://0.0.0.0:1935/live/cam-1-key",
            Path("/tmp/latest.jpg"),
            fps=2,
            quality=5,
        )
        self.assertIn("-listen", command)
        self.assertIn("rtmp://0.0.0.0:1935/live/cam-1-key", command)
        self.assertIn("-update", command)
        self.assertEqual(command[-1], "/tmp/latest.jpg")
        high_fps_command = server_mod.camera_push_ffmpeg_command(
            "rtmp://0.0.0.0:1935/live/cam-1-key",
            Path("/tmp/latest.jpg"),
            fps=30,
            quality=5,
        )
        self.assertIn("fps=15", high_fps_command)

    def test_begin_push_ingest_returns_dvr_stream_url_and_frame_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            server = fake_server(Path(tempdir))
            FakePopen.instances = []
            with patch.object(server_mod.subprocess, "Popen", FakePopen):
                result = server_mod.start_camera_push_ingest(
                    server,
                    {"stream_id": "cam-1", "publicHost": "wa.example.test", "fps": 2},
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["schema"], server_mod.CAMERA_PUSH_SCHEMA)
            self.assertEqual(result["state"], "listening")
            self.assertEqual(result["stream_id"], "cam-1")
            self.assertTrue(result["ingest"]["url"].startswith("rtmp://wa.example.test:1935/live/cam-1-"))
            self.assertEqual(result["frame"]["url"], "/camera/push-frame?stream_id=cam-1")
            self.assertEqual(result["stream"]["url"], "/camera/push-stream?stream_id=cam-1")
            self.assertEqual(result["replay"]["url"], "/camera/push-replay?stream_id=cam-1&seconds=300")
            self.assertEqual(len(FakePopen.instances), 1)
            self.assertIn("-listen", FakePopen.instances[0].command)

    def test_begin_push_ingest_restarts_when_fps_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            server = fake_server(Path(tempdir))
            FakePopen.instances = []
            with patch.object(server_mod.subprocess, "Popen", FakePopen):
                server_mod.start_camera_push_ingest(server, {"stream_id": "cam-1", "fps": 10})
                server_mod.start_camera_push_ingest(server, {"stream_id": "cam-1", "fps": 15})
            self.assertEqual(len(FakePopen.instances), 2)
            self.assertTrue(FakePopen.instances[0].terminated)
            self.assertIn("fps=15", FakePopen.instances[1].command)

    def test_push_archive_keeps_recent_frames_for_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            server = fake_server(Path(tempdir))
            frame_path = server_mod.camera_push_latest_frame_path(server, "cam-1")
            frame_path.write_bytes(b"\xff\xd8frame\xff\xd9")
            now = time.time()
            os_time = (now, now)
            os.utime(frame_path, os_time)
            archive_path = server_mod.camera_push_archive_latest_frame(server, "cam-1", frame_path)
            self.assertIsNotNone(archive_path)
            self.assertTrue(archive_path.exists())
            recent = server_mod.camera_push_recent_archive_frames(server, "cam-1", 300)
            self.assertEqual(recent, [archive_path])

    def test_push_frame_playback_archive_can_sample_fluid_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            server = fake_server(Path(tempdir))
            frame_path = server_mod.camera_push_latest_frame_path(server, "cam-1")
            frame_path.write_bytes(b"\xff\xd8frame1\xff\xd9")
            first_time = time.time()
            os.utime(frame_path, (first_time, first_time))
            first = server_mod.camera_push_playback_latest_frame(
                server,
                "cam-1",
                frame_path,
                min_interval_sec=server_mod.DEFAULT_CAMERA_PUSH_PLAYBACK_SAMPLE_SEC,
            )
            self.assertIsNotNone(first)
            self.assertAlmostEqual(first.stat().st_mtime, first_time, places=3)
            frame_path.write_bytes(b"\xff\xd8frame2\xff\xd9")
            second_time = first_time + server_mod.DEFAULT_CAMERA_PUSH_PLAYBACK_SAMPLE_SEC + 0.1
            os.utime(frame_path, (second_time, second_time))
            second = server_mod.camera_push_playback_latest_frame(
                server,
                "cam-1",
                frame_path,
                min_interval_sec=server_mod.DEFAULT_CAMERA_PUSH_PLAYBACK_SAMPLE_SEC,
            )
            self.assertIsNotNone(second)
            self.assertNotEqual(first, second)
            self.assertAlmostEqual(second.stat().st_mtime, second_time, places=3)
            frame_path.write_bytes(b"\xff\xd8partial")
            partial_time = second_time + server_mod.DEFAULT_CAMERA_PUSH_PLAYBACK_SAMPLE_SEC + 0.1
            os.utime(frame_path, (partial_time, partial_time))
            reused = server_mod.camera_push_playback_latest_frame(
                server,
                "cam-1",
                frame_path,
                min_interval_sec=server_mod.DEFAULT_CAMERA_PUSH_PLAYBACK_SAMPLE_SEC,
            )
            self.assertEqual(reused, second)
            playback_frames = server_mod.camera_push_playback_frames_from(server, "cam-1", int(first_time * 1000), 30)
            self.assertEqual(playback_frames, [first, second])
            near_first = server_mod.camera_push_nearest_playback_frame(
                server,
                "cam-1",
                target_ms=int((first_time + 0.02) * 1000),
            )
            self.assertIsNotNone(near_first)
            self.assertEqual(near_first[0], first)
            near_second = server_mod.camera_push_nearest_playback_frame(
                server,
                "cam-1",
                target_ms=int((second_time - 0.02) * 1000),
            )
            self.assertIsNotNone(near_second)
            self.assertEqual(near_second[0], second)
            too_far = server_mod.camera_push_nearest_playback_frame(
                server,
                "cam-1",
                target_ms=int((second_time + 10) * 1000),
                max_distance_ms=1000,
            )
            self.assertIsNone(too_far)

    def test_push_timeline_lists_today_archive_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            server = fake_server(Path(tempdir))
            now = time.time()
            archive_dir = server_mod.camera_push_archive_dir(server, "cam-1")
            old_path = archive_dir / "1000000000-8.jpg"
            new_path = archive_dir / "2000000000-8.jpg"
            old_path.write_bytes(b"\xff\xd8old\xff\xd9")
            new_path.write_bytes(b"\xff\xd8new\xff\xd9")
            os.utime(old_path, (now - 900, now - 900))
            os.utime(new_path, (now, now))
            timeline = server_mod.camera_push_timeline(server, "cam-1", mode="live", seconds=600)
            self.assertTrue(timeline["ok"])
            self.assertEqual(timeline["stream_id"], "cam-1")
            self.assertEqual(timeline["mode"], "live")
            self.assertEqual(len(timeline["frames"]), 1)
            frame = timeline["frames"][0]
            self.assertEqual(frame["id"], new_path.name)
            self.assertIn("/camera/push-archive-frame?stream_id=cam-1", frame["url"])
            recorded = server_mod.camera_push_timeline(server, "cam-1", mode="recorded")
            self.assertEqual(recorded["mode"], "recorded")
            self.assertEqual(len(recorded["frames"]), 2)
            self.assertEqual(recorded["available_range"]["frame_count"], 2)
            self.assertGreater(recorded["available_range"]["duration_sec"], 0)

    def test_live_timeline_range_uses_fresh_latest_frame_time(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            server = fake_server(Path(tempdir))
            now = time.time()
            archive_dir = server_mod.camera_push_archive_dir(server, "cam-1")
            sampled_path = archive_dir / "1000000000-8.jpg"
            sampled_path.write_bytes(b"\xff\xd8sampled\xff\xd9")
            os.utime(sampled_path, (now - 10, now - 10))
            latest_path = server_mod.camera_push_latest_frame_path(server, "cam-1")
            latest_path.write_bytes(b"\xff\xd8latest\xff\xd9")
            os.utime(latest_path, (now, now))
            timeline = server_mod.camera_push_timeline(server, "cam-1", mode="live", seconds=600)
            self.assertEqual(len(timeline["frames"]), 1)
            self.assertEqual(timeline["frames"][0]["id"], sampled_path.name)
            self.assertGreater(timeline["range"]["end_ms"], timeline["frames"][0]["timestamp_ms"])
            self.assertAlmostEqual(timeline["range"]["end_ms"], int(now * 1000), delta=50)

    def test_stop_push_ingest_terminates_running_listener(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            server = fake_server(Path(tempdir))
            FakePopen.instances = []
            with patch.object(server_mod.subprocess, "Popen", FakePopen):
                server_mod.start_camera_push_ingest(server, {"stream_id": "cam-1", "publicHost": "wa.example.test"})
                result = server_mod.stop_camera_push_ingest(server, {"stream_id": "cam-1"})
            self.assertTrue(FakePopen.instances[0].terminated)
            self.assertEqual(result["state"], "stopped")


if __name__ == "__main__":
    unittest.main()
