#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
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

route_spec = importlib.util.spec_from_file_location("master_frontier.route_contracts", SERVER_ROOT / "master_frontier" / "route_contracts.py")
assert route_spec and route_spec.loader
route_contracts = importlib.util.module_from_spec(route_spec)
route_spec.loader.exec_module(route_contracts)


class MasterFrontierCodeMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.freshness_patcher = patch.object(
            code_memory,
            "freshness",
            return_value={"state": "fresh", "trusted": True, "workspace_fingerprint": "test", "indexed_fingerprint": "test"},
        )
        self.freshness_patcher.start()
        self.addCleanup(self.freshness_patcher.stop)

    def contract(self) -> dict[str, object]:
        return {
            "route_id": "wasm-agent.avatar-chat.ui",
            "workspace_root": str(PLUGIN_ROOT),
            "allowed_read_roots": [str(PLUGIN_ROOT)],
            "source_index": {
                "include_roots": ["server", "tests"],
                "exclude_globs": [
                    "public/modules/**/onnx/**",
                    "tools/vendor/**",
                    "reports/**",
                    "state/**",
                    "**/node_modules/**",
                ],
                "max_file_bytes": 262144,
                "max_total_bytes": 8000000,
                "max_results": 8,
            },
        }

    def test_search_returns_compact_items_from_cli_graph(self) -> None:
        calls: list[list[str]] = []

        def runner(argv: list[str], cwd: Path, timeout_sec: int) -> tuple[int, str, str]:
            calls.append(argv)
            if argv[:3] == ["docker", "image", "inspect"]:
                return 0, "[]", ""
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

        with patch.object(code_memory.shutil, "which", return_value="/usr/bin/docker"):
            result = code_memory.search(self.contract(), {"query": "requires_structured_action"}, runner=runner)

        self.assertTrue(result["ok"])
        self.assertEqual(result["primitive"], "code.memory.search")
        self.assertEqual(result["engine"], "search_graph")
        self.assertEqual(result["items"][0]["file"], "server/master_frontier/envelope.py")
        self.assertNotIn("extra", result["items"][0])
        payload = json.loads(calls[-1][-1])
        self.assertEqual(payload["name_pattern"], "requires_structured_action")
        self.assertEqual(payload["project"], "workspace")
        self.assertEqual(payload["source_index"]["include_roots"], ["server", "tests"])
        self.assertIn("public/modules/**/onnx/**", payload["source_index"]["exclude_globs"])
        self.assertIn("tools/vendor/**", payload["source_index"]["exclude_globs"])
        self.assertIn("--read-only", calls[-1])
        self.assertIn("--user", calls[-1])
        self.assertIn("--tmpfs", calls[-1])
        self.assertIn("/tmp:rw,noexec,nosuid,size=64m", calls[-1])
        self.assertIn("--memory", calls[-1])
        self.assertIn("CBM_CACHE_DIR=/cache", calls[-1])
        self.assertNotIn("--privileged", calls[-1])
        self.assertTrue(any("dst=/cache" in part for part in calls[-1]))

    def test_direct_execution_env_prefers_vendored_binary_over_docker(self) -> None:
        calls: list[list[str]] = []

        def runner(argv: list[str], cwd: Path, timeout_sec: int) -> tuple[int, str, str]:
            calls.append(argv)
            return 0, json.dumps({"results": [{"name": "requires_structured_action"}]}), ""

        with patch.dict(code_memory.os.environ, {code_memory.DIRECT_EXEC_ENV: "1"}, clear=False), patch.object(code_memory.shutil, "which", return_value="/local/tools/vendor/codebase-memory-mcp/v0.8.1/codebase-memory-mcp"):
            result = code_memory.search(self.contract(), {"query": "requires_structured_action"}, runner=runner)

        self.assertTrue(result["ok"])
        self.assertTrue(calls[0][0].endswith("codebase-memory-mcp"))
        self.assertEqual(calls[0][1:3], ["cli", "search_graph"])
        self.assertNotIn("docker", calls[0][0])

    def test_structural_false_uses_search_code_pattern_contract(self) -> None:
        calls: list[list[str]] = []

        def runner(argv: list[str], cwd: Path, timeout_sec: int) -> tuple[int, str, str]:
            calls.append(argv)
            if argv[:3] == ["docker", "image", "inspect"]:
                return 0, "[]", ""
            payload = {
                "results": [{
                    "label": "RawMatch",
                    "file": "public/app.js",
                    "line": 12,
                }]
            }
            return 0, json.dumps(payload), ""

        with patch.object(code_memory.shutil, "which", return_value="/usr/bin/docker"):
            result = code_memory.search(self.contract(), {"query": "space widgets", "structural": False}, runner=runner)

        self.assertTrue(result["ok"])
        self.assertEqual(result["engine"], "search_code")
        payload = json.loads(calls[-1][-1])
        self.assertEqual(payload["pattern"], "space widgets")
        self.assertNotIn("query", payload)

    def test_graph_search_executes_the_head_query_exactly_once(self) -> None:
        calls: list[list[str]] = []

        def runner(argv: list[str], cwd: Path, timeout_sec: int) -> tuple[int, str, str]:
            calls.append(argv)
            if argv[:3] == ["docker", "image", "inspect"]:
                return 0, "[]", ""
            payload = json.loads(argv[-1])
            return 0, json.dumps({"results": []}), ""

        with patch.object(code_memory.shutil, "which", return_value="/usr/bin/docker"):
            result = code_memory.search(self.contract(), {"query": "space widgets", "limit": 8}, runner=runner)

        self.assertTrue(result["ok"])
        self.assertEqual(result["engine"], "search_graph")
        self.assertEqual(result["items"], [])
        self.assertNotIn("fallback_query", result)
        searched = [json.loads(call[-1]).get("name_pattern") for call in calls if call[:3] != ["docker", "image", "inspect"]]
        self.assertEqual(searched, ["space widgets"])

    def test_compound_query_is_not_rewritten_by_hidden_lexical_planning(self) -> None:
        searched: list[str] = []

        def runner(argv: list[str], cwd: Path, timeout_sec: int) -> tuple[int, str, str]:
            if argv[:3] == ["docker", "image", "inspect"]:
                return 0, "[]", ""
            pattern = str(json.loads(argv[-1]).get("name_pattern") or "")
            searched.append(pattern)
            return 0, json.dumps({"results": []}), ""

        with patch.object(code_memory.shutil, "which", return_value="/usr/bin/docker"):
            result = code_memory.search(self.contract(), {"query": "meta-analysis realure space", "limit": 8}, runner=runner)

        self.assertEqual(result["items"], [])
        self.assertNotIn("fallback_query", result)
        self.assertEqual(searched, ["meta-analysis realure space"])

    def test_search_filters_returned_items_by_route_excludes(self) -> None:
        def runner(argv: list[str], cwd: Path, timeout_sec: int) -> tuple[int, str, str]:
            if argv[:3] == ["docker", "image", "inspect"]:
                return 0, "[]", ""
            return 0, json.dumps({
                "results": [
                    {"label": "Variable", "name": "Widget", "file": "public/modules/voice/onnx/tokenizer.json"},
                    {"label": "Variable", "name": "INITIAL_WIDGET_LAYOUTS", "file": "public/app.js"},
                ]
            }), ""

        with patch.object(code_memory.shutil, "which", return_value="/usr/bin/docker"):
            result = code_memory.search(self.contract(), {"query": "widget", "limit": 8}, runner=runner)

        self.assertTrue(result["ok"])
        self.assertEqual([item["file"] for item in result["items"]], ["public/app.js"])

    def test_unavailable_binary_is_typed_not_exception(self) -> None:
        with patch.object(code_memory.shutil, "which", return_value=None):
            result = code_memory.search(self.contract(), {"query": "kernel"}, runner=lambda *_: (0, "{}", ""))

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "code_memory_unavailable")

    def test_ready_index_without_fingerprint_is_not_trusted(self) -> None:
        def runner(argv: list[str], cwd: Path, timeout_sec: int) -> tuple[int, str, str]:
            if argv[:3] == ["docker", "image", "inspect"]:
                return 0, "[]", ""
            return 0, json.dumps({"status": "ready", "nodes": 12}), ""

        with patch.object(code_memory.shutil, "which", return_value="/usr/bin/docker"), patch.object(
            code_memory,
            "freshness",
            return_value={"state": "unknown", "trusted": False, "workspace_fingerprint": "current", "indexed_fingerprint": ""},
        ):
            result = code_memory.status(self.contract(), {}, runner=runner)

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "code_memory_freshness_unknown")
        self.assertFalse(result["freshness"]["trusted"])

    def test_stale_index_blocks_search_receipts(self) -> None:
        def runner(argv: list[str], cwd: Path, timeout_sec: int) -> tuple[int, str, str]:
            if argv[:3] == ["docker", "image", "inspect"]:
                return 0, "[]", ""
            return 0, json.dumps({"results": [{"name": "old_symbol"}]}), ""

        with patch.object(code_memory.shutil, "which", return_value="/usr/bin/docker"), patch.object(
            code_memory,
            "freshness",
            return_value={"state": "stale", "trusted": False, "workspace_fingerprint": "new", "indexed_fingerprint": "old"},
        ):
            result = code_memory.search(self.contract(), {"query": "symbol"}, runner=runner)

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "code_memory_stale")

    def test_missing_source_index_fails_closed(self) -> None:
        contract = {
            "route_id": "test.no-index",
            "workspace_root": str(PLUGIN_ROOT),
            "allowed_read_roots": [str(PLUGIN_ROOT)],
        }

        result = code_memory.search(contract, {"query": "kernel"}, runner=lambda *_: (0, "{}", ""))

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "code_memory_index_contract_missing")

    def test_resource_limit_is_typed_not_exception(self) -> None:
        def runner(argv: list[str], cwd: Path, timeout_sec: int) -> tuple[int, str, str]:
            if argv[:3] == ["docker", "image", "inspect"]:
                return 0, "[]", ""
            return 137, "", "container memory limit exceeded"

        with patch.object(code_memory.shutil, "which", return_value="/usr/bin/docker"):
            result = code_memory.search(self.contract(), {"query": "kernel"}, runner=runner)

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "code_memory_resource_limit")

    def test_timeout_is_typed_not_exception(self) -> None:
        def runner(argv: list[str], cwd: Path, timeout_sec: int) -> tuple[int, str, str]:
            if argv[:3] == ["docker", "image", "inspect"]:
                return 0, "[]", ""
            raise subprocess.TimeoutExpired(argv, timeout_sec)

        with patch.object(code_memory.shutil, "which", return_value="/usr/bin/docker"):
            result = code_memory.search(self.contract(), {"query": "kernel"}, runner=runner)

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "code_memory_timeout")

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

    def test_runtime_entity_contract_preserves_llm_native_handles(self) -> None:
        raw = {
            "route_id": "test.frontier",
            "surface": "frontier-provider",
            "workspace_root": ".",
            "entities": [{
                "id": "frontier",
                "name": "Master:frontier",
                "kind": "first-class-agent-target",
                "node_id": "frontier",
                "selector": "__target:master_frontier__",
                "route_symbol": "AGENT_MASTER_FRONTIER_TARGET_ID",
                "symbols": ["AGENT_MASTER_FRONTIER_TARGET_ID"],
                "proof": ["route_contract"],
            }],
        }

        contract = route_contracts.normalize_contract(raw, PLUGIN_ROOT)

        entity = contract["entities"][0]
        self.assertEqual(entity["name"], "Master:frontier")
        self.assertEqual(entity["node_id"], "frontier")
        self.assertEqual(entity["selector"], "__target:master_frontier__")
        self.assertEqual(entity["route_symbol"], "AGENT_MASTER_FRONTIER_TARGET_ID")
        self.assertEqual(entity["symbols"], ["AGENT_MASTER_FRONTIER_TARGET_ID"])
        self.assertEqual(entity["proof"], ["route_contract"])


if __name__ == "__main__":
    unittest.main()
