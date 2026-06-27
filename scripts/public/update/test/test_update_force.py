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


def test_action_update_template_can_checkout_release_tag(cm, tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "hermes-agent"
    (source_root / ".git").mkdir(parents=True, exist_ok=True)
    (source_root / "cli.py").write_text("print('ok')\n", encoding="utf-8")

    calls: list[list[str]] = []

    monkeypatch.setattr(cm, "HERMES_SOURCE_ROOT", source_root)
    monkeypatch.setattr(cm, "_fetch_remote_branch", lambda path, branch: False)
    monkeypatch.setattr(cm, "_fetch_remote_tag", lambda path, tag: True)
    monkeypatch.setattr(cm, "_git_commit", lambda path: "def456")
    monkeypatch.setattr(cm, "_git_branch", lambda path: "HEAD")
    monkeypatch.setattr(cm, "_log", lambda *args, **kwargs: None)

    def _fake_run(cmd: list[str], check: bool = True):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cm, "_run", _fake_run)

    payload = cm._action_update_template("v2026.6.19")

    checkout_cmd = next(cmd for cmd in calls if cmd[3] == "checkout")
    assert "--detach" in checkout_cmd
    assert "-B" not in checkout_cmd
    assert checkout_cmd[-1] == "refs/tags/v2026.6.19"
    clean_cmd = next(cmd for cmd in calls if cmd[3] == "clean")
    assert ".gitkeep" in clean_cmd
    assert payload["source_ref_type"] == "tag"
    assert payload["remote_ref"] == "refs/tags/v2026.6.19"
    assert payload["preserved_paths"] == [".venv", ".gitkeep", ".git"]


def test_seed_code_tree_removes_stale_destination_git(cm, tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    (source_root / "cli.py").write_text("print('ok')\n", encoding="utf-8")
    (dest_root / ".git").mkdir(parents=True)

    calls: list[list[str]] = []

    monkeypatch.setattr(
        cm.shutil,
        "which",
        lambda name: "/usr/bin/rsync" if name == "rsync" else None,
    )

    def _fake_run(cmd: list[str], check: bool = True):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cm, "_run", _fake_run)

    cm._seed_code_tree(source_root, dest_root, include_git=False)

    assert not (dest_root / ".git").exists()
    assert calls


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
