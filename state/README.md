# State

`/local/state` is the boundary for deployment-specific orchestrator state.

Use this directory for local values and implementations that should **not** be published as reusable framework code.

## Contract

- Keep reusable/public automation under `/local/scripts/public` and `/local/plugins/public`.
- Keep deployment-private runtime state under `/local/scripts/private`, `/local/plugins/private`, and `/local/skills`.
- Keep machine-specific IDs, allowlists, recipients, and rollout variants under `/local/state`.
- Commit only `*.example` templates and documentation from `state/`.

## Current Usage

- `/local/state/orchestrator/backup_nodes_to_gdrive.env`: local runtime config for `/local/scripts/private/backup/backup_nodes_to_gdrive.sh` (untracked).
- `/local/state/orchestrator/backup_nodes_to_gdrive.env.example`: tracked template to bootstrap new environments.

## Migration Pattern

When a script is useful globally but implemented with local assumptions:

1. Keep the stable entrypoint in `/local/scripts/public`.
2. Point deployment-local implementations to `/local/scripts/private` when behavior is instance-specific.
3. Move local assumptions into a file under `/local/state/<scope>/`.
4. Track only the `.example` template and document required keys.
