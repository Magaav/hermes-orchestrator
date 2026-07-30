#!/usr/bin/env python3
"""Visão-owned Master:frontier envelope over the authenticated Codex transport."""

from __future__ import annotations

import base64
import binascii
import json
import os
import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from studio_runtime import CodexCredentialsError, codex_credentials


MASTER_MODEL = "master:frontier"
PROVIDER_MODEL = "gpt-5.5"
DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_RESULT_BYTES = 32 * 1024 * 1024
MAX_EVENT_BYTES = 48 * 1024 * 1024
TRANSPORT_TIMEOUT_SECONDS = 180
SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/avif"}
UrlOpen = Callable[..., Any]


@dataclass(frozen=True)
class StudioEnvelopeError(RuntimeError):
    code: str
    message: str
    proof: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def _decode_source(body: dict[str, Any]) -> tuple[bytes, str]:
    if body.get("cloud_consent") is not True:
        raise StudioEnvelopeError(
            "cloud_consent_required",
            "Confirme o processamento seguro no datacenter.",
        )
    media_type = str(body.get("media_type") or "").lower()
    if media_type not in SUPPORTED_MEDIA_TYPES:
        raise StudioEnvelopeError(
            "unsupported_image",
            "Use uma imagem JPEG, PNG, WebP ou AVIF.",
        )
    try:
        image = base64.b64decode(str(body.get("image_base64") or ""), validate=True)
    except (ValueError, binascii.Error) as error:
        raise StudioEnvelopeError("invalid_image", "A imagem enviada é inválida.") from error
    if not image:
        raise StudioEnvelopeError("empty_image", "A imagem enviada está vazia.")
    if len(image) > MAX_SOURCE_BYTES:
        raise StudioEnvelopeError("image_too_large", "A imagem deve ter no máximo 20 MB.")
    return image, media_type


def studio_envelope(
    *,
    media_type: str,
    source_bytes: int,
    watermark_authorized: bool,
    trace_id: str,
) -> dict[str, Any]:
    watermark_rule = (
        "Remove visible watermarks; the user explicitly authorized their removal."
        if watermark_authorized
        else "Preserve every watermark; removal is not authorized."
    )
    return {
        "schema": "visao.studio.master_frontier.envelope.v1",
        "trace_id": trace_id,
        "model": MASTER_MODEL,
        "objective": "Clean the attached property photo and return exactly one edited image.",
        "state": {
            "media_type": media_type,
            "source_bytes": source_bytes,
            "watermark_authorized": watermark_authorized,
        },
        "capabilities": ["image.generate.edit"],
        "constraints": [
            "The attached image is the only edit target; inspect the entire frame.",
            "Remove movable non-property clutter, staging distractions, loose floor dirt, dust, grit, crumbs, hair, and debris.",
            watermark_rule,
            "Naturally reconstruct revealed texture, geometry, perspective, reflections, shadows, and occlusion.",
            "Preserve camera position, crop, aspect ratio, room geometry, fixtures, built-ins, doors, windows, lighting, color balance, and unselected content.",
            "Do not redesign, beautify, stage, add decor or openings, blur, leave remnants, or add text.",
            "Inspect the result for remnants, broken geometry, or synthetic fill before returning it.",
        ],
        "allowed_actions": [{"name": "image.generate.edit", "max_calls": 1}],
        "output": {"kind": "image", "count": 1},
        "budget": {"max_images": 1},
    }


def _request_body(
    image: bytes,
    media_type: str,
    envelope: dict[str, Any],
    provider_model: str,
) -> dict[str, Any]:
    encoded = base64.b64encode(image).decode("ascii")
    developer = (
        "You are the image execution surface for Visão Studio. Consume the bounded "
        "Master:frontier envelope, follow every constraint, call image_generation "
        "exactly once to edit the attached image, and return no prose."
    )
    return {
        "model": provider_model,
        "store": False,
        "stream": True,
        "input": [
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": developer}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(envelope, ensure_ascii=True, separators=(",", ":")),
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{media_type};base64,{encoded}",
                        "detail": "high",
                    },
                ],
            },
        ],
        "tools": [{"type": "image_generation", "action": "edit", "quality": "high"}],
    }


