from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import clone_manager


class GovernancePromptTests(unittest.TestCase):
    def test_non_orchestrator_node_state_one_is_normalized_to_worker(self) -> None:
        text = clone_manager._build_node_runtime_contract_text(
            "colmeio",
            {"NODE_STATE": "1", "NODE_TIME_ZONE": "UTC"},
        )
        prompt = clone_manager._build_node_governance_prompt(
            "colmeio",
            {"NODE_STATE": "1"},
        )

        self.assertIn("- Role: worker-node", text)
        self.assertIn("Bootstrap mode: NODE_STATE=2 (seed_from_parent_snapshot)", text)
        self.assertIn("Do not execute or claim direct shared plugin/framework mutations; escalate to orchestrator.", prompt)

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

    def test_runtime_env_overrides_pin_canonical_slash_cache_to_workspace(self) -> None:
        overrides = clone_manager._runtime_env_overrides("colmeio", {})

        self.assertEqual(
            overrides["HERMES_DISCORD_SLASH_CACHE_ROOT"],
            "/local/workspace/plugins/discord-slash-commands/cache",
        )
        self.assertEqual(
            overrides["HERMES_DISCORD_PRIVATE_DIR"],
            "/local/workspace/plugins/discord-slash-commands/cache/governance",
        )
        self.assertEqual(
            overrides["DISCORD_COMMANDS_FILE"],
            "/local/workspace/plugins/discord-slash-commands/cache/catalogs/custom_commands.json",
        )
        self.assertEqual(
            overrides["DISCORD_USERS_DB"],
            "/local/workspace/plugins/discord-slash-commands/cache/governance/discord_users.json",
        )
        self.assertEqual(overrides["OPENVIKING_ENABLED"], "0")
        self.assertEqual(overrides["MEMORY_OPENVIKING"], "0")
        self.assertEqual(overrides["OPENVIKING_ENDPOINT"], "")
        self.assertEqual(overrides["OPENVIKING_ACCOUNT"], "")
        self.assertEqual(overrides["OPENVIKING_USER"], "")

    def test_openviking_bootstrap_is_deprecated_noop_and_clears_stale_provider(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clone-manager-openviking-deprecated-") as tmp:
            root = Path(tmp)
            clone_root = root / "agents" / "nodes" / "colmeio"
            env_path = root / "colmeio.env"
            config_path = clone_root / ".hermes" / "config.yaml"

            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("memory:\n  provider: openviking\n", encoding="utf-8")
            env_path.write_text(
                "\n".join(
                    [
                        "OPENVIKING_ENABLED=1",
                        "OPENVIKING_ENDPOINT=http://host.docker.internal:1933",
                        "OPENVIKING_ACCOUNT=colmeio",
                        "OPENVIKING_USER=colmeio",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = clone_manager._bootstrap_openviking_for_clone("colmeio", env_path, clone_root)

            self.assertFalse(payload["enabled"])
            self.assertTrue(payload["deprecated"])
            self.assertTrue(payload["changed"])
            self.assertEqual(payload["effective"]["endpoint"], "")
            self.assertNotIn("openviking", config_path.read_text(encoding="utf-8"))

    def test_bare_orchestrator_runtime_overrides_translate_container_paths_to_node_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clone-manager-host-paths-") as tmp:
            root = Path(tmp)
            clone_root = root / "agents" / "nodes" / "orchestrator"
            data_root = root / "datas"
            clone_root.mkdir(parents=True, exist_ok=True)

            original_data_root = clone_manager.SHARED_NODE_DATA_ROOT
            try:
                clone_manager.SHARED_NODE_DATA_ROOT = data_root
                translated = clone_manager._translate_runtime_overrides_for_host(
                    {
                        "COLMEIO_PROJECT_DIR": "/local/workspace",
                        "DISCORD_COMMANDS_FILE": "/local/workspace/plugins/discord-slash-commands/cache/catalogs/custom_commands.json",
                        "HERMES_DATA_DIR": "/local/data",
                        "HERMES_NODE_RUNTIME_CONTRACT_PATH": "/local/.hermes/NODE_RUNTIME_CONTRACT.md",
                    },
                    clone_root=clone_root,
                    clone_name="orchestrator",
                )
            finally:
                clone_manager.SHARED_NODE_DATA_ROOT = original_data_root

            self.assertEqual(translated["COLMEIO_PROJECT_DIR"], str(clone_root / "workspace"))
            self.assertEqual(
                translated["DISCORD_COMMANDS_FILE"],
                str(clone_root / "workspace" / "plugins" / "discord-slash-commands" / "cache" / "catalogs" / "custom_commands.json"),
            )
            self.assertEqual(translated["HERMES_DATA_DIR"], str(data_root / "orchestrator"))
            self.assertEqual(
                translated["HERMES_NODE_RUNTIME_CONTRACT_PATH"],
                str(clone_root / ".hermes" / "NODE_RUNTIME_CONTRACT.md"),
            )

    def test_legacy_host_workspace_is_migrated_to_orchestrator_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clone-manager-legacy-workspace-") as tmp:
            root = Path(tmp)
            legacy = root / "workspace"
            clones_root = root / "agents" / "nodes"
            legacy.mkdir(parents=True)
            (legacy / "payload.txt").write_text("keep me\n", encoding="utf-8")

            original_legacy = clone_manager.LEGACY_HOST_WORKSPACE_ROOT
            original_clones = clone_manager.CLONES_ROOT
            try:
                clone_manager.LEGACY_HOST_WORKSPACE_ROOT = legacy
                clone_manager.CLONES_ROOT = clones_root

                clone_manager._migrate_legacy_host_workspace_root()
            finally:
                clone_manager.LEGACY_HOST_WORKSPACE_ROOT = original_legacy
                clone_manager.CLONES_ROOT = original_clones

            self.assertFalse(legacy.exists())
            self.assertEqual(
                (clones_root / "orchestrator" / "workspace" / "payload.txt").read_text(encoding="utf-8"),
                "keep me\n",
            )

    def test_docker_run_cmd_mounts_canonical_discord_slash_plugin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clone-manager-canonical-discord-") as tmp:
            root = Path(tmp)
            source_root = root / "source"
            plugins_root = root / "plugins"
            scripts_root = root / "scripts"
            clone_root = root / "clone"
            env_path = root / "colmeio.env"

            source_root.mkdir(parents=True, exist_ok=True)
            (plugins_root / "public").mkdir(parents=True, exist_ok=True)
            (plugins_root / "private").mkdir(parents=True, exist_ok=True)
            (plugins_root / "discord-slash-commands" / "scripts").mkdir(parents=True, exist_ok=True)
            clone_root.mkdir(parents=True, exist_ok=True)
            env_path.write_text("", encoding="utf-8")

            original_shared_crons = clone_manager.SHARED_CRONS_ROOT
            original_node_activity = clone_manager.NODE_ACTIVITY_LOG_ROOT
            original_private_skills = clone_manager.PRIVATE_SKILLS_ROOT

            try:
                clone_manager.SHARED_CRONS_ROOT = root / "crons"
                clone_manager.NODE_ACTIVITY_LOG_ROOT = root / "activity"
                clone_manager.PRIVATE_SKILLS_ROOT = root / "skills"

                with clone_manager._temporary_runtime_roots(
                    source_root=source_root,
                    plugins_root=plugins_root,
                    scripts_root=scripts_root,
                ), mock.patch.object(clone_manager, "_ensure_node_log_topology"), mock.patch.object(
                    clone_manager,
                    "_node_log_dir",
                    side_effect=lambda name: root / "logs" / name,
                ), mock.patch.object(
                    clone_manager,
                    "_node_attention_dir",
                    side_effect=lambda name: root / "attention" / name,
                ), mock.patch.object(
                    clone_manager,
                    "_node_hermes_log_dir",
                    side_effect=lambda name: root / "hermes-logs" / name,
                ), mock.patch.object(
                    clone_manager,
                    "_shared_node_data_dir",
                    side_effect=lambda name: root / "data" / name,
                ):
                    cmd = clone_manager._build_docker_run_cmd(
                        "colmeio",
                        clone_root,
                        env_path,
                        "ubuntu:24.04",
                        plugins_root / "public" / "discord",
                        camofox_enabled=False,
                        openviking_enabled=False,
                        runtime_env_overrides={},
                    )
            finally:
                clone_manager.SHARED_CRONS_ROOT = original_shared_crons
                clone_manager.NODE_ACTIVITY_LOG_ROOT = original_node_activity
                clone_manager.PRIVATE_SKILLS_ROOT = original_private_skills

            self.assertIn(
                f"{plugins_root / 'discord-slash-commands'}:/local/plugins/discord-slash-commands:ro",
                cmd,
            )
            self.assertIn(
                "HERMES_NATIVE_DISCORD_SLASH_COMMANDS_DIR=/local/plugins/discord-slash-commands",
                cmd,
            )

    def test_docker_run_cmd_skips_legacy_plugin_mounts_when_roots_are_absent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clone-manager-no-legacy-plugin-mounts-") as tmp:
            root = Path(tmp)
            source_root = root / "source"
            plugins_root = root / "plugins"
            scripts_root = root / "scripts"
            clone_root = root / "clone"
            env_path = root / "colmeio.env"

            source_root.mkdir(parents=True, exist_ok=True)
            (plugins_root / "discord-slash-commands" / "scripts").mkdir(parents=True, exist_ok=True)
            clone_root.mkdir(parents=True, exist_ok=True)
            env_path.write_text("", encoding="utf-8")

            original_shared_crons = clone_manager.SHARED_CRONS_ROOT
            original_node_activity = clone_manager.NODE_ACTIVITY_LOG_ROOT
            original_private_skills = clone_manager.PRIVATE_SKILLS_ROOT

            try:
                clone_manager.SHARED_CRONS_ROOT = root / "crons"
                clone_manager.NODE_ACTIVITY_LOG_ROOT = root / "activity"
                clone_manager.PRIVATE_SKILLS_ROOT = root / "skills"

                with clone_manager._temporary_runtime_roots(
                    source_root=source_root,
                    plugins_root=plugins_root,
                    scripts_root=scripts_root,
                ), mock.patch.object(clone_manager, "_ensure_node_log_topology"), mock.patch.object(
                    clone_manager,
                    "_node_log_dir",
                    side_effect=lambda name: root / "logs" / name,
                ), mock.patch.object(
                    clone_manager,
                    "_node_attention_dir",
                    side_effect=lambda name: root / "attention" / name,
                ), mock.patch.object(
                    clone_manager,
                    "_node_hermes_log_dir",
                    side_effect=lambda name: root / "hermes-logs" / name,
                ), mock.patch.object(
                    clone_manager,
                    "_shared_node_data_dir",
                    side_effect=lambda name: root / "data" / name,
                ):
                    cmd = clone_manager._build_docker_run_cmd(
                        "colmeio",
                        clone_root,
                        env_path,
                        "ubuntu:24.04",
                        plugins_root / "public" / "discord",
                        camofox_enabled=False,
                        openviking_enabled=False,
                        runtime_env_overrides={},
                    )
            finally:
                clone_manager.SHARED_CRONS_ROOT = original_shared_crons
                clone_manager.NODE_ACTIVITY_LOG_ROOT = original_node_activity
                clone_manager.PRIVATE_SKILLS_ROOT = original_private_skills

            self.assertNotIn("HERMES_PUBLIC_PLUGINS_ROOT=/local/plugins/public", cmd)
            self.assertNotIn("HERMES_PRIVATE_PLUGINS_ROOT=/local/plugins/private", cmd)
            self.assertFalse(
                any(
                    str(part).endswith(":/local/plugins/public:ro")
                    or str(part).endswith(":/local/plugins/private")
                    for part in cmd
                )
            )
            self.assertIn(
                f"{plugins_root / 'discord-slash-commands'}:/local/plugins/discord-slash-commands:ro",
                cmd,
            )

    def test_sync_discord_runtime_layout_uses_node_local_governance_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clone-manager-discord-runtime-layout-") as tmp:
            root = Path(tmp)
            clone_root = root / "agents" / "nodes" / "colmeio"
            plugins_root = root / "plugins"
            scripts_root = root / "scripts"
            source_root = root / "source"

            source_root.mkdir(parents=True, exist_ok=True)
            (plugins_root / "public" / "discord").mkdir(parents=True, exist_ok=True)
            (plugins_root / "private" / "discord").mkdir(parents=True, exist_ok=True)
            clone_root.mkdir(parents=True, exist_ok=True)

            with clone_manager._temporary_runtime_roots(
                source_root=source_root,
                plugins_root=plugins_root,
                scripts_root=scripts_root,
            ):
                clone_manager._sync_discord_runtime_layout(clone_root, "colmeio", {})

            self.assertTrue(
                (
                    clone_root
                    / "workspace"
                    / "plugins"
                    / "discord-slash-commands"
                    / "cache"
                    / "governance"
                    / "discord_users.json"
                ).exists()
            )
            self.assertFalse((plugins_root / "private" / "discord" / "discord_users.json").exists())


if __name__ == "__main__":
    unittest.main()
