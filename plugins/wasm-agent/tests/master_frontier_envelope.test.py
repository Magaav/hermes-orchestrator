#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PLUGIN_ROOT / "server"
ENVELOPE_PATH = PLUGIN_ROOT / "server" / "master_frontier" / "envelope.py"
STATIC_SERVER_PATH = PLUGIN_ROOT / "server" / "static_server.py"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

spec = importlib.util.spec_from_file_location("master_frontier.envelope", ENVELOPE_PATH)
assert spec and spec.loader
envelope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(envelope)


class MasterFrontierEnvelopeTests(unittest.TestCase):
    def test_task_contract_is_a_declared_direct_envelope_field(self) -> None:
        self.assertIn("task_contract", envelope.ALLOWED_KEYS)

    def test_capped_action_json_requires_structured_action_repair(self) -> None:
        capped_action_reply = (
            '{"answer":"Reading exact turn 6 content before self-criticism.",'
            '"decision":"transcript.read for turns 5-6 before answering",'
            '"actions":[{"action"'
        )

        self.assertTrue(envelope.requires_structured_action({}, capped_action_reply))

    def test_complete_answer_json_does_not_require_repair(self) -> None:
        parsed = {
            "answer": "I can answer from provided context.",
            "decision": "answer",
            "actions": [],
        }

        self.assertFalse(envelope.requires_structured_action(parsed, json.dumps(parsed)))

    def test_bare_inspection_decision_requires_executable_action(self) -> None:
        parsed = {
            "answer": "Let me inspect the repo root to verify codebase access before confirming.",
            "decision": "inspect_repo_root_then_answer",
            "actions": [],
        }

        self.assertTrue(envelope.requires_structured_action(parsed, json.dumps(parsed)))

    def test_kernel_action_decision_requires_executable_action(self) -> None:
        parsed = {
            "answer": "Not inspected yet - I need to search the wasm-agent repo first.",
            "decision": "Route to kernel.inspect on the owned repo to find space widget components.",
            "actions": [],
        }

        self.assertTrue(envelope.requires_structured_action(parsed, json.dumps(parsed)))

    def test_future_inspection_prose_requires_executable_action(self) -> None:
        reply = (
            "I have a declared repo root at /local/plugins/wasm-agent and repo.read "
            "capability, but I haven't verified its contents yet. Let me inspect it now."
        )

        self.assertTrue(envelope.requires_structured_action(None, reply))

    def test_conversation_objective_salvages_unexecuted_action_claim(self) -> None:
        parsed = {
            "answer": (
                "Here is my critique. I'm dispatching to Hermes now. "
                "The envelope is strongest when it keeps route, proof, and objective kind explicit."
            ),
            "decision": "answer",
            "actions": [],
        }

        salvaged = envelope.salvage_conversation_answer(
            {"objective_kind": "conversation"},
            parsed,
            parsed["answer"],
        )

        self.assertIn("Here is my critique", salvaged)
        self.assertIn("objective kind explicit", salvaged)
        self.assertNotIn("dispatching to Hermes", salvaged)

    def test_implementation_objective_does_not_salvage_unexecuted_action_claim(self) -> None:
        reply = "I'm dispatching to Hermes now. The implementation needs proof."

        self.assertEqual(
            envelope.salvage_conversation_answer({"objective_kind": "implementation"}, {}, reply),
            "",
        )
        self.assertTrue(envelope.requires_structured_action({}, reply))

    def test_conceptual_floor_downgrades_stray_inspection_decision(self) -> None:
        parsed = {
            "answer": "Honest critique from inside. Let me inspect the runtime first.",
            "decision": "local_runtime_route_inspection",
            "actions": [],
            "state_delta": {},
            "needs": [],
            "confidence": 0.8,
        }

        downgraded = envelope.downgraded_conceptual_answer(
            {"task_contract": {"evidence_floor": "conceptual"}},
            parsed,
            parsed["answer"],
        )

        self.assertIsNotNone(downgraded)
        assert downgraded is not None
        self.assertEqual(downgraded["decision"], "answer")
        self.assertEqual(downgraded["actions"], [])
        self.assertEqual(downgraded["downgraded_from"], "local_runtime_route_inspection")
        self.assertNotIn("inspect the runtime", downgraded["answer"])

    def test_conceptual_floor_normalizes_plain_text_answer_without_json(self) -> None:
        reply = "Plain text answer - I'll be honest about what this envelope actually does to me."

        downgraded = envelope.downgraded_conceptual_answer(
            {"task_contract": {"evidence_floor": "conceptual"}},
            {},
            reply,
        )

        self.assertIsNotNone(downgraded)
        assert downgraded is not None
        self.assertEqual(downgraded["decision"], "answer")
        self.assertEqual(downgraded["actions"], [])
        self.assertIn("Plain text answer", downgraded["answer"])

    def test_repo_object_missing_context_claim_requires_bounded_lookup_action(self) -> None:
        reply = (
            "I'd be happy to critique the meta-analysis widget, but I don't actually "
            "have it. Could you paste the widget code?"
        )

        self.assertTrue(envelope.requires_structured_action(None, reply))

    def test_continued_answer_after_tool_evidence_salvages_future_offer(self) -> None:
        reply = (
            "Yes, I can acknowledge the avatar-chat UI context. The route is "
            "`wasm-agent.avatar-chat.ui`, and the visible protocol widgets include "
            "continuity, transcript, route, and token-budget surfaces. I will inspect "
            "the actual UI code next for widget details."
        )

        salvaged = envelope.salvage_continued_answer_after_tool_evidence({}, reply)

        self.assertIn("avatar-chat UI context", salvaged)
        self.assertIn("recorded local tool evidence", salvaged)
        self.assertNotIn("dispatch that", salvaged)

    def test_continued_answer_salvage_does_not_mask_action_json(self) -> None:
        reply = '{"decision":"dispatch.hermes","actions":[{"action"'

        self.assertEqual(envelope.salvage_continued_answer_after_tool_evidence({}, reply), "")

    def test_repair_body_is_owned_by_master_frontier_contract(self) -> None:
        body = {"instructions": "Use the envelope.", "max_output_tokens": 128}
        repaired = envelope.action_repair_body(body, '{"decision":"dispatch.hermes"')

        self.assertIn("STRICT ACTION REPAIR", repaired["instructions"])
        self.assertGreaterEqual(repaired["max_output_tokens"], 1200)
        self.assertEqual(body["max_output_tokens"], 128)

    def test_semantic_text_splits_rules_from_proof_handles(self) -> None:
        semantic = envelope.semantic_text({
            "objective": "Critique your own envelope from within.",
            "objective_kind": "conversation",
            "route_id": "wasm-agent.avatar-chat.ui",
            "surface": "avatar-chat",
            "constraints": [
                "Do not assume hidden state beyond this envelope.",
                "When continuation_context is present and the user asks to continue or resume, continue that objective instead of asking the user to restate it.",
                "Answer directly when possible; use dispatch.hermes only when tool, file, runtime, or proof work is required.",
                "Use node.capabilities before assuming a named Hermes node can or cannot answer; use node.chat for bounded node-brain delegation when available.",
                "When tool work is required, output only compact JSON with executable actions as the first response bytes; no prose or markdown before action JSON.",
                "Use CSC/1 continuity first; request transcript.read only when exact previous-message content changes the answer.",
                "Keep the answer compact and include proof handles when work is dispatched.",
                "Do not report token usage in the answer text; the UI renders exact provider token usage from diagnostics.",
                "Do not claim inspected, confirmed, verified, or viable unless the claim is supported by envelope evidence or dispatched proof; otherwise say not inspected yet.",
            ],
            "proof_requests": [
                "route-used:/agent/provider/envelope/stream",
                "receiver:server-configured",
                "target-label:Master:frontier",
                "target-node:frontier",
            ],
            "budget": {"max_output_tokens": 1800},
            "stream": True,
        })

        self.assertIn("\nRULES ", semantic)
        self.assertIn("\nPROOF ", semantic)
        self.assertIn("\nEVID ", semantic)
        self.assertIn("\nOBJ_KIND conversation", semantic)
        self.assertIn("Do not claim inspected", semantic)
        proof_line = next(line for line in semantic.splitlines() if line.startswith("PROOF "))
        self.assertIn("route-used:/agent/provider/envelope/stream", proof_line)
        self.assertIn("target-node:frontier", proof_line)
        self.assertNotIn("Do not assume hidden state", proof_line)
        self.assertNotIn("[clipped]", proof_line)

    def test_semantic_text_projects_depth_evidence_and_recall_handles(self) -> None:
        semantic = envelope.semantic_text({
            "objective": "Critique your own envelope from within.",
            "route_id": "wasm-agent.avatar-chat.ui",
            "route_contract": {"workspace_root": "/local/plugins/wasm-agent"},
            "caps_verified": ["repo.read", "proof.report"],
            "compact_state": {
                "affect": "focused",
                "state_mode": "exploring",
                "coverage": {"level": "thin", "gaps": ["prior_decision"]},
                "anchors": [
                    {"i": 3, "kind": "decision", "anchor": "auth-proof"},
                    "turn7:preference:brevity",
                ],
                "continuity": {
                    "handle": "ctx://avatar-chat/session/agent_test",
                    "csc": "CSC/1 legend: G=goal R=recall",
                }
            },
            "allowed_actions": [{"id": "answer"}, {"id": "transcript.read"}, {"id": "memory.search"}],
            "task_contract": {
                "intent": "answer",
                "executor": "provider_head",
                "evidence_floor": "conceptual",
                "route_intent": "conceptual",
                "depth": {"level": "free", "budget_hint": "open"},
                "recall_budget": {"mode": "reflective", "transcript_turns": 10},
                "tools_first": ["kernel.resolve"],
                "proof_required": ["route", "evidence", "answer"],
                "hermes": "subagent_harness_only",
            },
            "last_feedback": {"status": "corrected", "last_action": "answer", "reply_sha16": "abc123"},
            "transcript_cache": {
                "turns": [
                    {"i": 1, "role": "user", "content": "Earlier I said quality comes before token saving."},
                    {"i": 2, "role": "assistant", "content": "I agreed and kept the contracts lean."},
                ],
            },
        })

        plan_line = next(line for line in semantic.splitlines() if line.startswith("PLAN "))
        reflect_line = next(line for line in semantic.splitlines() if line.startswith("REFLECT "))
        feedback_line = next(line for line in semantic.splitlines() if line.startswith("LAST_FEEDBACK "))
        recent_line = next(line for line in semantic.splitlines() if line.startswith("RECENT "))
        affect_line = next(line for line in semantic.splitlines() if line.startswith("A "))
        state_mode_line = next(line for line in semantic.splitlines() if line.startswith("STATE_MODE "))
        caps_verified_line = next(line for line in semantic.splitlines() if line.startswith("CAPS_VERIFIED "))
        evid_line = next(line for line in semantic.splitlines() if line.startswith("EVID "))
        anchors_line = next(line for line in semantic.splitlines() if line.startswith("ANCHORS "))
        self.assertIn('"d":{"level":"free","budget_hint":"open"}', plan_line)
        self.assertIn('"rb":{"mode":"reflective","transcript_turns":10}', plan_line)
        self.assertIn('"r":"conceptual"', plan_line)
        self.assertIn("allowed_labeled_self_model_not_proof", reflect_line)
        self.assertIn('"status":"corrected"', feedback_line)
        self.assertIn('"mode":"session_local_reflective"', recent_line)
        self.assertIn("quality comes before token saving", recent_line)
        self.assertIn('"persistent":false', recent_line)
        self.assertEqual(affect_line, "A focused")
        self.assertEqual(state_mode_line, "STATE_MODE exploring")
        self.assertIn("repo.read", caps_verified_line)
        self.assertIn("proof.report", caps_verified_line)
        self.assertNotIn("cost_trend", semantic)
        self.assertNotIn("tokens_last_turn", semantic)
        self.assertIn('"f":"conceptual"', envelope.semantic_text({
            "task_contract": {"intent": "answer", "executor": "provider_head", "evidence_floor": "conceptual"}
        }))
        self.assertIn('"route":"declared"', evid_line)
        self.assertIn('"route_contract":"attached"', evid_line)
        self.assertIn('"coverage":"thin"', evid_line)
        self.assertIn('3:decision:auth-proof', anchors_line)
        self.assertIn('turn7:preference:brevity', anchors_line)
        self.assertIn('"state":"ambiguous"', evid_line)
        self.assertIn('"pull":"transcript.read"', evid_line)
        self.assertIn('"recall_tools":["transcript.read","memory.search"]', evid_line)
        self.assertNotIn("model_caps", semantic)

    def test_recent_transcript_projection_stays_out_of_normal_turns(self) -> None:
        semantic = envelope.semantic_text({
            "objective": "Answer normally.",
            "task_contract": {
                "intent": "answer",
                "executor": "provider_head",
                "evidence_floor": "route",
                "recall_budget": {"mode": "on_demand", "transcript_turns": 6},
            },
            "transcript_cache": {
                "turns": [{"i": 1, "role": "user", "content": "Do not inject this into normal turns."}],
            },
        })

        self.assertNotIn("\nRECENT ", semantic)

    def test_self_check_flags_unbacked_verified_claims(self) -> None:
        check = envelope.self_check_projection(
            {},
            {"answer": "I verified the runtime state.", "decision": "answer", "actions": []},
            "",
        )

        self.assertFalse(check["claims_verified"])
        self.assertTrue(check["proof_overclaim"])
        self.assertFalse(check["actions_claimed"])

    def test_state_writeback_projects_delta_feedback_and_last_action(self) -> None:
        writeback = envelope.state_writeback_projection(
            {"coverage": "thin", "state_mode": "exploring"},
            {
                "answer": "Done.",
                "decision": "answer",
                "actions": [],
                "state_delta": {"decision": "keep conceptual floor"},
                "state_feedback": {
                    "coverage": "thin",
                    "state_mode": "converging",
                    "suggested_anchor": "turn3:decision:floor",
                },
                "model_reflection": {
                    "kind": "self_model",
                    "claim_status": "metaphor_not_proof",
                },
            },
            "Done.",
        )

        self.assertEqual(writeback["schema"], "hermes.wasm_agent.state_writeback.v1")
        self.assertEqual(writeback["last_action"], "answer")
        self.assertEqual(writeback["last_feedback"], "accepted")
        self.assertEqual(writeback["state_delta"]["decision"], "keep conceptual floor")
        self.assertEqual(writeback["model_reflection"]["claim_status"], "metaphor_not_proof")
        self.assertEqual(writeback["next"]["state_mode"], "converging")
        self.assertEqual(writeback["next"]["suggested_anchor"], "turn3:decision:floor")

    def test_duplicate_answer_blocks_are_suppressed(self) -> None:
        reply = (
            "What I actually am\n\n"
            "I am a stateless function reconstructed every turn.\n\n"
            "Where I am weak\n\n"
            "Give me evidence floors.\n\n"
            "Here is the honest critique from inside the envelope\n\n"
            "I am a stateless function reconstructed every turn.\n\n"
            "Where I am weak\n\n"
            "Give me evidence floors."
        )

        deduped = envelope.suppress_duplicate_answer_blocks(reply)

        self.assertTrue(deduped.startswith("Here is the honest critique"))
        self.assertEqual(deduped.count("I am a stateless function"), 1)

    def test_static_server_does_not_own_envelope_repair_policy(self) -> None:
        source = STATIC_SERVER_PATH.read_text(encoding="utf-8")

        self.assertIn("master_frontier_envelope.action_repair_body", source)
        self.assertIn("master_frontier_envelope.requires_structured_action", source)
        self.assertNotIn("STRICT ACTION REPAIR: your previous response", source)
        self.assertNotIn("DIRECT_HEAD_TOOL_INTENT_RE = re.compile", source)
        self.assertNotIn("DIRECT_HEAD_EXECUTIVE_INTENT_RE = re.compile", source)
        self.assertNotIn("def direct_head_reply_looks_like_action_json(reply: str) -> bool:\n    text =", source)


if __name__ == "__main__":
    unittest.main()
