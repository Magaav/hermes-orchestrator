#!/usr/bin/env python3
"""
Reapply session_info_hook in discord.py after hermes-agent updates.

Usage:
    python3 reapply_session_info_hook.py [--check] [--force]

    --check  only checks whether the hook is already applied (no changes)
    --force  applies even if already installed (overwrites)
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _resolve_hermes_home() -> Path:
    raw = str(os.getenv("HERMES_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


HERMES_HOME = _resolve_hermes_home()
DISCORD_PLUGIN_ROOT = Path(__file__).resolve().parents[1]

HOOK_BLOCK = '''            # ── Session info via hook (survives hermes-agent updates) ───────
            # Hook lives at ~/.hermes/hooks/session_info_hook/handler.py
            # Loaded via importlib so it survives hermes-agent pip -U updates
            tokens_used = 0
            model_label = "?"
            provider_label = "?"
            routing_note = "default (no channel rule matched)"
            try:
                import importlib.util, os, sys
                _hook_home = Path(os.getenv("HERMES_HOME") or (Path.home() / ".hermes"))
                _hook_path = _hook_home / "hooks" / "session_info_hook" / "handler.py"
                if _hook_path.exists():
                    _spec = importlib.util.spec_from_file_location("colmeio_session_info_hook", _hook_path)
                    if _spec and _spec.loader:
                        _mod = importlib.util.module_from_spec(_spec)
                        sys.modules["colmeio_session_info_hook"] = _mod
                        _spec.loader.exec_module(_mod)
                        _get_info = getattr(_mod, "get_session_info", None)
                        if callable(_get_info):
                            _info = _get_info(self, session_entry, source)
                            tokens_used = _info.get("tokens_used", 0)
                            model_label = _info.get("model_label", "?")
                            provider_label = _info.get("provider_label", "?")
                            routing_note = _info.get("routing_note", routing_note)
            except Exception:
                pass'''

# ORIGINAL block restored by hermes-agent updates
ORIGINAL_BLOCKS = [
    '''            # Token usage
            tokens_used = 0
            if session_entry:
                try:
                    tokens_used = (
                        (session_entry.input_tokens or 0) +
                        (session_entry.output_tokens or 0)
                    )
                except Exception:
                    pass''',
]

# PREVIOUS block (first hook version) - also matched when already applied
PREVIOUS_BLOCKS = [
    '''            # ── Session info via hook (survives hermes-agent updates) ───────
            # Hook registered at ~/.hermes/hooks/session_info_hook/
            # Injects: tokens_used, model_label, provider_label, routing_note
            tokens_used = 0
            model_label = "?"
            provider_label = "?"
            routing_note = "default (no channel rule matched)"
            try:
                _hook_ctx = {
                    "platform_adapter": self,
                    "session_entry": session_entry,
                    "source": source,
                }
                if hasattr(self.gateway_runner, "hooks"):
                    _result = self.gateway_runner.hooks.emit("status:query", _hook_ctx)
                    if _result is not None and isinstance(_result, dict):
                        tokens_used = _result.get("tokens_used", 0)
                        model_label = _result.get("model_label", "?")
                        provider_label = _result.get("provider_label", "?")
                        routing_note = _result.get("routing_note", routing_note)
            except Exception:
                pass''',
]

# Hook content
HOOK_DIR = HERMES_HOME / "hooks" / "session_info_hook"
HOOK_HANDLER = HOOK_DIR / "handler.py"
HOOK_YAML = HOOK_DIR / "HOOK.yaml"
HOOK_HANDLER_SOURCE = DISCORD_PLUGIN_ROOT / "hooks" / "session_info_hook" / "handler.py"

HOOK_YAML_CONTENT = '''name: session-info-hook
description: >
  Formats /status output: tokens (from session_entry), model/provider
  (from config.yaml), and smart routing. Survives hermes-agent updates.
events:
  - status:query
'''


def find_discord_py():
    """Find the discord.py platform adapter."""
    env_root = str(os.getenv("HERMES_AGENT_ROOT", "") or "").strip()
    possible = [
        Path(env_root).expanduser() / "gateway" / "platforms" / "discord.py" if env_root else None,
        Path("/local/hermes-agent/gateway/platforms/discord.py"),
        HERMES_HOME / "hermes-agent" / "gateway" / "platforms" / "discord.py",
        Path("/local/.hermes/hermes-agent/gateway/platforms/discord.py"),
        Path("/home/ubuntu/.hermes/hermes-agent/gateway/platforms/discord.py"),
    ]
    possible = [p for p in possible if p is not None]
    for p in possible:
        if p.exists():
            return p
    print("ERROR: could not find discord.py in expected locations", file=sys.stderr)
    print(f"  Looked in: {[str(p) for p in possible]}", file=sys.stderr)
    sys.exit(1)


def check_hook_installed(content: str) -> bool:
    """True when the hook is already applied."""
    return "colmeio_session_info_hook" in content and "importlib.util" in content


def install_hook():
    """Install (or reinstall) the hook in discord.py."""
    discord_path = find_discord_py()
    original = discord_path.read_text(encoding="utf-8")
    content = original

    # If already installed, stay idempotent and do nothing
    if check_hook_installed(content):
        print("✅ Hook is already applied in discord.py")
        return

    # Try matching the original block (pure hermes-agent)
    replaced = False
    for original in ORIGINAL_BLOCKS:
        if original in content:
            content = content.replace(original, HOOK_BLOCK)
            replaced = True
            break

    # Try matching a previous hook version (reapply scenario)
    if not replaced:
        for prev in PREVIOUS_BLOCKS:
            if prev in content:
                content = content.replace(prev, HOOK_BLOCK)
                replaced = True
                break

    if not replaced:
        # Newer upstream versions moved /status handling to run.py, so this
        # legacy discord.py hook block may no longer exist. This is non-fatal.
        print("⚠️  Legacy '/status token usage' block not found in discord.py; skipping patch.")
        print("   (Expected on newer hermes-agent versions where /status is handled in run.py.)")
        return

    # Save backup
    backup_dir = HERMES_HOME / "logs" / "patch-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"discord.py.session_info_hook.{stamp}.bak"
    backup.write_text(original, encoding="utf-8")

    # Install hook
    discord_path.write_text(content, encoding="utf-8")
    print(f"✅ Hook applied to: {discord_path}")
    print(f"   Backup at:        {backup}")


def install_hook_files():
    """Install hook files into ~/.hermes/hooks/."""
    HOOK_DIR.mkdir(parents=True, exist_ok=True)
    if not HOOK_HANDLER_SOURCE.exists():
        print(f"❌ Hook source not found: {HOOK_HANDLER_SOURCE}", file=sys.stderr)
        sys.exit(1)
    HOOK_HANDLER.write_text(HOOK_HANDLER_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    HOOK_YAML.write_text(HOOK_YAML_CONTENT, encoding="utf-8")
    print(f"✅ Hook files installed at: {HOOK_DIR}")


def status():
    """Show current status."""
    discord_path = find_discord_py()
    content = discord_path.read_text(encoding="utf-8")
    hook_ok = check_hook_installed(content)
    files_ok = HOOK_HANDLER.exists()
    yaml_ok = HOOK_YAML.exists()

    print(f"{'✅' if hook_ok else '❌'} Hook in discord.py: {'applied' if hook_ok else 'NOT applied - run with --force'}")
    print(f"{'✅' if files_ok else '❌'} handler.py:          {'exists' if files_ok else 'MISSING - run without --check to install'}")
    print(f"{'✅' if yaml_ok else '❌'} HOOK.yaml:            {'exists' if yaml_ok else 'MISSING - run without --check to install'}")

    if hook_ok and files_ok and yaml_ok:
        print("\n🟢 All good. Run again after hermes-agent updates.")
    else:
        print("\n⚠️  Action required. Run without --check.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reapply session_info_hook after Hermes Agent updates")
    parser.add_argument("--check", action="store_true", help="Only check status, do not modify")
    parser.add_argument("--force", action="store_true", help="Force reinstall even if already applied")
    args = parser.parse_args()

    if args.check:
        status()
    else:
        install_hook_files()
        install_hook()
        print("\nDone. Restart the gateway: /restart")
