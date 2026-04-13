from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class FleetCapabilities:
    core: dict[str, Any]
    enhanced: dict[str, Any]
    experimental_enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FleetNodeSummary:
    node: str
    runtime_type: str
    running: bool
    status: str
    state_mode: str
    state_code: int | None
    attention_events_last_200: int
    log_paths: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FleetNodeStatus:
    node: str
    running: bool
    status: str
    runtime_type: str
    state_mode: str
    state_code: int | None
    env_path: str
    clone_root: str
    required_mounts_ok: bool | None
    logs: dict[str, str]
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FleetLogEvent:
    id: str
    node: str
    channel: str
    ts: str
    severity: str
    message: str
    raw: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FleetActionRequest:
    node: str
    action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FleetActionResult:
    request: FleetActionRequest
    accepted: bool
    started_at: str
    finished_at: str
    before: dict[str, Any]
    after: dict[str, Any]
    action_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["request"] = self.request.to_dict()
        return data
