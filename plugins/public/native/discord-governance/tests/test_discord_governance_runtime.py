from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PACKAGE_ROOT = Path("/local/plugins/public/native/discord-governance")


def _load_runtime():
    package_name = "discord_governance_native_testpkg"
    for key in list(sys.modules):
        if key == package_name or key.startswith(package_name + "."):
            sys.modules.pop(key, None)
    spec = importlib.util.spec_from_file_location(
        package_name,
        PACKAGE_ROOT / "__init__.py",
        submodule_search_locations=[str(PACKAGE_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load governance plugin package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    spec.loader.exec_module(module)
    return importlib.import_module(f"{package_name}.runtime")


@pytest.mark.asyncio
async def test_handle_acl_command_update(monkeypatch):
    runtime = _load_runtime()

    class _FakeRoleAcl:
        def update_command_min_role(self, path, command_name, requested_role):
            assert str(path).endswith("_acl.json")
            assert command_name == "metricas"
            assert requested_role == "gerente"
            return {
                "command": "metricas",
                "min_role": "name:gerente",
                "min_role_label": "gerente",
                "previous_min_role": "name:balconista",
                "acl_path": str(path),
            }

    monkeypatch.setattr(runtime, "load_role_acl_module", lambda: _FakeRoleAcl())

    result = await runtime.handle_acl("command command:metricas role:gerente")

    assert "ACL de comando atualizado" in result
    assert "/metricas" in result


@pytest.mark.asyncio
async def test_handle_command_policy_denies_when_role_acl_denies(monkeypatch):
    runtime = _load_runtime()

    class _FakeRoleAcl:
        async def authorize_interaction(self, interaction, command, acl_path=None):
            assert command == "metricas"
            return {"allowed": False, "message": "blocked-role"}

    monkeypatch.setattr(runtime, "load_role_acl_module", lambda: _FakeRoleAcl())

    result = await runtime.handle_command_policy(
        platform="discord",
        command="metricas",
        event=SimpleNamespace(raw_message=object()),
        source=SimpleNamespace(chat_id="1", thread_id=None, chat_id_alt=None),
    )

    assert result == {"decision": "deny", "message": "blocked-role"}


@pytest.mark.asyncio
async def test_register_plugin_registers_command_and_hooks():
    runtime = _load_runtime()
    commands = []
    hooks = []

    class _FakeCtx:
        def register_command(self, name, handler, description="", args_hint=""):
            commands.append((name, handler, description, args_hint))

        def register_hook(self, name, callback):
            hooks.append((name, callback))

    runtime.register_plugin(_FakeCtx())

    assert commands[0][0] == "acl"
    assert {name for name, _callback in hooks} == {"pre_gateway_dispatch"}


def test_handle_pre_gateway_dispatch_sets_channel_prompt_and_model_override(monkeypatch):
    runtime = _load_runtime()

    class _FakeChannelAcl:
        def normalize_to_channel_skill(self, source, message):
            return "PASSTHROUGH", message

        def enforce_channel_model(self, source, turn_route):
            turn_route["model"] = "moonshotai/kimi-k2.5"
            turn_route["runtime"] = {
                **dict(turn_route.get("runtime") or {}),
                "provider": "kimi-coding",
            }
            turn_route["system_prompt_addon"] = "restricted channel prompt"
            return turn_route

        def check_command_allowed(self, channel_id, command, thread_id=None, parent_id=None):
            return True, ""

    monkeypatch.setattr(runtime, "load_channel_acl_module", lambda: _FakeChannelAcl())

    gateway = SimpleNamespace(
        _session_model_overrides={"session:c1:u1": {"model": "old-model"}},
        _session_key_for_source=lambda source: "session:c1:u1",
        _resolve_session_agent_runtime=lambda source=None: (
            "MiniMax-M2.7",
            {"provider": "minimax", "api_key": "key", "base_url": "", "api_mode": ""},
        ),
        adapters={},
    )
    source = SimpleNamespace(platform="discord", chat_id="c1", thread_id=None, chat_id_alt=None, user_id="u1")
    event = SimpleNamespace(
        text="oi",
        source=source,
        raw_message=None,
        channel_prompt="",
        get_command=lambda: "",
    )

    result = runtime.handle_pre_gateway_dispatch(event=event, gateway=gateway)

    assert result is None
    assert event.channel_prompt == "restricted channel prompt"
    assert gateway._session_model_overrides["session:c1:u1"]["model"] == "moonshotai/kimi-k2.5"
    assert gateway._session_model_overrides["session:c1:u1"]["provider"] == "kimi-coding"


def test_handle_pre_gateway_dispatch_blocks_restricted_channel_message(monkeypatch):
    runtime = _load_runtime()

    class _FakeChannelAcl:
        def normalize_to_channel_skill(self, source, message):
            return "BLOCK", "blocked-message"

    monkeypatch.setattr(runtime, "load_channel_acl_module", lambda: _FakeChannelAcl())

    replies = []
    monkeypatch.setattr(runtime, "_schedule_gateway_reply", lambda gateway, source, message: replies.append(message))

    gateway = SimpleNamespace(adapters={})
    source = SimpleNamespace(platform="discord", chat_id="c1", thread_id=None, chat_id_alt=None, user_id="u1")
    event = SimpleNamespace(
        text="papel higienico",
        source=source,
        raw_message=None,
        channel_prompt="",
        get_command=lambda: "",
    )

    result = runtime.handle_pre_gateway_dispatch(event=event, gateway=gateway)

    assert result == {"action": "skip", "reason": "channel_policy_block"}
    assert replies == ["blocked-message"]


def test_handle_pre_gateway_dispatch_overrides_status(monkeypatch):
    runtime = _load_runtime()

    class _FakeChannelAcl:
        def normalize_to_channel_skill(self, source, message):
            return "PASSTHROUGH", message

        def enforce_channel_model(self, source, turn_route):
            turn_route["model"] = "moonshotai/kimi-k2.5"
            turn_route["runtime"] = {
                **dict(turn_route.get("runtime") or {}),
                "provider": "kimi-coding",
            }
            return turn_route

        def get_channel_routing(self, channel_id, thread_id=None, parent_id=None):
            return "condicionado", {}

    monkeypatch.setattr(runtime, "load_channel_acl_module", lambda: _FakeChannelAcl())

    replies = []
    monkeypatch.setattr(runtime, "_schedule_gateway_reply", lambda gateway, source, message: replies.append(message))

    session_entry = SimpleNamespace(
        session_id="sess-1",
        created_at=SimpleNamespace(strftime=lambda fmt: "2026-04-24 17:40"),
        updated_at=SimpleNamespace(strftime=lambda fmt: "2026-04-24 17:41"),
        total_tokens=1234,
    )
    gateway = SimpleNamespace(
        session_store=SimpleNamespace(get_or_create_session=lambda source: session_entry),
        adapters={"discord": object()},
        _session_key_for_source=lambda source: "session:c1:u1",
        _running_agents={"session:c1:u1": object()},
        _session_db=SimpleNamespace(get_session_title=lambda session_id: "Fila faltas loja1"),
        _resolve_session_agent_runtime=lambda source=None: (
            "MiniMax-M2.7",
            {"provider": "minimax", "api_key": "key", "base_url": "", "api_mode": ""},
        ),
    )
    source = SimpleNamespace(platform="discord", chat_id="c1", thread_id=None, chat_id_alt=None, user_id="u1")
    event = SimpleNamespace(
        text="/status",
        source=source,
        raw_message=None,
        channel_prompt="",
        get_command=lambda: "status",
    )

    result = runtime.handle_pre_gateway_dispatch(event=event, gateway=gateway)

    assert result == {"action": "skip", "reason": "status_override"}
    assert len(replies) == 1
    assert "Hermes Gateway Status" in replies[0]
    assert "Fila faltas loja1" in replies[0]
    assert "`moonshotai/kimi-k2.5`" in replies[0]
    assert "`kimi-coding`" in replies[0]
    assert "channel-acl forced (condicionado)" in replies[0]
