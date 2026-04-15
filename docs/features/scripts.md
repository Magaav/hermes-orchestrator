# Scripts Feature

The scripts feature is the operational command and automation layer of Hermes Orchestrator.

## Canonical Roots

- Public scripts: `/local/scripts/public`
- Private scripts: `/local/scripts/private`
- Shared cron runtime: `/local/crons`

## Why It Is Segregated

- Public scripts stay versioned and reusable across environments.
- Private scripts keep deployment-specific runtime logic local.
- Cron state is elevated to `/local/crons` so node schedules are visible from a single top-level root.

## How Hermes-Orchestrator Uses It

- `horc` CLI wrapper: `/local/scripts/public/clone/horc.sh`
- Lifecycle engine: `/local/scripts/public/clone/clone_manager.py`
- Backup compatibility wrappers: `/local/scripts/public/backup/*.sh`
- Canonical local backup scripts: `/local/scripts/private/backup/*.sh`
- Orchestrator backup retention cron payload: `/local/crons/orchestrator/backup_daily_brt.sh`

Node mount behavior:

- `/local/scripts/public` is mounted read-only into worker containers.
- `/local/scripts/private` is mounted read-write into worker containers.
- `/local/crons/<node>` is mounted as node-local `/local/cron`.

## Synergy With Other Modules

- Plugins in `/local/plugins/public` call scripts for startup patching, backup dispatch, and lifecycle orchestration.
- Node profiles in `/local/agents/envs/*.env` configure script-driven behavior.
- `NODE_TIME_ZONE` from node env profiles aligns scheduler/runtime time (mapped to `HERMES_TIMEZONE`).
- Backup and restore workflows include script-private state plus shared cron roots.

## Related Docs

- [`../../scripts/README.md`](../../scripts/README.md)
- [`../commands/horc.md`](../commands/horc.md)
- [`plugins.md`](plugins.md)
