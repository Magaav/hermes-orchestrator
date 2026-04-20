from __future__ import annotations

import http.client
import json
import sys
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui_gateway.app import (
    FleetGatewayHandler,
    FleetGatewayServer,
    GatewayContext,
)
from ui_gateway.settings import GatewaySettings


FAKE_SCRIPT = r'''#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
action = args[0] if args else ""
name = "orchestrator"
for idx, value in enumerate(args):
    if value == "--name" and idx + 1 < len(args):
        name = args[idx + 1]

if action == "status":
    print(json.dumps({
        "ok": True,
        "action": "status",
        "clone_name": name,
        "runtime_type": "container",
        "state_mode": "fresh",
        "container_state": {"running": True, "status": "running"},
        "log_file": f"/tmp/{name}/management.log",
        "runtime_log_file": f"/tmp/{name}/runtime.log",
        "attention_log_file": f"/tmp/{name}/attention.log",
    }))
elif action in {"start", "stop"}:
    print(json.dumps({"ok": True, "action": action, "clone_name": name}))
else:
    print(json.dumps({"ok": False, "error": "unsupported"}))
    raise SystemExit(1)
'''


class GatewayActionsHttpTests(unittest.TestCase):
    def test_post_actions_restart_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts" / "clone").mkdir(parents=True)
            (root / "apps" / "wasm-ui").mkdir(parents=True)
            (root / "agents" / "envs").mkdir(parents=True)
            (root / "agents" / "nodes" / "orchestrator").mkdir(parents=True)
            (root / "logs" / "nodes" / "orchestrator").mkdir(parents=True)
            (root / "logs" / "attention" / "nodes" / "orchestrator").mkdir(parents=True)

            (root / "apps" / "wasm-ui" / "index.html").write_text("ok", encoding="utf-8")
            (root / "agents" / "envs" / "orchestrator.env").write_text("x=1\n", encoding="utf-8")

            script_path = root / "scripts" / "clone" / "clone_manager.py"
            script_path.write_text(FAKE_SCRIPT, encoding="utf-8")

            settings = GatewaySettings(
                host="127.0.0.1",
                port=0,
                repo_root=root,
                clone_manager_script=script_path,
                python_bin=sys.executable,
                agents_root=root / "agents",
                logs_root=root / "logs",
                node_logs_root=root / "logs" / "nodes",
                attention_logs_root=root / "logs" / "attention" / "nodes",
                node_activity_root=root / "logs" / "nodes" / "activities",
                guard_logs_root=root / "logs" / "guard",
                ui_root=root / "apps" / "wasm-ui",
                api_token="",
                experimental=True,
                poll_interval_sec=10.0,
                max_tail_lines=1500,
                read_limit_per_minute=100,
                write_limit_per_minute=20,
            )

            context = GatewayContext(settings)
            context.start()
            server = FleetGatewayServer((settings.host, settings.port), FleetGatewayHandler, context)
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
            thread.start()

            try:
                host, port = server.server_address
                conn = http.client.HTTPConnection(host, port, timeout=5)
                conn.request(
                    "POST",
                    "/api/fleet/nodes/orchestrator/actions",
                    body=json.dumps({"action": "restart"}),
                    headers={"Content-Type": "application/json"},
                )
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                conn.close()

                self.assertEqual(response.status, 200)
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["result"]["request"]["node"], "orchestrator")
                self.assertEqual(payload["result"]["request"]["action"], "restart")
            finally:
                server.shutdown()
                server.server_close()
                context.shutdown()
                thread.join(timeout=2)
                time.sleep(0.05)

    def test_capabilities_without_auth_and_nodes_with_auth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts" / "clone").mkdir(parents=True)
            (root / "apps" / "wasm-ui").mkdir(parents=True)
            (root / "agents" / "envs").mkdir(parents=True)
            (root / "agents" / "nodes" / "orchestrator").mkdir(parents=True)
            (root / "logs" / "nodes" / "orchestrator").mkdir(parents=True)
            (root / "logs" / "attention" / "nodes" / "orchestrator").mkdir(parents=True)

            (root / "apps" / "wasm-ui" / "index.html").write_text("ok", encoding="utf-8")
            (root / "agents" / "envs" / "orchestrator.env").write_text("x=1\n", encoding="utf-8")

            script_path = root / "scripts" / "clone" / "clone_manager.py"
            script_path.write_text(FAKE_SCRIPT, encoding="utf-8")

            settings = GatewaySettings(
                host="127.0.0.1",
                port=0,
                repo_root=root,
                clone_manager_script=script_path,
                python_bin=sys.executable,
                agents_root=root / "agents",
                logs_root=root / "logs",
                node_logs_root=root / "logs" / "nodes",
                attention_logs_root=root / "logs" / "attention" / "nodes",
                node_activity_root=root / "logs" / "nodes" / "activities",
                guard_logs_root=root / "logs" / "guard",
                ui_root=root / "apps" / "wasm-ui",
                api_token="test-token",
                experimental=True,
                poll_interval_sec=10.0,
                max_tail_lines=1500,
                read_limit_per_minute=100,
                write_limit_per_minute=20,
            )

            context = GatewayContext(settings)
            context.start()
            server = FleetGatewayServer((settings.host, settings.port), FleetGatewayHandler, context)
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
            thread.start()

            try:
                host, port = server.server_address
                conn = http.client.HTTPConnection(host, port, timeout=5)

                conn.request("GET", "/api/fleet/capabilities")
                resp_caps = conn.getresponse()
                payload_caps = json.loads(resp_caps.read().decode("utf-8"))
                self.assertEqual(resp_caps.status, 200)
                self.assertTrue(payload_caps["capabilities"]["core"]["auth_required"])

                conn.request("GET", "/api/fleet/nodes")
                resp_nodes_unauth = conn.getresponse()
                self.assertEqual(resp_nodes_unauth.status, 401)
                resp_nodes_unauth.read()

                conn.request(
                    "GET",
                    "/api/fleet/nodes",
                    headers={"Authorization": "Bearer test-token"},
                )
                resp_nodes_auth = conn.getresponse()
                payload_nodes_auth = json.loads(resp_nodes_auth.read().decode("utf-8"))
                self.assertEqual(resp_nodes_auth.status, 200)
                self.assertTrue(payload_nodes_auth["ok"])

                conn.request("GET", "/api/fleet/stream?token=test-token")
                resp_stream = conn.getresponse()
                self.assertEqual(resp_stream.status, 200)
                self.assertIn("text/event-stream", resp_stream.getheader("Content-Type", ""))
                resp_stream.close()
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                context.shutdown()
                thread.join(timeout=2)
                time.sleep(0.05)

    def test_guard_and_activity_routes_return_log_backed_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts" / "clone").mkdir(parents=True)
            (root / "apps" / "wasm-ui").mkdir(parents=True)
            (root / "agents" / "envs").mkdir(parents=True)
            (root / "agents" / "nodes" / "orchestrator").mkdir(parents=True)
            (root / "logs" / "nodes" / "orchestrator").mkdir(parents=True)
            (root / "logs" / "nodes" / "activities").mkdir(parents=True)
            (root / "logs" / "attention" / "nodes" / "orchestrator").mkdir(parents=True)
            (root / "logs" / "guard").mkdir(parents=True)

            (root / "apps" / "wasm-ui" / "index.html").write_text("ok", encoding="utf-8")
            (root / "agents" / "envs" / "orchestrator.env").write_text("x=1\n", encoding="utf-8")
            (root / "scripts" / "clone" / "clone_manager.py").write_text(FAKE_SCRIPT, encoding="utf-8")

            (root / "logs" / "guard" / "state.json").write_text(
                json.dumps(
                    {
                        "daemon_status": "running",
                        "updated_at": "2026-04-18T12:00:00Z",
                        "config": {"poll_interval_sec": 10.0, "retry_ceiling": 3},
                        "summary": {
                            "total_nodes": 1,
                            "healthy_nodes": 0,
                            "warned_nodes": 1,
                            "remediated_nodes": 0,
                            "cooldown_nodes": 0,
                            "retry_exhausted_nodes": 0,
                        },
                        "nodes": {
                            "orchestrator": {
                                "node": "orchestrator",
                                "decision": "warned",
                                "symptoms": ["attention-spike"],
                                "remediation_action": "none",
                                "remediation_result": "notify-only",
                                "retry_count": 0,
                                "cooldown_until": "",
                                "updated_at": "2026-04-18T12:00:00Z",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "logs" / "guard" / "runs.jsonl").write_text(
                json.dumps(
                    {
                        "ts": "2026-04-18T12:00:00Z",
                        "cycle_id": "guard-20260418T120000Z",
                        "node": "orchestrator",
                        "symptoms": ["attention-spike"],
                        "decision": "warned",
                        "remediation_action": "none",
                        "remediation_result": "notify-only",
                        "retry_count": 0,
                        "retry_ceiling": 3,
                        "cooldown_until": "",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "logs" / "nodes" / "activities" / "orchestrator.jsonl").write_text(
                json.dumps(
                    {
                        "id": "act-1",
                        "ts": "2026-04-18T12:01:00Z",
                        "node": "orchestrator",
                        "agent_identity": "orchestrator",
                        "interaction_source": "human",
                        "cycle_outcome": "completed",
                        "last_activity_desc": "Answered a user deployment check",
                        "message_preview": "status?",
                        "response_preview": "all green",
                        "tool_usage": {"tool_count": 1, "tool_names": ["shell"]},
                        "summary_text": "source=human | outcome=completed",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            settings = GatewaySettings(
                host="127.0.0.1",
                port=0,
                repo_root=root,
                clone_manager_script=root / "scripts" / "clone" / "clone_manager.py",
                python_bin=sys.executable,
                agents_root=root / "agents",
                logs_root=root / "logs",
                node_logs_root=root / "logs" / "nodes",
                attention_logs_root=root / "logs" / "attention" / "nodes",
                node_activity_root=root / "logs" / "nodes" / "activities",
                guard_logs_root=root / "logs" / "guard",
                ui_root=root / "apps" / "wasm-ui",
                api_token="",
                experimental=True,
                poll_interval_sec=10.0,
                max_tail_lines=1500,
                read_limit_per_minute=100,
                write_limit_per_minute=20,
            )

            context = GatewayContext(settings)
            context.start()
            server = FleetGatewayServer((settings.host, settings.port), FleetGatewayHandler, context)
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
            thread.start()

            try:
                host, port = server.server_address
                conn = http.client.HTTPConnection(host, port, timeout=5)

                conn.request("GET", "/api/fleet/guard/status")
                resp_guard = conn.getresponse()
                payload_guard = json.loads(resp_guard.read().decode("utf-8"))
                self.assertEqual(resp_guard.status, 200)
                self.assertEqual(payload_guard["guard"]["daemon_status"], "running")
                self.assertEqual(payload_guard["guard"]["nodes"]["orchestrator"]["decision"], "warned")

                conn.request("GET", "/api/fleet/nodes/orchestrator/guard?limit=4")
                resp_node_guard = conn.getresponse()
                payload_node_guard = json.loads(resp_node_guard.read().decode("utf-8"))
                self.assertEqual(resp_node_guard.status, 200)
                self.assertEqual(payload_node_guard["guard"]["summary"]["decision"], "warned")
                self.assertEqual(len(payload_node_guard["guard"]["records"]), 1)

                conn.request("GET", "/api/fleet/nodes/orchestrator/activity?limit=4")
                resp_activity = conn.getresponse()
                payload_activity = json.loads(resp_activity.read().decode("utf-8"))
                self.assertEqual(resp_activity.status, 200)
                self.assertEqual(len(payload_activity["activity"]), 1)
                self.assertEqual(payload_activity["activity"][0]["interaction_source"], "human")
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                context.shutdown()
                thread.join(timeout=2)
                time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
