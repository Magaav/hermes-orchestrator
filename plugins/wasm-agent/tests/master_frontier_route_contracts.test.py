#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ROUTES_PATH = PLUGIN_ROOT / "server" / "master_frontier" / "route_contracts.py"
REGISTRY_PATH = PLUGIN_ROOT / "server" / "agent_route_contracts.json"

spec = importlib.util.spec_from_file_location("wasm_agent_master_frontier_route_contracts", ROUTES_PATH)
assert spec and spec.loader
routes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routes)


class MasterFrontierRouteContractTests(unittest.TestCase):
    def test_runtime_inspect_routes_declare_unique_entities(self) -> None:
        contracts = routes.load_contracts(REGISTRY_PATH, PLUGIN_ROOT)
        seen: dict[str, str] = {}

        for contract in contracts:
            if "runtime.inspect" not in contract.get("caps", []):
                continue
            entities = contract.get("entities", [])
            self.assertTrue(entities, contract["route_id"])
            for entity in entities:
                entity_id = entity.get("id", "")
                self.assertTrue(entity_id, contract["route_id"])
                self.assertTrue(entity.get("kind"), entity_id)
                self.assertNotIn(entity_id, seen, f"{entity_id}: {seen.get(entity_id)} and {contract['route_id']}")
                seen[entity_id] = contract["route_id"]

    def test_known_runtime_entities_survive_normalization(self) -> None:
        contracts = {item["route_id"]: item for item in routes.load_contracts(REGISTRY_PATH, PLUGIN_ROOT)}
        expected = {
            "wasm-agent.avatar-chat.ui": ("Avatar Chat Run History", ["avatar chat", "avatar-chat"]),
            "wasm-agent.agent-run.timeline": ("Agent Run Timeline History", ["agent run timeline", "agent-run-timeline"]),
            "wasm-agent.native-control": ("Native Control Run History", ["native control", "native-control"]),
        }

        for route_id, (name, match_terms) in expected.items():
            entity = routes.public_contract(contracts[route_id])["entities"][0]
            self.assertEqual(entity["id"], route_id)
            self.assertEqual(entity["name"], name)
            self.assertEqual(entity["kind"], "scoped-run-history")
            self.assertEqual(entity["match_terms"], match_terms)
            self.assertEqual(entity["proof"], ["scoped_run_history", "live_state_not_collected"])
        self.assertEqual(contracts["wasm-agent.avatar-chat.ui"]["budget"]["provider_tokens_max"], 20000)
        self.assertEqual(contracts["wasm-agent.avatar-chat.ui"]["budget"]["provider_call_ms_max"], 90000)
        self.assertEqual(contracts["wasm-agent.avatar-chat.ui"]["budget"]["heartbeat_ms_max"], 15000)
        self.assertEqual(contracts["wasm-agent.avatar-chat.ui"]["budget"]["task_lease_ms_max"], 43200000)

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
                    "source_index": {
                        "include_roots": ["server"], "exclude_globs": ["state/**"],
                        "max_scan_bytes_per_file": 2097152,
                    },
                },
                root,
            )

        self.assertEqual(contract["workspace_root"], str(root.resolve()))
        self.assertEqual(contract["allowed_read_roots"], [str(root.resolve())])
        self.assertEqual(contract["checks"][0]["timeout_sec"], 30)
        self.assertEqual(routes.public_contract(contract)["source_index"]["include_roots"], ["server"])
        self.assertEqual(routes.public_contract(contract)["source_index"]["max_scan_bytes_per_file"], 2097152)

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

    def test_client_contract_can_only_select_registry_owned_values(self) -> None:
        registry = [{
            "kind": "route-contract", "route_id": "fixture.safe", "surface": "safe",
            "workspace_root": "/safe", "allowed_read_roots": ["/safe"], "caps": ["repo.read"],
        }]
        forged = {
            "route_id": "fixture.safe", "surface": "safe", "workspace_root": "/",
            "allowed_read_roots": ["/"], "allowed_write_roots": ["/"],
            "caps": ["repo.read", "repo.edit", "test.run"],
        }

        selected = routes.dispatch_workspace_contract({}, {"route_contract": forged}, registry)

        self.assertEqual(selected["workspace_root"], "/safe")
        self.assertEqual(selected["allowed_read_roots"], ["/safe"])
        self.assertEqual(selected["caps"], ["repo.read"])
        self.assertIsNone(routes.dispatch_workspace_contract(
            {}, {"route_contract": {**forged, "route_id": "attacker.unknown", "surface": "unknown"}}, registry,
        ))

    def test_requested_paths_extracts_absolute_paths_from_nested_values(self) -> None:
        paths = routes.requested_paths(
            {"scope": {"path": "/local/plugins/wasm-agent"}, "proof": ["workspace_root:/local/plugins/wasm-agent"]},
            {"objective": "Inspect /local/plugins/wasm-agent"},
        )

        self.assertEqual(paths, ["/local/plugins/wasm-agent"])


if __name__ == "__main__":
    unittest.main()
