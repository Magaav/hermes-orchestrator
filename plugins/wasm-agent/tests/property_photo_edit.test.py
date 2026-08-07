import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_ROOT))

from master_frontier.codex_image_worker import (  # noqa: E402
    image_generation_projection,
    reconstruction_prompt,
    token_usage_projection,
    worker_environment,
)
from property_photo_edit import (  # noqa: E402
    PropertyPhotoEditError,
    _ndjson_frame,
    dispatch_http,
    edit_property_photo,
    prepare_job_workspace,
)


class PropertyPhotoEditTest(unittest.TestCase):
    def test_worker_pins_lowest_supported_reasoning_for_one_photo_turn(self):
        worker_source = (SERVER_ROOT / "master_frontier/codex_image_worker.py").read_text(encoding="utf-8")
        self.assertIn('"effort": "none"', worker_source)

    def test_route_match_is_owned_outside_the_server_monolith(self):
        self.assertFalse(dispatch_http(object(), "/another-route", lambda _name: ""))

    def test_prompt_delegates_once_to_the_reconstruction_skill(self):
        prompt = reconstruction_prompt(watermark_authorized=True)
        self.assertEqual(prompt.count("$property-photo-reconstructor"), 1)
        self.assertIn("explicitly authorized", prompt)
        self.assertLess(len(prompt), 220)

    def test_prompt_preserves_watermark_without_authorization(self):
        prompt = reconstruction_prompt(watermark_authorized=False)
        self.assertIn("preserve all watermarks", prompt)

    def test_minimal_job_workspace_copies_only_the_owned_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner = root / "owner"
            job = root / "job"
            source = owner / ".agents/skills/property-photo-reconstructor/SKILL.md"
            source.parent.mkdir(parents=True)
            source.write_text("minimal skill", encoding="utf-8")
            job.mkdir()
            prepare_job_workspace(job, owner)
            files = [path.relative_to(job).as_posix() for path in job.rglob("*") if path.is_file()]
        self.assertEqual(files, [".agents/skills/property-photo-reconstructor/SKILL.md"])

    def test_production_minimal_workspace_path_is_stable_for_kv_prefix_reuse(self):
        source = (SERVER_ROOT / "property_photo_edit.py").read_text(encoding="utf-8")
        self.assertIn('MINIMAL_WORKSPACE = Path(tempfile.gettempdir()) / "wasm-agent-property-photo-workspace"', source)
        self.assertIn("prepare_job_workspace(MINIMAL_WORKSPACE, owner)", source)

    def test_worker_uses_isolated_sqlite_state_without_replacing_codex_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            environment = worker_environment(state)
        self.assertEqual(environment["CODEX_SQLITE_HOME"], str(state.resolve()))
        self.assertTrue(environment.get("CODEX_HOME"))

    def test_image_event_projection_discards_inline_base64_result(self):
        projected = image_generation_projection(
            {
                "id": "img_1",
                "savedPath": "/tmp/final.png",
                "status": "completed",
                "revisedPrompt": "clean room",
                "result": "base64-data-that-must-not-be-retained",
            }
        )
        self.assertEqual(projected["savedPath"], "/tmp/final.png")
        self.assertNotIn("result", projected)

    def test_token_usage_projection_is_bounded_to_codex_reported_totals(self):
        projected = token_usage_projection(
            {
                "total": {
                    "inputTokens": 120,
                    "cachedInputTokens": 20,
                    "outputTokens": 30,
                    "reasoningOutputTokens": 10,
                    "totalTokens": 150,
                    "futureField": 999,
                },
                "last": {"totalTokens": 25},
            }
        )
        self.assertEqual(projected["totalTokens"], 150)
        self.assertEqual(projected["cachedInputTokens"], 20)
        self.assertNotIn("futureField", projected)

    def test_runs_one_photo_codex_job_without_client_detection_or_persistence(self):
        seen = {}

        def worker(source_path, *, watermark_authorized, cwd):
            seen.update(
                source=source_path.read_bytes(),
                watermark_authorized=watermark_authorized,
                cwd=cwd,
            )
            return b"\x89PNG\r\n\x1a\ncleaned", "image/png", {"thread_id": "thr_test", "item_id": "img_test"}

        with tempfile.TemporaryDirectory() as temporary:
            result = edit_property_photo(
                {
                    "cloud_consent": True,
                    "watermark_authorized": True,
                    "media_type": "image/jpeg",
                    "image_base64": base64.b64encode(b"original").decode(),
                },
                worker=worker,
                workspace=Path(temporary),
            )

        self.assertEqual(result["image_base64"], base64.b64encode(b"\x89PNG\r\n\x1a\ncleaned").decode())
        self.assertEqual(result["model"], "codex-datacenter-imagegen")
        self.assertEqual(result["schema"], "hermes.wasm_agent.property_photo_edit.v4")
        self.assertFalse(result["photo_persisted"])
        self.assertTrue(result["scene_inspected"])
        self.assertTrue(result["watermark_authorized"])
        self.assertEqual(seen["source"], b"original")
        self.assertTrue(seen["watermark_authorized"])

    def test_progress_contract_reports_acceptance_and_worker_transitions(self):
        events = []

        def worker(source_path, *, watermark_authorized, cwd, progress):
            progress("session-started", {"thread_id": "thr_progress"})
            progress("artifact-generated", {"settle_seconds": 90})
            return b"\x89PNG\r\n\x1a\ncleaned", "image/png", {"thread_id": "thr_progress"}

        with tempfile.TemporaryDirectory() as temporary:
            edit_property_photo(
                {
                    "cloud_consent": True,
                    "media_type": "image/jpeg",
                    "image_base64": base64.b64encode(b"original").decode(),
                },
                worker=worker,
                workspace=Path(temporary),
                progress=lambda event, detail: events.append((event, detail)),
            )
        self.assertEqual([event for event, _detail in events], ["accepted", "session-started", "artifact-generated"])
        self.assertEqual(events[0][1]["bytes"], len(b"original"))

    def test_ndjson_progress_frame_is_compact_and_line_delimited(self):
        frame = _ndjson_frame("artifact-generated", {"settle_seconds": 90})
        self.assertTrue(frame.endswith(b"\n"))
        self.assertEqual(
            frame,
            b'{"event":"artifact-generated","detail":{"settle_seconds":90}}\n',
        )
        padded = _ndjson_frame("accepted", {}, min_bytes=4096)
        self.assertGreaterEqual(len(padded), 4096)
        self.assertEqual(json.loads(padded)["event"], "accepted")

    def test_accepts_avif_input_without_persisting_the_photo(self):
        def worker(source_path, *, watermark_authorized, cwd):
            self.assertEqual(source_path.suffix, ".avif")
            return b"\x89PNG\r\n\x1a\ncleaned", "image/png", {"thread_id": "thr_avif"}

        with tempfile.TemporaryDirectory() as temporary:
            result = edit_property_photo(
                {
                    "cloud_consent": True,
                    "media_type": "image/avif",
                    "image_base64": base64.b64encode(b"avif-source").decode(),
                },
                worker=worker,
                workspace=Path(temporary),
            )
        self.assertTrue(result["ok"])
        self.assertFalse(result["photo_persisted"])

    def test_requires_explicit_cloud_consent(self):
        with self.assertRaisesRegex(PropertyPhotoEditError, "Confirm the secure datacenter edit"):
            edit_property_photo(
                {
                    "media_type": "image/jpeg",
                    "image_base64": base64.b64encode(b"original").decode(),
                }
            )

    def test_rejects_empty_photo(self):
        with self.assertRaisesRegex(PropertyPhotoEditError, "property photo is empty"):
            edit_property_photo(
                {
                    "cloud_consent": True,
                    "media_type": "image/jpeg",
                    "image_base64": "",
                }
            )


if __name__ == "__main__":
    unittest.main()
