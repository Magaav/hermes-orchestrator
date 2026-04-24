#!/usr/bin/env python3
"""Remove legacy Discord bridge runtime artifacts from a Hermes home."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any


def _resolve_hermes_home(raw: str = "") -> Path:
    text = str(raw or os.getenv("HERMES_HOME", "") or "").strip()
    if text:
        return Path(text).expanduser()
    return Path.home() / ".hermes"


def _remove_path(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def cleanup_legacy_runtime(hermes_home: Path) -> dict[str, Any]:
    targets = [
        hermes_home / "hooks" / "discord_slash_bridge",
    ]

    removed: list[str] = []
    missing: list[str] = []
    for target in targets:
        if _remove_path(target):
            removed.append(str(target))
        else:
            missing.append(str(target))

    return {
        "ok": True,
        "hermes_home": str(hermes_home),
        "removed": removed,
        "missing": missing,
        "changed": bool(removed),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove legacy runtime artifacts superseded by native plugins.")
    parser.add_argument("--hermes-home", default="")
    args = parser.parse_args(argv)

    payload = cleanup_legacy_runtime(_resolve_hermes_home(args.hermes_home))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
