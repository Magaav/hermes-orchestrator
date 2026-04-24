from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path("/local/plugins/public/native/discord-slash-commands/scripts/register_guild_plugin_commands.py")


def _load_script_module():
    module_name = "discord_slash_commands_register_guild_plugin_commands_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load register_guild_plugin_commands.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_build_command_payloads_restores_structured_faltas_options(tmp_path):
    module = _load_script_module()
    commands_file = tmp_path / "colmeio.json"
    commands_file.write_text(
        json.dumps(
            [
                {
                    "name": "faltas",
                    "description": "Gerenciar lista de faltas das lojas",
                    "type": 1,
                    "options": [
                        {
                            "type": 3,
                            "name": "action",
                            "description": "Acao do comando",
                            "required": True,
                            "choices": [
                                {"name": "listar", "value": "listar"},
                                {"name": "adicionar", "value": "adicionar"},
                                {"name": "remover", "value": "remover"},
                                {"name": "limpar", "value": "limpar"},
                                {"name": "help", "value": "help"},
                            ],
                        },
                        {
                            "type": 3,
                            "name": "loja",
                            "description": "loja1, loja2 ou ambas",
                            "required": False,
                            "choices": [
                                {"name": "loja1", "value": "loja1"},
                                {"name": "loja2", "value": "loja2"},
                                {"name": "ambas", "value": "ambas"},
                            ],
                        },
                        {
                            "type": 3,
                            "name": "itens",
                            "description": "Itens separados por virgula (adicionar/remover)",
                            "required": False,
                        },
                        {
                            "type": 3,
                            "name": "formato",
                            "description": "Formato para listar: links, excel ou texto",
                            "required": False,
                            "choices": [
                                {"name": "links", "value": "links"},
                                {"name": "excel", "value": "excel"},
                                {"name": "texto", "value": "texto"},
                            ],
                        },
                    ],
                },
                {
                    "name": "metricas",
                    "description": "Dashboard de métricas Colmeio (somente admin)",
                    "type": 1,
                    "default_member_permissions": "8",
                    "dm_permission": False,
                    "options": [
                        {
                            "type": 3,
                            "name": "formato",
                            "description": "Formato do dashboard",
                            "required": False,
                            "choices": [
                                {"name": "texto", "value": "text"},
                                {"name": "json", "value": "json"},
                                {"name": "csv", "value": "csv"},
                            ],
                        },
                        {
                            "type": 4,
                            "name": "dias",
                            "description": "Janela em dias (ex.: 7, 30, 90)",
                            "required": False,
                            "min_value": 1,
                            "max_value": 365,
                        },
                    ],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payloads = module._build_command_payloads(commands_file)

    faltas = next(item for item in payloads if item["name"] == "faltas")
    metricas = next(item for item in payloads if item["name"] == "metricas")

    faltas_option_names = [item["name"] for item in faltas["options"]]
    assert faltas_option_names == ["action", "loja", "itens", "formato"]
    assert "args" not in faltas_option_names
    action_values = [item["value"] for item in faltas["options"][0]["choices"]]
    assert action_values == ["listar", "adicionar", "remover", "limpar", "help"]

    assert metricas["default_member_permissions"] == "8"
    assert metricas["dm_permission"] is False
    assert [item["name"] for item in metricas["options"]] == ["formato", "dias"]


def test_build_command_payloads_falls_back_to_structured_defaults_when_payload_missing(tmp_path):
    module = _load_script_module()

    payloads = module._build_command_payloads(tmp_path / "missing.json")

    faltas = next(item for item in payloads if item["name"] == "faltas")
    action_option = next(item for item in faltas["options"] if item["name"] == "action")
    format_option = next(item for item in faltas["options"] if item["name"] == "formato")

    assert [item["name"] for item in faltas["options"]] == ["action", "loja", "itens", "formato"]
    assert [choice["value"] for choice in action_option["choices"]] == [
        "listar",
        "adicionar",
        "remover",
        "limpar",
        "help",
    ]
    assert [choice["value"] for choice in format_option["choices"]] == ["links", "excel", "texto"]


def test_resolve_scope_uses_global_when_sync_is_enabled():
    module = _load_script_module()

    assert module._resolve_scope("safe", "auto") == "global"
    assert module._resolve_scope("bulk", "auto") == "global"
    assert module._resolve_scope("off", "auto") == "guild"
    assert module._resolve_scope("safe", "guild") == "guild"
    assert module._resolve_scope("off", "global") == "global"


def test_collect_overlaps_returns_secondary_entries_only():
    module = _load_script_module()

    overlap_names, overlapping_entries = module._collect_overlaps(
        [
            {"name": "status", "id": "global-1"},
            {"name": "metricas", "id": "global-2"},
        ],
        [
            {"name": "status", "id": "guild-1"},
            {"name": "help", "id": "guild-2"},
        ],
    )

    assert overlap_names == ["status"]
    assert overlapping_entries == [{"name": "status", "id": "guild-1"}]


def test_build_deploy_plan_ignores_discord_omitted_falsey_permission_fields():
    module = _load_script_module()

    desired = [
        {
            "name": "metricas",
            "type": 1,
            "description": "Dashboard",
            "default_member_permissions": "8",
            "dm_permission": False,
            "options": [],
        },
        {
            "name": "faltas",
            "type": 1,
            "description": "Gerenciar faltas",
            "options": [],
        },
    ]
    existing = [
        {
            "name": "metricas",
            "type": 1,
            "description": "Dashboard",
            "default_member_permissions": "8",
            "options": [],
        },
        {
            "name": "faltas",
            "type": 1,
            "description": "Gerenciar faltas",
            "default_member_permissions": None,
            "options": [],
        },
    ]

    unchanged, to_patch, to_create = module._build_deploy_plan(desired, existing)

    assert [item["name"] for item in unchanged] == ["metricas", "faltas"]
    assert to_patch == []
    assert to_create == []


def test_main_dry_run_global_scope_reports_guild_conflicts(tmp_path, monkeypatch, capsys):
    module = _load_script_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DISCORD_APP_ID=app-1",
                "DISCORD_SERVER_ID=guild-1",
                "DISCORD_BOT_TOKEN=token-1",
                "DISCORD_COMMAND_SYNC_POLICY=safe",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "_get_existing_global_commands",
        lambda app_id, bot_token: {
            "ok": True,
            "data": [
                {"name": "status", "id": "g-1"},
                {"name": "metricas", "id": "g-2"},
            ],
        },
    )
    monkeypatch.setattr(
        module,
        "_get_existing_commands",
        lambda app_id, guild_id, bot_token: {
            "ok": True,
            "data": [
                {"name": "status", "id": "gu-1"},
                {"name": "discord-slash-status", "id": "gu-2"},
            ],
        },
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["register_guild_plugin_commands.py", "--env-file", str(env_file), "--dry-run"],
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "global"
    assert payload["overlap_names"] == ["status"]
    assert payload["to_create"] == []


def test_main_dry_run_guild_scope_reports_global_conflicts(tmp_path, monkeypatch, capsys):
    module = _load_script_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DISCORD_APP_ID=app-1",
                "DISCORD_SERVER_ID=guild-1",
                "DISCORD_BOT_TOKEN=token-1",
                "DISCORD_COMMAND_SYNC_POLICY=off",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "_get_existing_global_commands",
        lambda app_id, bot_token: {
            "ok": True,
            "data": [
                {"name": "status", "id": "g-1"},
                {"name": "metricas", "id": "g-2"},
            ],
        },
    )
    monkeypatch.setattr(
        module,
        "_get_existing_commands",
        lambda app_id, guild_id, bot_token: {
            "ok": True,
            "data": [
                {"name": "status", "id": "gu-1"},
                {"name": "discord-slash-status", "id": "gu-2"},
            ],
        },
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["register_guild_plugin_commands.py", "--env-file", str(env_file), "--dry-run"],
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "guild"
    assert payload["overlap_names"] == ["status"]
    assert sorted(payload["to_create"]) == ["faltas", "metricas"]


def test_main_global_scope_is_non_destructive(tmp_path, monkeypatch, capsys):
    module = _load_script_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DISCORD_APP_ID=app-1",
                "DISCORD_SERVER_ID=guild-1",
                "DISCORD_BOT_TOKEN=token-1",
                "DISCORD_COMMAND_SYNC_POLICY=safe",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "_get_existing_global_commands",
        lambda app_id, bot_token: {
            "ok": True,
            "data": [{"name": "metricas", "id": "g-1"}],
        },
    )
    monkeypatch.setattr(
        module,
        "_get_existing_commands",
        lambda app_id, guild_id, bot_token: {
            "ok": True,
            "data": [{"name": "metricas", "id": "gu-1"}],
        },
    )

    delete_calls = []
    monkeypatch.setattr(module, "_delete_guild_command", lambda **kwargs: delete_calls.append(kwargs) or {"ok": True})
    monkeypatch.setattr(
        sys,
        "argv",
        ["register_guild_plugin_commands.py", "--env-file", str(env_file), "--mode", "safe"],
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "global"
    assert payload["summary"]["overlap_names"] == ["metricas"]
    assert delete_calls == []


def test_main_safe_guild_scope_patches_without_pruning(tmp_path, monkeypatch, capsys):
    module = _load_script_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DISCORD_APP_ID=app-1",
                "DISCORD_SERVER_ID=guild-1",
                "DISCORD_BOT_TOKEN=token-1",
                "DISCORD_COMMAND_SYNC_POLICY=off",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "_build_command_payloads",
        lambda _commands_file: [
            {"name": "metricas", "type": 1, "description": "new desc", "options": []},
            {"name": "faltas", "type": 1, "description": "faltas desc", "options": []},
        ],
    )
    monkeypatch.setattr(
        module,
        "_get_existing_global_commands",
        lambda app_id, bot_token: {
            "ok": True,
            "data": [{"name": "metricas", "id": "g-1"}],
        },
    )
    monkeypatch.setattr(
        module,
        "_get_existing_commands",
        lambda app_id, guild_id, bot_token: {
            "ok": True,
            "data": [{"name": "metricas", "id": "gu-1", "type": 1, "description": "old desc", "options": []}],
        },
    )

    patch_calls = []
    create_calls = []
    delete_calls = []
    monkeypatch.setattr(
        module,
        "_patch_command",
        lambda **kwargs: patch_calls.append(kwargs) or {"ok": True, "status": 200, "data": {}},
    )
    monkeypatch.setattr(
        module,
        "_create_command",
        lambda **kwargs: create_calls.append(kwargs) or {"ok": True, "status": 200, "data": {}},
    )
    monkeypatch.setattr(module, "_delete_global_command", lambda **kwargs: delete_calls.append(kwargs) or {"ok": True})
    monkeypatch.setattr(
        sys,
        "argv",
        ["register_guild_plugin_commands.py", "--env-file", str(env_file), "--mode", "safe"],
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "guild"
    assert payload["summary"]["overlap_names"] == ["metricas"]
    assert payload["summary"]["patched"] == ["metricas"]
    assert payload["summary"]["created"] == ["faltas"]
    assert len(patch_calls) == 1
    assert len(create_calls) == 1
    assert delete_calls == []


def test_main_safe_policy_allows_explicit_guild_overlay(tmp_path, monkeypatch, capsys):
    module = _load_script_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DISCORD_APP_ID=app-1",
                "DISCORD_SERVER_ID=guild-1",
                "DISCORD_BOT_TOKEN=token-1",
                "DISCORD_COMMAND_SYNC_POLICY=safe",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "_build_command_payloads",
        lambda _commands_file: [
            {"name": "metricas", "type": 1, "description": "new desc", "options": []},
            {"name": "faltas", "type": 1, "description": "faltas desc", "options": []},
        ],
    )
    monkeypatch.setattr(
        module,
        "_get_existing_global_commands",
        lambda app_id, bot_token: {
            "ok": True,
            "data": [
                {"name": "metricas", "id": "g-1"},
                {"name": "faltas", "id": "g-2"},
            ],
        },
    )
    monkeypatch.setattr(
        module,
        "_get_existing_commands",
        lambda app_id, guild_id, bot_token: {
            "ok": True,
            "data": [{"name": "metricas", "id": "gu-1", "type": 1, "description": "old desc", "options": []}],
        },
    )

    patch_calls = []
    create_calls = []
    monkeypatch.setattr(
        module,
        "_patch_command",
        lambda **kwargs: patch_calls.append(kwargs) or {"ok": True, "status": 200, "data": {}},
    )
    monkeypatch.setattr(
        module,
        "_create_command",
        lambda **kwargs: create_calls.append(kwargs) or {"ok": True, "status": 200, "data": {}},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "register_guild_plugin_commands.py",
            "--env-file",
            str(env_file),
            "--mode",
            "safe",
            "--scope",
            "guild",
        ],
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "guild"
    assert payload["sync_policy"] == "safe"
    assert payload["summary"]["overlap_names"] == ["metricas"]
    assert payload["summary"]["patched"] == ["metricas"]
    assert payload["summary"]["created"] == ["faltas"]
    assert len(patch_calls) == 1
    assert len(create_calls) == 1


def test_main_prunes_overlapping_global_plugin_commands(tmp_path, monkeypatch, capsys):
    module = _load_script_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DISCORD_APP_ID=app-1",
                "DISCORD_SERVER_ID=guild-1",
                "DISCORD_BOT_TOKEN=token-1",
                "DISCORD_COMMAND_SYNC_POLICY=safe",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "_build_command_payloads",
        lambda _commands_file: [
            {"name": "metricas", "type": 1, "description": "metricas desc", "options": []},
            {"name": "faltas", "type": 1, "description": "faltas desc", "options": []},
            {"name": "discord-slash-status", "type": 1, "description": "status desc"},
        ],
    )
    monkeypatch.setattr(
        module,
        "_get_existing_global_commands",
        lambda app_id, bot_token: {
            "ok": True,
            "data": [
                {"name": "metricas", "id": "g-1"},
                {"name": "faltas", "id": "g-2"},
                {"name": "discord-slash-status", "id": "g-3"},
                {"name": "status", "id": "g-4"},
            ],
        },
    )
    monkeypatch.setattr(
        module,
        "_get_existing_commands",
        lambda app_id, guild_id, bot_token: {
            "ok": True,
            "data": [
                {"name": "metricas", "id": "gu-1", "type": 1, "description": "metricas desc", "options": []},
                {"name": "faltas", "id": "gu-2", "type": 1, "description": "faltas desc", "options": []},
                {"name": "discord-slash-status", "id": "gu-3", "type": 1, "description": "status desc"},
            ],
        },
    )

    delete_calls = []
    monkeypatch.setattr(
        module,
        "_delete_global_command",
        lambda **kwargs: delete_calls.append(kwargs) or {"ok": True, "status": 204, "data": {}},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "register_guild_plugin_commands.py",
            "--env-file",
            str(env_file),
            "--mode",
            "safe",
            "--scope",
            "guild",
            "--prune-global-overlaps",
        ],
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "guild"
    assert payload["summary"]["deleted_global"] == [
        "metricas",
        "faltas",
        "discord-slash-status",
    ]
    assert [call["command_id"] for call in delete_calls] == ["g-1", "g-2", "g-3"]
