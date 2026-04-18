from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_plugin_matrix_includes_discord_acl_prestart_steps(cm, tmp_path: Path) -> None:
    log_path = tmp_path / "colmeio-prestart.log"
    log_path.write_text(
        "\n".join(
            [
                "[2026-04-17T00:00:00Z] STEP discord_role_acl_sync: /usr/bin/python3 /local/plugins/public/discord/scripts/discord_role_acl_sync.py",
                "[2026-04-17T00:00:01Z] OK   discord_role_acl_sync",
                "[2026-04-17T00:00:02Z] STEP discord_acl_contract_check: /usr/bin/python3 /local/plugins/public/discord/scripts/discord_acl_contract_check.py",
                "[2026-04-17T00:00:03Z] OK   discord_acl_contract_check",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    matrix = cm._build_plugin_matrix(prestart_log_path=log_path, deprecated_plugins=[])

    row = next(step for step in matrix["steps"] if step["step"] == "discord_role_acl_sync")
    assert row["plugin"] == "discord"
    assert row["status"] == "passed"
    contract_row = next(step for step in matrix["steps"] if step["step"] == "discord_acl_contract_check")
    assert contract_row["plugin"] == "discord"
    assert contract_row["status"] == "passed"


def test_update_test_fails_when_discord_acl_contract_step_fails(cm, tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "log" / "update-test-acl-fail"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.json"

    clone_root = tmp_path / "dummy-node"
    env_path = tmp_path / "env" / "node-dummy.env"

    monkeypatch.setattr(cm, "_create_update_run_dir", lambda prefix: (run_dir, "run-acl-fail", ""))
    monkeypatch.setattr(
        cm,
        "_refresh_dummy_snapshot",
        lambda source_branch, deprecate_plugins: {
            "deprecated_plugins_present": [],
            "deprecated_plugins_applied": [],
            "deprecated_plugins_already_present": [],
            "deprecated_plugins_missing": [],
        },
    )
    monkeypatch.setattr(cm, "_clone_env_path", lambda clone_name: env_path)
    monkeypatch.setattr(cm, "_clone_root_path", lambda clone_name: clone_root)
    monkeypatch.setattr(cm, "_container_name", lambda clone_name: f"ctr-{clone_name}")
    monkeypatch.setattr(cm, "_docker_exists", lambda name: False)
    monkeypatch.setattr(
        cm,
        "_seed_update_test_env_profile",
        lambda clone_name, env_path: {"env_path": str(env_path), "seed_source": "test"},
    )
    monkeypatch.setattr(cm, "_read_env_file", lambda env_path: {})
    monkeypatch.setattr(cm, "_prepare_clone_filesystem", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(cm, "_temporary_runtime_roots", lambda **kwargs: contextlib.nullcontext())

    prestart_log = tmp_path / "logs" / "colmeio-prestart.log"
    _touch(
        prestart_log,
        "\n".join(
            [
                "[2026-04-17T00:00:00Z] STEP discord_role_acl_sync: /usr/bin/python3 /local/plugins/public/discord/scripts/discord_role_acl_sync.py",
                "[2026-04-17T00:00:01Z] OK   discord_role_acl_sync",
                "[2026-04-17T00:00:02Z] STEP discord_acl_contract_check: /usr/bin/python3 /local/plugins/public/discord/scripts/discord_acl_contract_check.py",
                "[2026-04-17T00:00:03Z] FAIL discord_acl_contract_check",
            ]
        )
        + "\n",
    )

    monkeypatch.setattr(
        cm,
        "_run_prestart_reapply",
        lambda *args, **kwargs: {
            "script": "/local/plugins/public/hermes-core/scripts/prestart_reapply.sh",
            "returncode": 1,
            "stdout": "",
            "stderr": "",
            "prestart_log_path": str(prestart_log),
            "failed_marker_path": str(tmp_path / "logs" / "colmeio-prestart.failed"),
            "failed_marker_exists": True,
            "failures": ["discord_acl_contract_check"],
        },
    )

    with pytest.raises(cm.CloneManagerError):
        cm._action_update_test(
            clone_name="node-dummy",
            source_branch="main",
            deprecate_plugins=[],
        )

    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["result"] is False
    assert "discord_acl_contract_check" in str(payload.get("error") or "")
    assert "discord_acl_contract_check" in (payload.get("prestart") or {}).get("failures", [])

    matrix = json.loads(Path(payload["plugin_matrix_path"]).read_text(encoding="utf-8"))
    row = next(step for step in matrix["steps"] if step["step"] == "discord_acl_contract_check")
    assert row["plugin"] == "discord"
    assert row["status"] == "failed"


def test_update_apply_is_gated_when_acl_preflight_fails(cm, tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "log" / "apply-acl-gated"
    run_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(cm, "_create_update_run_dir", lambda prefix: (run_dir, "run-apply-acl", ""))
    monkeypatch.setattr(cm, "_resolve_apply_target_nodes", lambda mode, csv: ["node1"])

    called: list[str] = []

    def _preflight_fail(*args, **kwargs):
        called.append("preflight")
        raise cm.CloneManagerError("prestart reapply failed steps: discord_acl_contract_check")

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
