from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


_SCRIPT_CANDIDATES = (
    Path("/local/plugins/public/discord/scripts/model_env_bootstrap.py"),
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


class ModelBootstrapTests(unittest.TestCase):
    maxDiff = None

    def _run_bootstrap(self, *, env_file: Path, config_file: Path) -> dict:
        cmd = [
            "python3",
            str(SCRIPT_PATH),
            "--env-file",
            str(env_file),
            "--config-file",
            str(config_file),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, msg=f"stderr={proc.stderr}")
        self.assertTrue(proc.stdout.strip(), msg=f"missing stdout, stderr={proc.stderr}")
        payload = json.loads(proc.stdout)
        self.assertIsInstance(payload, dict)
        return payload

    def test_sets_default_model_from_env_and_normalizes_minimax(self) -> None:
        with tempfile.TemporaryDirectory(prefix="model-bootstrap-test-") as tmp:
            root = Path(tmp)
            env_file = root / "agent.env"
            config_file = root / ".hermes" / "config.yaml"

            _write_text(
                env_file,
                "\n".join(
                    [
                        "HERMES_INFERENCE_PROVIDER=minimax",
                        "DEFAULT_MODEL=MiniMax M2.7",
                        "",
                    ]
                ),
            )
            _write_text(config_file, "model:\n  default: ''\n  provider: ''\n")

            payload = self._run_bootstrap(env_file=env_file, config_file=config_file)
            self.assertTrue(payload.get("ok"))
            self.assertTrue(payload.get("changed"))

            cfg = _read_yaml(config_file)
            model_cfg = cfg.get("model", {})
            self.assertEqual(model_cfg.get("default"), "MiniMax-M2.7")
            self.assertEqual(model_cfg.get("provider"), "minimax")
            self.assertEqual(cfg.get("provider"), "minimax")

    def test_idempotent_when_reapplied(self) -> None:
        with tempfile.TemporaryDirectory(prefix="model-bootstrap-test-") as tmp:
            root = Path(tmp)
            env_file = root / "agent.env"
            config_file = root / ".hermes" / "config.yaml"

            _write_text(
                env_file,
                "\n".join(
                    [
                        "DEFAULT_MODEL_PROVIDER=minimax",
                        "DEFAULT_MODEL=MiniMax-M2.7",
                        "FALLBACK_MODEL_PROVIDER=kimi-coding",
                        "FALLBACK_MODEL=moonshotai/kimi-k2.5",
                        "",
                    ]
                ),
            )
            _write_text(config_file, "model:\n  default: MiniMax-M2.7\n  provider: minimax\n")

            first = self._run_bootstrap(env_file=env_file, config_file=config_file)
            second = self._run_bootstrap(env_file=env_file, config_file=config_file)
            self.assertTrue(first.get("ok"))
            self.assertTrue(second.get("ok"))
            self.assertFalse(second.get("changed"))

            cfg = _read_yaml(config_file)
            fb = cfg.get("fallback_model", {})
            self.assertEqual(fb.get("provider"), "kimi-coding")
            self.assertEqual(fb.get("model"), "moonshotai/kimi-k2.5")

    def test_uses_provider_default_when_model_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="model-bootstrap-test-") as tmp:
            root = Path(tmp)
            env_file = root / ".hermes" / ".env"
            config_file = root / ".hermes" / "config.yaml"

            _write_text(env_file, "HERMES_INFERENCE_PROVIDER=minimax\n")
            _write_text(config_file, "model: {}\n")

            payload = self._run_bootstrap(env_file=env_file, config_file=config_file)
            self.assertTrue(payload.get("ok"))

            cfg = _read_yaml(config_file)
            model_cfg = cfg.get("model", {})
            self.assertEqual(model_cfg.get("provider"), "minimax")
            self.assertEqual(model_cfg.get("default"), "MiniMax-M2.7")


if __name__ == "__main__":
    unittest.main()
