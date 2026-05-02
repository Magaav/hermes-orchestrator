from __future__ import annotations

import http.client
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from threading import Thread

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui_gateway.app import FleetGatewayHandler, FleetGatewayServer, GatewayContext
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
else:
    print(json.dumps({"ok": False, "error": "unsupported"}))
    raise SystemExit(1)
'''


def _write_dashboard_helper(root: Path) -> None:
    source = (
        Path(__file__).resolve().parents[4]
        / "hackaton-hermes-dashboard"
        / "plugin"
        / "dashboard"
        / "dashboard_metrics.py"
    )
    target = root / "hackaton-hermes-dashboard" / "plugin" / "dashboard" / "dashboard_metrics.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    rewritten = source.read_text(encoding="utf-8").replace(
        'PARACELSUS_DATA_ROOT = Path("/local/datas/paracelsus")',
        f'PARACELSUS_DATA_ROOT = Path({str(root / "datas" / "paracelsus")!r})',
    )
    target.write_text(rewritten, encoding="utf-8")


def _seed_state_db(node_root: Path, rows: list[dict[str, object]]) -> None:
    state_path = node_root / ".hermes" / "state.db"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(state_path)
    try:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                source TEXT,
                message_count INTEGER,
                tool_call_count INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                started_at REAL,
                ended_at REAL,
                estimated_cost_usd REAL,
                actual_cost_usd REAL,
                api_call_count INTEGER
            )
            """
        )
        for row in rows:
            conn.execute(
                """
                INSERT INTO sessions (
                    id, source, message_count, tool_call_count, input_tokens, output_tokens,
                    started_at, ended_at, estimated_cost_usd, actual_cost_usd, api_call_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row.get("source", "discord"),
                    row.get("message_count", 0),
                    row.get("tool_call_count", 0),
                    row.get("input_tokens", 0),
                    row.get("output_tokens", 0),
                    row.get("started_at", 0.0),
                    row.get("ended_at", 0.0),
                    row.get("estimated_cost_usd", 0.0),
                    row.get("actual_cost_usd", 0.0),
                    row.get("api_call_count", 0),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_sessions_json(node_root: Path, payload: dict[str, object]) -> None:
    path = node_root / ".hermes" / "sessions" / "sessions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_acl(node_root: Path, yaml_text: str) -> None:
    path = (
        node_root
        / "workspace"
        / "plugins"
        / "discord-slash-commands"
        / "cache"
        / "governance"
        / "hooks"
        / "channel_acl"
        / "config.yaml"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text, encoding="utf-8")


def _seed_colmeio_db(root: Path) -> None:
    db_path = root / "datas" / "colmeio" / "colmeio_db.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE trigger_tb (id INTEGER PRIMARY KEY, trigger_name TEXT)")
        conn.execute("CREATE TABLE skill_tb (id INTEGER PRIMARY KEY, skill_name TEXT, skill_action TEXT)")
        conn.execute(
            """
            CREATE TABLE user_metrics_tb (
                id INTEGER PRIMARY KEY,
                op_id TEXT,
                triggered_at_utc TEXT,
                trigger_id INTEGER,
                skill_id INTEGER,
                actor_user_id TEXT,
                duration_ms INTEGER,
                created_at_utc TEXT
            )
            """
        )
        conn.executemany("INSERT INTO trigger_tb (id, trigger_name) VALUES (?, ?)", [(1, "text_command"), (2, "slash_command")])
        conn.executemany(
            "INSERT INTO skill_tb (id, skill_name, skill_action) VALUES (?, ?, ?)",
            [(1, "colmeio-lista-de-faltas", "adicionar")],
        )
        conn.executemany(
            """
            INSERT INTO user_metrics_tb (
                id, op_id, triggered_at_utc, trigger_id, skill_id, actor_user_id, duration_ms, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "op-1", "2026-04-25T10:00:00Z", 1, 1, "system", 20, "2026-04-25T10:00:20Z"),
                (2, "op-2", "2026-04-25T11:00:00Z", 2, 1, "system", 30, "2026-04-25T11:00:30Z"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _seed_paracelsus_db(root: Path) -> None:
    data_root = root / "datas" / "paracelsus"
    data_root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data_root / "paracelsus_db.sqlite3")
    try:
        conn.execute(
            """
            CREATE TABLE "scientific-paper-meta-analysis_tb" (
                id TEXT PRIMARY KEY,
                http_link TEXT NOT NULL,
                paper_title TEXT NOT NULL,
                paper_content_string TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO "scientific-paper-meta-analysis_tb" (id, http_link, paper_title, paper_content_string)
            VALUES (?, ?, ?, ?)
            """,
            (
                "1",
                "https://doi.org/10.1000/example",
                "Example Paper",
                "<!-- paracelsus-meta: {\"title\": \"Example Paper\", \"http_link\": \"https://doi.org/10.1000/example\"} -->\n# Example Paper",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    (data_root / "files" / "1").mkdir(parents=True, exist_ok=True)
    (data_root / "scientific-paper-meta-analysis-events.jsonl").write_text(
        json.dumps(
            {
                "event": "run_summary",
                "ts": "2026-04-26T00:00:00Z",
                "query": "GLP-1 agonists",
                "mode": "search",
                "cache_mode": "mixed",
                "cache_hits": 2,
                "cache_misses": 1,
                "asset_downloads": 3,
                "papers_returned": 4,
            }
        )
        + "\n",
        encoding="utf-8",
    )


class DashboardHttpTests(unittest.TestCase):
    def test_dashboard_routes_filter_nodes_and_channels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts" / "clone").mkdir(parents=True)
            (root / "apps" / "wasm-ui").mkdir(parents=True)
            (root / "agents" / "envs").mkdir(parents=True)
            (root / "logs" / "nodes" / "orchestrator").mkdir(parents=True)
            (root / "logs" / "attention" / "nodes" / "orchestrator").mkdir(parents=True)
            (root / "apps" / "wasm-ui" / "index.html").write_text("ok", encoding="utf-8")
            (root / "scripts" / "clone" / "clone_manager.py").write_text(FAKE_SCRIPT, encoding="utf-8")
            _write_dashboard_helper(root)

            (root / "agents" / "envs" / "colmeio.env").write_text("PLUGIN_DASHBOARD=true\n", encoding="utf-8")
            (root / "agents" / "envs" / "paracelsus.env").write_text("PLUGIN_DASHBOARD=true\n", encoding="utf-8")
            (root / "agents" / "envs" / "orchestrator.env").write_text("PLUGIN_DASHBOARD=false\n", encoding="utf-8")

            colmeio_root = root / "agents" / "nodes" / "colmeio"
            paracelsus_root = root / "agents" / "nodes" / "paracelsus"
            orchestrator_root = root / "agents" / "nodes" / "orchestrator"
            colmeio_root.mkdir(parents=True)
            paracelsus_root.mkdir(parents=True)
            orchestrator_root.mkdir(parents=True)

            _seed_acl(
                colmeio_root,
                """
channels:
  "1487099467726328038":
    mode: condicionado
    label: loja1
    allowed_commands: [faltas]
  "1487099552636080201":
    mode: condicionado
    label: loja2
    allowed_commands: [faltas]
  "1488175722932736071":
    mode: livre
                """.strip(),
            )
            _seed_acl(
                paracelsus_root,
                """
channels:
  "1487099467726328038":
    mode: condicionado
    label: loja1
    allowed_commands: [faltas]
  "1497340589191204898":
    mode: condicionado
    label: scientific-paper-meta-analysis
    allowed_commands: [scientific-paper-meta-analysis]
                """.strip(),
            )

            _seed_state_db(
                colmeio_root,
                [
                    {
                        "id": "c-1",
                        "message_count": 4,
                        "tool_call_count": 1,
                        "input_tokens": 120,
                        "output_tokens": 40,
                        "started_at": 1777161000.0,
                        "ended_at": 1777161300.0,
                    },
                    {
                        "id": "c-2",
                        "message_count": 6,
                        "tool_call_count": 2,
                        "input_tokens": 220,
                        "output_tokens": 80,
                        "started_at": 1777162000.0,
                        "ended_at": 1777162300.0,
                    },
                ],
            )
            _seed_sessions_json(
                colmeio_root,
                {
                    "agent:main:discord:thread:t1:t1:user1": {
                        "session_id": "c-1",
                        "display_name": "loja1 thread",
                        "origin": {"chat_id": "thread-1", "chat_id_alt": "1487099467726328038", "user_name": "Ana"},
                    },
                    "agent:main:discord:thread:t2:t2:user2": {
                        "session_id": "c-2",
                        "display_name": "loja2 thread",
                        "origin": {"chat_id": "thread-2", "chat_id_alt": "1487099552636080201", "user_name": "Bia"},
                    },
                },
            )

            _seed_state_db(
                paracelsus_root,
                [
                    {
                        "id": "p-1",
                        "message_count": 9,
                        "tool_call_count": 3,
                        "input_tokens": 900,
                        "output_tokens": 300,
                        "started_at": 1777163000.0,
                        "ended_at": 1777163600.0,
                    }
                ],
            )
            _seed_sessions_json(
                paracelsus_root,
                {
                    "agent:main:discord:group:1497340589191204898:user1": {
                        "session_id": "p-1",
                        "display_name": "scientific channel",
                        "origin": {"chat_id": "1497340589191204898", "user_name": "Victor"},
                    }
                },
            )

            _seed_colmeio_db(root)
            _seed_paracelsus_db(root)

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

                conn.request("GET", "/api/fleet/dashboard/nodes")
                resp_nodes = conn.getresponse()
                payload_nodes = json.loads(resp_nodes.read().decode("utf-8"))
                self.assertEqual(resp_nodes.status, 200)
                self.assertEqual(payload_nodes["count"], 2)
                self.assertEqual({item["node"] for item in payload_nodes["nodes"]}, {"colmeio", "paracelsus"})

                conn.request("GET", "/api/fleet/dashboard/nodes/colmeio/channels")
                resp_colmeio = conn.getresponse()
                payload_colmeio = json.loads(resp_colmeio.read().decode("utf-8"))
                self.assertEqual(resp_colmeio.status, 200)
                self.assertEqual(
                    {item["channel_id"] for item in payload_colmeio["channels"]},
                    {"1487099467726328038", "1487099552636080201"},
                )

                conn.request("GET", "/api/fleet/dashboard/nodes/paracelsus/channels")
                resp_paracelsus = conn.getresponse()
                payload_paracelsus = json.loads(resp_paracelsus.read().decode("utf-8"))
                self.assertEqual(resp_paracelsus.status, 200)
                self.assertEqual(
                    [item["channel_id"] for item in payload_paracelsus["channels"]],
                    ["1497340589191204898"],
                )

                conn.request("GET", "/api/fleet/dashboard/nodes/paracelsus/channels/1497340589191204898")
                resp_detail = conn.getresponse()
                payload_detail = json.loads(resp_detail.read().decode("utf-8"))
                self.assertEqual(resp_detail.status, 200)
                self.assertEqual(payload_detail["channel"]["extras"]["cache"]["total_papers"], 1)
                self.assertEqual(payload_detail["channel"]["session_count"], 1)

                conn.request("GET", "/api/fleet/dashboard/nodes/paracelsus/channels/1497340589191204898/series?window=7d")
                resp_series = conn.getresponse()
                payload_series = json.loads(resp_series.read().decode("utf-8"))
                self.assertEqual(resp_series.status, 200)
                self.assertEqual(payload_series["series"]["window"], "7d")
                self.assertEqual(len(payload_series["series"]["points"]), 7)

                conn.request("GET", "/api/fleet/dashboard/nodes/paracelsus/channels/1497340589191204898/series?window=24h")
                resp_series_24h = conn.getresponse()
                payload_series_24h = json.loads(resp_series_24h.read().decode("utf-8"))
                self.assertEqual(resp_series_24h.status, 200)
                self.assertEqual(payload_series_24h["series"]["window"], "24h")
                self.assertEqual(len(payload_series_24h["series"]["points"]), 24)

                conn.request("GET", "/api/fleet/dashboard/nodes/paracelsus/channels/1497340589191204898/series?window=30d")
                resp_series_30d = conn.getresponse()
                payload_series_30d = json.loads(resp_series_30d.read().decode("utf-8"))
                self.assertEqual(resp_series_30d.status, 200)
                self.assertEqual(payload_series_30d["series"]["window"], "30d")
                self.assertEqual(len(payload_series_30d["series"]["points"]), 30)
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                context.shutdown()
                thread.join(timeout=2)
                time.sleep(0.05)
