# WASM UI Track (Hybrid Realization)

Status: `Implementation in progress` (V1 scope locked)

## Summary

Build a hybrid control-plane architecture:

- Local gateway service on host (`/local/scripts/ui-gateway/`)
- Browser UI shell (`/local/apps/wasm-ui/`)
- Targeted Rust/WASM worker for proven hot paths only

The operational source of truth remains CLI-first:

- `horc` and `scripts/clone/clone_manager.py`

UI is an augmentation layer, not a runtime ownership transfer.

## Possibilities and Decision

1. `Hybrid on Hermes Workspace` (selected): fastest path with controlled reuse and low migration risk.
2. `Greenfield UI`: cleaner boundaries but slower and higher implementation burden.
3. `Full Workspace Fork`: rich initial UX, but high long-term drift and unrelated feature baggage.

Decision: implement option `1`.

## V1 Scope (Locked)

- Observability: fleet/node status + multi-channel logs
- Safe operations only: `start`, `stop`, `restart`
- No destructive actions
- No requirement that UI exists for production operations

## Why Hybrid Beats Full PWA-First

1. Orchestrator actions require host privileges (`docker`, local files, runtime contracts) and should remain on a trusted local control plane.
2. CLI governance and runtime safety already exist in `clone_manager.py`; preserving this minimizes operational regression risk.
3. Offline-first caching in a PWA increases stale-state risk for control actions; this surface prioritizes freshness and explicit status checks.
4. WASM provides best ROI on bounded compute-heavy tasks (log parsing/aggregation/layout), not end-to-end app logic.

## Canonical Data Sources

Gateway and UI contracts are frozen to these sources:

- `scripts/clone/clone_manager.py` JSON outputs
- `/local/logs/nodes/<node>/*`
- `/local/logs/attention/nodes/<node>/*`
- `/local/agents/registry.json`

## Public API (V1)

Base URL: local gateway (`127.0.0.1:8787` by default)

1. `GET /api/fleet/capabilities`
2. `GET /api/fleet/nodes`
3. `GET /api/fleet/nodes/{node}/status`
4. `GET /api/fleet/nodes/{node}/logs?channel=...&tail=...`
5. `GET /api/fleet/stream` (SSE)
6. `POST /api/fleet/nodes/{node}/actions` with allowlisted actions `start|stop|restart`

## Shared Contracts

### `FleetCapabilities`

```json
{
  "core": {
    "health": true,
    "nodes": true,
    "status": true,
    "logs": true,
    "sse": true,
    "safe_actions": ["restart", "start", "stop"],
    "auth_required": false,
    "experimental_gate": "WASM_UI_EXPERIMENTAL",
    "experimental_active": true,
    "source_of_truth": "scripts/clone/clone_manager.py"
  },
  "enhanced": {
    "wasm_worker_rust_source": true,
    "wasm_worker_built": false,
    "wasm_runtime_switch": true,
    "js_fallback": true,
    "terminal_passthrough": false
  },
  "experimental_enabled": true
}
```

### `FleetNodeSummary`

```json
{
  "node": "orchestrator",
  "runtime_type": "baremetal",
  "running": true,
  "status": "running",
  "state_mode": "orchestrator",
  "state_code": 1,
  "attention_events_last_200": 2,
  "log_paths": {
    "management": "/local/logs/nodes/orchestrator/management.log",
    "runtime": "/local/logs/nodes/orchestrator/runtime.log",
    "attention": "/local/logs/attention/nodes/orchestrator/warning-plus.log",
    "hermes_errors": "/local/logs/nodes/orchestrator/hermes/errors.log",
    "hermes_gateway": "/local/logs/nodes/orchestrator/hermes/gateway.log",
    "hermes_agent": "/local/logs/nodes/orchestrator/hermes/agent.log"
  }
}
```

### `FleetNodeStatus`

`FleetNodeStatus` extends summary-oriented fields with `env_path`, `clone_root`, `required_mounts_ok`, and raw `clone_manager` payload pass-through (`raw`).

### `FleetLogEvent`

```json
{
  "id": "0a1b2c...",
  "node": "orchestrator",
  "channel": "runtime",
  "ts": "2026-04-11T15:00:00Z",
  "severity": "warning",
  "message": "...redacted line...",
  "raw": "...redacted line..."
}
```

### `FleetActionRequest` / `FleetActionResult`

