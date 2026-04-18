from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


_RUNTIME_CANDIDATES = (
    Path("/local/plugins/public/discord/hooks/discord_slash_bridge/runtime.py"),
)
_RUNTIME_PATH = next((p for p in _RUNTIME_CANDIDATES if p.exists()), _RUNTIME_CANDIDATES[0])

_SPEC = importlib.util.spec_from_file_location("discord_slash_runtime_payload_test_module", _RUNTIME_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"failed to load runtime module from {_RUNTIME_PATH}")
_RUNTIME = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RUNTIME)


class _FakeRoute:
    def __init__(self, method: str, path: str, **kwargs):
        self.method = method
        self.path = path
        self.kwargs = kwargs


class _FakeHTTP:
    def __init__(self, existing_commands: list[dict[str, str]]):
        self._existing = list(existing_commands)
        self._id_to_name = {str(entry.get("id")): str(entry.get("name")) for entry in self._existing}
        self.posted_names: list[str] = []
        self.deleted_names: list[str] = []

    async def request(self, route, json=None):
        method = str(getattr(route, "method", "")).upper()
        if method == "GET":
            return list(self._existing)
        if method == "POST":
            name = str((json or {}).get("name") or "")
            if name:
                self.posted_names.append(name)
            return {"id": f"new-{name}"}
        if method == "DELETE":
            command_id = str(getattr(route, "kwargs", {}).get("command_id") or "")
            name = self._id_to_name.get(command_id, "")
            if name:
                self.deleted_names.append(name)
            return None
        raise RuntimeError(f"unexpected HTTP method: {method}")


class _FakeGuild:
    def __init__(self, guild_id: int):
        self.id = guild_id


class _FakeTree:
    def __init__(self):
        self.removed: list[str] = []
        self._interaction_check_cb = None

    def interaction_check(self, fn):
        self._interaction_check_cb = fn
        return fn

    def remove_command(self, name, *args, **kwargs):
        self.removed.append(str(name))
        return None

    def command(self, *args, **kwargs):
        def _decorator(fn):
            return fn

        return _decorator


class _FakeClient:
    def __init__(self, existing_commands: list[dict[str, str]]):
        self.tree = _FakeTree()
        self.guilds = [_FakeGuild(123)]
        self.application_id = "999"
        self.user = types.SimpleNamespace(id=999)
        self.http = _FakeHTTP(existing_commands=existing_commands)


class _FakeAdapter:
    def __init__(self, existing_commands: list[dict[str, str]]):
        self._client = _FakeClient(existing_commands=existing_commands)


def _write_hook_dir(base: Path, registry_text: str) -> Path:
    hook_dir = base / "hooks" / "discord_slash_bridge"
    hook_dir.mkdir(parents=True, exist_ok=True)

    public_hook = Path("/local/plugins/public/discord/hooks/discord_slash_bridge")
    for name in ("handlers.py", "role_acl.py"):
        src = public_hook / name
        (hook_dir / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    (hook_dir / "config.yaml").write_text("{}\n", encoding="utf-8")
    (hook_dir / "registry.yaml").write_text(registry_text, encoding="utf-8")
    return hook_dir


class RuntimePayloadHygieneTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_external_payload_skips_native_duplicates_and_prunes_skill(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-runtime-payload-") as tmp:
            tmp_path = Path(tmp)
            payload_path = tmp_path / "commands.json"
            payload_path.write_text(
                json.dumps(
                    [
                        {"name": "metricas", "description": "dup native", "type": 1},
                        {"name": "faltas", "description": "bridge", "type": 1},
                        {"name": "skill", "description": "should-hide", "type": 1},
                        {"name": "faltas", "description": "duplicate payload", "type": 1},
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            hook_dir = _write_hook_dir(
                tmp_path,
                "\n".join(
                    [
                        "version: 1",
                        "native_overrides:",
                        "  metricas: {enabled: true}",
                        "slash_bridge:",
                        "  hide_skill_group: true",
                        "",
                    ]
                ),
            )

            adapter = _FakeAdapter(
                existing_commands=[
                    {"id": "11", "name": "metricas"},
                    {"id": "12", "name": "skill"},
                    {"id": "13", "name": "faltas"},
                ]
            )
            runtime = _RUNTIME.DiscordSlashRuntime(adapter, hook_dir=hook_dir)

            fake_discord = types.SimpleNamespace(http=types.SimpleNamespace(Route=_FakeRoute))
            with mock.patch.dict("sys.modules", {"discord": fake_discord}):
                old_commands_file = os.environ.get("DISCORD_COMMANDS_FILE")
                os.environ["DISCORD_COMMANDS_FILE"] = str(payload_path)
                try:
                    created = await runtime.sync_external_payload_commands()
                finally:
                    if old_commands_file is None:
                        os.environ.pop("DISCORD_COMMANDS_FILE", None)
                    else:
                        os.environ["DISCORD_COMMANDS_FILE"] = old_commands_file

            self.assertEqual(created, 1)
            self.assertEqual(adapter._client.http.posted_names, ["faltas"])
            self.assertEqual(set(adapter._client.http.deleted_names), {"metricas", "skill"})

    async def test_bootstrap_tree_removes_skill_when_hide_skill_group_enabled(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-runtime-payload-") as tmp:
            tmp_path = Path(tmp)
            hook_dir = _write_hook_dir(
                tmp_path,
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
                        "  hide_skill_group: true",
                        "",
                    ]
                ),
            )

            adapter = _FakeAdapter(existing_commands=[])
            runtime = _RUNTIME.DiscordSlashRuntime(adapter, hook_dir=hook_dir)
            tree = adapter._client.tree

            runtime.bootstrap_tree(tree)

            self.assertIn("skill", tree.removed)


if __name__ == "__main__":
    unittest.main()
