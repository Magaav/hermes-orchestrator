from __future__ import annotations

import json
import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui_gateway.clone_manager import discover_nodes
from ui_gateway.settings import GatewaySettings


class DiscoverNodesTests(unittest.TestCase):
    def test_reads_registry_envs_and_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents = root / "agents"
            (agents / "envs").mkdir(parents=True)
            (agents / "nodes").mkdir(parents=True)
            (root / "logs" / "nodes").mkdir(parents=True)
            (root / "logs" / "attention" / "nodes").mkdir(parents=True)
            (root / "apps" / "wasm-ui").mkdir(parents=True)
            (root / "scripts" / "clone").mkdir(parents=True)

            (agents / "envs" / "orchestrator.env").write_text("x=1\n", encoding="utf-8")
            (agents / "nodes" / "worker-a").mkdir()

            registry = {
                "version": 2,
                "clones": {
                    "colmeio": {"clone_name": "colmeio"},
                    "bad_name": {"clone_name": "INVALID.NAME"},
                },
            }
            (agents / "registry.json").write_text(json.dumps(registry), encoding="utf-8")

            clone_script = root / "scripts" / "clone" / "clone_manager.py"
            clone_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

            settings = GatewaySettings(
                host="127.0.0.1",
                port=8787,
                repo_root=root,
                clone_manager_script=clone_script,
                python_bin="python3",
                agents_root=agents,
                logs_root=root / "logs",
                node_logs_root=root / "logs" / "nodes",
                attention_logs_root=root / "logs" / "attention" / "nodes",
                node_activity_root=root / "logs" / "nodes" / "activities",
                guard_logs_root=root / "logs" / "guard",
                ui_root=root / "apps" / "wasm-ui",
                api_token="",
                experimental=True,
                poll_interval_sec=2.0,
                max_tail_lines=1500,
                read_limit_per_minute=100,
                write_limit_per_minute=10,
            )

            nodes = discover_nodes(settings)

            self.assertEqual(nodes[0], "orchestrator")
            self.assertIn("worker-a", nodes)
            self.assertIn("colmeio", nodes)
            self.assertNotIn("bad_name", nodes)


if __name__ == "__main__":
    unittest.main()
