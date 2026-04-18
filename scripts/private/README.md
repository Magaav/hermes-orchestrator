# Private Scripts

`/local/scripts/private` stores local-only operational scripts for this orchestrator instance.

## Why It Exists

This tree is intentionally separated from public framework code so deployment-specific behavior can evolve without polluting reusable orchestrator logic.

## Current Structure

- `backup/`: local backup/restore entrypoints used by compatibility wrappers and operational runbooks.

## Hermes-Orchestrator Integration

- Public wrappers in `/local/scripts/public/backup/` delegate to this folder.
- Runtime configuration for backup flows is loaded from `/local/scripts/private/backup/backup_nodes_to_gdrive.env`.

## Synergies With Other Modules

- `horc backup/restore` command flows are implemented in `/local/scripts/public/clone/clone_manager.py`.
- Discord slash backup handlers under `/local/plugins/public/discord/...` call the same backup core.
- Cron jobs that run backup routines are now centralized at `/local/crons`.

## See Also

- [`../README.md`](../README.md)
- [`../public/README.md`](../public/README.md)
- [`../../docs/features/scripts.md`](../../docs/features/scripts.md)
