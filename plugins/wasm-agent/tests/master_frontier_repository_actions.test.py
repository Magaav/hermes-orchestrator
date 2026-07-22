#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from unittest import mock
import hashlib
import os
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))
from master_frontier import repository_actions  # noqa: E402


class RepositoryActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transaction_state = tempfile.TemporaryDirectory()
        self.transaction_env = mock.patch.dict(
            os.environ,
            {repository_actions.TRANSACTION_ROOT_ENV: self.transaction_state.name},
        )
        self.transaction_env.start()

    def tearDown(self) -> None:
        self.transaction_env.stop()
        self.transaction_state.cleanup()
        repository_actions._RECOVERY_BLOCKS.clear()

    def apply(self, root: Path, operations: list[dict], *, dry_run: bool = False) -> dict:
        def resolve(value: str) -> Path:
            path = (root / value).resolve()
            if not value or not (path == root or root in path.parents):
                raise repository_actions.RepositoryActionError("scope_denied", "outside root")
            return path
        return repository_actions.apply(
            operations, dry_run=dry_run, resolve=resolve, relative=lambda path: str(path.relative_to(root)),
            max_operations=24, max_file_bytes=10000, max_payload_bytes=10000,
        )

    def test_create_replace_append_move_delete_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "old.txt").write_text("alpha\n")
            result = self.apply(root, [
                {"op":"replace","path":"old.txt","find":"alpha","replace":"beta"},
                {"op":"append","path":"old.txt","insert":"more\n"},
                {"op":"move","path":"old.txt","destination":"moved.txt"},
                {"op":"create","path":"created.txt","content":"new\n"},
                {"op":"delete","path":"created.txt"},
            ])
            self.assertFalse((root / "old.txt").exists()); self.assertEqual((root / "moved.txt").read_text(), "beta\nmore\n")
            self.assertFalse((root / "created.txt").exists()); self.assertEqual(result["changed_files"], ["moved.txt", "old.txt"])

    def test_invalid_later_operation_does_not_commit_earlier_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / "x.txt"; target.write_text("one\n")
            with self.assertRaises(repository_actions.RepositoryActionError):
                self.apply(root, [{"op":"replace","path":"x.txt","find":"one","replace":"two"}, {"op":"delete","path":"missing.txt"}])
            self.assertEqual(target.read_text(), "one\n")

    def test_dry_run_reports_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.apply(root, [{"op":"create","path":"x.txt","content":"x\n"}], dry_run=True)
            self.assertFalse((root / "x.txt").exists()); self.assertFalse(result["applied"]); self.assertIn("x.txt", result["diff"])

    def test_preimage_assertion_and_postimage_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / "x.txt"; target.write_text("one\n")
            before = hashlib.sha256(b"one\n").hexdigest()
            result = self.apply(root, [{"op":"replace","path":"x.txt","find":"one","replace":"two","expected_sha256":before}])
            self.assertEqual(result["postimage_sha256"]["x.txt"], hashlib.sha256(b"two\n").hexdigest())
            with self.assertRaisesRegex(repository_actions.RepositoryActionError, "changed since it was read"):
                self.apply(root, [{"op":"replace","path":"x.txt","find":"two","replace":"three","expected_sha256":before}])

    def test_commit_failure_rolls_back_already_replaced_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "a.txt").write_text("a\n"); (root / "b.txt").write_text("b\n")
            real_replace = repository_actions.os.replace
            commits = 0
            def fail_second(source, destination):
                nonlocal commits
                if ".mf5-" in str(source):
                    commits += 1
                    if commits == 2:
                        raise OSError("injected commit failure")
                return real_replace(source, destination)
            with mock.patch.object(repository_actions.os, "replace", side_effect=fail_second):
                with self.assertRaises(repository_actions.RepositoryActionError) as raised:
                    self.apply(root, [
                        {"op":"replace","path":"a.txt","find":"a","replace":"A"},
                        {"op":"replace","path":"b.txt","find":"b","replace":"B"},
                    ])
            self.assertEqual(raised.exception.code, "patch_commit_failed")
            self.assertEqual((root / "a.txt").read_text(), "a\n")
            self.assertEqual((root / "b.txt").read_text(), "b\n")

    def test_preimage_hash_preserves_crlf_bytes_across_multiple_operations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / "x.txt"; target.write_bytes(b"one\r\ntwo\r\n")
            before = hashlib.sha256(target.read_bytes()).hexdigest()
            result = self.apply(root, [
                {"op": "replace", "path": "x.txt", "find": "one", "replace": "ONE", "expected_sha256": before},
                {"op": "replace", "path": "x.txt", "find": "two", "replace": "TWO", "expected_sha256": before},
            ])
            self.assertEqual(target.read_bytes(), b"ONE\r\nTWO\r\n")
            self.assertEqual(result["postimage_sha256"]["x.txt"], hashlib.sha256(target.read_bytes()).hexdigest())

    def test_new_path_commit_never_clobbers_a_concurrent_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / "x.txt"; target.write_text("intruder\n")
            with self.assertRaises(repository_actions.RepositoryActionError) as raised:
                repository_actions._commit({target: "ours\n"}, {target: None})
            self.assertEqual(raised.exception.code, "patch_preimage_changed")
            self.assertEqual(target.read_text(), "intruder\n")

    def test_restart_recovery_restores_journaled_preimage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); journal_root = root / "journals"
            target = root / "x.txt"; target.write_text("before\n")
            backup = repository_actions._staged_file(target, "before\n", label="mf5-backup")
            target.write_text("partial-after\n")
            with mock.patch.dict(os.environ, {repository_actions.TRANSACTION_ROOT_ENV: str(journal_root)}):
                repository_actions._journal_write([{
                    "path": str(target), "original_absent": False,
                    "backup": str(backup), "staged": "",
                }])
                self.assertEqual(repository_actions.recover_pending(strict=True), 1)
            self.assertEqual(target.read_text(), "before\n")
            self.assertFalse(backup.exists())

    def test_journal_defaults_beside_configured_db_not_process_temp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); db_path = root / "durable" / "db" / "wa.sqlite3"
            with mock.patch.dict(
                os.environ,
                {repository_actions.DB_PATH_ENV: str(db_path)},
                clear=True,
            ):
                resolved = repository_actions.journal_root()
            self.assertEqual(resolved, db_path.parent / repository_actions.JOURNAL_DIRECTORY_NAME)
            self.assertNotEqual(resolved, Path(tempfile.gettempdir()) / repository_actions.JOURNAL_DIRECTORY_NAME)

    def test_configured_durable_journal_recovers_after_volatile_runtime_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); db_path = root / "durable" / "db" / "wa.sqlite3"
            volatile = root / "volatile-runtime"; volatile.mkdir()
            target = root / "x.txt"; target.write_text("before\n")
            backup = repository_actions._staged_file(target, "before\n", label="mf5-backup")
            target.write_text("partial-after\n")
            with mock.patch.dict(os.environ, {repository_actions.DB_PATH_ENV: str(db_path)}, clear=True):
                journal = repository_actions._journal_write([{
                    "path": str(target), "original_absent": False,
                    "backup": str(backup), "staged": "",
                }])
                volatile.rmdir()  # Simulate loss of unrelated process-temporary state.
                self.assertTrue(journal.is_file())
                self.assertEqual(repository_actions.recover_pending(strict=True), 1)
            self.assertEqual(target.read_text(), "before\n")

    def test_missing_recovery_backup_blocks_new_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); journal_root = root / "journals"
            target = root / "x.txt"; target.write_text("partial-after\n")
            missing = target.parent / f".{target.name}.mf5-backup-missing"
            with mock.patch.dict(os.environ, {repository_actions.TRANSACTION_ROOT_ENV: str(journal_root)}):
                repository_actions._journal_write([{
                    "path": str(target), "original_absent": False,
                    "backup": str(missing), "staged": "",
                }])
                with self.assertRaises(repository_actions.RepositoryActionError) as raised:
                    self.apply(root, [{"op":"create","path":"new.txt","content":"new\n"}])
            self.assertEqual(raised.exception.code, "patch_recovery_blocked")
            self.assertFalse((root / "new.txt").exists())

    def test_corrupt_recovery_journal_blocks_new_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); journal_root = root / "journals"; journal_root.mkdir()
            (journal_root / "transaction-corrupt.json").write_text("{broken")
            with mock.patch.dict(os.environ, {repository_actions.TRANSACTION_ROOT_ENV: str(journal_root)}):
                with self.assertRaises(repository_actions.RepositoryActionError) as raised:
                    self.apply(root, [{"op":"create","path":"new.txt","content":"new\n"}])
            self.assertEqual(raised.exception.code, "patch_recovery_blocked")
            self.assertFalse((root / "new.txt").exists())


if __name__ == "__main__": unittest.main()
