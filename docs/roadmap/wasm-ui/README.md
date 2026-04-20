# WASM UI Track (Hybrid Realization)

Status: `Implementation in progress` (V1 expanded with Guard + timeline)

## Summary

The UI remains a hybrid local control surface:

- host gateway: `/local/scripts/public/ui-gateway/`
- browser shell: `/local/apps/wasm-ui/`
- targeted Rust/WASM worker for bounded analysis work only

The product direction is now explicit:

- situation first
- safe actions second
- logs and raw evidence as drill-down

Guard observability and per-agent work timelines are now part of the V1 product lane, not future extras.

## Product Lane

Steer the UI toward:

- detect what matters first
- understand why a node is unhealthy
- act through bounded controls
- review evidence and recent agent work afterward

This is intentionally different from a generic admin dashboard or log tailer.

## Canonical Data Sources

Gateway and UI contracts are frozen to these sources:

- `scripts/public/clone/clone_manager.py`
- `/local/agents/registry.json`
- `/local/logs/nodes/<node>/*`
- `/local/logs/attention/nodes/<node>/*`
- `/local/logs/guard/*`
- `/local/logs/nodes/activities/<node>.jsonl`

## V1 Surfaces

- Fleet posture summary
- Urgency-sorted node list
- Selected-node operational snapshot
- Incident triage panel
- Guard doctor summary and per-node remediation panel
- Agent activity timeline
- Analyzer pulse
- Safe actions only: `start`, `stop`, `restart`
- Log drill-down across runtime, management, attention, and Hermes channels

## Public API (Current)

Base URL: local gateway (`127.0.0.1:8787` by default)

1. `GET /api/fleet/capabilities`
2. `GET /api/fleet/nodes`
3. `GET /api/fleet/guard/status`
4. `GET /api/fleet/nodes/{node}/status`
5. `GET /api/fleet/nodes/{node}/logs?channel=...&tail=...`
6. `GET /api/fleet/nodes/{node}/guard?limit=...`
7. `GET /api/fleet/nodes/{node}/activity?limit=...`
8. `GET /api/fleet/stream`
9. `POST /api/fleet/nodes/{node}/actions` with allowlisted actions `start|stop|restart`

## Live Stream Events

`GET /api/fleet/stream` now includes:

- `connected`
- `heartbeat`
- `status`
- `log`
- `action`
- `monitor`
- `guard`
- `activity`

The UI should treat `guard` and `activity` as first-class product signals, not as generic toast noise.

## Guard Observability Contract

The dashboard must expose:

- daemon/effective guard status
- last cycle time
- warned nodes
- remediated nodes
- nodes in cooldown
- nodes at retry ceiling
- latest guard finding per selected node
- recent remediation records per selected node

## Activity Timeline Contract

The dashboard timeline is sourced from:

- `/local/logs/nodes/activities/<node>.jsonl`

Each record represents one interaction cycle and includes:

- `ts`
- `node`
- `session_id`
- `agent_identity`
- `interaction_source`
- `last_activity_desc`
- `tool_usage`
- `cycle_outcome`

The UI should prefer this timeline over synthetic “recent event” lists so operators can see what an agent or human actually did, in order.

## Safety Controls

- CLI remains canonical
- action allowlist only
- server-side validation for node and action names
- fresh status check immediately before action execution
- optional bearer auth
- SSE token compatibility for browser `EventSource`
- rate limiting and log redaction remain mandatory

## Next Steps

1. Add cross-panel incident linking so a Guard finding jumps directly to relevant logs and timeline cycles.
2. Add richer history views for “what changed” across restarts, warnings, and operator actions.
3. Surface retry exhaustion and cooldown as explicit fleet filters.
4. Add deeper analyzer modules only where they prove real value over the current lightweight pulse.
