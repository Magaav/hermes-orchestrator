"""Bounded provider transport policy shared by Master:frontier controllers."""
from __future__ import annotations

import math
import os
from collections.abc import Mapping


DEFAULT_TIMEOUT_SEC = 90.0
MIN_TIMEOUT_SEC = 15.0
MAX_TIMEOUT_SEC = 180.0
TIMEOUT_ENV = "HERMES_WASM_AGENT_PROVIDER_TIMEOUT_SEC"


def timeout_sec(environ: Mapping[str, str] | None = None, *, requested: object = None) -> float:
    source = os.environ if environ is None else environ
    try:
        value = float(str(source.get(TIMEOUT_ENV, DEFAULT_TIMEOUT_SEC) or DEFAULT_TIMEOUT_SEC))
    except (TypeError, ValueError):
        value = DEFAULT_TIMEOUT_SEC
    if not math.isfinite(value):
        value = DEFAULT_TIMEOUT_SEC
    bounded = max(MIN_TIMEOUT_SEC, min(MAX_TIMEOUT_SEC, value))
    if requested is not None and not isinstance(requested, bool):
        try:
            requested_value = float(requested)
        except (TypeError, ValueError):
            requested_value = bounded
        if math.isfinite(requested_value):
            bounded = min(bounded, max(0.001, requested_value))
    return bounded
