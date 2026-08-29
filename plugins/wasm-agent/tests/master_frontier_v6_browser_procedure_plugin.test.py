#!/usr/bin/env python3
from pathlib import Path
import sys
import unittest

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import browser_procedure_plugin  # noqa: E402


class BrowserProcedurePluginTests(unittest.TestCase):
    def test_requires_hot_operation_runner_and_scoped_proof(self) -> None:
        self.assertEqual(browser_procedure_plugin.capabilities(set(), client_id="c1", binding="b"), [])
        capability = browser_procedure_plugin.capabilities({"run_hot_operation"}, client_id="c1", binding="b")[0]
        self.assertEqual(capability["id"], "client.windows.browser.cdp.procedure")
        self.assertEqual(capability["completion_proof"], ["windows.browser.cdp.procedure.completed"])
        self.assertTrue(capability["goal_completion"])
        self.assertEqual(capability["authorization"], "bounded_terminal")
        assertions = capability["input"]["properties"]["assertions"]
        self.assertEqual(assertions["minItems"], 1)
        self.assertIn("last_text", assertions["items"]["properties"]["property"]["enum"])
        self.assertIn("count_increased", assertions["items"]["properties"]["transition"]["enum"])
        target = capability["input"]["properties"]["steps"]["items"]["properties"]["target_contract"]
        self.assertEqual(target["required"], ["role", "editable", "scope_locator", "name_contains"])
        self.assertIn("page_target_id", capability["input"]["required"])
        self.assertEqual(capability["completion_effects"], ["browser.message.sent"])
        self.assertIn("right-bottom", target["properties"]["zone"]["enum"])
        self.assertIn("Observe-bind-act-prove", capability["summary"])


if __name__ == "__main__":
    unittest.main()
