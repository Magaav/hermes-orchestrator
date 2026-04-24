"""Native Discord slash-command compatibility status helpers.

The bridge-era runtime sync has been retired.  Keep this module as a
non-writing compatibility shim so older tests and diagnostics can verify that
the plugin is operating in native mode without copying files into
``~/.hermes/hooks``.
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


def ensure_discord_slash_runtime() -> Dict[str, Any]:
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

    print(json.dumps(ensure_discord_slash_runtime(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
