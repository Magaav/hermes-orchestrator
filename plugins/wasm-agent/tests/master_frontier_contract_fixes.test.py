#!/usr/bin/env python3
from __future__ import annotations

import json
import importlib.util
import sys
import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import inspect_contract, persistence  # noqa: E402

STATIC_SPEC = importlib.util.spec_from_file_location("wasm_agent_contract_static", SERVER / "static_server.py")
assert STATIC_SPEC and STATIC_SPEC.loader
static_server = importlib.util.module_from_spec(STATIC_SPEC)
STATIC_SPEC.loader.exec_module(static_server)


class MasterFrontierContractFixesTests(unittest.TestCase):
    def test_inspect_contract_exposes_supported_kinds_and_source_fallback(self) -> None:
        self.assertEqual(inspect_contract.canonical("map"), "route")
        self.assertEqual(inspect_contract.canonical("symbols"), "symbols")
        self.assertIsNone(inspect_contract.canonical("widget"))
        unsupported = inspect_contract.unsupported("widget")
        self.assertEqual(unsupported["code"], "inspect_kind_unsupported")
        self.assertEqual(unsupported["suggested_primitive"], "compound.source.discovery")
        self.assertIn("runtime_entity", unsupported["supported_kinds"])

    def test_bounded_json_is_always_valid_and_inside_limit(self) -> None:
        value = {"ledger": [{"input": "x" * 1000, "output": "y" * 1000} for _ in range(30)]}
        encoded = persistence.bounded_json_text(value, 24_000)
        decoded = json.loads(encoded)
        self.assertLessEqual(len(encoded), 24_000)
        self.assertTrue(decoded["truncated"])
        self.assertEqual(decoded["schema"], persistence.TRUNCATED_SCHEMA)
        self.assertGreater(decoded["original_chars"], len(encoded))

    def test_kernel_inspect_reports_unsupported_source_kind_without_claiming_found(self) -> None:
        result = static_server.kernel_inspect_tool(
            object(),
            {"route_id": "wasm-agent.avatar-chat.ui", "inspect": "widget"},
            {"id": "1", "role": "admin", "email": "admin@example.test"},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["observation_count"], 0)
        self.assertEqual(result["capability_health"], "capability_blocked")
        self.assertEqual(result["unknowns"][0]["code"], "inspect_kind_unsupported")
        self.assertEqual(result["unknowns"][0]["suggested_primitive"], "compound.source.discovery")


if __name__ == "__main__":
    unittest.main()
