from __future__ import annotations

import re
from pathlib import Path


NATIVE_ROOT = Path(__file__).resolve().parents[1]
HIDDEN_WORKSPACE_RE = re.compile(r"\.[A-Za-z0-9-]+-workspace")


def test_native_plugin_runtimes_do_not_define_hidden_repo_root_workspaces():
    offenders: list[str] = []
    for runtime_path in sorted(NATIVE_ROOT.glob("*/runtime.py")):
        text = runtime_path.read_text(encoding="utf-8")
        matches = sorted(set(HIDDEN_WORKSPACE_RE.findall(text)))
        if matches:
            offenders.append(f"{runtime_path}: {', '.join(matches)}")
    assert not offenders, "Hidden repo-root plugin workspaces are forbidden:\n" + "\n".join(offenders)
