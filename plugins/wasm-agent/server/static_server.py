#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import mimetypes
import os
import queue
import secrets
import shutil
import socket
import subprocess
import struct
import threading
import time
import uuid
from ipaddress import ip_address
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional runtime guard
    Image = None  # type: ignore[assignment]


PLUGIN_NAME = "wasm-agent"
PLUGIN_VERSION = "0.1.0"
IMAGE_CARD_ANALYZER_REVISION = "image-card-text-v2"
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DEFAULT_BROWSER_STREAM_FPS = 4.0
DEFAULT_BROWSER_STREAM_QUALITY = 62
DEFAULT_BROWSER_STREAM_EVERY_NTH_FRAME = 3
DEFAULT_BROWSER_SESSION_TTL_SEC = 30 * 60
DEFAULT_AGENT_BRIDGE_TIMEOUT_SEC = 5 * 60
DEFAULT_AGENT_IMAGE_MAX_BYTES = 1024 * 1024
DEFAULT_AGENT_IMAGE_LIMIT = 8
DEFAULT_AGENT_BRIDGE_IMAGE_BYTES = 900 * 1024
DEFAULT_AGENT_BRIDGE_IMAGE_SINGLE_BYTES = 640 * 1024
DEFAULT_AGENT_BRIDGE_REQUEST_BYTES = 1536 * 1024
DEFAULT_AGENT_BRIDGE_FORWARD_IMAGE_URLS = False
DEFAULT_AGENT_ATTACHMENT_MAX_BYTES = 2 * 1024 * 1024


class WasmAgentServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[SimpleHTTPRequestHandler],
        *,
        plugin_root: Path,
        public_root: Path,
        state_dir: Path,
        bridge_url: str,
        browser_timeout_sec: float,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.plugin_root = plugin_root
        self.public_root = public_root
        self.state_dir = state_dir
        self.bridge_url = bridge_url.rstrip("/")
        self.browser_timeout_sec = browser_timeout_sec
        self.browser_sessions: dict[str, dict[str, Any]] = {}
        self.browser_sessions_lock = threading.Lock()


