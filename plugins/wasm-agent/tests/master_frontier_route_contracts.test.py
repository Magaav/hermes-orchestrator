#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ROUTES_PATH = PLUGIN_ROOT / "server" / "master_frontier" / "route_contracts.py"

spec = importlib.util.spec_from_file_location("wasm_agent_master_frontier_route_contracts", ROUTES_PATH)
assert spec and spec.loader
routes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routes)


class MasterFrontierRouteContractTests(unittest.TestCase):
    def test_normalize_contract_resolves_relative_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = routes.normalize_contract(
                {
                    "route_id": "wasm-agent.avatar-chat.ui",
                    "surface": "avatar-chat",
                    "workspace_root": ".",
                    "allowed_read_roots": ["."],
                    "checks": [{"id": "provider-proxy", "command": ["python3", "tests/provider_proxy.test.py"]}],
                },
                root,
            )

        self.assertEqual(contract["workspace_root"], str(root.resolve()))
        self.assertEqual(contract["allowed_read_roots"], [str(root.resolve())])
        self.assertEqual(contract["checks"][0]["timeout_sec"], 30)

    def test_dispatch_workspace_path_scope_wins_over_runtime_proof_hint(self) -> None:
        contracts = [
            {
                "kind": "route-contract",
                "route_id": "wasm-agent.avatar-chat.ui",
                "surface": "avatar-chat",
                "workspace_root": "/local/plugins/wasm-agent",
                "cwd": "/local/plugins/wasm-agent",
                "allowed_read_roots": ["/local/plugins/wasm-agent"],
            },
            {
                "kind": "route-contract",
                "route_id": "hermes-node.paracelsus.runtime",
                "surface": "paracelsus-node",
                "workspace_root": "/local/agents/nodes/paracelsus",
                "cwd": "/local/agents/nodes/paracelsus",
                "allowed_read_roots": ["/local/agents/nodes/paracelsus"],
            },
        ]
        action = {
            "action": "dispatch.hermes",
            "objective": "Inspect /local/plugins/wasm-agent repo structure and Paracelsus runtime.",
            "proof": ["route_id:hermes-node.paracelsus.runtime", "workspace_root:/local/plugins/wasm-agent"],
        }
        envelope = {
            "route_id": "wasm-agent.avatar-chat.ui",
            "surface": "avatar-chat",
            "route_contract": contracts[0],
        }

        selected = routes.dispatch_workspace_contract(action, envelope, contracts)

        self.assertEqual(selected["route_id"], "wasm-agent.avatar-chat.ui")

    def test_free_text_route_mentions_do_not_authorize_dispatch_scope(self) -> None:
        contracts = [
            {
                "kind": "route-contract",
                "route_id": "wasm-agent.avatar-chat.ui",
                "surface": "avatar-chat",
                "workspace_root": "/local/plugins/wasm-agent",
                "cwd": "/local/plugins/wasm-agent",
                "allowed_read_roots": ["/local/plugins/wasm-agent"],
            },
            {
                "kind": "route-contract",
                "route_id": "hermes-node.paracelsus.runtime",
                "surface": "paracelsus-node",
                "workspace_root": "/local/agents/nodes/paracelsus",
                "cwd": "/local/agents/nodes/paracelsus",
                "allowed_read_roots": ["/local/agents/nodes/paracelsus"],
            },
        ]
        action = {
            "action": "dispatch.hermes",
            "objective": "Inspect Paracelsus.",
            "proof": ["route_id:hermes-node.paracelsus.runtime"],
            "refs": ["route_id=hermes-node.paracelsus.runtime"],
        }
        envelope = {"objective": "Tell me about Paracelsus."}

        self.assertEqual(routes.explicit_route_ids(action, contracts), [])
        self.assertIsNone(routes.dispatch_workspace_contract(action, envelope, contracts))

    def test_structured_route_id_authorizes_dispatch_scope(self) -> None:
        contracts = [
            {
                "kind": "route-contract",
                "route_id": "wasm-agent.avatar-chat.ui",
                "surface": "avatar-chat",
                "workspace_root": "/local/plugins/wasm-agent",
                "cwd": "/local/plugins/wasm-agent",
                "allowed_read_roots": ["/local/plugins/wasm-agent"],
            },
        ]
        action = {"action": "dispatch.hermes", "route_id": "wasm-agent.avatar-chat.ui"}

        selected = routes.dispatch_workspace_contract(action, {}, contracts)

        self.assertEqual(selected["route_id"], "wasm-agent.avatar-chat.ui")

    def test_requested_paths_extracts_absolute_paths_from_nested_values(self) -> None:
        paths = routes.requested_paths(
            {"scope": {"path": "/local/plugins/wasm-agent"}, "proof": ["workspace_root:/local/plugins/wasm-agent"]},
            {"objective": "Inspect /local/plugins/wasm-agent"},
        )

        self.assertEqual(paths, ["/local/plugins/wasm-agent"])


if __name__ == "__main__":
    unittest.main()
