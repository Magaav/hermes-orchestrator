from __future__ import annotations

import json
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_resolve_update_log_root_uses_canonical_logs_tree(cm, tmp_path, monkeypatch) -> None:
    canonical_root = tmp_path / "logs" / "update"
    monkeypatch.setattr(cm, "UPDATE_TEST_LOG_ROOT", canonical_root)
    monkeypatch.setattr(cm, "UPDATE_TEST_LOG_FALLBACK_ROOT", canonical_root)

    resolved, warning = cm._resolve_update_test_log_root()

    assert resolved == canonical_root
    assert warning == ""
    assert canonical_root.exists()


def test_update_run_stops_at_stage_validation(cm, tmp_path, monkeypatch) -> None:
    env_root = tmp_path / "envs"
    log_root = tmp_path / "logs" / "update"
    run_dir = log_root / "run-123"
    (env_root / "colmeio.env").parent.mkdir(parents=True, exist_ok=True)
    (env_root / "colmeio.env").write_text("NODE_STATE=2\n", encoding="utf-8")

    monkeypatch.setattr(cm, "ENVS_ROOT", env_root)
    monkeypatch.setattr(cm, "UPDATE_TEST_LOG_ROOT", log_root)
    monkeypatch.setattr(cm, "_active_guided_update_runs", lambda: [])
    monkeypatch.setattr(cm, "_create_update_run_dir", lambda prefix: (run_dir, "run-123", ""))
    monkeypatch.setattr(
        cm,
        "_action_profile_clone",
        lambda source_name, target_name, force: {
            "ok": True,
            "source_name": source_name,
            "target_name": target_name,
            "force": force,
        },
    )
    monkeypatch.setattr(
        cm,
        "_shared_discord_credentials",
        lambda source_name, target_name: {
            "shared": True,
            "keys": ["DISCORD_BOT_TOKEN"],
            "inferred": False,
            "warning": "shared credentials",
        },
    )
    monkeypatch.setattr(
        cm,
        "_node_status_summary",
        lambda node_name: {
            "clone_name": node_name,
            "running": node_name == "colmeio",
            "status": "running" if node_name == "colmeio" else "stopped",
        },
    )
    monkeypatch.setattr(cm, "_action_stop", lambda node_name: {"ok": True, "clone_name": node_name, "result": "stopped"})
    monkeypatch.setattr(
        cm,
        "_action_update_apply",
        lambda **kwargs: {
            "run_id": "apply-stage-1",
            "report_path": str(tmp_path / "nested" / "stage-report.json"),
            "plugin_matrix_path": str(tmp_path / "nested" / "stage-matrix.json"),
            "run_dir": str(tmp_path / "nested"),
            "updated_nodes": [kwargs["target_nodes_csv"]],
            "pending_nodes": [],
            "backup": {"ok": True},
            "preflight": {"ok": True},
            "promote_source": {"changed": True},
            "runtime_deprecations": {"deprecated_plugins_applied": []},
        },
    )
    monkeypatch.setattr(
        cm,
        "_assert_node_healthy",
        lambda node_name: {"clone_name": node_name, "running": True, "status": "running"},
    )

    payload = cm._action_update_run(
        "colmeio",
        stage_node="colmeio-stage",
        source_branch="main",
        deprecate_plugins=[],
    )

    assert payload["checkpoint"] == "stage_validation_pending"
    assert payload["manual_validation_required"] is True
    assert payload["next_safe_command"] == "horc update validate run-123 --phase stage"
    assert payload["shared_credentials_warning"] == "shared credentials"
    assert payload["stage"]["rollout"]["updated_nodes"] == ["colmeio-stage"]
    assert (run_dir / "report.json").exists()


