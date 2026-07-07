from __future__ import annotations

from typing import Any


LOCAL_TOOL_PATHS: dict[str, str] = {
    "kernel.capabilities": "/agent/tools/kernel.capabilities",
    "kernel.resolve": "/agent/tools/kernel.resolve",
    "kernel.inspect": "/agent/tools/kernel.inspect",
    "kernel.act": "/agent/tools/kernel.act",
    "kernel.prove": "/agent/tools/kernel.prove",
    "route.resolve": "/agent/tools/route.resolve",
    "map.summary": "/agent/tools/map.summary",
    "lookup.files": "/agent/tools/lookup.files",
    "lookup.symbol": "/agent/tools/lookup.symbol",
    "file.read_bounded": "/agent/tools/file.read_bounded",
    "patch.apply_scoped": "/agent/tools/patch.apply_scoped",
    "test.run_focused": "/agent/tools/test.run_focused",
    "git.diff_summary": "/agent/tools/git.diff_summary",
    "proof.collect": "/agent/tools/proof.collect",
    "cost.status": "/agent/tools/cost.status",
    "code.memory.index": "/agent/tools/code.memory.index",
    "code.memory.status": "/agent/tools/code.memory.status",
    "code.memory.search": "/agent/tools/code.memory.search",
    "code.memory.impact": "/agent/tools/code.memory.impact",
    "transcript.read": "/agent/tools/transcript.read",
    "messages.read": "/agent/tools/transcript.read",
    "node.capabilities": "/agent/tools/node.capabilities",
    "node.chat": "/agent/tools/node.chat",
    "hermes.capabilities": "/agent/tools/hermes.capabilities",
}


KERNEL_ACTION_TOOL_PATHS: dict[str, str] = {
    key: value
    for key, value in LOCAL_TOOL_PATHS.items()
    if key != "hermes.capabilities"
}


KERNEL_ACTIONS: tuple[dict[str, str], ...] = (
    {
        "id": "kernel.capabilities",
        "type": "kernel",
        "description": "Report local kernel capabilities, costs, budgets, and proof classes.",
    },
    {
        "id": "kernel.resolve",
        "type": "kernel",
        "description": "Resolve objective/surface to route, entity, workspace, and capability contracts.",
    },
    {
        "id": "kernel.inspect",
        "type": "kernel",
        "description": "Inspect bounded route-scoped state, files, symbols, timeline, cost, or explicit unknowns.",
    },
    {
        "id": "kernel.act",
        "type": "kernel",
        "description": "Execute scoped local actions under declared route contracts only.",
    },
    {
        "id": "kernel.prove",
        "type": "kernel",
        "description": "Collect replayable route, timeline, token, file, test, and runtime proof.",
    },
    {
        "id": "code.memory.search",
        "type": "kernel",
        "description": "Query the route-scoped code graph for symbols/files before bounded source reads.",
    },
    {
        "id": "code.memory.impact",
        "type": "kernel",
        "description": "Map current git changes to affected symbols and route-scoped blast radius.",
    },
)


DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["answer", "decision", "actions", "state_delta", "needs", "confidence"],
    "properties": {
        "answer": {"type": "string"},
        "decision": {"type": "string"},
        "actions": {"type": "array", "items": {"type": "object"}},
        "state_delta": {"type": "object"},
        "needs": {"type": "array", "items": {"type": "string"}},
        "proof_requests": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "additionalProperties": True,
}
