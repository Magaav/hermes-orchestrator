#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/context/prove-production-native-control-authority.py"
SPEC = importlib.util.spec_from_file_location("production_native_control_authority", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("production native-control authority proof import unavailable")
authority = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(authority)


class ProductionNativeControlAuthorityTests(unittest.TestCase):
    def test_compact_client_preserves_runtime_authority_without_raw_heartbeat(self) -> None:
        result = authority.compact_client({
            "device_id": "android-current",
            "runtime_type": "android",
            "build_id": "android-build-1",
            "route": "https://wa.colmeio.com/home?native=android",
            "age_sec": 2,
            "transport": "poll",
            "capabilities": ["control.wake.start"],
            "heartbeat": {"secret": "must-not-leak"},
        })

        self.assertEqual(result["runtimeType"], "android")
        self.assertEqual(result["deviceId"], "android-current")
        self.assertEqual(result["capabilities"], ["control.wake.start"])
        self.assertNotIn("heartbeat", result)
        self.assertNotIn("secret", str(result))


if __name__ == "__main__":
    unittest.main()
