"""Bounded, route-scoped and redacted repository reads."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from typing import Any, BinaryIO, Iterator


MAX_READ_BYTES = 96 * 1024
MAX_HASH_BYTES = 4 * 1024 * 1024
STREAM_CHUNK_BYTES = 64 * 1024
DENIED_NAMES = frozenset({".env", "wa.env", "credentials", "credentials.json", "id_rsa", "id_ed25519"})
DENIED_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".keystore", ".jks", ".sqlite", ".db", ".wasm", ".onnx", ".zip", ".gz"})
SECRET_ASSIGNMENT = re.compile(
    r"(?im)^(?P<prefix>\s*(?:\d+:\s*)?[\"']?[A-Za-z0-9_.-]*"
    r"(?:api[_-]?key|apikey|authorization|access[_-]?token|refresh[_-]?token|token|secret|password|passwd|"
    r"private[_-]?key|client[_-]?secret|aws[_-]?(?:access[_-]?key[_-]?id|secret[_-]?access[_-]?key)|database[_-]?url)"
    r"[A-Za-z0-9_.-]*[\"']?\s*[:=]\s*)(?P<value>[^\r\n]+)$"
)
TOKEN_LIKE = re.compile(
    r"(?i)\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b|"
    r"\bAKIA[A-Z0-9]{12,}\b|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}")
URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^\s/:@]+):(?P<password>[^\s/@]+)@", re.I)


class RepositoryReadError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message); self.code = code


def _roots(route: dict[str, Any]) -> tuple[Path, list[Path]]:
    raw_root = str(route.get("workspace_root") or "").strip()
    if not raw_root:
        raise RepositoryReadError("route_contract_missing", "Repository read requires a workspace root.")
    root = Path(raw_root).expanduser().resolve()
    allowed: list[Path] = []
    for item in route.get("allowed_read_roots") if isinstance(route.get("allowed_read_roots"), list) else []:
        try:
            allowed.append(Path(str(item)).expanduser().resolve())
        except OSError:
            continue
    if not allowed:
        raise RepositoryReadError("file_read_scope_denied", "The route declares no readable roots.")
    return root, allowed


def resolve(route: dict[str, Any], value: str) -> tuple[Path, str]:
    root, allowed = _roots(route)
    raw = str(value or "").strip()
    candidate = Path(raw).expanduser()
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not raw or not any(path == base or base in path.parents for base in allowed):
        raise RepositoryReadError("file_read_scope_denied", "Requested path is outside the routed workspace.")
    if path.name.lower() in DENIED_NAMES or path.suffix.lower() in DENIED_SUFFIXES or any(part.lower() in {".git", "state", "node_modules", "__pycache__"} for part in path.parts):
        raise RepositoryReadError("file_read_sensitive", "Requested path is not eligible for model-facing source reads.")
    if not path.is_file():
        raise RepositoryReadError("file_read_missing", "Requested route file does not exist.")
    try:
        relative = str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        relative = raw
    return path, relative


def redact(text: str) -> tuple[str, bool]:
    value = SECRET_ASSIGNMENT.sub(lambda match: match.group("prefix") + "[redacted]", text)
    value = TOKEN_LIKE.sub("[redacted]", value)
    value = BEARER.sub("Bearer [redacted]", value)
    value = URL_CREDENTIALS.sub(lambda match: match.group("scheme") + "[redacted]@", value)
    return value, value != text


def iter_bounded_lines(
    handle: BinaryIO, *, max_bytes: int | None = None,
    max_line_bytes: int = MAX_READ_BYTES, stats: dict[str, Any] | None = None,
    digest: Any | None = None,
) -> Iterator[tuple[int, bytes, bool]]:
    """Yield logical lines with fixed chunk and line-buffer memory bounds."""
    state = stats if stats is not None else {}
    state.update({
        "bytes_scanned": 0, "complete": False,
        "stream_chunk_bytes": STREAM_CHUNK_BYTES,
        "line_buffer_bytes_max": max(1, int(max_line_bytes)),
    })
    scan_limit = None if max_bytes is None else max(0, int(max_bytes))
    line_limit = max(1, int(max_line_bytes))
    line = bytearray()
    line_clipped = False
    line_number = 0

    def retain(raw: bytes) -> None:
        nonlocal line_clipped
        room = line_limit - len(line)
        if room > 0:
            line.extend(raw[:room])
        if len(raw) > room:
            line_clipped = True

    while scan_limit is None or state["bytes_scanned"] < scan_limit:
        remaining = STREAM_CHUNK_BYTES if scan_limit is None else min(
            STREAM_CHUNK_BYTES, scan_limit - state["bytes_scanned"],
        )
        chunk = handle.read(remaining)
        if not chunk:
            state["complete"] = True
            break
        state["bytes_scanned"] += len(chunk)
        if digest is not None:
            digest.update(chunk)
        offset = 0
        while offset < len(chunk):
            newline = chunk.find(b"\n", offset)
            if newline < 0:
                retain(chunk[offset:])
                break
            retain(chunk[offset:newline])
            if line.endswith(b"\r"):
                del line[-1:]
            line_number += 1
            state["lines_scanned"] = line_number
            yield line_number, bytes(line), line_clipped
            line.clear(); line_clipped = False; offset = newline + 1

    if line or line_clipped:
        # At EOF this is a complete unterminated line. At a byte ceiling it is
        # intentionally exposed as a clipped partial line instead of vanishing.
        line_number += 1
        state["lines_scanned"] = line_number
        yield line_number, bytes(line), line_clipped or not state["complete"]
    state["lines_scanned"] = line_number


def read_lines(
    route: dict[str, Any], value: str, *, start_line: int = 1, end_line: int | None = None,
    max_bytes: int = MAX_READ_BYTES, max_scan_bytes: int | None = None,
) -> dict[str, Any]:
    path, relative = resolve(route, value)
    start = max(1, int(start_line or 1))
    requested_end = max(start, int(end_line or (start + 499)))
    requested_end = min(requested_end, start + 999)
    byte_limit = max(1024, min(int(max_bytes), MAX_READ_BYTES))
    explicit_scan_limit = None if max_scan_bytes is None else max(byte_limit, int(max_scan_bytes))
    scan: dict[str, Any] = {}
    selected: list[str] = []
    selected_bytes = 0
    last_line = start - 1
    selected_line_clipped = False
    with path.open("rb") as handle:
        file_bytes = os.fstat(handle.fileno()).st_size
        iterator_limit = explicit_scan_limit
        if iterator_limit is not None and iterator_limit >= file_bytes:
            iterator_limit = None
        digest = hashlib.sha256() if file_bytes <= MAX_HASH_BYTES else None
        for index, raw_line, line_clipped in iter_bounded_lines(
            handle, max_bytes=iterator_limit, max_line_bytes=byte_limit, stats=scan, digest=digest,
        ):
            if start <= index <= requested_end and selected_bytes < byte_limit:
                rendered = f"{index}: {raw_line.decode('utf-8', 'replace')}"
                encoded = rendered.encode("utf-8", errors="replace")
                remaining = byte_limit - selected_bytes
                if len(encoded) + (1 if selected else 0) > remaining:
                    rendered = encoded[:remaining].decode("utf-8", "ignore") + "...[line clipped]"
                    selected_line_clipped = True
                separator = 1 if selected else 0
                selected.append(rendered)
                selected_bytes += len(rendered.encode("utf-8", errors="replace")) + separator
                last_line = index
                selected_line_clipped = selected_line_clipped or line_clipped
            if index >= requested_end and digest is None:
                break
        scan_complete = bool(scan.get("complete")) or int(scan.get("bytes_scanned") or 0) >= file_bytes
        sha256 = digest.hexdigest() if digest is not None and scan_complete else ""
    known_line_count = int(scan.get("lines_scanned") or 0) if scan_complete else None
    expected_last_line = min(requested_end, known_line_count) if known_line_count is not None else requested_end
    range_complete = last_line >= expected_last_line
    content, was_redacted = redact("\n".join(selected))
    return {
        "ok": True, "code": "ok", "path": relative, "start_line": start,
        "end_line": last_line, "line_count": known_line_count,
        "content": content, "bytes": len(content.encode()), "file_bytes": file_bytes,
        "sha256": sha256, "digest_complete": bool(sha256), "redacted": was_redacted,
        "truncated": not range_complete or selected_line_clipped,
        "scan": {
            "bytes_scanned": int(scan.get("bytes_scanned") or 0),
            "complete": scan_complete,
            "stream_chunk_bytes": STREAM_CHUNK_BYTES,
            "line_buffer_bytes_max": byte_limit,
            "output_bytes_max": byte_limit,
        },
        "limitations": [
            *(["line_count_lower_bound"] if not scan_complete else []),
            *(["explicit_scan_byte_limit_reached"] if explicit_scan_limit is not None and not scan_complete else []),
            *(["selected_line_clipped"] if selected_line_clipped else []),
            *(["file_digest_incomplete_scan"] if digest is not None and not sha256 else []),
            *(["file_digest_omitted_over_limit"] if digest is None else []),
        ],
    }
