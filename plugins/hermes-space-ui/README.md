# hermes-space-ui

`hermes-space-ui` is an external Hermes plugin that lets Space Agent act as the
mutable visual UI and control-plane surface for Hermes Orchestrator fleets.

Space Agent upstream reference:
<https://github.com/agent0ai/space-agent>

It keeps the responsibilities split cleanly:

- Space Agent owns the visual interface and mutable workspace.
- Hermes Agent owns reasoning, tools, memory, skills, and execution.
- Hermes Orchestrator owns node lifecycle, routing, isolation, policy, logs,
  upgrades, and rollback.
- This plugin translates Space Agent UI actions into safe Hermes Orchestrator
  operations.

## Why This Exists

Space Agent should not be merged into Hermes Agent core. A UI layer changes
quickly, carries user-specific workspace state, and needs deployment-specific
presentation contracts. Hermes Agent core should stay focused on reasoning and
tool execution so it can be upgraded safely.

By keeping Space Agent integration in an external plugin:

- Hermes Agent can update without carrying UI patches.
- UI behavior can iterate independently.
- Fleet controls stay routed through Hermes Orchestrator.
- Unsafe direct execution is avoided.
- Missing extension points can be requested upstream instead of hacked around.

## Architecture

```text
Space Agent UI
  -> hermes-space-ui bridge
  -> Hermes Orchestrator CLI/API boundary
  -> Hermes Agent nodes
```

MVP integration uses the stable `horc` CLI wrapper at
`/local/scripts/public/clone/horc.sh` for node status, logs, and lifecycle
actions. The bridge never imports Hermes Agent core modules and never patches
`/local/hermes-agent`.

Space Agent customizations are packaged through `plugin-interface/` as
Customware Bundle Interface source. That keeps Hermes-specific UI behavior in
this plugin while upstream Space Agent only needs generic seams such as bundle
manifests, extension points, action registration, and bridge-state sync.

## File Layout

```text
/local/plugins/hermes-space-ui/
  AGENTS.md
  README.md
  plugin.yaml
  plugin-interface/
    AGENTS.md
    README.md
    bridge.js
    plugins/
      AGENTS.md
      component-context-menu/
        AGENTS.md
        README.md
        component-menu.js
        component-menu.css
        space.bundle.yaml
      hermes-fleet/
        AGENTS.md
        README.md
        space.bundle.yaml
  server/
    __init__.py
    auth.py
    bridge.py
    routes.py
    schemas.py
  skills/
    space-ui/SKILL.md
  scripts/
    start_space_ui.sh
    stop_space_ui.sh
    doctor.sh
  examples/
    dashboard_payload.json
    node_action_payload.json
```

## Setup

Preferred local VM/tunnel workflow:

```bash
horc space start
```

This starts the actual Space Agent PWA at:

```text
http://127.0.0.1:8787
```

It also starts the Hermes bridge privately on the VM at:

```text
http://127.0.0.1:8790
```

`horc space start` is intended for SSH-tunneled browser access from Windows. It
frees port `8787`, starts Space Agent in `SINGLE_USER_APP=true`, seeds a Hermes
Fleet space/widget into Space Agent customware, seeds Space Agent's admin and
onscreen agents to call OpenRouter directly by default, starts the Hermes bridge
without requiring `HERMES_SPACE_UI_TOKEN`, and prints the tunnel target.

Legacy state under `/local/plugins/private/hermes-space-ui` is deprecated with
a hard error. Startup/status/stop commands will refuse to run until that legacy
directory is migrated or deleted.

Check it:

```bash
curl http://127.0.0.1:8787/api/health
curl http://127.0.0.1:8790/health
curl http://127.0.0.1:8790/nodes
```

Open the seeded Hermes OS space through the SSH tunnel:

```text
http://127.0.0.1:8787/#/spaces?id=hermes-os
```

Stop it:

```bash
horc space stop
```

Status:

```bash
horc space status
```

Manual token-protected startup:

Start the bridge from the orchestrator host:

```bash
export HERMES_SPACE_UI_TOKEN='choose-a-local-token'
/local/plugins/hermes-space-ui/scripts/start_space_ui.sh
```

Default URL:

```text
http://127.0.0.1:8790
```

Stop it:

```bash
/local/plugins/hermes-space-ui/scripts/stop_space_ui.sh
```

Run checks:

```bash
/local/plugins/hermes-space-ui/scripts/doctor.sh
```

