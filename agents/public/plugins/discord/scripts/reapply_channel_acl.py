#!/usr/bin/env python3
"""
Reapply the channel_acl hook in run.py after hermes-agent updates.

Usage:
    python3 reapply_channel_acl.py [--check] [--force]

channel_acl injects TWO blocks in run.py:
  1. Skill ACL check  (before _run_agent)
  2. Model ACL enforce (after resolve_turn_agent_config)
"""

import argparse
import sys
from pathlib import Path

# Block 1: Skill ACL check (before "# Run the agent")
SKILL_ACL_BLOCK = '''            # ── Channel ACL: normalize message to channel purpose ────────────────
            # In restricted channels: free text → /faltas adicionar <text>
            # Any other command → BLOCK
            _normalized = None
            _blocked = False
            _block_msg = None
            try:
                _hook_path = Path.home() / ".hermes" / "hooks" / "channel_acl" / "handler.py"
                if _hook_path.exists():
                    import importlib.util, sys
                    _spec = importlib.util.spec_from_file_location("colmeio_channel_acl", _hook_path)
                    if _spec and _spec.loader:
                        _mod = importlib.util.module_from_spec(_spec)
                        sys.modules["colmeio_channel_acl"] = _mod
                        _spec.loader.exec_module(_mod)
                        _norm = getattr(_mod, "normalize_to_channel_skill", None)
                        if callable(_norm):
                            _action, _result = _norm(source, message_text)
                            if _action == "BLOCK":
                                _blocked = True
                                _block_msg = _result
                            elif _action == "FALTAS_ADD":
                                _normalized = _result
                            # "PASSTHROUGH" → use message_text as-is
            except Exception:
                pass
            # Apply transformed text for restricted channel purposes
            if _normalized is not None:
                message_text = _normalized
            if _blocked:
                _adapter = self.adapters.get(source.platform)
                if _adapter:
                    await _adapter.send(source.chat_id, _block_msg or "🚫 Blocked.")
                return

'''

SKILL_ACL_ORIGINAL = '''            # Run the agent
            agent_result = await self._run_agent('''

# Block 2: Model ACL enforce (after resolve_turn_agent_config)
MODEL_ACL_BLOCK = '''            turn_route = self._resolve_turn_agent_config(message, model, runtime_kwargs, source=source)

            # ── Channel ACL: enforce channel-specific model ───────────────────
            try:
                _hook_path = Path.home() / ".hermes" / "hooks" / "channel_acl" / "handler.py"
                if _hook_path.exists():
                    import importlib.util, sys as _sys
                    _spec = importlib.util.spec_from_file_location("colmeio_channel_acl", _hook_path)
                    if _spec and _spec.loader:
                        _mod = importlib.util.module_from_spec(_spec)
                        _sys.modules["colmeio_channel_acl"] = _mod
                        _spec.loader.exec_module(_mod)
                        _enforce = getattr(_mod, "enforce_channel_model", None)
                        if callable(_enforce):
                            turn_route = _enforce(source, turn_route)
            except Exception:
                pass

'''

MODEL_ACL_ORIGINAL = '''            turn_route = self._resolve_turn_agent_config(message, model, runtime_kwargs, source=source)

            # Handle channel guardrail block — return early before spinning up an agent
            if turn_route.get("blocked"):'''

# ── Hook files ────────────────────────────────────────────────────────────────
CHANNEL_ACL_HANDLER = open("/home/ubuntu/.hermes/hooks/channel_acl/handler.py").read()

HOOK_YAML_CONTENT = """name: channel-acl
description: >
  Per-channel ACL: enforces allowed models and skills per channel/thread.
  Survives hermes-agent updates. Config in ~/.hermes/hooks/channel_acl/config.yaml.
events:
  - agent:start
  - command:*
"""

