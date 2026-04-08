# hermes-orchestrator

Hermes Orchestrator is the host-layer control plane for spawning and managing multiple Hermes agent nodes on demand.

## Goals

- Keep orchestrator state isolated under `/local/agents/nodes/orchestrator/.hermes` (no runtime dependency on `/local/.hermes`).
- Standardize node topology under `/local/agents/nodes/*`.
- Spawn worker nodes as Dockerized agents while keeping shared host assets (`scripts`, `plugins`, `crons`) consistent.
- Expose orchestration through:
  - Shell CLI (`horc`)
  - Discord-driven orchestration flows (via orchestrator gateway/plugin hooks)

## Topology

```text
/local/
├── agents/
│   ├── registry.json
│   ├── envs/
│   │   ├── orchestrator.env
│   │   ├── node1.env
│   │   └── ...
│   └── nodes/
│       ├── orchestrator/
│       │   ├── data/
│       │   ├── workspace/
│       │   ├── hermes-agent -> /local/hermes-agent
│       │   ├── .hermes/        # canonical orchestrator state
│       │   ├── scripts -> /local/scripts
│       │   ├── crons -> /local/crons/orchestrator
│       │   └── plugins -> /local/plugins
│       ├── node1/
│       │   ├── data/
│       │   ├── workspace/
│       │   ├── hermes-agent/
│       │   ├── .hermes/
│       │   ├── scripts/        # mounted from host (ro)
│       │   ├── crons/          # mounted from host node bucket
│       │   └── plugins/        # mounted from host (ro)
│       └── ...
├── hermes-agent/
├── scripts/
├── plugins/
├── memory/
│   └── openviking/
│       ├── orchestrator/
│       ├── node1/
│       └── ...
├── backups/
├── crons/
└── logs/
```

## Bootstrapping

Use `horc` as the primary entrypoint.

```bash
horc start
```

`horc start` (without a name) defaults to `orchestrator` and uses:

- `/local/agents/envs/orchestrator.env`
- `/local/agents/nodes/orchestrator/`

On first bootstrap, orchestrator state is migrated into `/local/agents/nodes/orchestrator/.hermes` from legacy locations (prefers `~/.hermes`, falls back to `/local/.hermes` when present).

If `horc` is not found:

```bash
/local/scripts/clone/horc.sh --help
```

and install a shell command wrapper:

```bash
bash /local/scripts/install.sh
```

## Node Lifecycle

```bash
# start/check orchestrator (host-layer)
horc start
horc status

# spawn/manage worker node (containerized)
horc start node1
horc status node1
horc logs node1 --lines 120
horc stop node1
```

Worker nodes run as Docker containers and are prepared to integrate with assets under `/local/docker/` and shared host resources.

Note on paths: inside worker containers, `HERMES_HOME=/local/.hermes` is expected and maps to host path `/local/agents/nodes/<node>/.hermes` (because each container mounts its node root at `/local`).

## Scripts

- Primary CLI wrapper: `/local/scripts/clone/horc.sh`
- Compatibility shim: `/local/scripts/clone.sh`
- Installer: `/local/scripts/install.sh` (installs `/usr/local/bin/horc`)

## Versioning Hygiene

- Runtime state directories are ignored via `.gitignore` (`agents/nodes`, `logs`, `memory`, `backups`, etc.).
- Real env files are ignored (`agents/envs/*.env`).
- Commit only env templates:
  - `agents/envs/orchestrator.env.example`
  - `agents/envs/catatau.env.example`
  - `agents/envs/colmeio.env.example`
