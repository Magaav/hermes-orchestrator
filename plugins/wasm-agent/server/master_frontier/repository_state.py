"""Small worktree postimage verifier for causal V5 proof."""
from __future__ import annotations

import hashlib
import fnmatch
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
from typing import Any


MAX_VERIFY_FILE_BYTES = 4 * 1024 * 1024
MAX_GIT_OUTPUT_BYTES = 512 * 1024
MAX_ROUTE_STATE_FILES = 512
DEFAULT_ROUTE_STATE_BYTES = 8 * 1024 * 1024
MAX_ROUTE_STATE_BYTES = 64 * 1024 * 1024
GIT_TIMEOUT_SEC = 5.0


def digest(postimages: dict[str, str]) -> str:
    raw = json.dumps(postimages, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _git_output(argv: list[str], *, limit: int = MAX_GIT_OUTPUT_BYTES) -> tuple[int, bytes]:
    """Run one fixed Git query with bounded pipe memory and time."""
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, close_fds=True, start_new_session=True,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except OSError:
        return 127, b""
    assert proc.stdout is not None and proc.stderr is not None
    streams = selectors.DefaultSelector()
    stdout_fd, stderr_fd = proc.stdout.fileno(), proc.stderr.fileno()
    outputs = {stdout_fd: bytearray(), stderr_fd: bytearray()}
    for stream in (proc.stdout, proc.stderr):
        os.set_blocking(stream.fileno(), False)
        streams.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + GIT_TIMEOUT_SEC
    overflow = False
    while streams.get_map():
        if time.monotonic() >= deadline:
            overflow = True
            break
        for key, _mask in streams.select(0.05):
            try:
                chunk = os.read(key.fd, 64 * 1024)
            except BlockingIOError:
                continue
            if not chunk:
                streams.unregister(key.fileobj); key.fileobj.close(); continue
            target = outputs[key.fd]
            if len(target) + len(chunk) > limit:
                overflow = True
                break
            target.extend(chunk)
        if overflow:
            break
    if overflow:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    try: proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        proc.wait()
    streams.close()
    for stream in (proc.stdout, proc.stderr):
        if not stream.closed: stream.close()
    return (124 if overflow else int(proc.returncode or 0)), bytes(outputs[stdout_fd])


def _inside(candidate: Path, roots: list[Path]) -> bool:
    return any(candidate == root or root in candidate.parents for root in roots)


def _excluded(raw_path: bytes, patterns: list[str]) -> bool:
    try:
        relative = raw_path.decode("utf-8", "surrogateescape").replace("\\", "/").lstrip("./")
    except UnicodeError:
        return False
    candidates = (relative, "/" + relative)
    return any(fnmatch.fnmatch(candidate, pattern.lstrip("./")) for pattern in patterns for candidate in candidates)


def _route_state(route: dict[str, Any], root: Path, roots: list[Path]) -> dict[str, Any] | None:
    code, raw_git_root = _git_output(["git", "-C", str(root), "rev-parse", "--show-toplevel"], limit=4096)
    if code != 0:
        return None
    try:
        git_root = Path(raw_git_root.decode("utf-8", "strict").strip()).resolve(strict=True)
    except (OSError, RuntimeError, UnicodeError):
        return {"ok": False, "code": "worktree_git_root_invalid", "digest": ""}
    pathspecs: list[str] = []
    for allowed in roots:
        if allowed == git_root or git_root in allowed.parents:
            pathspecs.append(allowed.relative_to(git_root).as_posix() or ".")
    if not pathspecs:
        return None
    status_argv = [
        "git", "-C", str(git_root), "status", "--porcelain=v1", "-z",
        "--untracked-files=all", "--", *sorted(set(pathspecs)),
    ]
    code, status = _git_output(status_argv)
    if code != 0:
        return {"ok": False, "code": "worktree_git_status_unavailable", "digest": ""}
    source_index = route.get("source_index") if isinstance(route.get("source_index"), dict) else {}
    excludes = [str(value).replace("\\", "/") for value in source_index.get("exclude_globs") or [] if str(value).strip()]
    records = status.split(b"\0")
    paths: list[bytes] = []
    included_records: list[bytes] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            return {"ok": False, "code": "worktree_git_status_invalid", "digest": ""}
        state = record[:2]
        entry_paths = [record[3:]]
        if b"R" in state or b"C" in state:
            if index >= len(records) or not records[index]:
                return {"ok": False, "code": "worktree_git_status_invalid", "digest": ""}
            entry_paths.append(records[index]); index += 1
        if excludes and any(_excluded(path, excludes) for path in entry_paths):
            continue
        paths.extend(entry_paths)
        included_records.append(record)
        included_records.extend(entry_paths[1:])
        if len(paths) > MAX_ROUTE_STATE_FILES:
            return {"ok": False, "code": "worktree_route_state_too_many_files", "digest": ""}
    status = b"\0".join(included_records) + (b"\0" if included_records else b"")
    try:
        byte_limit = int(source_index.get("max_total_bytes") or DEFAULT_ROUTE_STATE_BYTES)
    except (TypeError, ValueError):
        byte_limit = DEFAULT_ROUTE_STATE_BYTES
    byte_limit = max(1, min(byte_limit, MAX_ROUTE_STATE_BYTES))
    code, head = _git_output(["git", "-C", str(git_root), "rev-parse", "--verify", "HEAD"], limit=4096)
    if code != 0:
        head = b"unborn"
    value = hashlib.sha256()
    value.update(b"master.frontier.route-state.v1\0" + head.strip() + b"\0" + status)
    total_bytes = 0
    for raw_path in sorted(set(paths)):
        try:
            relative = raw_path.decode("utf-8", "surrogateescape")
            candidate = (git_root / relative).resolve(strict=False)
        except (OSError, RuntimeError):
            return {"ok": False, "code": "worktree_route_path_invalid", "digest": ""}
        if not _inside(candidate, roots):
            return {"ok": False, "code": "worktree_route_path_outside_scope", "digest": ""}
        value.update(b"\0P\0" + raw_path + b"\0")
        try:
            before = candidate.lstat()
        except FileNotFoundError:
            value.update(b"deleted")
            continue
        except OSError:
            return {"ok": False, "code": "worktree_route_file_unreadable", "digest": ""}
        if candidate.is_symlink():
            try: value.update(b"symlink\0" + os.readlink(candidate).encode("utf-8", "surrogateescape"))
            except OSError: return {"ok": False, "code": "worktree_route_file_unreadable", "digest": ""}
            continue
        if not candidate.is_file():
            value.update(b"non-file")
            continue
        total_bytes += before.st_size
        if total_bytes > byte_limit:
            return {"ok": False, "code": "worktree_route_state_too_large", "digest": "", "bytes": total_bytes}
        try:
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(64 * 1024), b""):
                    value.update(chunk)
            after = candidate.stat()
        except OSError:
            return {"ok": False, "code": "worktree_route_file_unreadable", "digest": ""}
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            return {"ok": False, "code": "worktree_route_state_unstable", "digest": ""}
    return {"ok": True, "code": "ok", "digest": value.hexdigest(), "files": len(set(paths)), "bytes": total_bytes}


