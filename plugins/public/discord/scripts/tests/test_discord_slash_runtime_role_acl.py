from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


_RUNTIME_CANDIDATES = (
    Path("/local/plugins/public/discord/hooks/discord_slash_bridge/runtime.py"),
)
_RUNTIME_PATH = next((p for p in _RUNTIME_CANDIDATES if p.exists()), _RUNTIME_CANDIDATES[0])

_SPEC = importlib.util.spec_from_file_location("discord_slash_runtime_acl_test_module", _RUNTIME_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"failed to load runtime module from {_RUNTIME_PATH}")
_RUNTIME = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RUNTIME)


class _FakeResponse:
    def __init__(self) -> None:
        self.done = False
        self.messages: list[str] = []

    def is_done(self) -> bool:
        return self.done

    async def send_message(self, content: str, ephemeral: bool = False) -> None:
        self.done = True
        self.messages.append(content)

    async def defer(self, ephemeral: bool = False) -> None:
        self.done = True


class _FakeFollowup:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, content: str, ephemeral: bool = False) -> None:
        self.messages.append(content)


class _FakeRole:
    def __init__(self, role_id: str, name: str):
        self.id = int(role_id)
        self.name = name


class _FakeUser:
    def __init__(self, user_id: str, role_pairs: list[tuple[str, str]]):
        self.id = int(user_id)
        self.display_name = f"u{user_id}"
        self.roles = [_FakeRole(rid, name) for rid, name in role_pairs]


class _FakeGuild:
    def __init__(self, guild_id: str):
        self.id = int(guild_id)


class _FakeInteraction:
    def __init__(self, *, command_name: str, role_pairs: list[tuple[str, str]]):
        self.type = 2
        self.data = {"type": 1, "name": command_name, "options": []}
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()
        self.id = 123
        self.guild = _FakeGuild("123")
        self.user = _FakeUser("999", role_pairs)
        self.channel = object()
        self.channel_id = 55


class _FakeTree:
    def __init__(self, known_commands: set[str] | None = None):
        self.known_commands = set(known_commands or set())
        self._interaction_check_cb = None

    def interaction_check(self, fn):
        self._interaction_check_cb = fn
        return fn

    def remove_command(self, *args, **kwargs):
        return None

    def command(self, *args, **kwargs):
        def _decorator(fn):
            return fn

        return _decorator

    def get_command(self, name: str, guild=None):
        if str(name or "") in self.known_commands:
            return object()
        return None


class _FakeAdapter:
    def __init__(self, known_commands: set[str] | None = None):
        self._client = type("Client", (), {"tree": _FakeTree(known_commands=known_commands or set())})()
        self.dispatched: list[str] = []

    def _build_slash_event(self, interaction, text: str):
        return type("Event", (), {"text": text})()

    async def handle_message(self, event):
        self.dispatched.append(str(getattr(event, "text", "")))


