"""Bounded Git worktree receipts for route-scoped repository proof.

The primitive deliberately uses one porcelain-status pass.  It executes Git
directly (never through a shell), sends process output to disk-backed temporary
files, and retains only bounded projections in memory.  Porcelain v1 with NUL
separators preserves staged/worktree state, renames, deletes, and untracked
paths without parsing human-formatted arrows or quoted filenames.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from typing import Any


SCHEMA = "master.frontier.repository_diff.v1"
MAX_ENTRIES = 512
MAX_OUTPUT_BYTES = 64 * 1024
MAX_STATUS_BYTES = 1024 * 1024
MAX_PATH_BYTES = 1024


@dataclass(frozen=True)
class _GitResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool = False


def _bounded_read(handle: Any, limit: int) -> tuple[bytes, bool]:
    handle.seek(0)
    value = handle.read(limit + 1)
    return value[:limit], len(value) > limit


def _git_status(root: Path, *, timeout_sec: float, capture_bytes: int) -> _GitResult:
    argv = [
        "git", "--no-optional-locks", "-c", "color.ui=false",
        "-c", "core.quotepath=false", "-c", "status.relativePaths=true",
        "-C", str(root), "status", "--porcelain=v1", "-z", "--renames",
        "--untracked-files=all", "--", ".",
    ]
    env = {
        key: value for key, value in os.environ.items()
        if key in {"PATH", "HOME", "SYSTEMROOT", "WINDIR", "PATHEXT", "TMPDIR", "TEMP", "TMP"}
    }
    env.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "LANG": "C"})
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed executable and arguments; shell is disabled.
                argv, stdout=stdout, stderr=stderr, env=env, shell=False,
                start_new_session=os.name == "posix",
            )
        except OSError as exc:
            message = str(exc).encode("utf-8", errors="replace")
            return _GitResult(127, b"", message[:capture_bytes], False, len(message) > capture_bytes)
        timed_out = False
        try:
            returncode = process.wait(timeout=max(0.1, min(float(timeout_sec), 30.0)))
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:  # pragma: no cover - production server is POSIX; keep the primitive portable.
                process.kill()
            returncode = process.wait()
        stdout_value, stdout_truncated = _bounded_read(stdout, capture_bytes)
        stderr_value, stderr_truncated = _bounded_read(stderr, capture_bytes)
    return _GitResult(
        int(returncode), stdout_value, stderr_value,
        stdout_truncated, stderr_truncated, timed_out,
    )


def _clip_path(raw: bytes) -> tuple[str, bool]:
    clipped = raw[:MAX_PATH_BYTES]
    return clipped.decode("utf-8", errors="replace"), len(raw) > MAX_PATH_BYTES


def _safe_relative(path: str) -> bool:
    candidate = Path(path)
    return bool(path) and not candidate.is_absolute() and ".." not in candidate.parts


def _kind(status: str) -> str:
    if status == "??":
        return "untracked"
    if status in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}:
        return "conflicted"
    if "R" in status:
        return "renamed"
    if "C" in status:
        return "copied"
    if "D" in status:
        return "deleted"
    if "A" in status:
        return "added"
    if "T" in status:
        return "type_changed"
    if "M" in status:
        return "modified"
    return "unknown"


def _entry(status: str, path_raw: bytes, old_raw: bytes | None) -> tuple[dict[str, Any] | None, bool]:
    path, path_truncated = _clip_path(path_raw)
    old_path, old_truncated = _clip_path(old_raw) if old_raw is not None else ("", False)
    if not _safe_relative(path) or (old_path and not _safe_relative(old_path)):
        return None, True
    untracked = status == "??"
    value: dict[str, Any] = {
        "path": path,
        "status": status,
        "kind": _kind(status),
        "staged": not untracked and status[0] not in {" ", "?", "!"},
        "worktree": untracked or status[1] not in {" ", "!"},
    }
    if old_path:
        value["old_path"] = old_path
    return value, path_truncated or old_truncated


def _parse_status(raw: bytes, *, max_entries: int, capture_truncated: bool) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    tokens = raw.split(b"\0")
    malformed = bool(raw and not raw.endswith(b"\0"))
    entries: list[dict[str, Any]] = []
    extra_entries = False
    path_truncated = False
    index = 0
    while index < len(tokens):
        record = tokens[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            malformed = True
            continue
        status = record[:2].decode("ascii", errors="replace")
        old_raw: bytes | None = None
        if "R" in status or "C" in status:
            if index >= len(tokens) or not tokens[index]:
                malformed = True
                break
            # Under porcelain -z the destination is in the status record and
            # the source path follows it (the reverse of the human format).
            old_raw = tokens[index]
            index += 1
        value, clipped = _entry(status, record[3:], old_raw)
        path_truncated = path_truncated or clipped
        if value is None:
            malformed = True
            continue
        if len(entries) < max_entries:
            entries.append(value)
        else:
            extra_entries = True
    return entries, {
        "entries": extra_entries or capture_truncated,
        "status_bytes": capture_truncated,
        "paths": path_truncated,
        "malformed": malformed,
    }


def _route_relative(entries: list[dict[str, Any]], root: Path) -> tuple[list[dict[str, Any]], bool]:
    repository_root = next((candidate for candidate in (root, *root.parents) if (candidate / ".git").exists()), root)
    try:
        prefix = root.relative_to(repository_root).as_posix().strip("/")
    except ValueError:
        return [], True
    if prefix in {"", "."}:
        return entries, False
    marker = prefix + "/"
    projected = []
    for item in entries:
        value = dict(item)
        for key in ("path", "old_path"):
            path = str(value.get(key) or "")
            if not path:
                continue
            if not path.startswith(marker):
                return [], True
            value[key] = path[len(marker):]
        projected.append(value)
    return projected, False


def _display_path(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")


def _render(entries: list[dict[str, Any]], limit: int) -> tuple[str, bool]:
    lines = []
    for item in entries:
        path = _display_path(str(item["path"]))
        old = _display_path(str(item.get("old_path") or ""))
        lines.append(f"{item['status']} {path}" + (f" <- {old}" if old else ""))
    raw = "\n".join(lines).encode("utf-8", errors="replace")
    clipped = raw[:limit]
    return clipped.decode("utf-8", errors="ignore"), len(raw) > limit


def _empty_stat() -> dict[str, Any]:
    return {
        "reported": 0, "complete": False, "staged": 0, "worktree": 0,
        "modified": 0, "added": 0, "deleted": 0, "renamed": 0,
        "copied": 0, "untracked": 0, "conflicted": 0, "type_changed": 0,
        "unknown": 0,
    }


def _result(
    *, route_id: str, ok: bool, code: str, returncode: int,
    changed_files: list[dict[str, Any]] | None = None,
    stat: dict[str, Any] | None = None, output: str = "",
    truncation: dict[str, bool] | None = None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA, "ok": ok, "code": code, "route_id": route_id,
        "returncode": int(returncode), "changed_files": changed_files or [],
        "stat": stat or _empty_stat(), "output": output,
        "truncation": truncation or {
            "entries": False, "output": False, "status_bytes": False,
            "stderr": False, "paths": False, "malformed": False,
        },
    }


def collect(
    route: dict[str, Any], *, max_entries: int = 128,
    max_output_bytes: int = 24 * 1024, max_status_bytes: int = 256 * 1024,
    timeout_sec: float = 10.0,
) -> dict[str, Any]:
    """Return a complete, bounded status receipt or an explicit typed failure."""
    route_id = str(route.get("route_id") or "") if isinstance(route, dict) else ""
    raw_root = str(route.get("workspace_root") or "").strip() if isinstance(route, dict) else ""
    try:
        root = Path(raw_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return _result(route_id=route_id, ok=False, code="diff_root_missing", returncode=2)
    if not raw_root or not root.is_dir():
        return _result(route_id=route_id, ok=False, code="diff_root_missing", returncode=2)

    entry_limit = max(1, min(int(max_entries), MAX_ENTRIES))
    output_limit = max(256, min(int(max_output_bytes), MAX_OUTPUT_BYTES))
    status_limit = max(4096, min(int(max_status_bytes), MAX_STATUS_BYTES))
    run = _git_status(root, timeout_sec=timeout_sec, capture_bytes=status_limit)
    if run.timed_out:
        error = run.stderr[:output_limit].decode("utf-8", errors="replace")
        return _result(route_id=route_id, ok=False, code="diff_timeout", returncode=124, output=error)
    if run.returncode != 0:
        error_raw = run.stderr or run.stdout
        error = error_raw[:output_limit].decode("utf-8", errors="replace")
        truncation = {
            "entries": False, "output": len(error_raw) > output_limit,
            "status_bytes": run.stdout_truncated, "stderr": run.stderr_truncated,
            "paths": False, "malformed": False,
        }
        code = "git_unavailable" if run.returncode == 127 else "diff_not_repository"
        return _result(
            route_id=route_id, ok=False, code=code, returncode=run.returncode,
            output=error, truncation=truncation,
        )

    changed, truncation = _parse_status(
        run.stdout, max_entries=entry_limit, capture_truncated=run.stdout_truncated,
    )
    changed, outside_route = _route_relative(changed, root)
    truncation["malformed"] = truncation["malformed"] or outside_route
    output, output_truncated = _render(changed, output_limit)
    truncation.update({"output": output_truncated, "stderr": run.stderr_truncated})
    counts = Counter(str(item["kind"]) for item in changed)
    incomplete = any(truncation[key] for key in ("entries", "status_bytes", "paths", "malformed"))
    stat = _empty_stat()
    stat.update({
        "reported": len(changed), "complete": not incomplete,
        "staged": sum(bool(item["staged"]) for item in changed),
        "worktree": sum(bool(item["worktree"]) for item in changed),
    })
    for key in ("modified", "added", "deleted", "renamed", "copied", "untracked", "conflicted", "type_changed", "unknown"):
        stat[key] = counts[key]
    canonical = json.dumps(changed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    result = _result(
        route_id=route_id, ok=not incomplete,
        code="ok" if not incomplete else "diff_receipt_truncated",
        returncode=run.returncode, changed_files=changed, stat=stat,
        output=output, truncation=truncation,
    )
    result["receipt_sha256"] = hashlib.sha256(canonical.encode("ascii")).hexdigest()
    return result
