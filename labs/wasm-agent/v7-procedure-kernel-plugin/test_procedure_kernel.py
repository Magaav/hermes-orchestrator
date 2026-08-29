from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from procedure_kernel import ProcedureError, Registry, compile_success, execute


ENV = {"route": "wasm-agent.avatar-chat.ui", "capability_digest": "cdp-v1", "platform": "windows"}


def compiled(*, account: str = "account-a", intent_id: str = "browser.realm.open", required=None, forbidden=None, argument_fields=None):
    return compile_success(
        intent={"id": intent_id, "required": required or {"realm": "persistent"}, "forbidden": forbidden or {"realm": "incognito"}},
        operation={
            "cap": "client.windows.browser.cdp.default.open", "args": {},
            "argument_fields": argument_fields or [], "required_proof": ["windows.browser.cdp.persistent.ready"],
            "authorization": "bounded_terminal",
        },
        receipt={"ok": True, "state": "completed", "proof": ["windows.browser.cdp.persistent.ready"]},
        account_scope=account, environment=ENV,
        source={"run_id": "wa_run_fixture", "trajectory_head": "ev:fixture"},
    )


class ProcedureKernelPilotTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "procedures.sqlite3"
        self.registry = Registry(self.path)

    def tearDown(self):
        self.registry.close()
        self.temp.cleanup()

    def promote(self, procedure):
        self.registry.save(procedure)
        return self.registry.calibrate(procedure["id"])

    def test_exact_repeat_uses_fresh_proof_without_provider(self):
        procedure = self.promote(compiled())
        match = self.registry.match(
            account_scope="account-a", intent={"id": "browser.realm.open", "values": {"realm": "persistent"}}, environment=ENV,
        )
        result = execute(match, intent={"values": {"realm": "persistent"}}, registry=self.registry, invoke=lambda cap, args: {
            "ok": True, "state": "completed", "observed": {"answer": "Opened persistent CDP."},
            "proof": ["windows.browser.cdp.persistent.ready"], "cap": cap, "args": args,
        })
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["answer"], "Opened persistent CDP.")
        self.assertEqual(procedure["state"], "promoted")

    def test_same_session_repeat_remains_exactly_once_per_invocation(self):
        procedure = self.promote(compiled())
        calls = []
        for sequence in (1, 2):
            match = self.registry.match(
                account_scope="account-a", intent={"id": "browser.realm.open", "values": {"realm": "persistent"}}, environment=ENV,
            )
            result = execute(match, intent={"values": {}}, registry=self.registry, invoke=lambda cap, args, n=sequence: calls.append((n, cap, args)) or {
                "ok": True, "state": "completed", "observed": {"answer": f"Opened repeat {n}."},
                "proof": ["windows.browser.cdp.persistent.ready"],
            })
            self.assertEqual(result["answer"], f"Opened repeat {sequence}.")
        self.assertEqual(len(calls), 2)
        self.assertEqual({item[0] for item in calls}, {1, 2})

    def test_candidate_is_not_executable_before_calibration(self):
        self.registry.save(compiled())
        with self.assertRaisesRegex(ProcedureError, "procedure_rediscovery_required"):
            self.registry.match(
                account_scope="account-a", intent={"id": "browser.realm.open", "values": {"realm": "persistent"}}, environment=ENV,
            )

    def test_forbidden_semantic_qualifier_cannot_reuse(self):
        self.promote(compiled())
        with self.assertRaisesRegex(ProcedureError, "procedure_rediscovery_required"):
            self.registry.match(
                account_scope="account-a", intent={"id": "browser.realm.open", "values": {"realm": "incognito"}}, environment=ENV,
            )

    def test_parameterized_repeat_binds_only_declared_fields(self):
        procedure = compiled(intent_id="browser.navigate", required={"realm": "persistent"}, forbidden={"realm": "incognito"}, argument_fields=["url"])
        procedure["operation"]["cap"] = "client.browser.navigate"
        unsigned = {key: value for key, value in procedure.items() if key != "digest"}
        from procedure_kernel import digest
        procedure["digest"] = digest(unsigned)
        self.promote(procedure)
        match = self.registry.match(
            account_scope="account-a", intent={"id": "browser.navigate", "values": {"realm": "persistent", "url": "https://example.com"}}, environment=ENV,
        )
        seen = {}
        execute(match, intent={"values": {"url": "https://example.com"}}, registry=self.registry, invoke=lambda cap, args: seen.update({"cap": cap, "args": args}) or {
            "ok": True, "state": "completed", "observed": {"answer": "Navigated."},
            "proof": ["windows.browser.cdp.persistent.ready"],
        })
        self.assertEqual(seen, {"cap": "client.browser.navigate", "args": {"url": "https://example.com"}})

    def test_parameterized_repeat_ignores_undeclared_values(self):
        procedure = compiled(intent_id="browser.navigate", required={"realm": "persistent"}, forbidden={}, argument_fields=["url"])
        procedure["operation"]["cap"] = "client.browser.navigate"
        self.promote(procedure)
        match = self.registry.match(
            account_scope="account-a", intent={"id": "browser.navigate", "values": {"realm": "persistent", "url": "https://example.com", "command": "forbidden"}}, environment=ENV,
        )
        seen = {}
        execute(match, intent={"values": {"url": "https://example.com", "command": "forbidden"}}, registry=self.registry, invoke=lambda cap, args: seen.update(args) or {
            "ok": True, "state": "completed", "observed": {"answer": "Navigated."},
            "proof": ["windows.browser.cdp.persistent.ready"],
        })
        self.assertEqual(seen, {"url": "https://example.com"})

    def test_new_session_same_account_reuses_but_other_account_cannot(self):
        procedure = self.promote(compiled())
        self.registry.close()
        self.registry = Registry(self.path)
        self.assertEqual(self.registry.match(
            account_scope="account-a", intent={"id": "browser.realm.open", "values": {"realm": "persistent"}}, environment=ENV,
        )["id"], procedure["id"])
        with self.assertRaisesRegex(ProcedureError, "procedure_rediscovery_required"):
            self.registry.match(
                account_scope="account-b", intent={"id": "browser.realm.open", "values": {"realm": "persistent"}}, environment=ENV,
            )

    def test_ambiguous_match_fails_closed(self):
        first = self.promote(compiled())
        second = compiled(required={"realm": "persistent", "profile": "default"})
        second["id"] += "-second"
        self.promote(second)
        with self.assertRaisesRegex(ProcedureError, "procedure_match_ambiguous"):
            self.registry.match(
                account_scope="account-a", intent={"id": "browser.realm.open", "values": {"realm": "persistent", "profile": "default"}}, environment=ENV,
            )
        self.assertNotEqual(first["id"], second["id"])

    def test_environment_drift_prunes_and_requests_rediscovery(self):
        procedure = self.promote(compiled())
        with self.assertRaisesRegex(ProcedureError, "procedure_rediscovery_required"):
            self.registry.match(
                account_scope="account-a", intent={"id": "browser.realm.open", "values": {"realm": "persistent"}},
                environment={**ENV, "capability_digest": "cdp-v2"},
            )
        self.assertEqual(self.registry.get(procedure["id"])["state"], "pruned")

    def test_failed_fresh_proof_prunes(self):
        procedure = self.promote(compiled())
        with self.assertRaisesRegex(ProcedureError, "procedure_fresh_proof_failed"):
            execute(procedure, intent={"values": {}}, registry=self.registry, invoke=lambda _cap, _args: {
                "ok": True, "state": "completed", "observed": {"answer": "Unproved."}, "proof": [],
            })
        self.assertEqual(self.registry.get(procedure["id"])["state"], "pruned")

    def test_pruning_one_account_does_not_change_another(self):
        first = self.promote(compiled(account="account-a"))
        second = self.promote(compiled(account="account-b"))
        self.registry.prune(first["id"], "account-specific drift")
        self.assertEqual(self.registry.get(first["id"])["state"], "pruned")
        self.assertEqual(self.registry.get(second["id"])["state"], "promoted")

    def test_compact_map_is_bounded(self):
        for index in range(70):
            procedure = compiled(intent_id=f"fixture.intent.{index}")
            procedure["id"] = f"proc:fixture-{index}"
            self.promote(procedure)
        projected = self.registry.compact_map("account-a")
        self.assertEqual(projected["count"], 64)
        self.assertEqual(len(projected["procedures"]), 64)

    def test_unproved_trajectory_cannot_compile(self):
        with self.assertRaisesRegex(ProcedureError, "trajectory_not_proof_complete"):
            compile_success(
                intent={"id": "x"}, operation={"cap": "x", "required_proof": ["proof"]},
                receipt={"ok": True, "state": "completed", "proof": []}, account_scope="a",
                environment=ENV, source={},
            )


if __name__ == "__main__":
    unittest.main()
