# WASM UI Gateway

Local control-plane gateway for Hermes Orchestrator UI.

## Run

```bash
WASM_UI_EXPERIMENTAL=1 python3 /local/scripts/public/ui-gateway/run.py
```

Default bind: `127.0.0.1:8787`

## Environment

- `WASM_UI_EXPERIMENTAL` (required for non-capability API routes)
- `WASM_UI_HOST` (default `127.0.0.1`)
- `WASM_UI_PORT` (default `8787`)
- `WASM_UI_API_TOKEN` (optional bearer auth)
- `WASM_UI_MAX_TAIL_LINES` (default `1500`)
- `WASM_UI_READ_LIMIT_PER_MINUTE` (default `180`)
- `WASM_UI_WRITE_LIMIT_PER_MINUTE` (default `45`)
- `HERMES_AGENTS_ACTIVITY_LOG_ROOT` (default `/local/logs/nodes/activities`)
- `HERMES_GUARD_LOG_ROOT` (default `/local/logs/guard`)

## Endpoints

- `GET /api/fleet/capabilities`
- `GET /api/fleet/nodes`
- `GET /api/fleet/guard/status`
- `GET /api/fleet/nodes/{node}/status`
- `GET /api/fleet/nodes/{node}/logs?channel=...&tail=...`
- `GET /api/fleet/nodes/{node}/guard?limit=...`
- `GET /api/fleet/nodes/{node}/activity?limit=...`
- `GET /api/fleet/stream`
- `POST /api/fleet/nodes/{node}/actions` with `{ "action": "start|stop|restart" }`

## Notes

- Operational source of truth remains `scripts/clone/clone_manager.py`.
- Only safe actions are exposed in V1.
- Static UI is served from `/local/apps/wasm-ui`.
- Disable gateway APIs by unsetting `WASM_UI_EXPERIMENTAL`; CLI (`horc`) remains canonical.
- Node discovery pulls from `/local/agents/registry.json`, `/local/agents/envs/*.env`, and `/local/agents/nodes/*`.
- Guard summaries are read from `/local/logs/guard/`.
- Agent timelines are read from `/local/logs/nodes/activities/<node>.jsonl`.
- When auth is enabled, SSE clients can pass `/api/fleet/stream?token=<WASM_UI_API_TOKEN>` because browser `EventSource` cannot set custom headers.
