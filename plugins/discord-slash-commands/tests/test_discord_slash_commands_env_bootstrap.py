from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


PLUGIN_ROOT = Path("/local/plugins/discord-slash-commands")
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import discord_slash_commands_env_bootstrap as bootstrap


def _plugin_source(tmp_path: Path) -> Path:
    plugin = tmp_path / "discord-slash-commands-source"
    plugin.mkdir()
    (plugin / "plugin.yaml").write_text("name: discord-slash-commands\n", encoding="utf-8")
    (plugin / "__init__.py").write_text("def register(ctx):\n    return None\n", encoding="utf-8")
    return plugin


def _seed_legacy_root(root: Path, *, node_name: str, with_custom: bool) -> None:
    (root / "acl").mkdir(parents=True, exist_ok=True)
    (root / "models").mkdir(parents=True, exist_ok=True)
    (root / "hooks" / "channel_acl").mkdir(parents=True, exist_ok=True)
    commands_dir = root / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    if with_custom:
        commands_payload = [
            {"name": "faltas", "description": "Gerenciar lista de faltas das lojas", "type": 1},
            {"name": "metricas", "description": "Dashboard de métricas Colmeio (somente admin)", "type": 1},
        ]
        (commands_dir / f"{node_name}.json").write_text(json.dumps(commands_payload), encoding="utf-8")

    (root / "acl" / f"{node_name}_acl.json").write_text(
        json.dumps({"version": 1, "node": node_name, "commands": {"status": {"min_role": "@everyone"}}}),
        encoding="utf-8",
    )
    (root / "models" / f"{node_name}_models.json").write_text(
        json.dumps({"version": 1, "node": node_name, "models": [{"key": "nemotron120b", "provider": "nvidia", "model": "nvidia/nemotron-3-super-120b-a12b"}]}),
        encoding="utf-8",
    )
    (root / "hooks" / "channel_acl" / "config.yaml").write_text("channels: {}\n", encoding="utf-8")
    (root / "discord_users.json").write_text('{"users":[]}\n', encoding="utf-8")


