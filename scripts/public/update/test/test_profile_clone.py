from __future__ import annotations

from pathlib import Path

import pytest


def test_render_cloned_env_text_retargets_stage_profile(cm, tmp_path: Path) -> None:
    backup_path = tmp_path / "backup.tar.gz"
    source_text = "\n".join(
        [
            "NODE_STATE=2",
            "NODE_STATE_FROM_BACKUP_PATH=''",
            "NODE_NAME=colmeio",
            "OPENVIKING_ACCOUNT=colmeio",
            "OPENVIKING_USER=colmeio",
            "DISCORD_COMMANDS_FILE=/local/plugins/private/discord/commands/colmeio.json",
        ]
    )

    rendered = cm._render_cloned_env_text(
        source_text,
        source_name="colmeio",
        target_name="colmeio-stage",
        backup_path=backup_path,
    )

    assert 'NODE_STATE=3' in rendered
    assert f'NODE_STATE_FROM_BACKUP_PATH="{backup_path}"' in rendered
    assert 'NODE_STATE_FROM_BACKUP_NODE="colmeio"' in rendered
    assert 'NODE_NAME="colmeio-stage"' in rendered
    assert 'OPENVIKING_ACCOUNT="colmeio-stage"' in rendered
    assert 'OPENVIKING_USER="colmeio-stage"' in rendered
    assert 'DISCORD_COMMANDS_FILE="/local/plugins/private/discord/commands/colmeio-stage.json"' in rendered


