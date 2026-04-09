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

## Topology

```text
/local/
├── agents/
│   ├── registry.json
│   ├── envs/
│   │   ├── orchestrator.env # runs inside host VM
│   │   ├── node1.env        # runs inside docker container (sandboxed)
│   │   ├── node2.env        # runs inside docker container (sandboxed)
│   │   └── ...
│   └── nodes/
│       ├── orchestrator/
│       │   ├── workspace/
│       │   ├── data/
│       │   ├── hermes-agent/ # node-local runtime copy (not symlinked to /local/hermes-agent)
│       │   ├── .hermes/
│       │   ├── scripts ->(symlink) /local/scripts
│       │   ├── crons   ->(symlink) /local/crons/orchestrator
│       │   └── plugins ->(symlink) /local/plugins
│       ├── node1/
│       │   ├── workspace/
│       │   ├── data/
│       │   ├── hermes-agent/
│       │   ├── .hermes/
│       │   ├── scripts/   # mounted from host (ro)
│       │   ├── crons/     # mounted from host node bucket
│       │   └── plugins/   # mounted from host (ro)
│       └── ...
├── hermes-agent/ # hermes-agent version used for spawning new nodes
├── scripts/      # triggered directly from discord native slash command/cronjobs/etc...
├── plugins/      # used to modify hermes-agent core on node start
│   ├── memory/   # optional setted in /agents/envs/<node>.env
│   │   ├── openviking/
│   │   ├── vectordb/
│   │   └── viking/
│   └── discord/
├── backups/ # used for rollback/versioning
├── crons/   # nodes centralized cronjobs
└── logs/    # nodes centralized debugging interface
    ├── nodes/
    │   ├── orchestrator/
    │   │   ├── management.log
    │   │   ├── runtime.log
    │   │   ├── skills/ # per-node skill log mirrors (for example: colmeio-*.log)
    │   │   └── hermes/
    │   │       ├── agent.log
    │   │       ├── errors.log
    │   │       └── gateway.log
    │   └── <node>/...
    └── attention/
        └── nodes/
            └── <node>/
                ├── warning-plus.log
                └── hermes-errors.log # hardlinked mirror of /local/logs/nodes/<node>/hermes/errors.log
```

## Bootstrap

```bash
horc start
```

Default `horc start` target is `orchestrator` and it reads:
- `/local/agents/envs/orchestrator.env`
- `/local/agents/nodes/orchestrator/`

## Node Lifecycle

```bash
# orchestrator
horc start
horc status
horc restart
horc logs --lines 120
horc logs clean

# workers
horc start node2
horc status node2
horc restart node2
horc logs clean node2
horc stop node2
horc delete node2
```

## Logging Topology

- Node management/runtime/Hermes logs are centralized at `/local/logs/nodes/<node>/`.
- Node skill mirrors are centralized at `/local/logs/nodes/<node>/skills/`.
- Warning-and-above mirrors are centralized at `/local/logs/attention/nodes/<node>/`.
- Legacy compatibility roots `/local/logs/agents`, `/local/logs/clones`, and `/local/logs/skills` are removed.
- `horc logs <node>` now tails management, runtime, attention, and Hermes logs from this canonical tree.

## Backups & Restore

```bash
# backup one node
horc backup node node1

# backup all nodes
horc backup all

# restore from a backup archive
horc restore /local/backups/horc-backup-node-node1-YYYYMMDDTHHMMSSZ.tar.gz
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
horc agent update node2

# refresh orchestrator runtime copy from template and restart host gateway if running
horc agent update orchestrator
```

Compatibility alias:

```bash
hord restart
```

`horc update <node>` is accepted as a compatibility alias for `horc agent update <node>`.

## Versioning Hygiene

Runtime and secret files are intentionally excluded:
- `.hermes/`, `agents/nodes/`, `logs/`, `plugins/memory/`, `backups/`, `crons/`
- Real env files: `agents/envs/*.env`, `docker/.env`, `hermes-agent/.env`, root `.env`
- Orchestrator prestart patching runs against `agents/nodes/orchestrator/hermes-agent` (node-local runtime copy), so tracked `/local/hermes-agent/*` source files stay clean.

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

Hermes Orchestrator layer can:
- Spawn sandboxed hermes-agents nodes on demand for various corporations/especificities.
- Doctor, fix, operate each others core code easily in case of fail or hard to debug problems and instanteneously up that node again.
- Enable any node exchange communication so they can self evolve easily.
- Orchestrate complex workflows
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

- Long-lived branch: `main` only (do not use `master`)
- Work branches should use your orchestrator id format: `<horc-id>`