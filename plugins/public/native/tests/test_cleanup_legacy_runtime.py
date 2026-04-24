from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from cleanup_legacy_runtime import main


def test_cleanup_legacy_runtime_removes_stale_bridge(tmp_path, capsys):
    hermes_home = tmp_path / ".hermes"
    bridge_dir = hermes_home / "hooks" / "discord_slash_bridge"
    bridge_dir.mkdir(parents=True)
    (bridge_dir / "runtime.py").write_text("legacy bridge\n", encoding="utf-8")

    rc = main(["--hermes-home", str(hermes_home)])
    payload = json.loads(capsys.readouterr().out.strip())

    assert rc == 0
    assert payload["changed"] is True
    assert not bridge_dir.exists()
    assert str(bridge_dir) in payload["removed"]
