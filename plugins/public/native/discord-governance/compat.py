"""Native Discord governance compatibility status helpers.

The bridge-era sync into ``~/.hermes/hooks`` has been retired.  Keep this
module as a non-writing compatibility shim so diagnostics and tests can verify
that governance now runs through Hermes-native plugin hooks.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict


def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


def ensure_governance_runtime() -> Dict[str, Any]:
    hermes_home = _resolve_hermes_home()
    return {
        "ok": True,
        "changed": False,
        "changed_paths": [],
        "mode": "native-no-sync",
        "hermes_home": str(hermes_home),
        "slash_bridge_dir": str(hermes_home / "hooks" / "discord_slash_bridge"),
        "channel_acl_dir": str(hermes_home / "hooks" / "channel_acl"),
    }


def main() -> int:
    import json

    print(json.dumps(ensure_governance_runtime(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
