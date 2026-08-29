#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
INTENT_PATH = PLUGIN_ROOT / "server" / "master_frontier" / "intent.py"

spec = importlib.util.spec_from_file_location("wasm_agent_master_frontier_intent", INTENT_PATH)
assert spec and spec.loader
intent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intent)


class MasterFrontierIntentTests(unittest.TestCase):
    def envelope(self, objective: str) -> dict:
        return {
            "objective": objective,
            "surface": "avatar-chat",
            "route_id": "wasm-agent.avatar-chat.ui",
            "capabilities": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
        }

    def test_widget_availability_question_is_capability_inquiry(self) -> None:
        envelope = self.envelope("Amazing. I would like to check the availability for you to make widgets in the realure space")

        self.assertTrue(intent.text_is_capability_inquiry(envelope["objective"]))
        self.assertFalse(intent.objective_is_implementation_intent(envelope))
        self.assertFalse(intent.goal_requires_change_artifact(envelope))

    def test_greeting_prefixed_space_open_is_declared_client_action(self) -> None:
        envelope = self.envelope("hello open realure space")
        envelope["route_contract"] = {"client_ui": {"operations": ["space_open"]}}

        self.assertTrue(intent.objective_is_declared_client_action(envelope))

    def test_browser_widget_state_question_is_declared_client_observation(self) -> None:
        envelope = self.envelope("hello is browser widget opened?")
        envelope["route_contract"] = {"client_ui": {"operations": ["browser_inspect"]}}

        self.assertTrue(intent.objective_is_declared_client_action(envelope))
        self.assertTrue(intent.objective_is_declared_client_state_query(envelope))

    def test_negated_browser_actions_do_not_grant_mutation_intent(self) -> None:
        envelope = self.envelope(
            "Inspect the current browser runtime. Do not navigate, click, type, or modify anything."
        )
        envelope["route_contract"] = {"client_ui": {"operations": ["windows_browser_cdp_runtime_inspect"]}}

        self.assertFalse(intent.objective_is_declared_client_action(envelope))

    def test_explicit_widget_build_request_requires_change_artifact(self) -> None:
        envelope = self.envelope("Go ahead and build the widget in the Realure space")

        self.assertFalse(intent.text_is_capability_inquiry(envelope["objective"]))
        self.assertTrue(intent.objective_is_implementation_intent(envelope))
        self.assertTrue(intent.goal_requires_change_artifact(envelope))

    def test_codebase_understanding_is_not_implementation(self) -> None:
        envelope = self.envelope("Search the code base to understand what the meta-analysis widget does")

        self.assertFalse(intent.objective_is_implementation_intent(envelope))
        self.assertFalse(intent.goal_requires_change_artifact(envelope))

    def test_possibility_to_ship_is_capability_inquiry(self) -> None:
        envelope = self.envelope("check out the possibility to ship widgets to the spaces")

        self.assertTrue(intent.text_is_capability_inquiry(envelope["objective"]))
        self.assertFalse(intent.objective_is_implementation_intent(envelope))
        self.assertFalse(intent.goal_requires_change_artifact(envelope))

    def test_self_capability_location_probe_is_not_implementation(self) -> None:
        envelope = self.envelope(
            "hello i am going to test your power\n"
            "check what you can do for us and your conecientness build up\n"
            "so, where are you?"
        )

        self.assertTrue(intent.text_is_capability_inquiry(envelope["objective"]))
        self.assertFalse(intent.objective_is_implementation_intent(envelope))
        self.assertFalse(intent.goal_requires_change_artifact(envelope))

    def test_continuation_with_prior_widget_goal_requires_change_artifact(self) -> None:
        envelope = self.envelope("Continue")
        envelope["compact_state"] = {
            "continuity": {
                "csc": "Previous goal: implement the shared-space widget for the Paracelsus meta-analysis workflow.",
            },
        }

        self.assertTrue(intent.goal_requires_change_artifact(envelope))

    def test_changed_file_artifacts_accept_bridge_trace(self) -> None:
        artifacts = intent.changed_file_artifacts(
            {"changed_files": []},
            {"bridge_trace": {"changed_files": ["public/app.js"]}},
        )

        self.assertEqual(artifacts, ["public/app.js"])

    def test_fresh_live_page_observation_requires_runtime_evidence(self) -> None:
        envelope = self.envelope(
            "Take a fresh look at this page and tell me whether the assistant is open."
        )

        self.assertTrue(intent.objective_requires_runtime_evidence(envelope))

    def test_source_file_look_does_not_require_runtime_evidence(self) -> None:
        envelope = self.envelope("Take a fresh look at this source file and explain it.")

        self.assertFalse(intent.objective_requires_runtime_evidence(envelope))


if __name__ == "__main__":
    unittest.main()
