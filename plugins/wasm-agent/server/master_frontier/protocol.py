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
    "checkpoint.resume": "/agent/tools/proof.collect",
    "cost.status": "/agent/tools/cost.status",
    "code.memory.index": "/agent/tools/code.memory.index",
    "code.memory.status": "/agent/tools/code.memory.status",
    "code.memory.search": "/agent/tools/code.memory.search",
    "code.memory.impact": "/agent/tools/code.memory.impact",
    "transcript.read": "/agent/tools/transcript.read",
    "messages.read": "/agent/tools/transcript.read",
    "node.capabilities": "/agent/tools/node.capabilities",
    "skill.select": "/agent/tools/node.capabilities",
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
        "description": "Inspect bounded route-scoped route, files, symbols, proof, cost, transcript, diff, capabilities, or runtime_entity state; source objects require source discovery/read tools.",
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
    {
        "id": "checkpoint.resume",
        "type": "kernel",
        "description": "Load bounded proof and token receipts for a prior interrupted run.",
    },
    {
        "id": "skill.select",
        "type": "kernel",
        "description": "Resolve a requested node skill and report exact availability before use.",
    },
)


DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["answer", "decision", "actions", "state_delta", "needs", "confidence"],
    "properties": {
        "answer": {"type": "string"},
        "decision": {"type": "string"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "id": {"type": "string"},
                    "args": {"type": "object"},
                    "role": {"type": "string"},
                    "route_id": {"type": "string"},
                    "caps": {"type": "array", "items": {"type": "string"}},
                    "objective": {"type": "string"},
                    "escalation_reason": {"type": "string"},
                    "proof": {"type": "array", "items": {"type": "string"}},
                    "harness": {"type": "boolean"},
                },
                "anyOf": [{"required": ["action"]}, {"required": ["id"]}],
                "additionalProperties": False,
            },
        },
        "state_delta": {"type": "object"},
        "model_reflection": {
            "type": "object",
            "description": "Optional labeled self-model/metaphor for reflective turns; not factual proof.",
        },
        "needs": {"type": "array", "items": {"type": "string"}},
        "proof_requests": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "additionalProperties": False,
}
