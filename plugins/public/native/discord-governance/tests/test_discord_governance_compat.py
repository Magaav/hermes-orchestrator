from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


COMPAT_PATH = Path("/local/plugins/public/native/discord-governance/compat.py")


def _load_compat():
    spec = importlib.util.spec_from_file_location("discord_governance_compat_test", COMPAT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load compat from {COMPAT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_ensure_governance_runtime_syncs_hooks(monkeypatch, tmp_path):
    compat = _load_compat()
    hermes_home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    public_bridge = tmp_path / "public" / "discord_slash_bridge"
    private_bridge = tmp_path / "private" / "discord_slash_bridge"
    public_channel_acl = tmp_path / "public" / "channel_acl"
    private_channel_acl = tmp_path / "private" / "channel_acl"
    public_custom = tmp_path / "public" / "custom_handlers"

    for name in ("runtime.py", "handlers.py", "role_acl.py"):
        _write(public_bridge / name, f"# {name}\n")
    for name in ("clean.py", "clone.py", "faltas.py", "pair.py", "thread.py"):
        _write(public_bridge / "custom_handlers" / name, f"# {name}\n")
    for name in ("falta_confirmation_store.py", "falta_confirmation_view.py"):
        _write(public_custom / name, f"# {name}\n")
    _write(public_channel_acl / "handler.py", "# handler\n")
    _write(private_channel_acl / "config.yaml", "channels:\n  \"123\":\n    mode: default\n")
    _write(private_bridge / "config.yaml", "blocked:\n  metrics: nope\n")
    _write(private_bridge / "registry.yaml", "slash_bridge:\n  commands: {}\n")

    monkeypatch.setattr(compat, "_PUBLIC_SLASH_BRIDGE_ROOT", public_bridge)
    monkeypatch.setattr(compat, "_PRIVATE_SLASH_BRIDGE_ROOT", private_bridge)
    monkeypatch.setattr(compat, "_PUBLIC_CHANNEL_ACL_ROOT", public_channel_acl)
    monkeypatch.setattr(compat, "_PRIVATE_CHANNEL_ACL_ROOT", private_channel_acl)
    monkeypatch.setattr(compat, "_PUBLIC_DISCORD_CUSTOM_ROOT", public_custom)

    payload = compat.ensure_governance_runtime()

    assert payload["ok"] is True
    assert (hermes_home / "hooks" / "discord_slash_bridge" / "runtime.py").exists()
    assert (hermes_home / "hooks" / "discord_slash_bridge" / "custom_handlers" / "clean.py").exists()
    assert (hermes_home / "hooks" / "discord_slash_bridge" / "custom_handlers" / "falta_confirmation_view.py").exists()
    assert (hermes_home / "hooks" / "channel_acl" / "handler.py").exists()

    registry = yaml.safe_load((hermes_home / "hooks" / "discord_slash_bridge" / "registry.yaml").read_text(encoding="utf-8"))
    assert registry["slash_bridge"]["enabled"] is True
    assert registry["native_overrides"]["acl"]["enabled"] is True
