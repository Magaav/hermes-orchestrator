# Hermes Orchestrator
> Host-level control plane for running and managing fleets of containerized Hermes Agent nodes.
![Hermes Orchestrator Hero](docs/assets/hero.png)
**Quick Links:** [Install](#install) | [Core Concepts](#core-concepts) | [Node Lifecycle](#node-lifecycle) | [Logging Topology](#logging-topology) | [Roadmap Workspace](#roadmap-workspace) | [Contributing](#contributing)

Hermes Orchestrator is a lightweight host-level operational layer for running Hermes agents at scale: spawning isolated nodes, managing environments, handling upgrades/rollbacks, centralizing logs, and coordinating multi-agent workflows.

Hermes Agent focuses on reasoning and tool execution inside a single runtime.
Hermes Orchestrator focuses on operating many Hermes runtimes safely and reliably.

Together they form a scalable architecture for AI-driven automation systems, multi-tenant agent deployments, and autonomous infrastructure operations.

## Why Hermes Orchestrator Exists

Hermes Agent is extremely capable within a single runtime:
- reasoning
- memory
- tool usage
- autonomous task execution

Production deployments often require many agents running concurrently, each with different environments, policies, or tenants.

Hermes Orchestrator provides the missing operational layer:
- fleet management
- node lifecycle control
- environment isolation
- upgrade and rollback safety
- centralized observability
- orchestration of multi-agent systems

The orchestrator allows Hermes agents to operate as a coordinated distributed system without modifying Hermes core internals.

## Key Capabilities

- **Agent Fleet Management:** spawn Hermes nodes on demand; start, stop, restart, and delete nodes; isolate environments per tenant/project.
- **Operational Safety:** upgrade agents safely; rollback node environments; maintain node-local runtime copies.
- **Observability:** centralized logging; attention-level warning mirrors; skill execution tracing.
- **Infrastructure Automation:** shared scripts/plugins; centralized cron orchestration; automated maintenance workflows.
- **Multi-Agent Systems:** orchestrate multiple Hermes runtimes; enable cooperation patterns; maintain operational boundaries.

## Install

Install the orchestrator:

```bash
curl -fsSL https://raw.githubusercontent.com/Magaav/hermes-orchestrator/main/scripts/install.sh | bash
```

Optional install parameters:

```bash
curl -fsSL https://raw.githubusercontent.com/Magaav/hermes-orchestrator/main/scripts/install.sh | bash -s -- --dir /local --branch main
```

What install does:
- Clones or updates this repo in `/local`
- Installs `horc` shell command wrappers
- Enables repo git hooks (`.githooks`) to block common secret leaks

## Core Concepts

Hermes Orchestrator operates with two primary node types.

### Orchestrator Node

The orchestrator runs on the host machine and is responsible for:
- managing worker nodes
- coordinating updates and backups
- maintaining centralized logs
- executing automation scripts
- enforcing node runtime contract-role (node self-conscience)

### Worker Nodes

Worker nodes are containerized Hermes Agent instances.

Each node runs in an isolated environment and can represent:
- a tenant
- a task executor
- a specialized agent
- a service automation worker

Nodes maintain their own runtime copies of Hermes Agent to avoid corruption of shared templates.

### Node Governance Contract

Every node receives a runtime contract on start/restart:
- `/local/.hermes/NODE_RUNTIME_CONTRACT.md`
- `/local/workspace/NODE_RUNTIME_CONTRACT.md`

This contract defines:
- node role (`orchestrator` vs `worker`)
- bootstrap mode (`NODE_STATE`)
- shared framework ownership (`/local/plugins`, `/local/scripts`)
- collaboration protocol for plugin/framework changes

Operational rule:
- Worker nodes should treat shared plugins/scripts as orchestrator-managed infrastructure.
- Workers should propose changes (diff + rollout/rollback + verification), then request orchestrator execution.
- Orchestrator applies approved shared changes and coordinates restarts/verification.

At runtime, a condensed governance prompt is also injected via `HERMES_EPHEMERAL_SYSTEM_PROMPT` so agent decisions stay aligned with this contract.

## Filesystem Topology

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
├── state/        # deployment-specific orchestrator state (local-first)
│   └── orchestrator/
│       ├── backup_nodes_to_gdrive.env.example
│       └── backup_nodes_to_gdrive.env # local runtime config (not tracked)
├── backups/ # used for rollback/versioning
├── crons/   # nodes centralized cronjobs
└── logs/    # nodes centralized debugging interface
    ├── nodes/
    │   ├── orchestrator/
    │   │   ├── management.log
    │   │   ├── runtime.log
    │   │   ├── skills/ # per-node skill log mirrors (for example: node-*.log)
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

Important characteristics:
- node-local runtime copies prevent template corruption
- shared scripts/plugins enable coordinated automation
- state folder isolates deployment-specific assumptions from reusable framework code
- centralized logs simplify debugging and monitoring

## Public vs Local State

- `/local/scripts` and `/local/plugins` are the reusable/public framework surface.
- `/local/state` is for orchestrator-local values and implementation assumptions.

## Bootstrap

```bash
horc start
```

Default `horc start` target is `orchestrator` and it reads:
- `/local/agents/envs/orchestrator.env` (auto-created from `agents/envs/orchestrator.env.example` if missing)
- `/local/agents/nodes/orchestrator/`

Node env conventions and defaults are documented in [`agents/README.md`](agents/README.md).

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
- `horc logs <node>` tails management, runtime, attention, and Hermes logs from this canonical tree.

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
- `.hermes/`, `agents/nodes/`, `logs/`, `plugins/memory/`, `backups/`, `crons/`, `state/` (except docs/examples)
- Real env files: `agents/envs/*.env`, `docker/.env`, `hermes-agent/.env`, root `.env`
- Orchestrator prestart patching runs against `agents/nodes/orchestrator/hermes-agent` (node-local runtime copy), so tracked `/local/hermes-agent/*` source files stay clean.

Commit only templates:
- `agents/envs/node.env.example`
- `agents/envs/orchestrator.env.example`
- `agents/README.md`
- `state/orchestrator/backup_nodes_to_gdrive.env.example`
- `state/README.md`

Pre-commit hook (`.githooks/pre-commit`) blocks common leaked paths and token patterns before commit.

## Roadmap

Roadmap work is intentionally tracked in dedicated docs to keep this README operational and implementation-focused.

Current roadmap themes:
- Visual control plane and high-performance observability exploration.
- Runtime guard monitoring, alert routing, and bounded remediation.
- Shared knowledge and collaboration workflows for larger multi-node operations.

## Roadmap Workspace

- [Roadmap Index](docs/roadmap/README.md)
- [WASM UI Track](docs/roadmap/wasm-ui/README.md)
- [Guard Track](docs/roadmap/guard/README.md)

## Long-Term Vision

Hermes Agent provides the intelligence inside a runtime.

Hermes Orchestrator coordinates many runtimes to form a scalable autonomous system.

## Branch Policy

- Long-lived branch: `main` only (do not use `master`)
- Work branches should use your orchestrator id format: `<horc-id>`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
