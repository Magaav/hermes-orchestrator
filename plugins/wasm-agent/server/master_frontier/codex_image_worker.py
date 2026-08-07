"""Codex App Server adapter for bounded generated-image jobs."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_TIMEOUT_SEC = 600
ARTIFACT_SETTLE_SEC = 90
MAX_EVENT_BYTES = 2 * 1024 * 1024
MAX_IMAGE_EVENT_BYTES = 48 * 1024 * 1024
TOKEN_FIELDS = (
    "inputTokens",
    "cachedInputTokens",
    "outputTokens",
    "reasoningOutputTokens",
    "totalTokens",
)


@dataclass(frozen=True)
class CodexImageWorkerError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def reconstruction_prompt(*, watermark_authorized: bool) -> str:
    watermark_rule = (
        "Visible watermark removal is explicitly authorized."
        if watermark_authorized
        else "Watermark removal is not authorized; preserve all watermarks."
    )
    return (
        "Use $property-photo-reconstructor on the attached property photo. "
        f"{watermark_rule} Return exactly one final image artifact."
    )


def worker_environment(state_dir: Path) -> dict[str, str]:
    state_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["CODEX_SQLITE_HOME"] = str(state_dir.resolve())
    return environment


def image_generation_projection(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "savedPath": str(item.get("savedPath") or ""),
        "status": str(item.get("status") or ""),
        "revisedPrompt": str(item.get("revisedPrompt") or "")[:1000],
    }


def token_usage_projection(token_usage: Any) -> dict[str, int]:
    usage = token_usage if isinstance(token_usage, dict) else {}
    total = usage.get("total") if isinstance(usage.get("total"), dict) else {}
    return {field: max(0, int(total.get(field) or 0)) for field in TOKEN_FIELDS}


def _request(process: subprocess.Popen[str], request_id: int, method: str, params: dict[str, Any]) -> None:
    if process.stdin is None:
        raise CodexImageWorkerError("codex_worker_closed", "The Codex image worker is not writable.")
    process.stdin.write(json.dumps({"method": method, "id": request_id, "params": params}) + "\n")
    process.stdin.flush()


def _notify(process: subprocess.Popen[str], method: str, params: dict[str, Any]) -> None:
    if process.stdin is None:
        raise CodexImageWorkerError("codex_worker_closed", "The Codex image worker is not writable.")
    process.stdin.write(json.dumps({"method": method, "params": params}) + "\n")
    process.stdin.flush()


def _read_event(
    process: subprocess.Popen[str],
    selector: selectors.BaseSelector,
    deadline: float,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        if process.poll() is not None:
            detail = process.stderr.read(1200) if process.stderr else ""
            raise CodexImageWorkerError(
                "codex_worker_exited",
                f"The Codex image worker exited before completion. {detail}".strip(),
            )
        ready = selector.select(timeout=min(0.5, max(0.0, deadline - time.monotonic())))
        if not ready:
            continue
        line = process.stdout.readline(MAX_IMAGE_EVENT_BYTES + 1) if process.stdout else ""
        wire_bytes = len(line.encode("utf-8"))
        if wire_bytes > MAX_IMAGE_EVENT_BYTES:
            raise CodexImageWorkerError("codex_event_too_large", "The Codex image worker emitted an oversized image event.")
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if wire_bytes > MAX_EVENT_BYTES:
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            item = params.get("item") if isinstance(params.get("item"), dict) else {}
            if event.get("method") != "item/completed" or item.get("type") != "imageGeneration":
                raise CodexImageWorkerError("codex_event_too_large", "The Codex image worker emitted an oversized event.")
        return event
    raise CodexImageWorkerError("codex_worker_timeout", "Datacenter reconstruction timed out.")


def _wait_response(
    process: subprocess.Popen[str],
    selector: selectors.BaseSelector,
    request_id: int,
    deadline: float,
) -> dict[str, Any]:
    while True:
        event = _read_event(process, selector, deadline)
        if event.get("id") != request_id:
            continue
        if event.get("error"):
            message = str(event["error"].get("message") or "Codex rejected the request.")
            raise CodexImageWorkerError("codex_request_failed", message[:500])
        result = event.get("result")
        if not isinstance(result, dict):
            raise CodexImageWorkerError("codex_invalid_response", "Codex returned an invalid response.")
        return result


def reconstruct_with_codex(
    source_path: Path,
    *,
    watermark_authorized: bool,
    cwd: Path,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    process_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    progress: Callable[[str, dict[str, Any]], None] | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    report = progress or (lambda _stage, _detail: None)
    report("session-starting", {})
    command = [os.environ.get("WASM_AGENT_CODEX_BIN", "codex"), "app-server", "--stdio"]
    process = process_factory(
        command,
        cwd=str(cwd),
        env=worker_environment(source_path.parent / "codex-state"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    selector = selectors.DefaultSelector()
    if process.stdout is None:
        raise CodexImageWorkerError("codex_worker_closed", "The Codex image worker has no output stream.")
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + max(30, min(int(timeout_sec), 1200))
    generated: dict[str, Any] | None = None
    artifact_deadline: float | None = None
    usage = token_usage_projection({})
    completion = "turn-completed"
    try:
        _request(
            process,
            1,
            "initialize",
            {
                "clientInfo": {
                    "name": "wasm_agent_batch_cleaner",
                    "title": "WASM Agent Batch Cleaner",
                    "version": "1.0.0",
                }
            },
        )
        _wait_response(process, selector, 1, deadline)
        _notify(process, "initialized", {})
        _request(
            process,
            2,
            "thread/start",
            {
                "cwd": str(cwd),
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
                "ephemeral": True,
                "serviceName": "wasm_agent_batch_cleaner",
            },
        )
        thread_result = _wait_response(process, selector, 2, deadline)
        thread = thread_result.get("thread") or {}
        instruction_sources = [
            str(path)[:500]
            for path in (thread_result.get("instructionSources") or [])
            if isinstance(path, str)
        ][:12]
        thread_id = str(thread.get("id") or "")
        if not thread_id:
            raise CodexImageWorkerError("codex_thread_missing", "Codex did not start a reconstruction thread.")
        report("session-started", {"thread_id": thread_id})
        _request(
            process,
            3,
            "turn/start",
            {
                "threadId": thread_id,
                "input": [
                    {"type": "text", "text": reconstruction_prompt(watermark_authorized=watermark_authorized)},
                    {"type": "localImage", "path": str(source_path), "detail": "original"},
                ],
                "effort": "none",
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "dangerFullAccess"},
            },
        )
        _wait_response(process, selector, 3, deadline)
        report("reconstructing", {})
        while True:
            event_deadline = min(deadline, artifact_deadline) if artifact_deadline else deadline
            try:
                event = _read_event(process, selector, event_deadline)
            except CodexImageWorkerError as error:
                if error.code == "codex_worker_timeout" and generated and artifact_deadline:
                    completion = "artifact-settled"
                    report("finalizing", {"completion": completion})
                    break
                raise
            method = event.get("method")
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            if method == "thread/tokenUsage/updated":
                usage = token_usage_projection(params.get("tokenUsage"))
            if method == "item/completed":
                item = params.get("item") if isinstance(params.get("item"), dict) else {}
                if item.get("type") == "imageGeneration" and item.get("savedPath"):
                    generated = image_generation_projection(item)
                    artifact_deadline = time.monotonic() + ARTIFACT_SETTLE_SEC
                    report("artifact-generated", {"settle_seconds": ARTIFACT_SETTLE_SEC})
            if method == "turn/completed":
                turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
                if turn.get("status") != "completed":
                    error = turn.get("error") if isinstance(turn.get("error"), dict) else {}
                    raise CodexImageWorkerError(
                        "codex_turn_failed",
                        str(error.get("message") or "Datacenter reconstruction failed.")[:500],
                    )
                report("finalizing", {"completion": completion})
                break
        if not generated:
            raise CodexImageWorkerError(
                "codex_image_missing",
                "Codex completed without a generated image artifact.",
            )
        saved_path = Path(str(generated["savedPath"])).resolve()
        if not saved_path.is_file():
            raise CodexImageWorkerError("codex_image_missing", "The generated image artifact was not saved.")
        image = saved_path.read_bytes()
        if not image or len(image) > 32 * 1024 * 1024:
            raise CodexImageWorkerError("codex_image_invalid", "The generated image artifact is empty or oversized.")
        media_type = "image/png" if image.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
        return image, media_type, {
            "thread_id": thread_id,
            "item_id": str(generated.get("id") or ""),
            "status": str(generated.get("status") or ""),
            "revised_prompt": str(generated.get("revisedPrompt") or "")[:1000],
            "completion": completion,
            "usage": usage,
            "instruction_sources": instruction_sources,
        }
    finally:
        selector.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
