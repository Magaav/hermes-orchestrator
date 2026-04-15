# horc Command Reference

`horc` is the Hermes Orchestrator command surface for lifecycle, logs, backup/restore, and update flows.

## Defaults

- Default node for most commands: `orchestrator`
- Backup destination: `/local/backups`
- Restore path resolution: absolute path, or relative path under `/local/backups`

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
horc backup <name>          # convenience alias for one node
horc restore <path>
```

## Update Commands

```bash
horc update
horc agent update
horc agent update <name>
horc agent update [name] --source-branch <branch>
```

## Compatibility Aliases

```bash
hord <same horc args>
horc update <node>          # compatibility alias for: horc agent update <node>
```

## Notes

- `horc restart` with no node restarts all nodes in orchestrator-first order.
- `horc backup` produces a lean archive by excluding node-local mirrors and transient cache/log bloat.
- `horc backup all` includes nodes that have an env profile under `/local/agents/envs/*.env`; node dirs without env files are skipped.
- `horc restore` stops included running nodes, restores payloads, then restarts nodes that were running.

## Source of Truth

- CLI wrapper: `/local/scripts/public/clone/horc.sh`
- Engine: `/local/scripts/public/clone/clone_manager.py`
