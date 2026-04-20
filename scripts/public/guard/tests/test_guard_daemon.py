from __future__ import annotations

import json
import sys
from pathlib import Path
import tempfile
import unittest
import os
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guard_daemon.app import GuardDaemon
from guard_daemon.settings import GuardSettings


class FakeClient:
    def __init__(self, statuses: dict[str, dict], restart_ok: bool = True) -> None:
        self.statuses = statuses
        self.restart_ok = restart_ok
        self.restart_calls: list[str] = []

    def status(self, node: str) -> dict:
        return dict(self.statuses[node])

    def restart(self, node: str) -> dict:
        self.restart_calls.append(node)
        if not self.restart_ok:
            raise RuntimeError("restart boom")
        return {"stop": {"ok": True}, "start": {"ok": True}}


class GuardDaemonTests(unittest.TestCase):
    def _settings(self, root: Path) -> GuardSettings:
        return GuardSettings(
            repo_root=root,
            clone_manager_script=root / "scripts" / "public" / "clone" / "clone_manager.py",
            python_bin=sys.executable,
            agents_root=root / "agents",
            logs_root=root / "logs",
            node_logs_root=root / "logs" / "nodes",
            attention_logs_root=root / "logs" / "attention" / "nodes",
            node_activity_root=root / "logs" / "nodes" / "activities",
            guard_logs_root=root / "logs" / "guard",
            poll_interval_sec=10.0,
            restart_cooldown_sec=60.0,
            retry_ceiling=2,
            stall_timeout_sec=30.0,
            attention_warn_threshold=3,
            discord_webhook_url="https://example.test/webhook",
        )

    def _prepare_root(self, root: Path, node: str = "orchestrator") -> None:
        (root / "scripts" / "public" / "clone").mkdir(parents=True)
        (root / "scripts" / "public" / "clone" / "clone_manager.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        (root / "agents" / "envs").mkdir(parents=True)
        (root / "agents" / "nodes" / node).mkdir(parents=True)
        (root / "logs" / "nodes" / node / "hermes").mkdir(parents=True)
        (root / "logs" / "attention" / "nodes" / node).mkdir(parents=True)
        (root / "logs" / "nodes" / "activities").mkdir(parents=True)
        (root / "agents" / "envs" / f"{node}.env").write_text("NODE_STATE=1\n", encoding="utf-8")

    def test_healthy_cycle_writes_logs_without_remediation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_root(root)
            runtime_log = root / "logs" / "nodes" / "orchestrator" / "runtime.log"
            runtime_log.write_text("[2026-04-18T00:00:00Z] runtime ok\n", encoding="utf-8")

            alerts: list[dict] = []
            daemon = GuardDaemon(
                self._settings(root),
                client=FakeClient(
                    {
                        "orchestrator": {
                            "ok": True,
                            "container_state": {"running": True, "status": "running"},
                            "required_mounts_ok": True,
                            "runtime_log_file": str(runtime_log),
                            "attention_log_file": str(root / "logs" / "attention" / "nodes" / "orchestrator" / "warning-plus.log"),
                        }
                    }
                ),
                alert_sender=lambda _url, payload: (alerts.append(payload) or True, "queued"),
            )

            snapshot = daemon.run_once()

            self.assertEqual(snapshot["summary"]["healthy_nodes"], 1)
            self.assertEqual(snapshot["summary"]["remediated_nodes"], 0)
            self.assertEqual(alerts, [])

            runs = (root / "logs" / "guard" / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(runs), 1)
            record = json.loads(runs[0])
            self.assertEqual(record["decision"], "healthy")

    def test_stalled_node_triggers_one_restart_and_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_root(root)
            runtime_log = root / "logs" / "nodes" / "orchestrator" / "runtime.log"
            runtime_log.write_text("[2026-04-18T00:00:00Z] stale runtime\n", encoding="utf-8")
            stale_ts = time.time() - 120
            os.utime(runtime_log, (stale_ts, stale_ts))

            alerts: list[dict] = []
            client = FakeClient(
                {
                    "orchestrator": {
                        "ok": True,
                        "container_state": {"running": True, "status": "running"},
                        "required_mounts_ok": True,
                        "runtime_log_file": str(runtime_log),
                        "attention_log_file": str(root / "logs" / "attention" / "nodes" / "orchestrator" / "warning-plus.log"),
                    }
                }
            )
            settings = self._settings(root)
            settings = GuardSettings(**{**settings.__dict__, "stall_timeout_sec": 10.0})

            daemon = GuardDaemon(
                settings,
                client=client,
                alert_sender=lambda _url, payload: (alerts.append(payload) or True, "queued"),
            )

            snapshot = daemon.run_once()
            node = snapshot["nodes"]["orchestrator"]

            self.assertEqual(client.restart_calls, ["orchestrator"])
            self.assertEqual(node["decision"], "restarted")
            self.assertEqual(node["retry_count"], 1)
            self.assertTrue(node["cooldown_until"])
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0]["event_type"], "remediation_started")

    def test_retry_ceiling_prevents_additional_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_root(root)
            runtime_log = root / "logs" / "nodes" / "orchestrator" / "runtime.log"
            runtime_log.write_text("[2026-04-18T00:00:00Z] runtime down\n", encoding="utf-8")

            previous_state = {
                "daemon_status": "running",
                "updated_at": "2026-04-18T00:00:00Z",
                "last_cycle_id": "guard-old",
                "summary": {},
                "nodes": {
                    "orchestrator": {
                        "node": "orchestrator",
                        "decision": "restart-failed",
                        "retry_count": 2,
                        "retry_exhausted": False,
                        "cooldown_until": "",
                        "last_alert_key": "",
                    }
                },
            }
            guard_root = root / "logs" / "guard"
            guard_root.mkdir(parents=True, exist_ok=True)
            (guard_root / "state.json").write_text(json.dumps(previous_state), encoding="utf-8")

            alerts: list[dict] = []
            client = FakeClient(
                {
                    "orchestrator": {
                        "ok": True,
                        "container_state": {"running": False, "status": "exited"},
                        "required_mounts_ok": True,
                        "runtime_log_file": str(runtime_log),
                        "attention_log_file": str(root / "logs" / "attention" / "nodes" / "orchestrator" / "warning-plus.log"),
                    }
                }
            )

            daemon = GuardDaemon(
                self._settings(root),
                client=client,
                alert_sender=lambda _url, payload: (alerts.append(payload) or True, "queued"),
            )

            snapshot = daemon.run_once()
            node = snapshot["nodes"]["orchestrator"]

            self.assertEqual(client.restart_calls, [])
            self.assertEqual(node["decision"], "retry-exhausted")
            self.assertTrue(node["retry_exhausted"])
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0]["event_type"], "retry_ceiling_reached")

    def test_attention_spike_warns_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prepare_root(root)
            runtime_log = root / "logs" / "nodes" / "orchestrator" / "runtime.log"
            runtime_log.write_text("[2026-04-18T00:00:00Z] runtime ok\n", encoding="utf-8")
            attention_log = root / "logs" / "attention" / "nodes" / "orchestrator" / "warning-plus.log"
            attention_log.write_text("\n".join(["warn"] * 5) + "\n", encoding="utf-8")

            alerts: list[dict] = []
            client = FakeClient(
                {
                    "orchestrator": {
                        "ok": True,
                        "container_state": {"running": True, "status": "running"},
                        "required_mounts_ok": True,
                        "runtime_log_file": str(runtime_log),
                        "attention_log_file": str(attention_log),
                    }
                }
            )

            daemon = GuardDaemon(
                self._settings(root),
                client=client,
                alert_sender=lambda _url, payload: (alerts.append(payload) or True, "queued"),
            )

            snapshot = daemon.run_once()
            node = snapshot["nodes"]["orchestrator"]

            self.assertEqual(client.restart_calls, [])
            self.assertEqual(node["decision"], "warned")
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0]["event_type"], "node_unhealthy_no_remediation")


if __name__ == "__main__":
    unittest.main()
