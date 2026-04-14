#!/usr/bin/env python3
"""
Reapply Discord Channel Routing Hook - survives hermes-agent updates.

PROBLEM:
  run.py hardcodes the hook path: ~/.hermes/hooks/channel_acl/handler.py
  hermes-agent updates can overwrite or reset the active hook files.

SOLUTION:
  Copy the routing hook files into ~/.hermes/hooks/channel_acl/:
    - handler.py (public)
    - config.yaml (private)
    - HOOK.yaml (public)

USAGE:
  # After updating hermes-agent:
  python3 /local/plugins/public/discord/hooks/reapply_discord_channel_routing_hook.py

  # Optional auto-restore after reboot (cron):
  # @reboot python3 /local/plugins/public/discord/hooks/reapply_discord_channel_routing_hook.py
"""

import sys
from pathlib import Path

HERMES_HOOKS_ACL_DIR = Path.home() / ".hermes" / "hooks" / "channel_acl"
ROUTING_HOOK_PUBLIC_SOURCE = Path(__file__).parent / "discord_channel_routing_hook"
ROUTING_HOOK_PRIVATE_SOURCE = Path("/local/plugins/private/discord/hooks/discord_channel_routing_hook")


def reapply() -> int:
    print(f"[reapply] Source(public):  {ROUTING_HOOK_PUBLIC_SOURCE}")
    print(f"[reapply] Source(private): {ROUTING_HOOK_PRIVATE_SOURCE}")
    print(f"[reapply] Destination: {HERMES_HOOKS_ACL_DIR}")

    if not ROUTING_HOOK_PUBLIC_SOURCE.exists():
        print(f"[ERROR] Hook public source not found: {ROUTING_HOOK_PUBLIC_SOURCE}")
        return 1
    if not ROUTING_HOOK_PRIVATE_SOURCE.exists():
        print(f"[ERROR] Hook private source not found: {ROUTING_HOOK_PRIVATE_SOURCE}")
        return 1

    HERMES_HOOKS_ACL_DIR.mkdir(parents=True, exist_ok=True)

    source_map = {
        "handler.py": ROUTING_HOOK_PUBLIC_SOURCE / "handler.py",
        "config.yaml": ROUTING_HOOK_PRIVATE_SOURCE / "config.yaml",
        "HOOK.yaml": ROUTING_HOOK_PUBLIC_SOURCE / "HOOK.yaml",
    }
    for fname, src in source_map.items():
        dst = HERMES_HOOKS_ACL_DIR / fname
        if src.exists():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"  [OK] {fname} -> {dst}")
        else:
            print(f"[ERROR] Required file not found: {src}")
            return 1

    print("[reapply] Done. Hook applied successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(reapply())