CONFIG_YAML_CONTENT = """# Channel ACL — survives hermes-agent updates
# Maps channel/thread IDs to channel purpose, model, and restrictions.
# Thread inherits from parent channel unless overridden.
#
# purpose: "faltas"  → all messages treated as "/faltas adicionar <text>"
#          "free"    → no restrictions (use default model/skills)
# model: specific model to force (e.g. nemotron), or "*" for default
# provider: e.g. nvidia, minimax

channels:
  # ── Faltas ────────────────────────────────────────────────────────────────
  1487099467726328038:   # faltas loja1
    purpose: faltas
    model: nemotron
    provider: nvidia

  1487099552636080201:   # faltas loja2
    purpose: faltas
    model: nemotron
    provider: nvidia
"""


def find_run_py():
    possible = [
        Path.home() / ".hermes" / "hermes-agent" / "gateway" / "run.py",
        Path("/home/ubuntu/.hermes/hermes-agent/gateway/run.py"),
    ]
    for p in possible:
        if p.exists():
            return p
    print("ERROR: run.py not found", file=sys.stderr)
    sys.exit(1)


def check_installed(content: str) -> bool:
    return "colmeio_channel_acl" in content and "normalize_to_channel_skill" in content


def install_hook_files():
    base = Path.home() / ".hermes" / "hooks" / "channel_acl"
    base.mkdir(parents=True, exist_ok=True)
    (base / "handler.py").write_text(CHANNEL_ACL_HANDLER, encoding="utf-8")
    (base / "HOOK.yaml").write_text(HOOK_YAML_CONTENT, encoding="utf-8")
    (base / "config.yaml").write_text(CONFIG_YAML_CONTENT, encoding="utf-8")
    print(f"✅ channel_acl files installed: {base}")


def install_hook():
    run_path = find_run_py()
    content = run_path.read_text(encoding="utf-8")

    if check_installed(content):
        print("✅ channel_acl is already applied in run.py")
        return

    # Patch 1: skill ACL
    if SKILL_ACL_ORIGINAL not in content:
        print("❌ Could not find '# Run the agent' in run.py - did the format change?", file=sys.stderr)
        sys.exit(1)
    content = content.replace(SKILL_ACL_ORIGINAL, SKILL_ACL_BLOCK + SKILL_ACL_ORIGINAL, 1)

    # Patch 2: model ACL
    if MODEL_ACL_ORIGINAL not in content:
        print("❌ Could not find 'Handle channel guardrail block' in run.py - did the format change?", file=sys.stderr)
        sys.exit(1)
    content = content.replace(MODEL_ACL_ORIGINAL, MODEL_ACL_BLOCK + MODEL_ACL_ORIGINAL, 1)

    backup = run_path.with_suffix(".py.backup_acl_v1")
    backup.write_text(content, encoding="utf-8")
    run_path.write_text(content, encoding="utf-8")
    print(f"✅ channel_acl applied to: {run_path}")
    print(f"   Backup at:              {backup}")


def status():
    run_path = find_run_py()
    content = run_path.read_text(encoding="utf-8")
    hook_ok = check_installed(content)
    files_ok = (Path.home() / ".hermes" / "hooks" / "channel_acl" / "handler.py").exists()
    print(f"{'✅' if hook_ok else '❌'} channel_acl in run.py:  {'applied' if hook_ok else 'NOT applied - run with --force'}")
    print(f"{'✅' if files_ok else '❌'} handler.py:             {'exists' if files_ok else 'MISSING'}")
    if hook_ok and files_ok:
        print("\n🟢 All good. Run again after hermes-agent updates.")
    else:
        print("\n⚠️  Action required.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reapply channel_acl hook after Hermes Agent updates")
    parser.add_argument("--check", action="store_true", help="Only check status")
    parser.add_argument("--force", action="store_true", help="Force reinstall")
    args = parser.parse_args()

    if args.check:
        status()
    else:
        install_hook_files()
        install_hook()
        print("\nDone. Restart the gateway: /restart")
