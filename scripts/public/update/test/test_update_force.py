from __future__ import annotations

from types import SimpleNamespace


def test_action_update_template_uses_force_checkout_when_requested(cm, tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "hermes-agent"
    (source_root / ".git").mkdir(parents=True, exist_ok=True)
    (source_root / "cli.py").write_text("print('ok')\n", encoding="utf-8")

    calls: list[list[str]] = []

    monkeypatch.setattr(cm, "HERMES_SOURCE_ROOT", source_root)
    monkeypatch.setattr(cm, "_fetch_remote_branch", lambda path, branch: True)
    monkeypatch.setattr(cm, "_git_commit", lambda path: "abc123")
    monkeypatch.setattr(cm, "_git_branch", lambda path: "main")
    monkeypatch.setattr(cm, "_log", lambda *args, **kwargs: None)

    def _fake_run(cmd: list[str], check: bool = True):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cm, "_run", _fake_run)

    payload = cm._action_update_template("main", force=True)

    checkout_cmd = next(cmd for cmd in calls if cmd[3] == "checkout")
    assert "-f" in checkout_cmd
    assert payload["force"] is True


def test_action_update_template_omits_force_checkout_by_default(cm, tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "hermes-agent"
    (source_root / ".git").mkdir(parents=True, exist_ok=True)
    (source_root / "cli.py").write_text("print('ok')\n", encoding="utf-8")

    calls: list[list[str]] = []

    monkeypatch.setattr(cm, "HERMES_SOURCE_ROOT", source_root)
    monkeypatch.setattr(cm, "_fetch_remote_branch", lambda path, branch: True)
    monkeypatch.setattr(cm, "_git_commit", lambda path: "abc123")
    monkeypatch.setattr(cm, "_git_branch", lambda path: "main")
    monkeypatch.setattr(cm, "_log", lambda *args, **kwargs: None)

    def _fake_run(cmd: list[str], check: bool = True):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cm, "_run", _fake_run)

    payload = cm._action_update_template("main")

    checkout_cmd = next(cmd for cmd in calls if cmd[3] == "checkout")
    assert "-f" not in checkout_cmd
    assert payload["force"] is False


def test_dispatch_passes_force_to_update_actions(cm) -> None:
    update_all_calls: list[dict[str, object]] = []
    update_node_calls: list[dict[str, object]] = []

    def _fake_update_all(source_branch: str, *, force: bool = False):
        update_all_calls.append({"source_branch": source_branch, "force": force})
        return {"ok": True}

    def _fake_update_node(clone_name: str, source_branch: str, *, force: bool = False):
        update_node_calls.append(
            {"clone_name": clone_name, "source_branch": source_branch, "force": force}
        )
        return {"ok": True}

    cm._action_update_all = _fake_update_all
    cm._action_update_node = _fake_update_node

    cm._dispatch(
        "update-all",
        None,
        image="",
        lines=80,
        source_branch="main",
        backup_all=False,
        restore_path="",
        logs_clean=False,
        source_name="",
        force=True,
        run_id="",
        confirm_token="",
    )
    cm._dispatch(
        "update-node",
        "colmeio",
        image="",
        lines=80,
        source_branch="main",
        backup_all=False,
        restore_path="",
        logs_clean=False,
        source_name="",
        force=True,
        run_id="",
        confirm_token="",
    )

    assert update_all_calls == [{"source_branch": "main", "force": True}]
    assert update_node_calls == [
        {"clone_name": "colmeio", "source_branch": "main", "force": True}
    ]
