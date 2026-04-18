#!/usr/bin/env python3
"""Re-aplica os arquivos de confirmação de falta suspeita para o diretório de hooks."""

import os
import sys
from pathlib import Path

def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    node_name = str(os.getenv("NODE_NAME", "") or "").strip()
    if node_name:
        candidate = Path("/local/agents/nodes") / node_name / ".hermes"
        if candidate.exists():
            return candidate.resolve()
    orchestrator_home = Path("/local/agents/nodes/orchestrator/.hermes")
    if orchestrator_home.exists():
        return orchestrator_home.resolve()
    return (Path.home() / ".hermes").resolve()


HERMES_HOME = _resolve_hermes_home()
if HERMES_HOME.is_symlink():
    HERMES_HOME = HERMES_HOME.resolve()
DISCORD_PLUGIN = Path(os.getenv("DISCORD_PLUGIN_DIR", "/local/plugins/public/discord")).resolve()

SRC_CONF_STORE   = DISCORD_PLUGIN / "custom_handlers/falta_confirmation_store.py"
SRC_CONF_VIEW    = DISCORD_PLUGIN / "custom_handlers/falta_confirmation_view.py"

DEST_DIR = HERMES_HOME / "hooks" / "discord_slash_bridge" / "custom_handlers"
DEST_DIR.mkdir(parents=True, exist_ok=True)

files = [
    (SRC_CONF_STORE,  DEST_DIR / "falta_confirmation_store.py"),
    (SRC_CONF_VIEW,   DEST_DIR / "falta_confirmation_view.py"),
]

copied = []
for src, dst in files:
    if src.exists():
        dst.write_bytes(src.read_bytes())
        copied.append(str(dst))
    else:
        print(f"[WARN] Source not found: {src}", file=sys.stderr)

if copied:
    print(f"[OK] Confirmation files re-applied: {len(copied)}")
else:
    print("[WARN] No confirmation files found to re-apply", file=sys.stderr)
