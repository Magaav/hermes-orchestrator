from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path("/local/plugins/discord-slash-commands/scripts/register_guild_plugin_commands.py")


def _load_script_module():
    module_name = "canonical_discord_slash_register_commands_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load canonical register_guild_plugin_commands.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _seed_cache(
    tmp_path: Path,
    *,
    enabled_commands: list[str],
    custom_commands: list[dict[str, object]] | None = None,
) -> Path:
    cache_root = tmp_path / "agents" / "nodes" / "colmeio" / "workspace" / "plugins" / "discord-slash-commands" / "cache"
    (cache_root / "catalogs").mkdir(parents=True, exist_ok=True)
    (cache_root / "state").mkdir(parents=True, exist_ok=True)
    (cache_root / "catalogs" / "custom_commands.json").write_text(
        json.dumps(
            custom_commands
            or [
                {
                    "name": "faltas",
                    "namespace": "custom",
                    "description": "Gerenciar lista de faltas das lojas",
                    "type": 1,
                    "options": [
                        {
                            "type": 3,
                            "name": "action",
                            "description": "Acao do comando",
                            "required": True,
                            "choices": [{"name": "help", "value": "help"}],
                        }
                    ],
                },
                {
                    "name": "metricas",
                    "namespace": "custom",
                    "description": "Dashboard de métricas Colmeio (somente admin)",
                    "type": 1,
                    "options": [
                        {
                            "type": 3,
                            "name": "action",
                            "description": "Acao do comando",
                            "required": False,
                            "choices": [{"name": "help", "value": "help"}],
                        }
                    ],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cache_root / "state" / "app_scope.json").write_text(
        json.dumps(
            {
                "version": 1,
                "app_id": "app-1",
                "guild_id": "guild-1",
                "enabled_commands": enabled_commands,
                "updated_at": "2026-04-25T00:00:00Z",
                "updated_by_node": "colmeio",
            }
        ),
        encoding="utf-8",
    )
    return cache_root


def test_build_desired_payloads_uses_enabled_global_and_custom_commands_only(tmp_path):
    module = _load_script_module()
    cache_root = _seed_cache(tmp_path, enabled_commands=["slash", "status", "metricas"])

    desired, enabled_names = module._build_desired_payloads(
        cache_root,
        app_id="app-1",
        guild_id="guild-1",
        sync_policy="off",
    )

    assert [item["name"] for item in desired] == ["status", "model", "acl", "slash", "clean", "metricas"]
    assert enabled_names == {"acl", "clean", "metricas", "model", "slash", "status"}


def test_build_desired_payloads_restores_custom_commands_from_node_activation(tmp_path):
    module = _load_script_module()
    cache_root = _seed_cache(tmp_path, enabled_commands=["slash", "status"])
    (cache_root / "state" / "node_activation.json").write_text(
        json.dumps(
            {
                "version": 1,
                "node_name": "colmeio",
                "custom_enabled": ["metricas"],
                "updated_at": "2026-04-27T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    desired, enabled_names = module._build_desired_payloads(
        cache_root,
        app_id="app-1",
        guild_id="guild-1",
        sync_policy="off",
    )

    assert [item["name"] for item in desired] == ["status", "model", "acl", "slash", "clean", "metricas"]
    assert enabled_names == {"acl", "clean", "metricas", "model", "slash", "status"}


def test_build_desired_payloads_skips_status_overlay_when_global_sync_is_on(tmp_path):
    module = _load_script_module()
    cache_root = _seed_cache(tmp_path, enabled_commands=["acl", "slash", "status", "metricas"])

    desired, enabled_names = module._build_desired_payloads(
        cache_root,
        app_id="app-1",
        guild_id="guild-1",
        sync_policy="safe",
    )

    assert [item["name"] for item in desired] == ["acl", "slash", "clean", "metricas"]
    assert enabled_names == {"acl", "clean", "metricas", "model", "slash", "status"}


def test_build_desired_payloads_includes_clean_native_confirm_option(tmp_path):
    module = _load_script_module()
    cache_root = _seed_cache(tmp_path, enabled_commands=["clean", "slash"])

    desired, enabled_names = module._build_desired_payloads(
        cache_root,
        app_id="app-1",
        guild_id="guild-1",
        sync_policy="safe",
    )

    clean = next(item for item in desired if item["name"] == "clean")
    assert "clean" in enabled_names
    assert clean["default_member_permissions"] == "8192"
    assert clean["dm_permission"] is False
    assert clean["options"] == [
        {
            "type": 5,
            "name": "confirm",
            "description": "Confirm deletion of all deletable messages in this channel",
            "required": True,
        }
    ]


def test_build_deploy_plan_uses_patch_create_and_delete_for_managed_guild_commands():
    module = _load_script_module()
    desired = [
        {"name": "status", "type": 1, "description": "New status", "options": []},
        {"name": "slash", "type": 1, "description": "Slash manager", "options": []},
        {"name": "metricas", "type": 1, "description": "Metrics", "options": []},
    ]
    existing = [
        {"id": "guild-status", "name": "status", "type": 1, "description": "Old status", "options": []},
        {"id": "guild-slash", "name": "slash", "type": 1, "description": "Slash manager", "options": []},
        {"id": "guild-acl", "name": "acl", "type": 1, "description": "ACL", "options": []},
        {"id": "guild-slash-status", "name": "discord-slash-status", "type": 1, "description": "Status", "options": []},
    ]

    unchanged, to_patch, to_create, to_delete = module._build_deploy_plan(desired, existing)

    assert [item["name"] for item in unchanged] == ["slash"]
    assert [(current["name"], desired["name"]) for current, desired in to_patch] == [("status", "status")]
    assert [item["name"] for item in to_create] == ["metricas"]
    assert [item["name"] for item in to_delete] == ["acl", "discord-slash-status"]


def test_main_dry_run_reports_guild_scope_from_canonical_cache(tmp_path, monkeypatch, capsys):
    module = _load_script_module()
    cache_root = _seed_cache(tmp_path, enabled_commands=["slash", "status", "metricas"])
    env_file = tmp_path / "agents" / "envs" / "colmeio.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
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

    monkeypatch.setattr(module, "_host_cache_root", lambda node_name: cache_root)
    monkeypatch.setattr(
        module,
        "_api_request",
        lambda **_: {
            "ok": True,
                "status": 200,
                "data": [
                    {"id": "guild-status", "name": "status", "type": 1, "description": "Old status", "options": []},
                    {
                        "id": "guild-slash",
                        "name": "slash",
                        "type": 1,
                        "description": "List and toggle plugin-owned Discord slash commands",
                        "options": [
                            {"type": 3, "name": "command", "description": "Command name to inspect or toggle", "required": False},
                            {"type": 5, "name": "enable", "description": "Enable or disable the selected command", "required": False},
                        ],
                    },
                    {"id": "guild-acl", "name": "acl", "type": 1, "description": "ACL", "options": []},
                    {
                        "id": "guild-slash-status",
                        "name": "discord-slash-status",
                        "type": 1,
                        "description": "Status",
                        "options": [],
                    },
                ],
            },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "register_guild_plugin_commands.py",
            "--env-file",
            str(env_file),
            "--dry-run",
        ],
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["scope"] == "guild"
    assert payload["mode"] == "safe"
    assert payload["cache_root"] == str(cache_root)
    assert payload["to_patch"] == ["status", "acl"]
    assert payload["to_create"] == ["model", "clean", "metricas"]
    assert payload["to_delete"] == ["discord-slash-status"]


def test_main_dry_run_accepts_explicit_cache_root(tmp_path, monkeypatch, capsys):
    module = _load_script_module()
    cache_root = _seed_cache(tmp_path, enabled_commands=["slash", "status", "metricas"])
    env_file = tmp_path / "agents" / "envs" / "wrong-node.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
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
        "_api_request",
        lambda **_: {
            "ok": True,
            "status": 200,
            "data": [],
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "register_guild_plugin_commands.py",
            "--env-file",
            str(env_file),
            "--cache-root",
            str(cache_root),
            "--dry-run",
        ],
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["cache_root"] == str(cache_root)
    assert payload["to_create"] == ["status", "model", "acl", "slash", "clean", "metricas"]


def test_main_reconciles_using_patch_post_delete_only(tmp_path, monkeypatch, capsys):
    module = _load_script_module()
    cache_root = _seed_cache(tmp_path, enabled_commands=["slash", "status", "metricas"])
    env_file = tmp_path / "agents" / "envs" / "colmeio.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
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

    calls: list[tuple[str, str]] = []

    def _fake_api_request(*, method: str, url: str, bot_token: str, payload=None):
        calls.append((method, url))
        if method == "GET":
            return {
                "ok": True,
                "status": 200,
                "data": [
                    {"id": "guild-status", "name": "status", "type": 1, "description": "Old status", "options": []},
                    {
                        "id": "guild-slash",
                        "name": "slash",
                        "type": 1,
                        "description": "List and toggle plugin-owned Discord slash commands",
                        "options": [
                            {"type": 3, "name": "command", "description": "Command name to inspect or toggle", "required": False},
                            {"type": 5, "name": "enable", "description": "Enable or disable the selected command", "required": False},
                        ],
                    },
                    {"id": "guild-acl", "name": "acl", "type": 1, "description": "ACL", "options": []},
                    {
                        "id": "guild-slash-status",
                        "name": "discord-slash-status",
                        "type": 1,
                        "description": "Status",
                        "options": [],
                    },
                ],
            }
        return {"ok": True, "status": 200, "data": {"id": "ok", "payload": payload}}

    monkeypatch.setattr(module, "_host_cache_root", lambda node_name: cache_root)
    monkeypatch.setattr(module, "_api_request", _fake_api_request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "register_guild_plugin_commands.py",
            "--env-file",
            str(env_file),
        ],
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["scope"] == "guild"
    assert payload["summary"]["patched"] == ["status", "acl"]
    assert payload["summary"]["created"] == ["model", "clean", "metricas"]
    assert payload["summary"]["deleted"] == ["discord-slash-status"]
    methods = [method for method, _url in calls]
    assert methods[:2] == ["GET", "GET"]
    assert methods.count("PATCH") == 2
    assert methods.count("POST") == 3
    assert methods.count("DELETE") >= 1
    assert "PUT" not in [method for method, _url in calls]


def test_main_safe_sync_deletes_guild_status_to_avoid_duplicate(tmp_path, monkeypatch, capsys):
    module = _load_script_module()
    cache_root = _seed_cache(tmp_path, enabled_commands=["acl", "slash", "status"])
    env_file = tmp_path / "agents" / "envs" / "paracelsus.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "\n".join(
            [
                "DISCORD_APP_ID=app-9",
                "DISCORD_SERVER_ID=guild-9",
                "DISCORD_BOT_TOKEN=token-9",
                "DISCORD_COMMAND_SYNC_POLICY=safe",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    calls: list[tuple[str, str]] = []

    def _fake_api_request(*, method: str, url: str, bot_token: str, payload=None):
        calls.append((method, url))
        if method == "GET":
            return {
                "ok": True,
                "status": 200,
                "data": [
                    {"id": "guild-status", "name": "status", "type": 1, "description": "Old status", "options": []},
                    {
                        "id": "guild-slash",
                        "name": "slash",
                        "type": 1,
                        "description": "List and toggle plugin-owned Discord slash commands",
                        "options": [
                            {"type": 3, "name": "command", "description": "Command name to inspect or toggle", "required": False},
                            {"type": 5, "name": "enable", "description": "Enable or disable the selected command", "required": False},
                        ],
                    },
                    {
                        "id": "guild-acl",
                        "name": "acl",
                        "type": 1,
                        "description": "Manage Discord command and channel ACL policy",
                        "options": [
                            {
                                "type": 3,
                                "name": "action",
                                "description": "help, command ou channel",
                                "required": False,
                                "choices": [
                                    {"name": "help", "value": "help"},
                                    {"name": "command", "value": "command"},
                                    {"name": "channel", "value": "channel"},
                                ],
                            },
                            {
                                "type": 3,
                                "name": "args",
                                "description": "Additional ACL arguments",
                                "required": False,
                            },
                        ],
                    },
                ],
            }
        return {"ok": True, "status": 200, "data": {"id": "ok", "payload": payload}}

    monkeypatch.setattr(module, "_host_cache_root", lambda node_name: cache_root)
    monkeypatch.setattr(module, "_api_request", _fake_api_request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "register_guild_plugin_commands.py",
            "--env-file",
            str(env_file),
        ],
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["scope"] == "guild"
    assert payload["summary"]["patched"] == ["acl"]
    assert payload["summary"]["created"] == ["clean"]
    assert payload["summary"]["deleted"] == ["status"]
    assert [method for method, _url in calls] == ["GET", "PATCH", "POST", "DELETE"]
