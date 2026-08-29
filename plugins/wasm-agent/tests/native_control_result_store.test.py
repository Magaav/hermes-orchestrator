import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).parents[1] / "server" / "native_control_result_store.py"
SPEC = importlib.util.spec_from_file_location("native_control_result_store", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NativeControlReceiptBudgetTest(unittest.TestCase):
    def test_compact_result_reports_exact_utf8_bytes(self):
        result = {"ok": True, "label": "olá"}
        budget = MODULE.receipt_budget("get_native_kernel_status", {}, result)
        self.assertEqual(budget["resultBytes"], len('{"label":"olá","ok":true}'.encode("utf-8")))
        self.assertEqual(budget["budgetBytes"], 4096)
        self.assertTrue(budget["withinBudget"])
        self.assertIsNone(budget["alert"])

    def test_oversized_default_is_alerted_without_mutating_result(self):
        result = {"ok": True, "payload": "x" * (64 * 1024)}
        original = dict(result)
        budget = MODULE.receipt_budget("run_hot_operation", {}, result)
        self.assertFalse(budget["withinBudget"])
        self.assertGreater(budget["overByBytes"], 0)
        self.assertEqual(budget["alert"], "native_control_receipt_budget_exceeded")
        self.assertEqual(result, original)

    def test_explicit_detail_uses_diagnostic_budget(self):
        budget = MODULE.receipt_budget("get_bridge_status", {"includeLogs": True}, {"logs": "x" * 9000})
        self.assertEqual(budget["profile"], "detail")
        self.assertEqual(budget["budgetBytes"], 256 * 1024)
        self.assertTrue(budget["withinBudget"])

    def test_store_persists_counter_and_emits_overflow_alert_without_failing_result(self):
        class Hub:
            def __init__(self):
                self.events = []

            def record_command(self, *args, **kwargs):
                return None

            def record_event(self, *args):
                self.events.append(args)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            command_path = root / "commands" / "dev" / "cmd.json"
            command_path.parent.mkdir(parents=True)
            command_path.write_text(json.dumps({"type": "run_hot_operation", "payload": {}}), encoding="utf-8")
            audits = []
            hub = Hub()
            server = SimpleNamespace(state_dir=root, observability_hub=hub)
            handler = SimpleNamespace(headers={}, client_address=("127.0.0.1", 1))

            def write(path, value):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value), encoding="utf-8")

            def read(path, fallback):
                return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback

            response = MODULE.save_result(
                server,
                {"device_id": "dev", "command_id": "cmd", "result": {"ok": True, "proof": "x" * (64 * 1024)}},
                handler,
                browser_error=ValueError,
                device_id_from_value=str,
                safe_state_id=lambda value, fallback: value or fallback,
                iso_timestamp=lambda: "2026-08-28T00:00:00Z",
                clipped_verbatim=lambda value, limit: value[:limit],
                redact_diagnostics=lambda value: value,
                control_dir=lambda _server: root,
                write_json_file=write,
                resolve_command_path=lambda _server, _device, _command: command_path,
                read_json_file=read,
                apply_command_result_surface=lambda *args, **kwargs: None,
                append_audit=lambda _server, value: audits.append(value),
            )
            stored = read(root / "results" / "dev" / "cmd.json", {})
            self.assertTrue(response["ok"])
            self.assertTrue(stored["result"]["ok"])
            self.assertFalse(stored["receiptBudget"]["withinBudget"])
            self.assertEqual([event[2] for event in hub.events], ["command_result", "receipt_budget_exceeded"])
            self.assertEqual([entry["action"] for entry in audits], ["command_result", "receipt_budget_exceeded"])


if __name__ == "__main__":
    unittest.main()
