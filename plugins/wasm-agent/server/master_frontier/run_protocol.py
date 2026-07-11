from __future__ import annotations

from typing import Any


V3 = "v3"
V4 = "v4-source-investigation"
V4_FLAG = "source-investigation-read-only"
V5 = "v5"


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message); self.code = code


def select(body: dict[str, Any]) -> str:
    requested = str(body.get("protocol") or "").strip()
    flag = str(body.get("investigation_mode") or "").strip()
    if requested in {"", V3}: return V3
    if requested == V5: return V5
    if requested == V4 and flag == V4_FLAG: return V4
    if requested == V4: raise ProtocolError("v4_read_only_flag_required", "V4 requires the explicit read-only source-investigation flag.")
    raise ProtocolError("protocol_unknown", "Unknown Master:frontier protocol.")


def persisted(row: dict[str, Any] | Any) -> str:
    try: value = str(row["protocol"] or "")
    except (KeyError, TypeError, IndexError): value = ""
    return value or V3


def require_resume(original: str, body: dict[str, Any]) -> str:
    selected = select(body) if body.get("protocol") else original
    if selected != original: raise ProtocolError("protocol_immutable", "A run protocol cannot change during resume.")
    return original


def request_fields(body: dict[str, Any]) -> dict[str, str]:
    protocol = select(body)
    return {"protocol": protocol, "investigation_mode": V4_FLAG if protocol == V4 else ""}
