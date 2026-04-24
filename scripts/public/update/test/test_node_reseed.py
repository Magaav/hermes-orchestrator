from __future__ import annotations

import json


def test_prepare_clone_filesystem_preserves_local_state_when_node_reseed_true(cm, monkeypatch, tmp_path) -> None:
    clone_root = tmp_path / "agents" / "nodes" / "node1"
    env_path = tmp_path / "agents" / "envs" / "node1.env"
    source_root = tmp_path / "hermes-source"

    (clone_root / ".hermes").mkdir(parents=True, exist_ok=True)
    (clone_root / "hermes-agent").mkdir(parents=True, exist_ok=True)
    (clone_root / ".clone-meta").mkdir(parents=True, exist_ok=True)
    (clone_root / ".runtime" / "uv").mkdir(parents=True, exist_ok=True)
    (clone_root / ".hermes" / "state.txt").write_text("keep-me\n", encoding="utf-8")
    (clone_root / "hermes-agent" / "cli.py").write_text("print('old-runtime')\n", encoding="utf-8")
    (clone_root / ".runtime" / "uv" / "seed.txt").write_text("seed\n", encoding="utf-8")
    (clone_root / ".clone-meta" / "bootstrap.json").write_text(
        json.dumps({"clone_name": "node1", "bootstrapped_at": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )

    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / "cli.py").write_text("print('brand-new-runtime')\n", encoding="utf-8")
    (source_root / ".venv").mkdir(parents=True, exist_ok=True)

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("NODE_STATE=2\nNODE_RESEED=true\n", encoding="utf-8")
    env = {"NODE_STATE": "2", "NODE_RESEED": "true"}

    monkeypatch.setattr(cm, "_ensure_node_log_topology", lambda *args, **kwargs: None)
    monkeypatch.setattr(cm, "_ensure_worker_shared_mount_links", lambda *args, **kwargs: None)
    monkeypatch.setattr(cm, "_sync_discord_runtime_layout", lambda *args, **kwargs: None)
    monkeypatch.setattr(cm, "_ensure_workspace_data_layout", lambda *args, **kwargs: None)
    monkeypatch.setattr(cm, "_sync_node_wiki_link", lambda *args, **kwargs: None)
    monkeypatch.setattr(cm, "_write_node_runtime_contract", lambda *args, **kwargs: None)
    monkeypatch.setattr(cm, "_ensure_clone_ownership", lambda *args, **kwargs: None)
    monkeypatch.setattr(cm, "_normalize_clone_skills_layout", lambda *args, **kwargs: None)
    monkeypatch.setattr(cm, "_seed_clone_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(cm, "_log_spawn_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(cm, "_parent_hermes_agent_source", lambda clone_name="orchestrator": source_root)
    monkeypatch.setattr(cm, "_select_seed_venv_source", lambda **kwargs: source_root / ".venv")

    payload = cm._prepare_clone_filesystem("node1", clone_root, env, env_path)

    assert payload["reseed_requested"] is True
    assert payload["reseed_preserved_local_state"] is True
    assert payload["bootstrapped"] is False
    assert (clone_root / ".hermes" / "state.txt").read_text(encoding="utf-8") == "keep-me\n"
    assert (clone_root / "hermes-agent" / "cli.py").read_text(encoding="utf-8") == "print('brand-new-runtime')\n"


def test_perform_update_target_keeps_stopped_node_stopped_and_resets_flag(cm, monkeypatch, tmp_path) -> None:
    env_path = tmp_path / "agents" / "envs" / "node1.env"
    clone_root = tmp_path / "agents" / "nodes" / "node1"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    clone_root.mkdir(parents=True, exist_ok=True)
    env_path.write_text("NODE_STATE=2\nNODE_RESEED=false\n", encoding="utf-8")

    start_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    stop_calls: list[str] = []

    monkeypatch.setattr(cm, "_clone_env_path", lambda name: env_path)
    monkeypatch.setattr(cm, "_clone_root_path", lambda name: clone_root)
    monkeypatch.setattr(
        cm,
        "_action_status",
        lambda name: {
            "ok": True,
            "container_state": {"running": False, "status": "exited"},
            "runtime_type": "container",
            "log_file": "",
            "runtime_log_file": "",
            "attention_log_file": "",
        },
    )
    monkeypatch.setattr(
        cm,
        "_prepare_clone_filesystem",
        lambda *args, **kwargs: {
            "state_mode": "seed_from_parent_snapshot",
            "state_code": 2,
            "bootstrapped": False,
            "reseed_requested": True,
            "reseeded": True,
            "reseed_preserved_local_state": True,
        },
    )
    monkeypatch.setattr(cm, "_action_stop", lambda name: stop_calls.append(name) or {"ok": True})
    monkeypatch.setattr(
        cm,
        "_action_start",
        lambda *args, **kwargs: start_calls.append((args, kwargs)) or {"ok": True},
    )
    monkeypatch.setattr(cm, "_reconcile_registry_node", lambda name: {"clone_name": name})

    payload = cm._perform_update_target("node1")

    assert payload["was_running"] is False
    assert stop_calls == []
    assert start_calls == []
    assert "NODE_RESEED=false" in env_path.read_text(encoding="utf-8")
