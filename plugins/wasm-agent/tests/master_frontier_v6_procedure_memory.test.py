from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import adapters, kernel, procedure_memory  # noqa: E402


class Store:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "memory.sqlite3"

    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def close(self) -> None:
        self.temp.cleanup()


ROUTE = {
    "route_id": "fixture.client", "owner": "fixture", "workspace_root": "/workspace",
    "allowed_read_roots": ["/workspace"], "caps": ["client.ui.inspect"],
}
TOPOLOGY = {"active_execution_realm": "native_windows", "selected_client_id": "windows-a"}
CAPABILITY_ID = "client.windows.desktop.windows.list"


def make_agent(
    answer: str = "2 visible Windows windows: WASM Agent; Notepad",
    *, proof: str = "windows.desktop.top_level_windows",
) -> kernel.Kernel:
    agent = kernel.Kernel(
        authorities={"client.ui.inspect"}, completion_requirements={"authority:client.ui.inspect"},
    )
    capability = next(item for item in adapters.live_client({
        "runtime_type": "electron", "client_id": "windows-a",
        "capabilities": ["run_hot_operation"],
    }) if item["id"] == CAPABILITY_ID)
    capability["proof"] = [proof]
    agent.register(capability, lambda _cap, _operation: {
        "ok": True, "state": "completed", "observed": {"answer": answer},
        "proof": [proof],
    })
    return agent


def journal(agent: kernel.Kernel) -> list[dict]:
    agent.run("What apps are open?", [{"id": "list", "cap": CAPABILITY_ID, "args": {}}])
    return agent.journal()


class ProcedureMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store()

    def tearDown(self) -> None:
        self.store.close()

    def observe(self, run_id: str, *, user: str = "u1", agent: kernel.Kernel | None = None):
        selected = agent or make_agent()
        return procedure_memory.observe_success(
            self.store.connect, user_id=user, route=ROUTE, objective="What apps are open?",
            topology=TOPOLOGY, run_id=run_id, journal=journal(selected), catalog=selected.catalog,
        )

    def test_two_distinct_successes_promote_then_exact_repeat_replays_without_provider(self) -> None:
        self.assertEqual(self.observe("run-1")["state"], "candidate")
        self.assertEqual(self.observe("run-2")["state"], "promoted")
        agent = make_agent("Fresh Windows answer.")
        procedure = procedure_memory.lookup(
            self.store.connect, user_id="u1", route=ROUTE,
            objective="What apps are open?", topology=TOPOLOGY, catalog=agent.catalog,
        )
        self.assertIsNotNone(procedure)
        replay = procedure_memory.replay(self.store.connect, procedure, agent=agent, objective="What apps are open?")
        self.assertEqual(replay["answer"], "Fresh Windows answer.")
        self.assertEqual(replay["trace"], [])

    def test_explicit_rollback_flag_disables_memory(self) -> None:
        with mock.patch.dict("os.environ", {"MF_V6_PROCEDURE_MEMORY": "0"}):
            self.assertFalse(procedure_memory.enabled())

    def test_same_run_cannot_self_calibrate(self) -> None:
        self.observe("run-1")
        self.assertEqual(self.observe("run-1")["successes"], 1)
        agent = make_agent()
        self.assertIsNone(procedure_memory.lookup(
            self.store.connect, user_id="u1", route=ROUTE,
            objective="What apps are open?", topology=TOPOLOGY, catalog=agent.catalog,
        ))

    def test_objective_account_and_topology_are_exact_scopes(self) -> None:
        self.observe("run-1")
        self.observe("run-2")
        agent = make_agent()
        for user, objective, topology in (
            ("u2", "What apps are open?", TOPOLOGY),
            ("u1", "Which apps are open?", TOPOLOGY),
            ("u1", "What apps are open?", {**TOPOLOGY, "selected_client_id": "windows-b"}),
        ):
            self.assertIsNone(procedure_memory.lookup(
                self.store.connect, user_id=user, route=ROUTE,
                objective=objective, topology=topology, catalog=agent.catalog,
            ))

    def test_whitespace_normalizes_but_case_and_paraphrases_do_not(self) -> None:
        self.observe("run-1")
        self.observe("run-2")
        agent = make_agent()
        self.assertIsNotNone(procedure_memory.lookup(
            self.store.connect, user_id="u1", route=ROUTE,
            objective="  What   apps are open?  ", topology=TOPOLOGY, catalog=agent.catalog,
        ))
        for objective in ("what apps are open?", "Which applications are running?"):
            self.assertIsNone(procedure_memory.lookup(
                self.store.connect, user_id="u1", route=ROUTE,
                objective=objective, topology=TOPOLOGY, catalog=agent.catalog,
            ))

    def test_write_or_missing_proof_never_harvests(self) -> None:
        agent = kernel.Kernel(authorities={"client.ui.control"})
        write = next(item for item in adapters.live_client({
            "runtime_type": "electron", "client_id": "windows-a",
            "capabilities": ["run_hot_operation"],
        }) if item["id"] == "client.windows.browser.cdp.default.open")
        agent.register(write, lambda _cap, _operation: {
            "ok": True, "state": "completed", "observed": {"answer": "Opened."},
            "proof": ["windows.browser.cdp.persistent.ready"],
        })
        agent.run("Open CDP", [{"id": "open", "cap": write["id"], "args": {}}])
        self.assertIsNone(procedure_memory.observe_success(
            self.store.connect, user_id="u1", route=ROUTE, objective="Open CDP",
            topology=TOPOLOGY, run_id="run-write", journal=agent.journal(), catalog=agent.catalog,
        ))

    def test_multi_operation_and_required_argument_reads_never_harvest(self) -> None:
        multi = make_agent()
        multi.run("Inspect twice", [
            {"id": "first", "cap": CAPABILITY_ID, "args": {}},
            {"id": "second", "cap": CAPABILITY_ID, "args": {}},
        ])
        self.assertIsNone(procedure_memory.observe_success(
            self.store.connect, user_id="u1", route=ROUTE, objective="Inspect twice",
            topology=TOPOLOGY, run_id="run-multi", journal=multi.journal(), catalog=multi.catalog,
        ))

        required = kernel.Kernel(authorities={"client.ui.inspect"})
        capability = {
            "id": "client.required.read", "kind": "observe", "authority": "client.ui.inspect",
            "executor": "client.required.read", "mode": "read", "terminal_result": True,
            "proof": ["required.read.proof"],
            "input": {
                "type": "object", "required": ["target"],
                "properties": {"target": {"type": "string"}}, "additionalProperties": False,
            },
        }
        required.register(capability, lambda _cap, _operation: {
            "ok": True, "state": "completed", "observed": {"answer": "Inspected."},
            "proof": ["required.read.proof"],
        })
        required.run("Inspect target", [{"id": "required", "cap": "client.required.read", "args": {"target": "x"}}])
        self.assertIsNone(procedure_memory.observe_success(
            self.store.connect, user_id="u1", route=ROUTE, objective="Inspect target",
            topology=TOPOLOGY, run_id="run-required", journal=required.journal(), catalog=required.catalog,
        ))

    def test_capability_contract_drift_prunes_before_execution(self) -> None:
        self.observe("run-1")
        self.observe("run-2")
        agent = make_agent(proof="windows.desktop.changed-proof")
        self.assertIsNone(procedure_memory.lookup(
            self.store.connect, user_id="u1", route=ROUTE,
            objective="What apps are open?", topology=TOPOLOGY, catalog=agent.catalog,
        ))

    def test_fresh_proof_failure_prunes(self) -> None:
        self.observe("run-1")
        self.observe("run-2")
        agent = make_agent()
        procedure = procedure_memory.lookup(
            self.store.connect, user_id="u1", route=ROUTE,
            objective="What apps are open?", topology=TOPOLOGY, catalog=agent.catalog,
        )
        capability = agent.catalog.get(CAPABILITY_ID)
        agent.executors[capability["executor"]] = lambda _cap, _operation: {
            "ok": True, "state": "completed", "observed": {"answer": "unsafe"}, "proof": [],
        }
        self.assertIsNone(procedure_memory.replay(
            self.store.connect, procedure, agent=agent, objective="What apps are open?",
        ))
        self.assertIsNone(procedure_memory.lookup(
            self.store.connect, user_id="u1", route=ROUTE,
            objective="What apps are open?", topology=TOPOLOGY, catalog=agent.catalog,
        ))


if __name__ == "__main__":
    unittest.main()