class WasmAgentHandler(SimpleHTTPRequestHandler):
    server: WasmAgentServer

    def __init__(self, *args: Any, directory: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.getenv("HERMES_WASM_AGENT_ACCESS_LOG", "").lower() in {"1", "true", "yes", "on"}:
            super().log_message(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/browser/stream":
            serve_browser_stream(self)
            return
        if path == "/modules/hmr/events":
            serve_dev_hmr_events(self)
            return
        if path.startswith("/agent/attachments/"):
            try:
                serve_agent_attachment(self, path)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/health":
            self._json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "health": {
                        "name": PLUGIN_NAME,
                        "version": PLUGIN_VERSION,
                        "status": "ok",
                        "bridge_url": self.server.bridge_url,
                        "public_root": str(self.server.public_root),
                        "wasm_core": "embedded",
                    },
                },
            )
            return
        if path == "/config.json":
            self._json(
                HTTPStatus.OK,
                {
                    "name": PLUGIN_NAME,
                    "version": PLUGIN_VERSION,
                    "bridgeUrl": self.server.bridge_url,
                    "agentTurnTimeoutSec": agent_bridge_timeout_sec(),
                    "compareWith": {
                        "hermesSpaceUiPwa": "http://127.0.0.1:8787",
                        "hermesSpaceUiBridge": "http://127.0.0.1:8790",
                    },
                },
            )
            return
        if path == "/observation/latest":
            try:
                self._json(HTTPStatus.OK, latest_observation(self.server))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/timeline/status":
            try:
                self._json(HTTPStatus.OK, {"ok": True, "timeline": timeline_status(self.server)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/agent/handoff/latest":
            try:
                self._json(HTTPStatus.OK, latest_agent_handoff(self.server))
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        super().do_GET()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/browser/open":
            try:
                body = self._read_json()
                self._json(HTTPStatus.OK, {"ok": True, "browser": capture_browser(self.server, body)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "browser_error", "message": str(exc)}},
                )
            return
        if path == "/browser/input":
            try:
                body = self._read_json()
                self._json(HTTPStatus.OK, {"ok": True, "browser": browser_input(self.server, body)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "browser_error", "message": str(exc)}},
                )
            return
        if path == "/browser/close":
            try:
                body = self._read_json()
                self._json(HTTPStatus.OK, {"ok": True, "browser": close_browser_session(self.server, body)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        if path == "/observation/latest":
            try:
                body = self._read_json(max_bytes=256 * 1024)
                self._json(HTTPStatus.OK, {"ok": True, "observation": save_observation(self.server, body)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "observation_error", "message": str(exc)}},
                )
            return
        if path == "/agent/attachments":
            try:
                body = self._read_json(max_bytes=4 * 1024 * 1024)
                self._json(HTTPStatus.OK, {"ok": True, "asset": save_agent_attachment(self.server, body)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "attachment_error", "message": str(exc)}},
                )
            return
        if path == "/agent/session/message":
            try:
                body = self._read_json(max_bytes=8 * 1024 * 1024)
                self._json(HTTPStatus.OK, {"ok": True, "agent": embedded_agent_message(self.server, body)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "agent_error", "message": str(exc)}},
                )
            return
        if path == "/agent/session/message/stream":
            try:
                body = self._read_json(max_bytes=8 * 1024 * 1024)
                stream_embedded_agent_message(self, body)
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "agent_error", "message": str(exc)}},
                )
            return
        if path == "/timeline/checkpoint":
            try:
                body = self._read_json(max_bytes=16 * 1024)
                self._json(HTTPStatus.OK, {"ok": True, "checkpoint": timeline_checkpoint(self.server, body)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "timeline_error", "message": str(exc)}},
                )
            return
        if path == "/agent/handoff":
            try:
                body = self._read_json(max_bytes=128 * 1024)
                self._json(HTTPStatus.OK, {"ok": True, "handoff": save_agent_handoff(self.server, body)})
            except BrowserError as exc:
                self._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "handoff_error", "message": str(exc)}},
                )
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint was not found")

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        translated = Path(super().translate_path(path))
        public_root = self.server.public_root.resolve()
        try:
            translated.resolve().relative_to(public_root)
        except ValueError:
            return str(public_root / "index.html")
        if translated.is_file() or translated.suffix:
            return str(translated)
        return str(public_root / "index.html")

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self, *, max_bytes: int = 64 * 1024) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise BrowserError("invalid_content_length", "Invalid Content-Length header.") from exc
        if length > max_bytes:
            raise BrowserError(
                "payload_too_large",
                "Request body is too large.",
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BrowserError("invalid_json", "Request body must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise BrowserError("invalid_json", "Request body must be a JSON object.")
        return payload


class BrowserError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def chromium_command() -> str:
    command = os.getenv("HERMES_WASM_AGENT_CHROMIUM", "").strip()
    if command:
        return command
    for candidate in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(candidate)
        if found:
            return found
    raise BrowserError(
        "chromium_not_found",
        "Chromium was not found. Set HERMES_WASM_AGENT_CHROMIUM to a browser binary.",
        status=HTTPStatus.SERVICE_UNAVAILABLE,
    )


def normalized_browser_url(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        raise BrowserError("missing_url", "A URL is required.")
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BrowserError("invalid_url", "Only http and https URLs are supported.")
    if not private_targets_allowed():
        reject_private_target(parsed.hostname)
    return value


def browser_dimensions(body: dict[str, Any]) -> tuple[int, int]:
    return (
        int(clamp_number(body.get("width") or 1280, 360, 1920)),
        int(clamp_number(body.get("height") or 800, 240, 1400)),
    )


def private_targets_allowed() -> bool:
    return os.getenv("HERMES_WASM_AGENT_BROWSER_ALLOW_PRIVATE", "").lower() in {"1", "true", "yes", "on"}


def reject_private_target(hostname: str) -> None:
    lowered = hostname.lower().strip("[]")
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".localhost"):
        raise BrowserError("private_url_blocked", "Localhost browser targets are disabled by default.")
    try:
        infos = socket.getaddrinfo(lowered, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BrowserError("dns_failed", f"Could not resolve browser target: {hostname}") from exc
    for info in infos:
        address = info[4][0]
        try:
            parsed = ip_address(address)
        except ValueError:
            continue
        if parsed.is_private or parsed.is_loopback or parsed.is_link_local or parsed.is_reserved:
            raise BrowserError(
                "private_url_blocked",
                "Private, loopback, link-local, and reserved browser targets are disabled by default.",
            )


def observation_path(server: WasmAgentServer) -> Path:
    return server.state_dir / "observation" / "latest.json"


def save_observation(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    schema = str(body.get("schema") or "")
    if schema != "hermes.space_os.observation.v1":
        raise BrowserError("invalid_observation", "Observation payload schema is not supported.")
    payload = dict(body)
    payload["received_at"] = int(time.time())
    path = observation_path(server)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)
    last_event = (payload.get("user_events") or [{}])[0]
    return {
        "schema": schema,
        "stored": True,
        "received_at": payload["received_at"],
        "event_count": payload.get("analytics", {}).get("event_count", 0),
        "last_event": last_event if isinstance(last_event, dict) else {},
    }


def latest_observation(server: WasmAgentServer) -> dict[str, Any]:
    path = observation_path(server)
    if not path.exists():
        return {"ok": True, "observation": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BrowserError("observation_read_failed", f"Could not read latest observation: {exc}") from exc
    return {"ok": True, "observation": payload}


def git_run(
    server: WasmAgentServer,
    args: list[str],
    *,
    timeout: float = 8,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        ["git", "-C", str(repo_root(server)), *args],
        text=True,
        capture_output=True,
        timeout=timeout,
        env=run_env,
        check=False,
    )


def git_output(server: WasmAgentServer, args: list[str], *, timeout: float = 8) -> str:
    proc = git_run(server, args, timeout=timeout)
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def timeline_ref_name(raw: str) -> str:
    base = "".join(ch.lower() if ch.isalnum() else "-" for ch in raw.strip())[:48].strip("-")
    return base or f"checkpoint-{int(time.time())}"


def timeline_status(server: WasmAgentServer) -> dict[str, Any]:
    branch = git_output(server, ["branch", "--show-current"]) or "detached"
    head = git_output(server, ["rev-parse", "--short", "HEAD"])
    head_full = git_output(server, ["rev-parse", "HEAD"])
    status = git_output(server, ["status", "--short"], timeout=5)
    recent_raw = git_output(server, ["log", "--oneline", "--decorate", "-8"], timeout=5)
    branches_raw = git_output(server, ["branch", "--format=%(refname:short)|%(objectname:short)|%(committerdate:relative)"], timeout=5)
    checkpoints_raw = git_output(
        server,
        ["for-each-ref", "refs/wasm-agent-timeline", "--format=%(refname:short)|%(objectname:short)|%(creatordate:iso8601)|%(subject)"],
        timeout=5,
    )
    return {
        "schema": "hermes.wasm_agent.timeline.v1",
        "branch": branch,
        "head": head,
        "head_full": head_full,
        "dirty": bool(status),
        "dirty_count": len(status.splitlines()) if status else 0,
        "status_preview": status.splitlines()[:16],
        "recent": recent_raw.splitlines() if recent_raw else [],
        "branches": [
            {"name": item.split("|")[0], "head": item.split("|")[1], "updated": item.split("|")[2]}
            for item in branches_raw.splitlines()
            if item.count("|") >= 2
        ][:12],
        "checkpoints": [
            {
                "name": item.split("|")[0].replace("wasm-agent-timeline/", "", 1),
                "head": item.split("|")[1],
                "created_at": item.split("|")[2],
                "subject": "|".join(item.split("|")[3:]),
            }
            for item in checkpoints_raw.splitlines()
            if item.count("|") >= 3
        ][:16],
        "actions": [
            {
                "id": "auto_checkpoint_on_change",
                "label": "Auto",
                "enabled": True,
                "description": "Chat turns create named git timeline refs automatically when the worktree changes.",
            },
            {
                "id": "branch_from_checkpoint",
                "label": "Branch",
                "enabled": False,
                "description": "Planned confirmation-gated action: create a branch from a selected checkpoint.",
            },
            {
                "id": "merge_checkpoint",
                "label": "Merge",
                "enabled": False,
                "description": "Planned confirmation-gated action: merge a selected branch/checkpoint.",
            },
            {
                "id": "restore_checkpoint",
                "label": "Restore",
                "enabled": False,
                "description": "Planned confirmation-gated action: restore files from a selected checkpoint.",
            },
        ],
    }


def timeline_checkpoint(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    label = timeline_ref_name(str(body.get("label") or "manual-checkpoint"))
    message = clipped(str(body.get("message") or f"wasm-agent timeline checkpoint: {label}"), 180)
    return create_timeline_checkpoint(server, label=label, message=message, automatic=False)


def checkpoint_tree(server: WasmAgentServer, metadata_dir: Path) -> tuple[str, Path]:
    temp_index = metadata_dir / f"checkpoint-{uuid.uuid4().hex}.index"
    index_env = {"GIT_INDEX_FILE": str(temp_index)}
    read_tree = git_run(server, ["read-tree", "HEAD"], timeout=8, env=index_env)
    if read_tree.returncode != 0:
        raise BrowserError("timeline_checkpoint_failed", clipped(read_tree.stderr or "Could not seed temporary git index."))
    add_proc = git_run(server, ["add", "-A"], timeout=20, env=index_env)
    if add_proc.returncode != 0:
        raise BrowserError("timeline_checkpoint_failed", clipped(add_proc.stderr or "Could not stage temporary checkpoint."))
    tree_proc = git_run(server, ["write-tree"], timeout=8, env=index_env)
    tree_sha = (tree_proc.stdout or "").strip()
    if tree_proc.returncode != 0 or not tree_sha:
        raise BrowserError("timeline_checkpoint_failed", clipped(tree_proc.stderr or "Could not write checkpoint tree."))
    return tree_sha, temp_index


def create_timeline_checkpoint(
    server: WasmAgentServer,
    *,
    label: str,
    message: str,
    automatic: bool,
) -> dict[str, Any]:
    dirty = git_output(server, ["status", "--short"], timeout=5)
    untracked = [line for line in dirty.splitlines() if line.startswith("?? ")]
    metadata_dir = server.state_dir / "timeline"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    tree_sha, temp_index = checkpoint_tree(server, metadata_dir)
    commit_proc = git_run(server, ["commit-tree", tree_sha, "-p", "HEAD", "-m", message], timeout=8)
    sha = (commit_proc.stdout or "").strip()
    if commit_proc.returncode != 0 or not sha:
        raise BrowserError("timeline_checkpoint_failed", clipped(commit_proc.stderr or "Could not create checkpoint commit."))
    ref = f"refs/wasm-agent-timeline/{label}-{int(time.time())}"
    update_proc = git_run(server, ["update-ref", ref, sha], timeout=8)
    if update_proc.returncode != 0:
        raise BrowserError("timeline_checkpoint_failed", clipped(update_proc.stderr or "Could not write timeline ref."))
    try:
        temp_index.unlink(missing_ok=True)
    except Exception:
        pass
    metadata = {
        "schema": "hermes.wasm_agent.timeline_checkpoint.v1",
        "ref": ref,
        "sha": sha,
        "tree": tree_sha,
        "label": label,
        "message": message,
        "created_at": int(time.time()),
        "automatic": automatic,
        "tracked_only": False,
        "untracked_count": len(untracked),
        "untracked_note": "Checkpoint uses a temporary git index and captures untracked non-ignored files without changing the real index.",
    }
    (metadata_dir / f"{label}-{metadata['created_at']}.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return metadata


def auto_checkpoint_state_path(server: WasmAgentServer) -> Path:
    return server.state_dir / "timeline" / "auto-latest.json"


def timeline_auto_checkpoint(
    server: WasmAgentServer,
    reason: str,
    *,
    message: str | None = None,
    tree_sha: str | None = None,
) -> dict[str, Any] | None:
    dirty = git_output(server, ["status", "--short"], timeout=5)
    if not dirty:
        return None
    metadata_dir = server.state_dir / "timeline"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    if tree_sha is None:
        tree_sha = worktree_tree_sha(server)
    state_path = auto_checkpoint_state_path(server)
    previous: dict[str, Any] = {}
    if state_path.exists():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    if previous.get("tree") == tree_sha:
        return None
    label = timeline_ref_name(f"auto-{reason}")
    metadata = create_timeline_checkpoint(
        server,
        label=label,
        message=message or f"wasm-agent auto checkpoint: {reason}",
        automatic=True,
    )
    state_path.write_text(
        json.dumps(
            {
                "schema": "hermes.wasm_agent.timeline_auto_checkpoint.v1",
                "tree": metadata.get("tree"),
                "sha": metadata.get("sha"),
                "ref": metadata.get("ref"),
                "reason": reason,
                "created_at": metadata.get("created_at"),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return metadata


def worktree_tree_sha(server: WasmAgentServer) -> str:
    metadata_dir = server.state_dir / "timeline"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    tree_sha, temp_index = checkpoint_tree(server, metadata_dir)
    try:
        temp_index.unlink(missing_ok=True)
    except Exception:
        pass
    return tree_sha


def safe_worktree_tree_sha(server: WasmAgentServer) -> str:
    try:
        return worktree_tree_sha(server)
    except Exception:
        return ""


def changed_files_between_trees(server: WasmAgentServer, before_tree: str, after_tree: str) -> list[dict[str, Any]]:
    if not before_tree or not after_tree or before_tree == after_tree:
        return []
    root = repo_root(server)
    status_proc = git_run(server, ["diff", "--name-status", before_tree, after_tree], timeout=8)
    numstat_proc = git_run(server, ["diff", "--numstat", before_tree, after_tree], timeout=8)
    if status_proc.returncode != 0:
        return []
    numstat: dict[str, tuple[int | None, int | None]] = {}
    if numstat_proc.returncode == 0:
        for row in (numstat_proc.stdout or "").splitlines():
            parts = row.split("\t")
            if len(parts) < 3:
                continue
            added = None if parts[0] == "-" else int(parts[0])
            deleted = None if parts[1] == "-" else int(parts[1])
            numstat[parts[-1]] = (added, deleted)
    files: list[dict[str, Any]] = []
    for line in (status_proc.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        path = parts[-1]
        additions, deletions = numstat.get(path, (None, None))
        files.append(
            {
                "status": status,
                "path": path,
                "full_path": str((root / path).resolve()),
                "additions": additions,
                "deletions": deletions,
                "diff": f"+{additions or 0} -{deletions or 0}" if additions is not None or deletions is not None else "",
            }
        )
    return files[:40]


def run_checkpoint_summary(message: str) -> str:
    text = " ".join(str(message or "").split())
    if not text:
        return "chat turn"
    if len(text) > 72:
        return text[:71].rstrip() + "..."
    return text


def handoff_dir(server: WasmAgentServer) -> Path:
    return server.state_dir / "agent-handoffs"


def save_agent_handoff(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    proposal = body.get("proposal")
    if not isinstance(proposal, dict):
        raise BrowserError("invalid_handoff", "Handoff proposal must be an object.")
    files = proposal.get("files") if isinstance(proposal.get("files"), list) else []
    payload = {
        "schema": "hermes.wasm_agent.agent_handoff.v1",
        "id": f"handoff-{int(time.time())}-{uuid.uuid4().hex[:8]}",
        "created_at": int(time.time()),
        "message_id": str(body.get("message_id") or ""),
        "files": [str(item) for item in files[:12]],
        "summary": clipped(str(proposal.get("summary") or ""), 4000),
        "checkpoint": body.get("checkpoint") if isinstance(body.get("checkpoint"), dict) else None,
        "requires_outer_orchestrator": True,
    }
    root = handoff_dir(server)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{payload['id']}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    latest = root / "latest.json"
    tmp = latest.with_suffix(f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(latest)
    payload["auto_checkpoint"] = timeline_auto_checkpoint(server, "handoff")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp = latest.with_suffix(f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(latest)
    return payload


def latest_agent_handoff(server: WasmAgentServer) -> dict[str, Any]:
    path = handoff_dir(server) / "latest.json"
    if not path.exists():
        return {"ok": True, "handoff": None}
    try:
        return {"ok": True, "handoff": json.loads(path.read_text(encoding="utf-8"))}
    except Exception as exc:
        raise BrowserError("handoff_read_failed", f"Could not read latest handoff: {exc}") from exc


def attachment_dir(server: WasmAgentServer) -> Path:
    path = server.state_dir / "attachments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def image_extension(mime_type: str) -> str:
    normalized = mime_type.lower().split(";", 1)[0].strip()
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(normalized, ".img")


def parse_image_data_url(data_url: str) -> tuple[str, bytes]:
    if not data_url.startswith("data:image/"):
        raise BrowserError("invalid_attachment", "Attachment must be an image data URL.")
    header, sep, encoded = data_url.partition(",")
    if not sep or ";base64" not in header:
        raise BrowserError("invalid_attachment", "Attachment data URL must be base64 encoded.")
    mime_type = header.removeprefix("data:").split(";", 1)[0].lower()
    try:
        payload = base64.b64decode(encoded.encode("ascii"), validate=True)
    except Exception as exc:
        raise BrowserError("invalid_attachment", "Attachment base64 payload is invalid.") from exc
    if len(payload) > DEFAULT_AGENT_ATTACHMENT_MAX_BYTES:
        raise BrowserError(
            "attachment_too_large",
            "Attachment is too large for the local asset store.",
            status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        )
    return mime_type, payload


def compact_image_evidence(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compacted: list[dict[str, Any]] = []
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        facts = item.get("facts") if isinstance(item.get("facts"), list) else []
        values = item.get("values") if isinstance(item.get("values"), dict) else {}
        compacted.append({
            "module": clipped(str(item.get("module") or ""), 80),
            "title": clipped(str(item.get("title") or ""), 80),
            "status": clipped(str(item.get("status") or ""), 40),
            "summary": clipped(str(item.get("summary") or ""), 180),
            "confidence": item.get("confidence") if isinstance(item.get("confidence"), (int, float)) else None,
            "facts": [clipped(str(fact), 160) for fact in facts[:8]],
            "values": values,
            "reason": clipped(str(item.get("reason") or ""), 180),
            "duration_ms": item.get("duration_ms") if isinstance(item.get("duration_ms"), int) else None,
            "cached": bool(item.get("cached")),
        })
    return compacted


def compact_image_module_results(results: Any) -> dict[str, Any]:
    if not isinstance(results, dict):
        return {}
    compacted: dict[str, Any] = {}
    for key, value in list(results.items())[:8]:
        if not isinstance(value, dict):
            continue
        evidence = compact_image_evidence([value])
        if evidence:
            compacted[clipped(str(key), 80)] = evidence[0]
    return compacted


def compact_image_analyzer_modules(modules: Any) -> list[dict[str, Any]]:
    if not isinstance(modules, list):
        return []
    compacted: list[dict[str, Any]] = []
    for module in modules[:8]:
        if not isinstance(module, dict):
            continue
        compacted.append({
            "id": clipped(str(module.get("id") or ""), 80),
            "title": clipped(str(module.get("title") or ""), 80),
            "enabled": bool(module.get("enabled")),
            "status": clipped(str(module.get("status") or ""), 80),
            "mode": clipped(str(module.get("mode") or ""), 80),
            "evidence": clipped(str(module.get("evidence") or ""), 80),
            "cached": bool(module.get("cached")),
        })
    return compacted


def rounded_metric(value: float, digits: int = 3) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return 0
    return round(float(value), digits)


def luminance_word(value: float) -> str:
    if value < 0.12:
        return "very dark"
    if value < 0.28:
        return "dark"
    if value < 0.45:
        return "dim"
    if value < 0.65:
        return "medium"
    if value < 0.82:
        return "bright"
    return "very bright"


def server_text_like_region_signals(luma: list[float], mask: list[int], width: int, height: int, avg_luma: float) -> dict[str, Any]:
    rows = 6
    cols = 4
    cells = [
        {
            "row": index // cols,
            "col": index % cols,
            "count": 0,
            "dark": 0,
            "bright": 0,
            "transitions": 0,
            "comparisons": 0,
        }
        for index in range(rows * cols)
    ]
    dark_threshold = max(42, min(125, avg_luma * 0.78))
    bright_threshold = max(dark_threshold + 28, min(210, avg_luma + 24))
    for y in range(height):
        for x in range(width):
            index = y * width + x
            if not mask[index]:
                continue
            cell_col = min(cols - 1, int((x / max(1, width)) * cols))
            cell_row = min(rows - 1, int((y / max(1, height)) * rows))
            cell = cells[cell_row * cols + cell_col]
            lum = luma[index]
            cell["count"] += 1
            if lum <= dark_threshold:
                cell["dark"] += 1
            if lum >= bright_threshold:
                cell["bright"] += 1
            if x > 0:
                previous = index - 1
                if mask[previous]:
                    cell["comparisons"] += 1
                    if abs(lum - luma[previous]) > 18:
                        cell["transitions"] += 1
            if y > 0:
                previous = index - width
                if mask[previous]:
                    cell["comparisons"] += 1
                    if abs(lum - luma[previous]) > 18:
                        cell["transitions"] += 1
    scored: list[dict[str, Any]] = []
    for cell in cells:
        dark_ratio = cell["dark"] / max(1, cell["count"])
        bright_ratio = cell["bright"] / max(1, cell["count"])
        transition_density = cell["transitions"] / max(1, cell["comparisons"])
        has_ink_and_surface = dark_ratio > 0.035 and dark_ratio < 0.62 and bright_ratio > 0.08
        center_bias = 1.18 if cell["col"] > 0 and cell["col"] < cols - 1 and cell["row"] > 0 and cell["row"] < rows - 1 else 1
        score = min(
            1,
            (
                transition_density * 2.2
                + min(dark_ratio, 0.34) * 0.9
                + min(bright_ratio, 0.5) * 0.2
            )
            * center_bias
            * (1 if has_ink_and_surface else 0.45),
        )
        scored.append({
            "row": cell["row"],
            "col": cell["col"],
            "score": rounded_metric(score),
            "dark_ratio": rounded_metric(dark_ratio),
            "bright_ratio": rounded_metric(bright_ratio),
            "transition_density": rounded_metric(transition_density),
        })
    scored.sort(key=lambda cell: cell["score"], reverse=True)
    active = [cell for cell in scored if cell["score"] > 0.18]
    active_rows = {cell["row"] for cell in active}
    active_cols = {cell["col"] for cell in active}
    regions: list[str] = []
    if active:
        row_avg = sum(cell["row"] for cell in active) / len(active)
        col_avg = sum(cell["col"] for cell in active) / len(active)
        vertical = "upper" if row_avg < 1.8 else "lower" if row_avg > 3.8 else "middle"
        horizontal = "left" if col_avg < 1.1 else "right" if col_avg > 1.9 else "center"
        regions.append(f"{vertical} {horizontal}".strip())
    top_score = sum(cell["score"] for cell in scored[:4]) / max(1, min(4, len(scored)))
    return {
        "score": rounded_metric(top_score),
        "horizontal_band_estimate": len(active_rows),
        "active_cell_count": len(active),
        "active_row_count": len(active_rows),
        "active_col_count": len(active_cols),
        "regions": regions,
        "cells": scored[:5],
    }


def server_scene_hints(analysis: dict[str, Any], text_signals: dict[str, Any]) -> dict[str, Any]:
    text_score = float(text_signals.get("score") or 0)
    sharpness = float(analysis.get("sharpness") or 0)
    contrast = float(analysis.get("contrast") or 0)
    avg_luma = float(analysis.get("average_luminance") or 0)
    center_edge_delta = float(analysis.get("center_edge_delta") or 0)
    edge_density = float(analysis.get("edge_density") or 0)
    uneven_lighting = min(1.0, abs(center_edge_delta) * 3.8)
    low_sharpness = max(0.0, min(1.0, (0.09 - sharpness) / 0.09))
    not_bright_document = 1.0 if avg_luma < 0.58 else max(0.0, (0.72 - avg_luma) / 0.14)
    physical_photo = max(0.0, min(1.0, (uneven_lighting * 0.38) + (low_sharpness * 0.34) + (not_bright_document * 0.28)))
    printed_object = max(0.0, min(1.0, (text_score * 0.62) + (physical_photo * 0.38)))
    screenshot = max(0.0, min(1.0, (sharpness * 2.2 + contrast * 0.8 + edge_density * 0.9) - uneven_lighting * 0.75))
    document = max(0.0, min(1.0, ((avg_luma - 0.42) * 1.4) + (text_score * 0.35) - uneven_lighting * 0.45))
    reasons = []
    if text_score > 0.32:
        reasons.append("strong text-like bands")
    if low_sharpness > 0.45:
        reasons.append("soft camera-like capture")
    if uneven_lighting > 0.35:
        reasons.append("uneven lighting/gradient")
    if not_bright_document > 0.55:
        reasons.append("not a bright flat document field")
    return {
        "physical_photo_likelihood": rounded_metric(physical_photo),
        "printed_object_or_label_likelihood": rounded_metric(printed_object),
        "document_likelihood": rounded_metric(document),
        "screenshot_likelihood": rounded_metric(screenshot),
        "reason": reasons[:6],
    }


def server_shape_hints(
    luma: list[float],
    mask: list[int],
    width: int,
    height: int,
    avg_luma: float,
    text_signals: dict[str, Any],
    scene_hints: dict[str, Any],
) -> dict[str, Any]:
    central_left = int(width * 0.12)
    central_right = max(central_left + 1, int(width * 0.88))
    dark_threshold = max(36, min(105, avg_luma * 0.72))
    best_rim = {
        "row": 0,
        "score": 0.0,
        "max_run_ratio": 0.0,
        "dark_ratio": 0.0,
        "edge_density": 0.0,
    }
    for y in range(int(height * 0.12), max(int(height * 0.42), int(height * 0.12) + 1)):
        max_run = 0
        current_run = 0
        dark_count = 0
        edges = 0
        comparisons = 0
        previous_dark = False
        for x in range(central_left, central_right):
            index = y * width + x
            if not mask[index]:
                current_run = 0
                previous_dark = False
                continue
            dark = luma[index] <= dark_threshold
            if dark:
                dark_count += 1
                current_run += 1
                max_run = max(max_run, current_run)
            else:
                current_run = 0
            if x > central_left:
                comparisons += 1
                if dark != previous_dark:
                    edges += 1
            previous_dark = dark
        row_width = max(1, central_right - central_left)
        run_ratio = max_run / row_width
        dark_ratio = dark_count / row_width
        edge_density = edges / max(1, comparisons)
        # Rim-like bands are long and continuous; text strokes are usually more fragmented.
        score = min(1.0, (run_ratio * 1.35) + (dark_ratio * 0.22) - (edge_density * 0.18))
        if score > best_rim["score"]:
            best_rim = {
                "row": y,
                "score": score,
                "max_run_ratio": run_ratio,
                "dark_ratio": dark_ratio,
                "edge_density": edge_density,
            }
    physical_photo = float(scene_hints.get("physical_photo_likelihood") or 0)
    printed_object = float(scene_hints.get("printed_object_or_label_likelihood") or 0)
    text_score = float(text_signals.get("score") or 0)
    rim_score = best_rim["score"]
    rounded_container = max(0.0, min(1.0, rim_score * 0.48 + physical_photo * 0.28 + printed_object * 0.18 + text_score * 0.06))
    cylindrical_surface = max(0.0, min(1.0, rounded_container * 0.72 + min(1.0, text_score) * 0.18 + physical_photo * 0.1))
    reasons = []
    if rim_score > 0.42:
        reasons.append("long dark rim-like band in upper portion")
    if physical_photo > 0.5:
        reasons.append("camera-photo lighting")
    if printed_object > 0.5:
        reasons.append("printed markings on physical surface")
    if text_score > 0.32:
        reasons.append("text bands across central surface")
    return {
        "rounded_container_likelihood": rounded_metric(rounded_container),
        "cylindrical_surface_likelihood": rounded_metric(cylindrical_surface),
        "rim_like_band": {
            "row_ratio": rounded_metric(best_rim["row"] / max(1, height)),
            "score": rounded_metric(rim_score),
            "max_run_ratio": rounded_metric(best_rim["max_run_ratio"]),
            "dark_ratio": rounded_metric(best_rim["dark_ratio"]),
            "edge_density": rounded_metric(best_rim["edge_density"]),
        },
        "reason": reasons[:6],
    }


def server_enrich_stale_image_card(card: dict[str, Any], payload: bytes) -> dict[str, Any]:
    revision = str(card.get("analyzer_revision") or "")
    analysis_source = card.get("analysis") if isinstance(card.get("analysis"), dict) else {}
    composition_source = card.get("composition") if isinstance(card.get("composition"), dict) else {}
    has_current_text_signals = (
        (revision == IMAGE_CARD_ANALYZER_REVISION or revision.startswith(f"{IMAGE_CARD_ANALYZER_REVISION}+"))
        and analysis_source.get("text_like_score") is not None
    )
    has_server_hints = isinstance(composition_source.get("scene_hints"), dict) and isinstance(
        composition_source.get("shape_hints"), dict
    )
    if has_current_text_signals and has_server_hints:
        return card
    if Image is None:
        return card
    try:
        with Image.open(io.BytesIO(payload)) as image:
            source_width, source_height = image.size
            image = image.convert("RGBA")
            scale = min(1.0, 128 / max(1, source_width, source_height))
            width = max(1, round(source_width * scale))
            height = max(1, round(source_height * scale))
            image = image.resize((width, height), Image.Resampling.LANCZOS)
            pixels = list(image.getdata())
    except Exception:
        return card
    luma = [0.0] * (width * height)
    mask = [0] * (width * height)
    count = 0
    luma_sum = 0.0
    luma_sq = 0.0
    edge_count = 0
    comparisons = 0
    center_sum = 0.0
    center_count = 0
    edge_sum = 0.0
    edge_pixels = 0
    center_left = width * 0.3
    center_right = width * 0.7
    center_top = height * 0.3
    center_bottom = height * 0.7
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[y * width + x]
            if alpha < 16:
                continue
            lum = red * 0.299 + green * 0.587 + blue * 0.114
            index = y * width + x
            luma[index] = lum
            mask[index] = 1
            count += 1
            luma_sum += lum
            luma_sq += lum * lum
            if center_left <= x <= center_right and center_top <= y <= center_bottom:
                center_sum += lum
                center_count += 1
            else:
                edge_sum += lum
                edge_pixels += 1
            if x > 0 and mask[index - 1]:
                comparisons += 1
                if abs(lum - luma[index - 1]) > 32:
                    edge_count += 1
            if y > 0 and mask[index - width]:
                comparisons += 1
                if abs(lum - luma[index - width]) > 32:
                    edge_count += 1
    if not count:
        return card
    avg_luma = luma_sum / count
    contrast = math.sqrt(max(0, (luma_sq / count) - (avg_luma * avg_luma)))
    center_luma = center_sum / max(1, center_count)
    edge_luma = edge_sum / max(1, edge_pixels)
    text_signals = server_text_like_region_signals(luma, mask, width, height, avg_luma)
    analysis = {
        **analysis_source,
        "average_luminance": rounded_metric(avg_luma / 255),
        "contrast": rounded_metric(contrast / 255),
        "edge_density": rounded_metric(edge_count / max(1, comparisons)),
        "center_luminance": rounded_metric(center_luma / 255),
        "edge_luminance": rounded_metric(edge_luma / 255),
        "center_edge_delta": rounded_metric((center_luma - edge_luma) / 255),
        "text_like_score": text_signals["score"],
        "text_band_estimate": text_signals["horizontal_band_estimate"],
        "text_active_cell_count": text_signals["active_cell_count"],
        "sample_size": f"{width}x{height}",
    }
    scene_hints = server_scene_hints(analysis, text_signals)
    shape_hints = server_shape_hints(luma, mask, width, height, avg_luma, text_signals, scene_hints)
    composition = {
        **composition_source,
        "text_regions": text_signals,
        "scene_hints": scene_hints,
        "shape_hints": shape_hints,
        "server_brightness": {
            "center_label": luminance_word(center_luma / 255),
            "edge_label": luminance_word(edge_luma / 255),
        },
    }
    visual_notes = card.get("visual_notes") if isinstance(card.get("visual_notes"), list) else []
    visual_notes = [str(note) for note in visual_notes[:12]]
    if text_signals["score"] > 0.32 and "strong text-like dark strokes on lighter regions" not in visual_notes:
        visual_notes.insert(0, "strong text-like dark strokes on lighter regions")
    elif text_signals["score"] > 0.2 and "possible printed text or label-like markings" not in visual_notes:
        visual_notes.insert(0, "possible printed text or label-like markings")
    if text_signals["horizontal_band_estimate"] >= 2:
        band_note = f"{text_signals['horizontal_band_estimate']} horizontal text-like bands"
        if band_note not in visual_notes:
            visual_notes.insert(1, band_note)
    if scene_hints["printed_object_or_label_likelihood"] > 0.58 and "likely printed label or markings on a physical photographed surface" not in visual_notes:
        visual_notes.insert(0, "likely printed label or markings on a physical photographed surface")
    if shape_hints["cylindrical_surface_likelihood"] > 0.58 and "rounded or cylindrical container-like photographed surface" not in visual_notes:
        visual_notes.insert(0, "rounded or cylindrical container-like photographed surface")
    evidence = card.get("evidence") if isinstance(card.get("evidence"), list) else []
    enrichment_source = "server_hints" if has_current_text_signals else "server_fallback"
    enrichment_revision = (
        f"{IMAGE_CARD_ANALYZER_REVISION}+server-hints"
        if has_current_text_signals
        else f"{IMAGE_CARD_ANALYZER_REVISION}+server-fallback"
    )
    enrichment_reason = (
        "browser_image_card_missing_scene_shape_hints"
        if has_current_text_signals
        else "browser_image_card_stale_or_missing_revision"
    )
    enrichment_summary = (
        "Server added scene and shape hints to a current browser image card before model inference."
        if has_current_text_signals
        else "Server enriched a stale browser image card before model inference."
    )
    server_result = {
        "module": "server-image-card-core",
        "title": "Server Image Card Core",
        "status": "active",
        "summary": enrichment_summary,
        "confidence": 0.86,
        "facts": [
            f"{width}x{height} server sample",
            f"text-like score {text_signals['score']}",
            f"{text_signals['horizontal_band_estimate']} text-like bands",
            f"printed-object label likelihood {scene_hints['printed_object_or_label_likelihood']}",
            f"cylindrical surface likelihood {shape_hints['cylindrical_surface_likelihood']}",
        ],
        "values": {
            "sample_size": f"{width}x{height}",
            "text_like_score": text_signals["score"],
            "text_band_estimate": text_signals["horizontal_band_estimate"],
            "scene_hints": scene_hints,
            "shape_hints": shape_hints,
            "source": enrichment_source,
        },
        "reason": enrichment_reason,
        "duration_ms": None,
        "cached": False,
    }
    module_results = card.get("module_results") if isinstance(card.get("module_results"), dict) else {}
    module_results = {**module_results, "server-image-card-core": server_result}
    return {
        **card,
        "analyzer_revision": enrichment_revision,
        "analysis": analysis,
        "composition": composition,
        "visual_notes": visual_notes[:12],
        "evidence": [*evidence, server_result][:8],
        "module_results": module_results,
    }


def compact_image_card(card: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    source = card if isinstance(card, dict) else {}
    fallback = fallback or {}
    palette = source.get("palette") if isinstance(source.get("palette"), list) else []
    palette_hex = source.get("palette_hex") if isinstance(source.get("palette_hex"), list) else []
    visual_notes = source.get("visual_notes") if isinstance(source.get("visual_notes"), list) else []
    analysis = source.get("analysis") if isinstance(source.get("analysis"), dict) else {}
    composition = source.get("composition") if isinstance(source.get("composition"), dict) else {}
    return {
        "schema": "hermes.wasm_agent.image_card.v1",
        "analyzer_revision": clipped(str(source.get("analyzer_revision") or ""), 80),
        "name": clipped(str(source.get("name") or fallback.get("name") or "image"), 120),
        "size": source.get("size") if isinstance(source.get("size"), int) else fallback.get("size"),
        "dimensions": clipped(str(source.get("dimensions") or ""), 80),
        "width": source.get("width") if isinstance(source.get("width"), int) else fallback.get("width"),
        "height": source.get("height") if isinstance(source.get("height"), int) else fallback.get("height"),
        "palette": [clipped(str(item), 40) for item in palette[:6]],
        "palette_hex": [clipped(str(item), 16) for item in palette_hex[:6]],
        "visual_notes": [clipped(str(item), 120) for item in visual_notes[:12]],
        "perceptual_hash": clipped(str(source.get("perceptual_hash") or ""), 120),
        "rendered_dimensions": clipped(str(source.get("rendered_dimensions") or ""), 80),
        "analysis": analysis,
        "composition": composition,
        "evidence": compact_image_evidence(source.get("evidence")),
        "module_results": compact_image_module_results(source.get("module_results")),
        "analyzer_modules": compact_image_analyzer_modules(source.get("analyzer_modules")),
        "local_url": clipped(str(source.get("local_url") or ""), 240),
        "hash": clipped(str(source.get("hash") or ""), 120),
    }


def save_agent_attachment(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    image = body.get("image") if isinstance(body.get("image"), dict) else body
    data_url = str(image.get("data_url") or "")
    mime_type, payload = parse_image_data_url(data_url)
    digest = hashlib.sha256(payload).hexdigest()
    ext = image_extension(mime_type)
    basename = f"{digest}{ext}"
    path = attachment_dir(server) / basename
    if not path.exists():
        path.write_bytes(payload)
    size = image.get("size") if isinstance(image.get("size"), int) else len(payload)
    card = compact_image_card(
        image.get("image_card"),
        {
            "name": image.get("name"),
            "size": size,
            "width": image.get("width") if isinstance(image.get("width"), int) else None,
            "height": image.get("height") if isinstance(image.get("height"), int) else None,
        },
    )
    card = compact_image_card(server_enrich_stale_image_card(card, payload), {
        "name": image.get("name"),
        "size": size,
        "width": image.get("width") if isinstance(image.get("width"), int) else None,
        "height": image.get("height") if isinstance(image.get("height"), int) else None,
    })
    card["local_url"] = f"/agent/attachments/{basename}"
    card["hash"] = digest
    metadata = {
        "schema": "hermes.wasm_agent.attachment_asset.v1",
        "hash": digest,
        "local_url": card["local_url"],
        "name": clipped(str(image.get("name") or "image"), 120),
        "type": mime_type,
        "size": len(payload),
        "declared_size": size,
        "width": image.get("width") if isinstance(image.get("width"), int) else None,
        "height": image.get("height") if isinstance(image.get("height"), int) else None,
        "original_type": clipped(str(image.get("original_type") or ""), 80),
        "original_size": image.get("original_size") if isinstance(image.get("original_size"), int) else None,
        "stored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "image_card": card,
    }
    meta_path = attachment_dir(server) / f"{digest}.json"
    tmp = meta_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8")
    tmp.replace(meta_path)
    return metadata


def serve_agent_attachment(handler: WasmAgentHandler, path: str) -> None:
    filename = path.rsplit("/", 1)[-1]
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_")
    if not filename or any(char not in allowed for char in filename):
        raise BrowserError("attachment_not_found", "Attachment was not found.", status=HTTPStatus.NOT_FOUND)
    resolved = (attachment_dir(handler.server) / filename).resolve()
    try:
        resolved.relative_to(attachment_dir(handler.server).resolve())
    except ValueError as exc:
        raise BrowserError("attachment_not_found", "Attachment was not found.", status=HTTPStatus.NOT_FOUND) from exc
    if not resolved.is_file() or resolved.suffix == ".json":
        raise BrowserError("attachment_not_found", "Attachment was not found.", status=HTTPStatus.NOT_FOUND)
    content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
    data = resolved.read_bytes()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "private, max-age=86400")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def repo_root(server: WasmAgentServer) -> Path:
    return server.plugin_root.parents[1]


def clipped(value: str, limit: int = 6000) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[clipped {len(text) - limit} chars]"


def text_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=True)) if not isinstance(value, str) else len(value)


def tool_preview(tool: dict[str, Any]) -> dict[str, Any]:
    content = str(tool.get("content") or tool.get("output") or "")
    return {
        "tool": tool.get("tool"),
        "path": tool.get("path"),
        "query": tool.get("query"),
        "returncode": tool.get("returncode"),
        "bytes": tool.get("bytes"),
        "preview": clipped(content, 900) if content else clipped(json.dumps(tool, ensure_ascii=True), 900),
    }


def compact_json(value: Any, limit: int = 900) -> str:
    return clipped(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True), limit)


def tool_output_text(tool: dict[str, Any]) -> str:
    return str(tool.get("content") or tool.get("output") or "")


def first_nonempty_line(value: str, fallback: str = "") -> str:
    for line in value.splitlines():
        text = line.strip()
        if text:
            return clipped(text, 160)
    return fallback


def parsed_tool_content(tool: dict[str, Any]) -> dict[str, Any]:
    raw = str(tool.get("content") or "")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def tool_action_label(tool: dict[str, Any]) -> str:
    name = str(tool.get("tool") or "tool")
    labels = {
        "current_turn_observation": "Inspect current UI",
        "observation_latest": "Read latest observation",
        "app_map": "Map wasm-agent surface",
        "git_status": "Check worktree status",
        "git_diff_stat": "Summarize source diff",
        "timeline_status": "Read Timeline state",
        "attachment_manifest": "Build image cards",
        "read_file": "Read file",
        "search": "Search repository",
        "doctor": "Run wasm-agent doctor",
    }
    return labels.get(name, f"Run {name}")


def tool_action_detail(tool: dict[str, Any]) -> str:
    name = str(tool.get("tool") or "tool")
    content = parsed_tool_content(tool)
    output = tool_output_text(tool)
    if name == "current_turn_observation":
        workspace = tool.get("workspace") if isinstance(tool.get("workspace"), dict) else {}
        events = tool.get("recent_events") if isinstance(tool.get("recent_events"), list) else []
        return f"{workspace.get('active_panel', 'workspace')} / {len(events)} recent events"
    if name == "observation_latest":
        workspace = tool.get("workspace") if isinstance(tool.get("workspace"), dict) else {}
        fleet = tool.get("fleet") if isinstance(tool.get("fleet"), dict) else {}
        return f"{workspace.get('active_panel', 'workspace')} / node {fleet.get('selected_node') or '-'}"
    if name == "app_map":
        files = content.get("primary_files") if isinstance(content.get("primary_files"), list) else []
        return f"{len(files)} files / {content.get('write_boundary', 'local boundary')}"
    if name == "git_status":
        lines = [line for line in output.splitlines() if line.strip()]
        return "clean" if not lines else f"{len(lines)} changed paths"
    if name == "git_diff_stat":
        return first_nonempty_line(output, "no tracked diff")
    if name == "timeline_status":
        return f"{content.get('branch', '-')} / {content.get('dirty_count', 0)} dirty / {content.get('checkpoint_count', 0)} checkpoints"
    if name == "attachment_manifest":
        received = content.get("received_count", 0)
        forwarded = content.get("forwarded_count", 0)
        summarized = content.get("summarized_count", 0)
        cards = content.get("image_card_count", 0)
        return f"{received} received / {cards} cards / {forwarded} raw to bridge / {summarized} summarized"
    if name == "read_file":
        return f"{tool.get('path') or '-'} / {tool.get('bytes') or 0} bytes"
    if name == "search":
        lines = [line for line in output.splitlines() if line.strip()]
        return f"{tool.get('query') or '-'} / {len(lines)} matches"
    if name == "doctor":
        return f"exit {tool.get('returncode', 0)} / {first_nonempty_line(output, 'no output')}"
    detail = str(tool.get("path") or tool.get("query") or tool.get("returncode") or "")
    return clipped(detail, 180)


def tool_action_arguments(tool: dict[str, Any]) -> dict[str, Any]:
    name = str(tool.get("tool") or "tool")
    args: dict[str, Any] = {"tool": name}
    if tool.get("path"):
        args["path"] = tool.get("path")
    if tool.get("query"):
        args["query"] = tool.get("query")
    if name in {"current_turn_observation", "observation_latest"}:
        args["source"] = "workspace observation snapshot"
    if name == "attachment_manifest":
        args["bridge_image_budget_bytes"] = tool.get("bridge_image_budget_bytes")
        args["forwarded_count"] = tool.get("forwarded_count")
        args["summarized_count"] = tool.get("summarized_count")
        args["image_card_count"] = tool.get("image_card_count")
    if name == "doctor":
        args["command"] = "scripts/doctor.sh"
    return args


def tool_action_preview(tool: dict[str, Any]) -> str:
    name = str(tool.get("tool") or "tool")
    if name in {"current_turn_observation", "observation_latest"}:
        payload = {
            "timestamp": tool.get("timestamp"),
            "workspace": tool.get("workspace"),
            "fleet": tool.get("fleet"),
            "requested_click_context": tool.get("requested_click_context"),
            "last_event": tool.get("last_event"),
            "recent_events": tool.get("recent_events"),
        }
        compact_payload = {
            key: value for key, value in payload.items()
            if value is not None and value != "" and value != []
        }
        return compact_json(compact_payload, 900)
    output = tool_output_text(tool)
    if output:
        return clipped(output, 900)
    return compact_json(tool, 900)


def tool_action_event(tool: dict[str, Any], index: int) -> dict[str, Any]:
    name = str(tool.get("tool") or "tool")
    returncode = tool.get("returncode")
    status = "done"
    if isinstance(returncode, int) and returncode != 0 and name != "search":
        status = "error"
    return {
        "id": f"tool_{index}_{name}",
        "kind": "tool",
        "label": tool_action_label(tool),
        "status": status,
        "detail": tool_action_detail(tool),
        "meta": name,
        "arguments": tool_action_arguments(tool),
        "preview": tool_action_preview(tool),
    }


def agent_action_events(
    tools: list[dict[str, Any]],
    *,
    mode: str,
    target_node: str,
    transcript_turns: int,
    image_count: int,
    source: str,
    duration_ms: int,
    token_usage: dict[str, Any] | None,
    auto_checkpoint: dict[str, Any] | None,
    changed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [
        {
            "id": "turn_intake",
            "kind": "turn",
            "label": "Receive chat turn",
            "status": "done",
            "detail": f"{target_node} / {mode}",
            "meta": f"{transcript_turns} transcript turns / {image_count} images",
        }
    ]
    for index, tool in enumerate(tools, 1):
        actions.append(tool_action_event(tool, index))
    total_tokens = token_usage.get("total_tokens") if isinstance(token_usage, dict) else None
    token_detail = f"{total_tokens} tokens" if isinstance(total_tokens, int) else "tokens unknown"
    actions.append({
        "id": "node_reply",
        "kind": "model",
        "label": "Receive final reply",
        "status": "done",
        "detail": f"{source} / {duration_ms} ms",
        "meta": token_detail,
    })
    if changed:
        actions.append({
            "id": "changed_files",
            "kind": "timeline",
            "label": "Capture changed files",
            "status": "done",
            "detail": f"{len(changed)} paths",
            "preview": compact_json(changed[:12], 900),
        })
    if auto_checkpoint:
        actions.append({
            "id": "timeline_checkpoint",
            "kind": "timeline",
            "label": "Timeline checkpoint",
            "status": "done",
            "detail": clipped(str(auto_checkpoint.get("label") or ""), 160),
            "meta": str(auto_checkpoint.get("sha") or "")[:7],
            "preview": compact_json(auto_checkpoint, 900),
        })
    return actions


def relative_repo_path(server: WasmAgentServer, raw: str) -> Path:
    root = repo_root(server).resolve()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise BrowserError("agent_path_denied", "Tool path must stay inside /local.") from exc
    return resolved


def agent_read_file(server: WasmAgentServer, path: str) -> dict[str, Any]:
    resolved = relative_repo_path(server, path)
    if not resolved.is_file():
        raise BrowserError("agent_file_not_found", f"File was not found: {path}", status=HTTPStatus.NOT_FOUND)
    text = resolved.read_text(encoding="utf-8", errors="replace")
    return {
        "tool": "read_file",
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "content": clipped(text),
    }


def agent_search(server: WasmAgentServer, query: str) -> dict[str, Any]:
    pattern = str(query or "").strip()
    if not pattern:
        raise BrowserError("agent_missing_query", "Search query is required.")
    root = repo_root(server)
    proc = subprocess.run(
        ["rg", "-n", "--glob", "!plugins/hermes-space-ui/state/**", "--glob", "!logs/**", pattern, str(root)],
        text=True,
        capture_output=True,
        timeout=8,
        check=False,
    )
    output = proc.stdout or proc.stderr
    return {"tool": "search", "query": pattern, "returncode": proc.returncode, "output": clipped(output, 5000)}


def agent_git_status(server: WasmAgentServer) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root(server)), "status", "--short"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    return {"tool": "git_status", "returncode": proc.returncode, "output": clipped(proc.stdout or proc.stderr, 4000)}


def changed_files(server: WasmAgentServer) -> list[dict[str, Any]]:
    root = repo_root(server)
    proc = git_run(server, ["status", "--short", "-uall"], timeout=5)
    if proc.returncode != 0:
        return []
    numstat_proc = git_run(server, ["diff", "HEAD", "--numstat"], timeout=5)
    numstat: dict[str, tuple[int | None, int | None]] = {}
    if numstat_proc.returncode == 0:
        for row in (numstat_proc.stdout or "").splitlines():
            parts = row.split("\t")
            if len(parts) < 3:
                continue
            added = None if parts[0] == "-" else int(parts[0])
            deleted = None if parts[1] == "-" else int(parts[1])
            numstat[parts[2]] = (added, deleted)
    files: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        if not line:
            continue
        status = line[:2].strip() or "?"
        path = line[3:] if len(line) > 3 else line[2:].strip()
        stat_path = path.split(" -> ", 1)[-1]
        additions, deletions = numstat.get(stat_path, (None, None))
        full_path = str((root / stat_path).resolve())
        if additions is None and deletions is None and status == "??":
            candidate = root / stat_path
            if candidate.is_file() and candidate.stat().st_size <= 1024 * 1024:
                try:
                    additions = len(candidate.read_text(encoding="utf-8", errors="replace").splitlines())
                    deletions = 0
                except OSError:
                    additions = None
                    deletions = None
        files.append(
            {
                "status": status,
                "path": stat_path,
                "full_path": full_path,
                "additions": additions,
                "deletions": deletions,
                "diff": f"+{additions or 0} -{deletions or 0}" if additions is not None or deletions is not None else "",
            }
        )
    return files[:40]


def agent_git_diff_stat(server: WasmAgentServer) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root(server)), "diff", "--stat"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    return {"tool": "git_diff_stat", "returncode": proc.returncode, "output": clipped(proc.stdout or proc.stderr, 4000)}


def agent_timeline_status(server: WasmAgentServer) -> dict[str, Any]:
    timeline = timeline_status(server)
    return {
        "tool": "timeline_status",
        "content": json.dumps(
            {
                "branch": timeline.get("branch"),
                "head": timeline.get("head"),
                "dirty": timeline.get("dirty"),
                "dirty_count": timeline.get("dirty_count"),
                "checkpoint_count": len(timeline.get("checkpoints") or []),
                "latest_checkpoint": (timeline.get("checkpoints") or [{}])[0],
                "actions": timeline.get("actions") or [],
            },
            ensure_ascii=True,
        ),
    }


def agent_doctor(server: WasmAgentServer) -> dict[str, Any]:
    proc = subprocess.run(
        [str(server.plugin_root / "scripts" / "doctor.sh")],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    return {"tool": "doctor", "returncode": proc.returncode, "output": clipped((proc.stdout or "") + (proc.stderr or ""), 4000)}


def agent_app_map(server: WasmAgentServer) -> dict[str, Any]:
    files = [
        "plugins/wasm-agent/public/app.js",
        "plugins/wasm-agent/public/index.html",
        "plugins/wasm-agent/public/styles.css",
        "plugins/wasm-agent/server/static_server.py",
        "plugins/wasm-agent/tests/wasm_agent_smoke.test.js",
        "plugins/wasm-agent/README.md",
        "docs/roadmap/space-os/embedded-agent-path.md",
    ]
    root = repo_root(server)
    entries = []
    for item in files:
        path = root / item
        if path.exists():
            entries.append({"path": item, "bytes": path.stat().st_size})
    return {
        "tool": "app_map",
        "content": json.dumps(
            {
                "goal": "Evolve wasm-agent as the active WASM harness: embedded chat, observation, Timeline recovery, Host Browser stream, and image-card perception.",
                "write_boundary": "In-app agent proposes changes; outer orchestrator applies filesystem mutations until confirmation-first mutation tools exist.",
                "primary_files": entries,
                "current_chat_contract": {
                    "endpoint": "/agent/session/message",
                    "modes": ["auto", "local", "bridge"],
                    "tools": [
                        "observation_latest",
                        "read_file",
                        "search",
                        "git_status",
                        "git_diff_stat",
                        "timeline_status",
                        "doctor",
                        "app_map",
                        "attachment_manifest",
                    ],
                },
            },
            ensure_ascii=True,
        ),
    }


def agent_latest_observation(server: WasmAgentServer) -> dict[str, Any]:
    payload = latest_observation(server).get("observation") or {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "tool": "observation_latest",
        "timestamp": payload.get("timestamp", ""),
        "workspace": payload.get("workspace", {}),
        "fleet": {
            "selected_node": payload.get("fleet", {}).get("selected_node"),
            "node_count": payload.get("fleet", {}).get("node_count"),
            "bridge_ready": payload.get("fleet", {}).get("bridge_ready"),
        },
        "requested_click_context": payload.get("requested_click_context") or payload.get("analytics", {}).get("last_non_agent_click"),
        "last_event": (payload.get("user_events") or [{}])[0],
    }


def infer_agent_tools(
    server: WasmAgentServer,
    message: str,
    *,
    action_callback: Any | None = None,
    action_offset: int = 0,
) -> list[dict[str, Any]]:
    lowered = message.lower()
    tools: list[dict[str, Any]] = []
    seen = set()

    def add_tool(tool: dict[str, Any]) -> None:
        if len(tools) >= 6:
            return
        key = (tool.get("tool"), tool.get("path"), tool.get("query"))
        if key in seen:
            return
        seen.add(key)
        tools.append(tool)
        if action_callback:
            action_callback(tool_action_event(tool, action_offset + len(tools)))

    add_tool(agent_latest_observation(server))
    wants_evolution_context = any(
        phrase in lowered
        for phrase in (
            "evolve the app",
            "evolve app",
            "from chat",
            "from there",
            "cheaper",
            "chat",
            "adapter",
            "ui",
            "patch proposal",
            "real patch",
            "proposal",
            "patch",
        )
    )
    if wants_evolution_context:
        add_tool(agent_app_map(server))
        add_tool(agent_git_status(server))
        add_tool(agent_git_diff_stat(server))
        add_tool(agent_timeline_status(server))
    if "read /local/readme.md" in lowered or "read readme" in lowered or "resume our work" in lowered:
        add_tool(agent_read_file(server, "/local/README.md"))
        roadmap = repo_root(server) / "docs" / "roadmap" / "space-os" / "embedded-agent-path.md"
        if roadmap.exists():
            add_tool(agent_read_file(server, str(roadmap)))
    if "git status" in lowered or "worktree" in lowered:
        add_tool(agent_git_status(server))
    if "doctor" in lowered or "health" in lowered:
        add_tool(agent_doctor(server))
    if lowered.startswith("search ") or "\nsearch " in lowered:
        query = message.split("search ", 1)[1].splitlines()[0]
        add_tool(agent_search(server, query))
    return tools


def compact_transcript(body: dict[str, Any]) -> list[dict[str, str]]:
    transcript = body.get("transcript")
    if not isinstance(transcript, list):
        return []
    compact: list[dict[str, str]] = []
    seed_message = "I can see this workspace snapshot and help evolve the app from here."
    current_message = str(body.get("message") or "").strip()
    for item in transcript[-6:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")[:20]
        content = clipped(str(item.get("content") or ""), 600)
        if content == seed_message or (role == "user" and content == current_message):
            continue
        if role in {"user", "assistant"} and content:
            compact.append({"role": role, "content": content})
    return compact


def compact_agent_images(images: Any) -> list[dict[str, Any]] | None:
    if not isinstance(images, list):
        return None
    compact: list[dict[str, Any]] = []
    for item in images[:DEFAULT_AGENT_IMAGE_LIMIT]:
        if not isinstance(item, dict):
            continue
        data_url = str(item.get("data_url") or "")
        if not data_url.startswith("data:image/"):
            continue
        approx_bytes = len(data_url.encode("utf-8"))
        if approx_bytes > DEFAULT_AGENT_IMAGE_MAX_BYTES * 2:
            continue
        compact.append({
            "data_url": data_url,
            "name": clipped(str(item.get("name") or "image"), 120),
            "type": clipped(str(item.get("type") or ""), 80),
            "size": item.get("size") if isinstance(item.get("size"), int) else approx_bytes,
            "width": item.get("width") if isinstance(item.get("width"), int) else None,
            "height": item.get("height") if isinstance(item.get("height"), int) else None,
            "image_card": compact_image_card(item.get("image_card"), item),
            "asset": item.get("asset") if isinstance(item.get("asset"), dict) else None,
        })
    return compact or None


def compact_agent_attachment_summaries(attachments: Any) -> list[dict[str, Any]]:
    if not isinstance(attachments, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in attachments[:DEFAULT_AGENT_IMAGE_LIMIT]:
        if not isinstance(item, dict):
            continue
        compact.append({
            "name": clipped(str(item.get("name") or "attachment"), 120),
            "type": clipped(str(item.get("type") or item.get("original_type") or ""), 80),
            "size": item.get("size") if isinstance(item.get("size"), int) else None,
            "width": item.get("width") if isinstance(item.get("width"), int) else None,
            "height": item.get("height") if isinstance(item.get("height"), int) else None,
            "original_type": clipped(str(item.get("original_type") or ""), 80),
            "original_size": item.get("original_size") if isinstance(item.get("original_size"), int) else None,
            "image_card": compact_image_card(item.get("image_card"), item),
            "asset": item.get("asset") if isinstance(item.get("asset"), dict) else None,
            "reason": clipped(str(item.get("reason") or "summarized"), 120),
        })
    return compact


def agent_image_data_url_bytes(image: dict[str, Any]) -> int:
    return len(str(image.get("data_url") or "").encode("utf-8"))


def agent_image_descriptor(
    image: dict[str, Any],
    *,
    raw_included: bool,
    forwarded_to_bridge: bool,
    reason: str = "",
) -> dict[str, Any]:
    image_card = compact_image_card(image.get("image_card"), image)
    asset = image.get("asset") if isinstance(image.get("asset"), dict) else {}
    local_url = str(asset.get("local_url") or image_card.get("local_url") or "")
    digest = str(asset.get("hash") or image_card.get("hash") or "")
    if local_url:
        image_card["local_url"] = clipped(local_url, 240)
    if digest:
        image_card["hash"] = clipped(digest, 120)
    return {
        "name": clipped(str(image.get("name") or "image"), 120),
        "type": clipped(str(image.get("type") or image.get("original_type") or ""), 80),
        "size": image.get("size") if isinstance(image.get("size"), int) else agent_image_data_url_bytes(image),
        "width": image.get("width") if isinstance(image.get("width"), int) else None,
        "height": image.get("height") if isinstance(image.get("height"), int) else None,
        "original_type": clipped(str(image.get("original_type") or ""), 80),
        "original_size": image.get("original_size") if isinstance(image.get("original_size"), int) else None,
        "local_url": local_url,
        "hash": digest,
        "image_card": image_card,
        "raw_included": raw_included,
        "forwarded_to_bridge": forwarded_to_bridge,
        "reason": reason,
    }


def agent_bridge_forwards_image_urls() -> bool:
    raw = os.getenv(
        "HERMES_WASM_AGENT_FORWARD_IMAGE_URLS",
        "1" if DEFAULT_AGENT_BRIDGE_FORWARD_IMAGE_URLS else "0",
    ).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def plan_bridge_attachments(
    images: list[dict[str, Any]] | None,
    summaries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    forwarded: list[dict[str, Any]] = []
    descriptors: list[dict[str, Any]] = []
    forwarded_bytes = 0
    may_forward_image_urls = agent_bridge_forwards_image_urls()
    for image in images or []:
        data_url_bytes = agent_image_data_url_bytes(image)
        can_forward = (
            may_forward_image_urls
            and data_url_bytes > 0
            and data_url_bytes <= DEFAULT_AGENT_BRIDGE_IMAGE_SINGLE_BYTES
            and forwarded_bytes + data_url_bytes <= DEFAULT_AGENT_BRIDGE_IMAGE_BYTES
        )
        if can_forward:
            forwarded.append(image)
            forwarded_bytes += data_url_bytes
        descriptors.append(agent_image_descriptor(
            image,
            raw_included=True,
            forwarded_to_bridge=can_forward,
            reason="" if can_forward else (
                "bridge_image_url_forwarding_disabled"
                if not may_forward_image_urls
                else "summarized_to_keep_bridge_request_small"
            ),
        ))
    for item in summaries:
        descriptors.append({
            **agent_image_descriptor(
                item,
                raw_included=False,
                forwarded_to_bridge=False,
                reason=str(item.get("reason") or "summarized"),
            ),
            "size": item.get("size") if isinstance(item.get("size"), int) else None,
        })
    if not descriptors:
        return forwarded, None
    manifest = {
        "attachments": descriptors,
        "received_count": len(descriptors),
        "forwarded_count": len(forwarded),
        "summarized_count": len(descriptors) - len(forwarded),
        "image_card_count": sum(1 for item in descriptors if item.get("image_card")),
        "bridge_image_bytes": forwarded_bytes,
        "bridge_image_budget_bytes": DEFAULT_AGENT_BRIDGE_IMAGE_BYTES,
        "image_url_forwarding_enabled": may_forward_image_urls,
        "policy": (
            "Forward raw image_url parts only when HERMES_WASM_AGENT_FORWARD_IMAGE_URLS is enabled "
            "and the bridge request stays under its size budget; always preserve compact browser-built "
            "image_card metadata for text-only providers. Treat filenames, local URLs, and surrounding "
            "workspace state as context, not visual proof. Do not claim object identity, wallpaper/background "
            "role, OCR text, or UI placement unless raw vision or user-provided context establishes it."
        ),
        "semantic_limits": [
            "image_card is browser pixel metadata, not full object recognition",
            "filename and local_url are not visual evidence",
            "shape hints are not object identity",
            "do not infer wallpaper/background role from a name like bg",
        ],
    }
    return forwarded, {
        "tool": "attachment_manifest",
        "received_count": manifest["received_count"],
        "forwarded_count": manifest["forwarded_count"],
        "summarized_count": manifest["summarized_count"],
        "image_card_count": manifest["image_card_count"],
        "bridge_image_budget_bytes": DEFAULT_AGENT_BRIDGE_IMAGE_BYTES,
        "content": json.dumps(manifest, ensure_ascii=True),
    }


def redact_image_card_focus_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("tool") != "attachment_manifest":
            sanitized.append(tool)
            continue
        try:
            manifest = json.loads(str(tool.get("content") or "{}"))
        except json.JSONDecodeError:
            sanitized.append(tool)
            continue
        if not isinstance(manifest, dict):
            sanitized.append(tool)
            continue
        attachments = manifest.get("attachments")
        if not isinstance(attachments, list):
            sanitized.append(tool)
            continue
        redacted_attachments: list[Any] = []
        for index, item in enumerate(attachments):
            if not isinstance(item, dict):
                redacted_attachments.append(item)
                continue
            label = f"attachment-{index + 1}"
            clean_item = {**item, "name": label, "local_url": "", "hash": ""}
            image_card = clean_item.get("image_card") if isinstance(clean_item.get("image_card"), dict) else None
            if image_card:
                clean_item["image_card"] = {**image_card, "name": label, "local_url": "", "hash": ""}
            redacted_attachments.append(clean_item)
        policy = str(manifest.get("policy") or "")
        manifest = {
            **manifest,
            "attachments": redacted_attachments,
            "policy": (
                f"{policy} Attachment names, hashes, and local URLs are redacted from image-card-only "
                "model context because they are bookkeeping, not visual evidence."
            ).strip(),
        }
        sanitized.append({**tool, "content": json.dumps(manifest, ensure_ascii=True)})
    return sanitized


def agent_bridge_timeout_sec() -> float:
    raw = os.getenv("HERMES_WASM_AGENT_CHAT_TIMEOUT_SEC", str(DEFAULT_AGENT_BRIDGE_TIMEOUT_SEC))
    try:
        value = float(raw)
    except ValueError:
        value = DEFAULT_AGENT_BRIDGE_TIMEOUT_SEC
    return max(30.0, min(6 * 60 * 60.0, value))


def call_agent_bridge(
    server: WasmAgentServer,
    message: str,
    tools: list[dict[str, Any]],
    transcript: list[dict[str, str]],
    target_node: str,
    images: list[dict[str, Any]] | None = None,
    image_card_focus: bool = False,
) -> tuple[str, str, dict[str, Any] | None]:
    timeout_sec = agent_bridge_timeout_sec()
    context_label = "Image-card tool results" if image_card_focus else "Tool results"
    text_content = (
        f"Recent transcript:\n{json.dumps(transcript, ensure_ascii=True)}\n\n"
        f"{context_label}:\n{json.dumps(tools, ensure_ascii=True)}\n\n"
        f"User message:\n{message}"
    )
    if images:
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": text_content}]
        for img in images:
            data_url = str(img.get("data_url") or "")
            if data_url:
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": data_url},
                })
        user_content = content_parts
    else:
        user_content = text_content
    system_content = (
        f"You are the configured embedded agent inside wasm-agent talking through target node `{target_node}`. "
        "Use compact tool results to answer briefly. You may inspect context, "
        "but do not claim you executed mutations or shell actions beyond listed tools. "
        "If the current user message is ambiguous and includes attachments, treat words like 'it' or 'this' "
        "as referring to the attachment unless the user explicitly asks about the workspace or app. "
        "Attachment image_card data is cheap browser pixel metadata, not full vision. "
        "When raw image_url parts were not forwarded, say what the image_card supports and avoid claims "
        "about object identity, wallpaper/background role, OCR text, or UI placement. "
        "Do not treat filenames, local URLs, or surrounding workspace state as visual proof. "
        "There is no vision_analyze tool in this adapter; never offer or name fake vision tools. "
        "When the user asks about the last clicked UI button, use observation.requested_click_context.last_non_agent_click "
        "instead of assistant open/send events. "
        "When the user asks to evolve the app, produce a concrete, small implementation brief: "
        "files, behavior, verification, and whether it needs outer-orchestrator application."
    )
    if image_card_focus:
        system_content += (
            " This is an attached-image interpretation turn. Use the image_card metadata as the primary source. "
            "Give the best minimal interpretation the metadata supports, with uncertainty. "
            "You may infer broad visual character from dimensions, palette, luminance, contrast, edge density, "
            "sharpness, entropy, saturation, transparency, visual_notes, and composition fields such as "
            "brightness_distribution, gradient, symmetry, text_regions, scene_hints, shape_hints, and analysis fields like text_like_score. "
            "Text-like scores support claims about likely printed/label-like markings, not exact transcription. "
            "Only quote OCR text when an OCR evidence item has status detected and includes text facts. "
            "OCR text is evidence for readable words only; it does not identify the object carrying those words. "
            "Do not mention attachment filenames, hashes, or local URLs in image-card-only answers unless the user asks about file bookkeeping. "
            "When scene_hints suggests a physical photographed surface, prefer wording like printed label/markings on a photographed object "
            "over document, receipt, or screenshot unless the card specifically supports those categories. "
            "When shape_hints suggests a rounded container or cylindrical surface, say photographed rounded/cylindrical "
            "container-like object or surface rather than generic package/box/sign; do not narrow it to mug, cup, can, "
            "bottle, packaged product, or another object identity unless raw vision or user context supports it. "
            "If examples are useful, label them as examples of the shape class, not the likely identity. "
            "When there is no raw image_url part, avoid identity words like mug, cup, can, bottle, "
            "package, packaged product, drink can, or product label; use rounded/cylindrical physical object or surface "
            "with printed markings instead. "
            "Use evidence, module_results, and analyzer_modules as provenance; "
            "distinguish detected, not_detected, disabled, unsupported, not_loaded, timeout, and error statuses. "
            "If analyzer_revision is missing or older than image-card-text-v2, mention that the browser is likely still using a stale image-card runtime. "
            "Do not infer from workspace observations because they were intentionally omitted. "
            "Do not assert wallpaper/background role, object identity, OCR text, or exact scene content unless the "
            "image_card explicitly supports it. Do not offer to run raw vision analysis from this adapter; "
            "when raw image_url parts were not forwarded, simply say exact recognition would require an explicitly "
            "vision-capable provider path. Keep the answer short and useful."
        )

    def build_payload(content: str | list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "model": "embedded-hermes",
            "stream": False,
            "target_node": target_node,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": content},
            ],
            "timeout_sec": timeout_sec,
        }

    payload = build_payload(user_content)
    payload_data = json.dumps(payload).encode("utf-8")
    if images and len(payload_data) > DEFAULT_AGENT_BRIDGE_REQUEST_BYTES:
        user_content = (
            text_content
            + "\n\nRaw attachment payloads were omitted because the bridge request budget would be exceeded. "
            "Use the attachment_manifest tool result above for image-card metadata."
        )
        payload = build_payload(user_content)
        payload_data = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{server.bridge_url}/v1/chat/completions",
        data=payload_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return deterministic_agent_reply(message, tools, f"Bridge model did not answer within budget: {exc}"), "local_fallback", {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "source": "local_fallback",
        }
    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    if not choices:
        return "The bridge returned no assistant choices.", "bridge_empty", usage
    message_obj = choices[0].get("message") if isinstance(choices[0], dict) else {}
    return str(message_obj.get("content") or "The bridge returned an empty assistant response."), "bridge_model", usage


def attachment_cards_from_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("tool") != "attachment_manifest":
            continue
        content = parsed_tool_content(tool)
        attachments = content.get("attachments") if isinstance(content.get("attachments"), list) else []
        for item in attachments:
            if not isinstance(item, dict):
                continue
            card = item.get("image_card") if isinstance(item.get("image_card"), dict) else {}
            if not card:
                continue
            cards.append({
                "analyzer_revision": card.get("analyzer_revision") or "",
                "name": item.get("name") or card.get("name") or "image",
                "dimensions": card.get("dimensions") or (
                    f"{item.get('width')}x{item.get('height')}"
                    if item.get("width") and item.get("height")
                    else ""
                ),
                "size": item.get("size") or card.get("size"),
                "palette": card.get("palette") if isinstance(card.get("palette"), list) else [],
                "visual_notes": card.get("visual_notes") if isinstance(card.get("visual_notes"), list) else [],
                "analysis": card.get("analysis") if isinstance(card.get("analysis"), dict) else {},
                "composition": card.get("composition") if isinstance(card.get("composition"), dict) else {},
                "evidence": card.get("evidence") if isinstance(card.get("evidence"), list) else [],
                "module_results": card.get("module_results") if isinstance(card.get("module_results"), dict) else {},
                "analyzer_modules": card.get("analyzer_modules") if isinstance(card.get("analyzer_modules"), list) else [],
                "local_url": item.get("local_url") or card.get("local_url") or "",
                "hash": item.get("hash") or card.get("hash") or card.get("perceptual_hash") or "",
                "forwarded_to_bridge": item.get("forwarded_to_bridge"),
            })
    return cards


def image_question_hint(message: str) -> bool:
    lowered = message.lower().strip()
    if not lowered:
        return True
    image_terms = (
        "what is it",
        "what's this",
        "what is this",
        "what am i looking",
        "describe",
        "attached",
        "attachment",
        "image",
        "picture",
        "photo",
        "screenshot",
    )
    if any(term in lowered for term in image_terms):
        return True
    words = lowered.replace("?", "").split()
    return len(words) <= 5 and any(word in {"it", "this", "that"} for word in words)


def asks_about_attached_image(message: str, cards: list[dict[str, Any]]) -> bool:
    return bool(cards) and image_question_hint(message)


def image_card_reply(cards: list[dict[str, Any]], reason: str) -> str:
    lines = [
        f"{reason}. I only have the browser-built image card for this turn, not full object recognition.",
        "",
        "What I can safely say:",
    ]
    for card in cards[:3]:
        palette = ", ".join(str(item) for item in card.get("palette", [])[:4]) or "unknown palette"
        notes = ", ".join(str(item) for item in card.get("visual_notes", [])[:5]) or "no visual notes"
        analysis = card.get("analysis") if isinstance(card.get("analysis"), dict) else {}
        composition = card.get("composition") if isinstance(card.get("composition"), dict) else {}
        gradient = composition.get("gradient") if isinstance(composition.get("gradient"), dict) else {}
        gradient_text = f" Gradient: {gradient.get('kind')} ({gradient.get('strength')})." if gradient.get("kind") else ""
        text_like = analysis.get("text_like_score")
        text_text = f" Text-like score: {text_like}." if isinstance(text_like, (int, float)) else ""
        revision = str(card.get("analyzer_revision") or "")
        revision_text = f" Analyzer revision: `{clipped(revision, 80)}`." if revision else ""
        evidence = card.get("evidence") if isinstance(card.get("evidence"), list) else []
        evidence_text = "; ".join(
            f"{item.get('module')}: {item.get('status')}"
            for item in evidence[:4]
            if isinstance(item, dict) and item.get("module")
        )
        size = f"{card.get('size')} bytes" if isinstance(card.get("size"), int) else "unknown size"
        local_url = str(card.get("local_url") or "")
        lines.append(
            f"- `{clipped(str(card.get('name') or 'image'), 80)}`: "
            f"{card.get('dimensions') or 'unknown dimensions'}, {size}, palette {palette}; notes: {notes}.{gradient_text}{text_text}"
        )
        if evidence_text:
            lines.append(f"  Analyzer evidence: {clipped(evidence_text, 180)}.")
        if local_url:
            lines.append(f"  Local asset: `{clipped(local_url, 120)}`.")
        if revision_text:
            lines.append(f"  {revision_text}")
    lines.extend([
        "",
        "What I should not claim from this metadata alone: object identity, OCR text, or that it is the workspace background/wallpaper. A filename like `bg` is only a hint, not visual proof.",
    ])
    return "\n".join(lines)


def deterministic_agent_reply(message: str, tools: list[dict[str, Any]], reason: str) -> str:
    tool_names = ", ".join(str(tool.get("tool")) for tool in tools)
    lowered = message.lower()
    cards = attachment_cards_from_tools(tools)
    if asks_about_attached_image(message, cards):
        return image_card_reply(cards, reason)
    if "last" in lowered and ("click" in lowered or "button" in lowered):
        click = {}
        for tool in tools:
            context = tool.get("requested_click_context") if isinstance(tool.get("requested_click_context"), dict) else {}
            candidate = context.get("last_non_agent_click") if isinstance(context.get("last_non_agent_click"), dict) else None
            if candidate:
                click = candidate
                break
            candidate = tool.get("last_event") if isinstance(tool.get("last_event"), dict) else None
            if candidate and candidate.get("type") == "workspace.click":
                click = candidate
                break
        if click:
            target = click.get("target") or "unknown"
            detail = click.get("data", {}).get("target", {}) if isinstance(click.get("data"), dict) else {}
            classes = " ".join(detail.get("classes") or [])
            title = detail.get("title") or detail.get("aria_label") or target
            return (
                f"The last non-chat UI click I can see was `{target}` at `{click.get('timestamp', '')}`. "
                f"It was the `{title}` button"
                f"{f' with classes `{classes}`' if classes else ''}."
            )
        return "I do not have a non-chat button click in the current observation yet."
    if "resume our work" in lowered or "read /local/readme.md" in lowered:
        return (
            "I read the available local context with inspect-only tools. "
            f"{reason}.\n\n"
            "Current direction: resume from the WASM harness saga. Keep Hermes Orchestrator and wasm-agent "
            "aligned with performance, efficiency, and simplicity. The active work is the in-workspace harness: "
            "Host Browser stream, Observation, embedded assistant, Timeline recovery, and browser-built image cards "
            "that let text-only nodes reason over compact visual facts.\n\n"
            "What I can do from inside the app now: inspect the latest observation, read allowlisted files, "
            "search the repo, check git status, and run the wasm-agent doctor. Mutation tools are intentionally "
            "future work and should be confirmation-first.\n\n"
            f"Tools used: {tool_names}."
        )
    if (
        "evolve" in lowered
        or "chat" in lowered
        or "cheaper" in lowered
        or "from there" in lowered
        or "proposal" in lowered
        or "patch" in lowered
    ):
        if "checkpoint" in lowered and ("already exists" in lowered or "exists" in lowered or "show whether" in lowered):
            return (
                f"I gathered compact app-evolution context with: {tool_names}. {reason}.\n\n"
                "Implementation brief:\n"
                "- Files: `plugins/wasm-agent/public/app.js`, `plugins/wasm-agent/public/styles.css`, "
                "`plugins/wasm-agent/tests/wasm_agent_smoke.test.js`, `plugins/wasm-agent/README.md`.\n"
                "- Behavior: remove manual proposal cards and let Timeline record named recovery points automatically "
                "only when a chat turn actually changes the worktree.\n"
                "- UI details: keep checkpoint evidence in the Timeline road, not inside assistant message chrome.\n"
                "- Verification: run `/local/plugins/wasm-agent/scripts/doctor.sh`, `git diff --check`, and probe "
                "`/agent/session/message` with a no-op greeting to confirm `changed_files` is empty.\n"
                "- Apply path: let the selected node answer the turn; the local adapter records a timeline point only if files changed."
            )
        return (
            f"I gathered compact app-evolution context with: {tool_names}. {reason}.\n\n"
            "Implementation brief:\n"
            "- Files: `plugins/wasm-agent/public/app.js`, `plugins/wasm-agent/public/styles.css`, "
            "`plugins/wasm-agent/tests/wasm_agent_smoke.test.js`, `plugins/wasm-agent/README.md`.\n"
            "- Behavior: keep app-evolution turns on a compact tool path, send the selected target node in the bridge payload, "
            "and leave filesystem mutation recovery to automatic Timeline points.\n"
            "- Verification: run `/local/plugins/wasm-agent/scripts/doctor.sh`, `git diff --check`, and probe "
            "`/agent/session/message` with `mode:auto` plus a selected `target_node`.\n"
            "- Apply path: the selected node handles the turn; the adapter names any resulting checkpoint after the target and prompt."
        )
    return (
        f"I gathered inspect-only context with: {tool_names}. {reason}. "
        "The local adapter is alive, but the model backend was unavailable or slow for this turn."
    )


def embedded_agent_message(
    server: WasmAgentServer,
    body: dict[str, Any],
    *,
    action_callback: Any | None = None,
) -> dict[str, Any]:
    message = str(body.get("message") or "").strip()
    if not message:
        raise BrowserError("agent_missing_message", "Message is required.")
    mode = str(body.get("mode") or "auto").strip().lower()
    if mode not in {"auto", "local", "bridge"}:
        raise BrowserError("agent_invalid_mode", "Agent mode must be auto, local, or bridge.")
    target_node = str(body.get("target_node") or body.get("node_id") or "orchestrator").strip() or "orchestrator"
    raw_attachment_present = bool(body.get("images") or body.get("attachments"))
    image_focused_turn = raw_attachment_present and image_question_hint(message)
    before_tree = safe_worktree_tree_sha(server)
    started = time.monotonic()
    observation = body.get("observation") if isinstance(body.get("observation"), dict) else {}
    tools: list[dict[str, Any]] = []
    if observation and not image_focused_turn:
        current_observation_tool = {
            "tool": "current_turn_observation",
            "timestamp": observation.get("timestamp", ""),
            "workspace": observation.get("workspace", {}),
            "requested_click_context": observation.get("requested_click_context", {}),
            "recent_events": observation.get("recent_events", [])[:6],
        }
        tools.append(current_observation_tool)
        if action_callback:
            action_callback(tool_action_event(current_observation_tool, 1))
    if not image_focused_turn:
        tools.extend(infer_agent_tools(
            server,
            message,
            action_callback=action_callback,
            action_offset=len(tools),
        ))
    transcript = compact_transcript(body)
    images = body.get("images")
    images = compact_agent_images(images)
    attachment_summaries = compact_agent_attachment_summaries(body.get("attachments"))
    bridge_images, attachment_manifest = plan_bridge_attachments(images, attachment_summaries)
    if attachment_manifest:
        tools.append(attachment_manifest)
        if action_callback:
            action_callback(tool_action_event(attachment_manifest, len(tools)))
    image_count = len(images or []) + len(attachment_summaries)
    lowered = message.lower()
    if mode == "local":
        reply = deterministic_agent_reply(message, tools, "Answered in local-only mode")
        source = "local_deterministic"
        token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "source": "local_deterministic",
        }
    elif mode == "auto" and asks_about_attached_image(message, attachment_cards_from_tools(tools)):
        if action_callback:
            action_callback({
                "id": "node_reply",
                "kind": "model",
                "label": "Infer from image card",
                "status": "running",
                "detail": f"{target_node} / image_card",
                "meta": "waiting",
            })
        focus_tools = redact_image_card_focus_tools([attachment_manifest] if attachment_manifest else tools)
        reply, source, token_usage = call_agent_bridge(
            server,
            message,
            focus_tools,
            transcript,
            target_node,
            images=None,
            image_card_focus=True,
        )
        if source.startswith("local_"):
            reply = deterministic_agent_reply(
                message,
                tools,
                "Answered locally from image-card metadata because the bridge image-card inference path was unavailable",
            )
            source = "local_image_card_fallback"
            token_usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "source": "local_image_card_fallback",
            }
        elif source == "bridge_model":
            source = "bridge_image_card"
    elif mode == "auto" and (
        "resume our work" in lowered
        or "read /local/readme.md" in lowered
    ):
        reply = deterministic_agent_reply(message, tools, "Answered locally for this known inspect/resume request")
        source = "local_deterministic"
        token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "source": "local_deterministic",
        }
    else:
        if action_callback:
            action_callback({
                "id": "node_reply",
                "kind": "model",
                "label": "Receive final reply",
                "status": "running",
                "detail": f"{target_node} / {mode}",
                "meta": "waiting",
            })
        reply, source, token_usage = call_agent_bridge(server, message, tools, transcript, target_node, images=bridge_images)
    duration_ms = int((time.monotonic() - started) * 1000)
    context_bytes = sum(text_size(tool) for tool in tools)
    after_tree = safe_worktree_tree_sha(server)
    files = changed_files_between_trees(server, before_tree, after_tree)
    checkpoint_summary = run_checkpoint_summary(message)
    auto_checkpoint = (
        timeline_auto_checkpoint(
            server,
            f"chat-{target_node}-{checkpoint_summary}",
            message=f"wasm-agent chat on {target_node}: {checkpoint_summary}",
            tree_sha=after_tree,
        )
        if files
        else None
    )
    return {
        "schema": "hermes.wasm_agent.embedded_agent.message.v1",
        "session_id": str(body.get("session_id") or "local"),
        "target_node": target_node,
        "reply": clipped(reply, 8000),
        "tools": [{"tool": tool.get("tool"), "path": tool.get("path"), "returncode": tool.get("returncode")} for tool in tools],
        "duration_ms": duration_ms,
        "actions": agent_action_events(
            tools,
            mode=mode,
            target_node=target_node,
            transcript_turns=len(transcript),
            image_count=image_count,
            source=source,
            duration_ms=duration_ms,
            token_usage=token_usage,
            auto_checkpoint=auto_checkpoint,
            changed=files,
        ),
        "diagnostics": {
            "source": source,
            "mode": mode,
            "target_node": target_node,
            "duration_ms": duration_ms,
            "tool_count": len(tools),
            "tools": [str(tool.get("tool")) for tool in tools],
            "transcript_turns": len(transcript),
            "context_bytes": context_bytes,
            "context_estimated_tokens": max(1, context_bytes // 4),
            "token_usage": token_usage,
            "model_tokens_avoided": source.startswith("local_"),
            "attachments": {
                "received": image_count,
                "raw_forwarded_to_bridge": len(bridge_images),
                "summarized": max(0, image_count - len(bridge_images)),
            },
            "auto_checkpoint": {
                "ref": auto_checkpoint.get("ref"),
                "sha": str(auto_checkpoint.get("sha") or "")[:7],
                "label": auto_checkpoint.get("label"),
            } if auto_checkpoint else None,
        },
        "changed_files": files,
        "context_preview": [tool_preview(tool) for tool in tools],
    }


def write_ndjson(handler: WasmAgentHandler, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8") + b"\n"
    handler.wfile.write(body)
    handler.wfile.flush()


def stream_embedded_agent_message(handler: WasmAgentHandler, body: dict[str, Any]) -> None:
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()

    def emit_action(action: dict[str, Any]) -> None:
        write_ndjson(handler, {"type": "action", "action": action})

    try:
        result = embedded_agent_message(handler.server, body, action_callback=emit_action)
        write_ndjson(handler, {"type": "final", "agent": result})
    except BrowserError as exc:
        write_ndjson(handler, {"type": "error", "error": {"code": exc.code, "message": exc.message}})
    except (BrokenPipeError, ConnectionResetError):
        return
    except Exception as exc:
        write_ndjson(handler, {"type": "error", "error": {"code": "agent_error", "message": str(exc)}})


def dev_hmr_files(server: WasmAgentServer) -> list[Path]:
    roots = [server.public_root, server.plugin_root / "server"]
    suffixes = {".html", ".css", ".js", ".webmanifest", ".py"}
    files: list[Path] = []
    for root in roots:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                files.append(path)
    return files


def dev_hmr_snapshot(server: WasmAgentServer) -> dict[str, float]:
    snapshot: dict[str, float] = {}
    for path in dev_hmr_files(server):
        try:
            relative = str(path.relative_to(server.plugin_root))
            snapshot[relative] = path.stat().st_mtime
        except OSError:
            continue
    return snapshot


def dev_hmr_revision(snapshot: dict[str, float]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def serve_dev_hmr_events(handler: WasmAgentHandler) -> None:
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()

    query = parse_qs(urlparse(handler.path).query)
    client_revision = str((query.get("client") or [""])[0])
    previous = dev_hmr_snapshot(handler.server)
    revision = dev_hmr_revision(previous)
    handler.wfile.write(b"event: ready\n")
    ready_payload = json.dumps({
        "ok": True,
        "module": "dev-hmr",
        "revision": revision,
        "client": client_revision,
    }, separators=(",", ":")).encode("utf-8")
    handler.wfile.write(b"data: " + ready_payload + b"\n\n")
    handler.wfile.flush()
    if not client_revision:
        legacy_payload = json.dumps({
            "changed": ["public/modules/hmr/dev-hmr.js"],
            "removed": [],
            "timestamp": int(time.time()),
            "revision": revision,
            "reason": "hmr_client_stale",
        }, separators=(",", ":")).encode("utf-8")
        try:
            handler.wfile.write(b"event: change\n")
            handler.wfile.write(b"data: " + legacy_payload + b"\n\n")
            handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    while True:
        time.sleep(0.6)
        current = dev_hmr_snapshot(handler.server)
        changed = sorted(path for path, mtime in current.items() if previous.get(path) != mtime)
        removed = sorted(path for path in previous if path not in current)
        if not changed and not removed:
            continue
        previous = current
        revision = dev_hmr_revision(current)
        payload = json.dumps({
            "changed": changed,
            "removed": removed,
            "timestamp": int(time.time()),
            "revision": revision,
        }, separators=(",", ":")).encode("utf-8")
        try:
            handler.wfile.write(b"event: change\n")
            handler.wfile.write(b"data: " + payload + b"\n\n")
            handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            break


def capture_browser(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    url = normalized_browser_url(body.get("url"))
    width, height = browser_dimensions(body)
    cdp_url = os.getenv("HERMES_WASM_AGENT_BROWSER_CDP_URL", "http://127.0.0.1:9233").strip()
    if cdp_url:
        try:
            return capture_browser_cdp(server, url, width, height, cdp_url.rstrip("/"))
        except BrowserError:
            raise
        except Exception:
            # Fall back to one-shot Chromium only when CDP is not reachable.
            if cdp_available(cdp_url.rstrip("/")):
                raise

    return capture_browser_cli(server, url, width, height)


def cdp_available(cdp_url: str) -> bool:
    try:
        with urlopen(f"{cdp_url}/json/version", timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def capture_browser_cdp(
    server: WasmAgentServer,
    url: str,
    width: int,
    height: int,
    cdp_url: str,
) -> dict[str, Any]:
    target: dict[str, Any] | None = None
    try:
        create_req = Request(f"{cdp_url}/json/new?{quote(url, safe='')}", method="PUT")
        with urlopen(create_req, timeout=3) as response:
            target = json.loads(response.read().decode("utf-8"))
        ws_url = str(target.get("webSocketDebuggerUrl") or "")
        if not ws_url:
            raise BrowserError("cdp_target_failed", "CDP target did not expose a websocket URL.")
        image = capture_cdp_screenshot(
            ws_url,
            width,
            height,
            server.browser_timeout_sec,
            navigate_url=url,
        )
    except BrowserError:
        raise
    except Exception as exc:
        raise BrowserError("cdp_capture_failed", f"CDP browser capture failed: {exc}") from exc

    image_bytes = base64.b64decode(image.encode("ascii"))
    session_id = uuid.uuid4().hex
    with server.browser_sessions_lock:
        server.browser_sessions[session_id] = {
            "session_id": session_id,
            "target_id": target.get("id") if target else "",
            "ws_url": ws_url,
            "cdp_url": cdp_url,
            "url": url,
            "width": width,
            "height": height,
            "created_at": time.time(),
            "last_access": time.time(),
        }
        prune_browser_sessions(server)
    return {
        "schema": "hermes.wasm_agent.browser_capture.v1",
        "session_id": session_id,
        "interactive": True,
        "url": url,
        "width": width,
        "height": height,
        "bytes": len(image_bytes),
        "captured_at": int(time.time()),
        "image": "data:image/png;base64," + image,
        "mode": "host_chromium_cdp_pixels",
        "iframe": False,
    }


def capture_browser_cli(server: WasmAgentServer, url: str, width: int, height: int) -> dict[str, Any]:
    browser_root = server.state_dir / "browser"
    capture_root = browser_root / "captures"
    profile_root = browser_root / "profile"
    capture_root.mkdir(parents=True, exist_ok=True)
    profile_root.mkdir(parents=True, exist_ok=True)
    capture_path = capture_root / f"{int(time.time())}-{uuid.uuid4().hex[:8]}.png"

    cmd = [
        chromium_command(),
        "--headless",
        "--no-sandbox",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--user-data-dir={profile_root}",
        f"--window-size={width},{height}",
        f"--screenshot={capture_path}",
        url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False,
            timeout=server.browser_timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise BrowserError(
            "browser_timeout",
            f"Chromium capture timed out after {server.browser_timeout_sec:.0f}s.",
            status=HTTPStatus.GATEWAY_TIMEOUT,
        ) from exc

    if proc.returncode != 0 or not capture_path.exists():
        stderr = (proc.stderr or proc.stdout or "Chromium capture failed.").strip()
        raise BrowserError(
            "browser_capture_failed",
            stderr[-900:],
            status=HTTPStatus.BAD_GATEWAY,
        )

    image_bytes = capture_path.read_bytes()
    image = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    return {
        "schema": "hermes.wasm_agent.browser_capture.v1",
        "session_id": "",
        "interactive": False,
        "url": url,
        "width": width,
        "height": height,
        "bytes": len(image_bytes),
        "captured_at": int(time.time()),
        "image": image,
        "mode": "chromium_screenshot_pixels",
        "iframe": False,
    }


def browser_session_ttl_sec() -> float:
    raw = os.getenv("HERMES_WASM_AGENT_BROWSER_SESSION_TTL_SEC")
    if raw in {None, ""}:
        return DEFAULT_BROWSER_SESSION_TTL_SEC
    return clamp_number(raw, 60, 24 * 60 * 60)


def prune_browser_sessions(server: WasmAgentServer, *, keep: int = 8) -> None:
    now = time.time()
    ttl_sec = browser_session_ttl_sec()
    for session_id, session in list(server.browser_sessions.items()):
        last_access = float(session.get("last_access") or session.get("created_at") or 0)
        if last_access and now - last_access > ttl_sec:
            server.browser_sessions.pop(session_id, None)
            close_cdp_target(str(session.get("cdp_url") or ""), str(session.get("target_id") or ""))

    sessions = sorted(
        server.browser_sessions.values(),
        key=lambda item: float(item.get("last_access") or item.get("created_at") or 0),
        reverse=True,
    )
    for session in sessions[keep:]:
        server.browser_sessions.pop(str(session.get("session_id")), None)
        close_cdp_target(str(session.get("cdp_url") or ""), str(session.get("target_id") or ""))


def close_cdp_target(cdp_url: str, target_id: str) -> None:
    if not cdp_url or not target_id:
        return
    try:
        with urlopen(f"{cdp_url}/json/close/{target_id}", timeout=2):
            pass
    except Exception:
        pass


def browser_input(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    session_id = str(body.get("session_id") or "").strip()
    if not session_id:
        raise BrowserError("missing_session", "A browser session_id is required.")
    with server.browser_sessions_lock:
        session = dict(server.browser_sessions.get(session_id) or {})
        if not session:
            raise BrowserError("browser_session_not_found", "Browser session was not found.", status=HTTPStatus.NOT_FOUND)
        session["last_access"] = time.time()
        server.browser_sessions[session_id] = session

    action = str(body.get("action") or "").strip().lower()
    width = int(session.get("width") or 1280)
    height = int(session.get("height") or 800)
    ws_url = str(session.get("ws_url") or "")
    url = str(session.get("url") or "")
    action_result = perform_browser_action(ws_url, action, body, width, height, server.browser_timeout_sec)
    image = action_result["image"]
    current_url = str(action_result.get("url") or "")
    if action == "navigate":
        url = current_url or normalized_browser_url(body.get("url"))
        session["url"] = url
        with server.browser_sessions_lock:
            server.browser_sessions[session_id] = session
    elif current_url:
        url = current_url
        session["url"] = url
        with server.browser_sessions_lock:
            server.browser_sessions[session_id] = session

    image_bytes = base64.b64decode(image.encode("ascii"))
    return {
        "schema": "hermes.wasm_agent.browser_capture.v1",
        "session_id": session_id,
        "interactive": True,
        "url": url,
        "width": width,
        "height": height,
        "bytes": len(image_bytes),
        "captured_at": int(time.time()),
        "image": "data:image/png;base64," + image,
        "mode": "host_chromium_cdp_interactive_pixels",
        "action": action,
        "iframe": False,
    }


def close_browser_session(server: WasmAgentServer, body: dict[str, Any]) -> dict[str, Any]:
    session_id = str(body.get("session_id") or "").strip()
    if not session_id:
        raise BrowserError("missing_session", "A browser session_id is required.")
    with server.browser_sessions_lock:
        session = server.browser_sessions.pop(session_id, None)
    if not session:
        return {"session_id": session_id, "closed": False}
    close_cdp_target(str(session.get("cdp_url") or ""), str(session.get("target_id") or ""))
    return {"session_id": session_id, "closed": True}


def serve_browser_stream(handler: WasmAgentHandler) -> None:
    key = handler.headers.get("Sec-WebSocket-Key", "").strip()
    upgrade = handler.headers.get("Upgrade", "").lower()
    if upgrade != "websocket" or not key:
        handler.send_error(HTTPStatus.UPGRADE_REQUIRED, "WebSocket upgrade required")
        return

    accept = base64.b64encode(hashlib.sha1((key + WEBSOCKET_GUID).encode("ascii")).digest()).decode("ascii")
    handler.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()
    handler.close_connection = True

    client_ws = BrowserClientWebSocket(handler)
    try:
        handle_browser_stream(handler.server, client_ws)
    finally:
        client_ws.close()


class BrowserClientWebSocket:
    def __init__(self, handler: WasmAgentHandler) -> None:
        self.sock = handler.connection
        self.reader = handler.rfile
        self.send_lock = threading.Lock()
        self.closed = False

    def send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_frame(0x1, data)

    def send_frame(self, opcode: int, payload: bytes = b"") -> None:
        if self.closed:
            return
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", length))
        with self.send_lock:
            self.sock.sendall(bytes(header) + payload)

    def recv_json(self, *, wait: float | None = None) -> dict[str, Any]:
        previous_timeout = self.sock.gettimeout()
        self.sock.settimeout(wait)
        try:
            while True:
                opcode, payload = self.recv_frame()
                if opcode == 0x8:
                    raise BrowserError("browser_ws_closed", "Browser websocket closed.")
                if opcode == 0x9:
                    self.send_frame(0xA, payload)
                    continue
                if opcode == 0xA:
                    continue
                if opcode in {0x1, 0x0}:
                    return json.loads(payload.decode("utf-8"))
        except socket.timeout as exc:
            raise BrowserError("browser_ws_timeout", "Timed out waiting for browser stream input.") from exc
        finally:
            self.sock.settimeout(previous_timeout)

    def recv_frame(self) -> tuple[int, bytes]:
        first = self._recv_exact(2)
        opcode = first[0] & 0x0F
        masked = bool(first[1] & 0x80)
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def close(self) -> None:
        if self.closed:
            return
        try:
            self.send_frame(0x8)
        except Exception:
            pass
        self.closed = True

    def _recv_exact(self, length: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            chunk = self.reader.read(length - len(chunks))
            if not chunk:
                raise BrowserError("browser_ws_closed", "Browser websocket closed.")
            chunks.extend(chunk)
        return bytes(chunks)


class CdpWebSocket:
    def __init__(self, ws_url: str, timeout: float) -> None:
        parsed = urlparse(ws_url)
        if parsed.scheme != "ws" or not parsed.hostname:
            raise BrowserError("cdp_ws_unsupported", "Only ws:// CDP websocket URLs are supported.")
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        self.sock = socket.create_connection((parsed.hostname, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = self._recv_until(b"\r\n\r\n")
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise BrowserError("cdp_ws_handshake_failed", "CDP websocket handshake failed.")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if f"sec-websocket-accept: {accept}".encode("ascii").lower() not in response.lower():
            raise BrowserError("cdp_ws_handshake_failed", "CDP websocket accept key did not match.")

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

    def send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = secrets.token_bytes(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_json(self) -> dict[str, Any]:
        while True:
            message = self._recv_frame()
            if message is None:
                continue
            return json.loads(message.decode("utf-8"))

    def _recv_frame(self) -> bytes | None:
        first = self._recv_exact(2)
        opcode = first[0] & 0x0F
        masked = bool(first[1] & 0x80)
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        data = self._recv_exact(length) if length else b""
        if masked:
            data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        if opcode == 0x8:
            raise BrowserError("cdp_ws_closed", "CDP websocket closed.")
        if opcode == 0x9:
            self._send_pong(data)
            return None
        if opcode not in {0x1, 0x0}:
            return None
        return data

    def _send_pong(self, payload: bytes) -> None:
        header = bytearray([0x8A])
        length = len(payload)
        header.append(0x80 | length)
        mask = secrets.token_bytes(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv_exact(self, length: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            chunk = self.sock.recv(length - len(chunks))
            if not chunk:
                raise BrowserError("cdp_ws_closed", "CDP websocket closed.")
            chunks.extend(chunk)
        return bytes(chunks)

    def _recv_until(self, marker: bytes) -> bytes:
        chunks = bytearray()
        while marker not in chunks:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise BrowserError("cdp_ws_closed", "CDP websocket closed.")
            chunks.extend(chunk)
        return bytes(chunks)


class CdpClient:
    def __init__(self, ws_url: str, timeout: float) -> None:
        self.ws = CdpWebSocket(ws_url, timeout)
        self.timeout = timeout
        self.next_id = 0

    def close(self) -> None:
        self.ws.close()

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        wait: float | None = None,
    ) -> dict[str, Any]:
        self.next_id += 1
        message_id = self.next_id
        timeout = wait or self.timeout
        self.ws.sock.settimeout(timeout)
        self.ws.send_json({"id": message_id, "method": method, "params": params or {}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            payload = self.ws.recv_json()
            if payload.get("id") != message_id:
                continue
            if "error" in payload:
                raise BrowserError("cdp_command_failed", json.dumps(payload["error"])[:700])
            return payload.get("result", {})
        raise BrowserError("cdp_timeout", f"Timed out waiting for {method}.", status=HTTPStatus.GATEWAY_TIMEOUT)

    def wait_for_load(self, timeout: float) -> None:
        deadline = time.time() + timeout
        self.ws.sock.settimeout(0.75)
        while time.time() < deadline:
            try:
                payload = self.ws.recv_json()
            except socket.timeout:
                continue
            if payload.get("method") == "Page.loadEventFired":
                break
        self.ws.sock.settimeout(self.timeout)


class CdpStreamClient:
    def __init__(
        self,
        ws_url: str,
        timeout: float,
        browser_ws: BrowserClientWebSocket,
        *,
        width: int,
        height: int,
        url: str,
        stream_id: str,
    ) -> None:
        self.ws = CdpWebSocket(ws_url, timeout)
        self.ws.sock.settimeout(0.5)
        self.timeout = timeout
        self.browser_ws = browser_ws
        self.width = width
        self.height = height
        self.url = url
        self.stream_id = stream_id
        self.next_id = 0
        self.frame_count = 0
        self.last_browser_frame_at = 0.0
        self.stream_fps = browser_stream_fps()
        self.pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self.pending_lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.load_events: queue.Queue[bool] = queue.Queue(maxsize=4)
        self.reader_thread = threading.Thread(target=self._read_loop, name=f"browser-stream-{stream_id}", daemon=True)

    def start(self) -> None:
        self.reader_thread.start()

    def close(self) -> None:
        self.stop_event.set()
        try:
            self.ws.close()
        except Exception:
            pass

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        wait: float | None = None,
    ) -> dict[str, Any]:
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self.send_lock:
            self.next_id += 1
            message_id = self.next_id
            with self.pending_lock:
                self.pending[message_id] = response_queue
            self.ws.send_json({"id": message_id, "method": method, "params": params or {}})
        timeout = wait or self.timeout
        try:
            payload = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            with self.pending_lock:
                self.pending.pop(message_id, None)
            raise BrowserError("cdp_timeout", f"Timed out waiting for {method}.", status=HTTPStatus.GATEWAY_TIMEOUT) from exc
        if "error" in payload:
            raise BrowserError("cdp_command_failed", json.dumps(payload["error"])[:700])
        return payload.get("result", {})

    def send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> int:
        with self.send_lock:
            self.next_id += 1
            message_id = self.next_id
            self.ws.send_json({"id": message_id, "method": method, "params": params or {}})
        return message_id

    def wait_for_load(self, timeout: float) -> None:
        try:
            self.load_events.get(timeout=timeout)
        except queue.Empty:
            pass

    def send_browser(self, payload: dict[str, Any]) -> None:
        if self.stop_event.is_set():
            return
        try:
            self.browser_ws.send_json(payload)
        except Exception:
            self.stop_event.set()

    def _read_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                payload = self.ws.recv_json()
            except socket.timeout:
                continue
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.send_browser({"type": "error", "code": "cdp_stream_closed", "message": str(exc)})
                self.stop_event.set()
                break

            message_id = payload.get("id")
            if message_id is not None:
                with self.pending_lock:
                    response_queue = self.pending.pop(int(message_id), None)
                if response_queue is not None:
                    response_queue.put(payload)
                continue

            method = str(payload.get("method") or "")
            params = payload.get("params") or {}
            if method == "Page.screencastFrame":
                self._handle_screencast_frame(params)
            elif method == "Page.loadEventFired":
                try:
                    self.load_events.put_nowait(True)
                except queue.Full:
                    pass
            elif method == "Page.frameNavigated":
                frame = params.get("frame") or {}
                if not frame.get("parentId"):
                    url = str(frame.get("url") or "")
                    if url:
                        self.url = url
                        self.send_browser({"type": "state", "stream_id": self.stream_id, "url": url})

    def _handle_screencast_frame(self, params: dict[str, Any]) -> None:
        data = str(params.get("data") or "")
        if not data:
            return
        metadata = params.get("metadata") or {}
        session_id = params.get("sessionId")
        if session_id is not None:
            self.send_command("Page.screencastFrameAck", {"sessionId": session_id})
        now = time.monotonic()
        min_interval = 1.0 / max(1.0, self.stream_fps)
        if now - self.last_browser_frame_at < min_interval:
            return
        self.last_browser_frame_at = now
        self.frame_count += 1
        self.send_browser({
            "type": "frame",
            "stream_id": self.stream_id,
            "url": self.url,
            "width": self.width,
            "height": self.height,
            "image": "data:image/jpeg;base64," + data,
            "frame": self.frame_count,
            "timestamp": metadata.get("timestamp"),
            "mode": "host_chromium_cdp_screencast",
        })

    def send_snapshot_frame(self) -> None:
        result = self.call("Page.captureScreenshot", {
            "format": "jpeg",
            "quality": browser_stream_quality(),
            "fromSurface": True,
            "captureBeyondViewport": False,
        }, wait=min(self.timeout, 6))
        data = str(result.get("data") or "")
        if not data:
            return
        self.frame_count += 1
        self.last_browser_frame_at = time.monotonic()
        self.send_browser({
            "type": "frame",
            "stream_id": self.stream_id,
            "url": self.url,
            "width": self.width,
            "height": self.height,
            "image": "data:image/jpeg;base64," + data,
            "frame": self.frame_count,
            "timestamp": time.time(),
            "mode": "host_chromium_cdp_snapshot",
        })


def setup_cdp_page(client: CdpClient, width: int, height: int) -> None:
    client.call("Page.enable")
    client.call("Runtime.enable")
    set_cdp_viewport(client, width, height)


def set_cdp_viewport(client: CdpClient, width: int, height: int) -> None:
    client.call("Emulation.setDeviceMetricsOverride", {
        "width": width,
        "height": height,
        "deviceScaleFactor": 1,
        "mobile": False,
    })


def start_cdp_screencast(client: CdpStreamClient, width: int, height: int) -> None:
    client.call("Page.startScreencast", {
        "format": "jpeg",
        "quality": browser_stream_quality(),
        "maxWidth": width,
        "maxHeight": height,
        "everyNthFrame": browser_stream_every_nth_frame(),
    })


def browser_stream_fps() -> float:
    raw = os.getenv("HERMES_WASM_AGENT_BROWSER_STREAM_FPS")
    if raw in {None, ""}:
        return DEFAULT_BROWSER_STREAM_FPS
    return clamp_number(raw, 1, 12)


def browser_stream_quality() -> int:
    raw = os.getenv("HERMES_WASM_AGENT_BROWSER_STREAM_QUALITY")
    if raw in {None, ""}:
        return DEFAULT_BROWSER_STREAM_QUALITY
    return int(clamp_number(raw, 35, 85))


def browser_stream_every_nth_frame() -> int:
    raw = os.getenv("HERMES_WASM_AGENT_BROWSER_STREAM_EVERY_NTH_FRAME")
    if raw in {None, ""}:
        return DEFAULT_BROWSER_STREAM_EVERY_NTH_FRAME
    return int(clamp_number(raw, 1, 12))


def cdp_screenshot(client: CdpClient) -> str:
    result = client.call("Page.captureScreenshot", {
        "format": "png",
        "fromSurface": True,
        "captureBeyondViewport": False,
    })
    image = str(result.get("data") or "")
    if not image:
        raise BrowserError("cdp_screenshot_empty", "CDP returned an empty screenshot.")
    return image


def capture_cdp_screenshot(
    ws_url: str,
    width: int,
    height: int,
    timeout: float,
    *,
    navigate_url: str | None = None,
) -> dict[str, str]:
    client = CdpClient(ws_url, timeout)
    try:
        setup_cdp_page(client, width, height)
        if navigate_url:
            client.call("Page.navigate", {"url": navigate_url}, wait=min(timeout, 6))
            client.wait_for_load(min(timeout, 8))
        return cdp_screenshot(client)
    finally:
        client.close()


def perform_browser_action(
    ws_url: str,
    action: str,
    body: dict[str, Any],
    width: int,
    height: int,
    timeout: float,
) -> str:
    if action not in {"click", "type", "key", "scroll", "navigate", "screenshot", "back", "forward", "reload"}:
        raise BrowserError("unsupported_browser_action", "Unsupported browser action.")
    client = CdpClient(ws_url, timeout)
    try:
        setup_cdp_page(client, width, height)
        if action == "click":
            x = clamp_number(body.get("x"), 0, width)
            y = clamp_number(body.get("y"), 0, height)
            client.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none"})
            client.call("Input.dispatchMouseEvent", {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
            })
            client.call("Input.dispatchMouseEvent", {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
            })
            time.sleep(0.15)
        elif action == "type":
            text = str(body.get("text") or "")
            if text:
                client.call("Input.insertText", {"text": text})
        elif action == "key":
            key = str(body.get("key") or "")
            dispatch_key(client, key)
            if key == "Enter":
                client.wait_for_load(min(timeout, 4))
            else:
                time.sleep(0.2)
        elif action == "scroll":
            x = clamp_number(body.get("x"), 0, width)
            y = clamp_number(body.get("y"), 0, height)
            delta_x = float(body.get("delta_x") or 0)
            delta_y = float(body.get("delta_y") or 0)
            client.call("Input.dispatchMouseEvent", {
                "type": "mouseWheel",
                "x": x,
                "y": y,
                "deltaX": delta_x,
                "deltaY": delta_y,
            })
            time.sleep(0.15)
        elif action == "navigate":
            url = normalized_browser_url(body.get("url"))
            client.call("Page.navigate", {"url": url}, wait=min(timeout, 6))
            client.wait_for_load(min(timeout, 8))
        elif action in {"back", "forward"}:
            navigate_history(client, direction=action, timeout=timeout)
        elif action == "reload":
            client.call("Page.reload", {"ignoreCache": False}, wait=min(timeout, 6))
            client.wait_for_load(min(timeout, 8))
        return {"image": cdp_screenshot(client), "url": current_cdp_url(client)}
    finally:
        client.close()


def clamp_number(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))


def dispatch_key(client: CdpClient, key: str) -> None:
    key_map = {
        "Enter": ("Enter", "Enter", 13),
        "Backspace": ("Backspace", "Backspace", 8),
        "Tab": ("Tab", "Tab", 9),
        "Escape": ("Escape", "Escape", 27),
        "ArrowLeft": ("ArrowLeft", "ArrowLeft", 37),
        "ArrowUp": ("ArrowUp", "ArrowUp", 38),
        "ArrowRight": ("ArrowRight", "ArrowRight", 39),
        "ArrowDown": ("ArrowDown", "ArrowDown", 40),
    }
    normalized = key_map.get(key)
    if not normalized and len(key) == 1:
        client.call("Input.insertText", {"text": key})
        return
    if not normalized:
        return
    key_name, code, vk = normalized
    payload = {
        "key": key_name,
        "code": code,
        "windowsVirtualKeyCode": vk,
        "nativeVirtualKeyCode": vk,
    }
    client.call("Input.dispatchKeyEvent", {"type": "keyDown", **payload})
    client.call("Input.dispatchKeyEvent", {"type": "keyUp", **payload})


def navigate_history(client: CdpClient, *, direction: str, timeout: float) -> None:
    history = client.call("Page.getNavigationHistory", wait=3)
    entries = history.get("entries") or []
    index = int(history.get("currentIndex") or 0)
    target_index = index - 1 if direction == "back" else index + 1
    if target_index < 0 or target_index >= len(entries):
        return
    entry_id = entries[target_index].get("id")
    if entry_id is None:
        return
    client.call("Page.navigateToHistoryEntry", {"entryId": entry_id}, wait=min(timeout, 6))
    client.wait_for_load(min(timeout, 8))


def current_cdp_url(client: CdpClient) -> str:
    try:
        result = client.call("Runtime.evaluate", {
            "expression": "location.href",
            "returnByValue": True,
        }, wait=2)
        return str(result.get("result", {}).get("value") or "")
    except Exception:
        return ""


def create_cdp_target(cdp_url: str, initial_url: str = "about:blank") -> dict[str, Any]:
    create_req = Request(f"{cdp_url}/json/new?{quote(initial_url, safe='')}", method="PUT")
    with urlopen(create_req, timeout=3) as response:
        target = json.loads(response.read().decode("utf-8"))
    ws_url = str(target.get("webSocketDebuggerUrl") or "")
    if not ws_url:
        raise BrowserError("cdp_target_failed", "CDP target did not expose a websocket URL.")
    return target


def handle_browser_stream(server: WasmAgentServer, browser_ws: BrowserClientWebSocket) -> None:
    stream: CdpStreamClient | None = None
    target: dict[str, Any] | None = None
    cdp_url = os.getenv("HERMES_WASM_AGENT_BROWSER_CDP_URL", "http://127.0.0.1:9233").strip().rstrip("/")
    try:
        hello = browser_ws.recv_json(wait=8)
        if str(hello.get("type") or "").lower() != "open":
            raise BrowserError("browser_stream_expected_open", "First browser stream message must be type=open.")
        url = normalized_browser_url(hello.get("url"))
        width, height = browser_dimensions(hello)
        if not cdp_url:
            raise BrowserError("cdp_stream_unavailable", "Browser streaming requires HERMES_WASM_AGENT_BROWSER_CDP_URL.")
        if not cdp_available(cdp_url):
            raise BrowserError("cdp_stream_unavailable", f"CDP is not reachable at {cdp_url}.")

        target = create_cdp_target(cdp_url)
        stream_id = uuid.uuid4().hex
        stream = CdpStreamClient(
            str(target["webSocketDebuggerUrl"]),
            server.browser_timeout_sec,
            browser_ws,
            width=width,
            height=height,
            url=url,
            stream_id=stream_id,
        )
        stream.start()
        setup_cdp_page(stream, width, height)
        start_cdp_screencast(stream, width, height)
        browser_ws.send_json({
            "type": "ready",
            "stream_id": stream_id,
            "url": url,
            "width": width,
            "height": height,
            "mode": "host_chromium_cdp_screencast",
            "iframe": False,
        })
        stream.call("Page.navigate", {"url": url}, wait=min(server.browser_timeout_sec, 6))
        stream.wait_for_load(min(server.browser_timeout_sec, 6))
        stream.send_snapshot_frame()

        while not stream.stop_event.is_set():
            try:
                message = browser_ws.recv_json()
            except BrowserError as exc:
                if exc.code == "browser_ws_closed":
                    break
                raise
            perform_browser_stream_action(stream, message, server.browser_timeout_sec)
    except BrowserError as exc:
        try:
            browser_ws.send_json({"type": "error", "code": exc.code, "message": exc.message})
        except Exception:
            pass
    except Exception as exc:
        try:
            browser_ws.send_json({"type": "error", "code": "browser_stream_error", "message": str(exc)})
        except Exception:
            pass
    finally:
        if stream is not None:
            try:
                stream.call("Page.stopScreencast", wait=1)
            except Exception:
                pass
            stream.close()
        if target is not None:
            close_cdp_target(cdp_url, str(target.get("id") or ""))


def perform_browser_stream_action(client: CdpStreamClient, body: dict[str, Any], timeout: float) -> None:
    message_type = str(body.get("type") or "").strip().lower()
    action = str(body.get("action") or message_type).strip().lower()
    if action not in {"click", "type", "key", "scroll", "navigate", "resize", "back", "forward", "reload", "ping"}:
        raise BrowserError("unsupported_browser_stream_action", "Unsupported browser stream action.")
    if action == "ping":
        client.send_browser({"type": "pong", "stream_id": client.stream_id, "url": client.url})
        return
    if action == "click":
        x = clamp_number(body.get("x"), 0, client.width)
        y = clamp_number(body.get("y"), 0, client.height)
        client.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none"}, wait=2)
        client.call("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        }, wait=2)
        client.call("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        }, wait=2)
    elif action == "type":
        text = str(body.get("text") or "")
        if text:
            client.call("Input.insertText", {"text": text}, wait=2)
    elif action == "key":
        dispatch_key(client, str(body.get("key") or ""))
    elif action == "scroll":
        x = clamp_number(body.get("x"), 0, client.width)
        y = clamp_number(body.get("y"), 0, client.height)
        client.call("Input.dispatchMouseEvent", {
            "type": "mouseWheel",
            "x": x,
            "y": y,
            "deltaX": float(body.get("delta_x") or 0),
            "deltaY": float(body.get("delta_y") or 0),
        }, wait=2)
    elif action == "navigate":
        url = normalized_browser_url(body.get("url"))
        client.url = url
        client.send_browser({"type": "state", "stream_id": client.stream_id, "url": url, "status": "navigating"})
        try:
            client.call("Page.stopScreencast", wait=1)
        except Exception:
            pass
        client.call("Page.navigate", {"url": url}, wait=min(timeout, 6))
        client.wait_for_load(min(timeout, 6))
        start_cdp_screencast(client, client.width, client.height)
        client.send_snapshot_frame()
    elif action in {"back", "forward"}:
        navigate_history(client, direction=action, timeout=timeout)
    elif action == "reload":
        client.call("Page.reload", {"ignoreCache": False}, wait=min(timeout, 6))
    elif action == "resize":
        width, height = browser_dimensions(body)
        client.width = width
        client.height = height
        try:
            client.call("Page.stopScreencast", wait=1)
        except Exception:
            pass
        set_cdp_viewport(client, width, height)
        start_cdp_screencast(client, width, height)
        client.send_snapshot_frame()

    should_sync_url = action in {"navigate", "back", "forward", "reload"} or (
        action == "key" and str(body.get("key") or "") == "Enter"
    )
    if should_sync_url:
        url = current_cdp_url(client)
        if url:
            client.url = url
            client.send_browser({"type": "state", "stream_id": client.stream_id, "url": url})
    client.send_browser({"type": "ack", "stream_id": client.stream_id, "action": action, "url": client.url})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the wasm-agent shadow PWA")
    parser.add_argument("--host", default=os.getenv("HERMES_WASM_AGENT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("HERMES_WASM_AGENT_PORT", "8877")))
    parser.add_argument(
        "--bridge-url",
        default=os.getenv("HERMES_WASM_AGENT_BRIDGE_URL", "http://127.0.0.1:8790"),
        help="Hermes bridge URL exposed to the PWA",
    )
    parser.add_argument(
        "--browser-timeout-sec",
        type=float,
        default=float(os.getenv("HERMES_WASM_AGENT_BROWSER_TIMEOUT_SEC", "20")),
        help="Maximum Chromium browser capture or stream command time",
    )
    return parser


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    public_root = plugin_root / "public"
    state_dir = Path(
        os.getenv("HERMES_WASM_AGENT_STATE_DIR", str(plugin_root / "state"))
    ).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    mimetypes.add_type("application/wasm", ".wasm")

    args = build_parser().parse_args()

    def handler(*handler_args: Any, **handler_kwargs: Any) -> WasmAgentHandler:
        return WasmAgentHandler(*handler_args, directory=str(public_root), **handler_kwargs)

    server = WasmAgentServer(
        (args.host, args.port),
        handler,
        plugin_root=plugin_root,
        public_root=public_root,
        state_dir=state_dir,
        bridge_url=args.bridge_url,
        browser_timeout_sec=args.browser_timeout_sec,
    )
    print(f"wasm-agent listening on http://{args.host}:{args.port}", flush=True)
    print(f"wasm-agent bridge target {args.bridge_url.rstrip('/')}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("wasm-agent stopping", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
