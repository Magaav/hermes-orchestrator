import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import authority, route_contracts, session_context  # noqa: E402
from master_frontier.v5 import completion, context, policy, task_policy, tool_stage, tools  # noqa: E402


class SessionMemoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "memory.sqlite3"
        connection = sqlite3.connect(self.db)
        connection.executescript("""
            CREATE TABLE agent_run_tb (
              run_id TEXT, turn_id TEXT, user_id TEXT, session_id TEXT,
              status TEXT, updated_at TEXT, terminal_at TEXT, final_json TEXT
            );
            CREATE TABLE agent_run_event_tb (
              run_id TEXT, user_id TEXT, session_id TEXT, type TEXT, seq INTEGER, summary TEXT
            );
        """)
        runs = [
            ("ra", "ta", "acct-a", "session-a", "2026-01-01T00:00:00Z", "private answer alpha " * 200, "remember our garden intent"),
            ("rb", "tb", "acct-a", "session-b", "2026-01-02T00:00:00Z", "private answer beta " * 200, "design compact continuity"),
            ("rx", "tx", "acct-b", "session-x", "2026-01-03T00:00:00Z", "FOREIGN SECRET", "foreign objective"),
        ]
        for run, turn, user, session, updated, answer, objective in runs:
            connection.execute(
                "INSERT INTO agent_run_tb VALUES (?,?,?,?,?,?,?,?)",
                (run, turn, user, session, "completed", updated, updated, json.dumps({"reply": answer})),
            )
            connection.execute(
                "INSERT INTO agent_run_event_tb VALUES (?,?,?,?,?,?)",
                (run, user, session, "envelope.created", 1, objective),
            )
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def connect(self):
        connection = sqlite3.connect(self.db)
        connection.row_factory = sqlite3.Row
        return connection

    def test_manifest_is_account_scoped_compact_and_body_free(self) -> None:
        manifest = session_context.load_memory_manifest(
            self.connect, user_id="acct-a", active_session_id="session-b",
        )
        serialized = json.dumps(manifest)
        self.assertEqual(manifest["intent"], "rel-continuity-v1")
        self.assertEqual(len(manifest["sessions"]), 1)
        self.assertEqual(len(manifest["sessions"]), 1)
        self.assertNotIn("session-b", json.dumps(manifest))
        self.assertNotIn("private answer", serialized)
        self.assertNotIn("FOREIGN SECRET", serialized)
        self.assertNotIn("foreign objective", serialized)
        self.assertGreater(manifest["cost"]["saved_chars"], 0)

    def test_exact_read_rejects_foreign_and_malformed_pointers(self) -> None:
        own = session_context.load_memory_manifest(
            self.connect, user_id="acct-a", active_session_id="session-a",
        )["sessions"][0]["p"]
        read = session_context.read_memory(self.connect, user_id="acct-a", pointer=own)
        self.assertTrue(read["ok"])
        self.assertNotIn("FOREIGN SECRET", json.dumps(read))
        self.assertEqual(
            session_context.read_memory(self.connect, user_id="acct-b", pointer=own)["code"],
            "session_memory_not_found",
        )
        self.assertEqual(
            session_context.read_memory(self.connect, user_id="acct-a", pointer="sm1.%not-base64")["code"],
            "session_memory_pointer_invalid",
        )

    def test_v5_projects_manifest_and_exposes_bounded_memory_tool(self) -> None:
        manifest = session_context.load_memory_manifest(
            self.connect, user_id="acct-a", active_session_id="session-a",
        )
        route = {
            "route_id": "fixture", "workspace_root": self.tmp.name,
            "caps": ["repo.read", "session.memory.read"],
            "task_contract": {"request_class": "conversation"},
            "session_memory": manifest,
        }
        names = [item["name"] for item in policy.descriptors_for(route)]
        self.assertIn("memory", names)
        memory_descriptor = next(item for item in policy.descriptors_for(route) if item["name"] == "memory")
        self.assertEqual(
            memory_descriptor["input_schema"]["properties"]["pointer"]["enum"],
            [item["p"] for item in manifest["sessions"]],
        )
        self.assertFalse(task_policy.direct_completion(route))
        projected = context.payload("recall", route, {"steps": [], "loop_counters": {}})
        self.assertEqual(projected["session_memory"], manifest)
        called = []
        result = tools.execute(
            "memory", {"pointer": manifest["sessions"][0]["p"], "limit": 2}, route,
            invoke=lambda name, args: called.append((name, args)) or {"ok": True},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(called[0][0], "session.memory.read")
        self.assertEqual(authority.required_capability("memory"), "session.memory.read")

        runtime_route = {
            **route,
            "caps": ["runtime.inspect", "session.memory.read"],
            "task_contract": {"request_class": "runtime_inspection"},
            "entities": [
                {"id": "live-a", "kind": "application"},
                {"id": "memory-a", "kind": "summary-first-session-memory"},
            ],
        }
        self.assertEqual(
            [item["name"] for item in policy.descriptors_for(runtime_route)],
            ["memory", "inspect"],
        )
        runtime_projected = context.payload("recall", runtime_route, {"steps": [], "loop_counters": {}})
        self.assertEqual(runtime_projected["runtime_entities"][0]["id"], "memory-a")

        declared = {
            "entities": [
                {"id": "generic", "kind": "scoped-run-history", "match_terms": ["avatar chat"]},
                {"id": "memory", "kind": "summary-first-session-memory", "match_terms": ["cross-session memory"]},
            ],
        }
        resolved = route_contracts.resolve_entity("Use cross-session memory in avatar chat", declared)
        self.assertEqual(resolved["id"], "memory")
        runtime_route["resolved_entity"] = resolved
        self.assertEqual(tool_stage.active_names(runtime_route, {}, ["memory", "inspect"]), ["memory"])

        state = {
            "root_objective": "What shared symbol and relationship intent did I establish?",
            "steps": [{
                "tool": "memory", "status": "completed",
                "result": {"ok": True, "turns": [{
                    "objective": "Our shared symbol is amber-lantern-731",
                    "answer": "It preserves relationship continuity and intent",
                }]},
            }],
        }
        self.assertEqual(completion.assess(state, runtime_route)["status"], "sufficient")


if __name__ == "__main__":
    unittest.main()
