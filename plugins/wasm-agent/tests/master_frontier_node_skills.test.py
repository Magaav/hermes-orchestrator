#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


SERVER_ROOT = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_ROOT))

from master_frontier import node_skills  # noqa: E402


class MasterFrontierNodeSkillsTests(unittest.TestCase):
    def test_manifest_finds_exact_nested_skill(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            skill_dir = root / "custom" / "scientific-paper-meta-analysis"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: scientific-paper-meta-analysis\ndescription: Research.\nmetadata:\n  hermes:\n    version: 1.1.0\n---\n",
                encoding="utf-8",
            )

            manifest = node_skills.skill_manifest("scientific-paper-meta-analysis", skills_root=root)

        self.assertTrue(manifest["available"])
        self.assertEqual(manifest["version"], "1.1.0")
        self.assertEqual(len(manifest["sha256"]), 16)

    def test_receipt_requires_a_skill_view_tool_call(self) -> None:
        skill = {"id": "scientific-paper-meta-analysis", "available": True}
        trace = {
            "finish_reason": "completed",
            "tool_calls": [
                {
                    "name": "skill_view",
                    "arguments": '{"name":"scientific-paper-meta-analysis"}',
                    "status": "done",
                }
            ]
        }

        receipt = node_skills.skill_receipt(skill, trace)

        self.assertTrue(receipt["requested"])
        self.assertTrue(receipt["available"])
        self.assertTrue(receipt["loaded"])
        self.assertTrue(receipt["successfully_used"])
        self.assertTrue(receipt["tool_seen"])
        self.assertTrue(receipt["argument_matched"])
        self.assertTrue(receipt["used"])

    def test_bare_matching_skill_view_only_proves_loaded(self) -> None:
        skill = {"id": "scientific-paper-meta-analysis", "available": True}
        trace = {
            "finish_reason": "completed",
            "tool_calls": [
                {
                    "name": "skill_view",
                    "arguments": '{"name":"scientific-paper-meta-analysis"}',
                }
            ]
        }

        receipt = node_skills.skill_receipt(skill, trace)

        self.assertTrue(receipt["loaded"])
        self.assertFalse(receipt["successfully_used"])
        self.assertFalse(receipt["used"])

    def test_receipt_rejects_an_unrelated_sole_skill_view(self) -> None:
        skill = {"id": "scientific-paper-meta-analysis", "available": True}
        trace = {
            "tool_calls": [
                {
                    "name": "skill_view",
                    "arguments": '{"name":"unrelated-skill"}',
                    "status": "done",
                }
            ]
        }

        receipt = node_skills.skill_receipt(skill, trace)

        self.assertTrue(receipt["requested"])
        self.assertTrue(receipt["available"])
        self.assertTrue(receipt["tool_seen"])
        self.assertFalse(receipt["argument_matched"])
        self.assertFalse(receipt["loaded"])
        self.assertFalse(receipt["successfully_used"])
        self.assertFalse(receipt["used"])

    def test_receipt_requires_an_exact_skill_view_name(self) -> None:
        skill = {"id": "paper-analysis", "available": True}
        trace = {
            "tool_calls": [
                {
                    "name": "skill_view",
                    "arguments": '{"name":"paper-analysis-extended"}',
                    "status": "done",
                }
            ]
        }

        receipt = node_skills.skill_receipt(skill, trace)

        self.assertFalse(receipt["loaded"])
        self.assertFalse(receipt["successfully_used"])

    def test_receipt_distinguishes_loaded_from_successfully_used(self) -> None:
        skill = {"id": "paper-analysis", "available": True}
        trace = {
            "tool_calls": [
                {
                    "name": "skill_view",
                    "arguments": {"name": "paper-analysis"},
                    "status": "failed",
                }
            ]
        }

        receipt = node_skills.skill_receipt(skill, trace)

        self.assertTrue(receipt["loaded"])
        self.assertFalse(receipt["successfully_used"])
        self.assertFalse(receipt["used"])

    def test_successful_skill_view_does_not_prove_a_failed_run(self) -> None:
        skill = {"id": "paper-analysis", "available": True}
        trace = {
            "finish_reason": "failed",
            "tool_calls": [{
                "name": "skill_view",
                "arguments": {"name": "paper-analysis"},
                "status": "done",
            }],
        }

        receipt = node_skills.skill_receipt(skill, trace)

        self.assertTrue(receipt["loaded"])
        self.assertFalse(receipt["successfully_used"])

    def test_unavailable_skill_cannot_be_successfully_used(self) -> None:
        skill = {"id": "paper-analysis", "available": False}
        trace = {
            "tool_calls": [
                {
                    "name": "skill_view",
                    "arguments": {"name": "paper-analysis"},
                    "status": "done",
                }
            ]
        }

        receipt = node_skills.skill_receipt(skill, trace)

        self.assertTrue(receipt["requested"])
        self.assertFalse(receipt["available"])
        self.assertTrue(receipt["loaded"])
        self.assertFalse(receipt["successfully_used"])

    def test_directive_is_generic_and_requires_structured_proof(self) -> None:
        directive = node_skills.skill_directive({"id": "paper-analysis"})

        self.assertIn('skill_view(name="paper-analysis")', directive)
        self.assertIn("successfully_used", directive)
        self.assertNotIn("research", directive.lower())
        self.assertNotIn("query", directive.lower())
        self.assertNotIn("literal search", directive.lower())

    def test_invalid_skill_identifier_is_rejected(self) -> None:
        self.assertEqual(node_skills.requested_skill_id({"skill_id": "../../secrets"}), "")


if __name__ == "__main__":
    unittest.main()
