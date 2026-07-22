"""Route-scoped repository mutations with validate-before-commit semantics."""
from __future__ import annotations

import difflib
import json
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import threading
from collections.abc import Callable, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - production server is POSIX.
    fcntl = None  # type: ignore[assignment]


TRANSACTION_ROOT_ENV = "HERMES_WASM_AGENT_REPOSITORY_TRANSACTION_DIR"
DB_PATH_ENV = "HERMES_WASM_AGENT_DB_PATH"
STATE_DIR_ENV = "HERMES_WASM_AGENT_STATE_DIR"
CLOUD_STATE_ROOT_ENV = "HERMES_WASM_AGENT_CLOUD_STATE_ROOT"
DEPLOYMENT_MODE_ENV = "HERMES_WASM_AGENT_DEPLOYMENT_MODE"
JOURNAL_DIRECTORY_NAME = "master-frontier-repository-transactions"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PLUGIN_ROOT / "state" / "db" / "sqlite" / "wa_db.sqlite3"
_PROCESS_LOCK = threading.Lock()
_RECOVERY_BLOCKS: dict[str, str] = {}


class RepositoryActionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message); self.code = code


def journal_root(environ: Mapping[str, str] | None = None) -> Path:
    """Resolve transaction state beside the configured durable DB/state root."""
    source = os.environ if environ is None else environ
    explicit = str(source.get(TRANSACTION_ROOT_ENV) or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured_db = str(source.get(DB_PATH_ENV) or "").strip()
    if configured_db:
        return Path(configured_db).expanduser().resolve().parent / JOURNAL_DIRECTORY_NAME
    deployment = str(source.get(DEPLOYMENT_MODE_ENV) or "local").strip().lower()
    cloud_root = str(source.get(CLOUD_STATE_ROOT_ENV) or "").strip()
    if deployment == "cloud" and cloud_root:
        state_root = Path(cloud_root).expanduser().resolve() / "state"
        return state_root / "db" / "sqlite" / JOURNAL_DIRECTORY_NAME
    configured_state = str(source.get(STATE_DIR_ENV) or "").strip()
    if configured_state:
        state_root = Path(configured_state).expanduser().resolve()
        return state_root / "db" / "sqlite" / JOURNAL_DIRECTORY_NAME
    return DEFAULT_DB_PATH.resolve().parent / JOURNAL_DIRECTORY_NAME


def _prepare_journal_root(root: Path) -> Path:
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not root.is_dir():
            raise OSError("transaction state is not a directory")
        root.chmod(0o700)
    except OSError as exc:
        raise RepositoryActionError(
            "patch_recovery_unavailable",
            "Durable repository transaction state is unavailable; mutations are disabled.",
        ) from exc
    return root


def _read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _apply_locked(
    operations: list[dict], *, dry_run: bool, resolve: Callable[[str], Path], relative: Callable[[Path], str],
    max_operations: int, max_file_bytes: int, max_payload_bytes: int, journal_state_root: Path,
) -> dict:
    if not operations: raise RepositoryActionError("patch_missing_operations", "A scoped patch requires operations.")
    if len(operations) > max_operations: raise RepositoryActionError("patch_too_many_operations", "The scoped patch has too many operations.")
    original: dict[Path, str | None] = {}
    pending: dict[Path, str | None] = {}
    payload_bytes = 0

    def current(path: Path) -> str | None:
        if path in pending: return pending[path]
        if path.exists() and (not path.is_file() or path.stat().st_size > max_file_bytes):
            raise RepositoryActionError("patch_file_too_large", "Patch target is not a bounded regular file.")
        value = _read_text(path) if path.exists() else None
        original.setdefault(path, value); pending[path] = value
        return value

    for operation in operations:
        op = str(operation.get("op") or operation.get("operation") or "replace").strip().lower()
        path = resolve(str(operation.get("path") or "")); value = current(path)
        expected_absent = operation.get("expected_absent") is True
        expected_sha = str(operation.get("expected_sha256") or "").strip().lower()
        if expected_absent and value is not None:
            raise RepositoryActionError("patch_preimage_exists", f"Expected an absent target: {relative(path)}")
        if expected_sha:
            preimage = original.get(path)
            actual_sha = hashlib.sha256(preimage.encode("utf-8")).hexdigest() if preimage is not None else "absent"
            if actual_sha != expected_sha:
                raise RepositoryActionError("patch_preimage_mismatch", f"Patch target changed since it was read: {relative(path)}")
        if op == "create":
            if value is not None: raise RepositoryActionError("patch_create_exists", f"Create target already exists: {relative(path)}")
            content = str(operation.get("content") or operation.get("text") or "")
            payload_bytes += len(content.encode()); pending[path] = content
        elif op == "replace":
            if value is None: raise RepositoryActionError("patch_file_missing", f"Replace target is missing: {relative(path)}")
            find, replacement = str(operation.get("find") or ""), str(operation.get("replace") or "")
            if not find: raise RepositoryActionError("patch_invalid_replace", "Replace requires a non-empty find string.")
            if value.count(find) != 1: raise RepositoryActionError("patch_non_unique_match", f"Replace match must be unique: {relative(path)}")
            payload_bytes += len(find.encode()) + len(replacement.encode()); pending[path] = value.replace(find, replacement, 1)
        elif op == "append":
            insert, after = str(operation.get("insert") or operation.get("text") or ""), str(operation.get("after") or "")
            if not insert: raise RepositoryActionError("patch_invalid_append", "Append requires non-empty content.")
            base = value or ""
            if after and base.count(after) != 1: raise RepositoryActionError("patch_non_unique_match", f"Append anchor must be unique: {relative(path)}")
            payload_bytes += len(insert.encode()); pending[path] = base.replace(after, after + insert, 1) if after else base + insert
        elif op == "delete":
            if value is None: raise RepositoryActionError("patch_file_missing", f"Delete target is missing: {relative(path)}")
            pending[path] = None
        elif op == "move":
            if value is None: raise RepositoryActionError("patch_file_missing", f"Move source is missing: {relative(path)}")
            destination = resolve(str(operation.get("destination") or operation.get("to") or ""))
            if current(destination) is not None: raise RepositoryActionError("patch_move_exists", f"Move destination exists: {relative(destination)}")
            pending[destination] = value; pending[path] = None
        else:
            raise RepositoryActionError("patch_invalid_op", f"Unsupported scoped operation: {op}")
        if payload_bytes > max_payload_bytes: raise RepositoryActionError("patch_payload_too_large", "Scoped patch payload is too large.")

    diff: list[str] = []
    changed = sorted(relative(path) for path, value in pending.items() if value != original.get(path))
    for path in sorted(pending, key=lambda item: relative(item)):
        before, after = original.get(path), pending[path]
        if before == after: continue
        diff.extend(difflib.unified_diff((before or "").splitlines(), (after or "").splitlines(), fromfile=f"a/{relative(path)}", tofile=f"b/{relative(path)}", lineterm="", n=3))
    if not dry_run:
        _commit(pending, original, journal_state_root=journal_state_root)
    postimages = {
        relative(path): "deleted" if value is None else hashlib.sha256(value.encode("utf-8")).hexdigest()
        for path, value in pending.items() if value != original.get(path)
    }
    return {
        "applied": not dry_run, "dry_run": dry_run, "changed_files": changed,
        "operations": len(operations), "diff": "\n".join(diff), "postimage_sha256": postimages,
    }


def _staged_file(path: Path, value: str, *, label: str = "mf5") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.{label}-", dir=str(path.parent))
    staged = Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            staged.chmod(path.stat().st_mode)
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def _restore(path: Path, value: str | None) -> None:
    if value is None:
        path.unlink(missing_ok=True)
        return
    staged = _staged_file(path, value)
    os.replace(staged, path)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def _journal_write(items: list[dict[str, object]], *, root: Path | None = None) -> Path:
    state_root = _prepare_journal_root(root or journal_root())
    descriptor, raw = tempfile.mkstemp(prefix="transaction-", suffix=".tmp", dir=str(state_root))
    temporary = Path(raw); final = temporary.with_suffix(".json")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"schema": "master.frontier.repository.transaction.v1", "items": items}, handle, separators=(",", ":"))
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, final); _fsync_directory(state_root)
        return final
    except Exception:
        temporary.unlink(missing_ok=True); raise


