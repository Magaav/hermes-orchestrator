#!/usr/bin/env python3
"""Wire-contract tests for the Visão Studio worker."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import studio_worker  # pylint: disable=wrong-import-position


class StudioWorkerWireTest(unittest.TestCase):
    def test_success_image_is_split_into_bounded_frames_without_metadata_duplication(self) -> None:
        frames: list[tuple[str, dict[str, object]]] = []
        encoded = "a" * (studio_worker.IMAGE_CHUNK_CHARS * 2 + 7)
        result = {
            "ok": True,
            "image_base64": encoded,
            "media_type": "image/png",
            "proof": {"trace_id": "trace-1"},
        }

        studio_worker.emit_result(result, lambda event, detail: frames.append((event, detail)), wire_version=2)

        self.assertEqual(frames[0][0], "result-start")
        self.assertNotIn("image_base64", frames[0][1]["result"])
        chunks = [frame[1]["data"] for frame in frames if frame[0] == "result-chunk"]
        self.assertEqual("".join(chunks), encoded)
        self.assertTrue(all(len(chunk) <= studio_worker.IMAGE_CHUNK_CHARS for chunk in chunks))
        self.assertEqual(frames[-1], ("complete", {"chunks": 3}))

    def test_legacy_open_tabs_receive_the_original_completion_shape(self) -> None:
        frames: list[tuple[str, dict[str, object]]] = []
        result = {"ok": True, "image_base64": "legacy-image", "media_type": "image/png"}

        studio_worker.emit_result(result, lambda event, detail: frames.append((event, detail)))

        self.assertEqual(frames, [("complete", {"result": result})])


if __name__ == "__main__":
    unittest.main()
