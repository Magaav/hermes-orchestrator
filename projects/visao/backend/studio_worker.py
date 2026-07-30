#!/usr/bin/env python3
"""NDJSON bridge for Visão Studio's internal Master:frontier envelope."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from studio_master_frontier import StudioEnvelopeError, reconstruct


IMAGE_CHUNK_CHARS = 8 * 1024


def emit_result(result: dict[str, Any], emit: Any, *, wire_version: int = 1) -> None:
    if wire_version < 2:
        emit("complete", {"result": result})
        return
    image_base64 = str(result.get("image_base64") or "")
    metadata = {key: value for key, value in result.items() if key != "image_base64"}
    chunks = [
        image_base64[offset : offset + IMAGE_CHUNK_CHARS]
        for offset in range(0, len(image_base64), IMAGE_CHUNK_CHARS)
    ]
    emit("result-start", {"result": metadata, "chunks": len(chunks)})
    for index, chunk in enumerate(chunks):
        emit("result-chunk", {"index": index, "data": chunk})
    emit("complete", {"chunks": len(chunks)})


def main() -> int:
    def emit(event: str, detail: dict[str, Any] | None = None) -> None:
        minimum = 0 if event in {"complete", "error"} else 4096
        payload = {"event": str(event), "detail": detail or {}}
        frame = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        if minimum > len(frame):
            payload["_flush"] = " " * max(0, minimum - len(frame) - 12)
            frame = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        sys.stdout.buffer.write(frame)
        sys.stdout.buffer.flush()

    try:
        body = json.load(sys.stdin)
        if not isinstance(body, dict):
            raise StudioEnvelopeError("invalid_request", "A solicitação do Studio é inválida.")
        result = reconstruct(body, progress=emit)
        source_name = Path(str(body.get("source_name") or "")).name[:180]
        emit("usage", {"source_name": source_name, "proof": result.get("proof") or {}})
        emit_result(result, emit, wire_version=int(body.get("wire_version") or 1))
    except StudioEnvelopeError as error:
        detail: dict[str, Any] = {"code": error.code, "message": error.message}
        if error.proof:
            detail["proof"] = error.proof
        emit("error", detail)
    except (BrokenPipeError, ConnectionResetError):
        return 0
    except Exception:  # pragma: no cover - runtime boundary
        emit("error", {"code": "studio_worker_failed", "message": "O Studio encontrou uma falha interna no tratamento."})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