def _recovery_artifact(raw: object, path: Path, *, backup: bool) -> Path | None:
    value = str(raw or "")
    if not value:
        return None
    artifact = Path(value)
    marker = f".{path.name}.mf5-backup-" if backup else f".{path.name}.mf5-"
    if not artifact.is_absolute() or artifact.parent != path.parent or not artifact.name.startswith(marker):
        raise ValueError("unsafe transaction artifact")
    return artifact


def _recovery_items(journal: Path) -> list[dict[str, object]]:
    if journal.is_symlink() or not journal.is_file() or journal.stat().st_size > 256 * 1024:
        raise ValueError("invalid transaction journal file")
    payload = json.loads(journal.read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) and payload.get("schema") == "master.frontier.repository.transaction.v1" else None
    if not isinstance(items, list):
        raise ValueError("invalid transaction journal")
    validated: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid transaction item")
        path = Path(str(item.get("path") or ""))
        if not path.is_absolute():
            raise ValueError("unsafe transaction path")
        original_absent = item.get("original_absent") is True
        backup = _recovery_artifact(item.get("backup"), path, backup=True)
        staged = _recovery_artifact(item.get("staged"), path, backup=False)
        if original_absent:
            if backup is not None:
                raise ValueError("unexpected transaction backup")
        elif backup is None or not backup.is_file() or backup.is_symlink():
            raise ValueError("transaction backup missing")
        validated.append({
            "path": path, "original_absent": original_absent,
            "backup": backup, "staged": staged,
        })
    return validated