```json
{
  "request": { "node": "orchestrator", "action": "restart" },
  "accepted": true,
  "started_at": "2026-04-11T15:03:20Z",
  "finished_at": "2026-04-11T15:03:32Z",
  "before": { "status": "running" },
  "after": { "status": "running" },
  "action_payload": { "stop": { "ok": true }, "start": { "ok": true } }
}
```

## SSE Event Schema

Endpoint: `GET /api/fleet/stream`

Transport:

- Content type: `text/event-stream`
- Keepalive: periodic `heartbeat`
- Broker fanout: one publish path to many subscribers

Event names:

- `connected`
- `heartbeat`
- `status`
- `log`
- `action`
- `monitor`

Envelope behavior:

- SSE `event` = event name
- SSE `data` = event payload JSON
- Every payload includes `emitted_at` injected by broker

`log` payloads are normalized and redacted before fanout.

## Safety and Rollback Behavior

### Safety Controls

- Input validation for node and action names
- Action allowlist only: `start`, `stop`, `restart`
- Fresh status check is executed server-side immediately before action
- Optional bearer auth (`WASM_UI_API_TOKEN`)
- SSE auth compatibility: `/api/fleet/stream?token=...` supported for browser `EventSource`
- Sliding-window request rate limiting
- Sensitive token redaction in log surfaces

### Rollback / Disable

1. Disable UI APIs by unsetting experimental gate:
   - `unset WASM_UI_EXPERIMENTAL`
2. Keep operations on CLI:
   - `horc` remains canonical and fully supported
3. Optional hard-stop of gateway process:
   - stop `python3 /local/scripts/ui-gateway/run.py`

No data migration is required for rollback.

## Hermes Workspace Contribution Map

Validated against `outsourc-e/hermes-workspace` commit `379f3b1` (checked on `2026-04-11`).

Reuse now:

1. Capability model and graceful degradation patterns
   - `docs/hermes-openai-compat-spec.md` (core vs enhanced capability split)
   - `src/lib/feature-gates.ts`
2. SSE fanout + dedup transport ideas
   - `src/server/chat-event-bus.ts`
   - `src/routes/api/chat-events.ts`
3. Auth and rate-limit guard patterns
   - `src/server/auth-middleware.ts`
   - `src/server/rate-limit.ts`
4. Terminal PTY transport pattern (phase-2 optional)
   - `src/server/terminal-sessions.ts`

Do not adopt as-is in V1:

1. Chat/session-specific API routes and UX assumptions
2. Workspace-daemon dependent surfaces outside orchestrator scope
3. PWA offline/service-worker assumptions (workspace explicitly unregisters SW to avoid stale assets)

## Implementation Map

1. Gateway service: `/local/scripts/ui-gateway/`
2. UI shell: `/local/apps/wasm-ui/`
3. Targeted WASM worker: `/local/apps/wasm-ui/wasm/log-worker/`
4. Benchmark harness: `/local/apps/wasm-ui/scripts/benchmark-log-parser.mjs`
5. Build orchestration: `/local/apps/wasm-ui/Makefile` + `/local/apps/wasm-ui/Dockerfile.build`

## Test Plan (V1)

Unit tests:

1. Action allowlist and input validation
2. Log normalization + redaction
3. Capability model shape

Integration tests:

1. `clone_manager` roundtrip parity (`status/start/stop/logs`)
2. Node-not-found / docker-unavailable / permission-denied error paths
3. Registry + filesystem node discovery parity

Performance tests:

1. Large-log parse benchmark (100k+ lines)
2. JS vs WASM switch decision (WASM only when materially faster)

## Acceptance Criteria

1. UI is optional; CLI remains fully valid.
2. V1 exposes no destructive operations.
3. No stale-state action execution path (fresh status check before action).
4. Feature-gating prevents broken tabs/spinners on unsupported surfaces.

## Runbook

```bash
WASM_UI_EXPERIMENTAL=1 python3 /local/scripts/ui-gateway/run.py
# open http://127.0.0.1:8787
```

Optional auth:

```bash
export WASM_UI_API_TOKEN='your-token'
WASM_UI_EXPERIMENTAL=1 python3 /local/scripts/ui-gateway/run.py
```

## Sources

- Hermes Workspace repository: `https://github.com/outsourc-e/hermes-workspace`
- Hermes OpenAI compatibility spec: `https://github.com/outsourc-e/hermes-workspace/blob/main/docs/hermes-openai-compat-spec.md`
