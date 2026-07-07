#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = PLUGIN_ROOT / "server" / "master_frontier" / "protocol.py"

spec = importlib.util.spec_from_file_location("wasm_agent_master_frontier_protocol", PROTOCOL_PATH)
assert spec and spec.loader
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)


class MasterFrontierProtocolTests(unittest.TestCase):
    def test_local_tool_manifest_owns_kernel_and_node_paths(self) -> None:
        self.assertEqual(protocol.LOCAL_TOOL_PATHS["kernel.resolve"], "/agent/tools/kernel.resolve")
        self.assertEqual(protocol.LOCAL_TOOL_PATHS["node.chat"], "/agent/tools/node.chat")
        self.assertEqual(protocol.LOCAL_TOOL_PATHS["hermes.capabilities"], "/agent/tools/hermes.capabilities")

    def test_kernel_action_paths_exclude_bridge_only_capability_probe(self) -> None:
        self.assertIn("node.chat", protocol.KERNEL_ACTION_TOOL_PATHS)
        self.assertNotIn("hermes.capabilities", protocol.KERNEL_ACTION_TOOL_PATHS)

    def test_default_output_schema_is_action_capable(self) -> None:
        self.assertIn("actions", protocol.DEFAULT_OUTPUT_SCHEMA["required"])
        self.assertEqual(protocol.DEFAULT_OUTPUT_SCHEMA["properties"]["confidence"]["type"], "number")


if __name__ == "__main__":
    unittest.main()
