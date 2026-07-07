#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class CodeMemoryAgentContractTests(unittest.TestCase):
    def test_code_memory_helper_returns_compact_route_scoped_results(self) -> None:
        proc = subprocess.run(
            [
                "python3",
                "tools/context/code-memory-query.py",
                "--route-id",
                "wasm-agent.avatar-chat.ui",
                "requires_structured_action",
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
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
