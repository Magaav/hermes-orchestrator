#!/usr/bin/env python3
"""Apply the native Discord governance runtime compatibility steps."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from compat import ensure_governance_runtime


def main() -> int:
    print(json.dumps(ensure_governance_runtime(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
