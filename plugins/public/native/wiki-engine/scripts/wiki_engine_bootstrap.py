#!/usr/bin/env python3
"""Compatibility wrapper for the wiki-engine bootstrap flow."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


LEGACY_SCRIPT = Path("/local/plugins/public/hermes-core/scripts/wiki_engine.py")


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    proc = subprocess.run([sys.executable, str(LEGACY_SCRIPT), *args], check=False)
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
