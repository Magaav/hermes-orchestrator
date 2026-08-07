from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from master_frontier import capability_foundry  # noqa: E402


class CapabilityFoundryTests(unittest.TestCase):
    def test_source_registry_projects_only_verified_production_capabilities(self) -> None:
        registry = capability_foundry.load()
        self.assertEqual(len(registry["capabilities"]), 7)
        qa = next(record for record in registry["capabilities"] if record["id"] == "asolaria.qa.binary.evaluate")
        self.assertEqual(qa["state"], "rejected")
        self.assertIn("holdout-no-added-value", qa["blockers"])
        teacher = next(record for record in registry["capabilities"] if record["id"] == "image.teacher_edit")
        self.assertEqual(teacher["state"], "candidate")
        self.assertNotIn("supervised-teacher-adapter", teacher["blockers"])
        self.assertIn("gpu-student-training-worker", teacher["blockers"])
        routes = json.loads((ROOT / "server" / "agent_route_contracts.json").read_text())["routes"]
        declared = {str(item.get("route_id") or "") for item in routes}
        self.assertEqual(capability_foundry.undeclared_routes(registry, declared), [])
        projection = capability_foundry.project(
            registry,
            route_id="wasm-agent.agent-run.timeline",
            available_caps=["proof.report"],
        )
        self.assertEqual(projection["count"], 2)
        self.assertEqual(projection["blocked"], 5)
        self.assertEqual(
            {item["id"] for item in projection["capabilities"]},
            {"master_frontier.event_integrity.verify", "master_frontier.event_anchor.append"},
        )

    def test_only_verified_unblocked_route_authorized_capability_projects(self) -> None:
        registry = capability_foundry.load()
        promoted = copy.deepcopy(next(
            record for record in registry["capabilities"]
            if record["id"] == "master_frontier.event_integrity.verify"
        ))
        promoted.update({"state": "promoted", "claim_status": "verified", "blockers": []})
        decision = capability_foundry.evaluate(
            promoted,
            route_id="wasm-agent.agent-run.timeline",
            available_caps=["proof.report"],
        )
        self.assertTrue(decision["eligible"])
        self.assertFalse(capability_foundry.evaluate(
            promoted,
            route_id="wrong.route",
            available_caps=["proof.report"],
        )["eligible"])
        self.assertFalse(capability_foundry.evaluate(
            promoted,
            route_id="wasm-agent.agent-run.timeline",
            available_caps=[],
        )["eligible"])

    def test_duplicate_and_invalid_registry_fail_closed(self) -> None:
        source = json.loads(capability_foundry.default_registry_path().read_text())
        source["capabilities"].append(copy.deepcopy(source["capabilities"][0]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps(source))
            with self.assertRaises(capability_foundry.CapabilityFoundryError) as raised:
                capability_foundry.load(path)
        self.assertEqual(raised.exception.code, "capability_registry_duplicate")

    def test_projection_is_compact_and_contains_no_evidence_detail(self) -> None:
        registry = capability_foundry.load()
        for record in registry["capabilities"]:
            record.update({"state": "promoted", "claim_status": "verified", "blockers": []})
            record["required_caps"] = []
            record["routes"] = ["route"]
        projection = capability_foundry.project(registry, route_id="route")
        encoded = json.dumps(projection, separators=(",", ":"))
        self.assertLess(len(encoded), 1400)
        self.assertNotIn("verifier", encoded)
        self.assertNotIn("invalidated_by", encoded)


if __name__ == "__main__":
    unittest.main()
