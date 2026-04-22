from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from discord_governance_env_bootstrap import main


def _plugin_source(tmp_path: Path) -> Path:
    plugin = tmp_path / "discord-governance-source"
    plugin.mkdir()
    (plugin / "plugin.yaml").write_text("name: discord-governance\n", encoding="utf-8")
    (plugin / "__init__.py").write_text("def register(ctx):\n    return None\n", encoding="utf-8")
    return plugin


def test_bootstrap_disabled_removes_from_enabled(monkeypatch, tmp_path, capsys):
    env_file = tmp_path / ".env"
    config_file = tmp_path / "config.yaml"
    plugin_source = _plugin_source(tmp_path)

    env_file.write_text("PLUGIN_DISCORD_GOVERNANCE=false\n", encoding="utf-8")
    config_file.write_text(yaml.safe_dump({"plugins": {"enabled": ["discord-governance", "other"]}}), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "discord_governance_env_bootstrap.py",
            "--env-file",
            str(env_file),
            "--config-file",
            str(config_file),
            "--plugin-source",
            str(plugin_source),
        ],
    )
    assert main() == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["enabled"] is False
    cfg = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert cfg["plugins"]["enabled"] == ["other"]


def test_bootstrap_enabled_syncs_plugin_and_updates_env(monkeypatch, tmp_path, capsys):
    env_file = tmp_path / ".env"
    config_file = tmp_path / "config.yaml"
    plugin_source = _plugin_source(tmp_path)

    env_file.write_text("PLUGIN_DISCORD_GOVERNANCE=true\n", encoding="utf-8")
    config_file.write_text(yaml.safe_dump({"plugins": {"enabled": ["other"]}}), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "discord_governance_env_bootstrap.py",
            "--env-file",
            str(env_file),
            "--config-file",
            str(config_file),
            "--plugin-source",
            str(plugin_source),
        ],
    )
    assert main() == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["enabled"] is True
    cfg = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert "discord-governance" in cfg["plugins"]["enabled"]
    assert (config_file.parent / "plugins" / "discord-governance" / "plugin.yaml").exists()
    assert "HERMES_ENABLE_PROJECT_PLUGINS=true" in env_file.read_text(encoding="utf-8")
