#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import runtime_snapshot


def sample() -> dict:
    return {
        "entity": {"route_id": "hermes-node.fixture.runtime", "id": "fixture", "kind": "hermes-node"},
        "status": "available",
        "freshness": {"state": "fresh", "observed_at": "2026-07-13T19:00:00Z", "age_ms": 1200, "max_age_ms": 5000, "trusted": True},
        "capabilities": {"runtime.inspect": True, "timeline.read": "bounded"},
        "counters": {"runs": 3, "events": 18},
        "proof_refs": [{"id": "proof-1", "kind": "runtime_snapshot", "digest": "sha256:" + "a" * 64, "lookup": "runtime.proof.get:proof-1"}],
        "unknowns": [],
        "redaction": {"applied": True, "class": "runtime-public-v1"},
    }


class RuntimeSnapshotTests(unittest.TestCase):
    def test_normalizes_bounded_snapshot_and_compact_projection(self) -> None:
        result = runtime_snapshot.normalize(sample())
        self.assertEqual(result["schema"], runtime_snapshot.SCHEMA)
        self.assertTrue(result["freshness"]["trusted"])
        self.assertEqual(len(result["snapshot_digest"]), 64)
        projection = runtime_snapshot.model_projection(result)
        self.assertEqual(projection["s"], "available")
        self.assertEqual(projection["p"], [{"id": "proof-1", "kind": "runtime_snapshot"}])
        self.assertLess(len(json.dumps(projection)), runtime_snapshot.MAX_BYTES)

    def test_stale_snapshot_cannot_be_trusted(self) -> None:
        value = sample(); value["freshness"].update({"state": "stale", "age_ms": 6000})
        self.assertFalse(runtime_snapshot.normalize(value)["freshness"]["trusted"])

    def test_requires_redaction_and_bounded_refs(self) -> None:
        value = sample(); value["redaction"]["applied"] = False
        with self.assertRaisesRegex(runtime_snapshot.SnapshotError, "redaction_required"):
            runtime_snapshot.normalize(value)
        value = sample(); value["proof_refs"] *= runtime_snapshot.MAX_PROOF_REFS + 1
        with self.assertRaisesRegex(runtime_snapshot.SnapshotError, "proof_refs_invalid"):
            runtime_snapshot.normalize(value)

    def test_proof_refs_cannot_embed_paths_or_unbound_digests(self) -> None:
        value = sample(); value["proof_refs"][0]["lookup"] = "/host/runtime/proof-1"
        with self.assertRaisesRegex(runtime_snapshot.SnapshotError, "proof_ref_lookup_invalid"):
            runtime_snapshot.normalize(value)
        value = sample(); value["proof_refs"][0]["digest"] = "sha256:abc"
        with self.assertRaisesRegex(runtime_snapshot.SnapshotError, "proof_ref_digest_invalid"):
            runtime_snapshot.normalize(value)

    def test_contract_forbids_control_and_opaque_payloads(self) -> None:
        declared = runtime_snapshot.contract()
        self.assertEqual(declared["authority"], "read_only_snapshot")
        self.assertIn("control_actions", declared["forbidden"])
        self.assertIn("base64", declared["forbidden"])


if __name__ == "__main__":
    unittest.main()
