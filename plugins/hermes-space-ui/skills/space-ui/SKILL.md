# Space UI

Use this skill when Hermes needs a visual fleet dashboard, node health cards,
log panels, or safe control actions rendered through Space Agent.

## Purpose

Space Agent owns the mutable visual workspace. Hermes Agent owns reasoning,
tools, memory, skills, and execution. Hermes Orchestrator owns node lifecycle,
routing, isolation, policy, logs, upgrades, and rollback.

`hermes-space-ui` is the bridge between Space Agent UI actions and Hermes
Orchestrator operations. Treat it as a control-plane adapter, not as a place to
run arbitrary commands.

Space Agent should follow the upstream project at:

```text
https://github.com/agent0ai/space-agent
```

Use that repository as the reference for Space Agent conventions, workspace
shape, and future embedded-dashboard integration.

## When To Use

- The user asks for a dashboard or visual status view of a Hermes fleet.
- The user wants host VM CPU, memory, disk, process, uptime, or load metrics.
- The user wants node health, lifecycle state, or logs shown in Space Agent.
- The user asks Space Agent to start, stop, or restart a Hermes node.
- The user wants UI buttons for safe node actions.

## How To Request A Dashboard

Call the bridge:

```http
GET /nodes
GET /resources
GET /capabilities
GET /nodes/{node_id}/stats?bucket=daily&days=30
POST /nodes
POST /nodes/{node_id}/action
```

Use `open_dashboard` when Space Agent needs a complete dashboard layout:

```json
{
  "action": "open_dashboard",
  "payload": {}
}
```

Render `hermes.space_ui.dashboard_layout.v1`, `node_card.v1`, and
`logs_panel.v1` payloads directly in the Space Agent workspace.

## Node Health

Use `GET /nodes` for fleet cards and `GET /nodes/{node_id}` for one node. The
node card includes:

- runtime type and state mode
- running status
- env and clone-root paths
- log paths
- allowlisted action buttons

Use `GET /nodes/{node_id}/logs?lines=120` or the `tail_logs` action for a log
panel. Prefer summaries and visual status indicators over dumping long logs.

## Host Resources

Use `GET /resources` for the Resources Monitor widget. It returns
`hermes.space_ui.host_resources.v1` from the bridge host VM, which is the
Hermes Orchestrator host in the local deployment.

## Safety Rules

- Never request raw shell execution through Space Agent.
- Never ask this plugin to patch Hermes Agent core.
- Use only allowlisted actions:
  - `inspect_node`
  - `tail_logs`
  - `restart_node`
  - `stop_node`
  - `start_node`
  - `run_prompt`
  - `open_dashboard`
- Unknown actions must be rejected.
- Lifecycle actions must route through Hermes Orchestrator, currently `horc`.
- Prompt submission must route through the official Hermes API server Runs API
  instead of bypassing the control plane.

## Current Task Submission Boundary

`run_prompt` and `POST /task` use the target node's official API server:

- `GET /v1/capabilities`
- `POST /v1/runs`
- `GET /v1/runs/{run_id}`

Do not work around this by importing Hermes Agent internals or writing directly
to gateway state.
