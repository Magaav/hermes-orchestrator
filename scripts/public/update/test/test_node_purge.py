from __future__ import annotations

from pathlib import Path

import pytest


def test_purge_node_requires_second_confirmation(cm, tmp_path: Path, monkeypatch) -> None:
    env_root = tmp_path / "envs"
    nodes_root = tmp_path / "nodes"
    datas_root = tmp_path / "datas"
    crons_root = tmp_path / "crons"
    logs_root = tmp_path / "logs"
    registry_path = tmp_path / "registry.json"
    purge_root = logs_root / "node-purge"

    clone_name = "colmeio"
    (env_root / f"{clone_name}.env").parent.mkdir(parents=True, exist_ok=True)
    (env_root / f"{clone_name}.env").write_text("NODE_STATE=4\n", encoding="utf-8")
    (nodes_root / clone_name / ".hermes").mkdir(parents=True, exist_ok=True)
    (datas_root / clone_name).mkdir(parents=True, exist_ok=True)
    (crons_root / clone_name).mkdir(parents=True, exist_ok=True)
    (logs_root / "nodes" / clone_name).mkdir(parents=True, exist_ok=True)
    (logs_root / "attention" / "nodes" / clone_name).mkdir(parents=True, exist_ok=True)
    registry_path.write_text('{"clones":{"colmeio":{"name":"colmeio"}}}\n', encoding="utf-8")

    monkeypatch.setattr(cm, "ENVS_ROOT", env_root)
    monkeypatch.setattr(cm, "CLONES_ROOT", nodes_root)
    monkeypatch.setattr(cm, "SHARED_NODE_DATA_ROOT", datas_root)
    monkeypatch.setattr(cm, "SHARED_CRONS_ROOT", crons_root)
    monkeypatch.setattr(cm, "NODE_LOG_ROOT", logs_root / "nodes")
    monkeypatch.setattr(cm, "ATTENTION_LOG_ROOT", logs_root / "attention" / "nodes")
    monkeypatch.setattr(cm, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(cm, "NODE_PURGE_REQUEST_ROOT", purge_root)
    monkeypatch.setattr(cm, "_action_status", lambda name: {"ok": True, "container_state": {"running": False}})
    cm._ensure_dirs()

    request = cm._action_purge_node_request(clone_name)

    assert request["ok"] is True
    assert request["action"] == "purge-node-request"
    assert "horc purge-node confirm" in request["next_safe_command"]
    request_path = Path(request["request_path"])
    assert request_path.exists()
    assert (env_root / f"{clone_name}.env").exists()
    assert (nodes_root / clone_name).exists()

    token = request["next_safe_command"].split("--token", 1)[1].strip()
    confirm = cm._action_purge_node_confirm(request["request_id"], token)

    assert confirm["ok"] is True
    assert not (env_root / f"{clone_name}.env").exists()
    assert not (nodes_root / clone_name).exists()
    assert not (datas_root / clone_name).exists()
    assert not (crons_root / clone_name).exists()
    assert not (logs_root / "nodes" / clone_name).exists()
    assert not (logs_root / "attention" / "nodes" / clone_name).exists()
    assert not request_path.exists()
    assert "colmeio" not in registry_path.read_text(encoding="utf-8")


def test_purge_node_rejects_orchestrator(cm) -> None:
    with pytest.raises(cm.CloneManagerError, match="refuses to target orchestrator"):
        cm._action_purge_node_request("orchestrator")
