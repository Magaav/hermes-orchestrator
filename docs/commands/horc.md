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

## Source of Truth

- CLI wrapper: `/local/scripts/public/clone/horc.sh`
- Engine: `/local/scripts/public/clone/clone_manager.py`
