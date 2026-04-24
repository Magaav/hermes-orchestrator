from __future__ import annotations

import importlib.util
from pathlib import Path


COMPAT_PATH = Path("/local/plugins/public/native/discord-governance/compat.py")


def _load_compat():
    spec = importlib.util.spec_from_file_location("discord_governance_compat_test", COMPAT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load compat from {COMPAT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ensure_governance_runtime_is_noop(monkeypatch, tmp_path):
    compat = _load_compat()
    hermes_home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    payload = compat.ensure_governance_runtime()

    assert payload["ok"] is True
    assert payload["changed"] is False
    assert payload["mode"] == "native-no-sync"
    assert not (hermes_home / "hooks").exists()
