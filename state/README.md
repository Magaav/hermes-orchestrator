# State

`/local/state` is the boundary for deployment-specific orchestrator state.

Use this directory for local values and implementations that should **not** be published as reusable framework code.

## Contract

- Keep reusable/public automation under `/local/agents/public/scripts` and `/local/agents/public/plugins`.
- Keep deployment-private runtime state under `/local/agents/private`.
- Keep machine-specific IDs, allowlists, recipients, and rollout variants under `/local/state`.
- Commit only `*.example` templates and documentation from `state/`.

## Current Usage

- `/local/state/orchestrator/backup_nodes_to_gdrive.env`: local runtime config for `/local/agents/private/scripts/backup/backup_nodes_to_gdrive.sh` (untracked).
- `/local/state/orchestrator/backup_nodes_to_gdrive.env.example`: tracked template to bootstrap new environments.

## Migration Pattern

When a script is useful globally but implemented with local assumptions:

1. Keep the stable entrypoint in `/local/scripts`.
2. Point that entrypoint to the canonical implementation under `/local/agents/private/scripts` when behavior is deployment-local.
3. Move local assumptions into a file under `/local/state/<scope>/`.
4. Track only the `.example` template and document required keys.
