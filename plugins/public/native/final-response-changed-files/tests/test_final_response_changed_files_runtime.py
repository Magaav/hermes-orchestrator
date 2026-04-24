from __future__ import annotations

import importlib.util
from pathlib import Path


RUNTIME_PATH = Path("/local/plugins/public/native/final-response-changed-files/runtime.py")


def _load_runtime():
    spec = importlib.util.spec_from_file_location("final_response_changed_files_runtime", RUNTIME_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load runtime from {RUNTIME_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_files_changed_footer_keeps_created_deleted_and_updated():
    runtime = _load_runtime()

    footer = runtime.render_files_changed_footer(
        [
            {"path": "a.txt", "status": "created", "add": 1, "del": 0},
            {"path": "b.txt", "status": "deleted", "add": 0, "del": 2},
            {"path": "c.txt", "status": "updated", "add": 1, "del": 1},
        ]
    )

    assert footer.startswith("📁 Files changed +2 -1")
    assert "Updated:" in footer
    assert "Created:" in footer
    assert "Deleted:" in footer
    assert "- a.txt +1 -0" in footer
    assert "- b.txt" in footer
    assert "- c.txt +1 -1" in footer


def test_transform_final_response_appends_created_write_file(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGIN_FINAL_RESPONSE_FILES_CHANGED", "true")
    monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))

    runtime.reset_turn_state(session_id="sess-1")
    runtime.record_pre_tool_snapshot(
        tool_name="write_file",
        args={"path": "new.txt"},
        session_id="sess-1",
        tool_call_id="tool-1",
    )
    runtime.record_post_tool_result(
        tool_name="write_file",
        args={"path": "new.txt", "content": "one\ntwo\nthree\n"},
        result='{"bytes_written": 14}',
        session_id="sess-1",
        tool_call_id="tool-1",
    )

    transformed = runtime.transform_final_response(
        session_id="sess-1",
        assistant_response="Done.",
    )

    assert transformed is not None
    assert transformed.startswith("Done.\n\n📁 Files changed +3 -0")
    assert "Created:" in transformed
    assert "- new.txt +3 -0" in transformed


def test_transform_final_response_marks_updated_write_file(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGIN_FINAL_RESPONSE_FILES_CHANGED", "true")
    monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))
    (tmp_path / "existing.txt").write_text("before\nkeep\n", encoding="utf-8")

    runtime.reset_turn_state(session_id="sess-2")
    runtime.record_pre_tool_snapshot(
        tool_name="write_file",
        args={"path": "existing.txt"},
        session_id="sess-2",
        tool_call_id="tool-2",
    )
    runtime.record_post_tool_result(
        tool_name="write_file",
        args={"path": "existing.txt", "content": "keep\nnew\n"},
        result='{"bytes_written": 9}',
        session_id="sess-2",
        tool_call_id="tool-2",
    )

    transformed = runtime.transform_final_response(
        session_id="sess-2",
        assistant_response="Done.",
    )

    assert transformed is not None
    assert "📁 Files changed +1 -1" in transformed
    assert "Updated:" in transformed
    assert "- existing.txt +1 -1" in transformed


def test_transform_final_response_uses_patch_payload_lists(monkeypatch):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGIN_FINAL_RESPONSE_FILES_CHANGED", "true")

    runtime.reset_turn_state(session_id="sess-3")
    runtime.record_post_tool_result(
        tool_name="patch",
        args={"mode": "patch"},
        result=(
            '{"success": true, "files_modified": ["a.py"], '
            '"files_created": ["b.py"], "files_deleted": ["c.py"], '
            '"diff": "diff --git a/a.py b/a.py\\n--- a/a.py\\n+++ b/a.py\\n@@ -1 +1 @@\\n-old\\n+new\\n'
            'diff --git a/b.py b/b.py\\n--- /dev/null\\n+++ b/b.py\\n@@ -0,0 +1,2 @@\\n+one\\n+two\\n'
            'diff --git a/c.py b/c.py\\n--- a/c.py\\n+++ /dev/null\\n@@ -1,2 +0,0 @@\\n-old1\\n-old2\\n"}'
        ),
        session_id="sess-3",
        tool_call_id="tool-3",
    )

    transformed = runtime.transform_final_response(
        session_id="sess-3",
        assistant_response="Done.",
    )

    assert transformed is not None
    assert "📁 Files changed +3 -1" in transformed
    assert "Updated:" in transformed
    assert "Created:" in transformed
    assert "Deleted:" in transformed
    assert "- a.py +1 -1" in transformed
    assert "- b.py +2 -0" in transformed
    assert "- c.py" in transformed


def test_transform_final_response_accumulates_same_file_across_turn_tools(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGIN_FINAL_RESPONSE_FILES_CHANGED", "true")
    monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))

    runtime.reset_turn_state(session_id="sess-4")

    runtime.record_pre_tool_snapshot(
        tool_name="write_file",
        args={"path": "file.txt"},
        session_id="sess-4",
        tool_call_id="tool-4a",
    )
    runtime.record_post_tool_result(
        tool_name="write_file",
        args={"path": "file.txt", "content": "one\n"},
        result='{"bytes_written": 4}',
        session_id="sess-4",
        tool_call_id="tool-4a",
    )

    (tmp_path / "file.txt").write_text("one\n", encoding="utf-8")
    runtime.record_pre_tool_snapshot(
        tool_name="write_file",
        args={"path": "file.txt"},
        session_id="sess-4",
        tool_call_id="tool-4b",
    )
    runtime.record_post_tool_result(
        tool_name="write_file",
        args={"path": "file.txt", "content": "one\ntwo\n"},
        result='{"bytes_written": 8}',
        session_id="sess-4",
        tool_call_id="tool-4b",
    )

    transformed = runtime.transform_final_response(
        session_id="sess-4",
        assistant_response="Done.",
    )

    assert transformed is not None
    assert "📁 Files changed +2 -0" in transformed
    assert "Created:" in transformed
    assert "- file.txt +2 -0" in transformed


def test_reset_turn_state_clears_previous_session_changes(monkeypatch, tmp_path):
    runtime = _load_runtime()
    monkeypatch.setenv("PLUGIN_FINAL_RESPONSE_FILES_CHANGED", "true")
    monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))

    runtime.reset_turn_state(session_id="sess-5")
    runtime.record_pre_tool_snapshot(
        tool_name="write_file",
        args={"path": "file.txt"},
        session_id="sess-5",
        tool_call_id="tool-5",
    )
    runtime.record_post_tool_result(
        tool_name="write_file",
        args={"path": "file.txt", "content": "one\n"},
        result='{"bytes_written": 4}',
        session_id="sess-5",
        tool_call_id="tool-5",
    )

    first = runtime.transform_final_response(
        session_id="sess-5",
        assistant_response="Done once.",
    )
    runtime.reset_turn_state(session_id="sess-5")
    second = runtime.transform_final_response(
        session_id="sess-5",
        assistant_response="Done again.",
    )

    assert first is not None
    assert "📁 Files changed +1 -0" in first
    assert second == "Done again."