def _iter_sse_json(response: BinaryIO) -> Iterator[dict[str, Any]]:
    event_bytes = 0
    data_lines: list[bytes] = []
    while True:
        line = response.readline(MAX_EVENT_BYTES + 1)
        if len(line) > MAX_EVENT_BYTES:
            raise StudioEnvelopeError(
                "studio_response_too_large",
                "O datacenter retornou um evento maior que o limite do Studio.",
            )
        if not line:
            break
        event_bytes += len(line)
        if event_bytes > MAX_EVENT_BYTES:
            raise StudioEnvelopeError(
                "studio_response_too_large",
                "O datacenter retornou um evento maior que o limite do Studio.",
            )
        stripped = line.rstrip(b"\r\n")
        if stripped:
            if stripped.startswith(b"data:"):
                data_lines.append(stripped[5:].lstrip())
            continue
        if data_lines:
            raw = b"\n".join(data_lines)
            data_lines = []
            event_bytes = 0
            if raw != b"[DONE]":
                try:
                    payload = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise StudioEnvelopeError(
                        "studio_response_invalid",
                        "O datacenter retornou um evento inválido.",
                    ) from error
                if isinstance(payload, dict):
                    yield payload


def _image_item(value: Any) -> dict[str, Any] | None:
    item = value if isinstance(value, dict) else {}
    item_type = str(item.get("type") or "")
    if item_type in {"image_generation_call", "imageGeneration"} and (
        item.get("result") or item.get("image_base64") or item.get("b64_json")
    ):
        return item
    return None


def _response_error(event: dict[str, Any]) -> StudioEnvelopeError:
    error = event.get("error") if isinstance(event.get("error"), dict) else {}
    response = event.get("response") if isinstance(event.get("response"), dict) else {}
    detail = str(error.get("message") or response.get("incomplete_details") or "")
    if "rate" in detail.lower() or "limit" in detail.lower():
        return StudioEnvelopeError(
            "studio_rate_limited",
            "O limite do Codex foi atingido. Aguarde um instante e tente novamente.",
        )
    return StudioEnvelopeError(
        "studio_provider_failed",
        "O Codex não concluiu o tratamento desta foto.",
    )


def _http_error(error: HTTPError) -> StudioEnvelopeError:
    if error.code in {401, 403}:
        return StudioEnvelopeError(
            "studio_codex_reconnect_required",
            "A sessão do Codex expirou. Reconecte-a nas Configurações do Studio.",
        )
    if error.code == 429:
        return StudioEnvelopeError(
            "studio_rate_limited",
            "O limite do Codex foi atingido. Aguarde um instante e tente novamente.",
        )
    if error.code in {400, 404, 422}:
        return StudioEnvelopeError(
            "studio_image_edit_rejected",
            "O Codex recusou esta edição ou formato de imagem.",
        )
    return StudioEnvelopeError(
        "studio_provider_unavailable",
        "O datacenter do Studio está temporariamente indisponível.",
    )


def _token_count(value: Any, *keys: str) -> int:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return 0
        current = current.get(key)
    try:
        return max(0, int(current or 0))
    except (TypeError, ValueError):
        return 0


def _normalized_usage(
    completed_response: dict[str, Any],
    generated: dict[str, Any],
) -> dict[str, Any]:
    main = completed_response.get("usage") if isinstance(completed_response.get("usage"), dict) else {}
    image = generated.get("usage") if isinstance(generated.get("usage"), dict) else {}
    main_available = bool(main)
    image_available = bool(image)
    main_input = _token_count(main, "input_tokens")
    main_output = _token_count(main, "output_tokens")
    image_input = _token_count(image, "input_tokens")
    image_output = _token_count(image, "output_tokens")
    main_total = _token_count(main, "total_tokens") or main_input + main_output
    image_total = _token_count(image, "total_tokens") or image_input + image_output
    return {
        "available": main_available or image_available,
        "complete": main_available and image_available,
        "source": "provider_reported",
        "main_available": main_available,
        "image_available": image_available,
        "main_input_tokens": main_input,
        "cached_main_input_tokens": _token_count(main, "input_tokens_details", "cached_tokens"),
        "main_output_tokens": main_output,
        "reasoning_output_tokens": _token_count(main, "output_tokens_details", "reasoning_tokens"),
        "image_input_tokens": image_input,
        "image_output_tokens": image_output,
        "image_text_input_tokens": _token_count(image, "input_tokens_details", "text_tokens"),
        "image_source_input_tokens": _token_count(image, "input_tokens_details", "image_tokens"),
        "total_tokens": main_total + image_total,
    }


def _image_bytes(generated: dict[str, Any]) -> bytes:
    encoded = str(
        generated.get("result")
        or generated.get("image_base64")
        or generated.get("b64_json")
        or ""
    )
    try:
        image = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise StudioEnvelopeError(
            "studio_image_invalid",
            "O datacenter retornou uma imagem inválida.",
        ) from error
    if not image or len(image) > MAX_RESULT_BYTES:
        raise StudioEnvelopeError(
            "studio_image_invalid",
            "O datacenter retornou uma imagem inválida.",
        )
    return image


