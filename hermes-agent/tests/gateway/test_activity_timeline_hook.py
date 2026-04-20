from __future__ import annotations

import json
from pathlib import Path

import pytest

from gateway.builtin_hooks import activity_timeline


def test_build_activity_entry_normalizes_source_and_outcome() -> None:
    entry = activity_timeline.build_activity_entry(
        {
            "node": "orchestrator",
            "finished_at": "2026-04-18T12:00:00Z",
            "agent_identity": "doctor",
            "source_is_bot": True,
            "cycle_outcome": "success",
            "message": "check fleet",
            "response": "all green",
            "activity_summary": {
                "last_activity_desc": "Reviewed fleet state",
                "api_call_count": 2,
            },
            "tool_usage": {
                "tool_count": 1,
                "tool_names": ["shell"],
            },
        }
    )

    assert entry is not None
    assert entry["node"] == "orchestrator"
    assert entry["interaction_source"] == "agent"
    assert entry["cycle_outcome"] == "completed"
    assert entry["tool_usage"]["tool_count"] == 1
    assert entry["tool_usage"]["api_call_count"] == 2
    assert "Reviewed fleet state" in entry["summary_text"]


@pytest.mark.asyncio
async def test_handle_appends_one_jsonl_record_per_agent_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_AGENTS_ACTIVITY_LOG_ROOT", str(tmp_path))

    await activity_timeline.handle(
        "agent:end",
        {
            "node": "orchestrator",
            "finished_at": "2026-04-18T12:01:00Z",
            "platform": "discord",
            "user_name": "alex",
            "cycle_outcome": "errored",
            "message": "restart it",
            "response": "restart failed",
            "activity_summary": {
                "last_activity_desc": "Restart attempt failed",
                "api_call_count": 1,
            },
            "tool_usage": {
                "tool_count": 2,
                "names": ["clone_manager", "discord"],
            },
        },
    )

    path = tmp_path / "orchestrator.jsonl"
    assert path.exists()

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) == 1
    assert records[0]["interaction_source"] == "human"
    assert records[0]["cycle_outcome"] == "errored"
    assert records[0]["tool_usage"]["unique_tool_count"] == 2
    assert records[0]["tool_usage"]["tool_names"] == ["clone_manager", "discord"]
    assert records[0]["user_name"] == "alex"
