#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/context/evaluate-master-frontier-v5-production.py"
spec = importlib.util.spec_from_file_location("mf5_production_campaign", SCRIPT)
assert spec and spec.loader
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


class MasterFrontierV5CampaignTests(unittest.TestCase):
    def test_manifest_is_exactly_fifty_unique_cases_across_required_categories(self) -> None:
        names = [name for _path, values in campaign.CAMPAIGN.values() for name in values]
        self.assertEqual(campaign.case_count(), 50)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(campaign.CAMPAIGN), {
            "lifecycle", "cost", "causal_proof", "transactions", "diff",
            "worktree", "detached_restart", "authority",
        })

    def test_campaign_executes_all_cases_and_writes_pull_on_demand_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "campaign.json"
            report = campaign.run_campaign(path)
        self.assertTrue(report["ok"])
        self.assertEqual((report["passed"], report["total"], report["failed"]), (50, 50, 0))
        self.assertEqual(len(report["cases"]), 50)