## Environment

- `HERMES_SPACE_UI_TOKEN`: bearer token for bridge requests.
- `HERMES_SPACE_UI_HOST`: bind host, default `127.0.0.1`.
- `HERMES_SPACE_UI_PORT`: bind port, default `8790`.
- `HERMES_SPACE_AGENT_PORT`: Space Agent PWA port for `horc space start`,
  default `8787`.
- `HERMES_SPACE_UI_BRIDGE_PORT`: VM-local bridge port behind Space Agent,
  default `8790`.
- `SPACE_AGENT_DIR`: Space Agent checkout directory, default
  `/local/plugins/hermes-space-ui/state/space-agent`.
- `SPACE_AGENT_CUSTOMWARE_PATH`: Space Agent writable customware root, default
  `/local/plugins/hermes-space-ui/state/space-customware`.
- `HERMES_SPACE_UI_HORC`: orchestrator CLI path, default
  `/local/scripts/public/clone/horc.sh`.
- `HERMES_SPACE_UI_STATE_DIR`: task/status state, default
  `/local/plugins/hermes-space-ui/state`.
- `HERMES_SPACE_UI_TIMEOUT_SEC`: `horc` timeout, default `120`.
- `HERMES_SPACE_UI_API_SERVER_URL`: default Hermes API server URL for prompt
  submission, inferred from node env when unset.
- `HERMES_SPACE_UI_API_SERVER_<NODE>_URL`: node-specific API server URL, for
  example `HERMES_SPACE_UI_API_SERVER_ORCHESTRATOR_URL`.
- `HERMES_SPACE_UI_API_SERVER_KEY`: optional bearer token for the Hermes API
  server. Node-specific `..._<NODE>_KEY` overrides are also supported.
- `HERMES_SPACE_UI_API_SERVER_TIMEOUT_SEC`: max wait for Hermes Runs API tasks,
  default `900`.
- `HERMES_SPACE_UI_PID_FILE`: optional pid file override.
- `HERMES_SPACE_UI_LOG_FILE`: optional bridge log override.
- `SPACE_AGENT_URL`: optional doctor probe target.
- `SPACE_AGENT_REPO`: Space Agent upstream reference, default
  `https://github.com/agent0ai/space-agent`.
- `HERMES_SPACE_LLM_MODE`: LLM seed mode for Space Agent, default `openrouter`.
  Set to `hermes` only when you explicitly want requests proxied through the
  Hermes bridge.
- `HERMES_SPACE_LLM_ENDPOINT`: default
  `https://openrouter.ai/api/v1/chat/completions` in `openrouter` mode.
- `HERMES_SPACE_LLM_MODEL`: optional model override for both seeded Space Agent
  chats.
- `HERMES_SPACE_ADMIN_LLM_MODEL`: default `openai/gpt-5.4-mini` in
  `openrouter` mode.
- `HERMES_SPACE_ONSCREEN_LLM_MODEL`: default `anthropic/claude-sonnet-4.6` in
  `openrouter` mode.
- `HERMES_SPACE_LLM_MAX_TOKENS`: default `120000`.
- `HERMES_SPACE_LLM_PARAMS_TEXT`: default `temperature:0.2` in `openrouter`
  mode.
- `HERMES_SPACE_LLM_API_KEY`: API key written into seeded Space Agent LLM
  config. When unset, startup reads `OPENROUTER_API_KEY` from
  `/local/agents/envs/orchestrator.env`.
- `HERMES_SPACE_SEED_FORCE`: set to `1` to rewrite seeded Space Agent config
  even when files already exist.
- `HERMES_SPACE_UI_DROP_TO_COPY_NODE`: node that receives Drop to Copy runs,
  default `orchestrator`.
- `HERMES_SPACE_UI_DROP_TO_COPY_PROVIDER`: requested frontier provider for
  Drop to Copy runs, default `openai-codex`.
- `HERMES_SPACE_UI_DROP_TO_COPY_MODEL`: requested frontier model for Drop to
  Copy runs, default `gpt-5.5`.
- `HERMES_SPACE_UI_DROP_TO_COPY_REASONING_EFFORT`: requested reasoning effort,
  default `xhigh`.

## Auth

When `HERMES_SPACE_UI_TOKEN` is set, send either:

```http
Authorization: Bearer <token>
```

or:

```http
X-Hermes-Space-Ui-Token: <token>
```

