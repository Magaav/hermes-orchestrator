#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = ROOT / "plugins" / "wasm-agent" / "server" / "static_server.py"
DEFAULT_REPORT = ROOT / "reports" / "master-frontier-v4" / "live-evaluation.json"


def load_server() -> Any:
    spec = importlib.util.spec_from_file_location("wasm_agent_v4_live_server", SERVER_PATH)
    if not spec or not spec.loader:
        raise RuntimeError("static_server_import_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded dev-only Master:frontier V4 source investigation.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--receiver", default="provider")
    parser.add_argument("--objective", default="Locate the V4 run controller in the declared wasm-agent source scope and report source presence only.")
    args = parser.parse_args()
    report_path = Path(args.report).expanduser().resolve()
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="mf-v4-live-") as tmp:
        os.environ["HERMES_WASM_AGENT_DB_PATH"] = str(Path(tmp) / "wa.sqlite3")
        os.environ["HERMES_WASM_AGENT_DEPLOYMENT_MODE"] = "local"
        server = load_server()
        user = {"id": "1", "role": "admin", "email": "v4-live-local@example.invalid"}
        body = {
            "session_id": "master-frontier-v4-live",
            "turn_id": f"v4-live-{int(started)}",
            "receiver": args.receiver,
            "protocol": "v4-source-investigation",
            "investigation_mode": "source-investigation-read-only",
            "envelope": {
                "trace_id": f"v4-live-{int(started)}",
                "schema": "hermes.wasm_agent.master_frontier.v4.request.v1",
                "objective": args.objective,
                "surface": "avatar-chat",
                "route_id": "wasm-agent.avatar-chat.ui",
                "capabilities": ["repo.read", "proof.report"],
                "budget": {"max_output_tokens": 2400, "enforcement": "hard"},
            },
        }
        try:
            result = server.provider_envelope_run_completion(object(), body, user=user)
            run_id = str(result.get("run_id") or "")
            stored = server.read_agent_run(user, run_id)["run"]
            events = server.read_agent_run_events(user, run_id, {"limit": ["500"]})["events"]
            final = stored.get("final") if isinstance(stored.get("final"), dict) else {}
            gate = final.get("gate") if isinstance(final.get("gate"), dict) else {}
            completion = final.get("completion") if isinstance(final.get("completion"), dict) else {}
            evidence = final.get("evidence") if isinstance(final.get("evidence"), dict) else {}
            diagnostics = final.get("diagnostics") if isinstance(final.get("diagnostics"), dict) else {}
            payload = {
                "schema": "hermes.wasm_agent.master_frontier.v4.live_evaluation.v1",
                "ok": stored.get("status") == "completed" and gate.get("ok") is True,
                "evidence_level": "live-frontier-dev-source-only",
                "production": False,
                "run_id": run_id,
                "protocol": stored.get("protocol"),
                "status": stored.get("status"),
                "terminal_answerability": completion.get("terminal_answerability"),
                "claim_count": len(completion.get("claims") or []),
                "evidence_match_count": len(evidence.get("matches") or []),
                "gate": gate,
                "usage": diagnostics.get("usage"),
                "event_types": [event.get("type") for event in events],
                "duration_ms": int((time.time() - started) * 1000),
                "limitations": ["Dev-only live provider proof; no runtime, build, installed-app, deployment, or production proof."],
            }
        except Exception as exc:
            payload = {
                "schema": "hermes.wasm_agent.master_frontier.v4.live_evaluation.v1",
                "ok": False,
                "evidence_level": "live-frontier-dev-attempted",
                "production": False,
                "error": {"code": str(getattr(exc, "code", type(exc).__name__)), "message": str(exc)[:2000]},
                "duration_ms": int((time.time() - started) * 1000),
            }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