def test_update_validate_stage_advances_to_prod_validation(cm, tmp_path, monkeypatch) -> None:
    log_root = tmp_path / "logs" / "update"
    report_path = log_root / "run-123" / "report.json"
    monkeypatch.setattr(cm, "UPDATE_TEST_LOG_ROOT", log_root)
    _write_json(
        report_path,
        {
            "ok": True,
            "action": "update-run",
            "run_id": "run-123",
            "report_path": str(report_path),
            "run_dir": str(report_path.parent),
            "checkpoint": "stage_validation_pending",
            "target_node": "colmeio",
            "stage_node": "colmeio-stage",
            "source_branch": "main",
            "deprecate_plugins": [],
            "shared_credentials": {"shared": True, "warning": "shared credentials"},
            "shared_credentials_warning": "shared credentials",
            "stage": {"node": "colmeio-stage"},
            "prod": {"node": "colmeio"},
        },
    )
    monkeypatch.setattr(
        cm,
        "_node_status_summary",
        lambda node_name: {
            "clone_name": node_name,
            "running": node_name == "colmeio-stage",
            "status": "running" if node_name == "colmeio-stage" else "stopped",
        },
    )
    monkeypatch.setattr(cm, "_action_stop", lambda node_name: {"ok": True, "clone_name": node_name, "result": "stopped"})
    monkeypatch.setattr(
        cm,
        "_action_update_apply",
        lambda **kwargs: {
            "run_id": "apply-prod-1",
            "report_path": str(tmp_path / "nested" / "prod-report.json"),
            "plugin_matrix_path": str(tmp_path / "nested" / "prod-matrix.json"),
            "run_dir": str(tmp_path / "nested"),
            "updated_nodes": [kwargs["target_nodes_csv"]],
            "pending_nodes": [],
            "backup": {"ok": True},
            "preflight": {"ok": True},
            "promote_source": {"changed": False},
            "runtime_deprecations": {"deprecated_plugins_applied": []},
        },
    )
    monkeypatch.setattr(
        cm,
        "_assert_node_healthy",
        lambda node_name: {"clone_name": node_name, "running": True, "status": "running"},
    )

    payload = cm._action_update_validate("run-123", "stage")

    assert payload["checkpoint"] == "prod_validation_pending"
    assert payload["manual_validation_required"] is True
    assert payload["next_safe_command"] == "horc update validate run-123 --phase prod"
    assert payload["stage"]["validation"]["status"] == "approved"
    assert payload["prod"]["rollout"]["updated_nodes"] == ["colmeio"]


def test_update_validate_prod_marks_run_complete(cm, tmp_path, monkeypatch) -> None:
    log_root = tmp_path / "logs" / "update"
    report_path = log_root / "run-123" / "report.json"
    monkeypatch.setattr(cm, "UPDATE_TEST_LOG_ROOT", log_root)
    _write_json(
        report_path,
        {
            "ok": True,
            "action": "update-run",
            "run_id": "run-123",
            "report_path": str(report_path),
            "run_dir": str(report_path.parent),
            "checkpoint": "prod_validation_pending",
            "target_node": "colmeio",
            "stage_node": "colmeio-stage",
            "source_branch": "main",
            "deprecate_plugins": [],
            "stage": {"node": "colmeio-stage"},
            "prod": {"node": "colmeio"},
        },
    )

    payload = cm._action_update_validate("run-123", "prod")

    assert payload["checkpoint"] == "completed"
    assert payload["manual_validation_required"] is False
    assert payload["next_safe_command"] == ""
    assert payload["prod"]["validation"]["status"] == "approved"


def test_update_resume_retries_failed_stage(cm, tmp_path, monkeypatch) -> None:
    log_root = tmp_path / "logs" / "update"
    report_path = log_root / "run-123" / "report.json"
    monkeypatch.setattr(cm, "UPDATE_TEST_LOG_ROOT", log_root)
    _write_json(
        report_path,
        {
            "ok": False,
            "action": "update-run",
            "run_id": "run-123",
            "report_path": str(report_path),
            "run_dir": str(report_path.parent),
            "checkpoint": "stage_rollout_failed",
            "target_node": "colmeio",
            "stage_node": "colmeio-stage",
            "source_branch": "main",
            "deprecate_plugins": [],
            "stage": {"node": "colmeio-stage"},
            "prod": {"node": "colmeio"},
        },
    )

    called = {"stage": 0}

    def _resume_stage(payload):
        called["stage"] += 1
        payload["checkpoint"] = "stage_validation_pending"
        return payload

    monkeypatch.setattr(cm, "_execute_guided_update_stage", _resume_stage)

    payload = cm._action_update_resume("run-123")

    assert called["stage"] == 1
    assert payload["checkpoint"] == "stage_validation_pending"
