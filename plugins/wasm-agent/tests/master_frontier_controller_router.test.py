#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import controller_router, run_protocol  # noqa: E402


class ControllerRouterTests(unittest.TestCase):
    def test_v6_routes_only_to_owned_v6_controller(self) -> None:
        with patch.object(controller_router.controller_v6, "execute_owned", return_value={"protocol": "v6"}) as selected, patch.object(
            controller_router.controller_v5, "execute_owned", side_effect=AssertionError("v5 must not run"),
        ):
            result = controller_router.execute(
                run_protocol.V6, object(), {}, user={"id": "u1"},
                run={"run_id": "run"}, context={"envelope": {}}, runtime={},
            )
        self.assertEqual(result, {"protocol": "v6"})
        selected.assert_called_once()

    def test_unknown_persisted_protocol_fails_closed(self) -> None:
        with self.assertRaisesRegex(run_protocol.ProtocolError, "Unknown persisted"):
            controller_router.execute("v99", object(), {}, user=None, run={}, context={}, runtime={})


if __name__ == "__main__":
    unittest.main()
