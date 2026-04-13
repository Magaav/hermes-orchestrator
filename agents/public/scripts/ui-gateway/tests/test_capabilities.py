from __future__ import annotations

import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui_gateway.app import GatewayContext, build_capabilities
from ui_gateway.settings import GatewaySettings


class CapabilityTests(unittest.TestCase):
    def test_capabilities_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts" / "clone").mkdir(parents=True)
            clone_script = root / "scripts" / "clone" / "clone_manager.py"
            clone_script.write_text("#!/usr/bin/env python3\n")
            ui_root = root / "apps" / "wasm-ui"
            (ui_root / "wasm" / "log-worker" / "src").mkdir(parents=True)
            (ui_root / "wasm" / "log-worker" / "src" / "lib.rs").write_text("// test")

            settings = GatewaySettings(
                host="127.0.0.1",
                port=8787,
                repo_root=root,
                clone_manager_script=clone_script,
                python_bin="python3",
                agents_root=root / "agents",
                logs_root=root / "logs",
                node_logs_root=root / "logs" / "nodes",
                attention_logs_root=root / "logs" / "attention" / "nodes",
                ui_root=ui_root,
                api_token="",
                experimental=True,
                poll_interval_sec=2.0,
                max_tail_lines=1500,
                read_limit_per_minute=100,
                write_limit_per_minute=10,
            )
            ctx = GatewayContext(settings)
            caps = build_capabilities(ctx).to_dict()

            self.assertIn("core", caps)
            self.assertIn("enhanced", caps)
            self.assertTrue(caps["core"]["logs"])
            self.assertTrue(caps["enhanced"]["wasm_worker_rust_source"])


if __name__ == "__main__":
    unittest.main()
