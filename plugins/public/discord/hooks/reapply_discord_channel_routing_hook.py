#!/usr/bin/env python3
"""
Legacy compatibility wrapper for the removed discord_channel_routing_hook.

This entrypoint now delegates to the canonical channel_acl applier so old
automation cannot overwrite ~/.hermes/hooks/channel_acl/ with stale legacy
logic anymore.
"""

import subprocess
import sys
from pathlib import Path

CHANNEL_ACL_APPLIER = Path(__file__).parent / "apply_channel_acl_run_py.py"


def reapply() -> int:
    print("[compat] discord_channel_routing_hook is deprecated.")
    print("[compat] Re-applying canonical channel_acl instead.")

    if not CHANNEL_ACL_APPLIER.exists():
        print(f"[ERROR] Canonical applier not found: {CHANNEL_ACL_APPLIER}")
        return 1

    proc = subprocess.run([sys.executable, str(CHANNEL_ACL_APPLIER)], check=False)
    return int(proc.returncode or 0)


if __name__ == "__main__":
    sys.exit(reapply())
