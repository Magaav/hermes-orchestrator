from __future__ import annotations

import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


_ROLE_ACL_CANDIDATES = (
    Path("/local/plugins/public/discord/hooks/discord_slash_bridge/role_acl.py"),
)
_ROLE_ACL_PATH = next((p for p in _ROLE_ACL_CANDIDATES if p.exists()), _ROLE_ACL_CANDIDATES[0])

_SPEC = importlib.util.spec_from_file_location("discord_role_acl_test_module", _ROLE_ACL_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"failed to load role ACL module from {_ROLE_ACL_PATH}")
_ROLE_ACL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ROLE_ACL)


class _Role:
    def __init__(self, role_id: str, name: str):
        self.id = int(role_id)
        self.name = name


class _User:
    def __init__(self, user_id: str, roles: list[_Role]):
        self.id = int(user_id)
        self.roles = roles


class _Guild:
    def __init__(self, guild_id: str):
        self.id = int(guild_id)


class _Interaction:
    def __init__(self, *, user_id: str, role_pairs: list[tuple[str, str]], guild_id: str = "123"):
        self.user = _User(user_id, [_Role(role_id, name) for role_id, name in role_pairs])
        self.guild = _Guild(guild_id)


class RoleAclEngineTests(unittest.TestCase):
    def _write_acl(self, root: Path, payload: dict) -> Path:
        path = root / "orchestrator_acl.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def test_higher_role_inherits_lower_command_permission(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-role-acl-engine-") as tmp:
            root = Path(tmp)
            acl_path = self._write_acl(
                root,
                {
                    "node": "orchestrator",
                    "guild_id": "123",
                    "hierarchy": [
                        {"role_id": "10", "role_name": "admin"},
                        {"role_id": "20", "role_name": "gerente"},
                        {"role_id": "30", "role_name": "aprovado"},
                        {"role_id": "@everyone", "role_name": "@everyone"},
                    ],
                    "commands": {
                        "model": {"min_role": "20"},
                    },
                },
            )

            interaction = _Interaction(user_id="1000", role_pairs=[("10", "admin")])
            result = asyncio.run(
                _ROLE_ACL.authorize_interaction(
                    interaction,
                    "model",
                    acl_path=acl_path,
                )
            )

            self.assertTrue(result.get("allowed"))
            self.assertEqual(result.get("decision"), "admin_bypass")

    def test_multi_role_user_uses_highest_rank(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-role-acl-engine-") as tmp:
            root = Path(tmp)
            acl_path = self._write_acl(
                root,
                {
                    "node": "orchestrator",
                    "guild_id": "123",
                    "hierarchy": [
                        {"role_id": "10", "role_name": "admin"},
                        {"role_id": "20", "role_name": "gerente"},
                        {"role_id": "30", "role_name": "loja1"},
                        {"role_id": "40", "role_name": "aprovado"},
                        {"role_id": "@everyone", "role_name": "@everyone"},
                    ],
                    "commands": {
                        "faltas": {"min_role": "30"},
                    },
                },
            )

            interaction = _Interaction(
                user_id="1000",
                role_pairs=[("40", "aprovado"), ("20", "gerente")],
            )
            result = asyncio.run(_ROLE_ACL.authorize_interaction(interaction, "faltas", acl_path=acl_path))

            self.assertTrue(result.get("allowed"))
            self.assertEqual(result.get("actor_role"), "gerente")

    def test_everyone_role_is_supported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-role-acl-engine-") as tmp:
            root = Path(tmp)
            acl_path = self._write_acl(
                root,
                {
                    "node": "orchestrator",
                    "guild_id": "123",
                    "hierarchy": [
                        {"role_id": "10", "role_name": "admin"},
                        {"role_id": "@everyone", "role_name": "@everyone"},
                    ],
                    "commands": {
                        "status": {"min_role": "@everyone"},
                    },
                },
            )

            interaction = _Interaction(user_id="1000", role_pairs=[])
            result = asyncio.run(_ROLE_ACL.authorize_interaction(interaction, "status", acl_path=acl_path))

            self.assertTrue(result.get("allowed"))
            self.assertEqual(result.get("required_role"), "@everyone")

    def test_unmapped_command_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-role-acl-engine-") as tmp:
            root = Path(tmp)
            acl_path = self._write_acl(
                root,
                {
                    "node": "orchestrator",
                    "guild_id": "123",
                    "hierarchy": [
                        {"role_id": "10", "role_name": "admin"},
                        {"role_id": "20", "role_name": "gerente"},
                        {"role_id": "@everyone", "role_name": "@everyone"},
                    ],
                    "commands": {
                        "status": {"min_role": "@everyone"},
                    },
                },
            )

            interaction = _Interaction(user_id="1000", role_pairs=[("20", "gerente")])
            result = asyncio.run(_ROLE_ACL.authorize_interaction(interaction, "reboot", acl_path=acl_path))

            self.assertFalse(result.get("allowed"))
            self.assertEqual(result.get("decision"), "unmapped_command")

    def test_admin_bypass_allows_unmapped_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-role-acl-engine-") as tmp:
            root = Path(tmp)
            acl_path = self._write_acl(
                root,
                {
                    "node": "orchestrator",
                    "guild_id": "123",
                    "hierarchy": [
                        {"role_id": "10", "role_name": "admin"},
                        {"role_id": "20", "role_name": "gerente"},
                        {"role_id": "@everyone", "role_name": "@everyone"},
                    ],
                    "commands": {
                        "status": {"min_role": "@everyone"},
                    },
                },
            )

            interaction = _Interaction(user_id="1000", role_pairs=[("10", "admin")])
            result = asyncio.run(_ROLE_ACL.authorize_interaction(interaction, "reboot", acl_path=acl_path))

            self.assertTrue(result.get("allowed"))
            self.assertEqual(result.get("decision"), "admin_bypass")

    def test_update_command_min_role_by_role_name(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-role-acl-engine-") as tmp:
            root = Path(tmp)
            acl_path = self._write_acl(
                root,
                {
                    "node": "orchestrator",
                    "guild_id": "123",
                    "hierarchy": [
                        {"role_id": "10", "role_name": "admin"},
                        {"role_id": "20", "role_name": "gerente"},
                        {"role_id": "@everyone", "role_name": "@everyone"},
                    ],
                    "commands": {
                        "metricas": {},
                    },
                },
            )

            result = _ROLE_ACL.update_command_min_role(acl_path, "metricas", "gerente")
            self.assertTrue(result.get("ok"))
            self.assertEqual(result.get("min_role"), "20")

            persisted = json.loads(acl_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["commands"]["metricas"]["min_role"], "20")

    def test_normalize_acl_deduplicates_everyone_entry(self) -> None:
        payload = _ROLE_ACL.normalize_acl(
            {
                "hierarchy": [
                    {"role_id": "@everyone", "role_name": "@everyone"},
                    {"role_id": "", "role_name": "@everyone"},
                ],
            }
        )
        everyone_entries = [
            row for row in payload.get("hierarchy", [])
            if str(row.get("role_id") or "") == "@everyone"
        ]
        self.assertEqual(len(everyone_entries), 1)


if __name__ == "__main__":
    unittest.main()
