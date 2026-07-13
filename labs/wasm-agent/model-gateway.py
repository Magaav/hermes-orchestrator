#!/usr/bin/env python3
"""Run-scoped allowlisted GLM gateway for safe-lab live adapter proofs."""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import threading
import time
import urllib.error
import urllib.request
import re
from pathlib import Path

import responses_bridge
import anthropic_bridge
import gemini_bridge
from urllib.parse import urlsplit

UPSTREAM = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL_REQUEST = "glm-5.2"
MODEL_EXPECTED = "frank/GLM-5.2"
TOKEN = os.environ.get("LAB_BROKER_TOKEN", "")
API_KEY = os.environ.get("UPSTREAM_API_KEY", "")
RECEIPTS = Path("/gateway-output/receipts.jsonl")
MAX_REQUEST_BYTES = 256_000
MAX_RESPONSE_BYTES = 2_000_000
MAX_OUTPUT_TOKENS = min(4096, max(256, int(os.environ.get("LAB_MAX_OUTPUT_TOKENS", "512"))))
RECEIPT_LOCK = threading.Lock()
REQUEST_COUNTS: dict[str, int] = {}
BENCHMARK_SCENARIO = os.environ.get("LAB_BENCHMARK_SCENARIO", "").strip().lower() in {"1", "true", "yes"}
DUPLICATE_LIMIT = 3 if BENCHMARK_SCENARIO else 2
PROVIDER_CALL_LIMIT = min(64, max(1, int(os.environ.get("LAB_MAX_PROVIDER_CALLS", "4"))))
PROVIDER_CALLS = 0
LANE_ID = re.compile(r"^harness-[0-9]{2}$")


def broker_identity(headers: http.client.HTTPMessage) -> str:
    presented = ""
    authorization = headers.get("Authorization") or ""
    if authorization.startswith("Bearer "):
        presented = authorization.removeprefix("Bearer ")
    presented = presented or headers.get("x-api-key") or headers.get("x-goog-api-key") or ""
    if presented == TOKEN:
        return "single-lane"
    prefix = TOKEN + "."
    lane_id = presented.removeprefix(prefix) if presented.startswith(prefix) else ""
    return lane_id if LANE_ID.fullmatch(lane_id) else ""


def append_receipt(receipt: dict) -> None:
    RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
    with RECEIPT_LOCK:
        with RECEIPTS.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, separators=(",", ":")) + "\n")


def claim_request_budget(request_sha256: str, lane_id: str = "single-lane") -> dict:
    global PROVIDER_CALLS
    with RECEIPT_LOCK:
        budget_key = f"{lane_id}:{request_sha256}"
        duplicate_ordinal = REQUEST_COUNTS.get(budget_key, 0) + 1
        REQUEST_COUNTS[budget_key] = duplicate_ordinal
        if duplicate_ordinal > DUPLICATE_LIMIT:
            return {"allowed": False, "reason": "duplicate", "duplicateOrdinal": duplicate_ordinal}
        provider_call_ordinal = PROVIDER_CALLS + 1
        if provider_call_ordinal > PROVIDER_CALL_LIMIT:
            return {
                "allowed": False,
                "reason": "provider_budget",
                "duplicateOrdinal": duplicate_ordinal,
                "providerCallOrdinal": provider_call_ordinal,
            }
        PROVIDER_CALLS = provider_call_ordinal
        return {
            "allowed": True,
            "reason": "initial" if duplicate_ordinal == 1 else "stability_check",
            "duplicateOrdinal": duplicate_ordinal,
            "providerCallOrdinal": provider_call_ordinal,
        }


