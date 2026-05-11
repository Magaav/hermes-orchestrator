from __future__ import annotations

import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import clone_manager


class SpaceBackupTests(unittest.TestCase):
    def test_space_backup_archives_private_state_manifest_without_noise(self) -> None:
        with tempfile.TemporaryDirectory(prefix="horc-space-backup-test-") as tmp:
            root = Path(tmp)
            cloud_root = root / "private" / "instance-a"
            state_root = cloud_root / "state"
            backups_root = root / "backups"
            (state_root / "db" / "sqlite").mkdir(parents=True)
            (state_root / "users" / "101" / "spaces" / "home").mkdir(parents=True)
            (state_root / "db" / "sqlite" / "wa_db.sqlite3").write_text("sqlite", encoding="utf-8")
            (state_root / "users" / "101" / "spaces" / "home" / "space.json").write_text("{}", encoding="utf-8")
            (state_root / "wasm-agent.pid").write_text("123\n", encoding="utf-8")
            (state_root / "wasm-agent.log").write_text("noisy\n", encoding="utf-8")
            (state_root / "browser" / "cache").mkdir(parents=True)
            (state_root / "browser" / "cache" / "frame.png").write_text("cache", encoding="utf-8")

            env = {
                "HERMES_WASM_AGENT_CLOUD_STATE_ROOT": str(cloud_root),
                "HERMES_WASM_AGENT_CLOUD_INSTANCE_ID": "team-alpha",
            }
            with patch.dict(os.environ, env, clear=False), patch.object(clone_manager, "BACKUPS_ROOT", backups_root):
                result = clone_manager._action_space_backup()

            self.assertTrue(result["ok"])
            self.assertEqual(result["instance_id"], "team-alpha")
            archive = Path(result["archive"])
            self.assertTrue(archive.exists())
            with tarfile.open(archive, "r:gz") as tf:
                names = tf.getnames()
                self.assertIn("wasm-agent-cloud/team-alpha/backup-manifest.json", names)
                self.assertIn("wasm-agent-cloud/team-alpha/state/db/sqlite/wa_db.sqlite3", names)
                self.assertIn("wasm-agent-cloud/team-alpha/state/users/101/spaces/home/space.json", names)
                self.assertNotIn("wasm-agent-cloud/team-alpha/state/wasm-agent.pid", names)
                self.assertNotIn("wasm-agent-cloud/team-alpha/state/wasm-agent.log", names)
                self.assertNotIn("wasm-agent-cloud/team-alpha/state/browser/cache/frame.png", names)
                manifest = json.loads(tf.extractfile("wasm-agent-cloud/team-alpha/backup-manifest.json").read().decode("utf-8"))
            self.assertEqual(manifest["schema"], "hermes.wasm_agent.space_backup_manifest.v1")
            self.assertEqual(manifest["instance_id"], "team-alpha")
            self.assertEqual(manifest["server_role"], "auth-sync-relay-backup-fleet")


if __name__ == "__main__":
    unittest.main()
