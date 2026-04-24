from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from canva_env_bootstrap import main


def _write_plugin_source(root: Path) -> Path:
    plugin = root / "canva"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text("name: canva\n", encoding="utf-8")
    (plugin / "__init__.py").write_text("def register(ctx):\n    pass\n", encoding="utf-8")
    return plugin


def test_bootstrap_disabled_keeps_plugin_inactive(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "node.env"
    env_file.write_text("PLUGIN_CANVA=false\n", encoding="utf-8")
    config_file = tmp_path / ".hermes" / "config.yaml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(yaml.safe_dump({"plugins": {"enabled": ["canva", "other"]}}), encoding="utf-8")
    plugin_source = _write_plugin_source(tmp_path / "src")
    monkeypatch.setattr(sys, "argv", ["canva_env_bootstrap.py", "--env-file", str(env_file), "--config-file", str(config_file), "--plugin-source", str(plugin_source)])
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["enabled"] is False
    cfg = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert cfg["plugins"]["enabled"] == ["other"]


def test_bootstrap_enabled_requires_credentials(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "node.env"
    env_file.write_text("PLUGIN_CANVA=true\n", encoding="utf-8")
    config_file = tmp_path / ".hermes" / "config.yaml"
    plugin_source = _write_plugin_source(tmp_path / "src")
    monkeypatch.setattr(sys, "argv", ["canva_env_bootstrap.py", "--env-file", str(env_file), "--config-file", str(config_file), "--plugin-source", str(plugin_source)])
    assert main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "CANVA_REFRESH_TOKEN" in payload["missing"]


def test_bootstrap_enabled_syncs_plugin_and_updates_config(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "node.env"
    env_file.write_text("PLUGIN_CANVA=true\nCANVA_REFRESH_TOKEN=refresh\nCANVA_CLIENT_ID=client\nCANVA_CLIENT_SECRET=secret\n", encoding="utf-8")
    config_file = tmp_path / ".hermes" / "config.yaml"
    plugin_source = _write_plugin_source(tmp_path / "src")
    monkeypatch.setattr(sys, "argv", ["canva_env_bootstrap.py", "--env-file", str(env_file), "--config-file", str(config_file), "--plugin-source", str(plugin_source)])
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["enabled"] is True
    assert (config_file.parent / "plugins" / "canva" / "plugin.yaml").exists()
    cfg = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert "canva" in cfg["plugins"]["enabled"]
    assert "HERMES_ENABLE_PROJECT_PLUGINS=true" in env_file.read_text(encoding="utf-8")
