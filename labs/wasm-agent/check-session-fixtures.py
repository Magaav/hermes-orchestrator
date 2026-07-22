#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from session_fixture_contract import canonical_digest, load, validate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite")
    parser.add_argument("--report")
    args = parser.parse_args()
    path = Path(args.suite)
    suite = load(path)
    errors = validate(suite)
    result = {
        "schema": "wasm-agent.safe-lab.session-fixture-proof.v1",
        "ok": not errors,
        "suiteSha256": canonical_digest(suite),
        "fixtureCount": len(suite.get("fixtures") or []),
        "cases": sorted(item.get("case") for item in suite.get("fixtures") or []),
        "errors": errors,
    }
    if args.report:
        report = Path(args.report); report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__": raise SystemExit(main())
