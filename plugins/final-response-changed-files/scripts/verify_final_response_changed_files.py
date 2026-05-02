#!/usr/bin/env python3
"""Compatibility wrapper for the final-response changed-files verify step."""

from __future__ import annotations

import importlib.util
from pathlib import Path


LEGACY_SCRIPT = Path("/local/plugins/public/hermes-core/scripts/verify_node_agent_followup_footer.py")


def _load_legacy():
    spec = importlib.util.spec_from_file_location("legacy_verify_final_response_changed_files", LEGACY_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load legacy script from {LEGACY_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = _load_legacy()
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
