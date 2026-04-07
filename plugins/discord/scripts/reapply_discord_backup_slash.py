#!/usr/bin/env python3
"""Compatibility wrapper.

The old /backup patcher is superseded by:
  reapply_discord_command_bootstrap.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    target = Path("/local/workspace/discord/scripts/reapply_discord_command_bootstrap.py")
    if not target.exists():
        print(f"❌ Bootstrap script not found: {target}", file=sys.stderr)
        return 1

    print("[info] reapply_discord_backup_slash.py is deprecated; using command bootstrap.")
    proc = subprocess.run(["python3", str(target)], check=False)
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
