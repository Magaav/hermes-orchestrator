#!/usr/bin/env python3
"""Sync Hermes-native project plugins into the node runtime before startup."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


BOOTSTRAPS = [
    Path("/local/plugins/public/native/canva/scripts/canva_env_bootstrap.py"),
    Path("/local/plugins/public/native/browser-plus/scripts/browser_plus_env_bootstrap.py"),
    Path("/local/plugins/public/native/discord-governance/scripts/discord_governance_env_bootstrap.py"),
    Path("/local/plugins/public/native/discord-slash-commands/scripts/discord_slash_commands_env_bootstrap.py"),
    Path("/local/plugins/public/native/wiki-engine/scripts/wiki_engine_env_bootstrap.py"),
    Path("/local/plugins/public/native/final-response-changed-files/scripts/final_response_changed_files_env_bootstrap.py"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Hermes-native project plugins into a node runtime.")
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--config-file", required=True)
    args = parser.parse_args(argv)

    env_file = str(Path(args.env_file).expanduser())
    config_file = str(Path(args.config_file).expanduser())

    results: list[dict[str, object]] = []
    failed = False
    for script in BOOTSTRAPS:
        if not script.exists():
            continue
        proc = subprocess.run(
            [sys.executable, str(script), "--env-file", env_file, "--config-file", config_file],
            capture_output=True,
            text=True,
            check=False,
        )
        stdout = str(proc.stdout or "").strip()
        stderr = str(proc.stderr or "").strip()
        payload: dict[str, object] = {
            "script": str(script),
            "returncode": int(proc.returncode),
        }
        if stdout:
            try:
                payload["result"] = json.loads(stdout.splitlines()[-1])
            except Exception:
                payload["stdout"] = stdout
        if stderr:
            payload["stderr"] = stderr
        results.append(payload)
        if proc.returncode != 0:
            failed = True

    print(json.dumps({"ok": not failed, "results": results}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
