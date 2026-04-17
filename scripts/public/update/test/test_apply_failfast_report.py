from __future__ import annotations

import json
from pathlib import Path

import pytest


def _touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_apply_failfast_reports_updated_and_pending_nodes(cm, tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "log" / "apply-failfast"
    run_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = tmp_path / "log" / "matrix.json"
    _touch(matrix_path, json.dumps({"summary": {"passed": 2, "failed": 0, "pending": 0}}))

    runtime_public = tmp_path / "plugins" / "public"
    runtime_public.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(cm, "SHARED_PLUGINS_ROOT", runtime_public)
    monkeypatch.setattr(cm, "_create_update_run_dir", lambda prefix: (run_dir, "run-failfast", ""))
    monkeypatch.setattr(cm, "_resolve_apply_target_nodes", lambda mode, csv: ["node1", "node2", "node3"])
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
    monkeypatch.setattr(cm, "_action_backup", lambda *args, **kwargs: {"ok": True, "archive": "backup.tgz", "scope": "all", "nodes": ["node1", "node2", "node3"]})
    monkeypatch.setattr(cm, "_promote_dummy_source_to_runtime", lambda: {"changed": True})
    monkeypatch.setattr(cm, "_action_update_node", lambda *args, **kwargs: {"ok": True})

    def _restart(node_name: str):
        if node_name == "node2":
            raise cm.CloneManagerError("restart failed")
        return {"ok": True}

    monkeypatch.setattr(cm, "_action_restart_node_for_rollout", _restart)

    with pytest.raises(cm.CloneManagerError):
        cm._action_update_apply(
            target_mode="all",
            target_nodes_csv="",
            source_branch="main",
            deprecate_plugins=[],
        )

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["updated_nodes"] == ["node1"]
    assert report["pending_nodes"] == ["node3"]
    rollout = report["rollout"]
    assert rollout[0]["node"] == "node1" and rollout[0]["status"] == "updated"
    assert rollout[1]["node"] == "node2" and rollout[1]["status"] == "failed"
