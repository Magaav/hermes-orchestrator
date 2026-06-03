> Open-core agent infrastructure. Public local runtime. Commercial cloud/network layer in development.
> Open to incubation, accelerators, grants, strategic funding, infrastructure credits, sponsors, and pilot partners.

# Hermes Orchestrator
> Host-level control plane for running and managing fleets of containerized Hermes Agent nodes.
![Hermes Orchestrator Hero](docs/assets/hero.png)
**Quick Links:** [Prompt Guidelines](#prompt-guidelines) | [Install](#install) | [Core Concepts](#core-concepts) | [Node Lifecycle](#node-lifecycle) | [Logging Topology](#logging-topology) | [Feature Docs](#feature-docs) | [Command Reference](docs/commands/horc.md) | [Roadmap Workspace](#roadmap-workspace) | [Contributing](#contributing)

## Engineering Philosophy

Hermes Orchestrator, its plugins, and every agent working on this repo should
optimize for performance, efficiency, and simplicity.

- Performance: do less work per frame, per request, and per agent turn. Prefer
  event-driven updates, bounded loops, lazy loading, explicit refreshes, and
  measured hot-path fixes over decorative or speculative computation.
- Efficiency: spend tokens, CPU, memory, network, disk, and human attention
  deliberately. Give agents compact state and tools to fetch context on demand
  instead of resending large logs, files, screenshots, or transcripts by
  default.
- Simplicity: choose the smallest understandable design that can be verified
  and evolved. Prefer clear contracts, plugin-owned modules, reversible changes,
  and boring operational paths over clever hidden coupling.

This philosophy applies equally to terminal Codex work, Hermes Agent nodes,
the `wasm-agent` workspace/bridge integration, and the embedded agent. A powerful system
should feel calm: idle when nothing changed, precise when context is needed,
and explicit about what it is spending or doing.

## Prompt Guidelines

Use these rules before evolving this project:

- Let the engineering philosophy lead implementation choices: optimize for
  performance, efficiency, and simplicity before adding visual effects,
  background work, broad context, or new abstractions.
- Preserve compatibility with Hermes Agent mainline and Space Agent upstream. Future-proofing and version-update survivability are hard engineering goals.
- Prefer extension layers before core edits: Hermes Agent changes should use plugins, skills, tools, hooks, or components; Space Agent changes should use modules, customware bundles, extension points, or components.
- If a goal cannot be achieved through extension layers, pause implementation and design the smallest upstreamable Hermes Agent or Space Agent PR/seam before patching core. Do not let local product work drift into an unmaintainable fork by default.
- Treat `/local/plugins/wasm-agent` as the active product UI and bridge owner.
  New workspace, account, browser, topology, resources, and bridge work belongs
  there unless a task explicitly names a separate plugin.
- Keep generated/runtime state out of source changes unless a README or explicit migration note is being added at the parent level.
- Every code-changing commit must add or update a very fast regression test for
  the smallest behavior it could break, then run that focused test before the
  commit. Prefer existing smoke/unit checks that finish in seconds; if a change
  truly cannot be covered quickly, document the reason and add the smallest
  slower acceptance check that proves the risk.
- For long Space OS evolution runs, keep resumability as a first-class deliverable:
  update the active roadmap before or during each major direction change, commit
  stable checkpoints, and leave exact next actions in docs before context gets
  blurry.
- Treat the next action as durable handoff state, not chat memory. For ongoing
  product or roadmap work, update the relevant roadmap or plugin README with a
  short, explicit `Durable Next Step` before ending the turn. This entry should
  be concrete enough for a future agent to resume after context compaction
  without relying on the previous transcript.
- If context is lost or compacted, resume by reading this README, then
  `/local/docs/roadmap/README.md`, then
  `/local/docs/roadmap/space-os/README.md`, then the relevant plugin README.
  Inspect runtime/codeflow again before changing source, because current code
  truth wins over remembered intent. If a relevant `Durable Next Step` exists,
  reconcile it with the current code and make it the default next action unless
  the user gives a newer direction.
- During extended implementation, chain work in small verified steps:
  inspect, document the finding, implement the smallest plugin-owned change,
  verify, sync docs, commit, then continue from the roadmap's next action.
- After a verified stable checkpoint is committed, check whether the current
  branch is ahead of its upstream. Unless the user explicitly asked for
  local-only work or a separate PR branch, push the committed checkpoint to
  GitHub so repository browsing reflects the latest durable achievements.
- End every final agent response with a concrete proposed next step for the
  agent to run next. For ongoing product work, that final next step must match
  the durable handoff recorded in docs.

## Documentation Sync

Documentation is part of the runtime contract. It must describe the current software, not intended behavior, unless the section is explicitly labeled as roadmap, proposal, future work, risk, or open question.

When codeflow/runtime behavior and documentation disagree, inspect the current implementation and update the docs to match reality. If code is changed to match intended behavior, update the docs in the same change so they describe the new actual state. Any code CRUD change must include a docs-sync check before it is complete.

Before major wasm-agent, WASM browser, Space OS, or cloud-client evolution, treat documentation sync as a gate: prune or relabel stale claims, record partial or broken capabilities honestly, and make sure the roadmap can answer "what should we do now?"

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

**Hermes Agent** focuses on reasoning and tool execution inside a single runtime.
**Hermes Orchestrator** focuses on operating many Hermes runtimes safely and reliably.

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
- **Diff-synchronized checkpoints:** commit each agent-made code diff to the Hermes Orchestrator repository so every iteration stays durable and available for parallel model review.

## Install
Install the orchestrator:
```bash
curl -fsSL https://raw.githubusercontent.com/Magaav/hermes-orchestrator/main/scripts/install.sh | bash
```
Optional install parameters:
- -s --dir /local --branch main

What install does:
- Clones or updates this repo in `/local` by default
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
- `/local/agents/nodes/<node>/workspace/NODE_RUNTIME_CONTRACT.md`
This contract defines:
- node role (`orchestrator` vs `worker`)
- bootstrap mode (`NODE_STATE`)
- shared framework ownership (`/local/plugins/<standalone-plugin>`, `/local/scripts/public`)
- collaboration protocol for plugin/framework changes
- execution discipline for shared infrastructure changes
Operational rule:
- Worker nodes should treat shared plugins/scripts as orchestrator-managed infrastructure.
- Workers should propose changes (diff + rollout/rollback + verification), then request orchestrator execution.
- Orchestrator applies approved shared changes and coordinates restarts/verification.
At runtime, a condensed governance prompt is also injected via `HERMES_EPHEMERAL_SYSTEM_PROMPT` so agent decisions stay aligned with this contract.

Execution discipline for the orchestrator and any shared framework mutation:
- Think before acting: inspect current state first, make assumptions explicit, and surface blast radius before changing shared assets.
- Simplicity first: prefer the smallest reversible change that solves the problem; avoid speculative framework churn.
- Surgical changes: touch only the files required for the current task and avoid opportunistic refactors in shared infrastructure.
- Goal-driven execution: define success checks up front and require rollout steps, rollback trigger, and post-restart verification before claiming success.

## Filesystem Topology
```text
/local/
├── agents/
│   ├── registry.json             # canonical node inventory + runtime metadata + hermes-agent version snapshot
│   ├── envs/                     # used for bootstrapping/starting/restarting nodes
│   │   ├── orchestrator.env      # runs inside host VM
│   │   ├── node1.env             # runs inside docker container (sandboxed)
│   │   ├── node2.env             # runs inside docker container (sandboxed)
│   │   └── ...
│   └── nodes/                    # each node filesystem
│       ├── orchestrator/
│       │   ├── wiki              ->(symlink) /local/wiki
│       │   ├── workspace/        # default for node refining dump
│       │   ├── hermes-agent/     # copyed from /local/hermes-agent on bootstrap
│       │   ├── .hermes/          # node hermes-agent state
│       │   ├── scripts           ->(symlink) /local/scripts
│       │   ├── cron              ->(symlink) /local/crons/orchestrator
│       │   └── plugins           ->(symlink) /local/plugins
│       ├── node1/
│       │   ├── wiki/             # mounted from /local/wiki when wiki is enabled
│       │   ├── workspace/        # default for node refining dump
│       │   │   └── plugins/      # node-local plugin runtime/cache root
│       │   │       └── <plugin>/
│       │   │           └── cache/ # canonical mutable plugin state, for example discord-slash-commands
│       │   ├── hermes-agent/     # copyed from /local/hermes-agent on bootstrap
│       │   ├── .hermes/          # node hermes-agent state
│       │   ├── scripts/public/   # mounted from /local/scripts/public  (ro)
│       │   ├── scripts/private/  # mounted from /local/scripts/private (rw)
│       │   ├── plugins/          # host mount anchor; standalone plugin mounts overlay in runtime
│       │   └── cron/             # mounted from /local/crons/<node>
│       └── ...
├── hermes-agent/ # hermes-agent version used for spawning new nodes
├── scripts/      # scripts are used 
│   ├── public/   # canonical git-tracked script code
│   └── private/  # canonical local-only script state/entrypoints
├── crons/        # canonical node cron roots mounted at /local/agents/nodes/<node>/cron
├── native/       # wasm-agent native installer lanes; Windows x64 uses electron-builder NSIS and streams via /native/download
├── plugins/      # plugins are modifications applyed to each node hermes-agent core
│   ├── discord-slash-commands/ # canonical host plugin root for Discord slash UX/runtime ownership
│   ├── exhaust/                # canonical host plugin root for exhaust-mode behavior
│   ├── final-response-changed-files/ # canonical host plugin root for final response file summaries
│   └── wasm-agent/             # active WASM workspace/PWA and bridge plugin; local state lives under ./state/ (gitignored)
├── skills/       # canonical shared mutable skills pool
├── wiki/         # canonical shared mutable wiki root (gitignored)
├── datas/        # centralized private node data root (/local/datas/<node> mounted as /local/data)
├── backups/      # used for rollback/versioning
└── logs/         # nodes centralized debugging interface
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

`/local/agents/registry.json` is the orchestrator's canonical fleet inventory. It is derived operational state maintained by the clone manager during start, update, restore, and delete flows.

What it tracks:
- node identity and topology: `clone_name`, `clone_root`, `env_path`, `state_mode`, `state_code`
- runtime attachment: `container_name`, `container_id`, `runtime_type`, and `host_pid` for bare-metal nodes
- reconciliation time: `updated_at`
- per-node Hermes runtime version under `hermes_agent`

The `hermes_agent` block is for quick fleet auditing and includes:
- `package_version`
- `git_commit`
- `git_branch`
- `git_describe`
- `engines_node`

When a node runtime tree has no `.git` checkout, the version snapshot falls back to the bootstrap source recorded in `.clone-meta/bootstrap.json`.

Operational rule:
- do not hand-edit `registry.json` as configuration
- use it as the canonical answer to “which nodes are active?” and “which Hermes build is each node running?”
- remove stale entries when a node is removed from the fleet

## Versioned vs Local State

Versioned folders contain reviewed orchestrator code, docs, templates, and
standalone plugin packages. Local state folders contain deployment-specific
runtime data, generated checkouts, logs, caches, and secrets.

- `/local/scripts/public` contains shared git-tracked orchestrator tooling.
- `/local/scripts/private` contains local-only script state and entrypoints.
- `/local/plugins/discord-slash-commands` is a canonical git-tracked host plugin root that now owns Discord slash/governance runtime code.
- `/local/plugins/exhaust` and `/local/plugins/final-response-changed-files` are canonical git-tracked standalone plugin roots.
- `/local/plugins/wasm-agent/state` is the canonical gitignored local-development state root for the WASM Agent PWA pid/log state, wasm-agent-owned bridge state, account metadata, Timeline metadata, observation debug snapshots, and embedded assistant attachment assets. Cloud deployments must use a private `HERMES_WASM_AGENT_CLOUD_STATE_ROOT` outside this public repo.
- Mutable plugin state should prefer node-local cache roots under `/local/agents/nodes/<node>/workspace/plugins/<plugin>/cache` and, from inside the node runtime, `/local/workspace/plugins/<plugin>/cache`.
- `discord-slash-commands` no longer uses shared mutable state under `/local/plugins/private/discord`; its active runtime state is node-local and mirrored per shared Discord app+guild when needed.
- `/local/wiki` is the canonical shared mutable wiki root; legacy `/local/plugins/private/wiki` is migrated away when found.
- `/local/crons` is the canonical cron runtime root consumed by every node via `/local/agents/nodes/<node>/cron`.
- `/local/skills` is the shared mutable skills pool mounted across nodes.
- `/local/datas/<node>` is the canonical private node data root (mounted in runtime at `/local/data`) used to hold databases.

## Feature Docs
- [Guard Feature Guide](docs/features/guard.md)
- [Activity Timeline Guide](docs/features/activity-timeline.md)
- [Scripts Feature Guide](docs/features/scripts.md)
- [Plugins Feature Guide](docs/features/plugins.md)
- [horc Command Reference](docs/commands/horc.md)
- [Node Env Contract](docs/agents/node.env.md)
### horc Commands list
- [horc command reference](docs/commands/horc.md)

## Bootstrap
```bash
horc start
```
Default `horc start` target is `orchestrator` and it reads:
- `/local/agents/envs/orchestrator.env` (auto-created from `agents/envs/orchestrator.env.example` if missing)
- `/local/agents/nodes/orchestrator/`
- `NODE_TIME_ZONE` from each node env is mapped to runtime `HERMES_TIMEZONE` (for cron/schedule alignment)

Node env conventions and defaults are documented in [`agents/README.md`](agents/README.md).  
Strict bootstrap and minimum-operational env requirements are documented in [docs/agents/node.env.md](docs/agents/node.env.md).

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

## Logging Topology
- Node management/runtime/Hermes logs are centralized at `/local/logs/nodes/<node>/`.
- Node interaction timelines are centralized at `/local/logs/nodes/activities/<node>.jsonl`.
- Node skill mirrors are centralized at `/local/logs/nodes/<node>/skills/`.
- Warning-and-above mirrors are centralized at `/local/logs/attention/nodes/<node>/`.
- Guard doctor logs are centralized at `/local/logs/guard/`.
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
- Backup now carries a single shared runtime seed (`runtime_seed/hermes-agent`, `runtime_seed/venv`, `runtime_seed/uv`) used to reseed nodes on restore
- Request dump cleanup runs before archive creation (`HERMES_REQUEST_DUMP_KEEP_LAST`, `HERMES_REQUEST_DUMP_KEEP_DAYS`)

## Updates
```bash
# show update-specific help
horc update help
# refresh /local/hermes-agent, then reseed every node
horc update all
# same, but discard local /local/hermes-agent checkout changes first
horc update all --force
# refresh /local/hermes-agent, then reseed only one node
horc update node orchestrator
horc update node colmeio --force
```

Update behavior:
- Every update first refreshes `/local/hermes-agent` as a hard mirror of the configured upstream repo/branch.
- `horc update all` reseeds every node from `/local/hermes-agent` and reconciles `/local/agents/registry.json`.
- `horc update node <name>` reseeds only that node and also updates `/local/agents/registry.json`.
- Add `--force` when `/local/hermes-agent` has local checkout changes that should be discarded during the refresh.
- Update-driven reseeds preserve node-local `.hermes` state; the refresh targets code/runtime, not node identity.
- Nodes that were already running are restarted through the normal lifecycle. Stopped nodes keep their stopped state after reseed.

Manual reseed override:
- Set `NODE_RESEED=true` in `/local/agents/envs/<node>.env` to force a one-shot runtime reseed from `/local/hermes-agent` on the next start or restart.
- If `NODE_RESEED` is absent, it defaults to `false`.
- After a successful reseed, `horc` resets `NODE_RESEED=false` automatically.

Operational tip:
- Run `horc backup all` before a fleet-wide update if you want fresh rollback artifacts.
## Versioning Hygiene
Runtime and secret files are intentionally excluded:
- `.hermes/`, `agents/nodes/`, `crons/*` (except `README.md` and baseline orchestrator backup cron files), `logs/`, `plugins/private/`, `plugins/wasm-agent/state/` (except `.gitignore` and parent `README.md`), `wiki/`, `memory/`, `skills/`, `datas/`, `backups/` (except docs/examples)
- Real env files: `agents/envs/*.env`, `docker/.env`, `hermes-agent/.env`, root `.env`
- Orchestrator prestart patching runs against `agents/nodes/orchestrator/hermes-agent` (node-local runtime copy); the host `/local/hermes-agent` checkout stays on disk but out of git except `.gitkeep`.
Commit only templates/examples:
- `agents/envs/node.env.example`
- `agents/envs/orchestrator.env.example`
- `agents/README.md`
- docs and README files that describe versioned behavior
Pre-commit hook (`.githooks/pre-commit`) blocks common leaked paths and token patterns before commit.

## Roadmap
Roadmap work is intentionally tracked in dedicated docs to keep this README operational and implementation-focused.
Current roadmap themes:
- Visual control plane with Guard observability and per-agent activity timelines.
- Runtime guard monitoring, Discord alert routing, and bounded remediation.
- Shared knowledge and collaboration workflows for larger multi-node operations.
- Space OS pre-evolution sync, Space Agent module strategy, active WASM harness evolution, embedded agent-in-workspace observation/action path, image-card perception, and browser-engine R&D as background evidence.

## Roadmap Workspace
- [Roadmap Index](docs/roadmap/README.md)
- [Space OS Track](docs/roadmap/space-os/README.md)
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

GNU Affero General Public License v3.0 or later. See [LICENSE](LICENSE).

Commercial hosted services, managed deployments, wasm-agent-cloud infrastructure, premium connectors, private commercial layers, project names, logos, marks, and branding may be licensed or protected separately. See [COMMERCIAL.md](COMMERCIAL.md) and [TRADEMARK.md](TRADEMARK.md).

## Incubation, Funding & Strategic Support

Hermes Orchestrator / wasm-agent is an open-core effort to build local-first infrastructure for agent fleets, browser-backed workspaces, and shareable agentic artifacts.

The public repository focuses on the local runtime, orchestration layer, plugin contracts, security posture, developer-facing architecture, and documentation.

We are open to:

- incubators and accelerators
- open-source infrastructure programs
- AI infrastructure grants
- strategic funding
- infrastructure credits
- GitHub Sponsors
- design partners
- paid pilots
- commercial deployment conversations

Support helps accelerate:

- wasm-agent local runtime
- wasm-agent-cloud
- hosted browser workers
- shared-space relay
- artifact hosting
- cloud sync
- security hardening
- documentation, demos, and pilot deployments

Commercial hosted services, managed deployments, premium cloud resources, Flux Credits, and wasm-agent-cloud infrastructure may live outside this public repository.
The public repo should remain the open-core factory; per-instance wasm-agent-cloud databases, secrets, and user state belong to private deployment roots and can be archived with `horc space backup`.

The public `wasm-agent` plugin now includes the client-first People/direct-chat
foundation for that boundary: account friendship lifecycle metadata and
accepted-friend sync events are centralized only where identity/relay requires
it, while chat cache, unread state, emoji/sticker/reaction UI state, and recent
conversation history stay browser-local by default. Browser-local client-state
can also be exported/imported as an encrypted passphrase snapshot without
sending the passphrase or snapshot contents to the wasm-agent backend.

See:

- [Commercial Direction](./COMMERCIAL.md)
- [Incubation & Strategic Support](./INCUBATION.md)
- [Trademark Notice](./TRADEMARK.md)

For sponsorship, incubation, funding, credits, or partnership conversations:

- GitHub: https://github.com/Magaav
- LinkedIn: https://www.linkedin.com/in/vgenaro/