def test_profile_clone_prepares_backup_seeded_stage_assets(cm, tmp_path: Path, monkeypatch) -> None:
    env_root = tmp_path / "envs"
    nodes_root = tmp_path / "nodes"
    datas_root = tmp_path / "datas"
    crons_root = tmp_path / "crons"
    plugins_root = tmp_path / "plugins" / "private"
    logs_root = tmp_path / "logs"
    registry_path = tmp_path / "registry.json"

    source_name = "colmeio"
    target_name = "colmeio-stage"
    backup_path = tmp_path / "backups" / "horc-backup-node-colmeio-20260418T000000Z.tar.gz"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text("dummy", encoding="utf-8")

    source_env_path = env_root / f"{source_name}.env"
    source_env_path.parent.mkdir(parents=True, exist_ok=True)
    source_env_path.write_text(
        "\n".join(
            [
                "NODE_STATE=2",
                "NODE_STATE_FROM_BACKUP_PATH=''",
                "NODE_NAME=colmeio",
                "DISCORD_COMMANDS_FILE=/local/plugins/private/discord/commands/colmeio.json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (nodes_root / source_name).mkdir(parents=True, exist_ok=True)
    (datas_root / source_name).mkdir(parents=True, exist_ok=True)
    (datas_root / source_name / "state.json").write_text('{"ok": true}\n', encoding="utf-8")
    (crons_root / source_name).mkdir(parents=True, exist_ok=True)
    (crons_root / source_name / "job.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    discord_root = plugins_root / "discord"
    (discord_root / "commands").mkdir(parents=True, exist_ok=True)
    (discord_root / "acl").mkdir(parents=True, exist_ok=True)
    (discord_root / "models").mkdir(parents=True, exist_ok=True)
    (discord_root / "commands" / f"{source_name}.json").write_text('{"name":"colmeio"}\n', encoding="utf-8")
    (discord_root / "acl" / f"{source_name}_acl.json").write_text('{"roles":[]}\n', encoding="utf-8")
    (discord_root / "models" / f"{source_name}_models.json").write_text('{"models":[]}\n', encoding="utf-8")

    monkeypatch.setattr(cm, "ENVS_ROOT", env_root)
    monkeypatch.setattr(cm, "CLONES_ROOT", nodes_root)
    monkeypatch.setattr(cm, "SHARED_NODE_DATA_ROOT", datas_root)
    monkeypatch.setattr(cm, "SHARED_CRONS_ROOT", crons_root)
    monkeypatch.setattr(cm, "PRIVATE_PLUGINS_ROOT", plugins_root)
    monkeypatch.setattr(cm, "NODE_LOG_ROOT", logs_root / "nodes")
    monkeypatch.setattr(cm, "ATTENTION_LOG_ROOT", logs_root / "attention")
    monkeypatch.setattr(cm, "REGISTRY_PATH", registry_path)

    monkeypatch.setattr(
        cm,
        "_action_backup",
        lambda clone_name, backup_all: {
            "ok": True,
            "archive": str(backup_path),
            "scope": "node",
            "nodes": [clone_name],
        },
    )
    monkeypatch.setattr(
        cm,
        "_action_status",
        lambda clone_name: {"ok": True, "container_state": {"running": False}},
    )

    payload = cm._action_profile_clone(source_name, target_name, force=False)

    target_env = env_root / f"{target_name}.env"
    assert payload["ok"] is True
    assert payload["backup"]["archive"] == str(backup_path)
    assert target_env.exists()
    env_text = target_env.read_text(encoding="utf-8")
    assert 'NODE_STATE=3' in env_text
    assert f'NODE_STATE_FROM_BACKUP_PATH="{backup_path}"' in env_text
    assert 'NODE_STATE_FROM_BACKUP_NODE="colmeio"' in env_text
    assert 'NODE_NAME="colmeio-stage"' in env_text
    assert 'DISCORD_COMMANDS_FILE="/local/plugins/private/discord/commands/colmeio-stage.json"' in env_text

    assert (datas_root / target_name / "state.json").exists()
    assert (crons_root / target_name / "job.sh").exists()
    assert (discord_root / "commands" / f"{target_name}.json").exists()
    assert (discord_root / "acl" / f"{target_name}_acl.json").exists()
    assert (discord_root / "models" / f"{target_name}_models.json").exists()


def test_profile_clone_requires_force_when_target_assets_exist(cm, tmp_path: Path, monkeypatch) -> None:
    env_root = tmp_path / "envs"
    nodes_root = tmp_path / "nodes"

    (env_root / "colmeio.env").parent.mkdir(parents=True, exist_ok=True)
    (env_root / "colmeio.env").write_text("NODE_STATE=2\n", encoding="utf-8")
    (nodes_root / "colmeio").mkdir(parents=True, exist_ok=True)
    (env_root / "colmeio-stage.env").write_text("NODE_STATE=3\n", encoding="utf-8")

    monkeypatch.setattr(cm, "ENVS_ROOT", env_root)
    monkeypatch.setattr(cm, "CLONES_ROOT", nodes_root)
    monkeypatch.setattr(cm, "_action_status", lambda clone_name: {"ok": True, "container_state": {"running": False}})

    with pytest.raises(cm.CloneManagerError, match="--force"):
        cm._action_profile_clone("colmeio", "colmeio-stage", force=False)


def test_seed_from_backup_accepts_horc_node_backup_layout(cm, tmp_path: Path) -> None:
    backup_root = tmp_path / "backup"
    node_root = backup_root / "agents" / "nodes" / "colmeio"
    (node_root / ".hermes").mkdir(parents=True, exist_ok=True)
    (node_root / ".hermes" / "config.yaml").write_text("ok: true\n", encoding="utf-8")
    (node_root / "workspace").mkdir(parents=True, exist_ok=True)
    (node_root / "workspace" / "payload.txt").write_text("payload\n", encoding="utf-8")
    (node_root / "hermes-agent").mkdir(parents=True, exist_ok=True)
    (node_root / "hermes-agent" / "cli.py").write_text("print('ok')\n", encoding="utf-8")

    target_root = tmp_path / "target"
    cm._seed_from_backup(
        target_root,
        backup_root,
        source_node_name="colmeio",
    )

    assert (target_root / ".hermes" / "config.yaml").exists()
    assert (target_root / "workspace" / "payload.txt").exists()
    assert (target_root / "hermes-agent" / "cli.py").exists()
