from __future__ import annotations

import json
from pathlib import Path


def _touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_update_apply_moves_runtime_plugin_to_deprecated(cm, tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "log" / "apply-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    preflight_matrix = tmp_path / "log" / "preflight-matrix.json"
    _touch(preflight_matrix, json.dumps({"summary": {"passed": 1, "failed": 0, "pending": 0}}))

    runtime_public = tmp_path / "plugins" / "public"
    _touch(runtime_public / "old-plugin" / "plugin.py", "x")

    monkeypatch.setattr(cm, "SHARED_PLUGINS_ROOT", runtime_public)
    monkeypatch.setattr(cm, "_create_update_run_dir", lambda prefix: (run_dir, "run-1", ""))
    monkeypatch.setattr(cm, "_resolve_apply_target_nodes", lambda mode, csv: ["node1"])
    monkeypatch.setattr(
        cm,
        "_action_update_test",
        lambda clone_name, source_branch, deprecate_plugins: {
            "ok": True,
            "run_id": "preflight-1",
            "report_path": str(tmp_path / "log" / "preflight-report.json"),
            "plugin_matrix_path": str(preflight_matrix),
            "run_dir": str(tmp_path / "log"),
            "clone_name": "node-dummy",
        },
    )
    monkeypatch.setattr(cm, "_action_backup", lambda clone_name, backup_all: {"ok": True, "archive": "backup.tar.gz", "scope": "all", "nodes": ["node1"]})
    monkeypatch.setattr(cm, "_promote_dummy_source_to_runtime", lambda: {"changed": True})
    monkeypatch.setattr(cm, "_action_update_node", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cm, "_action_restart_node_for_rollout", lambda node_name: {"ok": True})

    payload = cm._action_update_apply(
        target_mode="node",
        target_nodes_csv="node1",
        source_branch="main",
        deprecate_plugins=["old-plugin"],
    )

    assert payload["ok"] is True
    assert not (runtime_public / "old-plugin").exists()
    assert (runtime_public / "deprecated" / "old-plugin").exists()
    assert payload["deprecated_plugins_applied"] == ["old-plugin"]
    deprecations = payload["runtime_deprecations"]
    assert deprecations["deprecated_plugins_applied"] == ["old-plugin"]
