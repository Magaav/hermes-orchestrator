#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))
from master_frontier import repository_diff  # noqa: E402


class RepositoryDiffTests(unittest.TestCase):
    def test_nested_route_paths_are_route_relative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            nested = root / "plugin"
            nested.mkdir()
            (nested / "x.py").write_text("x\n", encoding="utf-8")
            result = repository_diff.collect(self.route(nested))
        self.assertEqual([item["path"] for item in result["changed_files"]], ["x.py"])

    @staticmethod
    def git(root: Path, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(root), *args], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def initialized(self, root: Path) -> None:
        self.git(root, "init", "-q")
        self.git(root, "config", "user.email", "tests@example.invalid")
        self.git(root, "config", "user.name", "Master Frontier Tests")

    @staticmethod
    def route(root: Path) -> dict:
        return {"route_id": "test.repository", "workspace_root": str(root)}

    def test_includes_index_worktree_delete_rename_and_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.initialized(root)
            for name in ("worktree.txt", "staged.txt", "deleted.txt", "old.txt"):
                (root / name).write_text(f"original {name}\n", encoding="utf-8")
            self.git(root, "add", ".")
            self.git(root, "commit", "-qm", "fixture")

            (root / "worktree.txt").write_text("worktree change\n", encoding="utf-8")
            (root / "staged.txt").write_text("staged change\n", encoding="utf-8")
            self.git(root, "add", "staged.txt")
            (root / "deleted.txt").unlink()
            self.git(root, "mv", "old.txt", "renamed.txt")
            (root / "untracked.txt").write_text("new\n", encoding="utf-8")

            result = repository_diff.collect(self.route(root))
            files = {item["path"]: item for item in result["changed_files"]}

            self.assertTrue(result["ok"])
            self.assertEqual(result["schema"], repository_diff.SCHEMA)
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(files["worktree.txt"]["status"], " M")
            self.assertTrue(files["worktree.txt"]["worktree"])
            self.assertEqual(files["staged.txt"]["status"], "M ")
            self.assertTrue(files["staged.txt"]["staged"])
            self.assertEqual(files["deleted.txt"]["kind"], "deleted")
            self.assertEqual(files["renamed.txt"]["kind"], "renamed")
            self.assertEqual(files["renamed.txt"]["old_path"], "old.txt")
            self.assertEqual(files["untracked.txt"]["kind"], "untracked")
            self.assertEqual(result["stat"]["reported"], 5)
            self.assertTrue(result["stat"]["complete"])
            self.assertFalse(any(result["truncation"].values()))
            self.assertEqual(len(result["receipt_sha256"]), 64)
            self.assertIn("?? untracked.txt", result["output"])

    def test_entry_and_projection_caps_are_explicit_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.initialized(root)
            for index in range(20):
                (root / f"untracked-{index:02d}.txt").write_text("x\n", encoding="utf-8")

            result = repository_diff.collect(
                self.route(root), max_entries=3, max_output_bytes=256,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "diff_receipt_truncated")
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(len(result["changed_files"]), 3)
            self.assertTrue(result["truncation"]["entries"])
            self.assertFalse(result["stat"]["complete"])
            self.assertLessEqual(len(result["output"].encode("utf-8")), 256)

    def test_output_cap_does_not_discard_complete_machine_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.initialized(root)
            for index in range(8):
                (root / ("long-" + str(index) + "-" + "x" * 80 + ".txt")).write_text("x\n", encoding="utf-8")

            result = repository_diff.collect(
                self.route(root), max_entries=32, max_output_bytes=256,
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["truncation"]["output"])
            self.assertEqual(len(result["changed_files"]), 8)
            self.assertLessEqual(len(result["output"].encode("utf-8")), 256)

    def test_non_repository_returns_typed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = repository_diff.collect(self.route(Path(tmp)))
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "diff_not_repository")
            self.assertNotEqual(result["returncode"], 0)
            self.assertEqual(result["changed_files"], [])
            self.assertIn("truncation", result)


if __name__ == "__main__":
    unittest.main()
