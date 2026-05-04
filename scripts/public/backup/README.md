# Public Backup Wrappers

`/local/scripts/public/backup` contains git-tracked compatibility entrypoints
for backup and restore commands.

## Current Scripts

- `backup_nodes_to_gdrive.sh`: execs
  `/local/scripts/private/backup/backup_nodes_to_gdrive.sh`.
- `restore_hermes_state.sh`: execs
  `/local/scripts/private/backup/restore_hermes_state.sh`.

## Change Rules

Keep deployment-specific credentials, destinations, and mutable backup behavior
in `/local/scripts/private/backup`. Public wrappers should stay thin and
documented so old runbooks keep working while private implementation details
remain local.
