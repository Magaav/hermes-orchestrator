import sys
import unittest
from pathlib import Path


SERVER = Path(__file__).parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import context_accounting


class V6ContextAccountingTest(unittest.TestCase):
    def test_provider_transport_delta_is_explicitly_estimated(self) -> None:
        measured, _ = context_accounting.measure(
            [{"role": "system", "content": "rules"}, {"role": "user", "content": "goal"}], [],
        )
        attached = context_accounting.attach_usage(measured, {
            "input_tokens": 20_000, "cached_input_tokens": 18_000,
        })
        accounting = attached["transport_accounting"]
        self.assertFalse(accounting["exact"])
        self.assertEqual(accounting["provider_input_tokens"], 20_000)
        self.assertGreater(accounting["transport_overhead_tokens_estimate"], 0)
        self.assertEqual(accounting["estimate_method"], "utf8_chars_div_4_ceiling")


if __name__ == "__main__":
    unittest.main()
