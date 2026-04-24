from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PACKAGE_ROOT = Path("/local/plugins/public/native/discord-slash-commands")


def _load_runtime():
    package_name = "discord_slash_commands_native_testpkg"
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


def test_parse_metricas_args():
    runtime = _load_runtime()

    parsed = runtime.parse_metricas_args('dias:7 formato:json skill:"loja a"')

    assert parsed == {
        "dias": 7,
        "formato": "json",
        "skill": "loja a",
    }


@pytest.mark.asyncio
async def test_handle_metricas_uses_legacy_runner(monkeypatch):
    runtime = _load_runtime()

    class _FakeHandlers:
        async def run_metrics_dashboard(self, interaction, command_name, option_values, settings=None):
            assert interaction is None
            assert command_name == "metricas"
            assert option_values["dias"] == 14
            assert option_values["formato"] == "csv"
            assert option_values["skill"] == "core"
            assert "script_path" in (settings or {})
            return "ok-metricas", False

    monkeypatch.setattr(runtime, "_load_legacy_handlers", lambda: _FakeHandlers())

    result = await runtime.handle_metricas("dias:14 formato:csv skill:core")

    assert result == "ok-metricas"


@pytest.mark.asyncio
async def test_handle_metricas_uses_captured_interaction_options(monkeypatch):
    runtime = _load_runtime()
    interaction = SimpleNamespace(
        data={
            "name": "metricas",
            "options": [
                {"name": "dias", "value": 7},
                {"name": "formato", "value": "json"},
                {"name": "skill", "value": "core"},
            ],
        }
    )
    runtime.handle_pre_gateway_dispatch(
        event=SimpleNamespace(source=SimpleNamespace(platform="discord"), raw_message=interaction),
        gateway=object(),
    )

    class _FakeHandlers:
        async def run_metrics_dashboard(self, interaction_value, command_name, option_values, settings=None):
            assert interaction_value is interaction
            assert command_name == "metricas"
            assert option_values == {"dias": 7, "formato": "json", "skill": "core"}
            return "ok-metricas-ctx", False

    monkeypatch.setattr(runtime, "_load_legacy_handlers", lambda: _FakeHandlers())

    result = await runtime.handle_metricas("")

    assert result == "ok-metricas-ctx"


def test_register_plugin_registers_metricas():
    runtime = _load_runtime()
    calls = []
    hooks = []
    logged = []

    class _FakeCtx:
        def register_command(self, name, handler, description="", args_hint=""):
            calls.append(
                SimpleNamespace(
                    name=name,
                    handler=handler,
                    description=description,
                    args_hint=args_hint,
                )
            )

        def register_hook(self, name, callback):
            hooks.append((name, callback))

    runtime._log_registration_status = lambda: logged.append(True)
    runtime.register_plugin(_FakeCtx())

    assert [call.name for call in calls] == ["metricas", "faltas", "discord-slash-status"]
    assert "dias" in calls[0].args_hint
    assert "action:listar" in calls[1].args_hint
    assert calls[2].description
    assert {name for name, _callback in hooks} == {"pre_gateway_dispatch"}
    assert logged == [True]


def test_handle_discord_slash_status_formats_registration():
    runtime = _load_runtime()
    runtime._collect_registration_status = lambda: {
        "node_name": "colmeio",
        "payload_path": "/tmp/colmeio.json",
        "payload_exists": True,
        "payload_names": ["metricas", "faltas"],
        "requested_commands": ["metricas", "faltas"],
        "missing_payload_commands": [],
        "metrics_script_path": "/tmp/metrics.py",
        "metrics_script_exists": True,
        "faltas_pipeline_path": "/tmp/faltas.py",
        "faltas_pipeline_exists": True,
        "discord_app_id": "123",
        "discord_server_id": "456",
    }

    result = asyncio.run(runtime.handle_discord_slash_status(""))

    assert "Discord slash registration status" in result
    assert "payload commands: metricas, faltas" in result
    assert "discord app id: 123" in result


