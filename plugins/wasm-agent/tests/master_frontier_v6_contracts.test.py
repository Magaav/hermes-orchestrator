#!/usr/bin/env python3
from __future__ import annotations

import sys
import struct
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import contracts, dag, evidence, projection, state  # noqa: E402


class V6ContractsTests(unittest.TestCase):
    def capabilities(self) -> dict[str, dict]:
        values = [
            {"id": "repo.source.read", "kind": "observe", "authority": "repo.read", "executor": "repo", "mode": "read", "summary": "Read source"},
            {"id": "repo.patch.apply", "kind": "act", "authority": "repo.edit", "executor": "repo", "mode": "write", "conflicts": ["repo:{path}"], "summary": "Patch source"},
            {"id": "client.widget.open", "kind": "act", "authority": "client.ui.control", "executor": "client", "mode": "write", "conflicts": ["client:{client}"], "summary": "Open widget"},
            {"id": "repo.test.run", "kind": "verify", "authority": "test.run", "executor": "repo", "mode": "write", "conflicts": ["repo:worktree"], "summary": "Run check"},
        ]
        return {item["id"]: contracts.capability(item) for item in values}

    def test_canonical_json_rejects_ambiguous_values(self) -> None:
        self.assertEqual(contracts.canonical({"b": 2, "a": 1}), '{"a":1,"b":2}')
        self.assertEqual(
            contracts.canonical([1.0, -0.0, 1e-7, 1e-6, 1e20, 1e21]),
            '[1,0,1e-7,0.000001,100000000000000000000,1e+21]',
        )
        with self.assertRaisesRegex(contracts.ContractError, "json_duplicate_key"):
            contracts.decode('{"a":1,"a":2}')
        with self.assertRaisesRegex(contracts.ContractError, "json_number_non_finite"):
            contracts.canonical({"x": float("nan")})
        with self.assertRaisesRegex(contracts.ContractError, "json_integer_unsafe"):
            contracts.canonical({"x": 9_007_199_254_740_992})
        with self.assertRaisesRegex(contracts.ContractError, "json_unicode_invalid"):
            contracts.canonical({"x": "\ud800"})

    def test_canonical_json_allows_composed_evidence_but_bounds_hostile_depth(self) -> None:
        def nested(depth: int):
            value = "leaf"
            for _index in range(depth):
                value = {"child": value}
            return value

        self.assertIn('"leaf"', contracts.canonical(nested(64)))
        with self.assertRaisesRegex(contracts.ContractError, "json_depth_exceeded"):
            contracts.canonical(nested(65))

    def test_commentary_phase_is_non_blocking_presentation_metadata(self) -> None:
        self.assertEqual(
            contracts.commentary({"phase": "editing", "message": "Applying the patch."})["phase"],
            "acting",
        )
        self.assertEqual(
            contracts.commentary({"phase": "testing", "message": "Running the check."})["phase"],
            "checking",
        )
        self.assertEqual(
            contracts.commentary({"phase": "custom-progress", "message": "Continuing."})["phase"],
            "acting",
        )

    def test_terminal_result_is_opt_in_and_requires_trusted_write_proof(self) -> None:
        terminal = contracts.capability({
            "id": "client.browser.inspect", "kind": "observe", "authority": "client.ui.inspect",
            "executor": "client.browser.inspect", "terminal_result": True,
        })
        self.assertTrue(terminal["terminal_result"])
        ordinary = contracts.capability({
            "id": "repo.read", "kind": "observe", "authority": "repo.read", "executor": "repo.read",
        })
        self.assertFalse(ordinary["terminal_result"])
        write = contracts.capability({
            "id": "client.space.open", "kind": "act", "authority": "client.ui.control",
            "executor": "client.space.open", "mode": "write", "proof": ["client.space.active"],
            "terminal_result": True,
        })
        self.assertTrue(write["terminal_result"])
        with self.assertRaisesRegex(contracts.ContractError, "capability_terminal_result_unsafe"):
            contracts.capability({"id": "unsafe.write", "kind": "act", "authority": "write", "executor": "write", "terminal_result": True})

    def test_canonical_numbers_match_rfc_8785_appendix_b(self) -> None:
        vectors = {
            "0000000000000000": "0",
            "8000000000000000": "0",
            "0000000000000001": "5e-324",
            "8000000000000001": "-5e-324",
            "7fefffffffffffff": "1.7976931348623157e+308",
            "ffefffffffffffff": "-1.7976931348623157e+308",
            "4340000000000000": "9007199254740992",
            "c340000000000000": "-9007199254740992",
            "4430000000000000": "295147905179352830000",
            "44b52d02c7e14af5": "9.999999999999997e+22",
            "44b52d02c7e14af6": "1e+23",
            "44b52d02c7e14af7": "1.0000000000000001e+23",
            "444b1ae4d6e2ef4e": "999999999999999700000",
            "444b1ae4d6e2ef4f": "999999999999999900000",
            "444b1ae4d6e2ef50": "1e+21",
            "3eb0c6f7a0b5ed8c": "9.999999999999997e-7",
            "3eb0c6f7a0b5ed8d": "0.000001",
            "41b3de4355555553": "333333333.3333332",
            "41b3de4355555554": "333333333.33333325",
            "41b3de4355555555": "333333333.3333333",
            "41b3de4355555556": "333333333.3333334",
            "41b3de4355555557": "333333333.33333343",
            "becbf647612f3696": "-0.0000033333333333333333",
            "43143ff3c1cb0959": "1424953923781206.2",
        }
        for bits, expected in vectors.items():
            with self.subTest(bits=bits):
                value = struct.unpack(">d", bytes.fromhex(bits))[0]
                self.assertEqual(contracts.canonical(value), expected)

    def test_projection_round_trips_semantic_records(self) -> None:
        value = {
            "goal": "Open browser",
            "capabilities": [self.capabilities()["client.widget.open"]],
            "state": {"id": "st:1", "rev": 1, "status": "acting", "known": ["ev:1"], "open": ["client_ack"], "plan": ["op.open"]},
            "evidence": [{"id": "ev:1", "kind": "client.status", "subject": "electron-a", "revision": "r1", "summary": "Live", "detail_ref": "ev:1:detail"}],
            "operations": [{"id": "op.open", "cap": "client.widget.open", "args": {"client": "electron-a", "widget": "browser"}, "after": [], "expect": {"opened": True}, "say": {"phase": "acting", "message": "I found the client. I’m opening its Browser widget now."}}],
            "receipts": [{"id": "rcpt:1", "op": "op.open", "ok": True, "state": "acknowledged", "observed": {"opened": True}, "proof": ["cmd:1"], "error": {}}],
            "missing": [], "ready": "answer",
        }
        decoded = projection.decode(projection.encode(value))
        self.assertEqual(decoded["goal"], value["goal"])
        self.assertEqual(decoded["operations"], value["operations"])
        self.assertEqual(decoded["receipts"], value["receipts"])
        self.assertEqual(decoded["ready"], "answer")

    def test_evidence_detail_is_pull_on_demand_and_revision_aware(self) -> None:
        store = evidence.EvidenceStore()
        item = store.put(kind="source.read", subject="repo:a.py", revision="git:1", summary="Owner read", detail={"content": "secret detail"}, proof=["sha:1"])
        self.assertNotIn("content", item)
        self.assertEqual(store.detail(item["detail_ref"]), {"content": "secret detail"})
        view = store.view(item["detail_ref"], pointer="/content", max_chars=6)
        self.assertEqual(view["content"], "secret")
        self.assertEqual(view["next_offset"], 6)
        self.assertTrue(view["truncated"])
        self.assertEqual(store.mark_stale(subject="repo:a.py", current_revision="git:2"), 1)
        self.assertTrue(store.get(item["id"])["stale"])

    def test_state_delta_is_source_bound_and_deterministic(self) -> None:
        current = state.initial("Fix widget")
        change = state.delta(current, add_known=["ev:1"], add_open=["test"], status="acting")
        first = state.apply(current, change)
        second = state.apply(current, change)
        self.assertEqual(first, second)
        with self.assertRaisesRegex(contracts.ContractError, "state_delta_source_mismatch"):
            state.apply(first, change)

    def test_dag_parallelizes_independent_domains_and_serializes_conflicts(self) -> None:
        capabilities = self.capabilities()
        operations = [
            {"id": "op.read", "cap": "repo.source.read", "args": {"path": "a.py"}},
            {"id": "op.client", "cap": "client.widget.open", "args": {"client": "electron-a"}},
            {"id": "op.patch1", "cap": "repo.patch.apply", "args": {"path": "a.py"}, "after": ["op.read"]},
            {"id": "op.patch2", "cap": "repo.patch.apply", "args": {"path": "a.py"}, "after": ["op.read"]},
            {"id": "op.test", "cap": "repo.test.run", "args": {}, "after": ["op.patch1", "op.patch2"]},
        ]
        scheduled = dag.waves(capabilities, operations)
        self.assertEqual({item["id"] for item in scheduled[0]}, {"op.read", "op.client"})
        self.assertEqual(len(scheduled[1]), 1)
        self.assertEqual(len(scheduled[2]), 1)
        self.assertEqual([item["id"] for item in scheduled[3]], ["op.test"])

    def test_failed_dependency_prevents_downstream_execution(self) -> None:
        capabilities = self.capabilities()
        operations = [
            {"id": "op.patch", "cap": "repo.patch.apply", "args": {"path": "a.py"}},
            {"id": "op.test", "cap": "repo.test.run", "args": {}, "after": ["op.patch"]},
        ]
        invoked = []

        def invoke(wave):
            invoked.extend(item["id"] for item in wave)
            return [{"id": "rcpt:patch", "op": "op.patch", "ok": False, "state": "failed", "error": {"code": "patch_failed"}}]

        receipts = dag.execute(capabilities, operations, invoke)
        self.assertEqual(invoked, ["op.patch"])
        self.assertEqual(receipts[-1]["error"]["code"], "dependency_failed")


if __name__ == "__main__":
    unittest.main()
