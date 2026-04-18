from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


_CHANNEL_ACL_PATH = Path("/local/plugins/public/discord/hooks/channel_acl/handler.py")
_PIPELINE_PATH = Path("/local/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py")


_channel_spec = importlib.util.spec_from_file_location("discord_channel_acl_runtime_test", _CHANNEL_ACL_PATH)
if _channel_spec is None or _channel_spec.loader is None:
    raise RuntimeError(f"failed to load channel ACL module from {_CHANNEL_ACL_PATH}")
_CHANNEL_ACL = importlib.util.module_from_spec(_channel_spec)
sys.modules["discord_channel_acl_runtime_test"] = _CHANNEL_ACL
_channel_spec.loader.exec_module(_CHANNEL_ACL)

_pipeline_spec = importlib.util.spec_from_file_location("faltas_pipeline_test", _PIPELINE_PATH)
if _pipeline_spec is None or _pipeline_spec.loader is None:
    raise RuntimeError(f"failed to load pipeline module from {_PIPELINE_PATH}")
_PIPELINE = importlib.util.module_from_spec(_pipeline_spec)
sys.modules["faltas_pipeline_test"] = _PIPELINE
_pipeline_spec.loader.exec_module(_PIPELINE)


class _Source:
    def __init__(self, *, chat_id: str, chat_id_alt: str | None = None, user_id: str = "200", user_name: str = "worker"):
        self.chat_id = chat_id
        self.chat_id_alt = chat_id_alt
        self.thread_id = chat_id
        self.user_id = user_id
        self.user_name = user_name


class _FakeProc:
    def __init__(self, *, stdout: str, stderr: str = "", returncode: int = 0) -> None:
        self._stdout = stdout.encode("utf-8")
        self._stderr = stderr.encode("utf-8")
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr


