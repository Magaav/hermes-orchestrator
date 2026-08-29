import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "server" / "native_control_receipts.py"
SPEC = importlib.util.spec_from_file_location("native_control_receipts", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NativeControlReceiptProjectionTest(unittest.TestCase):
    def test_nested_capability_contract_is_not_tail_truncated(self):
        capabilities = [f"native.capabilities.capability{i}.v1" for i in range(19)]
        projected = MODULE._bounded({"result": {"nativeKernel": {"supportedCapabilities": capabilities}}})
        self.assertEqual(projected["result"]["nativeKernel"]["supportedCapabilities"], capabilities)

    def test_array_bound_remains_forty_items(self):
        values = [str(index) for index in range(50)]
        self.assertEqual(MODULE._bounded({"values": values})["values"], values[:40])


if __name__ == "__main__":
    unittest.main()
