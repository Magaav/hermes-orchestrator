#!/usr/bin/env python3
"""
Reapply Discord Channel Routing Hook - survives hermes-agent updates.

PROBLEM:
  run.py hardcodes the hook path: ~/.hermes/hooks/channel_acl/handler.py
  hermes-agent updates can overwrite or reset the active hook files.

SOLUTION:
  Copy the routing hook files into ~/.hermes/hooks/channel_acl/:
    - handler.py
    - config.yaml
    - HOOK.yaml

USAGE:
  # After updating hermes-agent:
  python3 /local/workspace/discord/hooks/reapply_discord_channel_routing_hook.py

  # Optional auto-restore after reboot (cron):
  # @reboot python3 /local/workspace/discord/hooks/reapply_discord_channel_routing_hook.py
"""

import sys
from pathlib import Path

HERMES_HOOKS_ACL_DIR = Path.home() / ".hermes" / "hooks" / "channel_acl"
ROUTING_HOOK_SOURCE = Path(__file__).parent / "discord_channel_routing_hook"


def reapply() -> int:
    print(f"[reapply] Source:      {ROUTING_HOOK_SOURCE}")
    print(f"[reapply] Destination: {HERMES_HOOKS_ACL_DIR}")

    if not ROUTING_HOOK_SOURCE.exists():
        print(f"[ERROR] Hook source not found: {ROUTING_HOOK_SOURCE}")
        return 1

    HERMES_HOOKS_ACL_DIR.mkdir(parents=True, exist_ok=True)

    for fname in ["handler.py", "config.yaml", "HOOK.yaml"]:
        src = ROUTING_HOOK_SOURCE / fname
        dst = HERMES_HOOKS_ACL_DIR / fname
        if src.exists():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"  [OK] {fname} -> {dst}")
        else:
            print(f"  [WARN] {fname} not found in source, skipping")

    print("[reapply] Done. Hook applied successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(reapply())
