from __future__ import annotations

import importlib.util
import inspect
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


_RUNTIME_PATH = Path("/local/plugins/public/discord/hooks/discord_slash_bridge/runtime.py")
_SPEC = importlib.util.spec_from_file_location("discord_slash_runtime_acl_autocomplete_test", _RUNTIME_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"failed to load runtime module from {_RUNTIME_PATH}")
_RUNTIME = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RUNTIME)


class _FakeTree:
    def __init__(self) -> None:
        self.added_groups: list[object] = []

    def remove_command(self, name, *args, **kwargs):
        del name, args, kwargs
        return None

    def add_command(self, group):
        self.added_groups.append(group)


class _FakeAdapter:
    def __init__(self) -> None:
        self._client = object()


def _write_hook_dir(base: Path) -> Path:
    hook_dir = base / "hooks" / "discord_slash_bridge"
    hook_dir.mkdir(parents=True, exist_ok=True)

    public_hook = Path("/local/plugins/public/discord/hooks/discord_slash_bridge")
    for name in ("handlers.py", "role_acl.py"):
        src = public_hook / name
        (hook_dir / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    (hook_dir / "config.yaml").write_text("{}\n", encoding="utf-8")
    (hook_dir / "registry.yaml").write_text("version: 1\nnative_overrides: {}\n", encoding="utf-8")
    return hook_dir


class _Choice:
    def __init__(self, name: str, value: str) -> None:
        self.name = name
        self.value = value


class _Group:
    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description
        self.commands: dict[str, object] = {}

    def command(self, name: str, description: str = ""):
        del description

        def _decorator(fn):
            self.commands[name] = fn
            return fn

        return _decorator


class _AppCommands:
    Choice = _Choice
    Group = _Group

    @staticmethod
    def describe(**kwargs):
        def _decorator(fn):
            setattr(fn, "__describe__", dict(kwargs))
            return fn

        return _decorator

    @staticmethod
    def choices(**kwargs):
        def _decorator(fn):
            setattr(fn, "__choices__", dict(kwargs))
            return fn

        return _decorator

    @staticmethod
    def autocomplete(**kwargs):
        def _decorator(fn):
            setattr(fn, "__autocomplete__", dict(kwargs))
            return fn

        return _decorator


class RuntimeAclAutocompleteTests(unittest.TestCase):
    def test_acl_channel_uses_label_and_autocomplete_hooks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discord-acl-autocomplete-") as tmp:
            hook_dir = _write_hook_dir(Path(tmp))
            runtime = _RUNTIME.DiscordSlashRuntime(_FakeAdapter(), hook_dir=hook_dir)
            tree = _FakeTree()
            fake_discord = types.SimpleNamespace(app_commands=_AppCommands, AppCommandType=types.SimpleNamespace(chat_input=1))

            with mock.patch.dict("sys.modules", {"discord": fake_discord}):
                runtime._bootstrap_acl(tree, {"enabled": True})

            self.assertTrue(tree.added_groups)
            group = tree.added_groups[0]
            channel_fn = group.commands["channel"]
            command_fn = group.commands["command"]

            sig = inspect.signature(channel_fn)
            self.assertIn("label", sig.parameters)
            self.assertNotIn("store", sig.parameters)

            channel_autocomplete = getattr(channel_fn, "__autocomplete__", {})
            self.assertIn("model_key", channel_autocomplete)
            self.assertIn("allowed_commands", channel_autocomplete)
            self.assertIn("allowed_skills", channel_autocomplete)
            self.assertIn("always_allowed_commands", channel_autocomplete)
            self.assertIn("default_action", channel_autocomplete)
            self.assertIn("free_text_policy", channel_autocomplete)
            self.assertIn("label", channel_autocomplete)

            command_autocomplete = getattr(command_fn, "__autocomplete__", {})
            self.assertIn("command", command_autocomplete)
            self.assertIn("role", command_autocomplete)


if __name__ == "__main__":
    unittest.main()
