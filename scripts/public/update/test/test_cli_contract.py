from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
HORC_PATH = REPO_ROOT / "scripts" / "public" / "clone" / "horc.sh"


def _write_fake_manager(path: Path) -> None:
    path.write_text(
        (
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import sys\n"
            "print(json.dumps({'argv': sys.argv[1:]}))\n"
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_horc(tmp_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    fake_manager = tmp_path / "fake_clone_manager.py"
    _write_fake_manager(fake_manager)
    env = os.environ.copy()
    env["HERMES_CLONE_MANAGER_SCRIPT"] = str(fake_manager)
    env["HERMES_CLONE_PYTHON_BIN"] = sys.executable
    return subprocess.run(
        ["bash", str(HORC_PATH), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_update_test_command_contract(tmp_path: Path) -> None:
    proc = _run_horc(
        tmp_path,
        ["update", "test", "--source-branch", "feature-x", "--deprecate-plugins", "p1,p2"],
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["argv"][0] == "update-test"
    assert "--source-branch" in payload["argv"]
    assert "feature-x" in payload["argv"]
    assert "--deprecate-plugins" in payload["argv"]
    assert "p1,p2" in payload["argv"]


def test_update_apply_all_contract(tmp_path: Path) -> None:
    proc = _run_horc(
        tmp_path,
        ["update", "apply", "all", "--source-branch", "main"],
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["argv"][:3] == ["update-apply", "--target-mode", "all"]


def test_update_apply_node_contract(tmp_path: Path) -> None:
    proc = _run_horc(
        tmp_path,
        ["update", "apply", "node", "node1,node2", "--deprecate-plugins", "legacy"],
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["argv"][:3] == ["update-apply", "--target-mode", "node"]
    assert "--target-nodes" in payload["argv"]
    assert "node1,node2" in payload["argv"]


def test_legacy_commands_rejected(tmp_path: Path) -> None:
    cases = [
        ["agent", "update"],
        ["test", "update"],
        ["test-update"],
        ["update", "node1"],
        ["update"],
    ]
    for args in cases:
        proc = _run_horc(tmp_path, args)
        assert proc.returncode != 0
        err = proc.stderr.lower()
        assert (
            "removed" in err
            or "unknown update subcommand" in err
            or "requires subcommand" in err
        )
