#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_ROOT))

from master_frontier import cyphers_v3  # noqa: E402


class MasterFrontierCyphersV3Tests(unittest.TestCase):
    def envelope(self) -> dict[str, object]:
        return {
            "schema": cyphers_v3.SCHEMA,
            "objective": "search the code base to understand what the meta-analysis widget does",
            "route_id": "wasm-agent.avatar-chat.ui",
            "surface": "avatar-chat",
            "route_contract": {
                "route_id": "wasm-agent.avatar-chat.ui",
                "surface": "avatar-chat",
                "workspace_root": "/local/plugins/wasm-agent",
            },
            "task_contract": {
                "budget": {
                    "provider_tokens_max": 8000,
                    "api_calls_max": 6,
                    "max_output_tokens": 8192,
                },
            },
            "compact_state": {
                "continuity": {
                    "handle": "ctx://avatar-chat/session/test",
                    "csc": "CSC/1 G:understand-widget Q:source",
                },
                "verbose_unused_state": "must-not-enter-bootstrap",
            },
        }

    def test_registry_keeps_semantic_operations_separate_from_internal_cyphers(self) -> None:
        registry = cyphers_v3.registry()

        self.assertEqual(registry["id"], "c3")
        self.assertEqual(registry["schema"], "hermes.wasm_agent.cyphers.v3")
        self.assertEqual(len(cyphers_v3.registry_digest()), 16)
        self.assertEqual(len(registry["tools"].values()), len(set(registry["tools"].values())))
        for operation, spec in registry["operations"].items():
            self.assertIn(spec["tool"], registry["tools"].values(), operation)
            self.assertIsInstance(spec["args"], dict)
            self.assertTrue(all(name and target for name, target in spec["args"].items()))

    def test_bootstrap_is_semantic_small_and_excludes_cypher_dictionary(self) -> None:
        prompt = cyphers_v3.bootstrap(self.envelope(), receiver="openai-codex")

        self.assertIn("I e:C3 g:", prompt)
        self.assertIn("search(query,limit) read(path,bytes,offset,length)", prompt)
        self.assertIn("@search query='term'", prompt)
        self.assertIn("C c:CSC/1 G:understand-widget", prompt)
        self.assertNotIn("D v:", prompt)
        self.assertNotIn("q=code.memory.search", prompt)
        self.assertNotIn("code.memory.search", prompt)
        self.assertNotIn("must-not-enter-bootstrap", prompt)
        self.assertLess(cyphers_v3.estimate_tokens(prompt), 300)

    def test_semantic_search_decodes_to_route_scoped_internal_tool(self) -> None:
        choice = cyphers_v3.decision(
            {"reply": "@search query='realure meta-analysis' limit=10"},
            route_id="wasm-agent.avatar-chat.ui",
        )

        self.assertEqual(choice["kind"], "tool")
        self.assertEqual(choice["action"]["operation"], "search")
        self.assertEqual(choice["action"]["action"], "code.memory.search")
        self.assertEqual(choice["action"]["cypher"], "q")
        self.assertEqual(choice["action"]["args"]["query"], "realure meta-analysis")
        self.assertEqual(choice["action"]["args"]["limit"], 10)
        self.assertEqual(choice["action"]["args"]["route_id"], "wasm-agent.avatar-chat.ui")

    def test_semantic_read_uses_human_argument_names(self) -> None:
        choice = cyphers_v3.decision(
            {"reply": "@read path='public/modules/meta-analysis/meta-analysis-widget.js' bytes=12000 offset=0"},
            route_id="wasm-agent.avatar-chat.ui",
        )

        self.assertEqual(choice["action"]["operation"], "read")
        self.assertEqual(choice["action"]["action"], "file.read_bounded")
        self.assertEqual(choice["action"]["args"]["max_bytes"], 12000)
        self.assertEqual(choice["action"]["args"]["offset"], 0)

    def test_semantic_edit_can_carry_structured_operations(self) -> None:
        choice = cyphers_v3.decision(
            {"reply": "@edit operations='[{\"op\":\"replace\",\"path\":\"x.js\",\"find\":\"a\",\"replace\":\"b\"}]' dry_run=true"},
            route_id="wasm-agent.avatar-chat.ui",
        )

        self.assertEqual(choice["action"]["operation"], "edit")
        self.assertEqual(choice["action"]["action"], "patch.apply_scoped")
        self.assertEqual(choice["action"]["args"]["operations"][0]["path"], "x.js")
        self.assertTrue(choice["action"]["args"]["dry_run"])

    def test_empty_parentheses_are_normalized_for_argumentless_operations(self) -> None:
        choice = cyphers_v3.decision(
            {"reply": "@cost()"},
            route_id="wasm-agent.avatar-chat.ui",
        )

        self.assertEqual(choice["kind"], "tool")
        self.assertEqual(choice["action"]["operation"], "cost")
        self.assertEqual(choice["action"]["action"], "cost.status")

    def test_files_operation_exposes_declared_route_paths(self) -> None:
        choice = cyphers_v3.decision(
            {"reply": "@files"},
            route_id="wasm-agent.avatar-chat.ui",
        )

        self.assertEqual(choice["kind"], "tool")
        self.assertEqual(choice["action"]["operation"], "files")
        self.assertEqual(choice["action"]["action"], "lookup.files")

    def test_resume_and_skill_operations_map_to_declared_generic_tools(self) -> None:
        resumed = cyphers_v3.decision(
            {"reply": "@resume run_id='wa_run_1' turn_id='turn_1'"},
            route_id="wasm-agent.avatar-chat.ui",
        )
        selected = cyphers_v3.decision(
            {"reply": "@skill node_id='paracelsus' skill_id='scientific-paper-meta-analysis'"},
            route_id="wasm-agent.avatar-chat.ui",
        )

        self.assertEqual(resumed["action"]["action"], "checkpoint.resume")
        self.assertEqual(resumed["action"]["args"]["run_id"], "wa_run_1")
        self.assertEqual(selected["action"]["action"], "skill.select")
        self.assertEqual(selected["action"]["args"]["skill_id"], "scientific-paper-meta-analysis")

    def test_compact_cypher_remains_decode_only_compatibility(self) -> None:
        choice = cyphers_v3.decision(
            {"reply": '{"c":"q","a":{"q":"meta-analysis","l":8}}'},
            route_id="wasm-agent.avatar-chat.ui",
        )

        self.assertEqual(choice["kind"], "tool")
        self.assertEqual(choice["action"]["operation"], "search")
        self.assertEqual(choice["action"]["args"]["query"], "meta-analysis")

    def test_unknown_semantic_operation_cannot_become_a_final_answer(self) -> None:
        choice = cyphers_v3.decision(
            {"reply": "@invent target='anything'"},
            route_id="wasm-agent.avatar-chat.ui",
        )

        self.assertEqual(choice["kind"], "invalid")
        self.assertEqual(choice["code"], "cypher_action_invalid")
        self.assertEqual(choice["answer"], "")

    def test_one_semantic_operation_after_prose_still_continues(self) -> None:
        choice = cyphers_v3.decision(
            {"reply": "I will inspect the source.\n\n@read path='widget.js' bytes=12000"},
            route_id="wasm-agent.avatar-chat.ui",
        )

        self.assertEqual(choice["kind"], "tool")
        self.assertEqual(choice["action"]["operation"], "read")

    def test_search_observation_is_semantic_but_receipt_stays_cyphered(self) -> None:
        observed = cyphers_v3.observation({
            "tool": "code.memory.search",
            "ok": True,
            "result": {
                "ok": True,
                "items": [{
                    "label": "File",
                    "file_path": "public/modules/meta-analysis/meta-analysis-widget.js",
                    "name": "meta-analysis-widget.js",
                }],
            },
        })
        history = cyphers_v3.history_item(
            {
                "operation": "search",
                "action": "code.memory.search",
                "cypher": "q",
                "args": {"query": "meta-analysis", "route_id": "wasm-agent.avatar-chat.ui"},
            },
            observed,
        )

        self.assertEqual(observed["line"].split(":", 1)[0], "q")
        self.assertEqual(observed["model_line"].split(" ", 1)[0], "search")
        self.assertIn("file path=public/modules/meta-analysis/meta-analysis-widget.js", observed["detail"])
        self.assertTrue(history["line"].startswith("q"))
        self.assertTrue(history["model_line"].startswith("search query=meta-analysis -> search ok"))

    def test_file_observation_is_bounded_for_synthesis(self) -> None:
        observed = cyphers_v3.observation({
            "tool": "file.read_bounded",
            "ok": True,
            "result": {"ok": True, "path": "widget.js", "text": "x" * 20000},
        })

        self.assertTrue(observed["satisfying"])
        self.assertEqual(observed["operation"], "read")
        self.assertLessEqual(len(observed["detail"]), cyphers_v3.registry()["limits"]["file_observation_chars"])

    def test_empty_proof_diff_and_stale_memory_are_not_satisfying(self) -> None:
        empty_proof = cyphers_v3.observation({
            "tool": "proof.collect",
            "ok": True,
            "result": {"ok": True, "runs": [], "events": [], "token_ledger": {}},
        })
        empty_diff = cyphers_v3.observation({
            "tool": "git.diff_summary",
            "ok": True,
            "result": {"ok": True, "changed_files": [], "count": 0},
        })
        stale = cyphers_v3.observation({
            "tool": "code.memory.search",
            "ok": False,
            "result": {"ok": False, "code": "code_memory_stale", "items": []},
        })

        self.assertFalse(empty_proof["satisfying"])
        self.assertEqual(empty_proof["status"], "e")
        self.assertFalse(empty_diff["satisfying"])
        self.assertEqual(empty_diff["status"], "e")
        self.assertFalse(stale["satisfying"])
        self.assertEqual(stale["status"], "m")
        self.assertEqual(stale["evidence_class"], "capability_unavailable")
        self.assertFalse(stale["conclusive"])

    def test_trusted_empty_lookup_is_conclusive_negative_evidence(self) -> None:
        observed = cyphers_v3.observation({
            "tool": "lookup.symbol",
            "ok": True,
            "result": {"ok": True, "code": "ok", "matches": []},
        })

        self.assertFalse(observed["satisfying"])
        self.assertTrue(observed["conclusive"])
        self.assertEqual(observed["evidence_class"], "not_found_trusted")

    def test_unsupported_kernel_inspect_is_capability_evidence_not_found(self) -> None:
        observed = cyphers_v3.observation({
            "tool": "kernel.inspect",
            "ok": True,
            "result": {
                "ok": True,
                "code": "ok",
                "observations": [],
                "unknowns": [{"kind": "widget", "code": "inspect_kind_unsupported"}],
            },
        })

        self.assertFalse(observed["satisfying"])
        self.assertEqual(observed["status"], "m")
        self.assertEqual(observed["evidence_class"], "capability_unavailable")
        self.assertEqual(observed["failure_code"], "inspect_kind_unsupported")
        self.assertFalse(observed["conclusive"])

    def test_stateless_continuation_retains_bounded_prior_evidence(self) -> None:
        envelope = cyphers_v3.with_history(self.envelope(), [
            {"model_line": "read path=one.js -> read ok n=10 h=one", "handle": "one", "detail": "source-one"},
            {"model_line": "read path=two.js -> read ok n=10 h=two", "handle": "two", "detail": "source-two"},
        ])

        prompt = cyphers_v3.bootstrap(envelope)

        self.assertIn("source-one", prompt)
        self.assertIn("source-two", prompt)
        self.assertIn("E h=one", prompt)
        self.assertIn("E h=two", prompt)

    def test_bootstrap_declares_finite_inspect_contract(self) -> None:
        prompt = cyphers_v3.bootstrap(self.envelope())

        self.assertIn("inspect kinds=route|files|symbols|proof|cost|transcript|diff|capabilities|runtime_entity", prompt)
        self.assertIn("source objects require search/symbol/read", prompt)

    def test_explicit_hard_budget_blocks_but_default_target_is_advisory(self) -> None:
        envelope = self.envelope()
        envelope["task_contract"]["budget"].update({"provider_tokens_max": 1000, "max_output_tokens": 600, "enforcement": "hard"})
        blocked = cyphers_v3.admission(envelope, [{"total_tokens": 800}], cyphers_v3.bootstrap(envelope), calls_used=1)
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["code"], "provider_token_budget_exhausted")

        envelope["task_contract"]["budget"].pop("enforcement")
        advisory = cyphers_v3.admission(envelope, [{"total_tokens": 900}], cyphers_v3.bootstrap(envelope), calls_used=1)
        self.assertTrue(advisory["ok"])
        self.assertTrue(advisory["over_target"])
        self.assertEqual(advisory["code"], "token_target_exceeded")

        source_envelope = self.envelope()
        source_envelope["objective_kind"] = "source-investigation"
        source_envelope["task_contract"]["budget"].update({"provider_tokens_max": 1000, "api_calls_max": 1})
        source_admission = cyphers_v3.admission(source_envelope, [], cyphers_v3.bootstrap(source_envelope), calls_used=1)
        self.assertTrue(source_admission["hard_tokens"])
        self.assertFalse(source_admission["ok"])

    def test_default_call_target_is_advisory_but_explicit_hard_target_blocks(self) -> None:
        envelope = self.envelope()
        envelope["task_contract"]["budget"].update({"provider_tokens_max": 100000, "api_calls_max": 1})

        advisory = cyphers_v3.admission(envelope, [], cyphers_v3.bootstrap(envelope), calls_used=1)
        self.assertTrue(advisory["ok"])
        self.assertTrue(advisory["calls_over_target"])
        self.assertEqual(advisory["code"], "call_target_exceeded")

        envelope["task_contract"]["budget"]["enforcement"] = "hard"
        blocked = cyphers_v3.admission(envelope, [], cyphers_v3.bootstrap(envelope), calls_used=1)
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["code"], "api_call_budget_exhausted")

    def test_v3_output_ceiling_is_independent_from_advisory_token_target(self) -> None:
        envelope = self.envelope()
        envelope["budget"] = {"max_output_tokens": 32768}
        envelope["task_contract"]["budget"]["head_tokens_max"] = 3000

        limits = cyphers_v3.budget_limits(envelope)

        self.assertEqual(limits["output"], 32768)
        self.assertEqual(limits["total"], 8000)

    def test_resume_checkpoint_preserves_bounded_replayable_evidence(self) -> None:
        checkpoint = cyphers_v3.resume_checkpoint(
            self.envelope(),
            [{
                "operation": "read",
                "status": "o",
                "satisfying": True,
                "handle": "abc123",
                "model_line": "read path=widget.js -> read ok",
                "detail": "bounded source evidence",
            }],
            code="api_call_safety_ceiling",
            calls_used=24,
        )

        self.assertEqual(checkpoint["schema"], "hermes.wasm_agent.checkpoint.v3")
        self.assertEqual(checkpoint["failure_code"], "api_call_safety_ceiling")
        self.assertEqual(checkpoint["provider_calls_used"], 24)
        self.assertEqual(checkpoint["evidence"][0]["handle"], "abc123")
        self.assertIn("bounded source evidence", checkpoint["evidence"][0]["detail"])


if __name__ == "__main__":
    unittest.main()
