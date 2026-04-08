# hermes-orchestrator

Hermes Orchestrator is the host control plane for running one orchestrator node plus many containerized Hermes worker nodes.
Node env conventions and defaults are documented in [`agents/READ.me`](agents/READ.me) and [`agents/README.md`](agents/README.md).

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Magaav/hermes-orchestrator/main/scripts/install.sh | bash
```

Optional flags:

```bash
curl -fsSL https://raw.githubusercontent.com/Magaav/hermes-orchestrator/main/scripts/install.sh | bash -s -- --dir /local --branch main
```

What install does:
- Clones or updates this repo in `/local`
- Installs `horc` and `hord` wrappers
- Enables repo git hooks (`.githooks`) to block common secret leaks

## Goals

- Keep orchestrator state in `/local/agents/nodes/orchestrator/.hermes`
- Keep runtime topology deterministic under `/local/agents/nodes/*`
- Spawn and manage worker nodes on demand with shared host assets
- Expose orchestration through shell (`horc`) and Discord-triggered workflows

## Topology

```text
/local/
├── agents/
│   ├── registry.json
│   ├── envs/
│   │   ├── orchestrator.env
│   │   ├── catatau.env
│   │   ├── colmeio.env
│   │   ├── node.env.example
│   │   └── ...
│   └── nodes/
│       ├── orchestrator/
│       │   ├── workspace/
│       │   │   ├── data/
│       │   │   └── discord/
│       │   ├── hermes-agent -> /local/hermes-agent
│       │   ├── .hermes/
│       │   ├── scripts -> /local/scripts
│       │   ├── crons -> /local/crons/orchestrator
│       │   └── plugins -> /local/plugins
│       ├── node1/
│       │   ├── workspace/
│       │   │   ├── data/
│       │   │   └── discord/
│       │   ├── hermes-agent/
│       │   ├── .hermes/
│       │   ├── scripts/   # mounted from host (ro)
│       │   ├── crons/     # mounted from host node bucket
│       │   └── plugins/   # mounted from host (ro)
│       └── ...
├── hermes-agent/
├── scripts/
├── plugins/
│   ├── memory/
│   │   ├── openviking/
│   │   ├── vectordb/
│   │   └── viking/
│   └── discord/
├── memory/
│   └── -> /local/plugins/memory (compatibility symlink)
├── backups/
├── crons/
└── logs/
```

## Bootstrap

```bash
horc start
```

Default `horc start` target is `orchestrator` and it reads:
- `/local/agents/envs/orchestrator.env`
- `/local/agents/nodes/orchestrator/`

On first bootstrap:
- Legacy state migrates to `/local/agents/nodes/orchestrator/.hermes` (prefers `~/.hermes`, fallback `/local/.hermes`)
- If `/local/hermes-agent` is missing, it is cloned automatically
- If `/local/.venv` runtime is missing, dependencies are bootstrapped automatically

## Node Lifecycle

```bash
# orchestrator
horc start
horc status
horc restart
horc logs --lines 120

# workers
horc start catatau
horc status catatau
horc restart catatau
horc stop catatau
horc delete catatau
```

## Backups & Restore

```bash
# backup one node
horc backup node colmeio

# backup all nodes
horc backup all

# restore from a backup archive
horc restore /local/backups/horc-backup-node-colmeio-YYYYMMDDTHHMMSSZ.tar.gz
```

Restore behavior:
- If you pass a relative path, `horc restore` resolves it under `/local/backups/`
- `backup node <name>` captures that node env/root plus node-scoped `plugins/memory/{openviking,viking}/<name>` and `crons/<name>`
- `backup all` captures all envs/nodes plus full shared `plugins/memory/*` and `crons/*`
- Restore reapplies whatever is present in the archive (`agents/*`, memory paths, and crons paths)
- Stops included running nodes before restore and restarts those that were running

## Updates

```bash
# update hermes-orchestrator repo itself (/local)
horc update

# update hermes-agent template source (/local/hermes-agent)
horc agent update

# update one existing node to latest template and restart it if running
horc agent update catatau

# refresh orchestrator runtime copy from template and restart host gateway if running
horc agent update orchestrator
```

Compatibility alias:

```bash
hord restart
```

`horc update <node>` is accepted as a compatibility alias for `horc agent update <node>`.

## Credential Model

- API keys and Discord bot tokens belong in `agents/envs/*.env` (local only, never committed)
- Codex OAuth (`openai-codex`) is runtime auth state in each node’s `.hermes/auth.json` and must be re-login rotated, not committed in env templates

Rotate Codex OAuth for a node by running Hermes login/logout in that node context:
- Orchestrator (host): `HERMES_HOME=/local/agents/nodes/orchestrator/.hermes /local/hermes-agent/.venv/bin/python /local/hermes-agent/cli.py login`
- Worker: `docker exec -it hermes-node-<name> bash -lc 'cd /local/hermes-agent && /local/hermes-agent/.venv/bin/python /local/hermes-agent/cli.py login'`

## Versioning Hygiene

Runtime and secret files are intentionally excluded:
- `.hermes/`, `agents/nodes/`, `logs/`, `plugins/memory/`, `memory/`, `backups/`, `crons/`, `workspace/`, `spawns/`
- Real env files: `agents/envs/*.env`, `docker/.env`, `hermes-agent/.env`, root `.env`
- Orchestrator prestart patching runs against `agents/nodes/orchestrator/.runtime/hermes-agent` (node-local runtime copy), so tracked `/local/hermes-agent/*` source files stay clean.

Commit only templates:
- `agents/envs/node.env.example`
- `agents/README.md`

Pre-commit hook (`.githooks/pre-commit`) blocks common leaked paths and token patterns before commit.

## Road Map

### UI (Hermes Workspace-style Interface)

A lightweight web UI is planned as an optional visual layer inspired by Hermes Workspace, but independent from Hermes runtime internals.

Scope:
- node lifecycle management
- tenant and environment overview
- task execution monitoring
- orchestration logs and event streams
- shared wiki navigation and editing
- health and heartbeat dashboards

```text
UI
  ├─ Fleet overview
  ├─ Node management
  ├─ Task monitoring
  ├─ Logs & events
  └─ Shared wiki
```

The orchestrator remains fully operable via CLI and automation pipelines even without the UI.

## Why Use Hermes Orchestrator

Hermes Agent is excellent at reasoning and tool use inside a single runtime.
Hermes Orchestrator solves a different layer: operating many Hermes nodes safely and reliably.

Hermes Agent focuses on:
- reasoning
- memory
- tool execution

Hermes Orchestrator focuses on:
- node lifecycle and fleet management
- environment and tenant isolation
- upgrades, rollbacks, and operational guardrails
- logs, auditability, and policy boundaries

This separation gives teams scale and operational clarity without modifying Hermes Agent itself.

## Branch Policy

- Long-lived branch: `main` only
- Do not use `master`
- Work branches should use your orchestrator id format: `<horc-id>`
