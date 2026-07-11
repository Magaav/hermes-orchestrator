#!/usr/bin/env python3
"""Guard frozen monoliths against casual growth and enforce shrink-on-touch."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "reports/context/latest/monolith-growth-result.json"

FROZEN_FILES = {
    "plugins/wasm-agent/public/app.js": {
        "owner": "plugins/wasm-agent/public",
        "target": "public/modules/* or owning feature module",
        "module_prefixes": ["plugins/wasm-agent/public/modules/"],
    },
    "plugins/wasm-agent/server/static_server.py": {
        "owner": "plugins/wasm-agent/server",
        "target": "server/master_frontier/* or server/routes/*",
        "module_prefixes": ["plugins/wasm-agent/server/master_frontier/", "plugins/wasm-agent/server/routes/"],
    },
    "plugins/wasm-agent/public/styles.css": {
        "owner": "plugins/wasm-agent/public",
        "target": "public/styles/* or owning feature stylesheet",
        "module_prefixes": ["plugins/wasm-agent/public/styles/", "plugins/wasm-agent/public/modules/"],
    },
    "scripts/public/clone/clone_manager.py": {
        "owner": "scripts/public/clone",
        "target": "scripts/public/clone/* owning lifecycle module",
        "module_prefixes": ["scripts/public/clone/"],
    },
    "native/windows/src/main.js": {
        "owner": "native/windows",
        "target": "native/windows/src/main/* coordinator module",
        "module_prefixes": ["native/windows/src/main/"],
    },
    "native/android/app/src/main/java/com/colmeio/wasmagent/MainActivity.kt": {
        "owner": "native/android",
        "target": "native/android/app/src/main/java/com/colmeio/wasmagent/*Coordinator.kt",
        "module_prefixes": ["native/android/app/src/main/java/com/colmeio/wasmagent/"],
    },
    "plugins/wasm-agent/server/routes.py": {
        "owner": "plugins/wasm-agent/server",
        "target": "server/routes/*, schemas, or route contract module",
        "module_prefixes": ["plugins/wasm-agent/server/routes/", "plugins/wasm-agent/server/master_frontier/"],
    },
}

SOURCE_EXTENSIONS = {
    ".css",
    ".js",
    ".json",
    ".kt",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".ts",
    ".tsx",
}

NEW_FILE_LINE_LIMIT = 1200
MONOLITH_LINE_LIMIT = 5000
MONOLITH_WARNING_LINE_LIMIT = 3000
EXCEPTION_RE = re.compile(
    r"ARCH_EXCEPTION:\s*owner=[^;\s]+;\s*reason=[^;]+;\s*expires=\d{4}-\d{2}-\d{2}",
)
ROUTE_BRANCH_RE = re.compile(r"^\+\s*(?:if|elif)\s+[^#\n]*(?:path|self\.path|parsed\.path)\s*(?:==|in|startswith\()")
DURABLE_LOGIC_RE = re.compile(
    r"^\+\s*(?:"
    r"def\s+(?!handle_|do_|_json|_send|main\b)[A-Za-z_][A-Za-z0-9_]*\s*\("
    r"|(?:async\s+)?function\s+(?!render|handle|on[A-Z])[A-Za-z_][A-Za-z0-9_]*\s*\("
    r"|(?:const|let|var)\s+[A-Z][A-Z0-9_]{3,}\s*="
    r"|class\s+[A-Za-z_][A-Za-z0-9_]*"
    r"|(?:if|elif)\s+.*\b(?:objective|intent|route_id|route|scope|proof|policy|capability|entity|widget|component)\b.*:"
    r"|direct_envelope_error\s*\("
    r"|finish_agent_run\s*\("
    r")"
)
DELEGATION_RE = re.compile(
    r"^\+\s*(?:return\s+)?(?:[A-Za-z_][A-Za-z0-9_]*\.)?[A-Za-z_][A-Za-z0-9_]*\("
)


def run_git(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def changed_files() -> list[str]:
    output = run_git(["diff", "--name-only", "--diff-filter=ACMRT", "HEAD", "--"])
    tracked = [line.strip() for line in output.splitlines() if line.strip()]
    untracked_output = run_git(["ls-files", "--others", "--exclude-standard"])
    untracked = [line.strip() for line in untracked_output.splitlines() if line.strip()]
    return list(dict.fromkeys([*tracked, *untracked]))


def parse_numstat() -> dict[str, tuple[int, int]]:
    output = run_git(["diff", "--numstat", "HEAD", "--"])
    stats: dict[str, tuple[int, int]] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or parts[0] == "-" or parts[1] == "-":
            continue
        stats[parts[2]] = (int(parts[0]), int(parts[1]))
    for path in run_git(["ls-files", "--others", "--exclude-standard"]).splitlines():
        clean = path.strip()
        if clean and clean not in stats:
            stats[clean] = (current_line_count(clean), 0)
    return stats


def added_lines(path: str) -> list[str]:
    if is_new_file(path):
        full_path = ROOT / path
        try:
            return ["+" + line.rstrip("\n") for line in full_path.read_text(encoding="utf-8", errors="ignore").splitlines()]
        except FileNotFoundError:
            return []
    diff = run_git(["diff", "--unified=0", "HEAD", "--", path])
    return [
        line
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def added_hunks(path: str) -> list[list[str]]:
    if is_new_file(path):
        return [added_lines(path)]
    diff = run_git(["diff", "--unified=0", "HEAD", "--", path])
    hunks: list[list[str]] = []
    current: list[str] = []
    for line in diff.splitlines():
        if line.startswith("@@"):
            if current:
                hunks.append(current)
            current = []
        elif line.startswith("+") and not line.startswith("+++"):
            current.append(line)
    if current:
        hunks.append(current)
    return hunks


def has_exception(lines: list[str]) -> bool:
    return any(EXCEPTION_RE.search(line) for line in lines)


def durable_logic_lines(path: str, lines: list[str]) -> list[str]:
    matches: list[str] = []
    for line in lines:
        stripped = line[1:].strip() if line.startswith("+") else line.strip()
        if not stripped or stripped.startswith("#") or "ARCH_EXCEPTION:" in stripped:
            continue
        if not DURABLE_LOGIC_RE.search(line):
            continue
        if DELEGATION_RE.search(line) and "." in stripped.split("(", 1)[0]:
            continue
        matches.append(line)
    return matches[:8]


def current_line_count(path: str) -> int:
    full_path = ROOT / path
    try:
        with full_path.open("r", encoding="utf-8", errors="ignore") as handle:
            return sum(1 for _ in handle)
    except FileNotFoundError:
        return 0


def is_source_file(path: str) -> bool:
    return Path(path).suffix in SOURCE_EXTENSIONS


def is_new_file(path: str) -> bool:
    output = run_git(["diff", "--name-status", "--diff-filter=A", "HEAD", "--", path])
    if output.strip():
        return True
    proc = subprocess.run(
        ["git", "ls-files", "--error-unmatch", path],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode != 0 and (ROOT / path).exists()


def touched_owned_module(files: list[str], frozen_path: str, prefixes: list[str]) -> bool:
    for path in files:
        if path == frozen_path:
            continue
        if any(path.startswith(prefix) for prefix in prefixes):
            return True
    return False


def check() -> dict[str, object]:
    stats = parse_numstat()
    files = changed_files()
    violations: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []

    for path in files:
        hunks = added_hunks(path)
        lines = [line for hunk in hunks for line in hunk]
        unexcepted_lines = [line for hunk in hunks if not has_exception(hunk) for line in hunk]
        exception = bool(hunks) and not unexcepted_lines
        additions, deletions = stats.get(path, (0, 0))

        if path in FROZEN_FILES:
            meta = FROZEN_FILES[path]
            if additions >= deletions and not exception:
                violations.append(
                    {
                        "code": "monolith_touch_without_net_shrink",
                        "file": path,
                        "added": additions,
                        "deleted": deletions,
                        "owner": meta["owner"],
                        "target": meta["target"],
                        "next": "classify why this belongs in the monolith, then extract/remove enough touched logic into the owning module for a net shrink or add a temporary ARCH_EXCEPTION marker",
                    }
                )
            if additions > 0 and not exception and not touched_owned_module(files, path, list(meta.get("module_prefixes", []))):
                violations.append(
                    {
                        "code": "monolith_addition_without_owned_module",
                        "file": path,
                        "added": additions,
                        "deleted": deletions,
                        "owner": meta["owner"],
                        "target": meta["target"],
                        "next": "move durable logic into an existing/new owned module and leave only delegation/removal in the frozen monolith, or add a temporary ARCH_EXCEPTION marker for unavoidable bootstrap wiring",
                    }
                )
            if path == "plugins/wasm-agent/server/static_server.py":
                route_branch_lines = [line for line in unexcepted_lines if ROUTE_BRANCH_RE.search(line)]
                if route_branch_lines:
                    violations.append(
                        {
                            "code": "route_branch_in_static_server",
                            "file": path,
                            "matches": route_branch_lines[:5],
                            "target": "declare route ownership in a route contract or owning route module",
                        }
                    )
            durable_lines = durable_logic_lines(path, unexcepted_lines)
            if durable_lines:
                violations.append(
                    {
                        "code": "durable_logic_in_frozen_monolith",
                        "file": path,
                        "matches": durable_lines,
                        "owner": meta["owner"],
                        "target": meta["target"],
                        "next": "move helper/policy/final-shaping logic to the owning module; frozen monolith additions should be delegation, HTTP/run wiring, compatibility shims, or explicit ARCH_EXCEPTION only",
                    }
                )

        if is_source_file(path):
            line_count = current_line_count(path)
            if line_count >= MONOLITH_LINE_LIMIT and path not in FROZEN_FILES and additions > 0 and not exception:
                violations.append(
                    {
                        "code": "monolith_sized_source_file_touched",
                        "file": path,
                        "lines": line_count,
                        "limit": MONOLITH_LINE_LIMIT,
                        "added": additions,
                        "deleted": deletions,
                        "next": "treat this file as a monolith-class surface: move durable logic into smaller owned modules and leave only delegation/removal, or add a temporary ARCH_EXCEPTION marker with a modularization reason",
                    }
                )
            elif line_count >= MONOLITH_WARNING_LINE_LIMIT and path not in FROZEN_FILES:
                warnings.append(
                    {
                        "code": "large_source_file_modularization_warning",
                        "file": path,
                        "lines": line_count,
                        "limit": MONOLITH_LINE_LIMIT,
                    }
                )

        if is_new_file(path) and is_source_file(path):
            line_count = current_line_count(path)
            if line_count > NEW_FILE_LINE_LIMIT and not exception:
                violations.append(
                    {
                        "code": "new_monolith_file",
                        "file": path,
                        "lines": line_count,
                        "limit": NEW_FILE_LINE_LIMIT,
                        "next": "split the new file by ownership before landing it",
                    }
                )
            elif line_count > NEW_FILE_LINE_LIMIT // 2:
                warnings.append(
                    {
                        "code": "large_new_file_warning",
                        "file": path,
                        "lines": line_count,
                        "limit": NEW_FILE_LINE_LIMIT,
                    }
                )

    return {
        "ok": not violations,
        "classification": "monolith_shrink_on_touch_pass" if not violations else "monolith_shrink_on_touch_blocked",
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "frozenFiles": sorted(FROZEN_FILES),
        "monolithLineLimit": MONOLITH_LINE_LIMIT,
        "monolithWarningLineLimit": MONOLITH_WARNING_LINE_LIMIT,
        "exceptionPattern": "ARCH_EXCEPTION: owner=<id>; reason=<why>; expires=YYYY-MM-DD",
        "violations": violations,
        "warnings": warnings,
    }


def self_test() -> int:
    cases = [
        (
            "blocks helper defs",
            ["+def direct_head_repo_object_needs_runtime_scope_proof(envelope):"],
            True,
        ),
        (
            "blocks policy branches",
            ["+    if objective and scope_id and not proof:"],
            True,
        ),
        (
            "allows module delegation",
            ["+    return master_frontier_entity_resolution.needs_runtime_scope_proof(envelope)"],
            False,
        ),
        (
            "allows event wiring assignment",
            ['+    payload = {"code": code, "route_id": route_id}'],
            False,
        ),
        (
            "blocks final shaping",
            ["+        finish_agent_run(server, run_id, status=\"failed\", final=final)"],
            True,
        ),
        (
            "blocks pre-code gate violations that start with monolith policy helpers",
            ["+def build_scoped_repo_object_answer_policy(envelope, evidence):"],
            True,
        ),
    ]
    failures: list[str] = []
    for label, lines, should_block in cases:
        blocked = bool(durable_logic_lines("plugins/wasm-agent/server/static_server.py", lines))
        if blocked != should_block:
            failures.append(f"{label}: expected {should_block}, got {blocked}")
    if MONOLITH_LINE_LIMIT != 5000:
        failures.append(f"monolith line limit drifted: expected 5000, got {MONOLITH_LINE_LIMIT}")
    if not has_exception(["+# ARCH_EXCEPTION: owner=test; reason=bounded wiring; expires=2099-01-01"]):
        failures.append("valid hunk exception was not recognized")
    if has_exception(["+def policy():", "+    return True"]):
        failures.append("unmarked hunk was treated as excepted")
    if not is_source_file("example.py") or is_source_file("example.txt"):
        failures.append("source file classifier drifted")
    if failures:
        print("Monolith growth guard self-test: FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Monolith growth guard self-test: PASS")
    return 0


def main() -> int:
    if "--self-test" in __import__("sys").argv:
        return self_test()
    report = check()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Monolith growth guard: {'PASS' if report['ok'] else 'FAIL'} ({report['classification']})")
    print(f"Report JSON: {REPORT_PATH.relative_to(ROOT)}")
    for violation in report["violations"]:
        print(f"- {violation['code']}: {violation['file']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
