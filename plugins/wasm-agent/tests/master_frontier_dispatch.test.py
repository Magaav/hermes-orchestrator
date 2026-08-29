#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PLUGIN_ROOT / "server"
DISPATCH_PATH = SERVER_ROOT / "master_frontier" / "dispatch.py"

sys.path.insert(0, str(SERVER_ROOT))

spec = importlib.util.spec_from_file_location("master_frontier.dispatch", DISPATCH_PATH)
assert spec and spec.loader
dispatch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatch)


class MasterFrontierDispatchTests(unittest.TestCase):
    def test_caps_accept_string_and_report_unknown(self) -> None:
        action = {"caps": "repo.read, proof.report, root.secret"}

        self.assertEqual(dispatch.dispatch_caps(action), ["repo.read", "proof.report", "root.secret"])
        self.assertEqual(dispatch.unknown_caps(action), ["root.secret"])

    def test_escalation_reason_accepts_fallback_reason(self) -> None:
        action = {"fallback_reason": "provider api key is not configured"}

        self.assertEqual(dispatch.escalation_reason(action), "provider api key is not configured")

    def test_prompt_workspace_contract_drops_non_authority_context(self) -> None:
        projected = dispatch.prompt_workspace_contract({
            "route_id": "wasm-agent.avatar-chat.ui",
            "workspace_root": "/local/plugins/wasm-agent",
            "allowed_read_roots": ["/local/plugins/wasm-agent"],
            "allowed_write_roots": ["/local/plugins/wasm-agent"],
            "caps": ["repo.read", "repo.edit"],
            "client_ui": {"widget_ids": ["browser"]},
            "source_index": {"include_roots": ["server", "public", "tests"]},
            "checks": [{"id": "full-suite"}],
        })

        self.assertEqual(projected["route_id"], "wasm-agent.avatar-chat.ui")
        self.assertEqual(projected["allowed_read_roots"], ["/local/plugins/wasm-agent"])
        self.assertNotIn("client_ui", projected)
        self.assertNotIn("source_index", projected)
        self.assertNotIn("checks", projected)
        self.assertNotIn("caps", projected)

    def test_runtime_entity_dispatch_ignores_repo_edit_implementation(self) -> None:
        envelope = {"objective": "Go ahead and build the MCP files", "capabilities": ["repo.edit", "test.run"]}

        self.assertFalse(dispatch.is_runtime_entity_dispatch({"caps": ["repo.edit", "runtime.inspect"]}, envelope))
        self.assertTrue(dispatch.is_runtime_entity_dispatch({"caps": ["runtime.inspect"]}, {"objective": "Who is Paracelsus?"}))

    def test_hermes_dispatch_must_be_declared_as_harness_subagent(self) -> None:
        self.assertTrue(dispatch.is_harness_subagent_dispatch({"role": "subagent_harness"}))
        self.assertTrue(dispatch.is_harness_subagent_dispatch({"harness": True}))
        self.assertFalse(dispatch.is_harness_subagent_dispatch({"action": "dispatch.hermes"}))

    def test_hermes_dispatch_requires_explicit_user_request(self) -> None:
        self.assertTrue(dispatch.explicit_hermes_requested({"objective": "please use Hermes for this proof"}))
        self.assertTrue(dispatch.explicit_hermes_requested({"allow_hermes": True, "objective": "inspect locally"}))
        self.assertFalse(dispatch.explicit_hermes_requested({"objective": "inspect locally", "allowed_actions": [{"id": "dispatch.hermes"}]}))


if __name__ == "__main__":
    unittest.main()
