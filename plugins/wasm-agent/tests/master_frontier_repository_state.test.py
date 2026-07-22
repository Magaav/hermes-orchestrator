#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))
from master_frontier import repository_state  # noqa: E402


class RepositoryStateTests(unittest.TestCase):
    def test_exact_postimages_bind_and_external_change_invalidates_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / "x.py"; target.write_text("one\n")
            route = {"workspace_root": str(root), "allowed_write_roots": [str(root)]}
            expected = {"x.py": hashlib.sha256(b"one\n").hexdigest()}
            first = repository_state.verify(route, expected)
            self.assertTrue(first["ok"]); self.assertEqual(first["digest"], first["expected_digest"])
            target.write_text("two\n")
            second = repository_state.verify(route, expected)
            self.assertFalse(second["ok"]); self.assertEqual(second["mismatches"], ["x.py"])

    def test_deleted_postimage_and_scope_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp); route = {"workspace_root": str(root), "allowed_write_roots": [str(root)]}
            self.assertTrue(repository_state.verify(route, {"gone.py": "deleted"})["ok"])
            escaped = repository_state.verify(route, {str(Path(outside) / "x.py"): "deleted"})
            self.assertFalse(escaped["ok"])

    def test_route_state_digest_detects_other_dirty_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "owned.py"; other = root / "dependency.py"
            target.write_text("base\n"); other.write_text("stable\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=test", "-c", "user.email=test@example.test", "commit", "-qm", "base"],
                cwd=root, check=True,
            )
            target.write_text("changed\n")
            expected = {"owned.py": hashlib.sha256(b"changed\n").hexdigest()}
            route = {
                "workspace_root": str(root), "allowed_write_roots": [str(root)],
                "source_index": {"max_total_bytes": 1024 * 1024},
            }
            first = repository_state.verify(route, expected)
            self.assertTrue(first["ok"]); self.assertTrue(first["route_state_sha256"])
            other.write_text("changed elsewhere\n")
            second = repository_state.verify(route, expected)
            self.assertTrue(second["ok"])
            self.assertNotEqual(first["digest"], second["digest"])

    def test_route_state_excludes_declared_generated_artifacts_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "owned.py"
            target.write_text("base\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=test", "-c", "user.email=test@example.test", "commit", "-qm", "base"],
                cwd=root, check=True,
            )
            target.write_text("changed\n")
            expected = {"owned.py": hashlib.sha256(b"changed\n").hexdigest()}
            route = {
                "workspace_root": str(root), "allowed_write_roots": [str(root)],
                "source_index": {"exclude_globs": ["**/__pycache__/**"]},
            }
            first = repository_state.verify(route, expected)
            cache = root / "__pycache__" / "owned.cpython-312.pyc"
            cache.parent.mkdir(); cache.write_bytes(b"generated")
            excluded = repository_state.verify(route, expected)
            self.assertEqual(first["digest"], excluded["digest"])
            (root / "unexpected.txt").write_text("owned state\n")
            source_change = repository_state.verify(route, expected)
            self.assertNotEqual(excluded["digest"], source_change["digest"])


if __name__ == "__main__": unittest.main()
