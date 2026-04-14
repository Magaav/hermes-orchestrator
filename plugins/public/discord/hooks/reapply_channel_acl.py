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
    /local/plugins/public/discord/hooks/channel_acl/ (handler + manifest)
    /local/plugins/private/discord/hooks/channel_acl/ (runtime config)
  to:
    ~/.hermes/hooks/channel_acl/

USAGE:
  python3 /local/plugins/public/discord/hooks/reapply_channel_acl.py

AUTORUN:
  - Via BOOT.md: BOOT.md can trigger an LLM agent that runs this script.
  - Via cron: @reboot or run manually after agent updates.
"""

import sys
from pathlib import Path

PUBLIC_SOURCE = Path("/local/plugins/public/discord/hooks/channel_acl")
PRIVATE_SOURCE = Path("/local/plugins/private/discord/hooks/channel_acl")
DEST = Path.home() / ".hermes" / "hooks" / "channel_acl"


def reapply() -> int:
    print(f"[reapply] Source(public):  {PUBLIC_SOURCE}")
    print(f"[reapply] Source(private): {PRIVATE_SOURCE}")
    print(f"[reapply] Destination: {DEST}")

    if not PUBLIC_SOURCE.exists():
        print(f"[ERROR] Public source not found: {PUBLIC_SOURCE}")
        return 1
    if not PRIVATE_SOURCE.exists():
        print(f"[ERROR] Private source not found: {PRIVATE_SOURCE}")
        return 1

    DEST.mkdir(parents=True, exist_ok=True)

    source_map = {
        "handler.py": PUBLIC_SOURCE / "handler.py",
        "config.yaml": PRIVATE_SOURCE / "config.yaml",
        "HOOK.yaml": PUBLIC_SOURCE / "HOOK.yaml",
    }
    for fname, src in source_map.items():
        dst = DEST / fname
        if src.exists():
            dst.write_bytes(src.read_bytes())
            print(f"  [OK] {fname}")
        else:
            print(f"[ERROR] Required file not found: {src}")
            return 1

    print("[reapply] Done. Hook applied.")
    return 0


if __name__ == "__main__":
    sys.exit(reapply())