def test_bootstrap_enabled_moves_state_into_node_cache_and_updates_env(monkeypatch, tmp_path, capsys):
    env_root = tmp_path / "agents" / "envs"
    env_root.mkdir(parents=True)
    env_file = env_root / "colmeio.env"
    config_file = tmp_path / "config.yaml"
    plugin_source = _plugin_source(tmp_path)
    legacy_root = tmp_path / "plugins" / "private" / "discord"
    _seed_legacy_root(legacy_root, node_name="colmeio", with_custom=True)

    env_file.write_text(
        "\n".join(
            [
                "PLUGIN_DISCORD_SLASH_COMMANDS=true",
                "DISCORD_APP_ID=app-1",
                "DISCORD_SERVER_ID=guild-1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_file.write_text(yaml.safe_dump({"plugins": {"enabled": ["discord-governance"]}}), encoding="utf-8")

    monkeypatch.setattr(bootstrap, "DEFAULT_LEGACY_PRIVATE_DISCORD_ROOT", legacy_root)
    monkeypatch.setattr(bootstrap, "_infer_host_node_root", lambda _env_file, _node_name: tmp_path / "agents" / "nodes" / "colmeio")
    monkeypatch.setattr(
        bootstrap,
        "_host_cache_root",
        lambda node_name: tmp_path / "agents" / "nodes" / node_name / "workspace" / "plugins" / "discord-slash-commands" / "cache",
    )
    monkeypatch.setattr(bootstrap, "_peer_nodes_for_scope", lambda app_id, guild_id: ["colmeio", "orchestrator"])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "discord_slash_commands_env_bootstrap.py",
            "--env-file",
            str(env_file),
            "--config-file",
            str(config_file),
            "--plugin-source",
            str(plugin_source),
        ],
    )

    assert bootstrap.main() == 0
    payload = json.loads(capsys.readouterr().out.strip())

    cache_root = tmp_path / "agents" / "nodes" / "colmeio" / "workspace" / "plugins" / "discord-slash-commands" / "cache"
    mirrored_scope = tmp_path / "agents" / "nodes" / "orchestrator" / "workspace" / "plugins" / "discord-slash-commands" / "cache" / "state" / "app_scope.json"
    env_text = env_file.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    custom_catalog = json.loads((cache_root / "catalogs" / "custom_commands.json").read_text(encoding="utf-8"))
    acl_payload = json.loads((cache_root / "governance" / "acl.json").read_text(encoding="utf-8"))
    node_activation = json.loads((cache_root / "state" / "node_activation.json").read_text(encoding="utf-8"))
    app_scope = json.loads((cache_root / "state" / "app_scope.json").read_text(encoding="utf-8"))

    assert payload["enabled"] is True
    assert payload["mirrored_scope_nodes"] == ["colmeio", "orchestrator"]
    assert "discord-slash-commands" in cfg["plugins"]["enabled"]
    assert "discord-governance" not in cfg["plugins"]["enabled"]
    assert sorted(item["name"] for item in custom_catalog) == ["faltas", "metricas"]
    assert node_activation["custom_enabled"] == ["faltas", "metricas"]
    assert set(app_scope["enabled_commands"]) == {"acl", "clean", "faltas", "metricas", "model", "slash", "status"}
    assert acl_payload["commands"]["clean"]["min_role"] == "admin"
    assert mirrored_scope.exists()
    assert (cache_root / "governance" / "acl" / "colmeio_acl.json").is_symlink()
    assert (cache_root / "governance" / "hooks" / "channel_acl" / "config.yaml").is_symlink()


def test_scope_payload_for_node_restores_custom_commands_from_node_activation(monkeypatch, tmp_path):
    cache_root = tmp_path / "agents" / "nodes" / "colmeio" / "workspace" / "plugins" / "discord-slash-commands" / "cache"
    (cache_root / "state").mkdir(parents=True, exist_ok=True)
    (cache_root / "state" / "app_scope.json").write_text(
        json.dumps(
            {
                "version": 1,
                "app_id": "app-1",
                "guild_id": "guild-1",
                "enabled_commands": ["acl", "slash", "status"],
                "updated_at": "2026-04-27T11:59:00Z",
                "updated_by_node": "colmeio",
            }
        ),
        encoding="utf-8",
    )
    (cache_root / "state" / "node_activation.json").write_text(
        json.dumps(
            {
                "version": 1,
                "node_name": "colmeio",
                "custom_enabled": ["metricas"],
                "updated_at": "2026-04-27T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        bootstrap,
        "_host_cache_root",
        lambda node_name: tmp_path / "agents" / "nodes" / node_name / "workspace" / "plugins" / "discord-slash-commands" / "cache",
    )

    payload = bootstrap._scope_payload_for_node("colmeio")

    assert set(payload["enabled_commands"]) == {"acl", "clean", "metricas", "model", "slash", "status"}


def test_bootstrap_migrates_old_hermes_cache_to_workspace(monkeypatch, tmp_path, capsys):
    env_root = tmp_path / "agents" / "envs"
    env_root.mkdir(parents=True)
    env_file = env_root / "colmeio.env"
    config_file = tmp_path / "config.yaml"
    plugin_source = _plugin_source(tmp_path)
    host_node_root = tmp_path / "agents" / "nodes" / "colmeio"
    old_cache = host_node_root / ".hermes" / "discord-slash-commands" / "cache"
    (old_cache / "state").mkdir(parents=True, exist_ok=True)
    (old_cache / "state" / "node_activation.json").write_text(
        json.dumps({"version": 1, "node_name": "colmeio", "custom_enabled": ["metricas"]}),
        encoding="utf-8",
    )

    env_file.write_text(
        "PLUGIN_DISCORD_SLASH_COMMANDS=true\nDISCORD_APP_ID=app-1\nDISCORD_SERVER_ID=guild-1\n",
        encoding="utf-8",
    )
    config_file.write_text(yaml.safe_dump({"plugins": {"enabled": []}}), encoding="utf-8")

    monkeypatch.setattr(bootstrap, "_infer_host_node_root", lambda _env_file, _node_name: host_node_root)
    monkeypatch.setattr(bootstrap, "_peer_nodes_for_scope", lambda app_id, guild_id: ["colmeio"])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "discord_slash_commands_env_bootstrap.py",
            "--env-file",
            str(env_file),
            "--config-file",
            str(config_file),
            "--plugin-source",
            str(plugin_source),
        ],
    )

    assert bootstrap.main() == 0
    payload = json.loads(capsys.readouterr().out.strip())

    new_cache = host_node_root / "workspace" / "plugins" / "discord-slash-commands" / "cache"
    assert payload["migrated_hermes_cache"] is True
    assert (new_cache / "state" / "node_activation.json").exists()


def test_bootstrap_governance_alias_enables_canonical_plugin(monkeypatch, tmp_path, capsys):
    env_root = tmp_path / "agents" / "envs"
    env_root.mkdir(parents=True)
    env_file = env_root / "orchestrator.env"
    config_file = tmp_path / "config.yaml"
    plugin_source = _plugin_source(tmp_path)
    legacy_root = tmp_path / "plugins" / "private" / "discord"
    _seed_legacy_root(legacy_root, node_name="orchestrator", with_custom=False)

    env_file.write_text(
        "\n".join(
            [
                "PLUGIN_DISCORD_GOVERNANCE=true",
                "DISCORD_APP_ID=app-1",
                "DISCORD_SERVER_ID=guild-1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_file.write_text(yaml.safe_dump({"plugins": {"enabled": []}}), encoding="utf-8")

    monkeypatch.setattr(bootstrap, "DEFAULT_LEGACY_PRIVATE_DISCORD_ROOT", legacy_root)
    monkeypatch.setattr(bootstrap, "_infer_host_node_root", lambda _env_file, _node_name: tmp_path / "agents" / "nodes" / "orchestrator")
    monkeypatch.setattr(
        bootstrap,
        "_host_cache_root",
        lambda node_name: tmp_path / "agents" / "nodes" / node_name / "workspace" / "plugins" / "discord-slash-commands" / "cache",
    )
    monkeypatch.setattr(bootstrap, "_peer_nodes_for_scope", lambda app_id, guild_id: ["orchestrator"])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "discord_slash_commands_env_bootstrap.py",
            "--env-file",
            str(env_file),
            "--config-file",
            str(config_file),
            "--plugin-source",
            str(plugin_source),
        ],
    )

    assert bootstrap.main() == 0
    payload = json.loads(capsys.readouterr().out.strip())

    cfg = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert payload["enabled_via_deprecated_governance_flag"] is True
    assert "discord-slash-commands" in cfg["plugins"]["enabled"]


def test_bootstrap_fresh_node_defaults_custom_to_disabled(monkeypatch, tmp_path, capsys):
    env_root = tmp_path / "agents" / "envs"
    env_root.mkdir(parents=True)
    env_file = env_root / "paracelsus.env"
    config_file = tmp_path / "config.yaml"
    plugin_source = _plugin_source(tmp_path)
    legacy_root = tmp_path / "plugins" / "private" / "discord"
    _seed_legacy_root(legacy_root, node_name="paracelsus", with_custom=False)

    env_file.write_text(
        "\n".join(
            [
                "PLUGIN_DISCORD_SLASH_COMMANDS=true",
                "DISCORD_APP_ID=app-9",
                "DISCORD_SERVER_ID=guild-9",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_file.write_text(yaml.safe_dump({"plugins": {"enabled": []}}), encoding="utf-8")

    monkeypatch.setattr(bootstrap, "DEFAULT_LEGACY_PRIVATE_DISCORD_ROOT", legacy_root)
    monkeypatch.setattr(bootstrap, "_infer_host_node_root", lambda _env_file, _node_name: tmp_path / "agents" / "nodes" / "paracelsus")
    monkeypatch.setattr(
        bootstrap,
        "_host_cache_root",
        lambda node_name: tmp_path / "agents" / "nodes" / node_name / "workspace" / "plugins" / "discord-slash-commands" / "cache",
    )
    monkeypatch.setattr(bootstrap, "_peer_nodes_for_scope", lambda app_id, guild_id: ["paracelsus"])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "discord_slash_commands_env_bootstrap.py",
            "--env-file",
            str(env_file),
            "--config-file",
            str(config_file),
            "--plugin-source",
            str(plugin_source),
        ],
    )

    assert bootstrap.main() == 0
    capsys.readouterr()

    cache_root = tmp_path / "agents" / "nodes" / "paracelsus" / "workspace" / "plugins" / "discord-slash-commands" / "cache"
    acl_payload = json.loads((cache_root / "governance" / "acl.json").read_text(encoding="utf-8"))
    node_activation = json.loads((cache_root / "state" / "node_activation.json").read_text(encoding="utf-8"))
    app_scope = json.loads((cache_root / "state" / "app_scope.json").read_text(encoding="utf-8"))

    assert any(str(item.get("role_name") or "").strip().lower() == "admin" for item in acl_payload["hierarchy"])
    assert node_activation["custom_enabled"] == []
    assert set(app_scope["enabled_commands"]) == {"acl", "clean", "model", "slash", "status"}
    assert acl_payload["commands"]["clean"]["min_role"] == "admin"


def test_bootstrap_runtime_hermes_home_env_uses_node_name_from_env(monkeypatch, tmp_path, capsys):
    runtime_root = tmp_path / "runtime-root"
    env_file = runtime_root / ".hermes" / ".env"
    config_file = runtime_root / ".hermes" / "config.yaml"
    plugin_source = _plugin_source(tmp_path)
    legacy_root = tmp_path / "plugins" / "private" / "discord"
    _seed_legacy_root(legacy_root, node_name="colmeio", with_custom=True)

    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "\n".join(
            [
                "PLUGIN_DISCORD_SLASH_COMMANDS=true",
                "NODE_NAME=colmeio",
                "DISCORD_APP_ID=app-1",
                "DISCORD_SERVER_ID=guild-1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_file.write_text(yaml.safe_dump({"plugins": {"enabled": []}}), encoding="utf-8")

    monkeypatch.setattr(bootstrap, "DEFAULT_LEGACY_PRIVATE_DISCORD_ROOT", legacy_root)
    monkeypatch.setattr(
        bootstrap,
        "_host_cache_root",
        lambda node_name: runtime_root / "workspace" / "plugins" / "discord-slash-commands" / "cache",
    )
    monkeypatch.setattr(bootstrap, "_peer_nodes_for_scope", lambda app_id, guild_id: ["colmeio"])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "discord_slash_commands_env_bootstrap.py",
            "--env-file",
            str(env_file),
            "--config-file",
            str(config_file),
            "--plugin-source",
            str(plugin_source),
        ],
    )

    assert bootstrap.main() == 0
    payload = json.loads(capsys.readouterr().out.strip())

    cache_root = runtime_root / "workspace" / "plugins" / "discord-slash-commands" / "cache"
    node_activation = json.loads((cache_root / "state" / "node_activation.json").read_text(encoding="utf-8"))

    assert payload["node_name"] == "colmeio"
    assert node_activation["node_name"] == "colmeio"
    assert node_activation["custom_enabled"] == ["faltas", "metricas"]


def test_bootstrap_runtime_hermes_home_env_uses_process_node_name(monkeypatch, tmp_path, capsys):
    runtime_root = tmp_path / "runtime-root"
    env_file = runtime_root / ".hermes" / ".env"
    config_file = runtime_root / ".hermes" / "config.yaml"
    plugin_source = _plugin_source(tmp_path)
    legacy_root = tmp_path / "plugins" / "private" / "discord"
    _seed_legacy_root(legacy_root, node_name="colmeio", with_custom=True)

    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "\n".join(
            [
                "PLUGIN_DISCORD_SLASH_COMMANDS=true",
                "DISCORD_APP_ID=app-1",
                "DISCORD_SERVER_ID=guild-1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_file.write_text(yaml.safe_dump({"plugins": {"enabled": []}}), encoding="utf-8")

    monkeypatch.setenv("NODE_NAME", "colmeio")
    monkeypatch.setattr(bootstrap, "DEFAULT_LEGACY_PRIVATE_DISCORD_ROOT", legacy_root)
    monkeypatch.setattr(
        bootstrap,
        "_host_cache_root",
        lambda node_name: runtime_root / "workspace" / "plugins" / "discord-slash-commands" / "cache",
    )
    monkeypatch.setattr(bootstrap, "_peer_nodes_for_scope", lambda app_id, guild_id: ["colmeio"])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "discord_slash_commands_env_bootstrap.py",
            "--env-file",
            str(env_file),
            "--config-file",
            str(config_file),
            "--plugin-source",
            str(plugin_source),
        ],
    )

    assert bootstrap.main() == 0
    payload = json.loads(capsys.readouterr().out.strip())

    cache_root = runtime_root / "workspace" / "plugins" / "discord-slash-commands" / "cache"
    node_activation = json.loads((cache_root / "state" / "node_activation.json").read_text(encoding="utf-8"))

    assert payload["node_name"] == "colmeio"
    assert node_activation["node_name"] == "colmeio"
    assert node_activation["custom_enabled"] == ["faltas", "metricas"]
