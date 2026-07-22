#!/usr/bin/env python3
"""Focused end-to-end proof for adapter events crossing the lane boundary."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_trajectory import FIELD_DICTIONARY, MAX_EVENTS, MAX_SUMMARY_CHARS, write_trajectory


LAB = Path(__file__).resolve().parent
FIXTURE = LAB / "fixtures/fake-agent-event-runner.py"


def load_lane_runner():
    path = LAB / "lane-runner.py"
    spec = importlib.util.spec_from_file_location("safe_lab_lane_runner_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("lane runner import unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentTrajectoryFixtureTests(unittest.TestCase):
    def test_lane_normalizes_fake_adapter_events_and_owns_terminal(self) -> None:
        lane_runner = load_lane_runner()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter_events = root / "adapter-events.jsonl"
            normalized_events = root / "events.jsonl"
            env = lane_runner.adapter_environment(
                {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"},
                adapter_events,
            )
            completed = subprocess.run(
                [sys.executable, str(FIXTURE)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            trajectory = write_trajectory(
                normalized_events,
                adapter_events,
                terminal_status="completed",
                slot="harness-fixture",
                terminal_summary="fixture lane completed",
            )
            raw_normalized = normalized_events.read_text(encoding="utf-8")
            events = [json.loads(line) for line in raw_normalized.splitlines()]
            transported = lane_runner.trajectory_projection(trajectory)

        self.assertEqual(
            [event["k"] for event in events],
            ["search", "read", "edit", "command", "test", "diff", "proof", "terminal"],
        )
        self.assertEqual([event["q"] for event in events], list(range(1, len(events) + 1)))
        self.assertLessEqual(len(events), MAX_EVENTS)
        self.assertTrue(all(len(event.get("x", "")) <= MAX_SUMMARY_CHARS for event in events))
        self.assertEqual(len(events[0]["x"]), MAX_SUMMARY_CHARS)
        self.assertTrue(all(set(event).issubset(FIELD_DICTIONARY) for event in events))

        self.assertNotIn("fixture.person@example.com", raw_normalized)
        self.assertNotIn("fixture-token-1234567890", raw_normalized)
        self.assertNotIn("fixture-private-value", raw_normalized)
        self.assertNotIn("fixture-private-token", raw_normalized)
        self.assertNotIn("needle-sk_test_1234567890123456", raw_normalized)
        self.assertIn("[redacted-email]", raw_normalized)
        self.assertIn("[redacted-secret]", raw_normalized)
        self.assertIn("authorization=[redacted]", raw_normalized)
        self.assertTrue(events[0]["d"].startswith("sha256:"))
        self.assertEqual(events[0]["p"], "src:pkg/owner.py")
        self.assertEqual(events[2]["p"], "ws:pkg/owner.py")

        terminal = events[-1]
        self.assertEqual(terminal["k"], "terminal")
        self.assertEqual(terminal["s"], "ok")
        self.assertEqual(terminal["a"], "harness-fixture")
        self.assertTrue(all(event["o"] == "adapter" for event in events[:-1]))
        self.assertEqual(terminal["o"], "lane")
        self.assertTrue(trajectory["metadata"]["terminalPreserved"])
        self.assertEqual(trajectory["metadata"]["completeness"], "complete")
        self.assertEqual(trajectory["metadata"]["provenance"], ["adapter", "lane"])
        self.assertTrue(trajectory["metadata"]["admissibleForStrategyMining"])
        self.assertEqual(trajectory["metadata"]["warnings"], [])
        self.assertEqual(transported["events"], events)
        self.assertEqual(transported["completeness"], "complete")
        self.assertLessEqual(len(transported["events"]), MAX_EVENTS)


if __name__ == "__main__":
    unittest.main()
