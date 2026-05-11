from __future__ import annotations

from pathlib import Path


def test_ensure_dirs_does_not_create_legacy_plugin_roots(cm, tmp_path: Path, monkeypatch) -> None:
    agents_root = tmp_path / "agents"
    logs_root = tmp_path / "logs"
    plugins_root = tmp_path / "plugins"
    scripts_root = tmp_path / "scripts"
    backups_root = tmp_path / "backups"
    skills_root = tmp_path / "skills"
    datas_root = tmp_path / "datas"
    crons_root = tmp_path / "crons"
    wiki_root = tmp_path / "wiki"
    memory_root = tmp_path / "memory"

    monkeypatch.setattr(cm, "AGENTS_ROOT", agents_root)
    monkeypatch.setattr(cm, "ENVS_ROOT", agents_root / "envs")
    monkeypatch.setattr(cm, "CLONES_ROOT", agents_root / "nodes")
    monkeypatch.setattr(cm, "LOGS_ROOT", logs_root)
    monkeypatch.setattr(cm, "NODE_LOG_ROOT", logs_root / "nodes")
    monkeypatch.setattr(cm, "NODE_ACTIVITY_LOG_ROOT", logs_root / "nodes" / "activities")
    monkeypatch.setattr(cm, "ATTENTION_LOG_ROOT", logs_root / "attention" / "nodes")
    monkeypatch.setattr(cm, "NODE_PURGE_REQUEST_ROOT", logs_root / "node-purge")
    monkeypatch.setattr(cm, "BACKUPS_ROOT", backups_root)
    monkeypatch.setattr(cm, "PLUGINS_ROOT", plugins_root)
    monkeypatch.setattr(cm, "SHARED_PLUGINS_ROOT", plugins_root / "public")
    monkeypatch.setattr(cm, "PRIVATE_PLUGINS_ROOT", plugins_root / "private")
    monkeypatch.setattr(cm, "SCRIPTS_ROOT", scripts_root)
    monkeypatch.setattr(cm, "SHARED_SCRIPTS_ROOT", scripts_root / "public")
    monkeypatch.setattr(cm, "PRIVATE_SCRIPTS_ROOT", scripts_root / "private")
    monkeypatch.setattr(cm, "SHARED_CRONS_ROOT", crons_root)
    monkeypatch.setattr(cm, "LEGACY_SHARED_CRONS_ROOT", scripts_root / "private" / "crons")
    monkeypatch.setattr(cm, "SHARED_WIKI_ROOT", wiki_root)
    monkeypatch.setattr(cm, "SHARED_MEMORY_ROOT", memory_root)
    monkeypatch.setattr(cm, "LEGACY_SHARED_WIKI_ROOT", plugins_root / "private" / "wiki")
    monkeypatch.setattr(cm, "LEGACY_SHARED_MEMORY_ROOT", plugins_root / "private" / "memory")
    monkeypatch.setattr(cm, "PRIVATE_SKILLS_ROOT", skills_root)
    monkeypatch.setattr(cm, "SHARED_NODE_DATA_ROOT", datas_root)
    monkeypatch.setattr(cm, "_ensure_orchestrator_backup_cron_script", lambda: crons_root / "orchestrator" / "backup_daily_brt.sh")

    cm._ensure_dirs()

    assert plugins_root.exists()
    assert not (plugins_root / "public").exists()
    assert not (plugins_root / "private").exists()


def test_ensure_dirs_migrates_legacy_wiki_out_of_private_plugins(cm, tmp_path: Path, monkeypatch) -> None:
    plugins_root = tmp_path / "plugins"
    legacy_wiki_root = plugins_root / "private" / "wiki"
    wiki_root = tmp_path / "wiki"

    (legacy_wiki_root / "meta").mkdir(parents=True, exist_ok=True)
    (legacy_wiki_root / "index.md").write_text("hello\n", encoding="utf-8")

    monkeypatch.setattr(cm, "AGENTS_ROOT", tmp_path / "agents")
    monkeypatch.setattr(cm, "ENVS_ROOT", tmp_path / "agents" / "envs")
    monkeypatch.setattr(cm, "CLONES_ROOT", tmp_path / "agents" / "nodes")
    monkeypatch.setattr(cm, "LOGS_ROOT", tmp_path / "logs")
    monkeypatch.setattr(cm, "NODE_LOG_ROOT", tmp_path / "logs" / "nodes")
    monkeypatch.setattr(cm, "NODE_ACTIVITY_LOG_ROOT", tmp_path / "logs" / "nodes" / "activities")
    monkeypatch.setattr(cm, "ATTENTION_LOG_ROOT", tmp_path / "logs" / "attention" / "nodes")
    monkeypatch.setattr(cm, "NODE_PURGE_REQUEST_ROOT", tmp_path / "logs" / "node-purge")
    monkeypatch.setattr(cm, "BACKUPS_ROOT", tmp_path / "backups")
    monkeypatch.setattr(cm, "PLUGINS_ROOT", plugins_root)
    monkeypatch.setattr(cm, "SHARED_PLUGINS_ROOT", plugins_root / "public")
    monkeypatch.setattr(cm, "PRIVATE_PLUGINS_ROOT", plugins_root / "private")
    monkeypatch.setattr(cm, "SCRIPTS_ROOT", tmp_path / "scripts")
    monkeypatch.setattr(cm, "SHARED_SCRIPTS_ROOT", tmp_path / "scripts" / "public")
    monkeypatch.setattr(cm, "PRIVATE_SCRIPTS_ROOT", tmp_path / "scripts" / "private")
    monkeypatch.setattr(cm, "SHARED_CRONS_ROOT", tmp_path / "crons")
    monkeypatch.setattr(cm, "LEGACY_SHARED_CRONS_ROOT", tmp_path / "scripts" / "private" / "crons")
    monkeypatch.setattr(cm, "SHARED_WIKI_ROOT", wiki_root)
    monkeypatch.setattr(cm, "SHARED_MEMORY_ROOT", tmp_path / "memory")
    monkeypatch.setattr(cm, "LEGACY_SHARED_WIKI_ROOT", legacy_wiki_root)
    monkeypatch.setattr(cm, "LEGACY_SHARED_MEMORY_ROOT", plugins_root / "private" / "memory")
    monkeypatch.setattr(cm, "PRIVATE_SKILLS_ROOT", tmp_path / "skills")
    monkeypatch.setattr(cm, "SHARED_NODE_DATA_ROOT", tmp_path / "datas")
    monkeypatch.setattr(cm, "_ensure_orchestrator_backup_cron_script", lambda: tmp_path / "crons" / "orchestrator" / "backup_daily_brt.sh")

    cm._ensure_dirs()

    assert (wiki_root / "index.md").read_text(encoding="utf-8") == "hello\n"
    assert not legacy_wiki_root.exists()


def test_sanitize_space_ui_env_map_is_noop_after_wasm_agent_migration(cm) -> None:
    env = {
        "HERMES_WASM_AGENT_STATE_DIR": "/tmp/wasm-agent-state",
        "HERMES_WASM_AGENT_BRIDGE_STATE_DIR": "/tmp/wasm-agent-state/bridge",
        "UNCHANGED": "keep-me",
    }

    sanitized = cm._sanitize_space_ui_env_map(env)

    assert sanitized == env
    assert sanitized is not env
    assert sanitized["UNCHANGED"] == "keep-me"