def verify(route: dict[str, Any], postimages: dict[str, str]) -> dict[str, Any]:
    raw_root = str(route.get("workspace_root") or "").strip()
    try:
        root = Path(raw_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return {"ok": False, "code": "worktree_root_missing", "digest": "", "mismatches": []}
    roots = []
    for value in route.get("allowed_write_roots") if isinstance(route.get("allowed_write_roots"), list) else []:
        try:
            raw = Path(str(value)).expanduser()
            roots.append((raw if raw.is_absolute() else root / raw).resolve())
        except (OSError, RuntimeError): continue
    if not roots:
        return {"ok": False, "code": "worktree_scope_missing", "digest": "", "mismatches": []}
    actual: dict[str, str] = {}
    mismatches: list[str] = []
    for relative, expected in sorted(postimages.items()):
        raw = str(relative or "")
        candidate = root / raw
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError):
            mismatches.append(raw); continue
        if not raw or Path(raw).is_absolute() or ".." in Path(raw).parts or not _inside(resolved, roots):
            mismatches.append(raw); continue
        if expected == "deleted":
            actual[raw] = "deleted" if not candidate.exists() and not candidate.is_symlink() else "present"
        else:
            try:
                stat = candidate.lstat()
                if candidate.is_symlink() or not candidate.is_file() or stat.st_size > MAX_VERIFY_FILE_BYTES:
                    raise OSError("ineligible postimage")
                value = hashlib.sha256()
                with candidate.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(64 * 1024), b""):
                        value.update(chunk)
                actual[raw] = value.hexdigest()
            except OSError:
                actual[raw] = "unreadable"
        if actual.get(raw) != expected:
            mismatches.append(raw)
    postimage_digest = digest(actual)
    route_state = _route_state(route, root, roots)
    if route_state is not None and route_state.get("ok") is not True:
        return {
            "ok": False, "code": str(route_state.get("code") or "worktree_route_state_unavailable"),
            "digest": "", "expected_digest": digest(postimages), "mismatches": mismatches[:32],
            "route_state": route_state,
        }
    combined = postimage_digest
    if route_state is not None:
        combined = hashlib.sha256((postimage_digest + ":" + str(route_state["digest"])).encode()).hexdigest()
    ok = not mismatches and bool(postimages)
    return {
        "ok": ok,
        "code": "ok" if ok else "worktree_postimage_mismatch",
        "digest": combined, "expected_digest": combined if ok else digest(postimages),
        "postimage_digest": postimage_digest,
        "route_state_sha256": str((route_state or {}).get("digest") or ""),
        "route_state": route_state or {"ok": True, "code": "not_git", "files": 0, "bytes": 0},
        "mismatches": mismatches[:32],
    }
