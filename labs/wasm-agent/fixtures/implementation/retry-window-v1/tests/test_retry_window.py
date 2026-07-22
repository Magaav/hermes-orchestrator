from __future__ import annotations

import unittest

from retry_window import RetryWindow


class RetryWindowTests(unittest.TestCase):
    def test_exact_boundary_event_expires(self) -> None:
        window = RetryWindow(limit=2, window_seconds=10)
        self.assertTrue(window.allow(0))
        self.assertTrue(window.allow(1))
        self.assertTrue(window.allow(10))

    def test_capacity_inside_window_is_denied(self) -> None:
        window = RetryWindow(limit=2, window_seconds=10)
        self.assertTrue(window.allow(0))
        self.assertTrue(window.allow(1))
        self.assertFalse(window.allow(9.999))

    def test_retry_after_is_observational(self) -> None:
        window = RetryWindow(limit=1, window_seconds=10)
        self.assertTrue(window.allow(2))
        self.assertEqual(window.retry_after(5), 7)
        self.assertEqual(window.retry_after(12), 0)
        self.assertTrue(window.allow(12))


if __name__ == "__main__":
    unittest.main()
