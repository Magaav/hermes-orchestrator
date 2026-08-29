#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import authority, planner  # noqa: E402
from master_frontier.v6 import claim_gate, contracts, controller, kernel  # noqa: E402


def tool(name: str, arguments: dict) -> dict:
    return {
        "reply": "",
        "tool_calls": [{"id": f"call-{name}", "name": name, "arguments": arguments}],
        "usage": {"total_tokens": 10},
    }


def final(answer: str, claims: list[dict]) -> dict:
    return {
        "reply": json.dumps({"schema": claim_gate.SCHEMA, "answer": answer, "claims": claims}),
        "usage": {"total_tokens": 10},
    }


class V6ClaimGateTests(unittest.TestCase):
    def runtime_kernel(self) -> kernel.Kernel:
        agent = kernel.Kernel(authorities={"client.ui.inspect"})
        agent.register(contracts.capability({
            "id": "client.surface.inspect", "kind": "observe",
            "authority": "client.ui.inspect", "executor": "client.surface.inspect",
            "mode": "read", "proof": ["client.surface.snapshot"],
            "input": {"type": "object", "properties": {}, "additionalProperties": False},
        }), lambda _capability, _operation: {
            "ok": True,
            "observed": {"surface": "fixture", "controls": 7},
            "proof": ["client.surface.snapshot"],
        })
        return agent

    def test_runtime_claim_requires_viewed_capability_declared_proof(self) -> None:
        agent = self.runtime_kernel()
        result = agent.run("inspect", [{"id": "op.inspect", "cap": "client.surface.inspect"}])
        contract = claim_gate.parse(final("Seven controls are visible.", [{
            "id": "controls", "scope": "runtime", "statement": "Seven controls are visible.",
            "operations": ["op.inspect"], "proof": ["client.surface.snapshot"],
        }])["reply"])

        self.assertEqual(
            claim_gate.gaps(contract, agent, viewed_operations=set(), evidence_floor="runtime"),
            ["claim:controls:unviewed"],
        )
        self.assertEqual(
            claim_gate.gaps(contract, agent, viewed_operations={"op.inspect"}, evidence_floor="runtime"),
            [],
        )
        self.assertEqual(result["receipts"][0]["proof"], ["client.surface.snapshot"])

    def test_verification_claim_accepts_proof_owned_observation(self) -> None:
        agent = kernel.Kernel(authorities={"client.ui.inspect"})
        agent.register(contracts.capability({
            "id": "client.windows.desktop.windows.list", "kind": "observe",
            "authority": "client.ui.inspect", "executor": "client.windows.desktop.windows.list",
            "mode": "read", "proof": ["windows.desktop.top_level_windows"],
            "input": {"type": "object", "properties": {}, "additionalProperties": False},
        }), lambda _capability, _operation: {
            "ok": True, "observed": {"windowCount": 12},
            "proof": ["windows.desktop.top_level_windows"],
        })
        agent.run("list windows", [{
            "id": "list-visible-windows", "cap": "client.windows.desktop.windows.list", "args": {},
        }])
        contract = claim_gate.parse(final("Twelve windows are visible.", [{
            "id": "windows", "scope": "verification", "statement": "Twelve windows are visible.",
            "operations": ["list-visible-windows"], "proof": ["windows.desktop.top_level_windows"],
        }])["reply"])

        self.assertEqual(
            claim_gate.gaps(contract, agent, viewed_operations={"list-visible-windows"}, evidence_floor="runtime"),
            [],
        )

    def test_verification_claim_rejects_observation_without_declared_proof(self) -> None:
        agent = kernel.Kernel(authorities={"client.ui.inspect"})
        agent.register(contracts.capability({
            "id": "client.surface.inspect", "kind": "observe", "authority": "client.ui.inspect",
            "executor": "client.surface.inspect", "mode": "read",
            "input": {"type": "object", "properties": {}, "additionalProperties": False},
        }), lambda _capability, _operation: {"ok": True, "observed": {"controls": 7}})
        agent.run("inspect", [{"id": "op.inspect", "cap": "client.surface.inspect", "args": {}}])
        contract = claim_gate.parse(final("The inspection is verified.", [{
            "id": "inspection", "scope": "verification", "statement": "The inspection is verified.",
            "operations": ["op.inspect"],
        }])["reply"])

        self.assertEqual(
            claim_gate.gaps(contract, agent, viewed_operations={"op.inspect"}, evidence_floor="runtime"),
            ["claim:inspection:verification_proof"],
        )

    def test_route_claim_must_cite_route_contract_evidence(self) -> None:
        agent = self.runtime_kernel()
        route = agent.evidence.put(
            kind="route.contract", subject="route:fixture", summary="Fixture route", detail={"route_id": "fixture"},
        )
        unsupported = claim_gate.parse(final("The route is available.", [{
            "id": "route", "scope": "route", "statement": "The route is available.",
        }])["reply"])
        supported = claim_gate.parse(final("The route is available.", [{
            "id": "route", "scope": "route", "statement": "The route is available.",
            "evidence": [route["id"]],
        }])["reply"])

        self.assertEqual(
            claim_gate.gaps(unsupported, agent, viewed_operations=set(), evidence_floor="route"),
            ["claim:route:route_evidence"],
        )
        self.assertEqual(
            claim_gate.gaps(supported, agent, viewed_operations=set(), evidence_floor="route"),
            [],
        )

    def test_nonconceptual_controller_rejects_prose_then_accepts_receipt_bound_claim(self) -> None:
        agent = self.runtime_kernel()
        decisions = iter([
            {"reply": "I can inspect the current surface.", "usage": {"total_tokens": 10}},
            tool("execute", {"operations": [{
                "id": "op.inspect", "cap": "client.surface.inspect", "args": {},
            }]}),
            final("The current surface exposes seven controls.", [{
                "id": "controls", "scope": "runtime",
                "statement": "The current surface exposes seven controls.",
                "operations": ["op.inspect"], "proof": ["client.surface.snapshot"],
            }]),
        ])
        contexts = []

        def complete(messages, _tools, _index):
            contexts.append(messages[-1]["content"])
            return next(decisions)

        result = controller.run(
            "Inspect the current surface", agent, complete,
            initial_discovered={"client.surface.inspect"},
            final_contract_required=True, evidence_floor="runtime",
        )

        self.assertEqual(result["answer"], "The current surface exposes seven controls.")
        self.assertEqual(result["final_claims"]["claims"][0]["operations"], ["op.inspect"])
        self.assertIn('M\t"final:final_claim_json_invalid"', contexts[1])
        self.assertEqual(len(contexts), 3)

    def test_source_claim_cannot_satisfy_runtime_floor(self) -> None:
        agent = kernel.Kernel(authorities={"repo.read"})
        agent.register(contracts.capability({
            "id": "repo.read", "kind": "observe", "authority": "repo.read",
            "executor": "repo.read", "mode": "read",
        }), lambda _capability, _operation: {"ok": True, "observed": {"content": "x"}})
        agent.run("read", [{"id": "op.read", "cap": "repo.read", "args": {}}])
        contract = claim_gate.parse(final("The source contains x.", [{
            "id": "source", "scope": "source", "statement": "The source contains x.",
            "operations": ["op.read"],
        }])["reply"])

        self.assertEqual(
            claim_gate.gaps(contract, agent, viewed_operations={"op.read"}, evidence_floor="runtime"),
            ["claim:floor:runtime", "claim:source:scope:source"],
        )

    def test_observed_miss_is_a_fixture_for_generic_contracts_not_a_product_selector(self) -> None:
        route = {
            "route_id": "fixture.avatar", "workspace_root": "/workspace",
            "caps": ["repo.read", "runtime.inspect", "client.ui.inspect"],
            "client_ui": {"operations": ["inspect", "windows_desktop_inspect"]},
        }
        inventory = planner.task_contract({
            "objective": "Inspect my Windows desktop and tell me which applications and controls are currently available",
            "objective_kind": "diagnosis", "route_contract": route,
        })
        critique = planner.task_contract({
            "objective": "why have you finalled answer instead of verify?",
            "objective_kind": "diagnosis", "route_contract": route,
        })
        projected = authority.project_task_contract({"task_contract": critique}, route)

        self.assertEqual(inventory["completion_capabilities"], ["authority:client.ui.inspect"])
        self.assertNotIn("client.windows.desktop.inspect", inventory["completion_capabilities"])
        self.assertEqual(inventory["finalization_contract"], "claim_bound")
        self.assertEqual(projected["request_class"], "model_decision")
        self.assertEqual(critique["finalization_contract"], "claim_bound")


if __name__ == "__main__":
    unittest.main()