def inspect_response(raw: bytes, stream_requested: bool) -> dict:
    if not stream_requested:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("upstream response must be an object")
        choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
        return {
            "payload": payload,
            "returnedModel": str(payload.get("model") or ""),
            "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
            "contentChars": len(message.get("content") if isinstance(message.get("content"), str) else ""),
            "reasoningChars": len(message.get("reasoning_content") if isinstance(message.get("reasoning_content"), str) else ""),
            "toolCallCount": len(tool_calls),
            "toolNames": [
                str((item.get("function") if isinstance(item.get("function"), dict) else item).get("name") or "")[:80]
                for item in tool_calls if isinstance(item, dict)
            ],
            "finishReason": str(choice.get("finish_reason") or ""),
        }

    models: set[str] = set()
    usage: dict = {}
    content_chars = reasoning_chars = 0
    finish_reason = ""
    tool_calls: set[tuple[int, str]] = set()
    event_count = 0
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if not data or data == b"[DONE]":
            continue
        event = json.loads(data)
        if not isinstance(event, dict):
            raise ValueError("SSE event must be an object")
        event_count += 1
        model = str(event.get("model") or "")
        if model:
            models.add(model)
        if isinstance(event.get("usage"), dict):
            usage = event["usage"]
        choices = event.get("choices") if isinstance(event.get("choices"), list) else []
        for choice_index, choice in enumerate(choices):
            if not isinstance(choice, dict):
                continue
            finish_reason = str(choice.get("finish_reason") or finish_reason)
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            content_chars += len(delta.get("content") if isinstance(delta.get("content"), str) else "")
            reasoning_chars += len(delta.get("reasoning_content") if isinstance(delta.get("reasoning_content"), str) else "")
            fragments = delta.get("tool_calls") if isinstance(delta.get("tool_calls"), list) else []
            for fragment_index, fragment in enumerate(fragments):
                if isinstance(fragment, dict):
                    key = str(fragment.get("index") if fragment.get("index") is not None else fragment.get("id") or fragment_index)
                    tool_calls.add((choice_index, key))
    if not event_count or len(models) != 1:
        raise ValueError("SSE response lacks one stable model identity")
    return {
        "payload": {},
        "returnedModel": next(iter(models)),
        "usage": usage,
        "contentChars": content_chars,
        "reasoningChars": reasoning_chars,
        "toolCallCount": len(tool_calls),
        "finishReason": finish_reason,
    }


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "wasm-agent-safe-lab-gateway/1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def send_json(self, status: int, value: dict) -> None:
        data = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_sse(self, data: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self.send_json(200, {"ok": True, "model": MODEL_EXPECTED})
        else:
            self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        global PROVIDER_CALLS
        path = urlsplit(self.path).path
        responses_mode = path == "/v1/responses"
        anthropic_mode = path == "/v1/messages"
        gemini_route = gemini_bridge.parse_path(path)
        gemini_mode = gemini_route is not None
        gemini_action = gemini_route[1] if gemini_route else ""
        lane_id = broker_identity(self.headers) if TOKEN else ""
        broker_authenticated = bool(lane_id)
        if path == "/v1/messages/count_tokens":
            if not broker_authenticated:
                self.send_json(401, {"type": "error", "error": {"type": "authentication_error", "message": "broker_auth_required"}})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError
                raw = self.rfile.read(length)
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError
            except Exception:
                self.send_json(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "invalid_json"}})
                return
            self.send_json(200, anthropic_bridge.count_tokens(payload))
            return
        if gemini_action == "countTokens":
            if not broker_authenticated:
                self.send_json(401, {"error": {"code": 401, "message": "broker_auth_required", "status": "UNAUTHENTICATED"}})
                return
            if gemini_route[0] != MODEL_REQUEST:
                self.send_json(400, {"error": {"code": 400, "message": "model_contract_mismatch", "status": "INVALID_ARGUMENT"}})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError
            except Exception:
                self.send_json(400, {"error": {"code": 400, "message": "invalid_json", "status": "INVALID_ARGUMENT"}})
                return
            self.send_json(200, gemini_bridge.count_tokens(payload))
            return
        if path not in {"/v1/chat/completions", "/v1/responses", "/v1/messages"} and not gemini_mode:
            self.send_json(403, {"error": "path_denied"})
            return
        if not broker_authenticated:
            self.send_json(401, {"error": "broker_auth_required"})
            return
        if gemini_mode and (gemini_route[0] != MODEL_REQUEST or gemini_action not in {"generateContent", "streamGenerateContent"}):
            self.send_json(400, {"error": {"code": 400, "message": "model_contract_mismatch", "status": "INVALID_ARGUMENT"}})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self.send_json(413, {"error": "request_size_denied"})
                return
            raw = self.rfile.read(length)
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            generation_config = payload.get("generationConfig") if isinstance(payload.get("generationConfig"), dict) else {}
            requested_tokens = int(generation_config.get("maxOutputTokens") or payload.get("max_output_tokens") or payload.get("max_tokens") or 512)
            client_stream_requested = gemini_action == "streamGenerateContent" or payload.get("stream") is True
        except Exception:
            self.send_json(400, {"error": "invalid_json"})
            return
        bounded_tokens = min(MAX_OUTPUT_TOKENS, max(256, requested_tokens))
        if responses_mode:
            payload = responses_bridge.request_to_chat(payload, model=MODEL_REQUEST, max_tokens=bounded_tokens)
        elif anthropic_mode:
            payload = anthropic_bridge.request_to_chat(payload, model=MODEL_REQUEST, max_tokens=bounded_tokens)
        elif gemini_mode:
            payload = gemini_bridge.request_to_chat(payload, model=MODEL_REQUEST, max_tokens=bounded_tokens)
        else:
            payload["model"] = MODEL_REQUEST
            payload["max_tokens"] = bounded_tokens
        stream_requested = False if responses_mode or anthropic_mode or gemini_mode else client_stream_requested
        encoded = json.dumps(payload, separators=(",", ":")).encode()
        request_sha256 = hashlib.sha256(encoded).hexdigest()
        admission = claim_request_budget(request_sha256, lane_id)
        duplicate_ordinal = int(admission["duplicateOrdinal"])
        if admission["reason"] == "duplicate":
            append_receipt({
                "schema": "wasm-agent.safe-lab.gateway-receipt.v2",
                "laneId": lane_id,
                "requestSha256": request_sha256,
                "requestModel": MODEL_REQUEST,
                "returnedModel": "",
                "status": 409,
                "contractMatch": False,
                "duplicateOrdinal": duplicate_ordinal,
                "duplicateClass": "waste_blocked",
                "severity": "error",
                "upstreamCalled": False,
                "benchmarkScenario": BENCHMARK_SCENARIO,
                "upstreamHost": "opencode.ai",
                "upstreamPath": "/zen/go/v1/chat/completions",
            })
            self.send_json(409, {"error": "duplicate_request_limit", "duplicateOrdinal": duplicate_ordinal})
            return
        provider_call_ordinal = int(admission.get("providerCallOrdinal") or 0)
        if admission["reason"] == "provider_budget":
            append_receipt({
                "schema": "wasm-agent.safe-lab.gateway-receipt.v2",
                "laneId": lane_id,
                "requestSha256": request_sha256,
                "requestModel": MODEL_REQUEST,
                "returnedModel": "",
                "status": 409,
                "contractMatch": False,
                "duplicateOrdinal": duplicate_ordinal,
                "duplicateClass": "provider_budget_blocked",
                "severity": "error",
                "upstreamCalled": False,
                "providerCallOrdinal": provider_call_ordinal,
                "providerCallLimit": PROVIDER_CALL_LIMIT,
                "benchmarkScenario": BENCHMARK_SCENARIO,
                "upstreamHost": "opencode.ai",
                "upstreamPath": "/zen/go/v1/chat/completions",
            })
            self.send_json(409, {"error": "provider_call_budget", "providerCallOrdinal": provider_call_ordinal})
            return
        request = urllib.request.Request(
            UPSTREAM, data=encoded, method="POST",
            headers={
                "Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json",
                "Accept": "text/event-stream" if stream_requested else "application/json",
                "User-Agent": "wasm-agent/0.1 provider-proxy",
            },
        )
        started = time.monotonic()
        status = 502
        response_payload: dict = {}
        response_raw = b""
        inspected: dict = {}
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                status = response.status
                response_raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(response_raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("upstream response exceeded limit")
                inspected = inspect_response(response_raw, stream_requested)
                response_payload = inspected["payload"]
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                response_payload = json.loads(exc.read().decode("utf-8", "replace"))
                if not isinstance(response_payload, dict):
                    raise ValueError("upstream error response must be an object")
            except Exception:
                response_payload = {"error": "upstream_http_error"}
        except (urllib.error.URLError, TimeoutError, ValueError):
            status = 502
            response_payload = {"error": "upstream_unavailable"}
        returned_model = str(inspected.get("returnedModel") or response_payload.get("model") or "")
        contract_match = status == 200 and returned_model == MODEL_EXPECTED
        forwarded_status = status
        forwarded_payload = response_payload
        if status == 200 and not contract_match:
            forwarded_status = 502
            forwarded_payload = {"error": "model_contract_mismatch"}
        usage = inspected.get("usage") if isinstance(inspected.get("usage"), dict) else {}
        receipt = {
            "schema": "wasm-agent.safe-lab.gateway-receipt.v2",
            "laneId": lane_id,
            "requestSha256": request_sha256,
            "requestModel": MODEL_REQUEST,
            "returnedModel": returned_model,
            "status": status,
            "contractMatch": contract_match,
            "duplicateOrdinal": duplicate_ordinal,
            "duplicateClass": (
                "initial" if duplicate_ordinal == 1
                else ("benchmark_stability" if BENCHMARK_SCENARIO else "stability_check")
            ),
            "severity": "diagnostic",
            "upstreamCalled": True,
            "providerCallOrdinal": provider_call_ordinal,
            "providerCallLimit": PROVIDER_CALL_LIMIT,
            "benchmarkScenario": BENCHMARK_SCENARIO,
            "transport": "responses-via-chat-json" if responses_mode else ("anthropic-via-chat-json" if anthropic_mode else ("gemini-via-chat-json" if gemini_mode else ("sse" if stream_requested else "json"))),
            "promptTokens": usage.get("prompt_tokens"),
            "completionTokens": usage.get("completion_tokens"),
            "contentChars": int(inspected.get("contentChars") or 0),
            "reasoningChars": int(inspected.get("reasoningChars") or 0),
            "toolCallCount": int(inspected.get("toolCallCount") or 0),
            "toolNames": inspected.get("toolNames") if isinstance(inspected.get("toolNames"), list) else [],
            "finishReason": str(inspected.get("finishReason") or ""),
            "durationMs": round((time.monotonic() - started) * 1000),
            "upstreamHost": "opencode.ai",
            "upstreamPath": "/zen/go/v1/chat/completions",
        }
        append_receipt(receipt)
        if responses_mode and forwarded_status == 200:
            self.send_sse(responses_bridge.response_sse(response_payload, model=MODEL_EXPECTED))
        elif anthropic_mode and forwarded_status == 200 and client_stream_requested:
            self.send_sse(anthropic_bridge.message_sse(response_payload, model=MODEL_EXPECTED))
        elif anthropic_mode and forwarded_status == 200:
            self.send_json(200, anthropic_bridge.message(response_payload, model=MODEL_EXPECTED))
        elif gemini_mode and forwarded_status == 200 and client_stream_requested:
            self.send_sse(gemini_bridge.generate_content_sse(response_payload, model=MODEL_EXPECTED))
        elif gemini_mode and forwarded_status == 200:
            self.send_json(200, gemini_bridge.generate_content(response_payload, model=MODEL_EXPECTED))
        elif stream_requested and forwarded_status == 200:
            self.send_sse(response_raw)
        else:
            self.send_json(forwarded_status, forwarded_payload)


def main() -> int:
    if not TOKEN or not API_KEY:
        raise SystemExit("gateway credentials missing")
    http.server.ThreadingHTTPServer(("0.0.0.0", 8787), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