def test_parse_faltas_args():
    runtime = _load_runtime()

    parsed = runtime.parse_faltas_args('action:adicionar loja:loja2 itens:"banana prata" formato:texto confirm:sim')

    assert parsed == {
        "action": "adicionar",
        "loja": "loja2",
        "itens": "banana prata",
        "formato": "texto",
        "confirm": "sim",
    }


@pytest.mark.asyncio
async def test_handle_pre_gateway_message_handles_faltas(monkeypatch):
    runtime = _load_runtime()
    source = SimpleNamespace(chat_id="c1", chat_id_alt="p1", user_id="u1", user_name="Ana")

    async def _fake_execute(raw_args, *, source=None):
        assert raw_args == "action:listar loja:loja1"
        assert source.chat_id == "c1"
        return "ok-faltas"

    monkeypatch.setattr(runtime, "_execute_faltas", _fake_execute)

    result = await runtime.handle_pre_gateway_message(
        platform="discord",
        source=source,
        message="/faltas action:listar loja:loja1",
    )

    assert result == {"decision": "handled", "message": "ok-faltas"}


@pytest.mark.asyncio
async def test_handle_faltas_uses_captured_source(monkeypatch):
    runtime = _load_runtime()
    source = SimpleNamespace(platform="discord", chat_id="c1", chat_id_alt="p1", user_id="u1", user_name="Ana")
    runtime.handle_pre_gateway_dispatch(
        event=SimpleNamespace(source=source, raw_message=None),
        gateway=object(),
    )

    async def _fake_execute(raw_args, *, source=None):
        assert raw_args == "action:listar loja:loja1"
        assert source.chat_id == "c1"
        return "ok-captured"

    monkeypatch.setattr(runtime, "_execute_faltas", _fake_execute)

    result = await runtime.handle_faltas("action:listar loja:loja1")

    assert result == "ok-captured"


@pytest.mark.asyncio
async def test_handle_faltas_command_accepts_short_action(monkeypatch):
    runtime = _load_runtime()
    source = SimpleNamespace(chat_id="c1", chat_id_alt="p1", user_id="u1", user_name="Ana")

    async def _fake_execute(raw_args, *, source=None):
        assert raw_args == "listar"
        assert source.chat_id == "c1"
        return "ok-short"

    monkeypatch.setattr(runtime, "_execute_faltas", _fake_execute)

    result = await runtime.handle_faltas_command(
        platform="discord",
        args="listar",
        event=SimpleNamespace(raw_message=None),
        source=source,
    )

    assert result == {"decision": "handled", "message": "ok-short"}


@pytest.mark.asyncio
async def test_handle_faltas_command_rebuilds_args_from_interaction_options(monkeypatch):
    runtime = _load_runtime()
    interaction = SimpleNamespace(
        data={
            "name": "faltas",
            "options": [
                {"name": "action", "value": "listar"},
                {"name": "loja", "value": "loja1"},
                {"name": "formato", "value": "links"},
            ],
        }
    )

    async def _fake_execute(raw_args, *, source=None):
        assert raw_args == "action:listar loja:loja1 formato:links"
        return "ok-structured"

    monkeypatch.setattr(runtime, "_execute_faltas", _fake_execute)

    result = await runtime.handle_faltas_command(
        platform="discord",
        args="",
        event=SimpleNamespace(raw_message=interaction),
        source=None,
    )

    assert result == {"decision": "handled", "message": "ok-structured"}


