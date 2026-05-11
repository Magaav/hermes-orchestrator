from __future__ import annotations

from http.client import HTTPMessage


def extract_token(headers: HTTPMessage) -> str:
    """Read the bridge auth token from supported HTTP headers."""
    authorization = str(headers.get("Authorization", "") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return str(headers.get("X-Hermes-Space-Ui-Token", "") or "").strip()


def is_authorized(headers: HTTPMessage, expected_token: str) -> bool:
    expected = str(expected_token or "").strip()
    if not expected:
        return True
    return extract_token(headers) == expected
