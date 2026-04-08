#!/usr/bin/env python3
"""
Reapply Channel ACL Hook - survives hermes-agent updates.

PROBLEM:
  hermes-agent (/home/ubuntu/.hermes/hermes-agent/) is updated via
  git pull / pip install and may overwrite run.py.
  run.py imports channel_acl from ~/.hermes/hooks/channel_acl/.
  That directory is outside the agent source tree, so it survives updates.

  WARNING: if ~/.hermes/hooks/channel_acl/ is deleted, or if run.py changes
  the import path, the hook stops working.

SOLUTION:
  Copy the custom hook files from:
    /local/plugins/discord/hooks/channel_acl/
  to:
    ~/.hermes/hooks/channel_acl/

USAGE:
  python3 /local/plugins/discord/hooks/reapply_channel_acl.py

AUTORUN:
  - Via BOOT.md: BOOT.md can trigger an LLM agent that runs this script.
  - Via cron: @reboot or run manually after agent updates.
"""

import sys
from pathlib import Path

SOURCE = Path("/local/plugins/discord/hooks/channel_acl")
if not SOURCE.exists():
    legacy_source = Path("/local/workspace/discord/hooks/channel_acl")
    if legacy_source.exists():
        SOURCE = legacy_source
DEST = Path.home() / ".hermes" / "hooks" / "channel_acl"


def reapply() -> int:
    print(f"[reapply] Source:      {SOURCE}")
    print(f"[reapply] Destination: {DEST}")

    if not SOURCE.exists():
        print(f"[ERROR] Source not found: {SOURCE}")
        return 1

    DEST.mkdir(parents=True, exist_ok=True)

    for fname in ["handler.py", "config.yaml", "HOOK.yaml"]:
        src = SOURCE / fname
        dst = DEST / fname
        if src.exists():
            dst.write_bytes(src.read_bytes())
            print(f"  [OK] {fname}")
        else:
            print(f"  [WARN] {fname} not found, skipping")

    print("[reapply] Done. Hook applied.")
    return 0


if __name__ == "__main__":
    sys.exit(reapply())