class ChannelAclReliabilityTests(unittest.IsolatedAsyncioTestCase):
    def test_source_is_admin_prefers_live_discord_role_over_local_file(self) -> None:
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                # Member has no admin role.
                return b'{"roles":["200"]}'

        old_cache = dict(_CHANNEL_ACL._live_admin_cache)
        old_token = os.environ.get("DISCORD_BOT_TOKEN")
        old_server = os.environ.get("DISCORD_SERVER_ID")
        os.environ["DISCORD_BOT_TOKEN"] = "token-test"
        os.environ["DISCORD_SERVER_ID"] = "guild-test"
        try:
            _CHANNEL_ACL._live_admin_cache = {}
            with mock.patch.object(_CHANNEL_ACL, "_admin_role_ids_from_acl", return_value={"999"}), \
                mock.patch.object(_CHANNEL_ACL.urllib.request, "urlopen", return_value=_Resp()), \
                mock.patch.object(_CHANNEL_ACL, "_load_admin_users", return_value={"123"}):
                is_admin = _CHANNEL_ACL._source_is_admin(_Source(chat_id="1487099467726328038", user_id="123"))
            self.assertFalse(is_admin)
        finally:
            _CHANNEL_ACL._live_admin_cache = old_cache
            if old_token is None:
                os.environ.pop("DISCORD_BOT_TOKEN", None)
            else:
                os.environ["DISCORD_BOT_TOKEN"] = old_token
            if old_server is None:
                os.environ.pop("DISCORD_SERVER_ID", None)
            else:
                os.environ["DISCORD_SERVER_ID"] = old_server

    def test_source_is_admin_falls_back_to_local_file_when_live_check_unavailable(self) -> None:
        old_cache = dict(_CHANNEL_ACL._live_admin_cache)
        old_token = os.environ.get("DISCORD_BOT_TOKEN")
        old_server = os.environ.get("DISCORD_SERVER_ID")
        os.environ["DISCORD_BOT_TOKEN"] = "token-test"
        os.environ["DISCORD_SERVER_ID"] = "guild-test"
        try:
            _CHANNEL_ACL._live_admin_cache = {}
            with mock.patch.object(_CHANNEL_ACL, "_admin_role_ids_from_acl", return_value={"999"}), \
                mock.patch.object(_CHANNEL_ACL.urllib.request, "urlopen", side_effect=RuntimeError("network down")), \
                mock.patch.object(_CHANNEL_ACL, "_load_admin_users", return_value={"123"}):
                is_admin = _CHANNEL_ACL._source_is_admin(_Source(chat_id="1487099467726328038", user_id="123"))
            self.assertTrue(is_admin)
        finally:
            _CHANNEL_ACL._live_admin_cache = old_cache
            if old_token is None:
                os.environ.pop("DISCORD_BOT_TOKEN", None)
            else:
                os.environ["DISCORD_BOT_TOKEN"] = old_token
            if old_server is None:
                os.environ.pop("DISCORD_SERVER_ID", None)
            else:
                os.environ["DISCORD_SERVER_ID"] = old_server

    def test_channel_acl_resolves_private_config_as_source_of_truth(self) -> None:
        with tempfile.TemporaryDirectory(prefix="channel-acl-private-config-") as tmp:
            root = Path(tmp)
            private_root = root / "plugins" / "private" / "discord"
            private_cfg = private_root / "hooks" / "channel_acl" / "config.yaml"
            private_cfg.parent.mkdir(parents=True, exist_ok=True)
            private_cfg.write_text("channels: {}\n", encoding="utf-8")

            old_private = os.environ.get("HERMES_DISCORD_PRIVATE_DIR")
            old_config_path = _CHANNEL_ACL._CONFIG_PATH
            os.environ["HERMES_DISCORD_PRIVATE_DIR"] = str(private_root)
            try:
                # Keep runtime default path; resolver must still prefer private config.
                _CHANNEL_ACL._CONFIG_PATH = _CHANNEL_ACL._HOOK_DIR / "config.yaml"
                resolved = _CHANNEL_ACL._resolve_channel_acl_config_path()
                self.assertEqual(resolved, private_cfg)
            finally:
                _CHANNEL_ACL._CONFIG_PATH = old_config_path
                if old_private is None:
                    os.environ.pop("HERMES_DISCORD_PRIVATE_DIR", None)
                else:
                    os.environ["HERMES_DISCORD_PRIVATE_DIR"] = old_private
                _CHANNEL_ACL.clear_cache()

    def test_normalized_channel_skill_uses_label_tag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="channel-acl-label-") as tmp:
            cfg_path = Path(tmp) / "channel_acl.yaml"
            cfg_path.write_text(
                "\n".join(
                    [
                        "channels:",
                        "  '1487099467726328038':",
                        "    mode: condicionado",
                        "    model_key: nemotron120b",
                        "    allowed_commands:",
                        "      - faltas",
                        "    default_action: skill:add",
                        "    free_text_policy: auto_add",
                        "    label: loja1",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            old_config_path = _CHANNEL_ACL._CONFIG_PATH
            try:
                _CHANNEL_ACL._CONFIG_PATH = cfg_path
                _CHANNEL_ACL.clear_cache()
                action, transformed = _CHANNEL_ACL.normalize_to_channel_skill(
                    _Source(chat_id="1487099467726328038", user_id="999"),
                    "papel higienico",
                )
                self.assertEqual(action, "SKILL_ADD")
                self.assertEqual(transformed, "/faltas adicionar papel higienico")
            finally:
                _CHANNEL_ACL._CONFIG_PATH = old_config_path
                _CHANNEL_ACL.clear_cache()

    def test_enforce_access_policy_accepts_thread_parent_from_chat_id_alt(self) -> None:
        logger = _PIPELINE.Logger(op_id="test-op")
        policy = _PIPELINE.AccessPolicy(
            allowed_origin_channels={"1487099467726328038"},
            require_author_id=False,
            allowed_read_user_ids=set(),
            allowed_mutation_user_ids=set(),
        )

        with mock.patch.object(_PIPELINE, "resolve_discord_parent_channel_id", side_effect=RuntimeError("must not call")):
            _PIPELINE.enforce_access_policy(
                action="add",
                policy=policy,
                origin_channel_id="1487775038454370405",
                chat_id_alt="1487099467726328038",
                author_id="123",
                env={},
                logger=logger,
            )

    def test_enforce_access_policy_blocks_unmapped_thread_and_parent(self) -> None:
        logger = _PIPELINE.Logger(op_id="test-op-2")
        policy = _PIPELINE.AccessPolicy(
            allowed_origin_channels={"1487099467726328038"},
            require_author_id=False,
            allowed_read_user_ids=set(),
            allowed_mutation_user_ids=set(),
        )

        with self.assertRaises(_PIPELINE.PipelineError):
            _PIPELINE.enforce_access_policy(
                action="add",
                policy=policy,
                origin_channel_id="999999999999999999",
                chat_id_alt="",
                author_id="123",
                env={},
                logger=logger,
            )

    def test_enforce_access_policy_ignores_legacy_discord_allowed_threads(self) -> None:
        logger = _PIPELINE.Logger(op_id="test-op-legacy")
        with mock.patch.dict(
            os.environ,
            {
                "DISCORD_ALLOWED_THREADS": "1487775038454370405",
                "FALTAS_OPERATIONAL_CHANNEL_IDS": "1487099467726328038",
            },
            clear=False,
        ):
            policy = _PIPELINE.read_access_policy({})

            with self.assertRaises(_PIPELINE.PipelineError):
                _PIPELINE.enforce_access_policy(
                    action="add",
                    policy=policy,
                    origin_channel_id="1487775038454370405",
                    chat_id_alt="",
                    author_id="123",
                    env={},
                    logger=logger,
                )

    def test_infer_targets_list_defaults_to_both_stores_when_channel_is_unmapped(self) -> None:
        logger = _PIPELINE.Logger(op_id="test-list-fallback")

        with mock.patch.object(_PIPELINE, "resolve_discord_parent_channel_id", return_value=None):
            targets = _PIPELINE.infer_targets(
                "list",
                None,
                "999999999999999999",
                "",
                {},
                logger,
            )

        self.assertEqual(targets, ["loja1", "loja2"])

    def test_infer_targets_add_still_fails_closed_when_channel_is_unmapped(self) -> None:
        logger = _PIPELINE.Logger(op_id="test-add-fail-closed")

        with mock.patch.object(_PIPELINE, "resolve_discord_parent_channel_id", return_value=None):
            with self.assertRaises(_PIPELINE.PipelineError):
                _PIPELINE.infer_targets(
                    "add",
                    None,
                    "999999999999999999",
                    "",
                    {},
                    logger,
                )

    def test_strict_item_blocks_chatty_request_quickly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="channel-acl-strict-item-") as tmp:
            cfg_path = Path(tmp) / "channel_acl.yaml"
            cfg_path.write_text(
                "\n".join(
                    [
                        "channels:",
                        "  '1487099467726328038':",
                        "    mode: condicionado",
                        "    model_key: nemotron120b",
                        "    allowed_commands:",
                        "      - faltas",
                        "    default_action: skill:add",
                        "    free_text_policy: strict_item",
                        "    label: loja1",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            old_config_path = _CHANNEL_ACL._CONFIG_PATH
            try:
                _CHANNEL_ACL._CONFIG_PATH = cfg_path
                _CHANNEL_ACL.clear_cache()
                action, message = _CHANNEL_ACL.normalize_to_channel_skill(
                    _Source(chat_id="1487099467726328038", user_id="999"),
                    "quero saber o status da lista",
                )
                self.assertEqual(action, "BLOCK")
                self.assertIn("canal", message.lower())
            finally:
                _CHANNEL_ACL._CONFIG_PATH = old_config_path
                _CHANNEL_ACL.clear_cache()

    def test_strict_item_blocks_chatty_request_even_for_admin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="channel-acl-admin-strict-item-") as tmp:
            cfg_path = Path(tmp) / "channel_acl.yaml"
            cfg_path.write_text(
                "\n".join(
                    [
                        "channels:",
                        "  '1487099552636080201':",
                        "    mode: condicionado",
                        "    model_key: nemotron120b",
                        "    allowed_commands:",
                        "      - faltas",
                        "    default_action: skill:add",
                        "    free_text_policy: strict_item",
                        "    label: loja2",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            old_config_path = _CHANNEL_ACL._CONFIG_PATH
            try:
                _CHANNEL_ACL._CONFIG_PATH = cfg_path
                _CHANNEL_ACL.clear_cache()
                with mock.patch.object(_CHANNEL_ACL, "_source_is_admin", return_value=True) as is_admin_mock:
                    action, message = _CHANNEL_ACL.normalize_to_channel_skill(
                        _Source(chat_id="1487099552636080201", user_id="1228037612338679961"),
                        "oi",
                    )
                self.assertEqual(action, "BLOCK")
                self.assertIn("canal", message.lower())
                is_admin_mock.assert_not_called()
            finally:
                _CHANNEL_ACL._CONFIG_PATH = old_config_path
                _CHANNEL_ACL.clear_cache()

    async def test_normalized_restricted_channel_dispatch_preserves_parent_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="channel-acl-dispatch-") as tmp:
            root = Path(tmp)
            private_root = root / "plugins" / "private" / "discord"
            models_path = private_root / "models" / "orchestrator_models.json"
            users_path = private_root / "discord_users.json"
            cfg_path = root / "runtime" / "channel_acl_config.yaml"
            script_file = root / "faltas_pipeline.py"
            models_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            script_file.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

            models_path.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "key": "nemotron120b",
                                "provider": "nvidia",
                                "model": "nvidia/nemotron-3-super-120b-a12b",
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            users_path.write_text(json.dumps({"users": []}, ensure_ascii=False) + "\n", encoding="utf-8")
            cfg_path.write_text(
                "\n".join(
                    [
                        "channels:",
                        "  '1487099467726328038':",
                        "    mode: condicionado",
                        "    model_key: nemotron120b",
                        "    allowed_commands:",
                        "      - faltas",
                        "    default_action: skill:add",
                        "    label: loja1",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            old_private = os.environ.get("HERMES_DISCORD_PRIVATE_DIR")
            old_node = os.environ.get("NODE_NAME")
            os.environ["HERMES_DISCORD_PRIVATE_DIR"] = str(private_root)
            os.environ["NODE_NAME"] = "orchestrator"
            try:
                _CHANNEL_ACL._CONFIG_PATH = cfg_path
                _CHANNEL_ACL.clear_cache()

                source = _Source(
                    chat_id="1487775038454370405",
                    chat_id_alt="1487099467726328038",
                    user_id="1228037612338679961",
                    user_name="Laura",
                )
                action, transformed = _CHANNEL_ACL.normalize_to_channel_skill(source, "papel higienico")
                self.assertEqual(action, "SKILL_ADD")
                self.assertTrue(transformed.startswith("/faltas adicionar "))

                captured: list[str] = []

                async def _fake_exec(*cmd, **kwargs):
                    captured[:] = [str(part) for part in cmd]
                    payload = {
                        "ok": True,
                        "data": {"stores": {"loja1": {"added": [["papel higienico", 1]], "incremented": []}}},
                    }
                    return _FakeProc(stdout=json.dumps(payload, ensure_ascii=False))

                with mock.patch.object(_CHANNEL_ACL, "_resolve_faltas_pipeline_script", return_value=script_file), \
                    mock.patch.object(_CHANNEL_ACL, "_resolve_python_bin", return_value="/usr/bin/python3"), \
                    mock.patch.object(_CHANNEL_ACL.asyncio, "create_subprocess_exec", side_effect=_fake_exec):
                    handled, reply = await _CHANNEL_ACL.dispatch_normalized_command(source, transformed)

                self.assertTrue(handled)
                self.assertIn("--origin-channel-id", captured)
                self.assertIn("1487775038454370405", captured)
                self.assertIn("--chat-id-alt", captured)
                self.assertIn("1487099467726328038", captured)
                self.assertIn("--loja", captured)
                self.assertIn("loja1", captured)
                self.assertIn("Item processado", reply)
                self.assertIn("loja:`1`", reply)
                self.assertIn("nome:`papel higienico`", reply)
                self.assertNotIn("papel higienico loja1", captured)
            finally:
                if old_private is None:
                    os.environ.pop("HERMES_DISCORD_PRIVATE_DIR", None)
                else:
                    os.environ["HERMES_DISCORD_PRIVATE_DIR"] = old_private
                if old_node is None:
                    os.environ.pop("NODE_NAME", None)
                else:
                    os.environ["NODE_NAME"] = old_node
                _CHANNEL_ACL.clear_cache()


if __name__ == "__main__":
    unittest.main()
