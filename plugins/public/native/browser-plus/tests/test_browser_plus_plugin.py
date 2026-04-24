from __future__ import annotations

import importlib
import importlib.util
import io
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_constants import WorkspaceResolutionError


PLUGIN_DIR = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "browser_plus_testpkg"
HERMES_AGENT_ROOT = Path("/local/hermes-agent")

if str(HERMES_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(HERMES_AGENT_ROOT))


def _load_package():
    existing = sys.modules.get(PACKAGE_NAME)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _load_submodule(name: str):
    _load_package()
    return importlib.import_module(f"{PACKAGE_NAME}.{name}")


class _Ctx:
    def __init__(self):
        self.hooks = []
        self.tools = []
        self.commands = []
        self.cli_commands = []
        self.skills = []

    def register_hook(self, hook_name, callback):
        self.hooks.append((hook_name, callback))

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_command(self, name, handler, description=""):
        self.commands.append((name, handler, description))

    def register_cli_command(self, **kwargs):
        self.cli_commands.append(kwargs)

    def register_skill(self, name, path, description=""):
        self.skills.append((name, path, description))


def test_registers_expected_surface():
    plugin = _load_package()
    ctx = _Ctx()
    plugin.register(ctx)

    tool_names = {item["name"] for item in ctx.tools}
    assert "browser_plus_status" in tool_names
    assert "browser_plus_cdp" in tool_names
    assert "browser_plus_search_knowledge" in tool_names
    assert any(hook_name == "pre_llm_call" for hook_name, _ in ctx.hooks)
    assert any(name == "browser-plus-status" for name, _, _ in ctx.commands)
    assert any(item["name"] == "browser-plus" for item in ctx.cli_commands)
    assert any(name == "browser-plus-operator" for name, _, _ in ctx.skills)


def test_search_knowledge_finds_upstream_domain_docs():
    runtime = _load_submodule("runtime")
    matches = runtime.search_knowledge("tiktok upload", kind="domain", limit=5)
    paths = [item["path"] for item in matches]
    assert any(path.endswith("domain-skills/tiktok/upload.md") for path in paths)


def test_hook_injects_browser_guidance():
    hooks = _load_submodule("hooks")
    payload = hooks.inject_browser_plus_turn_context(
        session_id="sess-1",
        user_message="Use the browser to upload this file on TikTok and open https://www.tiktok.com",
    )
    assert payload is not None
    context = payload["context"]
    assert "Browser Plus" in context
    assert "interaction-skills/uploads.md" in context
    assert "domain-skills/tiktok/upload.md" in context
    assert "prefer the browser_plus_* toolset as the primary browser path" in context


def test_runtime_resolves_http_cdp_endpoint_to_websocket():
    runtime = _load_submodule("runtime")
    response = io.BytesIO(b'{"webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/browser/test"}')
    with patch.object(runtime.urllib.request, "urlopen", return_value=response):
        resolved = runtime.resolve_cdp_ws_endpoint("http://127.0.0.1:9222")
    assert resolved == "ws://127.0.0.1:9222/devtools/browser/test"


def test_runtime_prefers_hermes_browser_cdp_env():
    runtime = _load_submodule("runtime")
    with patch.dict(os.environ, {"BROWSER_CDP_URL": "http://127.0.0.1:9222"}, clear=False):
        with patch.object(runtime, "read_hermes_browser_cdp_url", return_value="http://127.0.0.1:9555"):
            raw, source = runtime.configured_cdp_candidate()
    assert raw == "http://127.0.0.1:9222"
    assert source == "BROWSER_CDP_URL"


def test_runtime_prefers_generic_browsing_by_default():
    runtime = _load_submodule("runtime")
    with patch.dict(os.environ, {}, clear=True):
        assert runtime.browser_plus_prefers_generic_routing() is True


def test_runtime_workspace_root_prefers_node_root(monkeypatch, tmp_path):
    runtime = _load_submodule("runtime")
    node_root = tmp_path / "agents" / "nodes" / "browser"
    monkeypatch.setenv("HERMES_NODE_ROOT", str(node_root))
    assert runtime.resolve_workspace_root(cwd="/local") == node_root / "workspace"


def test_runtime_workspace_root_refuses_generic_repo_root_without_node_context(monkeypatch):
    runtime = _load_submodule("runtime")
    monkeypatch.delenv("HERMES_NODE_ROOT", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("TERMINAL_CWD", raising=False)
    with pytest.raises(WorkspaceResolutionError):
        runtime.resolve_workspace_root(cwd="/local")
