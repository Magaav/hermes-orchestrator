#!/usr/bin/env python3
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import adapters, contracts, kernel  # noqa: E402


class V6KernelTests(unittest.TestCase):
    def test_schema_admission_rejects_unknown_and_mistyped_arguments(self) -> None:
        agent = kernel.Kernel(authorities={"repo.read"})
        capability = next(item for item in adapters.repository() if item["id"] == "repo.read")
        agent.register(capability, lambda _cap, _op: {"ok": True})
        with self.assertRaisesRegex(contracts.ContractError, "schema_type_mismatch"):
            agent.run("read", [{"id": "op.read", "cap": "repo.read", "args": {"path": 3}}])
        with self.assertRaisesRegex(contracts.ContractError, "schema_property_unknown"):
            agent.run("read", [{"id": "op.read", "cap": "repo.read", "args": {"path": "a", "surprise": True}}])

    def test_operation_replay_is_exactly_once_and_redefinition_fails(self) -> None:
        calls = []
        events = []
        agent = kernel.Kernel(authorities={"repo.edit"}, event_sink=events.append)
        capability = next(item for item in adapters.repository() if item["id"] == "repo.patch")
        agent.register(capability, lambda _cap, _op: calls.append("called") or {"ok": True, "observed": {"changed": True}})
        operation = {"id": "op.patch", "cap": "repo.patch", "args": {"operations": [{"op": "create", "path": "a.py", "content": "x", "expected_absent": True}]}}
        first = agent.run("patch", [operation])
        second = agent.run("patch", [operation])
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(calls, ["called"])
        self.assertEqual([item["type"] for item in events], ["operation.started", "operation.completed", "operation.replayed"])
        self.assertEqual(agent.journal()[0]["capability"], "repo.patch")
        changed = {**operation, "args": {"operations": [{"op": "create", "path": "b.py", "content": "x", "expected_absent": True}]}}
        self.assertFalse(agent.run("patch", [changed])["ok"])

    def test_snapshot_restores_evidence_and_prevents_mutation_replay(self) -> None:
        calls = []
        capability = next(item for item in adapters.repository() if item["id"] == "repo.patch")
        operation = {"id": "op.patch", "cap": "repo.patch", "args": {"operations": [{"op": "create", "path": "a.py", "content": "x", "expected_absent": True}]}}
        first = kernel.Kernel(authorities={"repo.edit"})
        first.register(capability, lambda _cap, _op: calls.append("first") or {"ok": True, "observed": {"changed": True}})
        result = first.run("patch", [operation])
        snapshot = first.snapshot(result["state"])
        resumed = kernel.Kernel(authorities={"repo.edit"})
        resumed.register(capability, lambda _cap, _op: calls.append("second") or {"ok": True})
        current = resumed.restore(snapshot)
        replay = resumed.execute(current, [operation])
        self.assertTrue(replay["ok"])
        self.assertEqual(calls, ["first"])
        self.assertIsNotNone(resumed.evidence.detail(replay["evidence"][0]["detail_ref"]))

    def test_snapshot_drops_operation_arguments_but_keeps_replay_digest(self) -> None:
        calls = []
        capability = contracts.capability({
            "id": "mcp.fixture.call", "kind": "act", "authority": "mcp.fixture.call",
            "executor": "mcp", "mode": "write",
            "input": {"type": "object", "properties": {"token": {"type": "string"}}},
        })
        operation = {"id": "op.secret", "cap": "mcp.fixture.call", "args": {"token": "never-persist-this"}}
        first = kernel.Kernel(authorities={"mcp.fixture.call"})
        first.register(capability, lambda _cap, _op: calls.append("first") or {"ok": True})
        result = first.run("Call", [operation])
        snapshot = first.snapshot(result["state"])
        self.assertNotIn("never-persist-this", contracts.canonical(snapshot))
        resumed = kernel.Kernel(authorities={"mcp.fixture.call"})
        resumed.register(capability, lambda _cap, _op: calls.append("second") or {"ok": True})
        current = resumed.restore(snapshot)
        replay = resumed.execute(current, [operation])
        self.assertTrue(replay["ok"])
        self.assertEqual(calls, ["first"])

    def test_executor_evidence_is_redacted_before_storage(self) -> None:
        agent = kernel.Kernel(authorities={"repo.read"})
        capability = next(item for item in adapters.repository() if item["id"] == "repo.read")
        agent.register(capability, lambda _cap, _op: {"ok": True, "observed": {"authorization": "Bearer very-secret-value", "content": "Bearer another-secret-value"}})
        result = agent.run("read", [{"id": "op.read", "cap": "repo.read", "args": {"path": "a.py"}}])
        detail = agent.evidence.detail(result["evidence"][0]["detail_ref"])
        self.assertEqual(detail["observed"]["authorization"], "[redacted]")
        self.assertEqual(detail["observed"]["content"], "Bearer [redacted]")

    def test_completion_gate_requires_declared_capabilities_after_patch(self) -> None:
        agent = kernel.Kernel(
            authorities={"repo.edit", "test.run", "proof.report"},
            completion_requirements={"repo.patch", "repo.test", "repo.diff", "repo.prove"},
        )
        for capability in adapters.repository():
            if capability["authority"] in agent.authorities:
                agent.register(capability, lambda _cap, _op: {"ok": True})
        current = agent.run("patch", [{"id": "op.patch", "cap": "repo.patch", "args": {"operations": [{"op": "create", "path": "a.py", "content": "x", "expected_absent": True}]}}])["state"]
        self.assertEqual(set(agent.completion_gaps()), {
            "completion:repo.diff", "completion:repo.prove", "completion:repo.test",
            "after:op.patch:repo.diff", "after:op.patch:repo.prove", "after:op.patch:repo.test",
        })
        result = agent.execute(current, [
            {"id": "op.test", "cap": "repo.test", "args": {"check_id": "focused"}},
            {"id": "op.diff", "cap": "repo.diff", "args": {}},
            {"id": "op.prove", "cap": "repo.prove", "args": {}},
        ])
        self.assertTrue(result["ok"])
        self.assertEqual(agent.completion_gaps(), [])

    def test_capability_catalog_compiles_mcp_without_prompt_dump(self) -> None:
        tools = [{
            "name": f"tool_{index}", "description": f"Inspect object {index}",
            "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
            "annotations": {"readOnlyHint": True},
        } for index in range(100)]
        capabilities = adapters.mcp("github", tools)
        agent = kernel.Kernel(authorities={item["authority"] for item in capabilities})
        for item in capabilities:
            agent.register(item, lambda _cap, _op: {"ok": True, "observed": {}})
        found = agent.catalog.search("inspect object 42", limit=5)
        self.assertLessEqual(len(found), 5)
        self.assertEqual(found[0]["id"], "mcp.github.tool-42")
        self.assertNotIn("input", found[0], "search returns a compact signature; schemas stay pull-on-demand")
        self.assertIn("input", agent.catalog.get(found[0]["id"]))

    def test_parallel_wave_executes_independent_operations_concurrently(self) -> None:
        capability = contracts.capability({"id": "repo.read", "kind": "observe", "authority": "repo.read", "executor": "read", "mode": "read"})
        lock = threading.Lock()
        active = 0
        peak = 0
        barrier = threading.Barrier(2)

        def execute(_cap, operation):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait(timeout=2)
            time.sleep(0.01)
            with lock:
                active -= 1
            return {"ok": True, "observed": {"path": operation["args"]["path"]}}

        agent = kernel.Kernel(authorities={"repo.read"}, max_parallel=4)
        agent.register(capability, execute)
        result = agent.run("Read both", [
            {"id": "op.a", "cap": "repo.read", "args": {"path": "a.py"}},
            {"id": "op.b", "cap": "repo.read", "args": {"path": "b.py"}},
        ])
        self.assertTrue(result["ok"])
        self.assertEqual(peak, 2)

    def test_conflicting_mutations_are_serialized(self) -> None:
        capability = contracts.capability({
            "id": "repo.patch", "kind": "act", "authority": "repo.edit", "executor": "patch", "mode": "write", "conflicts": ["repo:{path}"],
        })
        lock = threading.Lock()
        active = 0
        peak = 0

        def execute(_cap, operation):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return {"ok": True, "observed": {"path": operation["args"]["path"]}}

        agent = kernel.Kernel(authorities={"repo.edit"}, max_parallel=4)
        agent.register(capability, execute)
        result = agent.run("Patch", [
            {"id": "op.a", "cap": "repo.patch", "args": {"path": "same.py"}},
            {"id": "op.b", "cap": "repo.patch", "args": {"path": "same.py"}},
        ])
        self.assertTrue(result["ok"])
        self.assertEqual(peak, 1)

    def test_commentary_is_model_authored_and_tied_to_operation(self) -> None:
        updates = []
        capability = contracts.capability({"id": "client.inspect", "kind": "observe", "authority": "client.ui.inspect", "executor": "client"})
        agent = kernel.Kernel(authorities={"client.ui.inspect"}, commentary_sink=updates.append)
        agent.register(capability, lambda _cap, _op: {"ok": True, "observed": {"live": True}})
        result = agent.run("Inspect", [{
            "id": "op.client", "cap": "client.inspect", "args": {},
            "say": {"phase": "investigating", "message": "I found the declared client capability. I’m checking its live state now."},
        }])
        self.assertTrue(result["ok"])
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["authored_by"], "model")
        self.assertEqual(updates[0]["visibility"], "public")
        self.assertEqual(updates[0]["operation"], "op.client")

    def test_authority_and_expectations_are_fail_closed(self) -> None:
        capability = contracts.capability({"id": "client.open", "kind": "act", "authority": "client.ui.control", "executor": "client", "mode": "write"})
        denied = kernel.Kernel(authorities=set())
        denied.register(capability, lambda _cap, _op: {"ok": True})
        with self.assertRaisesRegex(contracts.ContractError, "kernel_authority_denied"):
            denied.run("Open", [{"id": "op.open", "cap": "client.open"}])
        allowed = kernel.Kernel(authorities={"client.ui.control"})
        allowed.register(capability, lambda _cap, _op: {"ok": True, "observed": {"opened": False}})
        result = allowed.run("Open", [{"id": "op.open", "cap": "client.open", "expect": {"opened": True}}])
        self.assertFalse(result["ok"])
        self.assertEqual(result["receipts"][0]["error"]["code"], "expectation_mismatch")

    def test_cancellation_returns_typed_receipt(self) -> None:
        capability = contracts.capability({"id": "repo.read", "kind": "observe", "authority": "repo.read", "executor": "read"})
        agent = kernel.Kernel(authorities={"repo.read"})
        agent.register(capability, lambda _cap, _op: {"ok": True})
        agent.cancel.set()
        result = agent.run("Read", [{"id": "op.read", "cap": "repo.read"}])
        self.assertFalse(result["ok"])
        self.assertEqual(result["receipts"][0]["state"], "cancelled")

    def test_goal_action_requires_successful_correlated_write(self) -> None:
        inspect = contracts.capability({
            "id": "client.inspect", "kind": "observe", "authority": "client.ui.inspect", "executor": "inspect",
        })
        act = contracts.capability({
            "id": "client.act", "kind": "act", "authority": "client.ui.control", "executor": "act", "mode": "write",
        })
        agent = kernel.Kernel(
            authorities={"client.ui.inspect", "client.ui.control"},
            completion_requirements={"goal_action"},
        )
        agent.register(inspect, lambda _cap, _op: {"ok": True})
        agent.register(act, lambda _cap, _op: {"ok": True})

        agent.run("Inspect", [{"id": "inspect.only", "cap": "client.inspect", "completes_goal": True}])
        self.assertEqual(agent.completion_gaps(), ["completion:goal_action"])
        agent.run("Setup", [{"id": "setup", "cap": "client.act"}])
        self.assertEqual(agent.completion_gaps(), ["completion:goal_action"])
        agent.run("Act", [{"id": "send", "cap": "client.act", "completes_goal": True}])
        self.assertEqual(agent.completion_gaps(), [])
        restored = kernel.Kernel(
            authorities={"client.ui.inspect", "client.ui.control"},
            completion_requirements={"goal_action"},
        )
        restored.register(inspect, lambda _cap, _op: {"ok": True})
        restored.register(act, lambda _cap, _op: {"ok": True})
        restored.restore(agent.snapshot(agent.run("State", [])["state"]))
        self.assertEqual(restored.completion_gaps(), [])

    def test_shared_cancellation_stops_queued_parallel_operations(self) -> None:
        capability = contracts.capability({"id": "repo.read", "kind": "observe", "authority": "repo.read", "executor": "read"})
        cancel = threading.Event()
        started = threading.Barrier(3)
        release = threading.Event()
        calls = []

        def execute(_cap, operation):
            calls.append(operation["id"])
            started.wait(timeout=2)
            release.wait(timeout=2)
            return {"ok": True}

        agent = kernel.Kernel(authorities={"repo.read"}, max_parallel=2, cancel_event=cancel)
        agent.register(capability, execute)
        observed = {}

        def run():
            observed["result"] = agent.run("Read", [
                {"id": f"op.{index}", "cap": "repo.read"} for index in range(20)
            ])

        worker = threading.Thread(target=run)
        worker.start()
        started.wait(timeout=2)
        cancel.set()
        release.set()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(calls), 2)
        cancelled = [item for item in observed["result"]["receipts"] if item["state"] == "cancelled"]
        self.assertEqual(len(cancelled), 18)


if __name__ == "__main__":
    unittest.main()
