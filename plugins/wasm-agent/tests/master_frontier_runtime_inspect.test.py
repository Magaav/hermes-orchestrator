#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import runtime_actions, runtime_inspect


class RuntimeInspectTests(unittest.TestCase):
    def contract(self) -> dict:
        return {
            "route_id": "route.a",
            "caps": ["runtime.inspect"],
            "entities": [{"id": "entity-a", "kind": "agent"}],
        }

    def test_registration_requires_route_capability(self) -> None:
        self.assertEqual(len(runtime_inspect.action_registration(self.contract())), 2)
        self.assertEqual(runtime_inspect.action_registration({**self.contract(), "caps": []}), [])

    def test_host_authority_is_injected_not_read_from_arguments(self) -> None:
        request = {
            "name": runtime_actions.SNAPSHOT_GET,
            "arguments": {"route_id": "route.a", "entity_id": "entity-a"},
        }
        with patch.object(runtime_actions, "execute", return_value={"ok": True}) as execute:
            result = runtime_inspect.execute_requested_action(
                request,
                contract=self.contract(),
                user_id="authenticated-user",
                db_path=Path("/host/runtime.sqlite3"),
                now_ms=123,
            )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(execute.call_args.kwargs["authority"]["user_id"], "authenticated-user")
        self.assertEqual(execute.call_args.kwargs["db_path"], Path("/host/runtime.sqlite3"))

    def test_request_envelope_and_action_errors_are_typed(self) -> None:
        invalid = runtime_inspect.execute_requested_action(
            {"name": runtime_actions.SNAPSHOT_GET, "arguments": {}, "user_id": "injected"},
            contract=self.contract(), user_id="user-a", db_path=Path("missing"), now_ms=1,
        )
        self.assertEqual(invalid, {"ok": False, "code": "runtime_action_request_invalid"})
        denied = runtime_inspect.execute_requested_action(
            {"name": runtime_actions.SNAPSHOT_GET, "arguments": {"route_id": "route.b", "entity_id": "entity-a"}},
            contract=self.contract(), user_id="user-a", db_path=Path("missing"), now_ms=1,
        )
        self.assertEqual(denied, {"ok": False, "code": "runtime_action_route_denied"})


if __name__ == "__main__":
    unittest.main()
