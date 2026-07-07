#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = ROOT / "plugins" / "wasm-agent" / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from master_frontier import code_memory, route_contracts  # noqa: E402


def load_contract(route_id: str) -> dict:
    registry = SERVER_ROOT / "agent_route_contracts.json"
    contracts = route_contracts.load_contracts(registry, (ROOT / "plugins" / "wasm-agent").resolve())
    for contract in contracts:
        if str(contract.get("route_id") or "") == route_id:
            return contract
    raise SystemExit(f"route_contract_missing: {route_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Route-scoped Master:frontier code-memory query helper.")
    parser.add_argument("query", nargs="?", help="Symbol/text query for code.memory.search.")
    parser.add_argument("--route-id", default="wasm-agent.avatar-chat.ui")
    parser.add_argument("--tool", choices=["search", "status", "impact", "index"], default="search")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--label", default="")
    parser.add_argument("--file-pattern", default="")
    parser.add_argument("--include-raw", action="store_true")
    args = parser.parse_args()

    contract = load_contract(args.route_id)
    body = {
        "query": args.query or "",
        "limit": args.limit,
        "include_raw": args.include_raw,
    }
    if args.label:
        body["label"] = args.label
    if args.file_pattern:
        body["file_pattern"] = args.file_pattern
    result = code_memory.execute(f"code.memory.{args.tool}", contract, body)
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
