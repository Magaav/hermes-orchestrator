"""Bounded Batch Cleaner adapter for Codex datacenter reconstruction."""

from __future__ import annotations

import base64
import json
import shutil
import tempfile
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Callable

from master_frontier.codex_image_worker import CodexImageWorkerError, reconstruct_with_codex


MAX_SOURCE_BYTES = 20 * 1024 * 1024
SKILL_RELATIVE_PATH = Path(".agents/skills/property-photo-reconstructor/SKILL.md")
MINIMAL_WORKSPACE = Path(tempfile.gettempdir()) / "wasm-agent-property-photo-workspace"


@dataclass(frozen=True)
class PropertyPhotoEditError(RuntimeError):
    code: str
    message: str
    status: HTTPStatus = HTTPStatus.BAD_REQUEST

    def __str__(self) -> str:
        return self.message


def _decoded(value: Any, *, name: str, limit: int) -> bytes:
    try:
        data = base64.b64decode(str(value or ""), validate=True)
    except ValueError as exc:
        raise PropertyPhotoEditError(f"invalid_{name}", f"The {name} is not valid base64.") from exc
    if not data:
        raise PropertyPhotoEditError(f"empty_{name}", f"The {name} is empty.")
    if len(data) > limit:
        raise PropertyPhotoEditError(
            f"{name}_too_large",
            f"The {name} exceeds the 20 MB limit.",
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        )
    return data


def _source_image(body: dict[str, Any]) -> tuple[bytes, str]:
    media_type = str(body.get("media_type") or "image/jpeg").lower()
    extensions = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/avif": "avif"}
    if media_type not in extensions:
        raise PropertyPhotoEditError("unsupported_image", "Use a JPEG, PNG, WebP, or AVIF property photo.")
    return _decoded(body.get("image_base64"), name="property photo", limit=MAX_SOURCE_BYTES), extensions[media_type]


def prepare_job_workspace(job: Path, owner: Path) -> Path:
    skill_sources = [
        owner / SKILL_RELATIVE_PATH,
        Path(__file__).resolve().parents[3] / SKILL_RELATIVE_PATH,
    ]
    source = next((candidate for candidate in skill_sources if candidate.is_file()), None)
    if source:
        target = job / SKILL_RELATIVE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return job


def edit_property_photo(
    body: dict[str, Any],
    *,
    worker: Callable[..., tuple[bytes, str, dict[str, Any]]] = reconstruct_with_codex,
    workspace: Path | None = None,
    progress: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if body.get("cloud_consent") is not True:
        raise PropertyPhotoEditError("cloud_consent_required", "Confirm the secure datacenter edit first.")
    image, extension = _source_image(body)
    if progress:
        progress("accepted", {"media_type": str(body.get("media_type") or "image/jpeg"), "bytes": len(image)})
    watermark_authorized = body.get("watermark_authorized") is True
    owner = workspace or Path(__file__).resolve().parents[3]
    try:
        with tempfile.TemporaryDirectory(prefix="batch-cleaner-codex-") as temporary:
            job = Path(temporary)
            job_workspace = prepare_job_workspace(MINIMAL_WORKSPACE, owner)
            source_path = job / f"property-photo.{extension}"
            source_path.write_bytes(image)
            worker_options = {
                "watermark_authorized": watermark_authorized,
                "cwd": job_workspace,
            }
            if progress:
                worker_options["progress"] = progress
            cleaned, media_type, proof = worker(source_path, **worker_options)
    except CodexImageWorkerError as exc:
        raise PropertyPhotoEditError(exc.code, exc.message, HTTPStatus.BAD_GATEWAY) from exc
    encoded = base64.b64encode(cleaned).decode("ascii")
    return {
        "ok": True,
        "schema": "hermes.wasm_agent.property_photo_edit.v4",
        "image_base64": encoded,
        "media_type": media_type,
        "model": "codex-datacenter-imagegen",
        "scene_inspected": True,
        "watermark_authorized": watermark_authorized,
        "photo_persisted": False,
        "proof": proof,
    }


def _ndjson_frame(event: str, detail: dict[str, Any] | None = None, *, min_bytes: int = 0) -> bytes:
    payload = {"event": str(event), "detail": detail or {}}
    frame = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    if min_bytes > len(frame):
        payload["_flush"] = " " * max(0, min_bytes - len(frame) - 12)
        frame = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    return frame


def _stream_edit(handler: Any, body: dict[str, Any]) -> None:
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.send_header("X-Accel-Buffering", "no")
    handler.send_header("Content-Encoding", "identity")
    handler.end_headers()

    def emit(event: str, detail: dict[str, Any] | None = None) -> None:
        minimum = 0 if event in {"complete", "error"} else 4096
        handler.wfile.write(_ndjson_frame(event, detail, min_bytes=minimum))
        handler.wfile.flush()

    try:
        result = edit_property_photo(body, progress=emit)
        emit("complete", {"result": result})
    except PropertyPhotoEditError as exc:
        emit("error", {"code": exc.code, "message": exc.message})
    except (BrokenPipeError, ConnectionResetError):
        return


def dispatch_http(handler: Any, path: str, _configured_env: Callable[[str], str]) -> bool:
    """Own the route match and HTTP translation outside the server monolith."""
    if path not in {"/property-photo-cleaner/edit", "/property-photo-cleaner/edit/stream"}:
        return False
    if path.endswith("/stream"):
        body = handler._read_json(max_bytes=28 * 1024 * 1024)
        _stream_edit(handler, body)
        return True
    try:
        body = handler._read_json(max_bytes=28 * 1024 * 1024)
        handler._json(HTTPStatus.OK, edit_property_photo(body))
    except PropertyPhotoEditError as exc:
        handler._json(exc.status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
    return True
