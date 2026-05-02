from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _load_runtime():
    module_name = "exhaust_runtime_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN_ROOT / "runtime.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load exhaust runtime")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class FakeCtx:
    def __init__(self):
        self.tools = []
        self.commands = []
        self.hooks = []
        self.injected = []

    def register_tool(self, **kwargs):
        self.tools.append(kwargs["name"])

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands.append((name, handler, description, args_hint))

    def register_hook(self, name, callback):
        self.hooks.append(name)

    def inject_message(self, content, role="user"):
        self.injected.append((role, content))
        return True


def test_register_is_noop_without_env(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.delenv("PLUGINS_EXHAUST", raising=False)
    monkeypatch.setenv("HERMES_EXHAUST_LOG", str(tmp_path / "exhaust.log"))
    ctx = FakeCtx()

    runtime.register(ctx)

    assert ctx.tools == []
    assert ctx.commands == []
    assert ctx.hooks == []


def test_registers_commands_tool_and_hooks_when_enabled(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGINS_EXHAUST", "true")
    monkeypatch.setenv("HERMES_EXHAUST_LOG", str(tmp_path / "exhaust.log"))
    ctx = FakeCtx()

    runtime.register(ctx)

    assert ctx.tools == ["exhaust_inventory"]
    assert [name for name, *_ in ctx.commands] == ["exhaust", "bruteforce"]
    assert set(ctx.hooks) == {
        "pre_gateway_dispatch",
        "pre_llm_call",
        "post_tool_call",
        "transform_tool_result",
        "on_session_end",
    }


def test_exhaust_command_queues_prompt(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGINS_EXHAUST", "true")
    monkeypatch.setenv("HERMES_EXHAUST_LOG", str(tmp_path / "exhaust.log"))
    ctx = FakeCtx()
    handler = runtime.make_command_handler(ctx, alias="exhaust")

    result = handler("repair the workflow")

    assert "activated" in result.lower()
    assert len(ctx.injected) == 1
    role, prompt = ctx.injected[0]
    assert role == "user"
    assert "HERMES_EXHAUST_MODE=active" in prompt
    assert "repair the workflow" in prompt
    assert "distinct fallback" in prompt


def test_gateway_dispatch_rewrites_exhaust_command(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGINS_EXHAUST", "true")
    monkeypatch.setenv("HERMES_EXHAUST_LOG", str(tmp_path / "exhaust.log"))

    class Event:
        text = "/exhaust finish the migration"

    result = runtime.pre_gateway_dispatch(event=Event())

    assert result["action"] == "rewrite"
    assert result["text"].startswith("HERMES_EXHAUST_MODE=active")
    assert "finish the migration" in result["text"]


def test_baoyu_infographic_discord_exhaust_rewrite_contains_recovery_contract(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGINS_EXHAUST", "true")
    monkeypatch.setenv("HERMES_EXHAUST_LOG", str(tmp_path / "exhaust.log"))

    class Event:
        text = (
            "/exhaust call `/baoyu-infographic` with input as  "
            "`a map of every layout and style of baoyu-infographic command`"
        )

    result = runtime.pre_gateway_dispatch(event=Event())

    assert result["action"] == "rewrite"
    rewritten = result["text"]
    assert rewritten.startswith("HERMES_EXHAUST_MODE=active")
    assert "Trigger: /exhaust" in rewritten
    assert "Task: call `/baoyu-infographic`" in rewritten
    assert "Call exhaust_inventory before the first fallback" in rewritten
    assert "Keep a visible attempt ledger" in rewritten
    assert "Final answer format:" in rewritten


def test_pre_llm_call_marks_explicit_exhaust_turn_active(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGINS_EXHAUST", "true")
    monkeypatch.setenv("HERMES_EXHAUST_LOG", str(tmp_path / "exhaust.log"))

    session_id = "20260428_110952_f8dd7b67"
    context = runtime.pre_llm_call(
        session_id=session_id,
        user_message=runtime._build_exhaust_prompt(
            "call `/baoyu-infographic` with input as `a map of every layout and style`",
            trigger="/exhaust",
        ),
    )

    assert context is not None
    assert "current turn is in exhaust mode" in context["context"]
    assert runtime._SESSION_STATE[session_id]["active"] is True


def test_transform_tool_result_adds_bounded_recovery_hint(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGINS_EXHAUST", "true")
    monkeypatch.setenv("HERMES_EXHAUST_LOG", str(tmp_path / "exhaust.log"))

    original = json.dumps({"error": "missing token"})
    rewritten = runtime.transform_tool_result(
        tool_name="api_call",
        result=original,
        session_id="s1",
        tool_call_id="tc1",
    )

    payload = json.loads(rewritten)
    assert payload["error"] == "missing token"
    assert payload["_exhaust_recovery_hint"]["mode"] == "exhaust_passive_recovery"
    assert payload["_exhaust_recovery_hint"]["failed_tool"] == "api_call"


def test_missing_image_generate_plain_text_gets_recovery_hint(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGINS_EXHAUST", "true")
    monkeypatch.setenv("HERMES_EXHAUST_LOG", str(tmp_path / "exhaust.log"))

    original = (
        "Tool 'image_generate' does not exist. Available tools: "
        "browser_navigate, exhaust_inventory, terminal"
    )
    rewritten = runtime.transform_tool_result(
        tool_name="image_generate",
        result=original,
        session_id="20260428_110853_4ee25956",
        tool_call_id="call_function_tvoxyrewltzp_1",
    )

    assert rewritten is not None
    assert rewritten.startswith(original)
    assert "[exhaust recovery hint]" in rewritten
    hint = json.loads(rewritten.split("[exhaust recovery hint]", 1)[1])
    assert hint["mode"] == "exhaust_passive_recovery"
    assert hint["failed_tool"] == "image_generate"
    assert hint["failed_class"] == "image_generation_route"


def test_baoyu_failure_sequence_records_distinct_failed_routes(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGINS_EXHAUST", "true")
    monkeypatch.setenv("HERMES_EXHAUST_LOG", str(tmp_path / "exhaust.log"))

    session_id = "20260428_110952_f8dd7b67"
    runtime.pre_llm_call(
        session_id=session_id,
        user_message=runtime._build_exhaust_prompt(
            "call `/baoyu-infographic` with input as `a map of every layout and style`",
            trigger="/exhaust",
        ),
    )
    runtime.post_tool_call(
        tool_name="image_generate",
        result="Tool 'image_generate' does not exist. Available tools: exhaust_inventory, terminal",
        session_id=session_id,
        tool_call_id="missing-image-tool",
    )
    runtime.post_tool_call(
        tool_name="browser_navigate",
        result=json.dumps({"success": False, "error": "Command timed out after 60 seconds"}),
        session_id=session_id,
        tool_call_id="browser-timeout",
    )

    state = runtime._SESSION_STATE[session_id]
    assert state["active"] is True
    assert [failure["tool"] for failure in state["failures"]] == [
        "image_generate",
        "browser_navigate",
    ]
    assert "image_generation_route" in state["fallback_classes"]
    assert "browser_or_manual_workflow" in state["fallback_classes"]


def test_transform_tool_result_ignores_success(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGINS_EXHAUST", "true")
    monkeypatch.setenv("HERMES_EXHAUST_LOG", str(tmp_path / "exhaust.log"))

    assert runtime.transform_tool_result(result=json.dumps({"ok": True})) is None


def test_inventory_reports_enabled_budget(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGINS_EXHAUST", "true")
    monkeypatch.setenv("PLUGINS_EXHAUST_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("HERMES_EXHAUST_LOG", str(tmp_path / "exhaust.log"))

    payload = json.loads(runtime.exhaust_inventory({"scope": "summary", "query": "blocked"}))

    assert payload["enabled"] is True
    assert payload["budget"]["max_attempts"] == 5
    assert payload["query"] == "blocked"
    assert "recommended_fallback_classes" in payload
