#!/usr/bin/env python3

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("prove-update-reconnect.py")
SPEC = importlib.util.spec_from_file_location("prove_update_reconnect", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def client(build_id, *, live=True, age=1, route=MODULE.PRODUCTION_ROUTE, device="win-test"):
    return {"clients": [{
        "device_id": device, "runtime_type": "electron", "build_id": build_id,
        "route": route, "age_sec": age, "live": live, "transport": "poll",
    }]}


class UpdateReconnectProofTests(unittest.TestCase):
    def test_accepts_exact_fresh_production_build(self):
        report = MODULE.watch_reconnect(lambda: client("win-x64-new"), expected_build="win-x64-new", timeout_sec=0)
        self.assertEqual(report["status"], "pass")
        self.assertFalse(report["transitionObserved"])

    def test_accepts_authenticated_companion_route(self):
        report = MODULE.watch_reconnect(
            lambda: client("win-x64-new", route="https://wa.colmeio.com/home?native=electron&companion=overlay"),
            expected_build="win-x64-new",
            timeout_sec=0,
        )
        self.assertEqual(report["status"], "pass")

    def test_require_transition_waits_through_old_build(self):
        samples = iter([client("win-x64-old"), {"clients": []}, client("win-x64-new")])
        report = MODULE.watch_reconnect(
            lambda: next(samples), expected_build="win-x64-new", require_transition=True,
            timeout_sec=5, poll_sec=0, sleep=lambda _seconds: None,
        )
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["initialBuildId"], "win-x64-old")
        self.assertTrue(report["transitionObserved"])
        self.assertEqual(report["samples"], 3)

    def test_rejects_wrong_route_and_stale_heartbeat(self):
        for payload in (client("win-x64-new", route="http://127.0.0.1:8877"), client("win-x64-new", age=31)):
            report = MODULE.watch_reconnect(
                lambda payload=payload: payload, expected_build="win-x64-new", timeout_sec=0, max_age_sec=30,
            )
            self.assertEqual(report["status"], "fail")

    def test_pinned_device_does_not_accept_another_client(self):
        report = MODULE.watch_reconnect(
            lambda: client("win-x64-new", device="win-other"), expected_build="win-x64-new",
            device_id="win-target", timeout_sec=0,
        )
        self.assertEqual(report["status"], "fail")

    def test_registry_error_is_not_an_update_transition(self):
        report = MODULE.watch_reconnect(
            lambda: (_ for _ in ()).throw(OSError("temporary registry failure")),
            expected_build="win-x64-new", require_transition=True, timeout_sec=0,
        )
        self.assertEqual(report["failureClass"], "update_transition_not_observed")
        self.assertFalse(report["transitionObserved"])


if __name__ == "__main__":
    unittest.main()
