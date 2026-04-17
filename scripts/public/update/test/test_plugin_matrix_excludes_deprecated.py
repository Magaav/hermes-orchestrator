from __future__ import annotations

from pathlib import Path


def test_plugin_matrix_marks_deprecated_as_skipped(cm, tmp_path: Path) -> None:
    log_path = tmp_path / "colmeio-prestart.log"
    log_path.write_text(
        "\n".join(
            [
                "[2026-01-01T00:00:00Z] STEP alpha: /local/plugins/public/plugin-a/scripts/a.py",
                "[2026-01-01T00:00:01Z] OK   alpha",
                "[2026-01-01T00:00:02Z] STEP beta: /local/plugins/public/plugin-b/scripts/b.py",
                "[2026-01-01T00:00:03Z] OK   beta",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    matrix = cm._build_plugin_matrix(
        prestart_log_path=log_path,
        deprecated_plugins=["plugin-b", "plugin-c"],
    )

    steps = matrix["steps"]
    alpha = next(step for step in steps if step["step"] == "alpha")
    beta = next(step for step in steps if step["step"] == "beta")
    synthetic = next(step for step in steps if step["plugin"] == "plugin-c")

    assert alpha["status"] == "passed"
    assert beta["status"] == "skipped_deprecated"
    assert synthetic["status"] == "skipped_deprecated"
    assert matrix["summary"]["failed"] == 0
    assert matrix["summary"]["skipped_deprecated"] >= 2


def test_deprecated_plugins_are_auto_detected_from_deprecated_dir(cm, tmp_path: Path) -> None:
    public_root = tmp_path / "plugins" / "public"
    (public_root / "deprecated" / "plugin-old").mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / "colmeio-prestart.log"
    log_path.write_text("", encoding="utf-8")

    auto_deprecated = cm._list_deprecated_plugins(public_root)
    matrix = cm._build_plugin_matrix(
        prestart_log_path=log_path,
        deprecated_plugins=auto_deprecated,
    )

    assert auto_deprecated == ["plugin-old"]
    assert matrix["summary"]["skipped_deprecated"] == 1
