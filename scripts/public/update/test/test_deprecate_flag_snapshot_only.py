from __future__ import annotations

from pathlib import Path


def _touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_update_test_deprecate_affects_dummy_snapshot_only(cm, tmp_path, monkeypatch) -> None:
    runtime_plugins = tmp_path / "plugins"
    runtime_scripts = tmp_path / "scripts"
    dummy_root = tmp_path / "dummy"
    dummy_plugins = dummy_root / "plugins"
    dummy_scripts = dummy_root / "scripts"
    dummy_hermes = dummy_root / "hermes-agent"

    _touch(runtime_plugins / "public" / "plugin-a" / "a.txt")
    _touch(runtime_plugins / "public" / "plugin-b" / "b.txt")
    _touch(runtime_scripts / "public" / "noop" / "x.sh")

    monkeypatch.setattr(cm, "PLUGINS_ROOT", runtime_plugins)
    monkeypatch.setattr(cm, "SCRIPTS_ROOT", runtime_scripts)
    monkeypatch.setattr(cm, "UPDATE_DUMMY_ROOT", dummy_root)
    monkeypatch.setattr(cm, "UPDATE_DUMMY_HERMES_ROOT", dummy_hermes)
    monkeypatch.setattr(cm, "UPDATE_DUMMY_PLUGINS_ROOT", dummy_plugins)
    monkeypatch.setattr(cm, "UPDATE_DUMMY_SCRIPTS_ROOT", dummy_scripts)
    monkeypatch.setattr(cm, "UPDATE_DUMMY_PUBLIC_PLUGINS_ROOT", dummy_plugins / "public")
    monkeypatch.setattr(cm, "UPDATE_DUMMY_PRIVATE_PLUGINS_ROOT", dummy_plugins / "private")
    monkeypatch.setattr(cm, "UPDATE_DUMMY_PUBLIC_SCRIPTS_ROOT", dummy_scripts / "public")
    monkeypatch.setattr(cm, "UPDATE_DUMMY_PRIVATE_SCRIPTS_ROOT", dummy_scripts / "private")

    def _fake_update_template(branch: str):
        cm.HERMES_SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
        _touch(cm.HERMES_SOURCE_ROOT / "cli.py", f"# {branch}\n")
        return {"ok": True}

    monkeypatch.setattr(cm, "_action_update_template", _fake_update_template)

    payload = cm._refresh_dummy_snapshot(source_branch="main", deprecated_plugins=["plugin-a"])

    assert (runtime_plugins / "public" / "plugin-a").exists()
    assert (runtime_plugins / "public" / "plugin-b").exists()
    assert not (dummy_plugins / "public" / "plugin-a").exists()
    assert (dummy_plugins / "public" / "deprecated" / "plugin-a").exists()
    assert (dummy_plugins / "public" / "plugin-b").exists()
    assert payload["deprecated_plugins_applied"] == ["plugin-a"]
