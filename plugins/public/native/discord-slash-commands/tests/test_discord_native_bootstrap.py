from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
import types


PACKAGE_ROOT = Path("/local/plugins/public/native/discord-slash-commands")


def _install_fake_discord():
    discord_mod = SimpleNamespace()

    class _FakeCommand:
        def __init__(self, *, name, description, callback, parent=None):
            self.name = name
            self.description = description
            self.callback = callback
            self.parent = parent

    def _decorator(**_kwargs):
        def _wrap(fn):
            return fn
        return _wrap

    discord_mod.Interaction = object
    discord_mod.app_commands = SimpleNamespace(
        describe=_decorator,
        choices=_decorator,
        Choice=lambda **kwargs: SimpleNamespace(**kwargs),
        Command=_FakeCommand,
    )
    sys.modules["discord"] = discord_mod


def _load_runtime():
    _install_fake_discord()
    package_name = "discord_slash_commands_native_bootstrap_testpkg"
    for key in list(sys.modules):
        if key == package_name or key.startswith(package_name + "."):
            sys.modules.pop(key, None)
    spec = importlib.util.spec_from_file_location(
        package_name,
        PACKAGE_ROOT / "__init__.py",
        submodule_search_locations=[str(PACKAGE_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load slash plugin package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    spec.loader.exec_module(module)
    return importlib.import_module(f"{package_name}.runtime")


class _FakeTree:
    def __init__(self):
        self.commands = {}

    def add_command(self, cmd):
        self.commands[cmd.name] = cmd

    def remove_command(self, name):
        self.commands.pop(name, None)


def test_bootstrap_tree_registers_structured_metricas_and_faltas():
    runtime = _load_runtime()
    dispatched = []

    async def _fake_run(_interaction, command_text, followup_msg=None):
        dispatched.append((command_text, followup_msg))

    adapter = SimpleNamespace(_run_simple_slash=_fake_run)
    tree = _FakeTree()

    bridge = runtime.NativeDiscordSlashRuntime(adapter)
    bridge.bootstrap_tree(tree)

    assert set(tree.commands) == {"metricas", "faltas"}

    asyncio.run(tree.commands["faltas"].callback(SimpleNamespace(), action="listar", loja="loja1", formato="links"))
    asyncio.run(tree.commands["metricas"].callback(SimpleNamespace(), formato="json", dias=7, skill="colmeio"))

    assert dispatched == [
        ("/faltas action:listar loja:loja1 formato:links", None),
        ("/metricas formato:json dias:7 skill:colmeio", None),
    ]


def test_build_faltas_command_text_quotes_items_when_needed():
    runtime = _load_runtime()

    command_text = runtime._build_faltas_command_text(
        action="adicionar",
        itens="banana prata",
        loja="loja2",
    )

    assert command_text == '/faltas action:adicionar loja:loja2 itens:"banana prata"'


def test_runtime_bridge_wraps_discord_adapter_register_slash_commands():
    runtime = _load_runtime()

    previous_gateway = sys.modules.get("gateway")
    previous_platforms = sys.modules.get("gateway.platforms")
    previous_discord_platform = sys.modules.get("gateway.platforms.discord")

    gateway_module = types.ModuleType("gateway")
    platforms_module = types.ModuleType("gateway.platforms")
    discord_platform_module = types.ModuleType("gateway.platforms.discord")

    calls = []

    class _FakeAdapter:
        def __init__(self):
            self._client = SimpleNamespace(tree=_FakeTree())

        def _register_slash_commands(self):
            calls.append("original")
            self._client.tree.add_command(SimpleNamespace(name="metricas", callback=None))
            self._client.tree.add_command(SimpleNamespace(name="faltas", callback=None))

    discord_platform_module.DiscordAdapter = _FakeAdapter
    gateway_module.platforms = platforms_module
    platforms_module.discord = discord_platform_module
    try:
        sys.modules["gateway"] = gateway_module
        sys.modules["gateway.platforms"] = platforms_module
        sys.modules["gateway.platforms.discord"] = discord_platform_module

        runtime._install_discord_adapter_runtime_bridge()

        adapter = _FakeAdapter()
        adapter._register_slash_commands()

        assert calls == ["original"]
        assert set(adapter._client.tree.commands) == {"metricas", "faltas"}
        assert adapter._client.tree.commands["faltas"].callback is not None
    finally:
        if previous_gateway is None:
            sys.modules.pop("gateway", None)
        else:
            sys.modules["gateway"] = previous_gateway
        if previous_platforms is None:
            sys.modules.pop("gateway.platforms", None)
        else:
            sys.modules["gateway.platforms"] = previous_platforms
        if previous_discord_platform is None:
            sys.modules.pop("gateway.platforms.discord", None)
        else:
            sys.modules["gateway.platforms.discord"] = previous_discord_platform