def _restore_backup(path: Path, backup: Path) -> None:
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.mf5-recover-", dir=str(path.parent))
    staged = Path(raw)
    try:
        with os.fdopen(descriptor, "wb") as destination, backup.open("rb") as source:
            shutil.copyfileobj(source, destination, length=64 * 1024)
            destination.flush(); os.fsync(destination.fileno())
        staged.chmod(backup.stat().st_mode)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _recover_pending_locked(state_root: Path) -> int:
    recovered = 0
    for journal in sorted(state_root.glob("transaction-*.json")):
        try:
            items = _recovery_items(journal)
            for item in reversed(items):
                path = item["path"]
                assert isinstance(path, Path)
                if item["original_absent"] is True:
                    path.unlink(missing_ok=True)
                else:
                    backup = item["backup"]
                    assert isinstance(backup, Path)
                    _restore_backup(path, backup)
                _fsync_directory(path.parent)
            # The journal is the recovery commit marker. Remove it only after
            # every preimage is durable; artifact cleanup may then be best-effort.
            journal.unlink(); _fsync_directory(state_root); recovered += 1
            for item in items:
                for key in ("backup", "staged"):
                    artifact = item.get(key)
                    if isinstance(artifact, Path):
                        try: artifact.unlink(missing_ok=True)
                        except OSError: pass
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            message = f"Repository recovery is blocked by {journal.name}: {type(exc).__name__}."
            _RECOVERY_BLOCKS[str(state_root)] = message
            raise RepositoryActionError("patch_recovery_blocked", message) from exc
    _RECOVERY_BLOCKS.pop(str(state_root), None)
    return recovered


def recover_pending(*, strict: bool = False) -> int:
    """Recover durable journals; startup may defer errors, while mutations may not."""
    with _PROCESS_LOCK:
        try:
            state_root = _prepare_journal_root(journal_root())
            with (state_root / "commit.lock").open("a+b") as lock:
                if fcntl is not None: fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try: return _recover_pending_locked(state_root)
                finally:
                    if fcntl is not None: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except (OSError, RepositoryActionError) as exc:
            error = exc if isinstance(exc, RepositoryActionError) else RepositoryActionError(
                "patch_recovery_unavailable", "Durable repository transaction state is unavailable; mutations are disabled.",
            )
            _RECOVERY_BLOCKS[str(journal_root())] = str(error)
            if strict:
                raise error
            return 0


