#!/usr/bin/env python3
"""Prove wasm-agent can inspect and chat with a Hermes node through the bridge."""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = ROOT / "plugins/wasm-agent/server/static_server.py"
REPORT_PATH = ROOT / "reports/context/latest/wasm-agent-node-bridge-proof.json"


def load_static_server() -> Any:
    spec = importlib.util.spec_from_file_location("wasm_agent_static_server", SERVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {SERVER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compact_error(exc: BaseException) -> dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "message": str(exc)[:600],
        "code": getattr(exc, "code", ""),
        "status": int(getattr(exc, "status", 0) or 0),
    }


def write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node-id", default="paracelsus")
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8790")
    parser.add_argument("--expected-model", default="deepseek-v4-flash")
    parser.add_argument("--timeout-sec", type=int, default=180)
    args = parser.parse_args()

    started = time.monotonic()
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report: dict[str, Any] = {
        "ok": False,
        "status": "fail",
        "promiseId": "wasm-agent-node-bridge-proof",
        "claim": "wasm-agent can inspect and chat with a Hermes node through node.capabilities and node.chat",
        "checkedAt": checked_at,
        "nodeId": args.node_id,
        "bridgeUrl": args.bridge_url,
        "expectedModel": args.expected_model,
        "durationMs": 0,
        "evidence": [],
        "summary": "",
        "failureClass": None,
        "nextSuggestedSteps": [],
    }

    try:
        server_mod = load_static_server()
        server = type("HarnessServer", (), {"bridge_url": args.bridge_url})()
        user = {"is_admin": True, "email": "harness@local"}

        capabilities = server_mod.agent_kernel_tool(
            server,
            "/agent/tools/node.capabilities",
            {"node_id": args.node_id},
            user=user,
        )
        chat = server_mod.agent_kernel_tool(
            server,
            "/agent/tools/node.chat",
            {
                "node_id": args.node_id,
                "objective": "Harness proof only. Reply with exactly: node bridge proof ok",
                "timeout_sec": args.timeout_sec,
            },
            user=user,
        )

        actions = []
        for action in capabilities.get("actions", []) if isinstance(capabilities, dict) else []:
            if isinstance(action, dict):
                actions.append(str(action.get("action") or action.get("id") or ""))
            else:
                actions.append(str(action))

        usage = chat.get("usage") if isinstance(chat, dict) else {}
        usage_model = str((usage or {}).get("model") or "")
        reply = str(chat.get("reply") or "") if isinstance(chat, dict) else str(chat)
        source = str(chat.get("source") or "") if isinstance(chat, dict) else ""
        failures = []
        if not isinstance(capabilities, dict) or not capabilities.get("ok"):
            failures.append("node.capabilities did not return ok true")
        if "inspect_node" not in actions:
            failures.append("node.capabilities did not expose inspect_node")
        if "run_prompt" not in actions:
            failures.append("node.capabilities did not expose run_prompt")
        if not isinstance(chat, dict) or not chat.get("ok"):
            failures.append("node.chat did not return ok true")
        if source != "bridge_runs":
            failures.append("node.chat did not use bridge_runs")
        if reply.strip() != "node bridge proof ok":
            failures.append("node.chat reply did not match the harness canary")
        if usage_model != args.expected_model:
            failures.append(f"node.chat usage model was {usage_model or '<empty>'}, expected {args.expected_model}")

        report.update(
            {
                "capabilities": {
                    "ok": bool(isinstance(capabilities, dict) and capabilities.get("ok")),
                    "schema": capabilities.get("schema") if isinstance(capabilities, dict) else "",
                    "nodeId": capabilities.get("node_id") if isinstance(capabilities, dict) else "",
                    "actions": sorted(a for a in actions if a),
                },
                "chat": {
                    "ok": bool(isinstance(chat, dict) and chat.get("ok")),
                    "schema": chat.get("schema") if isinstance(chat, dict) else "",
                    "source": source,
                    "reply": reply[:200],
                    "usageModel": usage_model,
                    "usageTotalTokens": int((usage or {}).get("total_tokens") or 0),
                    "usageAccuracy": str((usage or {}).get("usage_accuracy") or ""),
                },
                "evidence": [str(REPORT_PATH.relative_to(ROOT))],
            }
        )

        if failures:
            report.update(
                {
                    "ok": False,
                    "status": "fail",
                    "summary": "; ".join(failures),
                    "failureClass": "node_bridge_contract_failed",
                    "nextSuggestedSteps": [
                        "Run node.capabilities against the node and fix missing bridge/runtime contract first.",
                        "If node.chat fails, verify the node API_SERVER_* env and the container-IP bridge path before changing prompts.",
                    ],
                }
            )
        else:
            report.update(
                {
                    "ok": True,
                    "status": "pass",
                    "summary": f"{args.node_id} node.capabilities and node.chat passed through bridge_runs using {usage_model}.",
                    "failureClass": None,
                    "nextSuggestedSteps": [],
                }
            )
    except Exception as exc:  # noqa: BLE001 - compact harness failure report.
        report.update(
            {
                "ok": False,
                "status": "fail",
                "summary": str(exc)[:600],
                "failureClass": "node_bridge_probe_error",
                "error": compact_error(exc),
                "nextSuggestedSteps": [
                    "Start wasm-agent and the target node, then rerun this promise.",
                    "If the bridge reports api_server_url_not_configured, add the node API_SERVER_* contract instead of hardcoding Hermes core.",
                ],
            }
        )
    finally:
        report["durationMs"] = int((time.monotonic() - started) * 1000)
        write_report(report)

    print(f"wasm-agent node bridge proof: {'PASS' if report['ok'] else 'FAIL'}")
    print(f"Report JSON: {REPORT_PATH.relative_to(ROOT)}")
    if report.get("summary"):
        print(report["summary"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