class RuntimeRoleAclTests(unittest.IsolatedAsyncioTestCase):
    def _write_acl(self, private_root: Path, *, mapped: dict[str, str]) -> Path:
        path = private_root / "acl" / "orchestrator_acl.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "node": "orchestrator",
            "guild_id": "123",
            "hierarchy": [
                {"role_id": "10", "role_name": "admin"},
                {"role_id": "@everyone", "role_name": "@everyone"},
            ],
            "commands": {cmd: {"min_role": role} for cmd, role in mapped.items()},
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _write_hook_dir(self, root: Path) -> Path:
        hook_dir = root / "hooks" / "discord_slash_bridge"
        hook_dir.mkdir(parents=True, exist_ok=True)
        public_hook = Path("/local/plugins/public/discord/hooks/discord_slash_bridge")
        for name in ("runtime.py", "handlers.py", "role_acl.py"):
            src = public_hook / name
            (hook_dir / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        (hook_dir / "config.yaml").write_text("{}\n", encoding="utf-8")
        (hook_dir / "registry.yaml").write_text(
            "\n".join(
                [
                    "version: 1",
                    "native_overrides:",
                    "  restart: {enabled: false}",
                    "  reboot: {enabled: false}",
                    "  metricas: {enabled: false}",
                    "  backup: {enabled: false}",
                    "  model: {enabled: false}",
                    "  acl: {enabled: false}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return hook_dir

    async def test_tree_interaction_check_blocks_known_command_when_unmapped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-runtime-acl-") as tmp:
            private_root = Path(tmp) / "plugins" / "private" / "discord"
            self._write_acl(private_root, mapped={"status": "@everyone"})

            old_private = os.environ.get("HERMES_DISCORD_PRIVATE_DIR")
            old_node = os.environ.get("NODE_NAME")
            os.environ["HERMES_DISCORD_PRIVATE_DIR"] = str(private_root)
            os.environ["NODE_NAME"] = "orchestrator"
            try:
                adapter = _FakeAdapter(known_commands={"reboot"})
                hook_dir = self._write_hook_dir(Path(tmp))
                runtime = _RUNTIME.DiscordSlashRuntime(
                    adapter,
                    hook_dir=hook_dir,
                )
                tree = adapter._client.tree
                runtime.bootstrap_tree(tree)

                self.assertIsNotNone(tree._interaction_check_cb)
                interaction = _FakeInteraction(command_name="reboot", role_pairs=[])
                allowed = await tree._interaction_check_cb(interaction)

                self.assertFalse(allowed)
                self.assertTrue(interaction.response.messages)
                self.assertIn("não está mapeado", interaction.response.messages[0])
            finally:
                if old_private is None:
                    os.environ.pop("HERMES_DISCORD_PRIVATE_DIR", None)
                else:
                    os.environ["HERMES_DISCORD_PRIVATE_DIR"] = old_private
                if old_node is None:
                    os.environ.pop("NODE_NAME", None)
                else:
                    os.environ["NODE_NAME"] = old_node

    async def test_tree_interaction_check_allows_admin_bypass_for_unmapped_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-runtime-acl-") as tmp:
            private_root = Path(tmp) / "plugins" / "private" / "discord"
            self._write_acl(private_root, mapped={"status": "@everyone"})

            old_private = os.environ.get("HERMES_DISCORD_PRIVATE_DIR")
            old_node = os.environ.get("NODE_NAME")
            os.environ["HERMES_DISCORD_PRIVATE_DIR"] = str(private_root)
            os.environ["NODE_NAME"] = "orchestrator"
            try:
                adapter = _FakeAdapter(known_commands={"reboot"})
                hook_dir = self._write_hook_dir(Path(tmp))
                runtime = _RUNTIME.DiscordSlashRuntime(
                    adapter,
                    hook_dir=hook_dir,
                )
                tree = adapter._client.tree
                runtime.bootstrap_tree(tree)

                self.assertIsNotNone(tree._interaction_check_cb)
                interaction = _FakeInteraction(command_name="reboot", role_pairs=[("10", "admin")])
                allowed = await tree._interaction_check_cb(interaction)

                self.assertTrue(allowed)
            finally:
                if old_private is None:
                    os.environ.pop("HERMES_DISCORD_PRIVATE_DIR", None)
                else:
                    os.environ["HERMES_DISCORD_PRIVATE_DIR"] = old_private
                if old_node is None:
                    os.environ.pop("NODE_NAME", None)
                else:
                    os.environ["NODE_NAME"] = old_node

    async def test_bridge_dispatch_is_guarded_by_role_acl(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-runtime-acl-") as tmp:
            private_root = Path(tmp) / "plugins" / "private" / "discord"
            self._write_acl(private_root, mapped={"clean": "@everyone"})

            hook_dir = Path(tmp) / "hooks" / "discord_slash_bridge"
            hook_dir.mkdir(parents=True, exist_ok=True)
            for name in ("runtime.py", "handlers.py", "role_acl.py"):
                src = Path("/local/plugins/public/discord/hooks/discord_slash_bridge") / name
                (hook_dir / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            (hook_dir / "config.yaml").write_text("{}\n", encoding="utf-8")
            (hook_dir / "registry.yaml").write_text(
                "\n".join(
                    [
                        "version: 1",
                        "native_overrides:",
                        "  restart: {enabled: false}",
                        "  reboot: {enabled: false}",
                        "  metricas: {enabled: false}",
                        "  backup: {enabled: false}",
                        "  model: {enabled: false}",
                        "slash_bridge:",
                        "  commands:",
                        "    clean:",
                        "      dispatch: clean",
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
                adapter = _FakeAdapter(known_commands=set())
                runtime = _RUNTIME.DiscordSlashRuntime(adapter, hook_dir=hook_dir)
                interaction = _FakeInteraction(command_name="clean", role_pairs=[])

                handled = await runtime.on_interaction(interaction)
                self.assertTrue(handled)
                self.assertEqual(adapter.dispatched, ["/clean"])
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
