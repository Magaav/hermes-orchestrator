from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import clone_manager


class OrchestratorGatewayStateTests(unittest.TestCase):
    def test_process_state_discovers_live_gateway_when_pid_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clone-manager-orchestrator-state-") as tmp:
            root = Path(tmp)
            clone_root = root / "nodes" / "orchestrator"
            (clone_root / ".hermes").mkdir(parents=True, exist_ok=True)
            (clone_root / "hermes-agent").mkdir(parents=True, exist_ok=True)

            with patch.object(clone_manager, "SHARED_NODE_DATA_ROOT", root / "datas"):
                state = None
                with patch.object(clone_manager, "_discover_orchestrator_gateway_pids", return_value=[4321]):
                    state = clone_manager._orchestrator_process_state(clone_root)

                self.assertIsNotNone(state)
                self.assertTrue(state["running"])
                self.assertEqual(state["pid"], 4321)

                pid_path = clone_manager._orchestrator_pid_path(clone_root)
                self.assertTrue(pid_path.exists())
                self.assertEqual(pid_path.read_text(encoding="utf-8").strip(), "4321")

    def test_stop_gateway_kills_discovered_process_without_pid_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clone-manager-orchestrator-stop-") as tmp:
            root = Path(tmp)
            clone_root = root / "nodes" / "orchestrator"
            clone_root.mkdir(parents=True, exist_ok=True)

            state_payload = {
                "exists": True,
                "running": True,
                "status": "running",
                "pid": 4321,
                "pid_file": str(root / "datas" / "orchestrator" / "gateway.pid"),
            }

            with patch.object(clone_manager, "_orchestrator_process_state", return_value=state_payload), \
                 patch.object(clone_manager, "_orchestrator_pid_candidates", return_value=[]), \
                 patch.object(clone_manager, "_log", lambda *args, **kwargs: None), \
                 patch.object(clone_manager.time, "sleep", lambda *_args, **_kwargs: None), \
                 patch.object(clone_manager, "_pid_running", side_effect=[True, False, False, False]), \
                 patch.object(clone_manager.os, "kill") as kill_mock:
                result = clone_manager._orchestrator_stop_gateway("orchestrator", clone_root)

            self.assertEqual(result["result"], "stopped")
            self.assertEqual(result["pid"], 4321)
            kill_mock.assert_called_once_with(4321, 15)


if __name__ == "__main__":
    unittest.main()