@pytest.mark.asyncio
async def test_handle_faltas_runs_pipeline(monkeypatch, tmp_path):
    runtime = _load_runtime()
    script_path = tmp_path / "faltas_pipeline.py"
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    monkeypatch.setattr(runtime, "resolve_faltas_pipeline_script", lambda: script_path)
    captured = {"required_modules": None}

    def _fake_python_bin(*, required_modules=()):
        captured["required_modules"] = tuple(required_modules)
        return "/usr/bin/python3"

    monkeypatch.setattr(runtime, "resolve_python_bin", _fake_python_bin)

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            payload = {
                "data": {
                    "stores": {
                        "loja1": {
                            "sheet_url": "https://example.com/loja1",
                            "total_items": 2,
                        }
                    }
                }
            }
            return json.dumps(payload).encode(), b""

    async def _fake_subprocess_exec(*cmd, **_kwargs):
        captured["cmd"] = list(cmd)
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_subprocess_exec)

    result = await runtime.handle_faltas("action:listar loja:loja1 formato:links")

    assert "/usr/bin/python3" in captured["cmd"][0]
    assert str(script_path) in captured["cmd"][1]
    assert captured["required_modules"] == ("openpyxl",)
    assert "--formato" not in captured["cmd"]
    assert "https://example.com/loja1" in result


@pytest.mark.asyncio
async def test_handle_commands_reload_ignores_non_reload():
    runtime = _load_runtime()

    result = await runtime.handle_commands_reload(
        platform="discord",
        command="commands",
        args="2",
        runner=SimpleNamespace(adapters={}),
    )

    assert result is None


@pytest.mark.asyncio
async def test_handle_commands_reload_skips_destructive_clear_by_default(monkeypatch):
    runtime = _load_runtime()

    class _FakeRoute:
        def __init__(self, method, path, **params):
            self.method = method
            self.path = path
            self.params = params

    class _FakeHTTP:
        def __init__(self):
            self.calls = []

        async def request(self, route, json=None):
            self.calls.append((route.method, route.path, json, route.params))
            raise AssertionError("request() should not be called for non-destructive reload")

    fake_discord = SimpleNamespace(http=SimpleNamespace(Route=_FakeRoute))
    monkeypatch.setitem(sys.modules, "discord", fake_discord)

    client = SimpleNamespace(
        application_id="app-123",
        user=SimpleNamespace(id="user-999"),
        http=_FakeHTTP(),
        guilds=[SimpleNamespace(id=111), SimpleNamespace(id=222)],
    )
    runner = SimpleNamespace(adapters={"discord": SimpleNamespace(_client=client)})

    result = await runtime.handle_commands_reload(
        platform="discord",
        command="commands",
        args="args:reload",
        runner=runner,
    )

    assert result is not None
    assert result["decision"] == "handled"
    assert "Skipped destructive Discord app-command clearing" in result["message"]
    assert client.http.calls == []


@pytest.mark.asyncio
async def test_handle_commands_reload_clears_global_and_guild_commands_when_explicit(monkeypatch):
    runtime = _load_runtime()

    class _FakeRoute:
        def __init__(self, method, path, **params):
            self.method = method
            self.path = path
            self.params = params

    class _FakeHTTP:
        def __init__(self):
            self.calls = []

        async def request(self, route, json=None):
            self.calls.append((route.method, route.path, json, route.params))
            if route.method == "GET" and route.path == "/applications/{application_id}/commands":
                return [{"id": "g1"}, {"id": "g2"}]
            if route.method == "GET" and route.path == "/applications/{application_id}/guilds/{guild_id}/commands":
                return [{"id": "x1"}]
            if route.method == "PUT":
                return []
            raise AssertionError(f"unexpected route: {route.method} {route.path}")

    fake_discord = SimpleNamespace(http=SimpleNamespace(Route=_FakeRoute))
    monkeypatch.setitem(sys.modules, "discord", fake_discord)

    client = SimpleNamespace(
        application_id="app-123",
        user=SimpleNamespace(id="user-999"),
        http=_FakeHTTP(),
        guilds=[SimpleNamespace(id=111), SimpleNamespace(id=222)],
    )
    runner = SimpleNamespace(adapters={"discord": SimpleNamespace(_client=client)})

    result = await runtime.handle_commands_reload(
        platform="discord",
        command="commands",
        args="args:reload clear",
        runner=runner,
    )

    assert result is not None
    assert result["decision"] == "handled"
    assert "Removed 2 global and 2 guild command(s)" in result["message"]
    put_calls = [call for call in client.http.calls if call[0] == "PUT"]
    assert len(put_calls) == 3
