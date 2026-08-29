#!/usr/bin/env python3
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins" / "wasm-agent"
sys.path.insert(0, str(PLUGIN / "server"))

from master_frontier.v6 import adapters  # noqa: E402


class ElectronBrowserRemovedTest(unittest.TestCase):
    def test_legacy_browser_is_absent_while_native_cdp_remains(self) -> None:
        route = json.loads((PLUGIN / "server" / "agent_route_contracts.json").read_text())
        serialized = json.dumps(route)
        legacy_capability = "client." + "browser.navigate"
        self.assertNotIn(legacy_capability, serialized)
        self.assertNotIn("browser_navigate", serialized)
        self.assertIn("windows_browser_cdp_persistent_open", serialized)
        self.assertIn("windows_browser_cdp_incognito_open", serialized)

        advertised = adapters.live_client({
            "runtime_type": "electron",
            "client_id": "legacy-fixture",
            "capabilities": ["control." + "browser.navigate", "observe." + "browser.inspect"],
        })
        self.assertFalse(any(item["id"].startswith("client." + "browser.") for item in advertised))

        self.assertFalse((PLUGIN / "public" / "modules" / "browser").exists())
        registry = (PLUGIN / "public" / "modules" / "app-registry.js").read_text()
        self.assertNotIn('id: "' + 'browser"', registry)

        native_main = (ROOT / "native" / "windows" / "src" / "main.js").read_text()
        preload = (ROOT / "native" / "windows" / "src" / "preload.js").read_text()
        self.assertNotIn("WebContents" + "View", native_main)
        self.assertNotIn("web" + "Surfaces", native_main + preload)
        self.assertFalse((ROOT / "native" / "windows" / "src" / "main" / "web-surfaces").exists())


if __name__ == "__main__":
    unittest.main()
