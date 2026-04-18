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


def test_update_run_command_contract(tmp_path: Path) -> None:
    proc = _run_horc(
        tmp_path,
        ["update", "run", "colmeio", "--stage", "colmeio-stage", "--source-branch", "main"],
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["argv"][:5] == [
        "update-run",
        "--name",
        "colmeio",
        "--stage-name",
        "colmeio-stage",
    ]
    assert "--source-branch" in payload["argv"]
    assert "main" in payload["argv"]


def test_update_validate_contract(tmp_path: Path) -> None:
    proc = _run_horc(tmp_path, ["update", "validate", "run-123", "--phase", "stage"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["argv"][:3] == ["update-validate", "--run-id", "run-123"]
    assert "--phase" in payload["argv"]
    assert "stage" in payload["argv"]


def test_update_resume_contract(tmp_path: Path) -> None:
    proc = _run_horc(tmp_path, ["update", "resume", "run-123"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["argv"] == ["update-resume", "--run-id", "run-123"]


def test_update_status_contract(tmp_path: Path) -> None:
    proc = _run_horc(tmp_path, ["update", "status", "run-123"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["argv"] == ["update-run-status", "--run-id", "run-123"]


def test_retired_update_commands_rejected(tmp_path: Path) -> None:
    cases = [
        ["update", "test"],
        ["update", "apply", "node", "node1"],
        ["profile", "clone", "colmeio", "colmeio-stage"],
        ["agent", "update"],
        ["test", "update"],
        ["test-update"],
    ]
    for args in cases:
        proc = _run_horc(tmp_path, args)
        assert proc.returncode != 0
        err = proc.stderr.lower()
        assert "retired" in err or "removed" in err
