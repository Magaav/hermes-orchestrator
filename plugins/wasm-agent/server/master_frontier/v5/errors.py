from __future__ import annotations

from typing import Any


class V5Error(RuntimeError):
    def __init__(self, code: str, message: str, *, checkpoint: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.checkpoint = checkpoint or {}

