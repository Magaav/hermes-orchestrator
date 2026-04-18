from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


_HANDLERS_CANDIDATES = (
    Path("/local/plugins/public/discord/hooks/discord_slash_bridge/handlers.py"),
)
_HANDLERS_PATH = next((p for p in _HANDLERS_CANDIDATES if p.exists()), _HANDLERS_CANDIDATES[0])

_SPEC = importlib.util.spec_from_file_location("discord_slash_handlers_acl_test_module", _HANDLERS_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"failed to load handlers module from {_HANDLERS_PATH}")
_HANDLERS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_HANDLERS)


class _FakeProc:
    def __init__(self, stdout_text: str, stderr_text: str = "", returncode: int = 0) -> None:
        self._stdout = stdout_text.encode("utf-8")
        self._stderr = stderr_text.encode("utf-8")
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr


class _FakeUser:
    def __init__(self, user_id: int = 999, name: str = "tester") -> None:
        self.id = user_id
        self.display_name = name
        self.name = name


class _FakeResponse:
    def __init__(self) -> None:
        self._done = False
        self.messages: list[str] = []

    def is_done(self) -> bool:
        return self._done

    async def defer(self, ephemeral: bool = False) -> None:
        self._done = True

    async def send_message(self, content: str, ephemeral: bool = False) -> None:
        self._done = True
        self.messages.append(content)


class _FakeFollowup:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, content: str, ephemeral: bool = False) -> None:
        self.messages.append(content)


class _FakeInteraction:
    def __init__(self) -> None:
        self.user = _FakeUser()
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()
        self.edits: list[str] = []

    async def edit_original_response(self, content: str) -> None:
        self.edits.append(content)


class _FakeThreadLikeChannel:
    def __init__(self, parent_id: str) -> None:
        self.parent_id = parent_id
        self.type = "public_thread"


class SlashAclManagementTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_bypass_still_respects_channel_acl_gate(self) -> None:
        interaction = _FakeInteraction()
        with patch.object(
            _HANDLERS,
            "check_role_acl",
            AsyncMock(return_value=(True, "", {"decision": "admin_bypass"})),
        ), patch.object(
            _HANDLERS,
            "check_command_acl",
            return_value=(False, "blocked"),
        ) as channel_acl_mock:
            allowed = await _HANDLERS.ensure_slash_acl_allowed(
                adapter=object(),
                interaction=interaction,
                acl_command="metricas",
                command_name="metricas",
            )
        self.assertFalse(allowed)
        channel_acl_mock.assert_called_once()
        self.assertEqual(interaction.response.messages[-1], "blocked")

    async def test_run_metrics_dashboard_passes_skip_dashboard_acl_flag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-metrics-handler-") as tmp:
            script = Path(tmp) / "metrics_logger.py"
            script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

            captured: list[str] = []

            async def _fake_spawn(*cmd, **kwargs):
                captured[:] = [str(part) for part in cmd]
                payload = {"ok": True, "text": "ok"}
                return _FakeProc(json.dumps(payload, ensure_ascii=False))

            with patch.object(_HANDLERS, "_resolve_existing_path", return_value=(script, [script])), patch.object(
                _HANDLERS,
                "_resolve_python_bin",
                return_value="/usr/bin/python3",
            ), patch.object(_HANDLERS.asyncio, "create_subprocess_exec", side_effect=_fake_spawn):
                text, is_error = await _HANDLERS.run_metrics_dashboard(
                    interaction=_FakeInteraction(),
                    command_name="metricas",
                    option_values={"dias": 7, "formato": "texto"},
                    settings={},
                )

            self.assertFalse(is_error)
            self.assertEqual(text, "ok")
            self.assertIn("--skip-dashboard-admin-check", captured)

    async def test_check_command_acl_uses_parent_for_thread_like_interactions(self) -> None:
        interaction = _FakeInteraction()
        interaction.channel_id = "1491111111111111111"
        interaction.channel = _FakeThreadLikeChannel(parent_id="1487099552636080201")

        captured: dict[str, str] = {}

        def _check(channel_id: str, command: str, *, thread_id: str | None = None, parent_id: str | None = None):
            captured["channel_id"] = channel_id
            captured["command"] = command
            captured["thread_id"] = str(thread_id or "")
            captured["parent_id"] = str(parent_id or "")
            return False, "blocked"

        fake_mod = type("FakeChannelAcl", (), {"check_command_allowed": staticmethod(_check)})
        with patch.object(_HANDLERS, "_load_channel_acl_module", return_value=fake_mod):
            allowed, message = _HANDLERS.check_command_acl(object(), interaction, "metricas")

        self.assertFalse(allowed)
        self.assertEqual(message, "blocked")
        self.assertEqual(captured.get("channel_id"), "1487099552636080201")
        self.assertEqual(captured.get("thread_id"), "1491111111111111111")
        self.assertEqual(captured.get("parent_id"), "1487099552636080201")

    async def test_handle_acl_command_update_persists_min_role(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-acl-update-") as tmp:
            acl_path = Path(tmp) / "orchestrator_acl.json"
            acl_payload = {
                "node": "orchestrator",
                "guild_id": "123",
                "hierarchy": [
                    {"role_id": "10", "role_name": "admin"},
                    {"role_id": "20", "role_name": "gerente"},
                    {"role_id": "@everyone", "role_name": "@everyone"},
                ],
                "commands": {"metricas": {}},
            }
            acl_path.write_text(json.dumps(acl_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            interaction = _FakeInteraction()
            with patch.object(_HANDLERS, "ensure_slash_acl_allowed", AsyncMock(return_value=True)), patch.object(
                _HANDLERS,
                "resolve_role_acl_path",
                return_value=str(acl_path),
            ):
                handled = await _HANDLERS.handle_acl_command_update(
                    adapter=object(),
                    interaction=interaction,
                    command_value="metricas",
                    role_value="gerente",
                    settings={"acl_command": "acl"},
                )

            self.assertTrue(handled)
            stored = json.loads(acl_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["commands"]["metricas"]["min_role"], "20")
            self.assertTrue(interaction.edits)
            self.assertIn("ACL de comando atualizado", interaction.edits[-1])

    async def test_handle_acl_channel_update_sets_specific_mode_with_model_key(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-acl-channel-") as tmp:
            private_root = Path(tmp) / "plugins" / "private" / "discord"
            models_path = private_root / "models" / "orchestrator_models.json"
            config_path = private_root / "hooks" / "channel_acl" / "config.yaml"
            models_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            models_path.write_text(
                json.dumps(
                    {
                        "node": "orchestrator",
                        "models": [
                            {
                                "key": "nemotron120b",
                                "label": "Nemotron",
                                "provider": "nvidia",
                                "model": "nvidia/nemotron-3-super-120b-a12b",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            config_path.write_text("channels: {}\n", encoding="utf-8")

            old_private = os.environ.get("HERMES_DISCORD_PRIVATE_DIR")
            old_node = os.environ.get("NODE_NAME")
            os.environ["HERMES_DISCORD_PRIVATE_DIR"] = str(private_root)
            os.environ["NODE_NAME"] = "orchestrator"
            try:
                interaction = _FakeInteraction()
                with patch.object(_HANDLERS, "ensure_slash_acl_allowed", AsyncMock(return_value=True)):
                    handled = await _HANDLERS.handle_acl_channel_update(
                        adapter=object(),
                        interaction=interaction,
                        channel_value="1487099467726328038",
                        mode_value="specific",
                        model_key="nemotron120b",
                        instructions="Somente faltas",
                        allowed_commands="faltas,clean",
                        allowed_skills="colmeio-lista-de-faltas",
                        label="loja1",
                        settings={"acl_command": "acl"},
                    )

                self.assertTrue(handled)
                payload = _HANDLERS.yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                channels = payload.get("channels") or {}
                row = channels.get("1487099467726328038") or {}
                self.assertEqual(row.get("mode"), "condicionado")
                self.assertEqual(row.get("model_key"), "nemotron120b")
                self.assertEqual(row.get("provider"), "nvidia")
                self.assertEqual(row.get("model"), "nvidia/nemotron-3-super-120b-a12b")
                self.assertEqual(row.get("allowed_commands"), ["faltas", "clean"])
                self.assertEqual(row.get("label"), "loja1")
                self.assertTrue(interaction.edits)
                self.assertIn("ACL de canal atualizado", interaction.edits[-1])
            finally:
                if old_private is None:
                    os.environ.pop("HERMES_DISCORD_PRIVATE_DIR", None)
                else:
                    os.environ["HERMES_DISCORD_PRIVATE_DIR"] = old_private
                if old_node is None:
                    os.environ.pop("NODE_NAME", None)
                else:
                    os.environ["NODE_NAME"] = old_node

    async def test_handle_acl_channel_update_rejects_invalid_model_key(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-acl-channel-invalid-") as tmp:
            private_root = Path(tmp) / "plugins" / "private" / "discord"
            models_path = private_root / "models" / "orchestrator_models.json"
            config_path = private_root / "hooks" / "channel_acl" / "config.yaml"
            models_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            models_path.write_text(
                json.dumps(
                    {
                        "node": "orchestrator",
                        "models": [
                            {
                                "key": "gpt54",
                                "label": "GPT-5.4",
                                "provider": "openai-codex",
                                "model": "gpt-5.4",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            config_path.write_text("channels: {}\n", encoding="utf-8")

            old_private = os.environ.get("HERMES_DISCORD_PRIVATE_DIR")
            old_node = os.environ.get("NODE_NAME")
            os.environ["HERMES_DISCORD_PRIVATE_DIR"] = str(private_root)
            os.environ["NODE_NAME"] = "orchestrator"
            try:
                interaction = _FakeInteraction()
                with patch.object(_HANDLERS, "ensure_slash_acl_allowed", AsyncMock(return_value=True)):
                    handled = await _HANDLERS.handle_acl_channel_update(
                        adapter=object(),
                        interaction=interaction,
                        channel_value="1487099467726328038",
                        mode_value="specific",
                        model_key="missing-key",
                        settings={"acl_command": "acl"},
                    )

                self.assertTrue(handled)
                self.assertTrue(interaction.edits)
                self.assertIn("model_key inválido", interaction.edits[-1])
            finally:
                if old_private is None:
                    os.environ.pop("HERMES_DISCORD_PRIVATE_DIR", None)
                else:
                    os.environ["HERMES_DISCORD_PRIVATE_DIR"] = old_private
                if old_node is None:
                    os.environ.pop("NODE_NAME", None)
                else:
                    os.environ["NODE_NAME"] = old_node


if __name__ == "__main__":
    unittest.main()
