from __future__ import annotations

import json
import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui_gateway.clone_manager import CloneManagerClient, CloneManagerError


FAKE_SCRIPT = r'''#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
action = args[0]
name = "orchestrator"
lines = 80
for idx, value in enumerate(args):
    if value == "--name" and idx + 1 < len(args):
        name = args[idx + 1]
    if value == "--lines" and idx + 1 < len(args):
        lines = int(args[idx + 1])

if name == "missing":
    print(json.dumps({"ok": False, "error": "node not found"}))
    raise SystemExit(1)
if name == "dockerdown":
    print(json.dumps({"ok": False, "error": "docker unavailable"}))
    raise SystemExit(1)
if name == "denied":
    print(json.dumps({"ok": False, "error": "permission denied"}))
    raise SystemExit(1)

if action == "status":
    print(json.dumps({
        "ok": True,
        "action": "status",
        "clone_name": name,
        "runtime_type": "container",
        "state_mode": "fresh",
        "container_state": {"running": True, "status": "running"}
    }))
elif action == "logs":
    print(json.dumps({
        "ok": True,
        "action": "logs",
        "clone_name": name,
        "lines": lines,
        "log_text": "[2026-01-01T00:00:00Z] ok"
    }))
elif action in {"start", "stop"}:
    print(json.dumps({"ok": True, "action": action, "clone_name": name}))
else:
    print(json.dumps({"ok": False, "error": "unsupported"}))
    raise SystemExit(1)
'''


class CloneManagerIntegrationTests(unittest.TestCase):
    def test_client_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fake_clone_manager.py"
            script.write_text(FAKE_SCRIPT)

            client = CloneManagerClient(
                script_path=script,
                python_bin=sys.executable,
                timeout_sec=5,
            )

            status = client.status("orchestrator")
            self.assertTrue(status["ok"])
            self.assertEqual(status["action"], "status")

            logs = client.logs("orchestrator", lines=120)
            self.assertTrue(logs["ok"])
            self.assertEqual(logs["action"], "logs")
            self.assertEqual(logs["lines"], 120)

            self.assertEqual(client.start("orchestrator")["action"], "start")
            self.assertEqual(client.stop("orchestrator")["action"], "stop")

    def test_client_error_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fake_clone_manager.py"
            script.write_text(FAKE_SCRIPT)

            client = CloneManagerClient(
                script_path=script,
                python_bin=sys.executable,
                timeout_sec=5,
            )

            with self.assertRaisesRegex(CloneManagerError, "node not found"):
                client.status("missing")

            with self.assertRaisesRegex(CloneManagerError, "docker unavailable"):
                client.status("dockerdown")

            with self.assertRaisesRegex(CloneManagerError, "permission denied"):
                client.status("denied")


if __name__ == "__main__":
    unittest.main()
