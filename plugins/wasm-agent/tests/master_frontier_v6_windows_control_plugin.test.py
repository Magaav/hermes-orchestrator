#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import windows_control_plugin  # noqa: E402


class WindowsControlPluginTests(unittest.TestCase):
    def test_map_is_small_stable_and_authority_explicit(self) -> None:
        summary = windows_control_plugin.describe({
            "run_hot_operation", "windows.desktop.inspect", "windows.shell.execute.unrestricted",
        })
        self.assertEqual(summary, {
            "plugin": "windows-control", "version": 1, "platform": "windows",
            "layers": ["inventory", "pixels", "browser_cdp", "uia", "shell"],
            "authority": "current_user", "elevation": "not_implicit",
        })

    def test_live_manifest_filters_missing_native_layers(self) -> None:
        values = windows_control_plugin.capabilities(
            {"windows.desktop.inspect"}, client_id="win-a", binding="client:win-a",
        )
        self.assertEqual([item["id"] for item in values], ["client.windows.desktop.inspect"])

    def test_full_manifest_has_unique_proof_owned_capabilities(self) -> None:
        values = windows_control_plugin.capabilities({
            "run_hot_operation", "windows.desktop.describe", "windows.desktop.inspect",
            "windows.desktop.act", "windows.desktop.prove", "windows.shell.execute.unrestricted",
        }, client_id="win-a", binding="client:win-a")
        by_id = {item["id"]: item for item in values}
        self.assertEqual(len(by_id), len(values))
        screenshot = by_id["client.windows.desktop.screenshot"]
        self.assertEqual((screenshot["kind"], screenshot["mode"], screenshot["authority"]), ("observe", "read", "client.ui.inspect"))
        self.assertTrue(screenshot["terminal_result"])
        self.assertEqual(screenshot["proof"], ["windows.desktop.screenshot"])
        navigate = by_id["client.windows.browser.cdp.navigate"]
        self.assertEqual(navigate["input"]["required"], ["url"])
        self.assertEqual(navigate["proof"], ["windows.browser.cdp.navigation.observed"])
        self.assertTrue(navigate["terminal_result"])
        inspect = by_id["client.windows.browser.cdp.inspect"]
        self.assertEqual(inspect["mode"], "read")
        self.assertEqual(inspect["proof"], ["windows.browser.cdp.dom.snapshot"])
        self.assertIn("use this first", inspect["summary"])
        self.assertEqual(inspect["input"]["properties"]["query_text"]["maxLength"], 300)
        self.assertEqual(inspect["input"]["properties"]["query_selector"]["maxLength"], 300)
        self.assertEqual(inspect["activates"], ["client.windows.browser.cdp.procedure"])
        runtime_inspect = by_id["client.windows.browser.cdp.runtime.inspect"]
        self.assertEqual(runtime_inspect["mode"], "read")
        self.assertTrue(runtime_inspect["terminal_result"])
        self.assertEqual(runtime_inspect["completion_proof"], ["windows.browser.cdp.runtime.snapshot"])
        self.assertEqual(runtime_inspect["proof"], ["windows.browser.cdp.runtime.snapshot"])
        self.assertEqual(runtime_inspect["input"]["properties"]["max_ancestors"]["maximum"], 16)
        self.assertIn("never invokes getters", runtime_inspect["summary"])
        self.assertIn("after CDP inspection reports", by_id["client.windows.browser.cdp.default.open"]["summary"])
        act = by_id["client.windows.browser.cdp.act"]
        self.assertEqual(act["input"]["required"], ["locator", "action", "expect"])
        self.assertEqual(act["completion_proof"], ["windows.browser.cdp.action.observed"])
        self.assertFalse(act["goal_completion"])
        self.assertTrue(act["setup_allowed"])
        transaction = by_id["client.windows.browser.cdp.transaction"]
        self.assertEqual(transaction["input"]["required"], ["steps", "expect"])
        self.assertEqual(transaction["input"]["properties"]["steps"]["maxItems"], 4)
        self.assertTrue(transaction["terminal_result"])
        self.assertFalse(transaction["goal_completion"])
        self.assertTrue(transaction["setup_allowed"])
        self.assertTrue(by_id["client.windows.browser.cdp.default.open"]["setup_allowed"])
        self.assertTrue(by_id["client.windows.browser.cdp.navigate"]["setup_allowed"])
        shell = by_id["client.windows.shell.execute.unrestricted"]
        self.assertEqual(shell["mode"], "write")
        self.assertFalse(shell["terminal_result"])
        self.assertEqual(shell["authorization"], "reviewed")
        for value in values:
            self.assertTrue(value["proof"], value["id"])
            if value["mode"] == "write":
                self.assertTrue(value["conflicts"], value["id"])


if __name__ == "__main__":
    unittest.main()
