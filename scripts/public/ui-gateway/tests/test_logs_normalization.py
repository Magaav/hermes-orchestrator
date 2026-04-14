from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui_gateway.logs import infer_severity, normalize_log_line, parse_timestamp


class LogNormalizationTests(unittest.TestCase):
    def test_severity_detection(self) -> None:
        self.assertEqual(infer_severity("ERROR failed"), "error")
        self.assertEqual(infer_severity("WARNING possible issue"), "warning")
        self.assertEqual(infer_severity("all good"), "info")

    def test_timestamp_parser(self) -> None:
        ts = parse_timestamp("[2026-04-11T15:00:00Z] hello")
        self.assertEqual(ts, "2026-04-11T15:00:00Z")

    def test_redaction_is_applied(self) -> None:
        evt = normalize_log_line(
            "orchestrator",
            "runtime",
            "Authorization: Bearer abcdefghijklmnop",
        )
        self.assertIn("***REDACTED***", evt.message)


if __name__ == "__main__":
    unittest.main()
