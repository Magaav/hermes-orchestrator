"""Owned immutable-protocol dispatch for hosted Master:frontier runs."""
from __future__ import annotations

import time
from typing import Any

from . import controller, controller_v4, controller_v5, controller_v6, run_protocol


def execute(
    protocol: str, server: Any, body: dict[str, Any], *, user: dict[str, Any] | None,
    run: dict[str, Any], context: dict[str, Any], runtime: dict[str, Any],
) -> dict[str, Any]:
    body.setdefault("_master_frontier_started_monotonic", time.monotonic())
    if protocol == run_protocol.V6:
        return controller_v6.execute_owned(server, body, user=user, run_record=run, context=context, runtime=runtime)
    if protocol == run_protocol.V5:
        return controller_v5.execute_owned(server, body, user=user, run_record=run, context=context, runtime=runtime)
    if protocol == run_protocol.V4:
        return controller_v4.execute_owned(server, body, user=user, run_record=run, context=context, runtime=runtime)
    if protocol != run_protocol.V3:
        raise run_protocol.ProtocolError("protocol_unknown", "Unknown persisted Master:frontier protocol.")
    controller.bind_runtime(runtime)
    return controller.provider_envelope_run_execute_owned(server, body, user=user, run=run, context=context)
