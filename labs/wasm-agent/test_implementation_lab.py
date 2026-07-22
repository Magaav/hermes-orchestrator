#!/usr/bin/env python3
"""Focused deterministic test entrypoint for the MF5 implementation lab."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent


def main() -> int:
    completed = subprocess.run(
        [sys.executable, str(LAB / "prove-master-frontier-v5-implementation-lab.py")],
        cwd=LAB.parents[1], check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
