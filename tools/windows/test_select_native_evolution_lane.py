import importlib.util
import json
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("select-native-evolution-lane.py")
SPEC = importlib.util.spec_from_file_location("native_evolution_lane", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ROUTES = MODULE.load_json(Path(__file__).with_name("native-evolution-routes.json"))
PROOF = {
    "ok": True,
    "results": {"get_bridge_status": {"result": {"nativeKernel": {"supportedCapabilities": [
        "native.capabilities.hotOps.v1",
        "native.capabilities.downloadedOperations.v1",
        "native.capabilities.runtimeLoader.v1",
        "native.capabilities.downloadedRuntime.v1",
    ]}}}},
}


class NativeEvolutionLaneTest(unittest.TestCase):
    def decide(self, paths, proof=PROOF):
        return MODULE.select(paths, "windows", ROUTES, proof)

    def test_cloud_change_blocks_installer(self):
        result = self.decide(["plugins/wasm-agent/public/modules/browser/module.js"])
        self.assertEqual(result["lane"], "cloud-module")
        self.assertFalse(result["nativeBuildAllowed"])

    def test_hot_op_uses_installed_capability_proof(self):
        result = self.decide(["native/windows/ops/canary/echo.js"])
        self.assertEqual(result["lane"], "hot-bundle")
        self.assertTrue(result["laneActionAllowed"])

    def test_hot_op_without_capability_is_blocked_not_rebuilt(self):
        result = self.decide(["native/windows/ops/canary/echo.js"], {"ok": True})
        self.assertEqual(result["lane"], "hot-bundle")
        self.assertFalse(result["laneActionAllowed"])
        self.assertFalse(result["nativeBuildAllowed"])

    def test_native_change_wins_mixed_change_set(self):
        result = self.decide([
            "plugins/wasm-agent/public/modules/browser/module.js",
            "native/windows/src/preload.js",
        ])
        self.assertEqual(result["lane"], "native-rebuild")
        self.assertTrue(result["nativeBuildAllowed"])

    def test_archives_and_docs_do_not_trigger_packaging(self):
        result = self.decide([
            "native/windows/README.md",
            "native/windows/archive/old/installer.exe",
        ])
        self.assertEqual(result["lane"], "no-build")
        self.assertFalse(result["nativeBuildAllowed"])


if __name__ == "__main__":
    unittest.main()
