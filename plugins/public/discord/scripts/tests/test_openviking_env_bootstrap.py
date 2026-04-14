from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


_SCRIPT_CANDIDATES = (
    Path("/local/plugins/public/discord/scripts/openviking_env_bootstrap.py"),
)
SCRIPT_PATH = next((p for p in _SCRIPT_CANDIDATES if p.exists()), _SCRIPT_CANDIDATES[0])


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


class OpenVikingBootstrapTests(unittest.TestCase):
    maxDiff = None

    def _run_bootstrap(
        self,
        *,
        env_file: Path,
        config_file: Path,
        agent_root: Path,
        default_endpoint: str = "http://127.0.0.1:1933",
        default_account: str = "colmeio",
        default_user: str = "colmeio",
        persist_env: bool = False,
    ) -> dict:
        cmd = [
            "python3",
            str(SCRIPT_PATH),
            "--env-file",
            str(env_file),
            "--config-file",
            str(config_file),
            "--agent-root",
            str(agent_root),
            "--default-endpoint",
            default_endpoint,
            "--default-account",
            default_account,
            "--default-user",
            default_user,
            "--health-timeout-sec",
            "0.2",
        ]
        if persist_env:
            cmd.append("--persist-env")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertTrue(proc.stdout.strip(), msg=f"missing stdout, stderr={proc.stderr}")
        payload = json.loads(proc.stdout)
        self.assertIsInstance(payload, dict)
        return payload

    def test_disabled_flag_makes_no_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ov-bootstrap-test-") as tmp:
            root = Path(tmp)
            env_file = root / ".hermes" / ".env"
            config_file = root / ".hermes" / "config.yaml"
            agent_root = root / "hermes-agent"

            _write_text(env_file, "MEMORY_OPENVIKING=0\n")
            _write_text(config_file, "memory:\n  provider: honcho\n")
            _write_text(
                agent_root / "plugins" / "memory" / "openviking" / "__init__.py",
                "# marker\n",
            )

            payload = self._run_bootstrap(
                env_file=env_file,
                config_file=config_file,
                agent_root=agent_root,
            )
            self.assertTrue(payload.get("ok"))
            self.assertFalse(payload.get("enabled"))
            self.assertFalse(payload.get("changed"))
            cfg = _read_yaml(config_file)
            self.assertEqual(cfg.get("memory", {}).get("provider"), "honcho")

    def test_enabled_sets_defaults_and_forces_provider_idempotently(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ov-bootstrap-test-") as tmp:
            root = Path(tmp)
            env_file = root / "clone.env"
            config_file = root / ".hermes" / "config.yaml"
            agent_root = root / "hermes-agent"

            _write_text(env_file, "MEMORY_OPENVIKING=1\n")
            _write_text(config_file, "memory:\n  provider: mem0\n")
            _write_text(
                agent_root / "plugins" / "memory" / "openviking" / "__init__.py",
                "# marker\n",
            )

            first = self._run_bootstrap(
                env_file=env_file,
                config_file=config_file,
                agent_root=agent_root,
                default_endpoint="http://host.docker.internal:1933",
                default_account="colmeio",
                default_user="hermes-catatau",
            )
            self.assertTrue(first.get("ok"))
            self.assertTrue(first.get("enabled"))
            self.assertTrue(first.get("changed"))
            self.assertEqual(first.get("provider_current"), "openviking")
            effective = first.get("effective", {})
            self.assertEqual(effective.get("endpoint"), "http://host.docker.internal:1933")
            self.assertEqual(effective.get("account"), "colmeio")
            self.assertEqual(effective.get("user"), "hermes-catatau")

            env_data = env_file.read_text(encoding="utf-8")
            self.assertNotIn("OPENVIKING_ACCOUNT=", env_data)
            self.assertNotIn("OPENVIKING_USER=", env_data)

            cfg = _read_yaml(config_file)
            self.assertEqual(cfg.get("memory", {}).get("provider"), "openviking")

            second = self._run_bootstrap(
                env_file=env_file,
                config_file=config_file,
                agent_root=agent_root,
                default_endpoint="http://host.docker.internal:1933",
                default_account="colmeio",
                default_user="hermes-catatau",
            )
            self.assertTrue(second.get("ok"))
            self.assertTrue(second.get("enabled"))
            self.assertFalse(second.get("changed"))

    def test_missing_plugin_degrades_but_keeps_start_fail_open(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ov-bootstrap-test-") as tmp:
            root = Path(tmp)
            env_file = root / ".hermes" / ".env"
            config_file = root / ".hermes" / "config.yaml"
            agent_root = root / "hermes-agent"

            _write_text(env_file, "MEMORY_OPENVIKING=1\n")
            _write_text(config_file, "memory:\n  provider: honcho\n")
            agent_root.mkdir(parents=True, exist_ok=True)  # No plugin path

            payload = self._run_bootstrap(
                env_file=env_file,
                config_file=config_file,
                agent_root=agent_root,
                default_user="legacy-clone",
            )
            self.assertTrue(payload.get("ok"))
            self.assertTrue(payload.get("enabled"))
            self.assertTrue(payload.get("degraded"))

            compatibility = payload.get("compatibility", {})
            self.assertIsInstance(compatibility, dict)
            self.assertFalse(bool(compatibility.get("supported")))

            cfg = _read_yaml(config_file)
            # Provider should be unchanged when plugin support is missing.
            self.assertEqual(cfg.get("memory", {}).get("provider"), "honcho")


if __name__ == "__main__":
    unittest.main()
