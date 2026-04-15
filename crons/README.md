# Crons

`/local/crons` is the canonical shared cron root for Hermes Orchestrator nodes.

## Layout

- `/local/crons/<node>/`: node-specific cron jobs/scripts.
- `/local/agents/nodes/<node>/cron`: symlink mountpoint to the same node cron root.
- `/local/crons/orchestrator/backup_daily_brt.sh`: daily backup runner with retention (`keep last 3`) + request-dump pruning defaults.
- `/local/crons/orchestrator/backup_daily_brt.cron`: cron expression file (`0 0 * * *`) for `00:00` in `America/Sao_Paulo` (BRT).

## Why Top-Level

Cron visibility is now centralized so operators and UI surfaces can discover schedules without navigating inside `scripts/private`.

## Related Docs

- `/local/docs/features/scripts.md`
- `/local/docs/commands/horc.md`
