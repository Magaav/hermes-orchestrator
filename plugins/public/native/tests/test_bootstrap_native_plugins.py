from __future__ import annotations

import json
import sys
from pathlib import Path


NATIVE_ROOT = Path(__file__).resolve().parents[1]
if str(NATIVE_ROOT) not in sys.path:
    sys.path.insert(0, str(NATIVE_ROOT))

import bootstrap_native_plugins as bootstrap


def _write_bootstrap_script(path: Path, *, marker: Path, rc: int) -> None:
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from __future__ import annotations",
                "import json",
                "import sys",
                "from pathlib import Path",
                f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')",
                f"print(json.dumps({{'ok': {rc == 0}, 'script': Path(__file__).name}}))",
                f"raise SystemExit({rc})",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_bootstrap_runs_remaining_scripts_after_failure(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    config_file = tmp_path / "config.yaml"
    env_file.write_text("", encoding="utf-8")
    config_file.write_text("plugins:\n  enabled: []\n", encoding="utf-8")

    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    third = tmp_path / "third.py"
    first_marker = tmp_path / "first.marker"
    second_marker = tmp_path / "second.marker"
    third_marker = tmp_path / "third.marker"
    _write_bootstrap_script(first, marker=first_marker, rc=0)
    _write_bootstrap_script(second, marker=second_marker, rc=1)
    _write_bootstrap_script(third, marker=third_marker, rc=0)

    monkeypatch.setattr(bootstrap, "BOOTSTRAPS", [first, second, third])

    rc = bootstrap.main(["--env-file", str(env_file), "--config-file", str(config_file)])
    payload = json.loads(capsys.readouterr().out.strip())

    assert rc == 1
    assert payload["ok"] is False
    assert len(payload["results"]) == 3
    assert first_marker.exists()
    assert second_marker.exists()
    assert third_marker.exists()
