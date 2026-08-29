#!/usr/bin/env python3
"""Compare the disposable procedure pilot with the captured V6 live baseline."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from procedure_kernel import ProcedureError, Registry, canonical, compile_success, execute


ROOT = Path(__file__).resolve().parent
BASELINE = ROOT / "fixtures/last-live-cdp-run.json"
WINDOWS_BASELINE = ROOT / "fixtures/windows-list-live-cold.json"
REPORT = ROOT / "benchmark-result.json"
ENV = {
    "route": "wasm-agent.avatar-chat.ui",
    "platform": "windows",
    "capability_digest": "client.windows.browser.cdp.default.open@pilot-v1",
}
INTENT = {
    "id": "browser.realm.open",
    "required": {"realm": "persistent"},
    "forbidden": {"realm": "incognito"},
}


def receipt(answer: str = "Opened browser_cdp_persistent with fresh readiness proof.") -> dict:
    return {
        "ok": True, "state": "completed", "observed": {"answer": answer},
        "proof": ["windows.browser.cdp.persistent.ready"],
    }


def candidate(run_id: str) -> dict:
    return compile_success(
        intent=INTENT,
        operation={
            "cap": "client.windows.browser.cdp.default.open", "args": {},
            "required_proof": ["windows.browser.cdp.persistent.ready"],
            "authorization": "bounded_terminal",
        },
        receipt=receipt(), account_scope="account-a", environment=ENV,
        source={"run_id": run_id, "trajectory_head": "captured-live-proof"},
    )


def run() -> dict:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    windows_baseline = json.loads(WINDOWS_BASELINE.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "procedures.sqlite3"
        registry = Registry(database)
        procedure = candidate(baseline["run_id"])
        registry.save(procedure)
        promoted = registry.calibrate(procedure["id"])
        windows_procedure = compile_success(
            intent={"id": "windows.apps.list", "required": {}, "forbidden": {}},
            operation={
                "cap": windows_baseline["capability"], "args": {},
                "required_proof": [windows_baseline["required_proof"]],
                "authorization": "bounded_terminal",
            },
            receipt={"ok": True, "state": "completed", "proof": [windows_baseline["required_proof"]]},
            account_scope="account-a", environment=ENV,
            source={"run_id": windows_baseline["run_id"], "trajectory_head": "captured-windows-list-proof"},
        )
        registry.save(windows_procedure)
        windows_promoted = registry.calibrate(windows_procedure["id"])
        procedure_map = registry.compact_map("account-a")
        registry.close()

        # A separate Registry instance is the cross-session persistence proof.
        next_session = Registry(database)
        started = time.perf_counter()
        matched = next_session.match(
            account_scope="account-a",
            intent={"id": "browser.realm.open", "values": {"realm": "persistent"}},
            environment=ENV,
        )
        result = execute(
            matched, intent={"values": {"realm": "persistent"}}, registry=next_session,
            invoke=lambda _cap, _args: receipt(),
        )
        windows_match = next_session.match(
            account_scope="account-a", intent={"id": "windows.apps.list", "values": {}}, environment=ENV,
        )
        windows_result = execute(
            windows_match, intent={"values": {}}, registry=next_session,
            invoke=lambda _cap, _args: {
                "ok": True, "state": "completed",
                "observed": {"answer": "12 visible Windows were freshly listed."},
                "proof": [windows_baseline["required_proof"]],
            },
        )
        procedure_kernel_ms = round((time.perf_counter() - started) * 1000, 3)

        other_account_rejected = False
        try:
            next_session.match(
                account_scope="account-b",
                intent={"id": "browser.realm.open", "values": {"realm": "persistent"}},
                environment=ENV,
            )
        except ProcedureError as exc:
            other_account_rejected = exc.code == "procedure_rediscovery_required"

        incompatible_pruned = False
        try:
            next_session.match(
                account_scope="account-a",
                intent={"id": "browser.realm.open", "values": {"realm": "persistent"}},
                environment={**ENV, "capability_digest": "changed"},
            )
        except ProcedureError as exc:
            incompatible_pruned = (
                exc.code == "procedure_rediscovery_required"
                and next_session.get(promoted["id"])["state"] == "pruned"
            )
        next_session.close()

    checks = {
        "proofCompleteTrajectoryCompiled": procedure["required_proof"] == [baseline["required_proof"]],
        "compactMapFindsProcedures": procedure_map["count"] == 2 and {
            item["cap"] for item in procedure_map["procedures"]
        } == {baseline["capability"], windows_baseline["capability"]},
        "crossSessionReuseWorks": result["procedure_id"] == promoted["id"],
        "freshProofStillRequired": baseline["required_proof"] in result["receipt"]["proof"],
        "procedureLaneUsesNoProvider": result["provider_calls"] == 0,
        "accountBoundaryRequiresRediscovery": other_account_rejected,
        "environmentDriftPrunes": incompatible_pruned,
        "outputSemanticsPreserved": "browser_cdp_persistent" in result["answer"],
        "nonBrowserLiveTrajectoryReusable": (
            windows_result["provider_calls"] == 0
            and windows_result["procedure_id"] == windows_promoted["id"]
            and windows_baseline["required_proof"] in windows_result["receipt"]["proof"]
        ),
    }
    limitations = {
        "naturalLanguageClassificationIncluded": False,
        "nativeExecutionLatencyIncluded": False,
        "productionRoutingChanged": False,
        "claim": (
            "This proves reusable procedure storage, retrieval, cross-session scope, "
            "fresh-proof execution, and invalidation. It does not prove end-to-end zero-token routing."
        ),
    }
    decision = "retain-candidate" if all(checks.values()) else "prune-pilot"
    return {
        "schema": "master.frontier.v7.procedure-pilot.benchmark.v1",
        "decision": decision,
        "baseline": baseline,
        "windows_baseline": windows_baseline,
        "pilot": {
            "procedure_provider_calls": result["provider_calls"],
            "procedure_provider_tokens": 0,
            "procedure_kernel_ms": procedure_kernel_ms,
            "map_bytes": len(canonical(procedure_map).encode()),
            "state": promoted["state"],
            "answer": result["answer"],
            "windows_answer": windows_result["answer"],
        },
        "comparison": {
            "provider_calls_avoided_after_match": baseline["provider_calls"] - result["provider_calls"],
            "provider_activity_tokens_avoided_after_match": baseline["total_tokens"],
            "fresh_input_tokens_avoided_after_match": baseline["fresh_input_tokens"],
            "quality_proxy": "same capability + same required proof + fresh receipt + equivalent bounded answer",
        },
        "checks": checks,
        "limitations": limitations,
        "next_gate": (
            "Semantic router A/B failed held-out coverage and was pruned; retain structured proof only and do not bootstrap MF-v7."
            if decision == "retain-candidate" else
            "Delete the isolated plugin; do not promote any contract into MF-v7."
        ),
    }


def main() -> int:
    report = run()
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"MF-V7 procedure pilot: {report['decision']}")
    print(f"Report: {REPORT.relative_to(ROOT.parent.parent.parent)}")
    for name, passed in report["checks"].items():
        print(f"- {name}: {'PASS' if passed else 'FAIL'}")
    print(f"- limitation: {report['limitations']['claim']}")
    return 0 if report["decision"] == "retain-candidate" else 1


if __name__ == "__main__":
    raise SystemExit(main())
