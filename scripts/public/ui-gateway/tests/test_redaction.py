from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui_gateway.redaction import redact_text


class RedactionTests(unittest.TestCase):
    def test_redacts_bearer_and_api_key(self) -> None:
        source = "Authorization: Bearer abcdefghijklmnop API_KEY=hello-world"
        redacted = redact_text(source)
        self.assertIn("Authorization: Bearer ***REDACTED***", redacted)
        self.assertIn("API_KEY=***REDACTED***", redacted)

    def test_redacts_sk_pattern(self) -> None:
        source = "token sk-abcdefghijklmnopqrstuv used"
        redacted = redact_text(source)
        self.assertNotIn("sk-abcdefghijklmnopqrstuv", redacted)
        self.assertIn("sk-***REDACTED***", redacted)


if __name__ == "__main__":
    unittest.main()
