#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/context/prove-master-frontier-cloud-canary.py"
spec = importlib.util.spec_from_file_location("mf_cloud_canary", SCRIPT)
assert spec and spec.loader
canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canary)


def response(url: str, status: int, body: str, content_type: str) -> dict[str, object]:
    encoded = body.encode()
    return {
        "status": status,
        "finalUrl": url,
        "contentType": content_type,
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "durationMs": 1,
        "body": encoded,
    }


class MasterFrontierCloudCanaryTests(unittest.TestCase):
    def test_contract_passes_cloud_only_public_boundaries(self) -> None:
        def fetcher(url: str, _timeout: float) -> dict[str, object]:
            path = url.removeprefix(canary.ORIGIN)
            if path == "/health":
                return response(url, 401, '{"ok":false,"error":{"code":"auth_required"}}', "application/json")
            if path == "/config.json":
                return response(url, 200, json.dumps({
                    "appId": "wasm-agent",
                    "deployment": {"mode": "cloud"},
                    "auth": {"googleClientIdConfigured": True, "googleLoginUri": f"{canary.ORIGIN}/auth/google/callback"},
                    "bridge": {"url": f"{canary.ORIGIN}/bridge"},
                }), "application/json")
            if path == "/auth/session":
                return response(url, 200, '{"ok":true,"authenticated":false,"user":null}', "application/json")
            if path == "/modules/master-frontier/source-investigation.js":
                source = (ROOT / "plugins/wasm-agent/public/modules/master-frontier/source-investigation.js").read_text()
                return response(url, 200, source, "text/javascript")
            return response(url, 200, "<!doctype html><title>WASM Agent</title>", "text/html")

        with tempfile.TemporaryDirectory() as tmp:
            report = canary.run_canary(Path(tmp) / "report.json", fetcher=fetcher)
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["results"]), 5)
        self.assertNotIn("body", report["results"][0])
        selector = next(item for item in report["results"] if item["name"] == "frontier_selector")
        self.assertEqual(selector["projection"], {
            "matchesLocal": True, "v6Default": True, "v5Rollback": True,
            "legacyV5Migrates": True,
        })

    def test_contract_rejects_local_origin_and_local_deployment(self) -> None:
        result = response(f"{canary.ORIGIN}/config.json", 200, json.dumps({
            "deployment": {"mode": "local"},
            "auth": {"googleClientIdConfigured": True},
            "bridgeUrl": "http://127.0.0.1:8790",
        }), "application/json")
        failures = canary.inspect_probe("public_config", result, "json")
        self.assertEqual({item["code"] for item in failures}, {"local_origin_exposed", "deployment_not_cloud"})
        self.assertEqual(result["projection"]["localOriginCount"], 1)

    def test_contract_rejects_stale_frontier_selector(self) -> None:
        result = response(
            f"{canary.ORIGIN}/modules/master-frontier/source-investigation.js",
            200,
            "const defaultProtocol = 'v5';",
            "text/javascript",
        )
        failures = canary.inspect_probe("frontier_selector", result, "javascript")
        self.assertEqual([item["code"] for item in failures], ["frontier_selector_stale"])
        self.assertEqual(result["projection"], {
            "matchesLocal": False, "v6Default": False, "v5Rollback": False,
            "legacyV5Migrates": False,
        })


if __name__ == "__main__":
    unittest.main()
