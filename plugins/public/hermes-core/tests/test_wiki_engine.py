import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN_ROOT = Path("/local/plugins/public/hermes-core")
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from hermes_wiki.bootstrap import ensure_layout
from hermes_wiki.config import load_settings
from hermes_wiki.doctrine import extract_doctrine_candidates
from hermes_wiki.emergence import discover_emergent_concepts
from hermes_wiki.governance import process_pending_proposals, queue_rollback_proposal, submit_proposal
from hermes_wiki.observability import build_observability_snapshot
from hermes_wiki.query import query_wiki
from hermes_wiki.refactor import analyse_refactor_candidates
from hermes_wiki.self_heal import run_self_heal


CLONE_MANAGER_PATH = Path("/local/scripts/public/clone/clone_manager.py")


def _load_clone_manager():
    spec = importlib.util.spec_from_file_location("clone_manager_for_tests", CLONE_MANAGER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load clone_manager module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLONE_MANAGER = _load_clone_manager()


class WikiEngineTests(unittest.TestCase):
    def _temp_root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def _settings(self, *, enabled: bool) -> tuple[Path, object, Path]:
        root = self._temp_root()
        env = {
            "NODE_WIKI_ENABLED": "1" if enabled else "0",
            "HERMES_WIKI_ROOT": str(root / "wiki"),
            "NODE_NAME": "test-node",
            "NODE_WIKI_DOCTRINE_MIN_FREQUENCY": "2",
            "NODE_WIKI_ECD_MIN_FREQUENCY": "2",
            "NODE_WIKI_PAGE_SPLIT_LINE_THRESHOLD": "30",
        }
        patcher = patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        return root, load_settings(), root / "node"

    def _submit_and_process(self, settings, payload: dict) -> tuple[dict, dict]:
        proposal = submit_proposal(settings, payload)
        result = process_pending_proposals(settings)
        return proposal, result

    def test_disabled_mode_is_safe_and_structured(self):
        root, settings, node_root = self._settings(enabled=False)
        layout = ensure_layout(settings, node_root=node_root)
        proposal = submit_proposal(
            settings,
            {
                "title": "Disabled Wiki Test",
                "details": "This should not create durable state while the wiki is disabled.",
                "durability_days": 90,
                "frequency": 2,
                "confidence": 0.8,
            },
        )
        query = query_wiki(settings, "disabled wiki test")

        self.assertFalse((root / "wiki").exists())
        self.assertFalse(layout["enabled"])
        self.assertEqual(proposal["status"], "disabled")
        self.assertFalse(query["enabled"])
        self.assertIn("plugins/private/", Path("/local/.gitignore").read_text(encoding="utf-8"))

    def test_bootstrap_creates_required_structure_and_is_idempotent(self):
        root, settings, node_root = self._settings(enabled=True)
        first = ensure_layout(settings, node_root=node_root)
        second = ensure_layout(settings, node_root=node_root)

        self.assertTrue((root / "wiki" / "index.md").exists())
        self.assertTrue((root / "wiki" / "meta" / "graph").is_dir())
        self.assertTrue((root / "wiki" / "meta" / "queues").is_dir())
        self.assertTrue((node_root / "wiki").is_symlink())
        self.assertGreater(len(first["seeded_files"]), 0)
        self.assertEqual(second["seeded_files"], [])

    def test_clone_manager_mounts_shared_wiki_only_when_enabled(self):
        root = self._temp_root()
        clone_root = root / "node"
        clone_root.mkdir(parents=True, exist_ok=True)
        env_path = root / "node.env"
        env_path.write_text("NODE_WIKI_ENABLED=true\n", encoding="utf-8")
        shared_discord = root / "plugins" / "discord"
        shared_discord.mkdir(parents=True, exist_ok=True)

        with patch.object(CLONE_MANAGER, "_ensure_node_log_topology", lambda *args, **kwargs: None), \
             patch.object(CLONE_MANAGER, "_node_log_dir", lambda name: root / "logs" / name), \
             patch.object(CLONE_MANAGER, "_node_attention_dir", lambda name: root / "attention" / name), \
             patch.object(CLONE_MANAGER, "_node_hermes_log_dir", lambda name: root / "hermes" / name), \
             patch.object(CLONE_MANAGER, "SHARED_CRONS_ROOT", root / "crons"), \
             patch.object(CLONE_MANAGER, "SHARED_SCRIPTS_ROOT", root / "scripts" / "public"), \
             patch.object(CLONE_MANAGER, "PRIVATE_SCRIPTS_ROOT", root / "scripts" / "private"), \
             patch.object(CLONE_MANAGER, "SHARED_PLUGINS_ROOT", root / "plugins"), \
             patch.object(CLONE_MANAGER, "PRIVATE_PLUGINS_ROOT", root / "plugins-private"), \
             patch.object(CLONE_MANAGER, "SHARED_WIKI_ROOT", root / "plugins-private" / "wiki"):
            cmd = CLONE_MANAGER._build_docker_run_cmd(
                "test-node",
                clone_root,
                env_path,
                "ubuntu:24.04",
                shared_discord,
                camofox_enabled=False,
                openviking_enabled=False,
                runtime_env_overrides={},
            )

        joined = " ".join(str(part) for part in cmd)
        self.assertIn("/local/wiki", joined)
        self.assertIn("HERMES_WIKI_ROOT=/local/wiki", joined)
        self.assertNotIn("/local/wiki-public", joined)

        env_path.write_text("NODE_WIKI_ENABLED=false\n", encoding="utf-8")
        with patch.object(CLONE_MANAGER, "_ensure_node_log_topology", lambda *args, **kwargs: None), \
             patch.object(CLONE_MANAGER, "_node_log_dir", lambda name: root / "logs" / f"off-{name}"), \
             patch.object(CLONE_MANAGER, "_node_attention_dir", lambda name: root / "attention" / f"off-{name}"), \
             patch.object(CLONE_MANAGER, "_node_hermes_log_dir", lambda name: root / "hermes" / f"off-{name}"), \
             patch.object(CLONE_MANAGER, "SHARED_CRONS_ROOT", root / "crons"), \
             patch.object(CLONE_MANAGER, "SHARED_SCRIPTS_ROOT", root / "scripts" / "public"), \
             patch.object(CLONE_MANAGER, "PRIVATE_SCRIPTS_ROOT", root / "scripts" / "private"), \
             patch.object(CLONE_MANAGER, "SHARED_PLUGINS_ROOT", root / "plugins"), \
             patch.object(CLONE_MANAGER, "PRIVATE_PLUGINS_ROOT", root / "plugins-private"), \
             patch.object(CLONE_MANAGER, "SHARED_WIKI_ROOT", root / "plugins-private" / "wiki"):
            cmd_disabled = CLONE_MANAGER._build_docker_run_cmd(
                "test-node-off",
                clone_root,
                env_path,
                "ubuntu:24.04",
                shared_discord,
                camofox_enabled=False,
                openviking_enabled=False,
                runtime_env_overrides={},
            )

        self.assertNotIn("/local/wiki", " ".join(str(part) for part in cmd_disabled))

    def test_clone_manager_worker_host_mirrors_include_skills_and_wikis(self):
        root = self._temp_root()
        clone_root = root / "node"
        clone_root.mkdir(parents=True, exist_ok=True)

        scripts_public = root / "scripts" / "public"
        scripts_private = root / "scripts" / "private"
        skills_root = root / "skills"
        private_wiki = root / "plugins-private" / "wiki"
        crons_root = root / "crons"

        for path in (scripts_public, scripts_private, skills_root, private_wiki, crons_root):
            path.mkdir(parents=True, exist_ok=True)

        (scripts_public / "hello.sh").write_text("echo public\n", encoding="utf-8")
        (scripts_private / "secret.sh").write_text("echo private\n", encoding="utf-8")
        (skills_root / "skill.md").write_text("# skill\n", encoding="utf-8")
        (private_wiki / "index.md").write_text("# private wiki\n", encoding="utf-8")
        # Legacy topology migration should remove this path when normalizing links.
        (clone_root / "wiki-public").mkdir(parents=True, exist_ok=True)
        (clone_root / "wiki-public" / "legacy.md").write_text("legacy\n", encoding="utf-8")

        with patch.object(CLONE_MANAGER, "SHARED_SCRIPTS_ROOT", scripts_public), \
             patch.object(CLONE_MANAGER, "PRIVATE_SCRIPTS_ROOT", scripts_private), \
             patch.object(CLONE_MANAGER, "PRIVATE_SKILLS_ROOT", skills_root), \
             patch.object(CLONE_MANAGER, "SHARED_WIKI_ROOT", private_wiki), \
             patch.object(CLONE_MANAGER, "SHARED_CRONS_ROOT", crons_root):
            CLONE_MANAGER._ensure_worker_shared_mount_links(clone_root, "worker-a")
            CLONE_MANAGER._sync_node_wiki_link(
                clone_root,
                {"NODE_WIKI_ENABLED": "true"},
                containerized=True,
            )

        self.assertTrue((clone_root / "scripts" / "public" / "hello.sh").exists())
        self.assertTrue((clone_root / "scripts" / "private" / "secret.sh").exists())
        self.assertTrue((clone_root / "skills" / "skill.md").exists())
        self.assertTrue((clone_root / "wiki" / "index.md").exists())
        self.assertFalse((clone_root / "wiki-public").exists())
        self.assertTrue((clone_root / "cron").is_symlink())
        self.assertEqual((clone_root / "cron").resolve(), (crons_root / "worker-a").resolve())

    def test_proposal_pipeline_moderation_and_consolidation_gate(self):
        root, settings, node_root = self._settings(enabled=True)
        ensure_layout(settings, node_root=node_root)

        rejected = submit_proposal(
            settings,
            {
                "proposal_type": "scratch",
                "page_type": "concept",
                "title": "Temporary Debug Notes",
                "details": "short lived debug note",
                "durability_days": 1,
                "frequency": 1,
                "confidence": 0.2,
            },
        )
        self.assertEqual(rejected["status"], "rejected")

        proposal, result = self._submit_and_process(
            settings,
            {
                "proposal_type": "knowledge_write",
                "page_type": "procedure",
                "title": "Restart Gateway Safely",
                "one_line_summary": "Restart the gateway from the orchestrator before deeper debugging.",
                "short_summary": "Use the node restart path and confirm runtime logs settle.",
                "details": "Restart the node and inspect runtime plus attention logs before escalating.",
                "confidence": 0.8,
                "durability_days": 90,
                "frequency": 3,
                "agent_id": "agent-a",
                "tags": ["gateway", "operations"],
                "sources": ["operator-validation"],
                "evidence": ["Observed in repeated runtime recoveries."],
            },
        )
        page_path = root / "wiki" / "global" / "restart-gateway-safely.md"
        self.assertIn(proposal["proposal_id"], result["executed"])
        self.assertTrue(page_path.exists())
        self.assertTrue((root / "wiki" / "indexes" / "by-type.md").exists())

        update = submit_proposal(
            settings,
            {
                "proposal_type": "knowledge_write",
                "page_type": "procedure",
                "title": "Restart Gateway Safely",
                "details": "Verify attention logs are quiet after the restart completes.",
                "confidence": 0.85,
                "durability_days": 90,
                "frequency": 4,
                "agent_id": "agent-b",
            },
        )
        self.assertEqual(update["classification"]["action"], "update_existing")
        process_pending_proposals(settings)
        self.assertIn("Verify attention logs are quiet", page_path.read_text(encoding="utf-8"))
        self.assertEqual(len(list((root / "wiki" / "global").glob("restart-gateway-safely*.md"))), 1)

    def test_coordination_conflict_detection_and_idempotent_retry(self):
        root, settings, node_root = self._settings(enabled=True)
        ensure_layout(settings, node_root=node_root)

        first = submit_proposal(
            settings,
            {
                "proposal_type": "knowledge_write",
                "page_type": "concept",
                "title": "Gateway Recovery Canonical",
                "one_line_summary": "Canonical recovery path.",
                "short_summary": "Use the orchestrator path first.",
                "details": "Canonical runbook content.",
                "aliases": ["gateway recovery"],
                "trust_tier": "canonical",
                "confidence": 0.95,
                "durability_days": 120,
                "frequency": 4,
                "agent_id": "agent-a",
            },
        )
        duplicate = submit_proposal(
            settings,
            {
                "proposal_type": "knowledge_write",
                "page_type": "concept",
                "title": "Gateway Recovery Canonical",
                "one_line_summary": "Duplicate canonical recovery path.",
                "short_summary": "Duplicate proposal.",
                "details": "Duplicate runbook content.",
                "aliases": ["gateway recovery"],
                "trust_tier": "canonical",
                "confidence": 0.9,
                "durability_days": 120,
                "frequency": 4,
                "agent_id": "agent-b",
            },
        )
        first_process = process_pending_proposals(settings)
        second_process = process_pending_proposals(settings)

        self.assertIn(first["proposal_id"], first_process["executed"])
        self.assertIn(duplicate["proposal_id"], first_process["duplicates_rejected"])
        self.assertEqual(second_process["executed"], [])

        page_path = root / "wiki" / "global" / "gateway-recovery-canonical.md"
        conflict = submit_proposal(
            settings,
            {
                "proposal_type": "knowledge_write",
                "page_type": "concept",
                "title": "Gateway Recovery Canonical",
                "details": "This update should conflict because the page changes before processing.",
                "confidence": 0.8,
                "durability_days": 90,
                "frequency": 3,
                "agent_id": "agent-c",
            },
        )
        page_path.write_text(page_path.read_text(encoding="utf-8") + "\n<!-- external change -->\n", encoding="utf-8")
        conflict_result = process_pending_proposals(settings)
        self.assertIn(conflict["proposal_id"], conflict_result["review_needed"])

    def test_query_observability_trust_preference_and_rollback(self):
        root, settings, node_root = self._settings(enabled=True)
        ensure_layout(settings, node_root=node_root)

        self._submit_and_process(
            settings,
            {
                "proposal_type": "knowledge_write",
                "page_type": "concept",
                "title": "Gateway Recovery Canonical",
                "one_line_summary": "Canonical recovery guidance.",
                "short_summary": "Canonical path for recovering a stuck gateway.",
                "details": "Prefer restart and log verification.",
                "aliases": ["gateway recovery"],
                "trust_tier": "canonical",
                "confidence": 0.95,
                "durability_days": 120,
                "frequency": 4,
                "agent_id": "agent-a",
                "evidence": ["Validated repeatedly."],
            },
        )
        self._submit_and_process(
            settings,
            {
                "proposal_type": "knowledge_write",
                "page_type": "concept",
                "title": "Gateway Recovery Draft",
                "one_line_summary": "Draft recovery guidance.",
                "short_summary": "Draft path for recovering a stuck gateway.",
                "details": "Draft notes.",
                "aliases": ["gateway recovery"],
                "trust_tier": "provisional",
                "confidence": 0.5,
                "durability_days": 120,
                "frequency": 4,
                "agent_id": "agent-b",
            },
        )
        canonical_path = root / "wiki" / "global" / "gateway-recovery-canonical.md"
        update = submit_proposal(
            settings,
            {
                "proposal_type": "knowledge_write",
                "page_type": "concept",
                "title": "Gateway Recovery Canonical",
                "details": "Updated detail that should be reverted by rollback.",
                "confidence": 0.9,
                "durability_days": 90,
                "frequency": 3,
                "agent_id": "agent-a",
            },
        )
        process_pending_proposals(settings)

        query = query_wiki(settings, "gateway recovery", require_detail=True)
        snapshot = build_observability_snapshot(settings)
        rollback = queue_rollback_proposal(settings, target_path="global/gateway-recovery-canonical.md")
        rollback_process = process_pending_proposals(settings)

        self.assertEqual(query["selected_node"], "gateway-recovery-canonical")
        self.assertLessEqual(query["pages_loaded"], settings.max_pages_per_query)
        self.assertGreater(snapshot["health_score"], 0)
        self.assertTrue(rollback["proposal_id"])
        self.assertIn(rollback["proposal_id"], rollback_process["executed"])
        self.assertNotIn("Updated detail that should be reverted", canonical_path.read_text(encoding="utf-8"))

    def test_doctrine_akr_ecd_self_heal_and_canonical_preservation(self):
        root, settings, node_root = self._settings(enabled=True)
        ensure_layout(settings, node_root=node_root)

        long_details = "\n".join(f"Line {index}: repeated durable explanation." for index in range(40))
        self._submit_and_process(
            settings,
            {
                "proposal_type": "knowledge_write",
                "page_type": "procedure",
                "title": "Gateway Rebuild Procedure",
                "one_line_summary": "Rebuild the gateway when restarts stop helping.",
                "short_summary": "Use the rebuild path for persistent failures.",
                "details": long_details,
                "confidence": 0.85,
                "durability_days": 120,
                "frequency": 4,
                "agent_id": "agent-a",
                "tags": ["gateway", "rebuild"],
                "evidence": ["Repeated runbook validation."],
            },
        )
        self._submit_and_process(
            settings,
            {
                "proposal_type": "knowledge_write",
                "page_type": "procedure",
                "title": "Gateway Rebuild Playbook",
                "one_line_summary": "A near-duplicate rebuild runbook.",
                "short_summary": "This overlaps heavily with the rebuild procedure.",
                "details": "This near duplicate should trigger AKR merge analysis.",
                "confidence": 0.8,
                "durability_days": 120,
                "frequency": 4,
                "agent_id": "agent-b",
                "tags": ["gateway", "rebuild"],
                "evidence": ["Repeated runbook validation."],
            },
        )

        log_root = root / "logs"
        log_root.mkdir(parents=True, exist_ok=True)
        repeated = "gateway rebuild failed after restart timeout"
        (log_root / "a.log").write_text(f"{repeated}\n{repeated}\n", encoding="utf-8")
        (log_root / "b.log").write_text(f"{repeated}\n{repeated}\n", encoding="utf-8")

        doctrine = extract_doctrine_candidates(settings, source_paths=[log_root], stage_proposals=True)
        akr = analyse_refactor_candidates(settings, stage_proposals=True)
        ecd = discover_emergent_concepts(settings, stage_proposals=True)

        page_path = root / "wiki" / "global" / "gateway-rebuild-procedure.md"
        before = page_path.read_text(encoding="utf-8")
        graph_nodes = root / "wiki" / "meta" / "graph" / "nodes.json"
        graph_nodes.write_text("{not valid json", encoding="utf-8")
        heal = run_self_heal(settings, node_root=node_root)
        after = page_path.read_text(encoding="utf-8")

        self.assertGreaterEqual(doctrine["candidate_count"], 1)
        self.assertGreaterEqual(len(doctrine["staged_proposals"]), 1)
        self.assertGreaterEqual(akr["action_count"], 1)
        self.assertGreaterEqual(ecd["candidate_count"], 1)
        self.assertEqual(before, after)
        self.assertEqual(heal["failures"], [])
        self.assertGreaterEqual(len(heal["quarantined"]), 1)
        self.assertTrue(json.loads(graph_nodes.read_text(encoding="utf-8")))

    def test_failure_modes_are_explicit_for_missing_rollback_target(self):
        root, settings, node_root = self._settings(enabled=True)
        ensure_layout(settings, node_root=node_root)
        payload = queue_rollback_proposal(settings, target_path="global/does-not-exist.md")
        self.assertEqual(payload["status"], "missing_target")
        self.assertIn("target page not found", payload["reason"])


if __name__ == "__main__":
    unittest.main()
