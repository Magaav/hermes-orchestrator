#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "wasm-agent"
SERVER_ROOT = PLUGIN_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from master_frontier import code_memory, route_contracts  # noqa: E402


class CodeMemoryAgentContractTests(unittest.TestCase):
    def test_code_memory_helper_returns_compact_route_scoped_results(self) -> None:
        contracts = route_contracts.load_contracts(SERVER_ROOT / "agent_route_contracts.json", PLUGIN_ROOT.resolve())
        contract = next(item for item in contracts if item.get("route_id") == "wasm-agent.avatar-chat.ui")

        def runner(argv: list[str], cwd: Path, timeout_sec: int) -> tuple[int, str, str]:
            payload = {
                "results": [{
                    "name": "requires_structured_action",
                    "file_path": "server/master_frontier/envelope.py",
                    "line": 265,
                    "body": "not included without include_raw",
                }]
            }
            return 0, json.dumps(payload), ""

        with patch.object(code_memory.shutil, "which", return_value="/usr/bin/docker"), patch.object(
            code_memory,
            "freshness",
            return_value={"state": "fresh", "trusted": True, "workspace_fingerprint": "test", "indexed_fingerprint": "test"},
        ):
            result = code_memory.search(contract, {"query": "requires_structured_action"}, runner=runner)

        self.assertTrue(result["ok"])
        self.assertEqual(result["primitive"], "code.memory.search")
        self.assertEqual(result["route_id"], "wasm-agent.avatar-chat.ui")
        self.assertTrue(any(item.get("file_path") == "server/master_frontier/envelope.py" for item in result["items"]))
        self.assertIsNone(result.get("raw"))

    def test_docs_require_code_memory_before_broad_codebase_reads(self) -> None:
        agents = (ROOT / "plugins" / "wasm-agent" / "AGENTS.md").read_text(encoding="utf-8")
        server_readme = (ROOT / "plugins" / "wasm-agent" / "server" / "README.md").read_text(encoding="utf-8")
        route_map = (ROOT / "docs" / "context" / "MAP.md").read_text(encoding="utf-8")

        self.assertIn("use the Master:frontier code-memory", agents)
        self.assertIn("lane before broad `rg`", agents)
        self.assertIn("primary codebase route", server_readme)
        self.assertIn("broad `rg`/multi-file reads as the first step", route_map)


if __name__ == "__main__":
    unittest.main()
