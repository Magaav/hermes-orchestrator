#!/usr/bin/env python3
"""Prove generic SQL materialization, budget gates, live execution, and cleanup."""

from __future__ import annotations

import importlib.util
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from safe_lab_host import IMAGE, ROOT, run

LAB = Path(__file__).resolve().parent
SOURCE_VOLUME = "wasm-agent-safe-lab-local-v11"
FIXTURE_VOLUME = "wasm-agent-safe-lab-output-v1"
GOOD_FIXTURE = "fx_d3154de08df6150be9c9"
MISSING_ROUTE_FIXTURE = "fx_2cb86d7cdebc6a33aad6"
LIVE_REPORT = ROOT / "reports/context/latest/live-fixture-hermes-result.json"
REPORT = ROOT / "reports/context/latest/generic-live-fixture-proof.json"


def budget_unit() -> dict:
    path = LAB / "model-gateway.py"
    spec = importlib.util.spec_from_file_location("generic_live_gateway_budget", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load gateway budget module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PROVIDER_CALLS = 0
    module.REQUEST_COUNTS.clear()
    duplicate = [module.claim_request_budget("same") for _ in range(3)]
    module.PROVIDER_CALLS = 0
    module.REQUEST_COUNTS.clear()
    distinct = [module.claim_request_budget(f"distinct-{index}") for index in range(5)]
    ok = (
        [item["allowed"] for item in duplicate] == [True, True, False]
        and duplicate[2]["reason"] == "duplicate"
        and [item["allowed"] for item in distinct] == [True, True, True, True, False]
        and distinct[4]["reason"] == "provider_budget"
    )
    return {"ok": ok, "duplicate": duplicate, "distinct": distinct}


def missing_route_unit() -> dict:
    completed = run([
        "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--user", "10000:10000",
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=32m",
        "-v", f"{SOURCE_VOLUME}:/source:ro", "-v", f"{FIXTURE_VOLUME}:/fixtures:ro",
        "--entrypoint", "python3", IMAGE, "/usr/local/bin/materialize-fixture-task",
        "--fixture-id", MISSING_ROUTE_FIXTURE, "--output", "/tmp/task.json",
    ], timeout=30)
    projection = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else {}
    adjudication = projection.get("adjudication") if isinstance(projection.get("adjudication"), dict) else {}
    return {
        "ok": completed.returncode == 2 and adjudication.get("classification") == "replay_environment_incomplete"
        and adjudication.get("executionAllowed") is False,
        "returncode": completed.returncode,
        "projection": projection,
    }


def main() -> int:
    started = time.monotonic()
    errors: list[str] = []
    budget = budget_unit()
    if not budget["ok"]:
        errors.append("gateway request-budget unit failed")
    route = missing_route_unit()
    if not route["ok"]:
        errors.append("missing-route fixture was not rejected before execution")
    live_stdout = ""
    validation_stdout = ""
    if not errors:
        live = run([
            "python3", str(LAB / "live-fixture-orchestrator.py"),
            "--slot", "harness-03", "--fixture-id", GOOD_FIXTURE,
        ], timeout=240)
        live_stdout = live.stdout
        if live.returncode != 0:
            errors.append(f"generic live orchestration failed: {live.stderr[-1000:] or live.stdout[-1000:]}")
        checked = run([
            "python3", str(LAB / "check-live-fixture-result.py"), str(LIVE_REPORT),
            "--fixture-id", GOOD_FIXTURE,
        ])
        validation_stdout = checked.stdout
        if checked.returncode != 0:
            errors.append(f"live result validation failed: {checked.stdout[-1000:]}")
    live_report = json.loads(LIVE_REPORT.read_text(encoding="utf-8")) if LIVE_REPORT.exists() else {}
    result = {
        "schema": "wasm-agent.safe-lab.generic-live-fixture-proof.v1",
        "ok": not errors,
        "classification": "generic_live_fixture_pass" if not errors else "generic_live_fixture_fail",
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "durationMs": round((time.monotonic() - started) * 1000),
        "budgetUnit": budget,
        "missingRouteUnit": route,
        "liveTechnicalReadiness": live_report.get("technicalReadinessPassed"),
        "liveRankingAllowed": live_report.get("rankingAllowed"),
        "liveFixtureId": ((live_report.get("task") or {}).get("fixture") or {}).get("id"),
        "liveTaskDigest": (live_report.get("task") or {}).get("taskDigest"),
        "liveOutputChars": len(live_stdout),
        "validatorOutputChars": len(validation_stdout),
        "errors": errors,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
