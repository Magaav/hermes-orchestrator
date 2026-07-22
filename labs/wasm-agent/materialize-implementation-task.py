#!/usr/bin/env python3
"""Materialize one immutable coding fixture into a private Git workspace."""

from __future__ import annotations

import hashlib
import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parent
FIXTURE_ROOT = LAB / "fixtures" / "implementation"
PROJECT_ROOT = LAB.parents[1]


def _digest_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def route_contract(workspace: Path, fixture_id: str) -> dict[str, Any]:
    root = str(workspace.resolve())
    return {
        "route_id": f"safe-lab.implementation.{fixture_id}",
        "owner": "labs/wasm-agent",
        "workspace_root": root,
        "allowed_read_roots": [root],
        "allowed_write_roots": [root],
        "allowed_write_paths": {
            "retry-window-v1": ["retry_window.py"],
            "challenge-evolution-v1": ["challenge_cases.py"],
            "widget-evolution-v1": ["meta-analysis-widget.js"],
        }[fixture_id],
        "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
        "source_index": {
            "include_roots": ["."],
            "exclude_globs": ["**/.git/**", "**/__pycache__/**"],
            "max_file_bytes": 65536,
            "max_total_bytes": 262144,
        },
        "checks": [{
            "id": {"retry-window-v1": "retry-window", "challenge-evolution-v1": "challenge-evolution", "widget-evolution-v1": "widget-syntax"}[fixture_id],
            "command": ["node", "--check", "meta-analysis-widget.js"] if fixture_id == "widget-evolution-v1" else ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"],
            "timeout_sec": 20,
            "description": "Retry-window focused unit tests",
        }],
        "proof": ["route_id", "changed_files", "checks", "diff", "postimages"],
        "task_contract": {
            "request_class": "implementation",
            "objective_kind": "implementation",
            "declared_classes": ["implementation"],
            "authority": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "proof_policy": "mutation_check_diff_proof",
            "evidence_floor": "proof",
            **({"decision_mode": "llm_autonomous"} if fixture_id in {"challenge-evolution-v1", "widget-evolution-v1"} else {}),
        },
    }


def materialize(fixture_id: str, workspace: Path) -> dict[str, Any]:
    if fixture_id not in {"retry-window-v1", "challenge-evolution-v1", "widget-evolution-v1"}:
        raise ValueError("implementation fixture is not registered")
    source = (
        PROJECT_ROOT / "plugins/wasm-agent/public/modules/meta-analysis"
        if fixture_id == "widget-evolution-v1" else FIXTURE_ROOT / fixture_id
    )
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("implementation workspace must be empty")
    workspace.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        target = workspace / relative
        if path.is_symlink():
            raise ValueError("implementation fixtures may not contain symlinks")
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.name", "WASM Agent Safe Lab"],
        ["git", "config", "user.email", "safe-lab.invalid"],
        ["git", "add", "."],
        ["git", "commit", "-q", "-m", "immutable fixture baseline"],
    ]
    for command in commands:
        completed = subprocess.run(command, cwd=workspace, capture_output=True, text=True, check=False)
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or "fixture Git initialization failed")
    if fixture_id == "retry-window-v1":
        objective = (
            "Fix expiration at the exact retry-window boundary. Preserve the public API, modify production code only, "
            "run the registered focused test, inspect the diff, and collect scoped proof."
        )
    elif fixture_id == "challenge-evolution-v1":
        objective = (
            "Evolve the behavioral curriculum in challenge_cases.py so it accepts the reference behavior and rejects "
            "every registered incorrect implementation within six cases. Do not edit the evaluator or tests. Run the "
            "registered focused check, inspect the diff, and collect scoped proof."
        )
    else:
        objective = (
            "Inspect the Meta-Analysis widget and make one meaningful, user-visible improvement to its usability, "
            "accessibility, resilience, or performance. Choose the improvement yourself. Keep the existing behavior "
            "compatible, modify only meta-analysis-widget.js, use your available tools as you judge appropriate, and "
            "explain what changed and how you verified it."
        )
    route = route_contract(workspace, fixture_id)
    task = {
        "schema": "wasm-agent.safe-lab.implementation-task.v1",
        "model": "frank/GLM-5.2",
        "fixture": {"id": fixture_id, "requestClass": "implementation"},
        "objective": objective,
        "fixtureSha256": _digest_tree(source),
        "route": route,
        "budgets": {
            "wallClockSeconds": 600 if fixture_id == "widget-evolution-v1" else 240,
            "maxProviderCalls": 16,
            "maxOutputTokensPerCall": 4096 if fixture_id in {"challenge-evolution-v1", "widget-evolution-v1"} else 2048,
            "providerCallTimeoutSeconds": 60,
            "maxAnswerBytes": 65536,
        },
        "adjudication": {"executionAllowed": True, "rankingAllowed": False},
    }
    task["taskDigest"] = hashlib.sha256(json.dumps(task, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return task


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-id", default="retry-window-v1")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    task = materialize(args.fixture_id, Path(args.workspace))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
