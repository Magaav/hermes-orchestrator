# Public Scripts

`/local/scripts/public` is the git-tracked script surface for Hermes Orchestrator.

## Public vs Private

- Public (`/local/scripts/public`): reusable orchestrator logic, safe to version and review.
- Private (`/local/scripts/private`): deployment-local operational scripts and stateful entrypoints.

## Main Entry Points

- `clone/horc.sh`: primary CLI wrapper (`horc`).
- `clone/hord.sh`: compatibility alias for `horc`.
- `clone/clone.sh`: compatibility alias to `horc`.
- `clone/clone_manager.py`: lifecycle engine for start/stop/status/logs/backup/restore/update.
- `install.sh`: bootstrap installer for orchestrator host setup.
- `backup/backup_nodes_to_gdrive.sh`: compatibility wrapper to private backup script.
- `backup/restore_hermes_state.sh`: compatibility wrapper to private restore script.
- `ui-gateway/run.py`: local HTTP/SSE gateway for the WASM UI experiment.

## Runtime Topology Synergy

- Shared script mounts into worker nodes come from:
  - `/local/scripts/public` (read-only)
  - `/local/scripts/private` (read-write)
- Node cron mounts come from `/local/crons/<node>` into `/local/agents/nodes/<node>/cron`.
- Plugin hooks under `/local/plugins/public` call this tree for lifecycle and backup automation.

## Common Commands

```bash
horc start
horc status
horc restart
horc logs clean
horc backup all
horc backup node node1
horc restore /local/backups/<archive>.tar.gz
horc update
horc agent update
```

See more: [`../../docs/commands/horc.md`](../../docs/commands/horc.md)

## Local State-Bound Setup

```bash
cp /local/state/orchestrator/backup_nodes_to_gdrive.env.example \
   /local/state/orchestrator/backup_nodes_to_gdrive.env
```

## See Also

- [`../README.md`](../README.md)
- [`../private/README.md`](../private/README.md)
- [`../../docs/features/scripts.md`](../../docs/features/scripts.md)
