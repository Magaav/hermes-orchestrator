#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import contracts, controller, execution_profiles, kernel, tool_compat, trajectory  # noqa: E402


def tool(name, arguments):
    return {"reply": "", "tool_calls": [{"id": "call-1", "name": name, "arguments": arguments}], "usage": {"input_tokens": 1, "output_tokens": 1}}


class V6TrajectoryTests(unittest.TestCase):
    def test_append_verify_replay_and_context_reconstruction(self) -> None:
        value = trajectory.create(run_id="run-1", route_id="route-1")
        messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "goal"}]
        tools = [{"type": "function", "function": {"name": "discover", "parameters": {"type": "object"}}}]
        trajectory.append(value, kind="run.started", source="host", payload={"profile": "semantic"})
        trajectory.append(value, kind="context.projected", source="v6.context", payload=trajectory.context_payload(messages, tools, decision=1, profile="semantic"))
        trajectory.append(value, kind="decision.completed", source="v6.controller", payload={"decision": 1, "tool": "discover"})
        verified = trajectory.verify(value)
        replayed = trajectory.replay(value)
        self.assertEqual(verified["count"], 3)
        self.assertEqual(replayed["contexts"][0]["messages"], messages)
        self.assertEqual(replayed["contexts"][0]["tool_contracts"], tools)
        self.assertEqual(replayed["decisions"][0]["tool"], "discover")

    def test_tamper_deletion_and_reordering_fail_closed(self) -> None:
        value = trajectory.create(run_id="run-1", route_id="route-1")
        for index in range(3):
            trajectory.append(value, kind="decision.completed", source="test", payload={"index": index})
        cases = []
        tampered = copy.deepcopy(value)
        tampered["events"][1]["payload"]["index"] = 99
        cases.append(tampered)
        deleted = copy.deepcopy(value)
        del deleted["events"][1]
        deleted["count"] = 2
        cases.append(deleted)
        reordered = copy.deepcopy(value)
        reordered["events"][0], reordered["events"][1] = reordered["events"][1], reordered["events"][0]
        cases.append(reordered)
        for candidate in cases:
            with self.subTest():
                with self.assertRaises(trajectory.TrajectoryError):
                    trajectory.verify(candidate)

    def test_fork_lineage_binds_parent_head(self) -> None:
        parent = trajectory.create(run_id="parent", route_id="route-1")
        trajectory.append(parent, kind="run.completed", source="host", payload={"ok": True})
        child = trajectory.create(run_id="child", route_id="route-1", parent=parent)
        self.assertEqual(child["parent"], {"run_id": "parent", "head": parent["head"], "count": 1})

    def test_profiles_are_route_owned_and_fail_closed(self) -> None:
        self.assertEqual(execution_profiles.resolve({})["id"], "semantic")
        minimal = execution_profiles.resolve({"task_contract": {"execution_profile": "minimal"}})
        self.assertEqual((minimal["max_decisions"], minimal["history_turns"]), (12, 0))
        with self.assertRaisesRegex(execution_profiles.ProfileError, "v6_execution_profile_invalid"):
            execution_profiles.resolve({"execution_profile": "unknown"})

    def test_legacy_tool_arguments_normalize_without_ambiguity(self) -> None:
        self.assertEqual(tool_compat.normalize("discover", {"search": "repo", "max_results": 3}), {"query": "repo", "limit": 3})
        self.assertEqual(tool_compat.normalize("execute", {"ops": []}), {"operations": []})
        with self.assertRaisesRegex(contracts.ContractError, "tool_argument_alias_conflict"):
            tool_compat.normalize("discover", {"search": "a", "query": "b"})

    def test_controller_emits_reconstructable_context_and_structured_recoverable_error(self) -> None:
        agent = kernel.Kernel(authorities=set())
        events = []
        decisions = [tool("discover", {"search": "nothing"}), {"reply": "No matching capability is available."}]
        result = controller.run("Inspect", agent, lambda *_args: decisions.pop(0), emit=events.append, execution_profile="minimal")
        context_event = next(item for item in events if item["type"] == "trajectory.context")
        decision_event = next(item for item in events if item["type"] == "decision.completed")
        self.assertEqual(context_event["profile"], "minimal")
        self.assertEqual(context_event["messages"][1]["role"], "user")
        self.assertEqual(decision_event["error"], {"code": "capability_match", "recoverable": True})
        self.assertEqual(result["answer"], "No matching capability is available.")


if __name__ == "__main__":
    unittest.main()
