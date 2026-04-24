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


def test_update_help_contract(tmp_path: Path) -> None:
    proc = _run_horc(tmp_path, ["update"])
    assert proc.returncode == 0, proc.stderr
    assert "horc update" in proc.stdout.lower()
    assert "update all" in proc.stdout.lower()
    assert "update node <name>" in proc.stdout.lower()


def test_update_help_subcommand_contract(tmp_path: Path) -> None:
    proc = _run_horc(tmp_path, ["update", "help"])
    assert proc.returncode == 0, proc.stderr
    assert "horc update" in proc.stdout.lower()
    assert "update all" in proc.stdout.lower()
    assert "update node <name>" in proc.stdout.lower()


def test_update_all_command_contract(tmp_path: Path) -> None:
    proc = _run_horc(
        tmp_path,
        ["update", "all"],
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["argv"] == ["update-all"]


def test_update_all_force_contract(tmp_path: Path) -> None:
    proc = _run_horc(
        tmp_path,
        ["update", "all", "--force"],
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["argv"] == ["update-all", "--force"]


def test_update_node_contract(tmp_path: Path) -> None:
    proc = _run_horc(tmp_path, ["update", "node", "orchestrator"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["argv"] == ["update-node", "--name", "orchestrator"]


def test_update_node_force_contract(tmp_path: Path) -> None:
    proc = _run_horc(tmp_path, ["update", "node", "orchestrator", "--force"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["argv"] == ["update-node", "--name", "orchestrator", "--force"]


def test_update_node_requires_name(tmp_path: Path) -> None:
    proc = _run_horc(tmp_path, ["update", "node"])
    assert proc.returncode != 0
    assert "update node requires <name>" in proc.stderr.lower()


def test_purge_node_request_contract(tmp_path: Path) -> None:
    proc = _run_horc(tmp_path, ["purge-node", "colmeio"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["argv"] == ["purge-node-request", "--name", "colmeio"]


def test_purge_node_confirm_contract(tmp_path: Path) -> None:
    proc = _run_horc(tmp_path, ["purge-node", "confirm", "purge-colmeio-123", "--token", "deadbeef"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["argv"] == ["purge-node-confirm", "--run-id", "purge-colmeio-123", "--token", "deadbeef"]


def test_retired_update_commands_rejected(tmp_path: Path) -> None:
    cases = [
        ["update", "run", "colmeio"],
        ["update", "status", "run-123"],
        ["update", "resume", "run-123"],
        ["update", "validate", "run-123"],
        ["agent", "update"],
        ["test", "update"],
        ["test-update"],
    ]
    for args in cases:
        proc = _run_horc(tmp_path, args)
        assert proc.returncode != 0
        err = proc.stderr.lower()
        assert "retired" in err or "removed" in err or "unknown update subcommand" in err
