from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml


PACKAGE_ROOT = Path("/local/plugins/discord-slash-commands")
REGISTER_SCRIPT = PACKAGE_ROOT / "scripts" / "register_guild_plugin_commands.py"


def _load_package():
    package_name = "canonical_discord_slash_package_testpkg"
    for key in list(sys.modules):
        if key == package_name or key.startswith(package_name + "."):
            sys.modules.pop(key, None)
    spec = importlib.util.spec_from_file_location(
        package_name,
        PACKAGE_ROOT / "__init__.py",
        submodule_search_locations=[str(PACKAGE_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load canonical slash plugin package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    spec.loader.exec_module(module)
    return module


def _seed_cache(tmp_path: Path) -> Path:
    cache_root = tmp_path / "workspace" / "plugins" / "discord-slash-commands" / "cache"
    (cache_root / "catalogs").mkdir(parents=True, exist_ok=True)
    (cache_root / "state").mkdir(parents=True, exist_ok=True)
    (cache_root / "catalogs" / "custom_commands.json").write_text(
        json.dumps(
            [
                {"name": "faltas", "namespace": "custom", "description": "Gerenciar lista de faltas das lojas", "type": 1},
                {"name": "metricas", "namespace": "custom", "description": "Dashboard de métricas Colmeio (somente admin)", "type": 1},
            ]
        ),
        encoding="utf-8",
    )
    (cache_root / "state" / "app_scope.json").write_text(
        json.dumps(
            {
                "version": 1,
                "app_id": "app-1",
                "guild_id": "guild-1",
                "enabled_commands": ["acl", "slash", "status"],
                "updated_at": "2026-04-25T00:00:00Z",
                "updated_by_node": "colmeio",
            }
        ),
        encoding="utf-8",
    )
    (cache_root / "state" / "node_activation.json").write_text(
        json.dumps({"version": 1, "node_name": "colmeio", "custom_enabled": [], "updated_at": "2026-04-25T00:00:00Z"}),
        encoding="utf-8",
    )
    return cache_root


def test_package_entrypoint_registers_canonical_runtime(monkeypatch, tmp_path):
    _seed_cache(tmp_path)
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(tmp_path / "workspace" / "plugins" / "discord-slash-commands" / "cache"))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    module = _load_package()

    commands = []
    hooks = []

    class _FakeCtx:
        def register_command(self, name, handler, description="", args_hint=""):
            commands.append(name)

        def register_hook(self, name, callback):
            hooks.append(name)

    module.register(_FakeCtx())

    assert commands == ["metricas", "faltas", "acl", "clean", "scientific-paper-meta-analysis", "slash"]
    assert hooks == ["pre_gateway_dispatch"]


def test_plugin_metadata_matches_canonical_runtime_contract():
    plugin_yaml = yaml.safe_load((PACKAGE_ROOT / "plugin.yaml").read_text(encoding="utf-8"))

    assert plugin_yaml["name"] == "discord-slash-commands"
    assert plugin_yaml["provides_hooks"] == ["pre_gateway_dispatch"]


def test_canonical_register_script_lives_with_slash_plugin():
    assert REGISTER_SCRIPT.exists()
