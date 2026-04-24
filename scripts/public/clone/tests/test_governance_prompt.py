from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import clone_manager


class GovernancePromptTests(unittest.TestCase):
    def test_runtime_contract_includes_execution_discipline(self) -> None:
        text = clone_manager._build_node_runtime_contract_text(
            "orchestrator",
            {"NODE_STATE": "1", "NODE_TIME_ZONE": "UTC"},
        )

        self.assertIn("## Execution Discipline", text)
        self.assertIn("Think before acting", text)
        self.assertIn("Simplicity first", text)
        self.assertIn("Surgical changes", text)
        self.assertIn("Goal-driven execution", text)

    def test_orchestrator_prompt_requires_shared_change_discipline(self) -> None:
        prompt = clone_manager._build_node_governance_prompt(
            "orchestrator",
            {"NODE_STATE": "1"},
        )

        self.assertIn("You own shared plugin/framework execution and rollout for the fleet.", prompt)
        self.assertIn("Execution discipline for shared infrastructure", prompt)
        self.assertIn("Think before acting", prompt)
        self.assertIn("Goal-driven execution", prompt)
        self.assertIn("rollout+rollback", prompt)
        self.assertIn("/local/plugins/public/native/scripts/prestart_reapply.sh", prompt)

    def test_worker_prompt_keeps_escalation_rule(self) -> None:
        prompt = clone_manager._build_node_governance_prompt(
            "worker-a",
            {"NODE_STATE": "4"},
        )

        self.assertIn(
            "Do not execute or claim direct shared plugin/framework mutations; escalate to orchestrator.",
            prompt,
        )
        self.assertIn("Surgical changes", prompt)

    def test_prestart_script_path_prefers_native_pipeline(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clone-manager-native-prestart-") as tmp:
            root = Path(tmp)
            source_root = root / "source"
            plugins_root = root / "plugins"
            scripts_root = root / "scripts"
            source_root.mkdir(parents=True, exist_ok=True)
            (plugins_root / "public" / "native" / "scripts").mkdir(parents=True, exist_ok=True)
            (plugins_root / "public" / "hermes-core" / "scripts").mkdir(parents=True, exist_ok=True)

            native_script = plugins_root / "public" / "native" / "scripts" / "prestart_reapply.sh"
            legacy_script = plugins_root / "public" / "hermes-core" / "scripts" / "prestart_reapply.sh"
            native_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            legacy_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            with clone_manager._temporary_runtime_roots(
                source_root=source_root,
                plugins_root=plugins_root,
                scripts_root=scripts_root,
            ):
                resolved = clone_manager._prestart_script_path()

            self.assertEqual(resolved, native_script)


if __name__ == "__main__":
    unittest.main()
