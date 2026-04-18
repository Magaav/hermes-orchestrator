from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


_SCRIPT_CANDIDATES = (
    Path("/local/plugins/public/discord/scripts/discord_role_acl_sync.py"),
)
SCRIPT_PATH = next((p for p in _SCRIPT_CANDIDATES if p.exists()), _SCRIPT_CANDIDATES[0])


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class DiscordRoleAclSyncTests(unittest.TestCase):
    maxDiff = None

    def _run_sync(self, *, private_root: Path, node_name: str, guild_id: str) -> dict:
        cmd = [
            "python3",
            str(SCRIPT_PATH),
            "--private-root",
            str(private_root),
            "--node-name",
            node_name,
            "--guild-id",
            guild_id,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, msg=f"stderr={proc.stderr}")
        payload = json.loads(proc.stdout)
        self.assertIsInstance(payload, dict)
        return payload

    def test_bootstrap_creates_private_acl_and_fail_closed_entries(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-role-acl-sync-") as tmp:
            root = Path(tmp)
            private_root = root / "plugins" / "private" / "discord"
            commands_path = private_root / "commands" / "colmeio.json"
            registry_path = private_root / "hooks" / "discord_slash_bridge" / "registry.yaml"

            _write_text(
                commands_path,
                json.dumps(
                    [
                        {"name": "faltas"},
                        {"name": "metricas"},
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
            )
            _write_text(
                registry_path,
                "\n".join(
                    [
                        "version: 1",
                        "native_overrides:",
                        "  reboot:",
                        "    enabled: true",
                        "slash_bridge:",
                        "  commands:",
                        "    clean:",
                        "      acl_command: clean",
                        "",
                    ]
                ),
            )

            payload = self._run_sync(private_root=private_root, node_name="colmeio", guild_id="123")
            self.assertTrue(payload.get("ok"))
            self.assertTrue(payload.get("wrote"))

            acl_path = Path(str(payload.get("acl_path") or ""))
            self.assertTrue(acl_path.exists())

            acl = json.loads(acl_path.read_text(encoding="utf-8"))
            self.assertEqual(acl.get("node"), "colmeio")
            self.assertEqual(acl.get("guild_id"), "123")
            self.assertEqual(acl.get("policy", {}).get("unmapped_command"), "deny")

            commands = acl.get("commands") or {}
            self.assertIn("status", commands)
            self.assertEqual(commands["status"].get("min_role"), "@everyone")
            self.assertIn("clean", commands)
            self.assertIsNone(commands["clean"].get("min_role"))

    def test_refresh_preserves_manual_command_role_mapping(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-role-acl-sync-") as tmp:
            root = Path(tmp)
            private_root = root / "plugins" / "private" / "discord"
            commands_path = private_root / "commands" / "orchestrator.json"
            registry_path = private_root / "hooks" / "discord_slash_bridge" / "registry.yaml"
            acl_path = private_root / "acl" / "orchestrator_acl.json"

            _write_text(commands_path, json.dumps([{"name": "clone"}], indent=2) + "\n")
            _write_text(registry_path, "version: 1\n")
            _write_text(
                acl_path,
                json.dumps(
                    {
                        "node": "orchestrator",
                        "guild_id": "123",
                        "hierarchy": [
                            {"role_id": "10", "role_name": "admin"},
                            {"role_id": "@everyone", "role_name": "@everyone"},
                        ],
                        "commands": {
                            "clone": {"min_role": "10"},
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
            )

            payload = self._run_sync(private_root=private_root, node_name="orchestrator", guild_id="123")
            self.assertTrue(payload.get("ok"))

            acl = json.loads(acl_path.read_text(encoding="utf-8"))
            self.assertEqual((acl.get("commands") or {}).get("clone", {}).get("min_role"), "10")


if __name__ == "__main__":
    unittest.main()
