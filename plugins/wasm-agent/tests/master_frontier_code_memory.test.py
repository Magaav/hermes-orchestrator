#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PLUGIN_ROOT / "server"
CODE_MEMORY_PATH = SERVER_ROOT / "master_frontier" / "code_memory.py"
STATIC_SERVER_PATH = SERVER_ROOT / "static_server.py"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

spec = importlib.util.spec_from_file_location("master_frontier.code_memory", CODE_MEMORY_PATH)
assert spec and spec.loader
code_memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(code_memory)


class MasterFrontierCodeMemoryTests(unittest.TestCase):
    def contract(self) -> dict[str, str]:
        return {
            "route_id": "wasm-agent.avatar-chat.ui",
            "workspace_root": str(PLUGIN_ROOT),
        }

    def test_search_returns_compact_items_from_cli_graph(self) -> None:
        calls: list[list[str]] = []

        def runner(argv: list[str], cwd: Path, timeout_sec: int) -> tuple[int, str, str]:
            calls.append(argv)
            payload = {
                "results": [{
                    "label": "Function",
                    "name": "requires_structured_action",
                    "file": "server/master_frontier/envelope.py",
                    "line": 265,
                    "extra": "not projected by default",
                }]
            }
            return 0, json.dumps(payload), ""

        with patch.object(code_memory.shutil, "which", return_value="/usr/bin/codebase-memory-mcp"):
            result = code_memory.search(self.contract(), {"query": "requires_structured_action"}, runner=runner)

        self.assertTrue(result["ok"])
        self.assertEqual(result["primitive"], "code.memory.search")
        self.assertEqual(result["engine"], "search_graph")
        self.assertEqual(result["items"][0]["file"], "server/master_frontier/envelope.py")
        self.assertNotIn("extra", result["items"][0])
        self.assertEqual(json.loads(calls[0][3])["name_pattern"], "requires_structured_action")
        self.assertEqual(json.loads(calls[0][3])["project"], "local-plugins-wasm-agent")

    def test_unavailable_binary_is_typed_not_exception(self) -> None:
        with patch.object(code_memory.shutil, "which", return_value=None):
            result = code_memory.search(self.contract(), {"query": "kernel"}, runner=lambda *_: (0, "{}", ""))

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "code_memory_unavailable")

    def test_cli_log_lines_before_json_are_ignored(self) -> None:
        parsed = code_memory.parse_cli_output(
            'level=info msg=pass.done\n{"results":[{"name":"code_memory_tool"}]}\n',
            "",
        )

        self.assertEqual(parsed["results"][0]["name"], "code_memory_tool")

    def test_static_server_only_delegates_code_memory_policy(self) -> None:
        source = STATIC_SERVER_PATH.read_text(encoding="utf-8")

        self.assertIn("master_frontier_code_memory.execute", source)
        self.assertIn('"/agent/tools/code.memory.search"', source)
        self.assertNotIn('"search_graph" if body.get("structural"', source)
        self.assertNotIn("codebase-memory-mcp binary is not installed", source)


if __name__ == "__main__":
    unittest.main()
