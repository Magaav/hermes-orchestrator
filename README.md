# Hermes Orchestrator
> Host-level control plane for running and managing fleets of containerized Hermes Agent nodes.
![Hermes Orchestrator Hero](docs/assets/hero.png)
**Quick Links:** [Install](#install) | [Core Concepts](#core-concepts) | [Node Lifecycle](#node-lifecycle) | [Logging Topology](#logging-topology) | [Feature Docs](#feature-docs) | [Command Reference](docs/commands/horc.md) | [Roadmap Workspace](#roadmap-workspace) | [Contributing](#contributing)

A control plane for managing fleets of Hermes agents across infrastructure.

                ┌───────────────────┐
                │ Hermes Workspace  │
                │  (UI / Discord)   │
                └─────────┬─────────┘
                          │
                ┌─────────▼───────────┐
                │ Hermes Orchestrator │
                │(Fleet Control Plane)│
                └─────────┬───────────┘
                          │
        ┌────────────┬────────────┬────────────┐
        │ Agent Node │ Agent Node │ Agent Node │
        │   Sales    │   DevOps   │  Research  │
        └────────────┴────────────┴────────────┘

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

- **Fleet management of Hermes agents:** spawn Hermes nodes on demand; start, stop, restart, and delete nodes; isolate environments per tenant/project.
- **Node isolation:** each agent runs in its own environment with dedicated configuration and resources.
- **Shared host capabilities:** expose common scripts, tools, and host-level assets to all nodes.
- **Plugin propagation:** distribute and update plugins consistently across the entire fleet.
- **Fleet-wide upgrades:** perform coordinated upgrades and rollbacks across nodes.
- **Observability & logs:** centralized metrics, logs, and health monitoring for all agents.
- **Policy enforcement:** enforce operational rules and guardrails across the fleet.
- **Secrets management:** securely manage environment variables, credentials, and per-node secrets.

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
- `/local/agents/nodes/<node>/workspace/NODE_RUNTIME_CONTRACT.md` (node-local convenience mirror)

This contract defines:
- node role (`orchestrator` vs `worker`)
- bootstrap mode (`NODE_STATE`)
- shared framework ownership (`/local/plugins/public`, `/local/scripts/public`)
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
│       │   ├── wiki -> /local/plugins/private/wiki
│       │   ├── workspace/
│       │   ├── data/
│       │   ├── hermes-agent/ # node-local runtime copy (not symlinked to /local/hermes-agent)
│       │   ├── .hermes/
│       │   ├── scripts ->(symlink) /local/scripts
│       │   ├── cron    ->(symlink) /local/crons/orchestrator
│       │   └── plugins ->(symlink) /local/plugins
│       ├── node1/
│       │   ├── wiki/          # mounted from /local/plugins/private/wiki when NODE_WIKI_ENABLED=true
│       │   ├── workspace/
│       │   ├── data/
│       │   ├── hermes-agent/
│       │   ├── .hermes/
│       │   ├── scripts/public/  # mounted from /local/scripts/public (ro)
│       │   ├── scripts/private/ # mounted from /local/scripts/private (rw)
│       │   ├── plugins/public/   # mounted from /local/plugins/public (ro)
│       │   ├── plugins/private/  # mounted from /local/plugins/private (rw)
│       │   └── cron/     # mounted from /local/crons/<node>
│       └── ...
├── hermes-agent/ # hermes-agent version used for spawning new nodes
├── scripts/
│   ├── public/       # canonical git-tracked script code
│   └── private/      # canonical local-only script state/entrypoints
├── crons/            # canonical node cron roots mounted at /local/agents/nodes/<node>/cron
├── plugins/
│   ├── public/       # canonical git-tracked plugin code
│   └── private/      # canonical local-only plugin runtime/config
├── skills/           # canonical shared mutable skills pool
├── backups/ # used for rollback/versioning
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
- shared public scripts/plugins enable coordinated automation
- private roots isolate deployment state (wiki, crons, memory, skills)
- state folder isolates deployment-specific assumptions from reusable framework code
- centralized logs simplify debugging and monitoring

## Public vs Local State

- `/local/scripts/public` and `/local/plugins/public` are the reusable/public framework surface.
- `/local/scripts/private` and `/local/plugins/private` are deployment-local script/plugin state surfaces.
- `/local/crons` is the canonical cron runtime root consumed by every node via `/local/agents/nodes/<node>/cron`.
- `/local/crons/orchestrator/backup_daily_brt.sh` is the default orchestrator backup+retention cron payload.
- `/local/skills` is the shared mutable skills pool mounted across nodes.
- `/local/state` is for orchestrator-local values and implementation assumptions.

## Feature Docs

- [Scripts Feature Guide](docs/features/scripts.md)
- [Plugins Feature Guide](docs/features/plugins.md)
- [horc Command Reference](docs/commands/horc.md)

## Bootstrap

```bash
horc start
```

See more: [horc command reference](docs/commands/horc.md)

Default `horc start` target is `orchestrator` and it reads:
- `/local/agents/envs/orchestrator.env` (auto-created from `agents/envs/orchestrator.env.example` if missing)
- `/local/agents/nodes/orchestrator/`
- `NODE_TIME_ZONE` from each node env is mapped to runtime `HERMES_TIMEZONE` (for cron/schedule alignment)

Node env conventions and defaults are documented in [`agents/README.md`](agents/README.md).

## Node Lifecycle

```bash
# control plane + fleet
horc start
horc status
horc restart
horc restart orchestrator
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

See more: [horc command reference](docs/commands/horc.md)

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

See more: [horc command reference](docs/commands/horc.md)

Restore behavior:
- If you pass a relative path, `horc restore` resolves it under `/local/backups/`
- `backup node <name>` captures node env/root plus private orchestrator state (including `plugins/private`, `scripts/private`, `/local/crons`, and `/local/skills`)
- `backup all` captures nodes that have an env profile (`agents/envs/<node>.env`) plus the same private orchestrator roots
- Node archives are intentionally lean: shared mirrors (`plugins/`, `scripts/`, `skills/`, `wiki/`, `cron/`), per-node runtime trees (`hermes-agent/`, `.runtime/`), and transient bloat (`.cache`, logs, request dump spillover) are excluded
- Backup now carries a single shared runtime seed (`runtime_seed/hermes-agent`, `runtime_seed/venv`, `runtime_seed/uv`) used to reseed nodes on restore
- Request dump cleanup runs before archive creation (`HERMES_REQUEST_DUMP_KEEP_LAST`, `HERMES_REQUEST_DUMP_KEEP_DAYS`)
- Backup retention is configurable via `HERMES_BACKUP_KEEP_LAST` (keep last N `horc-backup-*` archives; `0` disables)
- Restore reapplies whatever is present in the archive (`agents/*` and legacy memory/crons compatibility payloads)
- Restore reseeds node runtime from the shared runtime seed when per-node runtime folders are absent
- Stops included running nodes before restore and restarts those that were running

## Backup Automation (BRT)

- Default orchestrator cron payload: `/local/crons/orchestrator/backup_daily_brt.sh`
- Default schedule file: `/local/crons/orchestrator/backup_daily_brt.cron`
- Schedule: `0 0 * * *` at `America/Sao_Paulo` (00:00 BRT)
- Policy: backup all nodes, keep last 3 archives, prune old `request_dump_*`

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

See more: [horc command reference](docs/commands/horc.md)

Compatibility alias:

```bash
hord restart
```

`horc update <node>` is accepted as a compatibility alias for `horc agent update <node>`.

## Versioning Hygiene

Runtime and secret files are intentionally excluded:
- `.hermes/`, `agents/nodes/`, `crons/*` (except `README.md` and baseline orchestrator backup cron files), `plugins/private/memory/`, `logs/`, `plugins/private/`, `skills/`, `backups/`, `state/` (except docs/examples)
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
