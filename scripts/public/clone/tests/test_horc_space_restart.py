from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
import unittest


HORC = Path(__file__).resolve().parents[1] / "horc.sh"


class HorcSpaceRestartTests(unittest.TestCase):
    def test_space_relaunch_stops_then_starts_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="horc-space-restart-test-") as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "wasm-agent"
            scripts_dir = plugin_dir / "scripts"
            scripts_dir.mkdir(parents=True)
            log_path = root / "restart.log"
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "fuser").write_text(
                f"#!/usr/bin/env bash\nprintf 'kill-port:%s:%s\\n' \"$1\" \"$2\" >> {log_path}\n",
                encoding="utf-8",
            )
            os.chmod(bin_dir / "fuser", 0o755)
            (scripts_dir / "stop_wasm_agent.sh").write_text(
                f"#!/usr/bin/env bash\nprintf 'stop\\n' >> {log_path}\n",
                encoding="utf-8",
            )
            (scripts_dir / "start_wasm_agent.sh").write_text(
                f"#!/usr/bin/env bash\nprintf 'start\\n' >> {log_path}\n",
                encoding="utf-8",
            )
            os.chmod(scripts_dir / "stop_wasm_agent.sh", 0o755)
            os.chmod(scripts_dir / "start_wasm_agent.sh", 0o755)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            env["HERMES_WASM_AGENT_PLUGIN_DIR"] = str(plugin_dir)
            env["HERMES_CLONE_MANAGER_SCRIPT"] = str(root / "clone_manager.py")
            (root / "clone_manager.py").write_text("# test stub\n", encoding="utf-8")

            result = subprocess.run(
                ["bash", str(HORC), "space", "restart"],
                cwd=str(root),
                env=env,
                check=False,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("horc space: restarting wasm-agent workspace", result.stdout)
            self.assertEqual(
                log_path.read_text(encoding="utf-8").splitlines(),
                ["stop", "kill-port:-k:8877/tcp", "kill-port:-k:8790/tcp", "start"],
            )

    def test_space_usage_lists_restart(self) -> None:
        result = subprocess.run(
            ["bash", str(HORC), "space", "help"],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("horc space restart", result.stdout)


if __name__ == "__main__":
    unittest.main()
