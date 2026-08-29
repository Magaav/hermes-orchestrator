#!/usr/bin/env python3
"""Focused model-identity admission tests for the safe-lab gateway."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PATH = Path(__file__).with_name("model-gateway.py")
sys.path.insert(0, str(PATH.parent))
SPEC = importlib.util.spec_from_file_location("model_gateway_identity", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ModelGatewayIdentityTests(unittest.TestCase):
    def test_accepts_declared_qualified_identity(self) -> None:
        self.assertTrue(MODULE.expected_model_identity("frank/GLM-5.2"))

    def test_accepts_declared_request_alias(self) -> None:
        self.assertTrue(MODULE.expected_model_identity("glm-5.2"))

    def test_rejects_other_provider_or_model(self) -> None:
        self.assertFalse(MODULE.expected_model_identity("other/GLM-5.2"))
        self.assertFalse(MODULE.expected_model_identity("glm-5.1"))
        self.assertFalse(MODULE.expected_model_identity(""))


if __name__ == "__main__":
    unittest.main()
