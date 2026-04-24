"""Shared runtime helpers for the Hermes-native Canva plugin."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Iterable, List, Sequence

from hermes_constants import resolve_node_workspace_root


_PATH_PATTERNS = (
    re.compile(r"image_url:\s*(?P<path>/[^\s\]~]+)"),
    re.compile(r"saved at:\s*(?P<path>/[^\]\n]+)"),
    re.compile(r"Use this local file path for Canva workflows:\s*(?P<path>/[^\]\n]+)"),
    re.compile(r"Local file for Canva workflows:\s*(?P<path>/[^\]\n]+)"),
)

_DESIGN_KEYWORDS = {
    "canva",
    "design",
    "poster",
    "flyer",
    "thumbnail",
    "cover",
    "banner",
    "instagram",
    "social post",
    "social-post",
    "presentation",
    "brand template",
    "asset-led",
    "autofill",
}

_VISUAL_ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


def resolve_workspace_root(**kwargs) -> Path:
    return resolve_node_workspace_root(
        current_working_directory=str(kwargs.get("current_working_directory", "") or ""),
        cwd=str(kwargs.get("cwd", "") or ""),
        runtime_dir_name="canva",
    )


def workspace_canva_dir(**kwargs) -> Path:
    base = resolve_workspace_root(**kwargs) / "canva"
    base.mkdir(parents=True, exist_ok=True)
    return base


def workspace_canva_files_dir(**kwargs) -> Path:
    path = workspace_canva_dir(**kwargs) / "files"
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_canva_logs_dir(**kwargs) -> Path:
    path = workspace_canva_dir(**kwargs) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_canva_inbox_dir(**kwargs) -> Path:
    path = workspace_canva_files_dir(**kwargs) / "inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_operation_log(action: str, payload: dict, **kwargs) -> str:
    logs_dir = workspace_canva_logs_dir(**kwargs)
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = logs_dir / f"{timestamp}-{action}.json"
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(serialized, encoding="utf-8")
    (logs_dir / f"latest-{action}.json").write_text(serialized, encoding="utf-8")
    session_path = logs_dir / "session-manifest.jsonl"
    with session_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "timestamp": timestamp,
                    "action": action,
                    "log_path": str(path),
                    "ok": bool(payload.get("ok", True)),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return str(path)


def asset_cache_path(**kwargs) -> Path:
    return workspace_canva_logs_dir(**kwargs) / "uploaded-assets.json"


def file_fingerprint(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def load_asset_cache(**kwargs) -> dict:
    path = asset_cache_path(**kwargs)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_asset_cache(cache: dict, **kwargs) -> str:
    path = asset_cache_path(**kwargs)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def lookup_cached_asset(local_path: Path, **kwargs) -> dict:
    try:
        fingerprint = file_fingerprint(local_path)
    except Exception:
        return {}
    entry = load_asset_cache(**kwargs).get(fingerprint)
    if not isinstance(entry, dict):
        return {}
    entry = dict(entry)
    entry["fingerprint"] = fingerprint
    entry["local_path"] = str(local_path)
    return entry


def remember_uploaded_asset(local_path: Path, asset_id: str, *, name: str = "", source: str = "", **kwargs) -> dict:
    fingerprint = file_fingerprint(local_path)
    cache = load_asset_cache(**kwargs)
    cache[fingerprint] = {
        "asset_id": asset_id,
        "name": name or local_path.stem,
        "source": source or "upload_asset",
        "local_path": str(local_path),
        "updated_at": int(time.time()),
    }
    save_asset_cache(cache, **kwargs)
    return {"fingerprint": fingerprint, **cache[fingerprint]}


def extract_local_paths_from_message(message: str) -> List[Path]:
    found: List[Path] = []
    seen: set[str] = set()
    for pattern in _PATH_PATTERNS:
        for match in pattern.finditer(message or ""):
            raw_path = str(match.group("path") or "").strip().rstrip("]")
            if not raw_path or raw_path in seen:
                continue
            seen.add(raw_path)
            found.append(Path(raw_path))
    return found


def _history_content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif item.get("type") == "text" and isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(part for part in parts if part)
    return ""


def extract_local_paths_from_history(history: Sequence[dict] | None) -> List[Path]:
    found: List[Path] = []
    seen: set[str] = set()
    for message in history or []:
        if not isinstance(message, dict):
            continue
        text = _history_content_to_text(message.get("content"))
        for path in extract_local_paths_from_message(text):
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            found.append(path)
    return found


def looks_like_canva_request(message: str) -> bool:
    lower = str(message or "").lower()
    return any(keyword in lower for keyword in _DESIGN_KEYWORDS)


def stage_inbound_assets(paths: Iterable[Path], **kwargs) -> dict:
    inbox_dir = workspace_canva_inbox_dir(**kwargs)
    staged = []
    skipped = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except Exception:
            skipped.append({"path": str(path), "reason": "unresolvable"})
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if not resolved.exists() or not resolved.is_file():
            skipped.append({"path": str(resolved), "reason": "missing"})
            continue
        if inbox_dir in resolved.parents:
            staged.append(
                {
                    "source_path": str(resolved),
                    "staged_path": str(resolved),
                    "filename": resolved.name,
                    "source": "already_inbox",
                }
            )
            continue
        digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:10]
        safe_name = resolved.name or f"asset{resolved.suffix}"
        target = inbox_dir / f"{resolved.stem}-{digest}{resolved.suffix.lower()}"
        if not target.exists():
            shutil.copy2(resolved, target)
        staged.append(
            {
                "source_path": str(resolved),
                "staged_path": str(target),
                "filename": target.name,
                "source": "copied",
            }
        )
    payload = {
        "ok": True,
        "action": "stage_inbound_assets",
        "staged": staged,
        "skipped": skipped,
        "workspace_dir": str(workspace_canva_dir(**kwargs)),
        "files_dir": str(workspace_canva_files_dir(**kwargs)),
        "logs_dir": str(workspace_canva_logs_dir(**kwargs)),
        "inbox_dir": str(inbox_dir),
    }
    payload["log_path"] = write_operation_log("stage_inbound_assets", payload, **kwargs)
    return payload


def recent_local_assets(*, limit: int = 10, include_extensions: Iterable[str] | None = None, **kwargs) -> list[dict]:
    inbox_dir = workspace_canva_inbox_dir(**kwargs)
    exts = {ext.lower() for ext in (include_extensions or _VISUAL_ASSET_EXTENSIONS)}
    cache = load_asset_cache(**kwargs)
    items = []
    for entry in inbox_dir.iterdir():
        if not entry.is_file():
            continue
        ext = entry.suffix.lower()
        if exts and ext not in exts:
            continue
        stat = entry.stat()
        cached = lookup_cached_asset(entry, **kwargs)
        items.append(
            {
                "path": str(entry),
                "filename": entry.name,
                "extension": ext,
                "size_bytes": stat.st_size,
                "modified_at": int(stat.st_mtime),
                "cached_asset_id": str(cached.get("asset_id", "") or ""),
            }
        )
    items.sort(key=lambda item: item["modified_at"], reverse=True)
    return items[: max(1, int(limit or 10))]
