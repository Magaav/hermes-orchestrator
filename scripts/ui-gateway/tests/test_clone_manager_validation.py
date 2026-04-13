from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui_gateway.clone_manager import CloneManagerError, validate_action, validate_node_name


class CloneManagerValidationTests(unittest.TestCase):
    def test_validate_node_name_accepts_expected(self) -> None:
        self.assertEqual(validate_node_name("orchestrator"), "orchestrator")
        self.assertEqual(validate_node_name("NODE-1"), "node-1")

    def test_validate_node_name_rejects_bad_values(self) -> None:
        with self.assertRaises(CloneManagerError):
            validate_node_name("../../etc/passwd")
        with self.assertRaises(CloneManagerError):
            validate_node_name("UPPER_and_underscores")

    def test_validate_action(self) -> None:
        self.assertEqual(validate_action("restart"), "restart")
        with self.assertRaises(CloneManagerError):
            validate_action("delete")


if __name__ == "__main__":
    unittest.main()
