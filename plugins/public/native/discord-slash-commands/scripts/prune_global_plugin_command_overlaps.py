#!/usr/bin/env python3
"""Delay then prune global plugin commands that are shadowed by guild overlays."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_REGISTER_SCRIPT = Path(__file__).with_name("register_guild_plugin_commands.py")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prune overlapping global plugin commands after guild overlays have synced.",
    )
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--delay", type=float, default=12.0)
    parser.add_argument("--register-script", default=str(DEFAULT_REGISTER_SCRIPT))
    args = parser.parse_args()

    if args.delay > 0:
        time.sleep(float(args.delay))

    register_script = Path(args.register_script).expanduser()
    cmd = [
        sys.executable,
        str(register_script),
        "--env-file",
        str(Path(args.env_file).expanduser()),
        "--mode",
        "safe",
        "--scope",
        "guild",
        "--prune-global-overlaps",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
