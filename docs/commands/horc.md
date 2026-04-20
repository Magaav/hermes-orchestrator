# horc Command Reference

`horc` is the Hermes Orchestrator CLI for lifecycle, logs, backup/restore, and the guided one-node-at-a-time update flow.

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

## Guided Update Commands

```bash
horc update run <prod-node> --stage <stage-node> [--source-branch <branch>] [--deprecate-plugins <p1,p2,...>]
horc update validate <run-id> --phase stage|prod
horc update resume <run-id>
horc update status <run-id>
```

## Retired Update Commands

Older legacy update entrypoints are intentionally rejected. Operators should always start with `horc update run`.

## Notes

- `horc restart` with no node restarts all nodes in orchestrator-first order.
- `horc backup` produces lean archives and includes a shared runtime seed for reseeding nodes during restore.
- `horc restore` stops included running nodes, restores payloads, and restarts nodes that were running.
- `horc update run` is the only supported operator path for updates.
- Guided updates are one node at a time and require manual validation after stage and production.
- Update artifacts are written only under `/local/logs/update/<run-id>/`.
- Full runbook and troubleshooting guidance: [`update-engine.md`](/local/docs/commands/update-engine.md)

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
