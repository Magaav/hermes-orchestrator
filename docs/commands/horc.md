# horc Command Reference

`horc` is the Hermes Orchestrator CLI for lifecycle, logs, backup/restore, and simplified fleet updates.

## Defaults

- Default node for most lifecycle commands: `orchestrator`
- Backup destination: `/local/backups`
- Canonical update artifact root: `/local/logs/update`

## Lifecycle Commands

```bash
horc start [name]
horc status [name]
horc stop [name]
horc restart [all|name]
horc delete [name]
```

## Logs Commands

```bash
horc logs [name] [--lines N]
horc logs clean [name|all]
```

## Backup and Restore

```bash
horc backup all
horc backup node <name>
horc backup <name>
horc restore <path>
```

## Update Commands

```bash
horc update [help]
horc update all [--force]
horc update node <name> [--force]
```

## Notes

- `horc restart` with no node restarts all nodes in orchestrator-first order.
- `horc backup` produces lean archives and includes a shared runtime seed for reseeding nodes during restore.
- `horc restore` stops included running nodes, restores payloads, and restarts nodes that were running.
- Every update refreshes `/local/hermes-agent` as a hard mirror of the configured upstream repo/branch before reseeding nodes.
- `horc update all` reseeds every node and reconciles `/local/agents/registry.json`.
- `horc update node <name>` reseeds only the named node and leaves others untouched.
- Add `--force` to discard local `/local/hermes-agent` checkout changes when the upstream refresh would otherwise fail on a dirty working tree.
- Nodes that were already running are restarted through the normal lifecycle; stopped nodes keep their stopped state.
- `NODE_RESEED=true` in `/local/agents/envs/<node>.env` forces a one-shot reseed from `/local/hermes-agent` on the next start/restart.
- Update reports are written under `/local/logs/update/<run-id>/`.

## Governance

Every node receives a generated runtime contract at startup and restart:
- `/local/agents/nodes/<node>/.hermes/NODE_RUNTIME_CONTRACT.md`
- `/local/agents/nodes/<node>/workspace/NODE_RUNTIME_CONTRACT.md`

The clone manager also injects a condensed governance prompt through `HERMES_EPHEMERAL_SYSTEM_PROMPT` so live agent behavior stays aligned with the contract on each start.

Shared framework changes under `/local/plugins` and `/local/scripts` follow this execution discipline:
- Think before acting: inspect current state, state assumptions explicitly, and assess blast radius before editing shared assets.
- Simplicity first: prefer the smallest reversible change that solves the problem.
- Surgical changes: touch only the files required for the task and avoid unrelated refactors in shared infrastructure.
- Goal-driven execution: define success checks up front and require rollout, rollback, and post-restart verification for shared changes.

Operational implication:
- documentation-only changes to the generated contract files are not enough for a running node
- restart the affected node, usually with `horc restart <name>`, to load the updated injected governance prompt

## Source of Truth

- CLI wrapper: `/local/scripts/public/clone/horc.sh`
- Engine: `/local/scripts/public/clone/clone_manager.py`
- Fleet inventory: `/local/agents/registry.json`

## Registry Role

`/local/agents/registry.json` is the canonical operational inventory for orchestrated nodes. It is maintained by the clone manager and is intended for inspection, reconciliation, and version auditing.

Each node entry records:
- topology and identity: `clone_name`, `clone_root`, `env_path`, `state_mode`, `state_code`
- runtime attachment: `container_name`, `container_id`, `runtime_type`, and `host_pid` for bare-metal nodes
- reconciliation timestamp: `updated_at`
- Hermes runtime version metadata under `hermes_agent`

`hermes_agent` includes:
- `package_version`
- `git_commit`
- `git_branch`
- `git_describe`
- `engines_node`

If a node runtime tree does not keep a `.git` directory, the version snapshot falls back to the bootstrap source recorded in `.clone-meta/bootstrap.json`.

Operator guidance:
- treat `registry.json` as derived state, not declarative config
- use it to compare node versions before and after updates
- remove stale entries as part of node cleanup
