from __future__ import annotations

import pytest


def test_apply_target_resolution_all_uses_env_profiles(cm, tmp_path, monkeypatch) -> None:
    env_root = tmp_path / "envs"
    env_root.mkdir(parents=True, exist_ok=True)
    (env_root / "node-a.env").write_text("x=1\n", encoding="utf-8")
    (env_root / "node-b.env").write_text("x=1\n", encoding="utf-8")

    monkeypatch.setattr(cm, "_discover_node_names", lambda: ["node-a", "node-b", "node-c"])
    monkeypatch.setattr(cm, "_clone_env_path", lambda name: env_root / f"{name}.env")

    targets = cm._resolve_apply_target_nodes("all", "")
    assert targets == ["node-a", "node-b"]


def test_apply_target_resolution_node_csv(cm, tmp_path, monkeypatch) -> None:
    env_root = tmp_path / "envs"
    env_root.mkdir(parents=True, exist_ok=True)
    (env_root / "node-a.env").write_text("x=1\n", encoding="utf-8")
    (env_root / "node-b.env").write_text("x=1\n", encoding="utf-8")
    monkeypatch.setattr(cm, "_clone_env_path", lambda name: env_root / f"{name}.env")

    targets = cm._resolve_apply_target_nodes("node", "node-a,node-b,node-a")
    assert targets == ["node-a", "node-b"]

    with pytest.raises(cm.CloneManagerError):
        cm._resolve_apply_target_nodes("node", "node-a,node-missing")