`GET /health` remains unauthenticated so local process monitors and doctor can
probe the bridge without exposing fleet actions.

## Endpoints

- `GET /health`
- `GET /nodes`
- `GET /nodes/{node_id}`
- `GET /nodes/{node_id}/logs?lines=80`
- `GET /nodes/{node_id}/stats?bucket=daily&days=30`
- `GET /resources`
- `GET /tasks`
- `GET /tasks/{task_id}`
- `POST /nodes`
- `POST /nodes/{node_id}/action`
- `POST /nodes/{node_id}/prompt`
- `POST /task`
- `POST /tasks`
- `POST /tasks/{task_id}/stop`
- `POST /drop-to-copy/tasks`
- `GET /capabilities`

`POST /nodes/{node_id}/prompt`, `POST /task`, and `POST /tasks` accept
`"async": true` or `"stream_events": true` to return a running task
immediately. The bridge follows the Hermes Runs API event stream and copies
reasoning/tool/message progress into `GET /tasks/{task_id}` for Space widgets.
`POST /tasks/{task_id}/stop` asks the target node's Runs API to stop the
underlying run and marks the Space UI task as cancelled.

For node chat parity with Discord, the bridge also recognizes `/exhaust`,
`/exaust`, and `/bruteforce` at the start of a submitted prompt. When the target
node has `PLUGINS_EXHAUST=true`, the bridge rewrites the turn through the
Exhaust plugin activation contract before sending it to the Hermes Runs API.

Widget compatibility:

- `GET|POST /api/*` is accepted as an alias for the same bridge path without
  `/api`, so generated widgets that accidentally use app-style paths still
  reach the bridge.

Example:

```bash
curl -H "Authorization: Bearer ${HERMES_SPACE_UI_TOKEN}" \
  http://127.0.0.1:8790/nodes
```

Node action:

```bash
curl -X POST \
  -H "Authorization: Bearer ${HERMES_SPACE_UI_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"action":"tail_logs","payload":{"lines":120}}' \
  http://127.0.0.1:8790/nodes/orchestrator/action
```

## UI Payload Contracts

The bridge returns render-friendly JSON payloads:

- `hermes.space_ui.node_card.v1`
- `hermes.space_ui.logs_panel.v1`
- `hermes.space_ui.action_result.v1`
- `hermes.space_ui.task_status.v1`
- `hermes.space_ui.dashboard_layout.v1`
- `hermes.space_ui.host_resources.v1`
- `hermes.space_ui.node_stats.v1`
- `hermes.space_ui.node_create_result.v1`

`GET /capabilities` includes JSON Schemas for the UI-facing contracts.

## Safety Rules

- No raw shell execution endpoint exists.
- Unknown actions are rejected.
- All node lifecycle actions route through `horc`.
- The plugin does not import or patch Hermes Agent internals.
- `restart_node`, `stop_node`, and `start_node` are explicit allowlisted
  lifecycle actions.
- `run_prompt` routes through the official Hermes API server Runs API on the
  target node.

Allowlisted actions:

- `inspect_node`
- `tail_logs`
- `restart_node`
- `stop_node`
- `start_node`
- `run_prompt`
- `open_dashboard`

## MVP Limitations

- No websocket or SSE log streaming yet.
- Task submission requires the target node's official Hermes API server to be
  reachable from the bridge.
- `horc space start` clones and runs upstream Space Agent, then seeds one Hermes
  Fleet space/widget. Richer native Space Agent customware can grow from there.
- Auth is a single shared token, not per-user or per-tenant.
- No policy-engine integration beyond the fixed allowlist.
- Rollback-aware action planning is documented as future work.

## Task Submission Boundary

`POST /task`, `POST /nodes/{node_id}/prompt`, and the `run_prompt` action route
through the official Hermes API server Runs API:

```text
GET /v1/capabilities
POST /v1/runs
GET /v1/runs/{run_id}
```

The bridge does not import Hermes Agent internals or write directly into gateway
state. Configure node-specific API URLs with
`HERMES_SPACE_UI_API_SERVER_<NODE>_URL` when the bridge cannot infer the target
from the node env.

## Roadmap

- Live websocket log streaming.
- Space Agent embedded dashboard.
- Discord command bridge.
- Per-tenant UI spaces.
- Policy engine integration.
- Rollback-aware node actions.
- Plugin marketplace compatibility.
