#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))
from master_frontier import repository_checks  # noqa: E402


class RepositoryCheckTests(unittest.TestCase):
    def test_passes_argv_without_shell_and_uses_minimal_environment(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            result = repository_checks.run(
                [
                    sys.executable,
                    "-c",
                    "import json,os; print(json.dumps(dict(os.environ), sort_keys=True)); print(os.getcwd())",
                ],
                cwd=root,
                timeout_sec=2,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "passed")
        lines = result["stdout"]["head"].splitlines()
        child_env = json.loads(lines[0])
        self.assertEqual(set(child_env), {"HOME", "LANG", "PATH", "TMPDIR"})
        self.assertNotIn("API_KEY", child_env)
        self.assertEqual(lines[1], str(root))
        self.assertFalse(result["stdout"]["truncated"])
        self.assertEqual(result["stdout"]["bytes"], result["stdout"]["shown_bytes"])

    def test_returns_exact_counts_and_capped_head_tail(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            result = repository_checks.run(
                [sys.executable, "-c", "import sys; sys.stdout.write('A'*20+'B'*20); sys.stderr.write('E'*30)"],
                cwd=root,
                timeout_sec=2,
                preview_bytes=10,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"]["bytes"], 40)
        self.assertEqual(result["stdout"]["shown_bytes"], 10)
        self.assertEqual(result["stdout"]["omitted_bytes"], 30)
        self.assertEqual(result["stdout"]["head"], "AAAAA")
        self.assertEqual(result["stdout"]["tail"], "BBBBB")
        self.assertTrue(result["stdout"]["truncated"])
        self.assertEqual(result["stderr"]["bytes"], 30)
        self.assertLessEqual(result["stdout"]["shown_bytes"], 10)
        self.assertLessEqual(result["stderr"]["shown_bytes"], 10)

    def test_timeout_kills_the_new_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            child_pid_path = root / "child.pid"
            script = (
                "import pathlib,subprocess,sys,time; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid)); "
                "time.sleep(60)"
            )
            result = repository_checks.run(
                [sys.executable, "-c", script],
                cwd=root,
                timeout_sec=0.2,
            )
            child_pid = int(child_pid_path.read_text())
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.01)
            else:
                self.fail("timed-out descendant remained alive")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "check_timeout")
        self.assertTrue(result["timed_out"])
        self.assertIn(result["termination"], {"term", "kill"})

    def test_reports_nonzero_spawn_error_and_invalid_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            failed = repository_checks.run([sys.executable, "-c", "raise SystemExit(7)"], cwd=root, timeout_sec=2)
            missing = repository_checks.run([str(root / "missing")], cwd=root, timeout_sec=2)
            invalid = repository_checks.run("echo unsafe", cwd=root, timeout_sec=2)
        self.assertEqual((failed["status"], failed["code"], failed["returncode"]), ("failed", "check_failed", 7))
        self.assertEqual((missing["status"], missing["code"]), ("spawn_error", "check_spawn_failed"))
        self.assertEqual((invalid["status"], invalid["code"]), ("invalid", "check_invalid_argv"))

    def test_successful_parent_cannot_leave_background_child(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root); child_pid_path = root / "leaked.pid"
            script = (
                "import pathlib,subprocess,sys;"
                "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
                f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid))"
            )
            result = repository_checks.run([sys.executable, "-c", script], cwd=root, timeout_sec=2)
            child_pid = int(child_pid_path.read_text())
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                try: os.kill(child_pid, 0)
                except ProcessLookupError: break
                time.sleep(0.01)
            else: self.fail("background check descendant remained alive")
        self.assertEqual((result["ok"], result["code"], result["status"]), (False, "check_process_leak", "process_leak"))

    def test_setsid_descendant_holding_pipes_cannot_extend_check_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root); child_pid_path = root / "escaped.pid"
            script = (
                "import pathlib,subprocess,sys;"
                "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True);"
                f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid))"
            )
            started = time.monotonic()
            result = repository_checks.run([sys.executable, "-c", script], cwd=root, timeout_sec=1)
            elapsed = time.monotonic() - started
            child_pid = int(child_pid_path.read_text())
            try:
                self.assertLess(elapsed, 1.75)
                self.assertEqual(
                    (result["ok"], result["code"], result["status"]),
                    (False, "check_process_leak", "process_leak"),
                )
                self.assertIn("descendant", result["error"])
            finally:
                try: os.kill(child_pid, 9)
                except ProcessLookupError: pass

    def test_large_output_is_drained_with_constant_preview_memory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            result = repository_checks.run(
                [sys.executable, "-c", "import sys;sys.stdout.write('x'*2000000)"],
                cwd=Path(raw_root), timeout_sec=2, preview_bytes=1024,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"]["bytes"], 2_000_000)
        self.assertEqual(result["stdout"]["shown_bytes"], 1024)
        self.assertTrue(result["stdout"]["truncated"])


if __name__ == "__main__":
    unittest.main()
