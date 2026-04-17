from __future__ import annotations

import json
from pathlib import Path

import pytest


def _touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_apply_requires_preflight_before_backup(cm, tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "log" / "apply-preflight-fail"
    run_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cm, "_create_update_run_dir", lambda prefix: (run_dir, "run-preflight-fail", ""))
    monkeypatch.setattr(cm, "_resolve_apply_target_nodes", lambda mode, csv: ["node1"])

    called: list[str] = []

    def _preflight_fail(*args, **kwargs):
        called.append("preflight")
        raise cm.CloneManagerError("preflight failed")

    def _backup_called(*args, **kwargs):
        called.append("backup")
        return {"ok": True}

    monkeypatch.setattr(cm, "_action_update_test", _preflight_fail)
    monkeypatch.setattr(cm, "_action_backup", _backup_called)

    with pytest.raises(cm.CloneManagerError):
        cm._action_update_apply(
            target_mode="all",
            target_nodes_csv="",
            source_branch="main",
            deprecate_plugins=[],
        )

    assert called == ["preflight"]


def test_apply_requires_backup_before_mutations(cm, tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "log" / "apply-backup-fail"
    run_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = tmp_path / "log" / "matrix.json"
    _touch(matrix_path, json.dumps({"summary": {"passed": 1, "failed": 0, "pending": 0}}))

    monkeypatch.setattr(cm, "_create_update_run_dir", lambda prefix: (run_dir, "run-backup-fail", ""))
    monkeypatch.setattr(cm, "_resolve_apply_target_nodes", lambda mode, csv: ["node1"])
    monkeypatch.setattr(
        cm,
        "_action_update_test",
        lambda *args, **kwargs: {
            "ok": True,
            "run_id": "preflight-1",
            "report_path": str(tmp_path / "log" / "preflight-report.json"),
            "plugin_matrix_path": str(matrix_path),
            "run_dir": str(tmp_path / "log"),
            "clone_name": "node-dummy",
        },
    )

    called: list[str] = []

    def _backup_fail(*args, **kwargs):
        called.append("backup")
        raise cm.CloneManagerError("backup failed")

    def _promote_called():
        called.append("promote")
        return {"changed": True}

    monkeypatch.setattr(cm, "_action_backup", _backup_fail)
    monkeypatch.setattr(cm, "_promote_dummy_source_to_runtime", _promote_called)

    with pytest.raises(cm.CloneManagerError):
        cm._action_update_apply(
            target_mode="all",
            target_nodes_csv="",
            source_branch="main",
            deprecate_plugins=[],
        )

    assert called == ["backup"]
