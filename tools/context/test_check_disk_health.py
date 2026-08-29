#!/usr/bin/env python3
"""Focused behavioral tests for the disk-health guard."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("check-disk-health.py")


class DiskHealthTest(unittest.TestCase):
    def run_guard(self, root: Path, tmp_root: Path, report: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT), "--root", str(root), "--tmp-root", str(tmp_root), "--report", str(report), "--stale-minutes", "5", *extra],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_read_only_fails_on_stale_artifacts_and_cleanup_removes_only_known_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, tmp_root, report = base / "repo", base / "tmp", base / "report.json"
            pack_root = root / ".git" / "objects" / "pack"
            pack_root.mkdir(parents=True)
            tmp_root.mkdir()
            stale_pack = pack_root / "tmp_pack_fixture"
            valid_pack = pack_root / "pack-valid.pack"
            stale_build = tmp_root / "wasm-agent-installer-fixture"
            unrelated = tmp_root / "keep-me"
            stale_pack.write_bytes(b"garbage")
            valid_pack.write_bytes(b"valid")
            stale_build.mkdir()
            (stale_build / "payload").write_bytes(b"payload")
            unrelated.mkdir()
            old = time.time() - 7200
            os.utime(stale_pack, (old, old))
            os.utime(stale_build, (old, old))

            observed = self.run_guard(root, tmp_root, report)
            self.assertEqual(observed.returncode, 1)
            self.assertTrue(stale_pack.exists())
            self.assertTrue(stale_build.exists())

            cleaned = self.run_guard(root, tmp_root, report, "--cleanup")
            self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
            result = json.loads(report.read_text())
            self.assertEqual(result["removed"]["gitFiles"], 1)
            self.assertEqual(result["removed"]["buildDirs"], 1)
            self.assertTrue(valid_pack.exists())
            self.assertTrue(unrelated.exists())


if __name__ == "__main__":
    unittest.main()
