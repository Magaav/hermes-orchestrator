#!/usr/bin/env python3
"""Run a real Codex head through V6 against a disposable registered repository."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins/wasm-agent"
SERVER_PATH = PLUGIN / "server/static_server.py"
REPORT = ROOT / "reports/context/latest/master-frontier-v6-live-model-result.json"


def _load_server():
    spec = importlib.util.spec_from_file_location("wasm_agent_v6_live_model", SERVER_PATH)
    if not spec or not spec.loader:
        raise RuntimeError("static_server_import_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_report(value: dict) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _event_trace(events: list[dict]) -> list[dict]:
    trace = []
    for item in events[-160:]:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        commentary = payload.get("commentary") if isinstance(payload.get("commentary"), dict) else {}
        row = {
            "seq": item.get("seq"), "type": item.get("type"), "summary": item.get("summary"),
        }
        for key in (
            "decision", "tool", "missing", "status", "query", "matches", "capabilities",
            "new_capabilities", "visible_capabilities", "detail_kind", "detail_id", "found",
            "details", "active_details", "operations",
        ):
            if payload.get(key) not in (None, "", []):
                row[key] = payload[key]
        if commentary.get("message"):
            row["commentary"] = str(commentary["message"])[:600]
        trace.append(row)
    return trace


def main() -> int:
    started = time.monotonic()
    report: dict = {"ok": False, "classification": "master_frontier_v6_live_model_fail"}
    static_server = None
    run_id = ""
    try:
        static_server = _load_server()
        with tempfile.TemporaryDirectory(prefix="mf6-live-model-") as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            source = repository / "a.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(
                ["git", "init", "--quiet", str(repository)], check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["git", "-C", str(repository), "add", "a.py"], check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            route_id = "fixture.v6-live-model"
            registry = root / "routes.json"
            registry.write_text(json.dumps({
                "schema": "hermes.wasm_agent.route_contracts.v1",
                "routes": [{
                    "route_id": route_id, "surface": "v6-live-model",
                    "owner": "master-frontier-v6", "workspace_root": str(repository),
                    "allowed_read_roots": [str(repository)],
                    "allowed_write_roots": [str(repository)],
                    "allowed_edit_operations": ["replace"],
                    "likely_paths": ["a.py"],
                    "lookup_handles": ["route.files", "route.tests"],
                    "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
                    "proof": ["route_id", "changed_files", "checks", "token_ledger"],
                    "checks": [{
                        "id": "focused", "command": [
                            "python3", "-c", "from a import VALUE; assert VALUE == 2",
                        ],
                        "timeout_sec": 20, "evidence_paths": ["a.py"],
                        "description": "VALUE must equal 2",
                    }],
                }],
            }), encoding="utf-8")
            environment = {
                **os.environ,
                "HERMES_WASM_AGENT_DB_PATH": str(root / "state" / "wa.sqlite3"),
                "HERMES_WASM_AGENT_REPOSITORY_TRANSACTION_DIR": str(root / "transactions"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
                "WASM_AGENT_ROUTE_CONTRACTS_PATH": str(registry),
                "WASM_AGENT_EVENT_ANCHORS": "1",
                "WASM_AGENT_EVENT_ANCHOR_INTERVAL": "8",
            }
            model = str(os.environ.get("MASTER_FRONTIER_LIVE_MODEL") or "gpt-5.6-sol")
            server = SimpleNamespace(
                plugin_root=PLUGIN, public_root=PLUGIN / "public", state_dir=root / "private-state",
                bridge_url="http://127.0.0.1:8790", chat_turn_results={},
                chat_turn_results_lock=threading.Lock(), agent_run_workers={},
                agent_run_workers_lock=threading.Lock(), remote_control_live_clients={},
                remote_control_live_clients_lock=threading.Lock(),
            )
            user = {"id": "101", "role": "admin", "email": "admin@example.test"}
            objective = (
                "In the routed repository, change a.py so VALUE is 2. Inspect the current source first, "
                "apply a preconditioned edit, run the registered focused check, inspect the Git diff, "
                "collect proof, and report the verified result."
            )
            envelope = {
                "schema": "hermes.wasm_agent.master_frontier.v6",
                "objective": objective, "objective_kind": "implementation",
                "surface": "v6-live-model", "route_id": route_id,
                "task_contract": {"request_class": "implementation"},
                "completion_capabilities": ["repo.patch", "repo.test", "repo.diff", "repo.prove"],
            }
            body = {
                "session_id": "v6-live-model", "turn_id": "v6-live-model-turn",
                "message": objective, "mode": "direct-head", "target_node": "direct-head",
                "protocol": "v6", "receiver": "openai-codex", "model": model,
                "route_id": route_id, "envelope": envelope,
            }
            with patch.dict(os.environ, environment, clear=True):
                route = static_server.require_direct_envelope_route_contract(envelope)
                run, created = static_server.begin_agent_run(server, dict(body), user=user, direct_head=True)
                if not created:
                    raise RuntimeError("live_model_run_not_created")
                run_id = str(run["run_id"])
                try:
                    result = static_server.master_frontier_controller_router.execute(
                        "v6", server, body, user=user, run=run,
                        context={"receiver": "openai-codex", "envelope": envelope},
                        runtime=vars(static_server),
                    )
                except Exception:
                    events = static_server.read_agent_run_events(user, run_id, {"limit": ["240"]})["events"]
                    stored = static_server.read_agent_run(user, run_id)["run"]
                    report.update({
                        "run": run_id, "runStatus": stored.get("status"),
                        "eventTrace": _event_trace(events),
                    })
                    raise
                events = static_server.read_agent_run_events(
                    user, run_id, {"limit": ["240"]},
                )["events"]
                stored = static_server.read_agent_run(user, run_id)["run"]
                diff = static_server.master_frontier_repository_diff.collect(route, include_paths=["a.py"])
                static_server.master_frontier_run_control.clear(run_id)

            commentary = [
                str(((item.get("payload") or {}).get("commentary") or {}).get("message") or "")
                for item in events if item.get("type") == "llm.reason.summary"
            ]
            tools = result.get("local_tools") if isinstance(result.get("local_tools"), list) else []
            capabilities = {str(item.get("capability") or "") for item in tools if item.get("ok") is True}
            diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
            context_rows = [item for item in (diagnostics.get("context") or []) if isinstance(item, dict)]
            checks = {
                "sourceChanged": source.read_text(encoding="utf-8") == "VALUE = 2\n",
                "gitDiffObserved": diff.get("ok") is True and any(item.get("path") == "a.py" for item in diff.get("changed_files") or []),
                "completionGatePassed": diagnostics.get("completion_gaps") == [],
                "requiredCapabilitiesSucceeded": {"repo.patch", "repo.test", "repo.diff", "repo.prove"}.issubset(capabilities),
                "naturalCommentaryEmitted": bool(commentary) and all("Choosing the next bounded action" not in item for item in commentary),
                "exactUsageMeasured": (diagnostics.get("token_usage_total") or {}).get("exact") is True,
                "runCompleted": stored.get("status") == "completed",
                "terminalIntegrityVerified": (result.get("integrity_proof") or {}).get("status") == "verified",
            }
            report = {
                "ok": all(checks.values()),
                "classification": "master_frontier_v6_live_model_pass" if all(checks.values()) else "master_frontier_v6_live_model_fail",
                "model": model, "run": run_id, "checks": checks,
                "providerCalls": diagnostics.get("provider_calls"),
                "tokenUsage": diagnostics.get("token_usage_total"),
                "maxRequestSerializedChars": max((int(item.get("serialized_chars") or 0) for item in context_rows), default=0),
                "commentary": commentary, "capabilities": sorted(capabilities),
                "eventTrace": _event_trace(events),
                "changedFiles": result.get("changed_files") or [],
                "durationMs": round((time.monotonic() - started) * 1000),
                "errors": [name for name, passed in checks.items() if not passed],
            }
    except Exception as exc:  # noqa: BLE001 - proof serializes the typed boundary failure.
        if static_server is not None and run_id:
            static_server.master_frontier_run_control.clear(run_id)
        report.update({
            "error": {"type": type(exc).__name__, "code": str(getattr(exc, "code", "")), "message": str(exc)[:500]},
            "durationMs": round((time.monotonic() - started) * 1000),
        })
    _write_report(report)
    print(f"Master:frontier V6 live model: {'PASS' if report['ok'] else 'FAIL'}")
    print(f"Report JSON: {REPORT.relative_to(ROOT)}")
    if not report["ok"]:
        print(json.dumps(report.get("error") or report.get("errors") or [], ensure_ascii=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
