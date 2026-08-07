#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import contracts, kernel, mcp_host  # noqa: E402


class V6McpHostTests(unittest.TestCase):
    @staticmethod
    def manifests():
        return [{"id": "github", "tools": [
            {"name": "get_issue", "description": "Read one issue", "inputSchema": {"type": "object", "required": ["number"], "properties": {"number": {"type": "integer"}}, "additionalProperties": False}, "annotations": {"readOnlyHint": True}},
            {"name": "create_issue", "description": "Create one issue", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": False}},
        ]}]

    def test_read_only_route_filters_mutating_mcp_tools(self) -> None:
        route = {"mcp": {"servers": [{"id": "github", "tools": ["get_issue"], "mode": "read-only"}]}}
        bindings = mcp_host.compile(route, self.manifests())
        self.assertEqual([item["tool"] for item in bindings], ["get_issue"])
        calls = []
        agent = kernel.Kernel(authorities={bindings[0]["capability"]["authority"]})
        mcp_host.register(agent, bindings, lambda server, tool, args: calls.append((server, tool, args)) or {"structuredContent": {"title": "bug"}})
        result = agent.run("Read issue", [{"id": "op.issue", "cap": "mcp.github.get-issue", "args": {"number": 7}}])
        self.assertTrue(result["ok"])
        self.assertEqual(calls, [("github", "get_issue", {"number": 7})])

    def test_missing_server_and_missing_allowlist_fail_before_dispatch(self) -> None:
        with self.assertRaisesRegex(contracts.ContractError, "mcp_declared_server_missing"):
            mcp_host.compile({"mcp": {"servers": [{"id": "linear", "tools": ["*"]}]}}, self.manifests())
        with self.assertRaisesRegex(contracts.ContractError, "mcp_tool_allowlist_missing"):
            mcp_host.compile({"mcp": {"servers": [{"id": "github"}]}}, self.manifests())
        with self.assertRaisesRegex(contracts.ContractError, "mcp_read_only_wildcard_denied"):
            mcp_host.compile({"mcp": {"servers": [{"id": "github", "tools": ["*"], "mode": "read-only"}]}}, self.manifests())

    def test_normalized_name_collision_gets_stable_distinct_capability(self) -> None:
        manifests = [{"id": "fixture", "tools": [
            {"name": "read_item", "annotations": {"readOnlyHint": True}},
            {"name": "read-item", "annotations": {"readOnlyHint": True}},
        ]}]
        bindings = mcp_host.compile({"mcp": {"servers": [{"id": "fixture", "tools": ["read_item", "read-item"], "mode": "read-only"}]}}, manifests)
        identifiers = [item["capability"]["id"] for item in bindings]
        self.assertEqual(len(set(identifiers)), 2)
        self.assertTrue(identifiers[1].startswith("mcp.fixture.read-item-"))


if __name__ == "__main__":
    unittest.main()
