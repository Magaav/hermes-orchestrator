from __future__ import annotations

from pathlib import Path


def _touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_dummy_snapshot_copy_is_deterministic(cm, tmp_path, monkeypatch) -> None:
    runtime_plugins = tmp_path / "plugins"
    runtime_scripts = tmp_path / "scripts"
    dummy_root = tmp_path / "dummy"
    dummy_plugins = dummy_root / "plugins"
    dummy_scripts = dummy_root / "scripts"
    dummy_hermes = dummy_root / "hermes-agent"

    _touch(runtime_plugins / "public" / "plugin-a" / "a.txt", "plugin-a")
    _touch(runtime_plugins / "private" / "plugin-private" / "p.txt", "private")
    _touch(runtime_scripts / "public" / "script-a" / "s.sh", "echo ok")
    _touch(runtime_scripts / "private" / "script-private" / "sp.sh", "echo private")

    # stale files in dummy snapshot should be removed by delete=True sync.
    _touch(dummy_plugins / "public" / "stale" / "old.txt", "old")
    _touch(dummy_scripts / "public" / "stale-script" / "old.sh", "old")

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
        _touch(cm.HERMES_SOURCE_ROOT / "cli.py", f"# branch={branch}\n")
        return {"ok": True, "branch_requested": branch, "source_root": str(cm.HERMES_SOURCE_ROOT)}

    monkeypatch.setattr(cm, "_action_update_template", _fake_update_template)

    payload = cm._refresh_dummy_snapshot(source_branch="main", deprecated_plugins=[])
    assert payload["template_update"]["branch_requested"] == "main"

    assert (dummy_plugins / "public" / "plugin-a" / "a.txt").exists()
    assert (dummy_plugins / "private" / "plugin-private" / "p.txt").exists()
    assert (dummy_scripts / "public" / "script-a" / "s.sh").exists()
    assert (dummy_scripts / "private" / "script-private" / "sp.sh").exists()
    assert not (dummy_plugins / "public" / "stale").exists()
    assert not (dummy_scripts / "public" / "stale-script").exists()
