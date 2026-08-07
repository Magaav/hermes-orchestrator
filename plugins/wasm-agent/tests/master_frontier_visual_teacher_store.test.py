import sys
import tempfile
import unittest
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_ROOT))

from master_frontier.visual_teacher_store import VisualTeacherError, VisualTeacherStore  # noqa: E402


PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"
JPEG = b"\xff\xd8\xff" + b"teacher"


def contract():
    return {
        "objective": "Remove portable clutter while preserving the photographed property.",
        "remove_labels": ["bag", "watermark logo"],
        "preserve_rules": ["camera viewpoint", "architecture", "permanent fixtures"],
        "reject_rules": ["residual objects", "invented structures", "broken geometry"],
        "mask_semantics": "transparent pixels may change; opaque pixels must remain",
    }


def provenance():
    return {
        "teacher": "codex-image-teacher",
        "session_id": "session-1",
        "operator": "user-approved",
        "created_at": "2026-07-27T18:30:00Z",
    }


class VisualTeacherStoreTest(unittest.TestCase):
    def test_registers_content_addressed_immutable_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            store = VisualTeacherStore(directory)
            first = store.register_candidate(
                source=PNG, mask=PNG + b"mask", teacher_output=JPEG,
                contract=contract(), provenance=provenance(),
            )
            second = store.register_candidate(
                source=PNG, mask=PNG + b"mask", teacher_output=JPEG,
                contract=contract(), provenance=provenance(),
            )
            self.assertEqual(first, second)
            self.assertEqual(first["status"], "pending_approval")
            self.assertEqual(len(list((Path(directory) / "blobs").glob("*/*"))), 3)
            self.assertEqual(store.summary()["pending"], 1)

    def test_approval_binds_manifest_and_partition_once(self):
        with tempfile.TemporaryDirectory() as directory:
            store = VisualTeacherStore(directory)
            candidate = store.register_candidate(
                source=PNG, mask=PNG + b"mask", teacher_output=JPEG,
                contract=contract(), provenance=provenance(),
            )
            approved = store.approve(
                candidate["pair_id"], partition="gold", approver="owner",
                approved_at="2026-07-27T18:31:00Z",
                expected_manifest_sha256=candidate["manifest_sha256"],
            )
            self.assertFalse(approved["already_approved"])
            repeated = store.approve(
                candidate["pair_id"], partition="gold", approver="owner",
                approved_at="2026-07-27T18:31:00Z",
                expected_manifest_sha256=candidate["manifest_sha256"],
            )
            self.assertTrue(repeated["already_approved"])
            with self.assertRaisesRegex(VisualTeacherError, "cannot change partition"):
                store.approve(
                    candidate["pair_id"], partition="training", approver="owner",
                    approved_at="2026-07-27T18:32:00Z",
                    expected_manifest_sha256=candidate["manifest_sha256"],
                )
            self.assertEqual(store.summary()["gold"], 1)
            self.assertEqual(store.summary()["pending"], 0)

    def test_holdout_is_private_and_summary_withholds_details(self):
        with tempfile.TemporaryDirectory() as directory:
            store = VisualTeacherStore(directory)
            candidate = store.register_candidate(
                source=PNG, mask=PNG + b"mask", teacher_output=JPEG,
                contract=contract(), provenance=provenance(),
            )
            store.approve(
                candidate["pair_id"], partition="holdout", approver="owner",
                approved_at="2026-07-27T18:33:00Z",
                expected_manifest_sha256=candidate["manifest_sha256"],
            )
            self.assertFalse((Path(directory) / "approved/holdout").exists())
            self.assertTrue((Path(directory) / "private/holdout" / f"{candidate['pair_id']}.json").exists())
            self.assertEqual(store.summary()["holdout_detail"], "withheld")

    def test_rejects_inline_binary_metadata_and_stale_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            store = VisualTeacherStore(directory)
            bad = contract()
            bad["objective"] = "data:image/png;base64,abc"
            with self.assertRaisesRegex(VisualTeacherError, "inline image data"):
                store.register_candidate(
                    source=PNG, mask=PNG + b"mask", teacher_output=JPEG,
                    contract=bad, provenance=provenance(),
                )
            candidate = store.register_candidate(
                source=PNG, mask=PNG + b"mask", teacher_output=JPEG,
                contract=contract(), provenance=provenance(),
            )
            with self.assertRaisesRegex(VisualTeacherError, "does not match"):
                store.approve(
                    candidate["pair_id"], partition="training", approver="owner",
                    approved_at="2026-07-27T18:34:00Z",
                    expected_manifest_sha256="0" * 64,
                )


if __name__ == "__main__":
    unittest.main()
