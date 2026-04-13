from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Any, Iterator


SLUG_RE = re.compile(r"[^a-z0-9]+")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = SLUG_RE.sub("-", lowered).strip("-")
    return slug or "untitled"


def normalize_text(value: str) -> str:
    return SLUG_RE.sub(" ", value.strip().lower()).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write_text(path: Path, content: str) -> None:
    ensure_directory(path.parent)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def copy_if_missing(source: Path, target: Path) -> bool:
    if target.exists():
        return False
    ensure_directory(target.parent)
    shutil.copy2(source, target)
    return True


def ensure_symlink(path: Path, target: Path) -> bool:
    if path.is_symlink():
        try:
            if path.resolve() == target.resolve():
                return False
        except Exception:
            pass
        path.unlink()
    elif path.exists():
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink()
    ensure_directory(path.parent)
    os.symlink(target, path)
    return True


def remove_path(path: Path) -> bool:
    if path.is_symlink() or path.is_file():
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return True
    return False


def list_markdown_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*.md")
        if ".git" not in path.parts
    )


@contextmanager
def file_lock(lock_path: Path, timeout_sec: int = 30) -> Iterator[None]:
    ensure_directory(lock_path.parent)
    with lock_path.open("a+", encoding="utf-8") as handle:
        deadline = time.time() + max(timeout_sec, 1)
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() >= deadline:
                    raise TimeoutError(f"timed out waiting for lock: {lock_path}")
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