def apply(
    operations: list[dict], *, dry_run: bool, resolve: Callable[[str], Path], relative: Callable[[Path], str],
    max_operations: int, max_file_bytes: int, max_payload_bytes: int,
) -> dict:
    """Serialize cooperative patches and recover any process-interrupted commit first."""
    with _PROCESS_LOCK:
        state_root = _prepare_journal_root(journal_root())
        try:
            lock_handle = (state_root / "commit.lock").open("a+b")
        except OSError as exc:
            raise RepositoryActionError(
                "patch_recovery_unavailable", "Durable repository transaction state is unavailable; mutations are disabled.",
            ) from exc
        with lock_handle as lock:
            if fcntl is not None: fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                _recover_pending_locked(state_root)
                return _apply_locked(
                    operations, dry_run=dry_run, resolve=resolve, relative=relative,
                    max_operations=max_operations, max_file_bytes=max_file_bytes,
                    max_payload_bytes=max_payload_bytes, journal_state_root=state_root,
                )
            finally:
                if fcntl is not None: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _commit(
    pending: dict[Path, str | None], original: dict[Path, str | None],
    *, journal_state_root: Path | None = None,
) -> None:
    """Stage every postimage, then commit or restore every touched preimage."""
    staged: dict[Path, Path] = {}
    changed = [path for path, value in pending.items() if value != original.get(path)]
    for path in changed:
        actual = _read_text(path) if path.exists() and path.is_file() else None
        if actual != original.get(path):
            raise RepositoryActionError("patch_preimage_changed", f"Patch target changed during the transaction: {path}")
    backups: dict[Path, Path] = {}
    journal: Path | None = None
    retain_recovery = False
    try:
        for path in changed:
            value = pending[path]
            if value is not None:
                staged[path] = _staged_file(path, value)
            if original.get(path) is not None:
                backups[path] = _staged_file(path, str(original[path]), label="mf5-backup")
        state_root = _prepare_journal_root(journal_state_root or journal_root())
        journal = _journal_write([
            {
                "path": str(path), "original_absent": original.get(path) is None,
                "backup": str(backups.get(path) or ""), "staged": str(staged.get(path) or ""),
            }
            for path in changed
        ], root=state_root)
        committed: list[Path] = []
        try:
            for path in changed:
                value = pending[path]
                if value is None:
                    path.unlink()
                    _fsync_directory(path.parent)
                    committed.append(path)
                elif original.get(path) is None:
                    os.link(staged[path], path)
                    _fsync_directory(path.parent)
                    committed.append(path)
                    staged[path].unlink()
                    staged.pop(path)
                else:
                    os.replace(staged[path], path)
                    _fsync_directory(path.parent)
                    committed.append(path)
                    staged.pop(path)
        except Exception as exc:
            rollback_errors = []
            for path in reversed(committed):
                try:
                    _restore(path, original.get(path))
                    _fsync_directory(path.parent)
                except Exception as rollback_exc:  # pragma: no cover - catastrophic filesystem failure
                    rollback_errors.append(f"{path}:{rollback_exc}")
            message = "Atomic patch commit failed and was rolled back."
            if rollback_errors:
                message = "Atomic patch commit failed; rollback was incomplete: " + ", ".join(rollback_errors)
                retain_recovery = True
            elif journal is not None:
                journal.unlink(missing_ok=True); _fsync_directory(state_root); journal = None
            raise RepositoryActionError("patch_commit_failed", message) from exc
        if journal is not None:
            journal.unlink(missing_ok=True); _fsync_directory(state_root)
        for backup in backups.values(): backup.unlink(missing_ok=True)
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)
        if not retain_recovery:
            for path in backups.values(): path.unlink(missing_ok=True)
