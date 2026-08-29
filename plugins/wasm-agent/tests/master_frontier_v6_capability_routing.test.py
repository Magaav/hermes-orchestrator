import importlib.util
import sys
import unittest
from pathlib import Path


SERVER = Path(__file__).parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import budget
from master_frontier.v6 import capability_routing, catalog, contracts


class V6CapabilityRoutingTest(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog.Catalog()
        for identifier, summary in (
            ("client.inspect", "Inspect the bound live Electron renderer and semantic widget state."),
            ("client.windows.desktop.inspect", "Inspect a bounded Windows desktop UI Automation tree and open application window."),
            ("client.browser.inspect", "Inspect the active Browser page."),
            ("client.windows.browser.cdp.default.open", "Open the declared default CDP realm."),
            ("client.windows.browser.cdp.persistent.open", "Open persistent CDP explicitly."),
            ("client.windows.browser.cdp.incognito.open", "Open incognito CDP explicitly."),
            ("client.windows.browser.cdp.navigate", "Navigate persistent CDP to an HTTP(S) URL."),
            ("client.windows.browser.cdp.inspect", "Inspect persistent CDP page controls."),
            ("client.windows.browser.cdp.act", "Act on persistent CDP page controls."),
            ("client.windows.browser.cdp.transaction", "Run an atomic persistent CDP transaction."),
        ):
            self.catalog.register(contracts.capability({
                "id": identifier, "kind": "observe", "authority": "client.ui.inspect",
                "executor": identifier, "summary": summary, "mode": "read",
                "proof": ["runtime.snapshot"],
                "input": {"type": "object", "properties": {}, "additionalProperties": False},
            }))

    def test_native_realm_exposes_windows_tools_without_prompt_routing(self):
        selected = capability_routing.initial_client_capabilities(
            self.catalog,
            topology={"default_execution_realm": "native_windows"},
        )
        self.assertIn("client.windows.desktop.inspect", selected)
        self.assertNotIn("client.inspect", selected)

    def test_route_call_target_caps_semantic_profile(self):
        route = {"task_contract": {"budget": {"api_calls_max": 8}}}
        self.assertEqual(budget.decision_limit(route, 32), 8)

    def test_native_scope_excludes_generic_and_browser_capabilities(self):
        selected = capability_routing.initial_client_capabilities(
            self.catalog,
            topology={"default_execution_realm": "native_windows"},
        )
        self.assertIn("client.windows.desktop.inspect", selected)
        self.assertNotIn("client.inspect", selected)
        self.assertNotIn("client.browser.inspect", selected)

    def test_native_projection_keeps_default_cdp_workflow_always_on(self):
        selected = capability_routing.initial_client_capabilities(
            self.catalog, topology={"default_execution_realm": "native_windows"},
        )
        self.assertIn("client.windows.browser.cdp.default.open", selected)
        self.assertNotIn("client.windows.browser.cdp.persistent.open", selected)
        self.assertNotIn("client.windows.browser.cdp.incognito.open", selected)
        self.assertIn("client.windows.browser.cdp.navigate", selected)
        self.assertIn("client.windows.browser.cdp.inspect", selected)
        self.assertIn("client.windows.browser.cdp.act", selected)
        self.assertIn("client.windows.browser.cdp.transaction", selected)
        self.assertIn(
            "client.windows.browser.cdp.incognito.open",
            {item["id"] for item in self.catalog.search("incognito CDP")},
        )

    def test_browser_connection_uses_sandbox_realm(self):
        selected = capability_routing.initial_client_capabilities(
            self.catalog, topology={"default_execution_realm": "browser_sandbox"},
        )
        self.assertIn("client.browser.inspect", selected)
        self.assertNotIn("client.windows.desktop.inspect", selected)

    def test_active_realm_takes_precedence_over_legacy_default(self):
        selected = capability_routing.initial_client_capabilities(
            self.catalog,
            topology={
                "active_execution_realm": "browser_sandbox",
                "default_execution_realm": "native_windows",
            },
        )
        self.assertIn("client.browser.inspect", selected)
        self.assertNotIn("client.windows.desktop.inspect", selected)

    def test_profile_can_be_stricter_than_route_target(self):
        route = {"task_contract": {"budget": {"api_calls_max": 12}}}
        self.assertEqual(budget.decision_limit(route, 4), 4)


if __name__ == "__main__":
    unittest.main()
