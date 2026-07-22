#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))
from master_frontier import evidence, repository_reads  # noqa: E402
from master_frontier.v5 import tools as v5_tools  # noqa: E402


class RepositoryReadTests(unittest.TestCase):
    @staticmethod
    def route(root: Path) -> dict:
        return {"workspace_root": str(root), "allowed_read_roots": [str(root)]}

    def test_denies_sensitive_and_outside_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp); (root / ".env").write_text("API_KEY=secret\n"); target = Path(outside) / "x.py"; target.write_text("x\n")
            with self.assertRaises(repository_reads.RepositoryReadError) as sensitive:
                repository_reads.read_lines(self.route(root), ".env")
            self.assertEqual(sensitive.exception.code, "file_read_sensitive")
            with self.assertRaises(repository_reads.RepositoryReadError) as escaped:
                repository_reads.read_lines(self.route(root), str(target))
            self.assertEqual(escaped.exception.code, "file_read_scope_denied")

    def test_redacts_secret_assignments_and_returns_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "config.txt").write_text("MODE=dev\nAPI_TOKEN=supersecretvalue\n")
            result = repository_reads.read_lines(self.route(root), "config.txt")
            self.assertTrue(result["redacted"]); self.assertNotIn("supersecretvalue", result["content"])
            self.assertEqual(len(result["sha256"]), 64)

    def test_redacts_json_cloud_database_and_bearer_credentials(self) -> None:
        secrets = [
            '"apiKey": "json-secret-value"',
            "AWS_ACCESS_KEY_ID=AKIA1234567890ABCDEF",
            "DATABASE_URL=postgres://alice:db-password@example.test/db",
            "Authorization: Bearer eyJabcdefghijk.abcdefghijkl.abcdefghijk",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "settings.txt").write_text("\n".join(secrets))
            result = repository_reads.read_lines(self.route(root), "settings.txt")
        self.assertTrue(result["redacted"])
        for marker in ("json-secret-value", "AKIA1234567890ABCDEF", "db-password", "eyJabcdefghijk"):
            self.assertNotIn(marker, result["content"])

    def test_huge_line_and_file_are_byte_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "huge.txt").write_text("x" * 2_000_000)
            result = repository_reads.read_lines(self.route(root), "huge.txt", max_bytes=4096, max_scan_bytes=8192)
            self.assertLessEqual(result["bytes"], 4200); self.assertTrue(result["truncated"])
            self.assertIn("line_count_lower_bound", result["limitations"])

    def test_late_range_streams_past_one_mib_with_fixed_buffers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / "late.py"
            with target.open("wb") as handle:
                handle.seek(1_200_000)
                handle.write(b"\nLATE_READ_MARKER = True\n")
            with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read forbidden")):
                result = repository_reads.read_lines(
                    self.route(root), "late.py", start_line=2, end_line=2, max_bytes=4096,
                )
        self.assertIn("LATE_READ_MARKER", result["content"])
        self.assertEqual((result["start_line"], result["end_line"], result["line_count"]), (2, 2, 2))
        self.assertGreater(result["scan"]["bytes_scanned"], 1024 * 1024)
        self.assertEqual(result["scan"]["stream_chunk_bytes"], repository_reads.STREAM_CHUNK_BYTES)
        self.assertLessEqual(result["scan"]["line_buffer_bytes_max"], 4096)
        self.assertLessEqual(result["bytes"], 4096)
        self.assertTrue(result["digest_complete"])

    def test_search_streams_and_uses_the_same_sensitive_path_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "credentials.json").write_text('{"apiKey":"SEARCH-SECRET-MARKER"}')
            (root / "safe.py").write_text("class SafeOwner: pass\n")
            route = {
                "route_id": "fixture", "workspace_root": str(root), "allowed_read_roots": [str(root)],
                "source_index": {"include_roots": ["."], "exclude_globs": [], "max_file_bytes": 10000, "max_total_bytes": 100000},
            }
            with mock.patch.object(Path, "rglob", side_effect=AssertionError("eager rglob forbidden")):
                secret = evidence.compound_discover({"operation_id":"one","request_id":"one","query":"SEARCH-SECRET-MARKER"}, route)
                safe = evidence.compound_discover({"operation_id":"two","request_id":"two","query":"SafeOwner"}, route)
        self.assertEqual(secret["matches"], [])
        self.assertIn("safe.py", {item["file"] for item in safe["matches"]})

    def test_search_route_scan_bound_reaches_match_beyond_index_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / "late.py"
            with target.open("wb") as handle:
                handle.seek(400_000)
                handle.write(b"\ndef LATE_SEARCH_MARKER():\n    return True\n")
            base_index = {
                "include_roots": ["."], "exclude_globs": [],
                "max_file_bytes": 262144, "max_total_bytes": 800000,
            }
            route = {
                "route_id": "fixture", "workspace_root": str(root),
                "allowed_read_roots": [str(root)], "source_index": base_index,
            }
            narrow = evidence.compound_discover(
                {"operation_id":"narrow","request_id":"narrow","query":"LATE_SEARCH_MARKER"}, route,
            )
            route["source_index"] = {**base_index, "max_scan_bytes_per_file": 700000}
            with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read forbidden")):
                widened = evidence.compound_discover(
                    {"operation_id":"wide","request_id":"wide","query":"LATE_SEARCH_MARKER"}, route,
                )
            route.update({"caps": ["repo.read"], "task_contract": {"request_class": "source_investigation"}})
            with mock.patch.object(v5_tools.code_memory, "execute", return_value={"ok": False, "code": "fixture_unavailable"}):
                v5_result = v5_tools.execute(
                    "search", {"query":"LATE_SEARCH_MARKER"}, route, invoke=lambda *_: {},
                )
        self.assertEqual(narrow["matches"], [])
        self.assertEqual(narrow["coverage"][0]["bytes_scanned"], 262144)
        self.assertIn("late.py", {item["file"] for item in widened["matches"]})
        coverage = widened["coverage"][0]
        self.assertGreater(coverage["bytes_scanned"], 262144)
        self.assertLessEqual(coverage["bytes_scanned"], coverage["max_total_bytes"])
        self.assertEqual(coverage["max_scan_bytes_per_file"], 700000)
        self.assertEqual(coverage["stream_chunk_bytes"], repository_reads.STREAM_CHUNK_BYTES)
        self.assertEqual(coverage["line_buffer_bytes_max"], evidence.MAX_SEARCH_LINE_BYTES)
        self.assertIn("late.py", {item["path"] for item in v5_result["matches"]})
        self.assertEqual(v5_result["focus"]["owner_file"], "late.py")
        self.assertEqual(v5_result["focus"]["line_count"], 3)


if __name__ == "__main__":
    unittest.main()