def _result_media_type(image: bytes) -> str:
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image.startswith(b"RIFF") and image[8:12] == b"WEBP":
        return "image/webp"
    raise StudioEnvelopeError("studio_image_invalid", "O datacenter retornou uma imagem inválida.")


def reconstruct(
    body: dict[str, Any],
    *,
    opener: UrlOpen = urlopen,
    progress: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    report = progress or (lambda _stage, _detail: None)
    image, media_type = _decode_source(body)
    trace_id = uuid.uuid4().hex
    envelope = studio_envelope(
        media_type=media_type,
        source_bytes=len(image),
        watermark_authorized=body.get("watermark_authorized") is True,
        trace_id=trace_id,
    )
    try:
        credentials = codex_credentials()
    except CodexCredentialsError as error:
        raise StudioEnvelopeError(
            "studio_codex_reconnect_required",
            "Conecte sua conta Codex nas Configurações do Studio.",
        ) from error

    provider_model = (
        os.environ.get("STUDIO_MASTER_FRONTIER_PROVIDER_MODEL", PROVIDER_MODEL).strip()
        or PROVIDER_MODEL
    )
    base_url = os.environ.get("STUDIO_CODEX_BASE_URL", DEFAULT_CODEX_BASE_URL).rstrip("/")
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {credentials.access_token}",
        "User-Agent": "visao-studio/1.0",
        "originator": "codex_cli_rs",
    }
    if credentials.account_id:
        headers["ChatGPT-Account-ID"] = credentials.account_id
    request = Request(
        f"{base_url}/responses",
        data=json.dumps(
            _request_body(image, media_type, envelope, provider_model),
            separators=(",", ":"),
        ).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    report("accepted", {"media_type": media_type, "bytes": len(image)})
    report(
        "envelope-starting",
        {"schema": envelope["schema"], "model": MASTER_MODEL, "trace_id": trace_id},
    )
    started = time.monotonic()
    generated: dict[str, Any] | None = None
    completed_response: dict[str, Any] = {}
    request_id = ""
    try:
        report("reconstructing", {})
        with opener(request, timeout=TRANSPORT_TIMEOUT_SECONDS) as response:
            request_id = str(getattr(response, "headers", {}).get("x-request-id") or "")
            for event in _iter_sse_json(response):
                event_type = str(event.get("type") or event.get("event") or "")
                for candidate in (
                    event.get("item"),
                    event.get("output_item"),
                ):
                    generated = _image_item(candidate) or generated
                response_payload = event.get("response")
                if isinstance(response_payload, dict):
                    for candidate in response_payload.get("output") or []:
                        generated = _image_item(candidate) or generated
                if event_type in {"response.completed", "response.done", "response.output.done"}:
                    completed_response = response_payload if isinstance(response_payload, dict) else event
                if event_type in {"response.failed", "response.incomplete"}:
                    raise _response_error(event)
    except HTTPError as error:
        raise _http_error(error) from error
    except (TimeoutError, socket.timeout) as error:
        raise StudioEnvelopeError(
            "studio_provider_timeout",
            "O tratamento ultrapassou o tempo limite. Tente novamente.",
        ) from error
    except URLError as error:
        raise StudioEnvelopeError(
            "studio_provider_unavailable",
            "O datacenter do Studio está temporariamente indisponível.",
        ) from error

    if not generated:
        raise StudioEnvelopeError(
            "studio_image_missing",
            "O Codex concluiu sem retornar a imagem tratada.",
        )
    result = _image_bytes(generated)
    result_media_type = _result_media_type(result)
    report("artifact-generated", {})
    report("finalizing", {})
    return {
        "ok": True,
        "schema": "visao.studio.property_photo_edit.v1",
        "image_base64": base64.b64encode(result).decode("ascii"),
        "media_type": result_media_type,
        "model": MASTER_MODEL,
        "scene_inspected": True,
        "watermark_authorized": body.get("watermark_authorized") is True,
        "photo_persisted": False,
        "proof": {
            "schema": envelope["schema"],
            "trace_id": trace_id,
            "model": MASTER_MODEL,
            "provider_model": provider_model,
            "response_id": str(completed_response.get("id") or request_id),
            "status": "completed",
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "usage": _normalized_usage(completed_response, generated),
        },
    }
