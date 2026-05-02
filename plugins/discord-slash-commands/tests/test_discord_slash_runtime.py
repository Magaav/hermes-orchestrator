from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import types
from unittest import mock


PACKAGE_ROOT = Path("/local/plugins/discord-slash-commands")
CHANNEL_ACL_ROOT = Path("/local/plugins/discord-slash-commands/channel_acl")


def _load_paths_module():
    spec = importlib.util.spec_from_file_location("discord_slash_paths_test", PACKAGE_ROOT / "paths.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_channel_acl_module():
    spec = importlib.util.spec_from_file_location("discord_channel_acl_test", CHANNEL_ACL_ROOT / "handler.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "_cache"):
        module._cache = {}
    return module


def test_paths_fallback_uses_node_root_instead_of_host_workspace() -> None:
    paths = _load_paths_module()

    with mock.patch.dict(
        "os.environ",
        {
            "HERMES_NODE_ROOT": "/local/agents/nodes/orchestrator",
            "NODE_NAME": "orchestrator",
        },
        clear=True,
    ):
        assert paths.resolve_runtime_cache_root() == Path(
            "/local/agents/nodes/orchestrator/workspace/plugins/discord-slash-commands/cache"
        )


def test_paths_fallback_does_not_create_top_level_workspace_on_host() -> None:
    paths = _load_paths_module()

    with mock.patch.dict("os.environ", {"HOME": "/tmp/plain-host-home"}, clear=True):
        assert paths.resolve_runtime_cache_root() == Path(
            "/local/.hermes/discord-slash-commands/cache"
        )


def test_resolve_acl_path_uses_canonical_governance_acl_json(tmp_path) -> None:
    paths = _load_paths_module()

    with mock.patch.dict("os.environ", {"HERMES_DISCORD_SLASH_CACHE_ROOT": str(_cache_root(tmp_path))}, clear=True):
        assert paths.resolve_acl_path() == _cache_root(tmp_path) / "governance" / "acl.json"


def _cache_root(tmp_path: Path) -> Path:
    return tmp_path / "workspace" / "plugins" / "discord-slash-commands" / "cache"


def _seed_state(tmp_path: Path, *, enabled_commands: list[str] | None = None) -> Path:
    cache_root = _cache_root(tmp_path)
    (cache_root / "catalogs").mkdir(parents=True, exist_ok=True)
    (cache_root / "state").mkdir(parents=True, exist_ok=True)
    (cache_root / "catalogs" / "custom_commands.json").write_text(
        json.dumps(
            [
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
                            "required": False,
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
            ]
        ),
        encoding="utf-8",
    )
    (cache_root / "state" / "node_activation.json").write_text(
        json.dumps({"version": 1, "node_name": "colmeio", "custom_enabled": [], "updated_at": "2026-04-25T00:00:00Z"}),
        encoding="utf-8",
    )
    (cache_root / "state" / "app_scope.json").write_text(
        json.dumps(
            {
                "version": 1,
                "app_id": "app-1",
                "guild_id": "guild-1",
                "enabled_commands": enabled_commands or ["acl", "slash", "status"],
                "updated_at": "2026-04-25T00:00:00Z",
                "updated_by_node": "colmeio",
            }
        ),
        encoding="utf-8",
    )
    return cache_root


def _load_runtime():
    package_name = "canonical_discord_slash_runtime_testpkg"
    for key in list(sys.modules):
        if key == package_name or key.startswith(package_name + "."):
            sys.modules.pop(key, None)
    spec = importlib.util.spec_from_file_location(
        package_name,
        PACKAGE_ROOT / "__init__.py",
        submodule_search_locations=[str(PACKAGE_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load slash plugin package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    spec.loader.exec_module(module)
    return importlib.import_module(f"{package_name}.runtime")


def _patch_governance_runtime(runtime, monkeypatch):
    class _FakeChannelAcl:
        def normalize_to_channel_skill(self, source, message):
            return "PASSTHROUGH", message

        def check_command_allowed(self, channel_id, command, thread_id=None, parent_id=None):
            return True, ""

        def enforce_channel_model(self, source, turn_route):
            return dict(turn_route)

    monkeypatch.setattr(runtime, "load_channel_acl_module", lambda: _FakeChannelAcl())
    monkeypatch.setattr(runtime, "_authorize_interaction_sync", lambda interaction, command_name: {"allowed": True})


def test_register_plugin_registers_commands_and_hook(monkeypatch, tmp_path):
    _seed_state(tmp_path)
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    calls = []
    hooks = []

    class _FakeCtx:
        def register_command(self, name, handler, description="", args_hint=""):
            calls.append((name, handler, description, args_hint))

        def register_hook(self, name, callback):
            hooks.append((name, callback))

    runtime.register_plugin(_FakeCtx())

    assert [name for name, *_rest in calls] == [
        "metricas",
        "faltas",
        "acl",
        "clean",
        "scientific-paper-meta-analysis",
        "slash",
    ]
    assert {name for name, _callback in hooks} == {"pre_gateway_dispatch"}


def test_clean_requires_discord_native_interaction(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "clean", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    reply = asyncio.run(runtime.handle_clean("confirm:true"))

    assert "slash command nativo do Discord" in reply


def test_clean_requires_confirm(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "clean", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()
    interaction = SimpleNamespace(data={"options": [{"name": "confirm", "value": False}]})

    reply = asyncio.run(runtime._execute_clean("", interaction=interaction))

    assert "confirm:true" in reply


def test_clean_uses_bulk_delete_for_recent_messages(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "clean", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    now = datetime.now(timezone.utc)
    messages = [
        SimpleNamespace(id=idx, created_at=now - timedelta(minutes=idx), deleted=False)
        for idx in range(150)
    ]

    class _FakeChannel:
        id = 123
        name = "geral"
        parent_id = None

        def __init__(self):
            self.bulk_calls = []

        async def history(self, limit=None, oldest_first=False):
            for msg in messages:
                yield msg

        async def delete_messages(self, chunk):
            self.bulk_calls.append(list(chunk))
            for msg in chunk:
                msg.deleted = True

        def permissions_for(self, member):
            return SimpleNamespace(manage_messages=True)

    channel = _FakeChannel()
    interaction = SimpleNamespace(
        channel=channel,
        guild=SimpleNamespace(me=SimpleNamespace(id=99)),
        user=SimpleNamespace(id="123"),
        permissions=SimpleNamespace(value=8),
        data={"options": [{"name": "confirm", "value": True}]},
        response=SimpleNamespace(is_done=lambda: True),
    )
    gateway = SimpleNamespace(adapters={"discord": SimpleNamespace(_client=SimpleNamespace(user=SimpleNamespace(id=99)))})
    source = SimpleNamespace(platform="discord", chat_id="123")

    reply = asyncio.run(runtime._execute_clean("", gateway=gateway, source=source, interaction=interaction))

    assert "apagadas: `150`" in reply
    assert [len(chunk) for chunk in channel.bulk_calls] == [100, 50]
    assert all(msg.deleted for msg in messages)


def test_clean_bot_permission_check_accepts_manage_messages_bitmask(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "clean", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "paracelsus")
    runtime = _load_runtime()

    class _FakeChannel:
        def permissions_for(self, member):
            return SimpleNamespace(value=0x2000)

    adapter = SimpleNamespace(_client=SimpleNamespace(user=SimpleNamespace(id=99)))
    interaction = SimpleNamespace(
        guild=SimpleNamespace(me=SimpleNamespace(id=99)),
    )

    ok, reason = asyncio.run(runtime._bot_can_clean(adapter, interaction, _FakeChannel()))

    assert ok is True
    assert reason == ""


def test_command_definitions_expose_global_and_custom_namespaces(monkeypatch, tmp_path):
    _seed_state(tmp_path)
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    runtime = _load_runtime()

    assert runtime.get_command_definition("status")["namespace"] == "global"
    assert runtime.get_command_definition("acl")["namespace"] == "global"
    assert runtime.get_command_definition("slash")["namespace"] == "global"
    assert runtime.get_command_definition("clean")["namespace"] == "global"
    assert runtime.get_command_definition("metricas")["namespace"] == "custom"
    assert runtime.get_command_definition("faltas")["namespace"] == "custom"


def test_handle_slash_lists_grouped_global_and_custom_commands(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    result = asyncio.run(runtime.handle_slash(""))

    assert "Comandos `global`" in result
    assert "Comandos `custom`" in result
    assert "/status: enabled" in result
    assert "/metricas: disabled" in result
    assert "/slash: enabled" in result


def test_load_app_scope_rehydrates_custom_commands_from_node_activation(monkeypatch, tmp_path):
    cache_root = _seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

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
    (cache_root / "state" / "app_scope.json").write_text(
        json.dumps(
            {
                "version": 1,
                "app_id": "app-1",
                "guild_id": "guild-1",
                "enabled_commands": ["acl", "slash", "status"],
                "updated_at": "2026-04-27T11:59:00Z",
                "updated_by_node": "colmeio",
            }
        ),
        encoding="utf-8",
    )

    scope = runtime.load_app_scope()

    assert "metricas" in scope["enabled_commands"]
    assert "clean" in scope["enabled_commands"]


def test_handle_metricas_help_from_interaction_option(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "metricas"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()
    runtime.handle_pre_gateway_dispatch(
        event=SimpleNamespace(
            source=SimpleNamespace(platform="discord"),
            raw_message=SimpleNamespace(data={"options": [{"name": "action", "value": "help"}]}),
            text="/metricas",
            get_command=lambda: "metricas",
        ),
        gateway=object(),
    )

    result = asyncio.run(runtime.handle_metricas(""))

    assert "Uso do `/metricas`" in result


def test_handle_metricas_runs_dashboard_script_without_legacy_bridge(monkeypatch, tmp_path):
    cache_root = _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "metricas"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            payload = {
                "ok": True,
                "text": "## :bar_chart: Colmeio Metrics\n\nTudo certo.",
            }
            return json.dumps(payload, ensure_ascii=False).encode("utf-8"), b""

    calls = []

    async def _fake_create_subprocess_exec(*cmd, **kwargs):
        calls.append(list(cmd))
        return _FakeProc()

    script_path = tmp_path / "metrics_logger.py"
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "resolve_metrics_script_path", lambda: script_path)
    monkeypatch.setattr(runtime, "resolve_python_bin", lambda **kwargs: "/usr/bin/python3")
    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

    result = asyncio.run(runtime.handle_metricas("dias:7 formato:text skill:colmeio-lista-de-faltas"))

    assert "Colmeio Metrics" in result
    assert calls
    assert calls[0][:3] == ["/usr/bin/python3", str(script_path), "dashboard"]
    assert "--days" in calls[0]
    assert "--skill-name" in calls[0]


def test_authorize_interaction_sync_reads_roles_from_interaction_member(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "metricas"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    acl_path = tmp_path / "colmeio_acl.json"
    acl_path.write_text(
        json.dumps(
            {
                "hierarchy": [
                    {"role_id": "1228380823976149023", "role_name": "admin"},
                    {"role_id": "1487814333265088663", "role_name": "gerente"},
                    {"role_id": "@everyone", "role_name": "@everyone"},
                ],
                "commands": {"metricas": {"min_role": "1487814333265088663"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "resolve_acl_path", lambda: acl_path)

    interaction = SimpleNamespace(
        guild=object(),
        user=SimpleNamespace(id="123"),
        member=SimpleNamespace(roles=[SimpleNamespace(id=1487814333265088663, name="gerente")]),
    )

    result = runtime._authorize_interaction_sync(interaction, "metricas")

    assert result["allowed"] is True


def test_authorize_interaction_sync_fallback_allows_literal_admin_role_by_name(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "metricas"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    acl_path = tmp_path / "colmeio_acl.json"
    acl_path.write_text(
        json.dumps(
            {
                "hierarchy": [
                    {"role_id": "@everyone", "role_name": "@everyone"},
                ],
                "commands": {"status": {"min_role": "@everyone"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "resolve_acl_path", lambda: acl_path)

    guild = SimpleNamespace(get_role=lambda role_id: SimpleNamespace(id=role_id, name="Admin") if int(role_id) == 10 else None)
    interaction = SimpleNamespace(
        guild=guild,
        user=SimpleNamespace(id="123"),
        member=SimpleNamespace(roles=[10]),
    )

    result = runtime._authorize_interaction_sync(interaction, "metricas")

    assert result["allowed"] is True
    assert result["bypass_governance"] is True
    assert result["decision"] == "admin_bypass"


def test_authorize_interaction_sync_fallback_allows_admin_role_from_raw_member_ids(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "metricas"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    acl_path = tmp_path / "colmeio_acl.json"
    acl_path.write_text(
        json.dumps(
            {
                "hierarchy": [
                    {"role_id": "10", "role_name": "admin"},
                    {"role_id": "@everyone", "role_name": "@everyone"},
                ],
                "commands": {"status": {"min_role": "@everyone"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "resolve_acl_path", lambda: acl_path)

    guild = SimpleNamespace(get_role=lambda role_id: SimpleNamespace(id=role_id, name="Admin") if role_id == 10 else None)
    interaction = SimpleNamespace(
        guild=guild,
        user=SimpleNamespace(id="123"),
        member={"roles": ["10"]},
    )

    result = runtime._authorize_interaction_sync(interaction, "baoyu-infographic")

    assert result["allowed"] is True
    assert result["bypass_governance"] is True
    assert result["decision"] == "admin_bypass"


def test_authorize_interaction_sync_fallback_reads_role_iterables(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "metricas"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    acl_path = tmp_path / "colmeio_acl.json"
    acl_path.write_text(
        json.dumps(
            {
                "hierarchy": [
                    {"role_id": "10", "role_name": "admin"},
                    {"role_id": "@everyone", "role_name": "@everyone"},
                ],
                "commands": {"status": {"min_role": "@everyone"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "resolve_acl_path", lambda: acl_path)

    class _RoleBox:
        def __iter__(self):
            yield SimpleNamespace(id=10, name="Admin")

    interaction = SimpleNamespace(
        guild=object(),
        user=SimpleNamespace(id="123"),
        member=SimpleNamespace(roles=_RoleBox()),
    )

    result = runtime._authorize_interaction_sync(interaction, "baoyu-infographic")

    assert result["allowed"] is True
    assert result["bypass_governance"] is True


def test_authorize_interaction_sync_fallback_reads_roles_from_interaction_user(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "metricas"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    acl_path = tmp_path / "colmeio_acl.json"
    acl_path.write_text(
        json.dumps(
            {
                "hierarchy": [
                    {"role_id": "", "role_name": "admin"},
                    {"role_id": "@everyone", "role_name": "@everyone"},
                ],
                "commands": {"status": {"min_role": "@everyone"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "resolve_acl_path", lambda: acl_path)

    interaction = SimpleNamespace(
        guild=SimpleNamespace(get_role=lambda role_id: None, get_member=lambda user_id: None),
        user=SimpleNamespace(id="123", roles=[SimpleNamespace(id=10, name="Admin")]),
    )

    result = runtime._authorize_interaction_sync(interaction, "metricas")

    assert result["allowed"] is True
    assert result["bypass_governance"] is True


def test_authorize_interaction_sync_fallback_allows_administrator_permission(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "metricas"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    acl_path = tmp_path / "colmeio_acl.json"
    acl_path.write_text(
        json.dumps(
            {
                "hierarchy": [
                    {"role_id": "@everyone", "role_name": "@everyone"},
                ],
                "commands": {"status": {"min_role": "@everyone"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "resolve_acl_path", lambda: acl_path)

    interaction = SimpleNamespace(
        guild=object(),
        user=SimpleNamespace(id="123"),
        permissions=SimpleNamespace(administrator=True),
    )

    result = runtime._authorize_interaction_sync(interaction, "metricas")

    assert result["allowed"] is True
    assert result["bypass_governance"] is True


def test_authorize_interaction_sync_fallback_allows_administrator_permission_value(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "metricas"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    acl_path = tmp_path / "colmeio_acl.json"
    acl_path.write_text(
        json.dumps(
            {
                "hierarchy": [
                    {"role_id": "@everyone", "role_name": "@everyone"},
                ],
                "commands": {"status": {"min_role": "@everyone"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "resolve_acl_path", lambda: acl_path)

    interaction = SimpleNamespace(
        guild=object(),
        user=SimpleNamespace(id="123"),
        permissions=SimpleNamespace(value=8),
    )

    result = runtime._authorize_interaction_sync(interaction, "clean")

    assert result["allowed"] is True
    assert result["bypass_governance"] is True


def test_authorize_interaction_sync_fallback_unmapped_command_teaches_acl_mapping(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "metricas"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    acl_path = tmp_path / "colmeio_acl.json"
    acl_path.write_text(
        json.dumps(
            {
                "hierarchy": [
                    {"role_id": "@everyone", "role_name": "@everyone"},
                ],
                "commands": {"status": {"min_role": "@everyone"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "resolve_acl_path", lambda: acl_path)

    interaction = SimpleNamespace(
        guild=SimpleNamespace(get_role=lambda role_id: None),
        user=SimpleNamespace(id="123"),
        member=SimpleNamespace(roles=[]),
    )

    result = runtime._authorize_interaction_sync(interaction, "metricas")

    assert result["allowed"] is False
    assert "/acl command command:metricas role:admin" in result["message"]
    assert "Administrator" in result["message"]


def test_authorize_interaction_sync_allows_installed_skill_command_fallback(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "paracelsus")
    runtime = _load_runtime()

    acl_path = tmp_path / "paracelsus_acl.json"
    acl_path.write_text(
        json.dumps(
            {
                "hierarchy": [
                    {"role_id": "10", "role_name": "admin"},
                    {"role_id": "@everyone", "role_name": "@everyone"},
                ],
                "commands": {"status": {"min_role": "@everyone"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "resolve_acl_path", lambda: acl_path)

    class _FakeRoleAcl:
        @staticmethod
        def normalize_command_name(value):
            return str(value or "").strip().lower().lstrip("/")

        @staticmethod
        def load_acl(path):
            return json.loads(acl_path.read_text(encoding="utf-8"))

        @staticmethod
        def build_rank_map(hierarchy):
            return {"10": 0, "name:admin": 0, "@everyone": 1}

        @staticmethod
        def build_role_label_map(hierarchy):
            return {"10": "admin", "name:admin": "admin", "@everyone": "@everyone"}

        @staticmethod
        def _tokens_from_roles(roles):
            return {"@everyone"}

        @staticmethod
        def _apply_user_override_tokens(actor_tokens, acl, actor_user_id):
            return set(actor_tokens)

        @staticmethod
        def _resolve_top_role_name(actor_tokens, rank_map, role_labels):
            return "@everyone"

        @staticmethod
        def _admin_tokens_from_acl(acl):
            return {"10", "name:admin"}

        @staticmethod
        def resolve_command_acl_config(acl, command_name):
            command = str(command_name or "").strip().lower().lstrip("/")
            if command == "baoyu-infographic":
                return {"min_role": "@everyone", "notes": "implicit installed skill command fallback"}, True
            return None, False

        @staticmethod
        def normalize_role_token(value):
            return str(value or "").strip()

        @staticmethod
        def role_display_name(value):
            return str(value or "").strip()

        @staticmethod
        def _resolve_actor_rank(actor_tokens, rank_map):
            return 1

        @staticmethod
        def _resolve_required_rank(min_role, rank_map):
            return 1

    monkeypatch.setattr(runtime, "load_role_acl_module", lambda: _FakeRoleAcl())

    interaction = SimpleNamespace(
        guild=object(),
        user=SimpleNamespace(id="123"),
        member=SimpleNamespace(roles=[]),
    )

    result = runtime._authorize_interaction_sync(interaction, "baoyu-infographic")

    assert result["allowed"] is True


def test_handle_faltas_help_uses_custom_help_text(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "faltas"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    result = asyncio.run(runtime.handle_faltas("help"))

    assert "Uso do `/faltas`" in result


def test_handle_acl_help_returns_usage(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    result = asyncio.run(runtime.handle_acl("help"))

    assert "Uso do `/acl`" in result


def test_handle_acl_command_falls_back_to_builtin_updater(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    acl_path = tmp_path / "colmeio_acl.json"
    acl_path.write_text(
        json.dumps(
            {
                "version": 1,
                "node": "colmeio",
                "hierarchy": [{"role_id": "@everyone", "role_name": "@everyone"}],
                "commands": {"status": {"min_role": "@everyone"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "resolve_acl_path", lambda: acl_path)

    def _missing_role_acl_module():
        raise FileNotFoundError("legacy helper missing")

    monkeypatch.setattr(runtime, "load_role_acl_module", _missing_role_acl_module)

    result = asyncio.run(runtime.handle_acl("command command:metricas role:gerente"))
    stored = json.loads(acl_path.read_text(encoding="utf-8"))

    assert "ACL de comando atualizado com sucesso" in result
    assert stored["commands"]["metricas"]["min_role"] == "gerente"
    assert any(str(item.get("role_name") or "") == "gerente" for item in stored["hierarchy"])


def test_handle_acl_command_short_form_updates_acl(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    acl_path = tmp_path / "colmeio_acl.json"
    acl_path.write_text(
        json.dumps(
            {
                "version": 1,
                "node": "colmeio",
                "hierarchy": [{"role_id": "@everyone", "role_name": "@everyone"}],
                "commands": {"status": {"min_role": "@everyone"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "resolve_acl_path", lambda: acl_path)

    def _missing_role_acl_module():
        raise FileNotFoundError("legacy helper missing")

    monkeypatch.setattr(runtime, "load_role_acl_module", _missing_role_acl_module)

    result = asyncio.run(runtime.handle_acl("command:faltas role:gerente"))
    stored = json.loads(acl_path.read_text(encoding="utf-8"))

    assert "ACL de comando atualizado com sucesso" in result
    assert stored["commands"]["faltas"]["min_role"] == "gerente"
    assert any(str(item.get("role_name") or "") == "gerente" for item in stored["hierarchy"])


def test_dispatch_normalized_command_routes_scientific_pipeline(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "scientific-paper-meta-analysis"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "paracelsus")
    runtime = _load_runtime()

    class _FakeChannelAcl:
        async def dispatch_normalized_command(self, source, message):
            return False, ""

    replies = []
    typing_events = []
    monkeypatch.setattr(runtime, "load_channel_acl_module", lambda: _FakeChannelAcl())
    monkeypatch.setattr(runtime, "_schedule_gateway_reply", lambda gateway, source, message: replies.append(message))
    async def _fake_pipeline(raw_args):
        return f"report for {raw_args}"
    monkeypatch.setattr(runtime, "_execute_scientific_pipeline", _fake_pipeline)

    class _FakeAdapter:
        async def send_typing(self, chat_id, metadata=None):
            typing_events.append(("start", chat_id, metadata))

        async def stop_typing(self, chat_id):
            typing_events.append(("stop", chat_id, None))

    asyncio.run(
        runtime._dispatch_normalized_command(
            gateway=SimpleNamespace(adapters={"discord": _FakeAdapter()}),
            source=SimpleNamespace(platform="discord", chat_id="c1", thread_id=None),
            message_text="/scientific-paper-meta-analysis Benefícios da dieta carnívora",
        )
    )

    assert replies == ["report for Benefícios da dieta carnívora"]
    assert typing_events == [("start", "c1", None), ("stop", "c1", None)]


def test_handle_pre_gateway_dispatch_scientific_command_schedules_skill_dispatch(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "scientific-paper-meta-analysis"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "paracelsus")
    runtime = _load_runtime()
    _patch_governance_runtime(runtime, monkeypatch)

    scheduled_messages = []

    async def _fake_dispatch(gateway, source, message_text):
        scheduled_messages.append(message_text)

    class _FakeLoop:
        def create_task(self, coro):
            asyncio.run(coro)
            return None

    monkeypatch.setattr(runtime, "_dispatch_normalized_command", _fake_dispatch)
    monkeypatch.setattr(runtime.asyncio, "get_running_loop", lambda: _FakeLoop())

    event = SimpleNamespace(
        text='/scientific-paper-meta-analysis query:"Benefícios da dieta carnívora"',
        source=SimpleNamespace(platform="discord", chat_id="c1", thread_id=None, chat_id_alt=None),
        raw_message=None,
        get_command=lambda: "scientific-paper-meta-analysis",
    )

    result = runtime.handle_pre_gateway_dispatch(event=event, gateway=object())

    assert result == {"action": "skip", "reason": "scientific_skill_dispatch"}
    assert scheduled_messages == ['/scientific-paper-meta-analysis query:"Benefícios da dieta carnívora"']


def test_handle_scientific_paper_meta_analysis_returns_pipeline_response(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "scientific-paper-meta-analysis"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "paracelsus")
    runtime = _load_runtime()

    async def _fake_pipeline(raw_args):
        return f"pipeline:{raw_args}"
    monkeypatch.setattr(runtime, "_execute_scientific_pipeline", _fake_pipeline)

    result = asyncio.run(runtime.handle_scientific_paper_meta_analysis('query:"GLP-1 agonists"'))

    assert result == 'pipeline:query:"GLP-1 agonists"'


def test_handle_pre_gateway_message_scientific_dispatches_runtime(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "scientific-paper-meta-analysis"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "paracelsus")
    runtime = _load_runtime()

    dispatched = []

    async def _fake_dispatch(gateway, source, message_text):
        dispatched.append((gateway, source, message_text))

    gateway = object()
    source = SimpleNamespace(platform="discord", chat_id="c1", thread_id=None)
    monkeypatch.setattr(runtime, "_dispatch_normalized_command", _fake_dispatch)

    result = asyncio.run(
        runtime.handle_pre_gateway_message(
            platform="discord",
            source=source,
            message='/scientific-paper-meta-analysis query:"GLP-1 agonists"',
            gateway=gateway,
        )
    )

    assert result == {"decision": "handled", "message": "", "already_replied": True}
    assert dispatched == [(gateway, source, '/scientific-paper-meta-analysis query:"GLP-1 agonists"')]


def test_resolve_acl_raw_args_supports_structured_interaction_options(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    runtime = _load_runtime()

    interaction = SimpleNamespace(
        data={
            "options": [
                {"name": "action", "value": "channel"},
                {"name": "channel", "value": "1497340589191204898"},
                {"name": "mode", "value": "specific"},
                {"name": "model_key", "value": "gpt54"},
                {"name": "allowed_commands", "value": "scientific-paper-meta-analysis"},
                {"name": "allowed_skills", "value": "scientific-paper-meta-analysis"},
                {"name": "always_allowed_commands", "value": "status"},
                {"name": "default_action", "value": "command:scientific-paper-meta-analysis"},
                {"name": "instructions", "value": "Canal dedicado a meta-analysis cientifica"},
            ]
        }
    )

    result = runtime._resolve_acl_raw_args("", interaction)

    assert result == (
        'channel channel:1497340589191204898 mode:specific model_key:gpt54 '
        'allowed_commands:scientific-paper-meta-analysis '
        'allowed_skills:scientific-paper-meta-analysis '
        'always_allowed_commands:status '
        'default_action:command:scientific-paper-meta-analysis '
        'instructions:"Canal dedicado a meta-analysis cientifica"'
    )


def test_resolve_acl_raw_args_inferrs_command_action_from_native_options(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    runtime = _load_runtime()

    interaction = SimpleNamespace(
        data={
            "options": [
                {"name": "command", "value": "faltas"},
                {"name": "role", "value": "gerente"},
            ]
        }
    )

    result = runtime._resolve_acl_raw_args("", interaction)

    assert result == "command command:faltas role:gerente"


def test_resolve_acl_raw_args_inferrs_channel_action_from_native_options(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    runtime = _load_runtime()

    interaction = SimpleNamespace(
        data={
            "options": [
                {"name": "channel", "value": "1497340589191204898"},
                {"name": "mode", "value": "default"},
            ]
        }
    )

    result = runtime._resolve_acl_raw_args("", interaction)

    assert result == "channel channel:1497340589191204898 mode:default"


def test_handle_slash_toggles_custom_command_and_updates_state(monkeypatch, tmp_path):
    cache_root = _seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    monkeypatch.setenv("DISCORD_APP_ID", "app-1")
    monkeypatch.setenv("DISCORD_SERVER_ID", "guild-1")
    runtime = _load_runtime()

    async def _fake_reconcile():
        return "Discord commands reconciled."

    monkeypatch.setattr(runtime, "_mirror_scope_payload", lambda payload: ["colmeio", "orchestrator"])
    monkeypatch.setattr(runtime, "_reconcile_registered_commands", _fake_reconcile)

    result = asyncio.run(runtime.handle_slash("command:metricas enable:true"))
    app_scope = json.loads((cache_root / "state" / "app_scope.json").read_text(encoding="utf-8"))
    node_activation = json.loads((cache_root / "state" / "node_activation.json").read_text(encoding="utf-8"))

    assert "metricas" in app_scope["enabled_commands"]
    assert node_activation["custom_enabled"] == ["metricas"]
    assert "scope nodes: colmeio, orchestrator" in result


def test_handle_slash_cannot_disable_slash(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    runtime = _load_runtime()

    result = asyncio.run(runtime.handle_slash("command:slash enable:false"))

    assert "sempre habilitado" in result


def test_mirror_scope_payload_writes_shared_app_scope_for_peers(monkeypatch, tmp_path):
    _seed_state(tmp_path)
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    runtime = _load_runtime()
    agents_root = tmp_path / "agents" / "nodes"
    real_path = Path

    def _fake_path(raw):
        if str(raw) == "/local/agents/nodes":
            return agents_root
        return real_path(raw)

    monkeypatch.setattr(runtime, "Path", _fake_path)
    monkeypatch.setattr(runtime, "_peer_nodes_for_scope", lambda app_id, guild_id: ["colmeio", "orchestrator"])

    payload = {
        "version": 1,
        "app_id": "1490701435095089312",
        "guild_id": "1228043080167329853",
        "enabled_commands": ["acl", "slash", "status", "metricas"],
        "updated_at": "2026-04-25T00:00:00Z",
        "updated_by_node": "colmeio",
    }

    mirrored = runtime._mirror_scope_payload(payload)

    assert mirrored == ["colmeio", "orchestrator"]
    for node_name in mirrored:
        path = (
            agents_root
            / node_name
            / "workspace"
            / "plugins"
            / "discord-slash-commands"
            / "cache"
            / "state"
            / "app_scope.json"
        )
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["enabled_commands"] == ["acl", "slash", "status", "metricas"]


def test_handle_pre_gateway_dispatch_status_help_and_fallback(monkeypatch, tmp_path):
    cache_root = _seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()
    _patch_governance_runtime(runtime, monkeypatch)

    replies = []
    monkeypatch.setattr(runtime, "_schedule_gateway_reply", lambda gateway, source, message: replies.append(message))

    gateway = SimpleNamespace(
        adapters={"discord": object()},
        _running_agents={},
        session_store=SimpleNamespace(
            get_or_create_session=lambda source: SimpleNamespace(
                session_id="sess-1",
                created_at=SimpleNamespace(strftime=lambda fmt: "2026-04-24 17:40"),
                updated_at=SimpleNamespace(strftime=lambda fmt: "2026-04-24 17:41"),
                total_tokens=1234,
            )
        ),
        _session_key_for_source=lambda source: "session:c1:u1",
        _session_db=SimpleNamespace(get_session_title=lambda session_id: "Fila faltas loja1"),
        _resolve_session_agent_runtime=lambda source=None: ("MiniMax-M2.7", {"provider": "minimax"}),
    )
    source = SimpleNamespace(platform="discord", chat_id="c1", thread_id=None, chat_id_alt=None, user_id="u1")
    event = SimpleNamespace(
        text="/status help",
        source=source,
        raw_message=SimpleNamespace(guild=object(), user=SimpleNamespace(id="1"), data={}),
        get_command=lambda: "status",
        channel_prompt="",
    )

    result = runtime.handle_pre_gateway_dispatch(event=event, gateway=gateway)

    assert result == {"action": "skip", "reason": "status_override"}
    assert replies
    assert "Uso do `/status`" in replies[0]

    (cache_root / "state" / "app_scope.json").write_text(
        json.dumps(
            {
                "version": 1,
                    "app_id": "app-1",
                    "guild_id": "guild-1",
                    "enabled_commands": ["acl", "slash"],
                    "disabled_commands": ["status"],
                    "updated_at": "2026-04-25T00:00:00Z",
                    "updated_by_node": "colmeio",
                }
        ),
        encoding="utf-8",
    )
    replies.clear()
    event.text = "/status"

    result = runtime.handle_pre_gateway_dispatch(event=event, gateway=gateway)

    assert result == {"action": "skip", "reason": "command_disabled"}
    assert replies == ["🚫 `/status` está desabilitado neste node. Use `/slash command:status enable:true`."]


def test_execute_model_switch_records_model_catalog_and_session_override(monkeypatch, tmp_path):
    cache_root = _seed_state(tmp_path, enabled_commands=["acl", "model", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    class _FakeModelInfo:
        max_output = 4096

        def has_cost_data(self):
            return False

        def format_capabilities(self):
            return "tools"

    def _fake_switch_model(**kwargs):
        assert kwargs["raw_input"] == "deepseek-ai/deepseek-v4-pro"
        assert kwargs["explicit_provider"] == "nvidia"
        return SimpleNamespace(
            success=True,
            new_model="deepseek-ai/deepseek-v4-pro",
            target_provider="nvidia",
            provider_label="NVIDIA",
            api_key="token",
            base_url="",
            api_mode="openai",
            warning_message="",
            model_info=_FakeModelInfo(),
        )

    hermes_cli_pkg = types.ModuleType("hermes_cli")
    model_switch_mod = types.ModuleType("hermes_cli.model_switch")
    model_switch_mod.switch_model = _fake_switch_model
    model_switch_mod.resolve_display_context_length = lambda *args, **kwargs: 128000
    model_switch_mod.list_authenticated_providers = lambda **kwargs: []
    saved_cfg = {}

    config_mod = types.ModuleType("hermes_cli.config")
    config_mod.load_config = lambda: {"model": {"default": "MiniMax-M2.7", "provider": "minimax"}}
    config_mod.save_config = lambda cfg: saved_cfg.update(cfg)
    config_mod.get_compatible_custom_providers = lambda cfg: []
    providers_mod = types.ModuleType("hermes_cli.providers")
    providers_mod.get_label = lambda slug: str(slug or "").upper()
    hermes_cli_pkg.model_switch = model_switch_mod
    hermes_cli_pkg.config = config_mod
    hermes_cli_pkg.providers = providers_mod
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli_pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.model_switch", model_switch_mod)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config_mod)
    monkeypatch.setitem(sys.modules, "hermes_cli.providers", providers_mod)
    monkeypatch.setattr(runtime, "_smoke_test_model_switch", lambda **kwargs: (True, ""))

    gateway = SimpleNamespace(
        _session_model_overrides={},
        _pending_model_notes={},
        _agent_cache_lock=None,
        _agent_cache={},
        _session_key_for_source=lambda source: "session:c1:u1",
        _evict_cached_agent=lambda session_key: None,
    )
    source = SimpleNamespace(platform="discord", chat_id="c1", thread_id=None, user_id="u1")
    interaction = SimpleNamespace(
        data={
            "options": [
                {"name": "name", "value": "deepseek-ai/deepseek-v4-pro"},
                {"name": "provider", "value": "nvidia"},
            ]
        }
    )

    reply = asyncio.run(runtime._execute_model("", gateway=gateway, source=source, interaction=interaction))

    assert "Model switched to `deepseek-ai/deepseek-v4-pro`" in reply
    assert "Catalog: `deepseekv4pro` (added)" in reply
    assert "Saved as node default in `cache/status/active_model.json`." in reply
    assert gateway._session_model_overrides["session:c1:u1"]["provider"] == "nvidia"
    payload = json.loads((cache_root / "governance" / "models.json").read_text(encoding="utf-8"))
    assert any(
        item["provider"] == "nvidia" and item["model"] == "deepseek-ai/deepseek-v4-pro"
        for item in payload["models"]
    )
    active_model = json.loads((cache_root / "status" / "active_model.json").read_text(encoding="utf-8"))
    assert active_model["provider"] == "nvidia"
    assert active_model["model"] == "deepseek-ai/deepseek-v4-pro"
    assert saved_cfg["model"]["default"] == "deepseek-ai/deepseek-v4-pro"
    assert saved_cfg["model"]["provider"] == "nvidia"


def test_execute_model_switch_does_not_persist_when_live_verification_fails(monkeypatch, tmp_path):
    cache_root = _seed_state(tmp_path, enabled_commands=["acl", "model", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    class _FakeModelInfo:
        max_output = 4096

        def has_cost_data(self):
            return False

        def format_capabilities(self):
            return "tools"

    def _fake_switch_model(**kwargs):
        return SimpleNamespace(
            success=True,
            new_model="minimaxai/minimax-m2.7",
            target_provider="nvidia",
            provider_label="NVIDIA",
            api_key="token",
            base_url="https://integrate.api.nvidia.com/v1",
            api_mode="chat_completions",
            warning_message="",
            model_info=_FakeModelInfo(),
        )

    hermes_cli_pkg = types.ModuleType("hermes_cli")
    model_switch_mod = types.ModuleType("hermes_cli.model_switch")
    model_switch_mod.switch_model = _fake_switch_model
    model_switch_mod.resolve_display_context_length = lambda *args, **kwargs: 128000
    model_switch_mod.list_authenticated_providers = lambda **kwargs: []
    saved_cfg = {}

    config_mod = types.ModuleType("hermes_cli.config")
    config_mod.load_config = lambda: {"model": {"default": "deepseek/deepseek-v4-pro", "provider": "openrouter"}}
    config_mod.save_config = lambda cfg: saved_cfg.update(cfg)
    config_mod.get_compatible_custom_providers = lambda cfg: []
    providers_mod = types.ModuleType("hermes_cli.providers")
    providers_mod.get_label = lambda slug: str(slug or "").upper()
    hermes_cli_pkg.model_switch = model_switch_mod
    hermes_cli_pkg.config = config_mod
    hermes_cli_pkg.providers = providers_mod
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli_pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.model_switch", model_switch_mod)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config_mod)
    monkeypatch.setitem(sys.modules, "hermes_cli.providers", providers_mod)
    monkeypatch.setattr(
        runtime,
        "_smoke_test_model_switch",
        lambda **kwargs: (False, "nvidia: Connection error."),
    )

    gateway = SimpleNamespace(
        _session_model_overrides={},
        _pending_model_notes={},
        _agent_cache_lock=None,
        _agent_cache={},
        _session_key_for_source=lambda source: "session:c1:u1",
        _evict_cached_agent=lambda session_key: None,
    )
    source = SimpleNamespace(platform="discord", chat_id="c1", thread_id=None, user_id="u1")
    interaction = SimpleNamespace(
        data={
            "options": [
                {"name": "name", "value": "minimaxai/minimax-m2.7"},
                {"name": "provider", "value": "nvidia"},
            ]
        }
    )

    reply = asyncio.run(runtime._execute_model("", gateway=gateway, source=source, interaction=interaction))

    assert "nothing was persisted" in reply
    assert "minimaxai/minimax-m2.7" in reply
    assert gateway._session_model_overrides == {}
    assert not (cache_root / "status" / "active_model.json").exists()
    assert saved_cfg == {}


def test_register_plugin_syncs_persisted_active_model_to_config(monkeypatch, tmp_path):
    cache_root = _seed_state(tmp_path, enabled_commands=["acl", "model", "slash", "status"])
    (cache_root / "status").mkdir(parents=True, exist_ok=True)
    (cache_root / "status" / "active_model.json").write_text(
        json.dumps(
            {
                "version": 1,
                "node": "colmeio",
                "model": "deepseek-ai/deepseek-v4-pro",
                "provider": "nvidia",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "api_mode": "chat_completions",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    saved_cfg = {}
    hermes_cli_pkg = types.ModuleType("hermes_cli")
    config_mod = types.ModuleType("hermes_cli.config")
    config_mod.load_config = lambda: {"model": {"default": "MiniMax-M2.7", "provider": "minimax"}}
    config_mod.save_config = lambda cfg: saved_cfg.update(cfg)
    hermes_cli_pkg.config = config_mod
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli_pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config_mod)

    class _FakeCtx:
        def register_command(self, *args, **kwargs):
            return None

        def register_hook(self, *args, **kwargs):
            return None

    runtime.register_plugin(_FakeCtx())

    assert saved_cfg["model"]["default"] == "deepseek-ai/deepseek-v4-pro"
    assert saved_cfg["model"]["provider"] == "nvidia"
    assert saved_cfg["model"]["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert saved_cfg["model"]["api_mode"] == "chat_completions"


def test_execute_model_list_configured_reads_governance_catalog(monkeypatch, tmp_path):
    cache_root = _seed_state(tmp_path, enabled_commands=["acl", "model", "slash", "status"])
    (cache_root / "governance").mkdir(parents=True, exist_ok=True)
    (cache_root / "governance" / "models.json").write_text(
        json.dumps(
            {
                "version": 1,
                "node": "colmeio",
                "models": [
                    {
                        "key": "deepseekv4pro",
                        "label": "Deepseek V4 Pro (NVIDIA)",
                        "provider": "nvidia",
                        "model": "deepseek-ai/deepseek-v4-pro",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    reply = asyncio.run(runtime._execute_model("list:configured"))

    assert "Discord Model Catalog" in reply
    assert "`deepseekv4pro`" in reply
    assert "`nvidia` / `deepseek-ai/deepseek-v4-pro`" in reply


def test_status_uses_persisted_node_model_after_restart(monkeypatch, tmp_path):
    cache_root = _seed_state(tmp_path, enabled_commands=["acl", "model", "slash", "status"])
    (cache_root / "status").mkdir(parents=True, exist_ok=True)
    (cache_root / "status" / "active_model.json").write_text(
        json.dumps(
            {
                "version": 1,
                "node": "colmeio",
                "model": "deepseek-ai/deepseek-v4-pro",
                "provider": "nvidia",
                "updated_at": "2026-05-01T08:20:00Z",
                "updated_by_node": "colmeio",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()
    _patch_governance_runtime(runtime, monkeypatch)

    replies = []
    monkeypatch.setattr(runtime, "_schedule_gateway_reply", lambda gateway, source, message: replies.append(message))

    gateway = SimpleNamespace(
        adapters={"discord": object()},
        _running_agents={},
        _session_model_overrides={},
        session_store=SimpleNamespace(
            get_or_create_session=lambda source: SimpleNamespace(
                session_id="sess-1",
                created_at=SimpleNamespace(strftime=lambda fmt: "2026-04-24 17:40"),
                updated_at=SimpleNamespace(strftime=lambda fmt: "2026-04-24 17:41"),
                total_tokens=1234,
            )
        ),
        _session_key_for_source=lambda source: "session:c1:u1",
        _session_db=SimpleNamespace(get_session_title=lambda session_id: "Fila faltas loja1"),
    )

    def _resolve_runtime(source=None):
        override = gateway._session_model_overrides.get("session:c1:u1") or {}
        return (
            str(override.get("model") or "MiniMax-M2.7"),
            {"provider": str(override.get("provider") or "minimax")},
        )

    gateway._resolve_session_agent_runtime = _resolve_runtime
    source = SimpleNamespace(platform="discord", chat_id="c1", thread_id=None, chat_id_alt=None, user_id="u1")
    event = SimpleNamespace(
        text="/status",
        source=source,
        raw_message=SimpleNamespace(guild=object(), user=SimpleNamespace(id="1"), data={}),
        get_command=lambda: "status",
        channel_prompt="",
    )

    result = runtime.handle_pre_gateway_dispatch(event=event, gateway=gateway)

    assert result == {"action": "skip", "reason": "status_override"}
    assert gateway._session_model_overrides["session:c1:u1"]["provider"] == "nvidia"
    assert replies
    assert "`deepseek-ai/deepseek-v4-pro`" in replies[0]
    assert "`nvidia`" in replies[0]


def test_inherit_parent_channel_model_state_copies_override_to_thread(monkeypatch, tmp_path):
    cache_root = _seed_state(tmp_path, enabled_commands=["acl", "model", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    parent_source = SimpleNamespace(
        platform="discord",
        chat_id="channel-1",
        chat_name="guild / general",
        chat_type="group",
        user_id="u1",
        user_name="tester",
        thread_id=None,
        parent_chat_id=None,
        guild_id="guild-1",
        chat_topic=None,
        user_id_alt=None,
        chat_id_alt=None,
        is_bot=False,
        message_id="m-parent",
    )
    thread_source = SimpleNamespace(
        platform="discord",
        chat_id="thread-1",
        chat_name="guild / general / thread",
        chat_type="thread",
        user_id="u1",
        user_name="tester",
        thread_id="thread-1",
        parent_chat_id="channel-1",
        guild_id="guild-1",
        chat_topic=None,
        user_id_alt=None,
        chat_id_alt=None,
        is_bot=False,
        message_id="m-thread",
    )

    session_keys = {
        "channel-1": "session:channel",
        "thread-1": "session:thread",
    }
    gateway = SimpleNamespace(
        _session_model_overrides={
            "session:channel": {
                "model": "deepseek-ai/deepseek-v4-pro",
                "provider": "nvidia",
                "api_key": "nv-key",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "api_mode": "chat_completions",
            }
        },
        _pending_model_notes={"session:channel": "[Note: switched to DeepSeek.]"},
        _session_key_for_source=lambda source: session_keys[str(getattr(source, "chat_id", "") or "")],
    )

    runtime._inherit_parent_channel_model_state(gateway, thread_source)

    assert gateway._session_model_overrides["session:thread"]["provider"] == "nvidia"
    assert gateway._session_model_overrides["session:thread"]["model"] == "deepseek-ai/deepseek-v4-pro"
    assert gateway._pending_model_notes["session:thread"] == "[Note: switched to DeepSeek.]"
    assert "session:channel" not in gateway._pending_model_notes


def test_apply_channel_route_preserves_existing_model_override_when_acl_is_noop(monkeypatch, tmp_path):
    cache_root = _seed_state(tmp_path, enabled_commands=["acl", "model", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    class _FakeChannelAcl:
        @staticmethod
        def enforce_channel_model(source, payload):
            return dict(payload)

    monkeypatch.setattr(runtime, "_safe_channel_acl_module", lambda: _FakeChannelAcl())

    gateway = SimpleNamespace(
        _session_model_overrides={
            "session:c1:u1": {
                "model": "deepseek/deepseek-v4-pro",
                "provider": "openrouter",
                "api_key": "or-key",
                "base_url": "https://openrouter.ai/api/v1",
                "api_mode": "chat_completions",
            }
        },
        _session_key_for_source=lambda source: "session:c1:u1",
        _resolve_session_agent_runtime=lambda source=None: (
            "deepseek-ai/deepseek-v4-pro",
            {
                "provider": "nvidia",
                "api_key": "nv-key",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "api_mode": "chat_completions",
            },
        ),
    )
    source = SimpleNamespace(platform="discord", chat_id="c1", thread_id=None, user_id="u1")
    event = SimpleNamespace(channel_prompt="")

    reply = runtime._apply_channel_route(gateway, event, source)

    assert reply == ""
    assert gateway._session_model_overrides["session:c1:u1"]["provider"] == "openrouter"
    assert gateway._session_model_overrides["session:c1:u1"]["model"] == "deepseek/deepseek-v4-pro"
    assert gateway._session_model_overrides["session:c1:u1"]["api_key"] == "or-key"


def test_handle_pre_gateway_dispatch_skips_channel_acl_for_admin_bypass(monkeypatch, tmp_path):
    cache_root = _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "metricas"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    class _FakeChannelAcl:
        def normalize_to_channel_skill(self, source, message):
            return "PASSTHROUGH", message

        def check_command_allowed(self, channel_id, command, thread_id=None, parent_id=None):
            raise AssertionError("channel ACL should be bypassed for admins")

        def enforce_channel_model(self, source, turn_route):
            return dict(turn_route)

    monkeypatch.setattr(runtime, "load_channel_acl_module", lambda: _FakeChannelAcl())
    monkeypatch.setattr(
        runtime,
        "_authorize_interaction_sync",
        lambda interaction, command_name: {"allowed": True, "bypass_governance": True, "decision": "admin_bypass"},
    )

    source = SimpleNamespace(platform="discord", chat_id="c1", thread_id=None, chat_id_alt=None, user_id="u1")
    event = SimpleNamespace(
        text="/metricas",
        source=source,
        raw_message=SimpleNamespace(guild=object(), user=SimpleNamespace(id="1"), data={}),
        get_command=lambda: "metricas",
        channel_prompt="",
    )
    gateway = SimpleNamespace(_session_model_overrides={}, _session_key_for_source=lambda source: "session:c1:u1")

    result = runtime.handle_pre_gateway_dispatch(event=event, gateway=gateway)

    assert result is None


def test_handle_pre_gateway_dispatch_reports_disabled_plugin_command_before_acl(monkeypatch, tmp_path):
    cache_root = _seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    class _FakeChannelAcl:
        def normalize_to_channel_skill(self, source, message):
            return "PASSTHROUGH", message

        def check_command_allowed(self, channel_id, command, thread_id=None, parent_id=None):
            raise AssertionError("ACL should not run before disabled-command response")

        def enforce_channel_model(self, source, turn_route):
            return dict(turn_route)

    replies = []
    monkeypatch.setattr(runtime, "load_channel_acl_module", lambda: _FakeChannelAcl())
    monkeypatch.setattr(runtime, "_schedule_gateway_reply", lambda gateway, source, message: replies.append(message))
    monkeypatch.setattr(
        runtime,
        "_authorize_interaction_sync",
        lambda interaction, command_name: (_ for _ in ()).throw(AssertionError("role ACL should not run before disabled-command response")),
    )

    source = SimpleNamespace(platform="discord", chat_id="c1", thread_id=None, chat_id_alt=None, user_id="u1")
    event = SimpleNamespace(
        text="/faltas",
        source=source,
        raw_message=SimpleNamespace(guild=object(), user=SimpleNamespace(id="1"), data={}),
        get_command=lambda: "faltas",
        channel_prompt="",
    )

    result = runtime.handle_pre_gateway_dispatch(event=event, gateway=object())

    assert result == {"action": "skip", "reason": "command_disabled"}
    assert replies == ["🚫 `/faltas` está desabilitado neste node. Use `/slash command:faltas enable:true`."]


def test_channel_acl_accepts_voice_transcript_in_strict_faltas_channel() -> None:
    channel_acl = _load_channel_acl_module()
    source = SimpleNamespace(
        chat_id="1487099552636080201",
        chat_id_alt=None,
        thread_id=None,
    )

    action, payload = channel_acl.normalize_to_channel_skill(
        source,
        '[The user sent a voice message~ Here\'s what they said: "adiciona papel higienico por favor"]',
    )

    assert action == "SKILL_ADD"
    assert payload == "/faltas adicionar papel higienico por favor"


def test_channel_acl_keeps_strict_item_block_for_regular_text() -> None:
    channel_acl = _load_channel_acl_module()
    source = SimpleNamespace(
        chat_id="1487099552636080201",
        chat_id_alt=None,
        thread_id=None,
    )

    action, payload = channel_acl.normalize_to_channel_skill(
        source,
        "oi pode adicionar papel higienico por favor?",
    )

    assert action == "BLOCK"
    assert "aceita apenas inclusão de itens de faltas" in payload


def test_handle_pre_gateway_dispatch_transcribes_audio_only_faltas_message(monkeypatch, tmp_path):
    _seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "faltas"])
    monkeypatch.setenv("HERMES_DISCORD_SLASH_CACHE_ROOT", str(_cache_root(tmp_path)))
    monkeypatch.setenv("NODE_NAME", "colmeio")
    runtime = _load_runtime()

    scheduled_messages = []

    async def _fake_dispatch(gateway, source, message_text):
        scheduled_messages.append(message_text)

    class _FakeLoop:
        def create_task(self, coro):
            asyncio.run(coro)
            return None

    fake_transcription_tools = types.ModuleType("tools.transcription_tools")
    fake_transcription_tools.transcribe_audio = lambda _path: {
        "success": True,
        "transcript": "adiciona papel higienico por favor",
    }

    monkeypatch.setitem(sys.modules, "tools.transcription_tools", fake_transcription_tools)
    monkeypatch.setattr(runtime, "_dispatch_normalized_command", _fake_dispatch)
    monkeypatch.setattr(runtime.asyncio, "get_running_loop", lambda: _FakeLoop())

    event = SimpleNamespace(
        text="(The user sent a message with no text content)",
        media_urls=["/tmp/voice-message.ogg"],
        media_types=["audio/ogg"],
        source=SimpleNamespace(
            platform="discord",
            chat_id="1487099552636080201",
            thread_id=None,
            chat_id_alt=None,
        ),
        raw_message=None,
        get_command=lambda: "",
    )

    result = runtime.handle_pre_gateway_dispatch(event=event, gateway=object())

    assert result == {"action": "skip", "reason": "channel_policy_normalized"}
    assert scheduled_messages == ["/faltas adicionar papel higienico por favor"]
